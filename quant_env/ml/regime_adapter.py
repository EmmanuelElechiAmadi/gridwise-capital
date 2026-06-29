"""
RegimeAdapter – bridges the trained RegimeClassifier into live trading.

Periodically fetches recent OHLCV data, builds features, and classifies
the market regime (trending vs ranging). Exposes dynamic spacing/levels
that GridStrategy uses to adjust its grid parameters.
"""
import os
import time
import logging
import threading
import yfinance as yf
import pandas as pd

from .regime_model import RegimeClassifier
from .data_builder import build_features

log = logging.getLogger("QuantBot")


class RegimeAdapter:
    """
    Classifies market regime and exposes strategy parameters tuned per regime.

    Usage::
        adapter = RegimeAdapter(config)
        adapter.start()       # begins background refresh thread
        # ... trading loop ...
        spacing = adapter.spacing
        levels  = adapter.levels
        adapter.stop()
    """

    UNKNOWN = -1   # not yet classified
    RANGING = 0
    TRENDING = 1

    def __init__(self, config):
        self.config = config
        self.enabled = getattr(config, 'ML_ENABLED', False)

        # Current regime & confidence (populated after first prediction)
        self._regime = self.UNKNOWN
        self._confidence = 0.0
        self._last_refresh = 0.0

        # Dynamic parameters derived from regime (with defaults)
        self._spacing = float(getattr(config, 'GRID_SPACING', 0.5))
        self._levels = int(getattr(config, 'NUM_LEVELS', 3))

        # Model
        self._model = None
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

        if self.enabled:
            self._load_model()

    # ── Public properties ──────────────────────────────────────────

    @property
    def regime(self) -> int:
        """Current classified regime: UNKNOWN, RANGING, or TRENDING."""
        return self._regime

    @property
    def regime_name(self) -> str:
        return {self.UNKNOWN: "unknown", self.RANGING: "ranging",
                self.TRENDING: "trending"}.get(self._regime, "unknown")

    @property
    def confidence(self) -> float:
        """Prediction probability (0..1). 0 if unknown."""
        return self._confidence

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
        model_path = getattr(self.config, 'ML_MODEL_PATH',
                             os.path.join(os.path.dirname(__file__), 'model.pkl'))
        try:
            self._model = RegimeClassifier.load(model_path)
            log.info(f"RegimeAdapter: loaded model from {model_path}")
        except Exception as e:
            self._model = None
            log.warning(f"RegimeAdapter: could not load model ({e}) – will not adapt.")

    def _refresh_loop(self):
        interval_min = getattr(self.config, 'ML_REFRESH_MINUTES', 60)
        # Classify immediately on start
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

            X, _ = build_features(bars,
                                  lookback=self._model.lookback,
                                  adx_threshold=self._model.threshold)
            if X.empty:
                log.warning("RegimeAdapter: not enough data for features.")
                return

            # Get the most recent feature vector
            latest = X.iloc[-1:]

            # Align columns to training features
            missing = [c for c in self._model.features if c not in latest.columns]
            extra = [c for c in latest.columns if c not in self._model.features]
            if missing:
                log.warning(f"RegimeAdapter: missing features {missing}, skipping.")
                return
            latest = latest[self._model.features]

            pred = self._model.model.predict(latest)[0]
            proba = self._model.model.predict_proba(latest)[0]
            confidence = max(proba)

            with self._lock:
                old_regime = self._regime
                self._regime = pred
                self._confidence = confidence
                self._update_params()
                self._last_refresh = time.time()

            if old_regime != pred:
                log.info(
                    f"RegimeAdapter: regime changed {self.regime_name} "
                    f"(confidence {confidence:.2f}) → spacing={self._spacing} "
                    f"levels={self._levels}"
                )
            else:
                log.debug(
                    f"RegimeAdapter: regime={self.regime_name} confidence={confidence:.2f} "
                    f"spacing={self._spacing} levels={self._levels}"
                )

        except Exception as e:
            log.error(f"RegimeAdapter: classification error: {e}")

    def _fetch_bars(self):
        """Fetch recent OHLCV bars from Yahoo Finance."""
        symbol = getattr(self.config, 'YAHOO_SYMBOL', 'GC=F')
        # Fetch enough bars for feature building (lookback + some margin)
        lookback = self._model.lookback if self._model else 20
        # 1h bars: need at least lookback + 14 (ADX period) + some buffer ≈ 50
        # Use 5d of 1h data to be safe
        df = yf.download(symbol, period="5d", interval="1h", progress=False)
        if df.empty:
            return None
        # Flatten MultiIndex columns if present (yfinance format)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df.rename(columns={
            'Open': 'open', 'High': 'high', 'Low': 'low',
            'Close': 'close', 'Volume': 'volume'
        }, inplace=True)
        return df

    def _update_params(self):
        """Map current regime to grid spacing/levels from config."""
        c = self.config
        base_spacing = float(getattr(c, 'GRID_SPACING', 0.5))
        base_levels = int(getattr(c, 'NUM_LEVELS', 3))
        if self._regime == self.TRENDING:
            self._spacing = float(getattr(c, 'REGIME_SPACING_TRENDING', base_spacing * 2))
            self._levels = int(getattr(c, 'REGIME_LEVELS_TRENDING', max(1, base_levels // 2)))
        else:  # RANGING or UNKNOWN
            self._spacing = float(getattr(c, 'REGIME_SPACING_RANGING', base_spacing))
            self._levels = int(getattr(c, 'REGIME_LEVELS_RANGING', base_levels))
