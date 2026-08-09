"""
KronosBreakoutEnhancer – integrates Kronos foundation model forecasts into
BreakoutStrategy for trade filtering, confirmation weighting, and dynamic
TP/SL / threshold adjustment.

Provides
--------
- forecast_direction : 'BULLISH' | 'BEARISH' | 'NEUTRAL' — Kronos view on
  where price is heading over the forecast horizon.
- forecast_confidence : float (0–1) — trend_strength normalised, or 0 if
  Kronos is unavailable.
- volatility_mode : 'LOW' | 'MEDIUM' | 'HIGH' — volatility tercile based on
  forecast volatility, used for threshold / TP/SL scaling.
- adjust_breakout_threshold(base_threshold_pct) -> float — scales threshold
  by forecast volatility.
- adjust_tp_sl(tp_dollars, sl_dollars) -> (tp_dollars, sl_dollars) — scales
  TP/SL dollar amounts by forecast volatility.
- should_filter(side, direction_check=True) -> bool — True if the trade
  should be accepted based on Kronos forecast.

Usage::
    from ml.kronos import KronosBreakoutEnhancer

    enhancer = KronosBreakoutEnhancer(config, logger)
    enhancer.refresh()                    # fetch data + run forecast
    if enhancer.should_filter('buy'):
        ...  # proceed with entry
    tp, sl = enhancer.adjust_tp_sl([3,5,10], 3)
"""

import logging
import threading
import time
from typing import List, Optional, Tuple

import pandas as pd

from .config import (
    KRONOS_DEFAULT_SYMBOL,
    KRONOS_DEFAULT_INTERVAL,
    KRONOS_FETCH_PERIOD,
    KRONOS_PRED_LEN,
    KRONOS_TREND_STRENGTH_THRESHOLD,
    KRONOS_BREAKOUT_CONFIDENCE_MIN,
    KRONOS_BREAKOUT_FILTER_DIRECTION,
    KRONOS_BREAKOUT_VOL_ADJUST_THRESHOLD,
    KRONOS_BREAKOUT_DYNAMIC_TP_SL,
    KRONOS_BREAKOUT_BASE_VOL,
    KRONOS_BREAKOUT_REFRESH_SEC,
)

log = logging.getLogger("QuantBot")


