"""
RegimeAdapter – bridges the trained directional RegimeClassifier into live trading.

Periodically fetches recent OHLCV data, builds features, and classifies
the market regime (BULL / RANGING / BEAR). Exposes dynamic spacing/levels
that GridStrategy uses to adjust its grid parameters based on the detected
regime AND the model's confidence in its prediction.

Key improvements over the original:
  - Trains and predicts on the SAME instrument and timeframe
  - Direction-aware (BULL / RANGING / BEAR) instead of just trending/ranging
  - Confidence threshold: low-confidence predictions fall back to ranging
  - Smooth parameter blending to avoid abrupt grid changes
"""
import os
import time
import logging
import threading
import yfinance as yf
import pandas as pd

from .regime_model import (
    RegimeClassifier,
    REGIME_BEAR,
    REGIME_RANGING,
    REGIME_BULL,
    REGIME_UNKNOWN,
)
from .data_builder import build_features

log = logging.getLogger("QuantBot")


class RegimeAdapter:
    """
    Classifies market regime (BULL / RANGING / BEAR) and exposes
    strategy parameters tuned per regime.

    Usage::
        adapter = RegimeAdapter(config)
        adapter.start()       # begins background refresh thread
        # ... trading loop ...
        spacing = adapter.spacing
        levels  = adapter.levels
        adapter.stop()
    """

    # Public constants (for dashboard / other modules)
    UNKNOWN = REGIME_UNKNOWN
    BEAR = REGIME_BEAR
    RANGING = REGIME_RANGING
    BULL = REGIME_BULL

    # Minimum confidence to accept a non-RANGING prediction
    DEFAULT_CONFIDENCE_THRESHOLD = 0.45

    def __init__(self, config):
        self.config = config
        self.enabled = getattr(config, 'ML_ENABLED', False)

        # Current regime & confidence
        self._regime = self.UNKNOWN
        self._confidence = 0.0
        self._last_refresh = 0.0
        self._probabilities = {}

        # Dynamic parameters derived from regime
        self._spacing = float(getattr(config, 'GRID_SPACING', 0.5))
        self._levels = int(getattr(config, 'NUM_LEVELS', 3))

        # Previous regime (for smooth blending)
        self._prev_regime = self.UNKNOWN
        self._prev_spacing = self._spacing
        self._prev_levels = self._levels

        # Model
        self._model = None
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

        # Confidence threshold (can be overridden by config)
        self._conf_threshold = float(
            getattr(config, 'ML_CONFIDENCE_THRESHOLD', self.DEFAULT_CONFIDENCE_THRESHOLD)
        )

        if self.enabled:
            self._load_model()

    # ── Public properties ──────────────────────────────────────────

    @property
    def regime(self) -> int:
        """Current classified regime: UNKNOWN, BEAR, RANGING, or BULL."""
        return self._regime

    @property
    def regime_name(self) -> str:
        names = {
            self.UNKNOWN: "unknown",
            self.BEAR: "bear",
            self.RANGING: "ranging",
            self.BULL: "bull",
        }
        return names.get(self._regime, "unknown")

    @property
    def confidence(self) -> float:
        """Prediction probability (0..1) of the winning class."""
        return self._confidence

    @property
    def probabilities(self) -> dict:
        """Full probability distribution: {regime_label: prob}."""
        return dict(self._probabilities)

    @property
    def spacing(self) -> float:
        """Grid spacing recommended for the current regime."""
        return self._spacing

    @property
    def levels(self) -> int:
        """Number of grid levels recommended for the current regime."""
        return self._levels

    # ── Lifecycle ──────────────────────────────────────────────────

    def start(self):
        """Begin periodic background regime refreshes."""
        if not self.enabled:
            log.info("RegimeAdapter: ML disabled, using static grid parameters.")
            return
        if self._model is None:
            log.warning("RegimeAdapter: no trained model found, will use static grid.")
            return
        self._running = True
        self._thread = threading.Thread(target=self._refresh_loop, daemon=True)
        self._thread.start()
        log.info("RegimeAdapter: background refresh thread started.")

    def stop(self):
        self._running = False

    def refresh_now(self):
        """Force an immediate regime classification."""
        self._do_classify()

    # ── Internal ───────────────────────────────────────────────────

    def _load_model(self):
        # Always resolve model path relative to this file's directory
        # so it works regardless of CWD
        _ML_DIR = os.path.dirname(os.path.abspath(__file__))
        model_path = getattr(
            self.config, 'ML_MODEL_PATH',
            os.path.join(_ML_DIR, 'model.pkl')
        )
        # Make relative paths absolute relative to the ml/ directory
        if not os.path.isabs(model_path):
            # Strip any directory prefix (e.g. "ml/model.pkl" -> "model.pkl")
            # since _ML_DIR already includes "ml/"
            model_path = os.path.join(_ML_DIR, os.path.basename(model_path))
        try:
            self._model = RegimeClassifier.load(model_path)
            log.info(f"RegimeAdapter: loaded model from {model_path}")
        except Exception as e:
            self._model = None
            log.warning(f"RegimeAdapter: could not load model ({e}) – will not adapt.")

    def _refresh_loop(self):
        interval_min = getattr(self.config, 'ML_REFRESH_MINUTES', 60)
        self._do_classify()
        while self._running:
            time.sleep(interval_min * 60)
            self._do_classify()

    def _do_classify(self):
        if self._model is None:
            return

        try:
            bars = self._fetch_bars()
            if bars is None or bars.empty:
                log.warning("RegimeAdapter: no bars fetched, skipping classification.")
                return

            X, _ = build_features(
                bars,
                lookback=self._model.lookback,
                regime_threshold=self._model.regime_threshold,
            )
            if X.empty:
                log.warning("RegimeAdapter: not enough data for features.")
                return

            latest = X.iloc[-1:]

            # Use the classifier's confidence-aware prediction
            result = self._model.predict_with_confidence(latest)

            with self._lock:
                old_regime = self._regime
                self._prev_regime = old_regime
                self._regime = result['regime']
                self._confidence = result['confidence']
                self._probabilities = result['probabilities']
                self._update_params()
                self._last_refresh = time.time()

            # Log only on regime change or if confidence is low
            if old_regime != result['regime'] or result['uncertain']:
                prob_str = ", ".join(
                    f"{k}: {v:.2f}" for k, v in result['probabilities'].items()
                )
                log.info(
                    f"RegimeAdapter: regime={result['regime_name']} "
                    f"(conf={result['confidence']:.2f}, uncertain={result['uncertain']}) "
                    f"[{prob_str}] → spacing={self._spacing} levels={self._levels}"
                )
            else:
                log.debug(
                    f"RegimeAdapter: regime={result['regime_name']} "
                    f"confidence={result['confidence']:.2f}"
                )

        except Exception as e:
            log.error(f"RegimeAdapter: classification error: {e}")

    def _fetch_bars(self):
        """
        Fetch recent OHLCV bars from Yahoo Finance.

        Uses the same symbol and timeframe that the model was trained on.
        Default: GC=F (gold futures), 1h bars, 30 days to ensure enough data.
        """
        symbol = getattr(self.config, 'YAHOO_SYMBOL', 'GC=F')
        # Fetch enough bars for feature building + buffers
        # Need: lookback + lookback (target_lookahead) + ADX period (14) + margin
        required_bars = (self._model.lookback * 2) + 30 if self._model else 100
        # Use max(10d, 30d) to be safe
        period = "1mo"
        interval = "1h"

        df = yf.download(symbol, period=period, interval=interval, progress=False)
        if df.empty:
            return None

        # Flatten MultiIndex columns if present (yfinance format)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        df.rename(columns={
            'Open': 'open', 'High': 'high', 'Low': 'low',
            'Close': 'close', 'Volume': 'volume'
        }, inplace=True)

        if len(df) < required_bars:
            log.warning(
                f"RegimeAdapter: only {len(df)} bars fetched (need {required_bars}), "
                f"trying longer period..."
            )
            # Try 3 months of 1h data
            df = yf.download(symbol, period="3mo", interval="1h", progress=False)
            if df.empty:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
            df.rename(columns={
                'Open': 'open', 'High': 'high', 'Low': 'low',
                'Close': 'close', 'Volume': 'volume'
            }, inplace=True)

        return df

    def _update_params(self):
        """
        Map current regime to grid spacing/levels from config.

        Uses a blending approach: if confidence is moderate, blend
        regime-specific params with the default grid params.
        """
        c = self.config
        base_spacing = float(getattr(c, 'GRID_SPACING', 0.5))
        base_levels = int(getattr(c, 'NUM_LEVELS', 3))

        if self._regime == self.BULL:
            # Bull trend: wider spacing, fewer sell levels, prefer buy side
            regime_spacing = float(getattr(c, 'REGIME_SPACING_BULL', base_spacing * 2.0))
            regime_levels = int(getattr(c, 'REGIME_LEVELS_BULL', max(1, base_levels - 1)))
        elif self._regime == self.BEAR:
            # Bear trend: wider spacing, fewer buy levels, prefer sell side
            regime_spacing = float(getattr(c, 'REGIME_SPACING_BEAR', base_spacing * 2.0))
            regime_levels = int(getattr(c, 'REGIME_LEVELS_BEAR', max(1, base_levels - 1)))
        else:  # RANGING or UNKNOWN
            # Ranging: tight spacing, many levels (symmetric grid)
            regime_spacing = float(getattr(c, 'REGIME_SPACING_RANGING', base_spacing * 0.8))
            regime_levels = int(getattr(c, 'REGIME_LEVELS_RANGING', base_levels + 1))

        # Blend based on confidence
        # At low confidence → lean toward ranging params (conservative)
        # At high confidence → fully use regime-specific params
        blend = min(self._confidence / self._conf_threshold, 1.0) if self._conf_threshold > 0 else 0.5

        if self._regime in (self.BULL, self.BEAR):
            # Blend between regime-specific and default
            self._spacing = round(
                regime_spacing * blend + base_spacing * (1 - blend), 2
            )
            self._levels = max(1, round(
                regime_levels * blend + base_levels * (1 - blend)
            ))
        else:
            # Ranging – use ranging params directly (they are the conservative default)
            self._spacing = regime_spacing
            self._levels = regime_levels