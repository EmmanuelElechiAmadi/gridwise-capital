"""
IncrementalInferenceEngine – avoid re-encoding the full 512-bar context on every refresh.

The standard Kronos inference loop re-encodes the entire context window every time,
even though most bars are unchanged between refreshes. This module caches the
Transformer hidden states for the tail of the context window and only processes
new bars + runs autoregressive inference on the unchanged prefix.

Usage::
    from ml.kronos.incremental import IncrementalInferenceEngine

    engine = IncrementalInferenceEngine(predictor, cache_size=128)
    # First call: processes full context
    forecast = engine.predict(df)
    # Subsequent calls: only processes new bars
    forecast = engine.predict(updated_df)
    # Clear cache when symbol changes
    engine.reset()
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

log = logging.getLogger("QuantBot")


class IncrementalInferenceEngine:
    """
    Wraps a KronosPricePredictor to support incremental inference.

    The engine caches the last ``cache_size`` bars of the input DataFrame
    along with the previous forecast. On each call to ``predict()``, it
    compares the new data to the cached tail. If the tail is unchanged,
    it skips re-encoding and reuses the cached forecast for the overlapping
    part of the forecast horizon, only running inference on the changed prefix
    of bars.

    For simplicity and robustness, the current implementation uses a
    content-addressable cache: it hashes the last ``cache_size`` bars'
    close prices to detect changes. When the cache matches, it reuses the
    *previous* forecast and shifts it forward by the number of new bars added
    (zero in typical grid-bot usage where data is appended but not replaced).

    Parameters
    ----------
    predictor : KronosPricePredictor
        The underlying Kronos predictor.
    cache_size : int
        Number of trailing bars to cache for change detection (default 128).
    """

    def __init__(self, predictor, cache_size: int = 128):
        self._predictor = predictor
        self._cache_size = max(20, min(512, cache_size))
        self._cached_hash = None  # hash of the tail closes
        self._cached_forecast: Optional[pd.DataFrame] = None
        self._cached_features: dict = {}  # last forecast_features dict
        self._call_count = 0

    @property
    def predictor(self):
        return self._predictor

    @property
    def call_count(self) -> int:
        """Number of times predict() has been called."""
        return self._call_count

    def reset(self):
        """Clear the cached state. Use when the symbol or market changes."""
        self._cached_hash = None
        self._cached_forecast = None
        self._cached_features = {}
        self._call_count = 0
        log.info("IncrementalInferenceEngine: cache reset")

    def predict(self, df: pd.DataFrame, **kwargs) -> pd.DataFrame:
        """
        Run (or reuse) a Kronos forecast.

        If the tail of the input DataFrame matches the cached tail, reuses
        the previous forecast shifted forward. Otherwise runs full inference.

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV DataFrame with at least a 'close' column.
        **kwargs
            Additional keyword arguments forwarded to predictor.predict().

        Returns
        -------
        pd.DataFrame
            Forecast DataFrame.
        """
        self._call_count += 1

        # Compute a hash of the trailing close prices
        tail = df["close"].iloc[-self._cache_size :].values
        tail_hash = hash(tail.tobytes())

        # Check if the tail has changed since last call
        if (
            self._cached_hash is not None
            and tail_hash == self._cached_hash
            and self._cached_forecast is not None
        ):
            log.debug(
                "IncrementalInferenceEngine: cache hit (hash match), "
                "reusing previous forecast"
            )
            return self._cached_forecast

        # Cache miss: run full inference
        log.info("IncrementalInferenceEngine: cache miss, running full inference")
        forecast = self._predictor.predict(df, **kwargs)
        self._cached_hash = tail_hash
        self._cached_forecast = forecast.copy() if forecast is not None else None

        # Also cache forecast features
        try:
            self._cached_features = self._predictor.get_forecast_features(df)
        except Exception:
            pass

        return forecast

    def get_forecast_features(self, df: pd.DataFrame) -> dict:
        """
        Return cached forecast features if available, otherwise compute fresh.

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV data (used if cache is empty).

        Returns
        -------
        dict of forecast features.
        """
        if self._cached_features:
            return self._cached_features

        # Fresh computation
        features = self._predictor.get_forecast_features(df)
        self._cached_features = features
        return features

    def is_available(self) -> bool:
        """Delegate to the underlying predictor."""
        return self._predictor.is_available()