class KronosBreakoutEnhancer:
    """
    Breakout-specific wrapper around the Kronos price predictor.

    Parameters
    ----------
    config : object
        QuantEnv config object (may override Kronos settings).
    logger : logging.Logger or None
        Logger instance.
    """

    # Volatility tercile boundaries (annualised).
    VOL_LOW_THRESHOLD = 0.08      # below this = LOW
    VOL_HIGH_THRESHOLD = 0.18     # above this = HIGH

    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger or log

        self._enabled = getattr(config, "KRONOS_BREAKOUT_ENABLED", False)

        # ── Forecast state ─────────────────────────────────────────────
        self.forecast_direction = "NEUTRAL"
        self.forecast_confidence = 0.0
        self.volatility_mode = "MEDIUM"
        self.forecast_volatility = 0.0
        self.forecast_trend = 0.0
        self.forecast_trend_strength = 0.0
        self.forecast_features = {}
        self._last_refresh_time = 0.0

        # ── Config overrides ───────────────────────────────────────────
        self._confidence_min = getattr(
            config, "KRONOS_BREAKOUT_CONFIDENCE_MIN", KRONOS_BREAKOUT_CONFIDENCE_MIN
        )
        self._filter_direction = getattr(
            config, "KRONOS_BREAKOUT_FILTER_DIRECTION", KRONOS_BREAKOUT_FILTER_DIRECTION
        )
        self._vol_adjust_threshold = getattr(
            config, "KRONOS_BREAKOUT_VOL_ADJUST_THRESHOLD", KRONOS_BREAKOUT_VOL_ADJUST_THRESHOLD
        )
        self._dynamic_tp_sl = getattr(
            config, "KRONOS_BREAKOUT_DYNAMIC_TP_SL", KRONOS_BREAKOUT_DYNAMIC_TP_SL
        )
        self._base_vol = getattr(config, "KRONOS_BREAKOUT_BASE_VOL", KRONOS_BREAKOUT_BASE_VOL)
        self._refresh_sec = getattr(
            config, "KRONOS_BREAKOUT_REFRESH_SEC", KRONOS_BREAKOUT_REFRESH_SEC
        )
        self._symbol = getattr(config, "SYMBOL", KRONOS_DEFAULT_SYMBOL)

        # Lazy-loaded Kronos predictor
        self._predictor = None

        # Background refresh thread
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

    # ── Public API ─────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        """Whether the Kronos breakout enhancer is enabled."""
        return self._enabled

    def start(self):
        """Begin background forecast refresh."""
        if not self._enabled:
            self.logger.info("KronosBreakoutEnhancer: disabled, no background refresh.")
            return
        self._running = True
        self._thread = threading.Thread(target=self._refresh_loop, daemon=True)
        self._thread.start()
        self.logger.info("KronosBreakoutEnhancer: background refresh started.")

    def stop(self):
        """Stop background refresh."""
        self._running = False
        self.logger.info("KronosBreakoutEnhancer: stopped.")

    def refresh(self, data: Optional[pd.DataFrame] = None):
        """
        Run a forecast and update all derived features.

        Parameters
        ----------
        data : pd.DataFrame or None
            OHLCV DataFrame with DatetimeIndex. If None, fetches live data
            via yfinance for the configured symbol.
        """
        if not self._enabled:
            return

        self._init_predictor()
        if not self._predictor.is_available():
            self.logger.warning("KronosBreakoutEnhancer: predictor not available — skipping refresh")
            return

        if data is None:
            data = self._fetch_data()

        if data is None or len(data) < 20:
            self.logger.warning("KronosBreakoutEnhancer: insufficient data — skipping refresh")
            return

        try:
            features = self._predictor.get_forecast_features(data)
        except Exception as e:
            self.logger.error(f"KronosBreakoutEnhancer: forecast failed ({e})")
            return

        with self._lock:
            self.forecast_features = features
            self.forecast_trend = features.get("trend", 0.0)
            self.forecast_trend_strength = features.get("trend_strength", 0.0)
            self.forecast_volatility = features.get("volatility_forecast", 0.0)

            # ── Forecast direction ─────────────────────────────────────
            ts = self.forecast_trend_strength
            if ts >= self._confidence_min:
                self.forecast_direction = "BULLISH" if self.forecast_trend > 0 else "BEARISH"
            else:
                self.forecast_direction = "NEUTRAL"

            # ── Confidence (0–1) — clamp trend_strength ────────────────
            self.forecast_confidence = min(max(ts, 0.0), 1.0)

            # ── Volatility mode (tercile) ──────────────────────────────
            vol = self.forecast_volatility
            if vol <= self.VOL_LOW_THRESHOLD:
                self.volatility_mode = "LOW"
            elif vol >= self.VOL_HIGH_THRESHOLD:
                self.volatility_mode = "HIGH"
            else:
                self.volatility_mode = "MEDIUM"

            self._last_refresh_time = time.time()

        self.logger.info(
            f"KronosBreakoutEnhancer: direction={self.forecast_direction} "
            f"confidence={self.forecast_confidence:.3f} "
            f"vol_mode={self.volatility_mode} "
            f"vol={self.forecast_volatility:.4f} "
            f"trend={self.forecast_trend:.4f}"
        )

    # ── Filtering / adjustment methods ──────────────────────────────

    def should_filter(self, side: str, direction_check: Optional[bool] = None) -> bool:
        """
        Whether a breakout trade in *side* should be allowed.

        Parameters
        ----------
        side : str
            'buy' or 'sell'.
        direction_check : bool or None
            Whether to enforce Kronos direction alignment. Falls back to
            the configured KRONOS_BREAKOUT_FILTER_DIRECTION.

        Returns
        -------
        bool — True if the trade can proceed, False if it should be skipped.
        """
        if not self._enabled:
            return True

        direction_check = self._filter_direction if direction_check is None else direction_check

        with self._lock:
            # If confidence too low, let the trade proceed but flag as low-conviction.
            if self.forecast_confidence < self._confidence_min:
                return True  # no filter — just low conviction

            if not direction_check:
                return True  # not filtering by direction

            # Direction alignment check
            if side == 'buy' and self.forecast_direction == "BEARISH":
                self.logger.info(
                    f"KronosBreakoutEnhancer: BLOCKING buy — Kronos forecast is "
                    f"{self.forecast_direction} (confidence={self.forecast_confidence:.3f})"
                )
                return False

            if side == 'sell' and self.forecast_direction == "BULLISH":
                self.logger.info(
                    f"KronosBreakoutEnhancer: BLOCKING sell — Kronos forecast is "
                    f"{self.forecast_direction} (confidence={self.forecast_confidence:.3f})"
                )
                return False

            return True

    def adjust_breakout_threshold(self, base_threshold_pct: float) -> float:
        """
        Scale the breakout threshold by forecast volatility.

        High vol -> wider threshold (fewer false breakouts).
        Low vol  -> narrower threshold (more sensitive).

        Parameters
        ----------
        base_threshold_pct : float
            Base threshold as a decimal (e.g. 0.0005 for 0.05 %).

        Returns
        -------
        float — adjusted threshold (clamped to [0.5x, 3x] of base).
        """
        if not self._enabled or not self._vol_adjust_threshold:
            return base_threshold_pct

        with self._lock:
            vol = self.forecast_volatility
            if vol <= 0.0:
                return base_threshold_pct

        # vol vs base_vol ratio
        ratio = vol / self._base_vol
        ratio = max(0.5, min(3.0, ratio))
        return base_threshold_pct * ratio

    def adjust_tp_sl(
        self, tp_dollars: List[float], sl_dollars: float
    ) -> Tuple[List[float], float]:
        """
        Scale TP/SL dollar amounts by forecast volatility.

        Higher vol -> wider TP/SL (account for noise).
        Lower vol  -> tighter TP/SL.

        Parameters
        ----------
        tp_dollars : list of float
            TP levels in dollars.
        sl_dollars : float
            Stop loss in dollars.

        Returns
        -------
        (tp_dollars, sl_dollars) – adjusted values, clamped to [0.5x, 2x].
        """
        if not self._enabled or not self._dynamic_tp_sl:
            return list(tp_dollars), sl_dollars

        with self._lock:
            vol = self.forecast_volatility
            if vol <= 0.0:
                return list(tp_dollars), sl_dollars

        ratio = vol / self._base_vol
        ratio = max(0.5, min(2.0, ratio))

        adjusted_tp = [round(tp * ratio, 2) for tp in tp_dollars]
        adjusted_sl = round(sl_dollars * ratio, 2)
        return adjusted_tp, max(adjusted_sl, 0.5)  # never below $0.50

    # ── Status helper ──────────────────────────────────────────────────

    def status_str(self) -> str:
        """Return a short status string for logging / dashboard."""
        if not self._enabled:
            return "Kronos=disabled"

        with self._lock:
            return (
                f"Kronos={self.forecast_direction[0]}"
                f" conf={self.forecast_confidence:.2f}"
                f" vol={self.volatility_mode}"
            )

    def get_forecast_summary(self) -> dict:
        """Return a dict of forecast features for logging / dashboard."""
        with self._lock:
            return {
                "enabled": self._enabled,
                "direction": self.forecast_direction,
                "confidence": self.forecast_confidence,
                "volatility_mode": self.volatility_mode,
                "volatility": self.forecast_volatility,
                "trend": self.forecast_trend,
                "trend_strength": self.forecast_trend_strength,
                "last_refresh": self._last_refresh_time,
            }

    # ── Internal ───────────────────────────────────────────────────────

    def _init_predictor(self):
        """Lazy-init the KronosPricePredictor."""
        if self._predictor is None:
            from .predictor import KronosPricePredictor

            device = getattr(self.config, "DEVICE", None)
            self._predictor = KronosPricePredictor(device=device)

    def _fetch_data(self) -> Optional[pd.DataFrame]:
        """Fetch OHLCV data for the configured symbol via yfinance."""
        interval = getattr(self.config, "KRONOS_INTERVAL", KRONOS_DEFAULT_INTERVAL)
        period = KRONOS_FETCH_PERIOD

        self.logger.info(
            f"KronosBreakoutEnhancer: downloading {self._symbol} ({interval}, {period})"
        )
        import yfinance as yf

        try:
            ticker = yf.Ticker(self._symbol)
            df = ticker.history(period=period, interval=interval)
            if df.empty:
                self.logger.warning(f"KronosBreakoutEnhancer: no data for {self._symbol}")
                return None
            df.columns = [c.lower() for c in df.columns]
            for col in ["open", "high", "low", "close"]:
                if col not in df.columns:
                    self.logger.error(f"KronosBreakoutEnhancer: missing column '{col}'")
                    return None
            if "volume" not in df.columns:
                df["volume"] = 0
            return df
        except Exception as e:
            self.logger.error(f"KronosBreakoutEnhancer: yfinance error ({e})")
            return None

    def _refresh_loop(self):
        """Background loop: refresh forecast periodically."""
        # Do an initial refresh immediately
        self.refresh()
        while self._running:
            time.sleep(self._refresh_sec)
            self.refresh()