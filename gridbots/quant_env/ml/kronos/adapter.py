"""
KronosRegimeAdapter – plugs the Kronos foundation model forecast into the
existing QuantEnv regime-detection / grid-adaptation pipeline.

Acts as a drop-in replacement or complement to the RF-based RegimeAdapter.
When attached to GridStrategy, it provides:
  - regime (int): REGIME_BULL / BEAR / RANGING derived from Kronos forecast
  - regime_name (str): human-readable name
  - spacing (float): grid spacing adjusted by forecast volatility
  - levels (int): number of grid levels adjusted by forecast trend strength
  - forecast_features (dict): raw Kronos forecast data for logging/analysis

NEW in this version:
  - Multi-symbol support: manages per-symbol predictors for independent forecasting
  - predict_batch(): parallel multi-asset forecasts using ThreadPoolExecutor
  - Portfolio integration: per-symbol volatility/trend fed into PortfolioOptimizer

Constructor signature matches the RF adapter signature:
    adapter = KronosRegimeAdapter(config, logger)
    adapter.start()         # begin background refresh loop
    adapter.update(data)   -> None  (immediate sync update)
    adapter.regime         -> int
    adapter.regime_name    -> str
    adapter.spacing        -> float
    adapter.levels         -> int
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

import pandas as pd

from .config import (
    KRONOS_DEFAULT_SYMBOL,
    KRONOS_DEFAULT_INTERVAL,
    KRONOS_FETCH_PERIOD,
    KRONOS_PRED_LEN,
    KRONOS_TREND_STRENGTH_THRESHOLD,
    KRONOS_VOL_WINDOW,
    KRONOS_SYMBOLS,
    KRONOS_PARALLEL_FETCH,
    KRONOS_PARALLEL_WORKERS,
)

log = logging.getLogger("QuantBot")


class KronosRegimeAdapter:
    """
    Regime adapter that uses the Kronos foundation model for forward-looking
    market regime classification.

    Supports both single-symbol and multi-symbol modes.

    Parameters
    ----------
    config : object
        Global QuantEnv config (may override Kronos settings).
    logger : object
        Logger instance (may be None).
    """

    REGIME_RANGING = 0
    REGIME_BULL = 1
    REGIME_BEAR = -1
    UNKNOWN = 2  # compatibility alias; Kronos always has a prediction

    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger or log

        self._enabled = getattr(config, "KRONOS_ENABLED", False)
        self._regime = self.REGIME_RANGING
        self._regime_name = "RANGING"
        self._spacing = getattr(config, "GRID_SPACING", 80.0)
        self._levels = getattr(config, "NUM_LEVELS", 8)

        # Kronos forecast features for primary symbol (updated on each call to update())
        self.forecast_features = {}

        # ── Multi-symbol state (Item 6) ─────────────────────────────────
        # Per-symbol predictors: {symbol: KronosPricePredictor}
        self._symbol_predictors: Dict[str, object] = {}
        # Per-symbol forecast features: {symbol: dict}
        self.symbol_forecasts: Dict[str, dict] = {}
        # Resolve the list of symbols to track
        symbols_cfg = getattr(config, "KRONOS_SYMBOLS", KRONOS_SYMBOLS)
        if symbols_cfg and isinstance(symbols_cfg, str):
            symbols_cfg = [s.strip() for s in symbols_cfg.split(",") if s.strip()]
        elif not symbols_cfg:
            symbols_cfg = [KRONOS_DEFAULT_SYMBOL]
        self._symbols: List[str] = list(symbols_cfg) if symbols_cfg else [KRONOS_DEFAULT_SYMBOL]
        self._parallel_fetch = getattr(config, "KRONOS_PARALLEL_FETCH", KRONOS_PARALLEL_FETCH)
        self._parallel_workers = getattr(config, "KRONOS_PARALLEL_WORKERS", KRONOS_PARALLEL_WORKERS)

        # Base grid spacing from config (used as reference)
        self._base_spacing = self._spacing
        self._base_levels = self._levels

        # Lazy-loaded predictor for primary symbol
        self._predictor = None

        # ── Background refresh state ────────────────────────────────────
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._last_refresh = 0.0

    # ── Properties ─────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        """Whether the Kronos adapter is enabled."""
        return self._enabled

    @property
    def regime(self) -> int:
        """Current regime as int (BULL=1, RANGING=0, BEAR=-1)."""
        with self._lock:
            return self._regime

    @property
    def regime_name(self) -> str:
        """Human-readable regime name."""
        with self._lock:
            return self._regime_name

    @property
    def spacing(self) -> float:
        """Effective grid spacing, adjusted for forecast volatility."""
        with self._lock:
            return self._spacing

    @property
    def levels(self) -> int:
        """Effective number of grid levels, adjusted for trend strength."""
        with self._lock:
            return self._levels

    @property
    def confidence(self) -> float:
        """Compatibility property – returns trend_strength as a pseudo-confidence."""
        return self.forecast_features.get("trend_strength", 0.0)

    @property
    def symbols(self) -> List[str]:
        """List of symbols tracked by this adapter."""
        return list(self._symbols)

    # ── Lifecycle: background refresh (mirrors RegimeAdapter pattern) ──

    def start(self):
        """Begin periodic background regime refreshes."""
        if not self._enabled:
            self.logger.info("Kronos adapter: disabled, no background refresh.")
            return
        self._running = True
        self._thread = threading.Thread(target=self._refresh_loop, daemon=True)
        self._thread.start()
        self.logger.info(f"Kronos adapter: background refresh thread started. Symbols={self._symbols}")

    def stop(self):
        """Stop the background refresh thread."""
        self._running = False
        self.logger.info("Kronos adapter: background refresh stopped.")

    def refresh_now(self):
        """Force an immediate regime classification (compatibility method)."""
        self.update()

    def _refresh_loop(self):
        """Background loop: classify immediately, then every KRONOS_REFRESH_MINUTES."""
        self.update()
        interval_sec = (
            getattr(self.config, "KRONOS_REFRESH_MINUTES", 30) * 60
        )
        while self._running:
            time.sleep(interval_sec)
            self.update()

    # ── Public update API ──────────────────────────────────────────────

    def update(self, data=None):
        """
        Run the Kronos forecast on the primary symbol AND any additional
        symbols configured in KRONOS_SYMBOLS.

        Derives regime/spacing/levels from the primary symbol.

        Parameters
        ----------
        data : pd.DataFrame or None
            OHLCV DataFrame with DatetimeIndex for the PRIMARY symbol.
            If None, fetches live data for all symbols.
        """
        self._init_predictor()
        if not self._predictor.is_available():
            self.logger.warning("Kronos adapter: predictor not available — keeping default regime/spacing")
            return

        # Run forecasts for all symbols
        self._forecast_all_symbols(data)

        # Derive primary symbol regime/spacing/levels from primary symbol forecast
        self._derive_from_primary()

    # ── Multi-symbol forecasting (Item 6) ──────────────────────────────

    def _forecast_all_symbols(self, primary_data=None):
        """
        Fetch data and run Kronos forecasts for all configured symbols.

        Uses ThreadPoolExecutor for parallel fetching/forecasting when
        configured with multiple symbols.
        """
        # Build fetch-target list: all symbols that need data
        fetch_symbols = list(self._symbols)

        if len(fetch_symbols) == 1:
            # Single symbol: use existing logic
            symbol = fetch_symbols[0]
            df = primary_data
            if df is None:
                try:
                    df = self._fetch_symbol_data(symbol)
                except Exception as e:
                    self.logger.error(f"Kronos adapter: data fetch failed for {symbol} ({e})")
                    return
            if df is not None and len(df) >= 20:
                features = self._run_forecast(df, symbol)
                with self._lock:
                    self.forecast_features = features
                    self.symbol_forecasts[symbol] = features
            return

        # ── Multi-symbol: parallel fetch and forecast ──────────────────
        self.logger.info(
            f"Kronos adapter: running forecasts for {len(fetch_symbols)} symbols: {fetch_symbols}"
        )

        # For the primary symbol, reuse provided data if given
        primary_sym = fetch_symbols[0]
        data_map = {}
        if primary_data is not None:
            data_map[primary_sym] = primary_data

        # Fetch data in parallel for all symbols that don't have data yet
        with ThreadPoolExecutor(max_workers=self._parallel_workers) as executor:
            future_map = {}
            for sym in fetch_symbols:
                if sym in data_map:
                    continue
                future = executor.submit(self._fetch_symbol_data, sym)
                future_map[future] = sym

            for future in as_completed(future_map):
                sym = future_map[future]
                try:
                    df = future.result()
                    if df is not None and len(df) >= 20:
                        data_map[sym] = df
                    else:
                        self.logger.warning(f"Kronos adapter: insufficient data for {sym}")
                except Exception as e:
                    self.logger.error(f"Kronos adapter: fetch failed for {sym}: {e}")

        # Run forecasts in parallel
        forecasts = {}
        with ThreadPoolExecutor(max_workers=self._parallel_workers) as executor:
            future_map = {}
            for sym, df in data_map.items():
                future = executor.submit(self._run_forecast, df, sym)
                future_map[future] = sym

            for future in as_completed(future_map):
                sym = future_map[future]
                try:
                    features = future.result()
                    if features:
                        forecasts[sym] = features
                except Exception as e:
                    self.logger.error(f"Kronos adapter: forecast failed for {sym}: {e}")

        # Store results
        with self._lock:
            self.symbol_forecasts = forecasts
            # Primary symbol forecast is the main forecast_features
            if primary_sym in forecasts:
                self.forecast_features = forecasts[primary_sym]
            elif forecasts:
                # Fallback to first available
                first_sym = list(forecasts.keys())[0]
                self.forecast_features = forecasts[first_sym]

    def _fetch_symbol_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV data for a specific symbol from yfinance.

        Parameters
        ----------
        symbol : str
            Yahoo Finance symbol (e.g. "GC=F", "SI=F", "CL=F").

        Returns
        -------
        pd.DataFrame or None
        """
        max_context = getattr(self._predictor, "max_context", 512)
        interval = getattr(self.config, "KRONOS_INTERVAL", KRONOS_DEFAULT_INTERVAL)
        period = KRONOS_FETCH_PERIOD

        self.logger.info(f"Kronos adapter: downloading {symbol} ({interval}, {period}) via yfinance")
        import yfinance as yf

        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval)
            if df.empty:
                self.logger.warning(f"Kronos adapter: no data for {symbol}")
                return None
            df.columns = [c.lower() for c in df.columns]
            for col in ["open", "high", "low", "close"]:
                if col not in df.columns:
                    self.logger.error(f"Kronos adapter: missing column '{col}' in {symbol} data")
                    return None
            if "volume" not in df.columns:
                df["volume"] = 0
            return df
        except Exception as e:
            self.logger.error(f"Kronos adapter: yfinance error for {symbol}: {e}")
            return None

    def _run_forecast(self, df: pd.DataFrame, symbol: str) -> dict:
        """
        Run Kronos forecast on a single symbol's data.

        Uses the per-symbol predictor (lazy-initialized) to avoid model reloads.
        If an IncrementalInferenceEngine is attached (via _incremental_engine),
        uses it to avoid re-encoding the full context window.

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV data.
        symbol : str
            Symbol name (for per-symbol predictor tracking).

        Returns
        -------
        dict of forecast features, or empty dict on failure.
        """
        # Ensure per-symbol predictor exists
        if symbol not in self._symbol_predictors:
            from .predictor import KronosPricePredictor

            device = getattr(self.config, "DEVICE", None)
            self._symbol_predictors[symbol] = KronosPricePredictor(device=device)

        predictor = self._symbol_predictors[symbol]
        if not predictor.is_available():
            self.logger.warning(f"Kronos adapter: predictor not available for {symbol}")
            return {}

        try:
            # ── Incremental inference (Item 9) ──────────────────────────
            # If an IncrementalInferenceEngine is attached, use it instead
            # of the raw predictor to avoid re-encoding the full context.
            engine = getattr(self, '_incremental_engine', None)
            if engine is not None and hasattr(engine, 'get_forecast_features'):
                engine.predict(df)  # ensures cached forecast is up-to-date
                features = engine.get_forecast_features(df)
            else:
                features = predictor.get_forecast_features(df)
            features["symbol"] = symbol
            return features
        except Exception as e:
            self.logger.error(f"Kronos adapter: forecast error for {symbol}: {e}")
            return {}

    def predict_batch(self) -> Dict[str, dict]:
        """
        Return the latest per-symbol forecasts.

        Returns
        -------
        dict of {symbol: forecast_features_dict}
        """
        with self._lock:
            return dict(self.symbol_forecasts)

    # ── Regime/spacing derivation from primary symbol ──────────────────

    def _derive_from_primary(self):
        """Derive regime, spacing, and levels from the primary symbol forecast features."""
        features = self.forecast_features
        if not features:
            return

        kronos_label = features.get("regime_label", "RANGING")
        trend_strength = features.get("trend_strength", 0.0)

        with self._lock:
            if trend_strength >= KRONOS_TREND_STRENGTH_THRESHOLD:
                if kronos_label == "BULL":
                    self._regime = self.REGIME_BULL
                    self._regime_name = "BULL"
                elif kronos_label == "BEAR":
                    self._regime = self.REGIME_BEAR
                    self._regime_name = "BEAR"
                else:
                    trend = features.get("trend", 0.0)
                    self._regime = self.REGIME_BULL if trend > 0 else self.REGIME_BEAR
                    self._regime_name = "BULL" if trend > 0 else "BEAR"
            else:
                self._regime = self.REGIME_RANGING
                self._regime_name = "RANGING"

            # ── Adjust grid spacing based on forecast volatility ────────
            vol_forecast = features.get("volatility_forecast", 0.01)
            vol_multiplier = max(0.5, min(3.0, vol_forecast * 100))
            self._spacing = round(self._base_spacing * vol_multiplier, 2)

            # ── Adjust grid levels based on trend strength ──────────────
            strength = min(trend_strength, 2.0)
            levels_multiplier = 1.0 - (strength * 0.3)
            levels_multiplier = max(0.4, min(1.5, levels_multiplier))
            self._levels = max(3, round(self._base_levels * levels_multiplier))

        self.logger.info(
            f"Kronos adapter: regime={self._regime_name} "
            f"spacing={self._spacing} levels={self._levels} "
            f"vol_forecast={vol_forecast:.4f} trend_strength={trend_strength:.3f}"
        )

    # ── Portfolio integration helper (Item 6) ──────────────────────────

    def get_portfolio_inputs(self) -> Dict[str, dict]:
        """
        Build per-symbol volatility/trend data for PortfolioOptimizer.

        Returns a dict mapping each symbol to:
        {
            'volatility': float,   # forecast volatility (annualised)
            'trend': float,        # forecast trend (return over horizon)
            'regime': str,         # 'BULL' / 'BEAR' / 'RANGING'
            'confidence': float,   # trend strength
        }

        Usage::
            portfolio_inputs = adapter.get_portfolio_inputs()
            optimizer = PortfolioOptimizer()
            weights = optimizer.optimize(portfolio_inputs)
        """
        inputs = {}
        with self._lock:
            for sym, feats in self.symbol_forecasts.items():
                inputs[sym] = {
                    "volatility": feats.get("volatility_forecast", 0.01),
                    "trend": feats.get("trend", 0.0),
                    "regime": feats.get("regime_label", "RANGING"),
                    "confidence": feats.get("trend_strength", 0.0),
                }
        return inputs

    # ── Internal helpers ───────────────────────────────────────────────

    def _init_predictor(self):
        """Lazy-init the KronosPricePredictor for the primary symbol."""
        if self._predictor is None:
            from .predictor import KronosPricePredictor

            device = getattr(self.config, "DEVICE", None)
            self._predictor = KronosPricePredictor(device=device)

    def _fetch_data(self) -> pd.DataFrame:
        """
        Fetch recent price data for the primary/default symbol.
        Used when no explicit data argument is passed to update().
        """
        primary_sym = self._symbols[0] if self._symbols else KRONOS_DEFAULT_SYMBOL
        # First try using a data_loader if available
        loader = getattr(self.config, "data_loader", None)
        if loader is not None and hasattr(loader, "get_rates"):
            try:
                df = loader.get_rates(
                    symbol=getattr(self.config, "SYMBOL", primary_sym),
                    timeframe=getattr(self.config, "TIMEFRAME", KRONOS_DEFAULT_INTERVAL),
                    bars=self._predictor.max_context + 50,
                )
                return df
            except Exception as e:
                self.logger.warning(f"Kronos adapter: data_loader failed ({e}), falling back to yfinance.")

        # Fallback to yfinance
        return self._fetch_symbol_data(primary_sym)

    def __repr__(self):
        return (
            f"KronosRegimeAdapter(regime={self._regime_name}, "
            f"spacing={self._spacing}, levels={self._levels}, "
            f"symbols={self._symbols})"
        )
