"""
KronosPricePredictor – high-level wrapper around the Kronos foundation model.

Provides:
  - predict(df, pred_len) -> forecast DataFrame
  - forecast_regime_features(df) -> dict of regime-relevant metrics
  - generate_synthetic(df, n_scenarios) -> list of synthetic OHLCV scenarios
  - is_available() -> bool

Usage::
    from ml.kronos import KronosPricePredictor

    predictor = KronosPricePredictor()
    forecast = predictor.forecast_regime_features(bars_df)
    print(forecast['trend'], forecast['volatility_forecast'])
"""

import logging
import numpy as np
import pandas as pd
from .config import (
    KRONOS_MODEL_NAME,
    KRONOS_TOKENIZER_NAME,
    KRONOS_MAX_CONTEXT,
    KRONOS_PRED_LEN,
    KRONOS_SAMPLE_COUNT,
    KRONOS_TEMPERATURE,
    KRONOS_TOP_K,
    KRONOS_TOP_P,
    KRONOS_CLIP,
    KRONOS_TREND_STRENGTH_THRESHOLD,
    KRONOS_VOL_WINDOW,
)

log = logging.getLogger("QuantBot")


class KronosPricePredictor:
    """
    Wraps the Kronos model + tokenizer for OHLCV price forecasting.

    Parameters
    ----------
    model_name : str
        Hugging Face model ID for the Kronos backbone.
    tokenizer_name : str
        Hugging Face model ID for the Kronos tokenizer.
    max_context : int
        Maximum context length (bars) fed into the model.
    device : str or None
        Device to run on. Auto-detected if None (cuda > mps > cpu).
    """

    def __init__(
        self,
        model_name=None,
        tokenizer_name=None,
        max_context=None,
        device=None,
    ):
        self.model_name = model_name or KRONOS_MODEL_NAME
        self.tokenizer_name = tokenizer_name or KRONOS_TOKENIZER_NAME
        self.max_context = max_context or KRONOS_MAX_CONTEXT
        self._predictor = None

        # Auto-detect device
        if device is None:
            import torch
            if torch.cuda.is_available():
                device = "cuda:0"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"
        self.device = device

    def _lazy_load(self):
        """Load model + tokenizer on first use (lazy init)."""
        if self._predictor is not None:
            return

        log.info(
            f"KronosPricePredictor: loading model={self.model_name} "
            f"tokenizer={self.tokenizer_name} device={self.device}"
        )
        from .kronos import Kronos, KronosTokenizer, KronosPredictor

        tokenizer = KronosTokenizer.from_pretrained(self.tokenizer_name)
        model = Kronos.from_pretrained(self.model_name)

        self._predictor = KronosPredictor(
            model, tokenizer,
            device=self.device,
            max_context=self.max_context,
            clip=KRONOS_CLIP,
        )
        log.info("KronosPricePredictor: model loaded successfully")

    def is_available(self) -> bool:
        """Check whether the model is loaded and ready."""
        try:
            self._lazy_load()
            return self._predictor is not None
        except Exception as e:
            log.warning(f"KronosPricePredictor: not available ({e})")
            return False

    def predict(
        self,
        df: pd.DataFrame,
        pred_len=None,
        sample_count=None,
        T=None,
        top_p=None,
        verbose=False,
    ) -> pd.DataFrame:
        """
        Forecast future OHLCV values.

        Parameters
        ----------
        df : pd.DataFrame
            Historical OHLCV data with columns: open, high, low, close[, volume].
            Must have a DatetimeIndex.
        pred_len : int
            Number of bars to forecast (default: from config).
        sample_count : int
            Number of probabilistic samples to average (default: from config).
        T : float
            Sampling temperature (default: from config).
        top_p : float
            Top-p nucleus sampling threshold (default: from config).

        Returns
        -------
        pd.DataFrame with columns open, high, low, close, volume, amount
        and a DatetimeIndex spanning the forecast horizon.
        """
        self._lazy_load()
        pred_len = pred_len or KRONOS_PRED_LEN
        sample_count = sample_count or KRONOS_SAMPLE_COUNT
        T = T or KRONOS_TEMPERATURE
        top_p = top_p or KRONOS_TOP_P

        x_timestamp = df.index

        # Build future timestamps at the same frequency as the historical data
        inferred_freq = pd.infer_freq(x_timestamp)
        if inferred_freq is None and len(x_timestamp) >= 2:
            # Fall back to median delta
            deltas = x_timestamp[1:] - x_timestamp[:-1]
            inferred_freq = deltas.median()
        if inferred_freq is None:
            inferred_freq = pd.Timedelta(hours=1)  # default fallback

        y_timestamp = pd.date_range(
            start=x_timestamp[-1] + (x_timestamp[-1] - x_timestamp[-2]),
            periods=pred_len,
            freq=inferred_freq,
        )

        # Trim context if longer than max_context
        if len(df) > self.max_context:
            df = df.iloc[-self.max_context:].copy()
            x_timestamp = df.index

        return self._predictor.predict(
            df, x_timestamp, y_timestamp,
            pred_len=pred_len,
            T=T,
            top_k=KRONOS_TOP_K,
            top_p=top_p,
            sample_count=sample_count,
            verbose=verbose,
        )

    def _predict_with_raw(
        self,
        df: pd.DataFrame,
        pred_len=None,
        sample_count=None,
        T=None,
        top_p=None,
        verbose=False,
    ) -> tuple:
        """
        Like predict() but returns (forecast_df, raw_samples_np).
        raw_samples_np shape: (sample_count, pred_len, 6)  OHLCV+vol+amt.
        """
        self._lazy_load()
        pred_len = pred_len or KRONOS_PRED_LEN
        sample_count = sample_count or KRONOS_SAMPLE_COUNT
        T = T or KRONOS_TEMPERATURE
        top_p = top_p or KRONOS_TOP_P

        x_timestamp = df.index

        inferred_freq = pd.infer_freq(x_timestamp)
        if inferred_freq is None and len(x_timestamp) >= 2:
            deltas = x_timestamp[1:] - x_timestamp[:-1]
            inferred_freq = deltas.median()
        if inferred_freq is None:
            inferred_freq = pd.Timedelta(hours=1)

        # ── Data hygiene: never feed NaN/Inf rows into the model.  Live
        # feeds (yfinance) and spot re-anchoring can leave NaT/NaN rows for
        # market-closed hours — they corrupt normalization and can surface as
        # cryptic model errors (e.g. "Tensor * NoneType").
        df = df.copy()
        price_cols_in = [c for c in ("open", "high", "low", "close") if c in df.columns]
        if len(price_cols_in) >= 4:
            df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=price_cols_in)
            if len(df) < max(20, pred_len * 2):
                raise ValueError(
                    f"insufficient clean bars for Kronos forecast: {len(df)}")
        else:
            raise ValueError("Kronos forecast requires open/high/low/close columns")
        x_timestamp = df.index

        y_timestamp = pd.date_range(
            start=x_timestamp[-1] + (x_timestamp[-1] - x_timestamp[-2]),
            periods=pred_len,
            freq=inferred_freq,
        )

        if len(df) > self.max_context:
            df = df.iloc[-self.max_context:].copy()
            x_timestamp = df.index

        # Build tensors manually to pass return_raw=True
        import torch
        from .kronos import auto_regressive_inference, calc_time_stamps

        x_time_df = calc_time_stamps(x_timestamp)
        y_time_df = calc_time_stamps(y_timestamp)

        price_cols = ['open', 'high', 'low', 'close']
        vol_col = 'volume'
        amt_vol = 'amount'

        df_in = df.copy()
        if vol_col not in df_in.columns:
            df_in[vol_col] = 0.0
            df_in[amt_vol] = 0.0
        if amt_vol not in df_in.columns and vol_col in df_in.columns:
            df_in[amt_vol] = df_in[vol_col] * df_in[price_cols].mean(axis=1)

        x = df_in[price_cols + [vol_col, amt_vol]].values.astype(np.float32)
        x_stamp = x_time_df.values.astype(np.float32)
        y_stamp = y_time_df.values.astype(np.float32)

        x_mean, x_std = np.mean(x, axis=0), np.std(x, axis=0)
        x = (x - x_mean) / (x_std + 1e-5)
        x = np.clip(x, -KRONOS_CLIP, KRONOS_CLIP)

        x_tensor = torch.from_numpy(x[np.newaxis]).to(self._predictor.device)
        x_stamp_tensor = torch.from_numpy(x_stamp[np.newaxis]).to(self._predictor.device)
        y_stamp_tensor = torch.from_numpy(y_stamp[np.newaxis]).to(self._predictor.device)

        preds, raw = auto_regressive_inference(
            self._predictor.tokenizer,
            self._predictor.model,
            x_tensor, x_stamp_tensor, y_stamp_tensor,
            self._predictor.max_context,
            pred_len,
            clip=KRONOS_CLIP,
            T=T,
            top_k=KRONOS_TOP_K,
            top_p=top_p,
            sample_count=sample_count,
            verbose=verbose,
            return_raw=True,
        )
        # auto_regressive_inference decodes the LAST max_context tokens, which
        # include the trailing input context whenever len(df) + pred_len >
        # max_context.  Trim both the mean forecast and every raw sample to the
        # requested horizon so shapes line up with y_timestamp (pred_len, ...).
        # (This mirrors the `preds[:, -pred_len:, :]` trim in `generate()`.)
        preds = preds[:, -pred_len:, :]
        raw = raw[:, :, -pred_len:, :]
        # preds: (1, pred_len, 6), raw: (1, sample_count, pred_len, 6)
        preds = preds.squeeze(0) * (x_std + 1e-5) + x_mean
        raw_samples = raw.squeeze(0) * (x_std + 1e-5) + x_mean  # (sample_count, pred_len, 6)

        forecast_df = pd.DataFrame(
            preds, columns=price_cols + [vol_col, amt_vol], index=y_timestamp
        )
        return forecast_df, raw_samples

    def get_forecast_features(self, df: pd.DataFrame) -> dict:
        """
        Compute regime-relevant forecast metrics from the Kronos model.

        Returns
        -------
        dict with keys:
            volatility_forecast  : std of forecast returns
            trend                : signed relative price change over forecast horizon
            trend_strength       : |trend| / volatility_forecast (signal-to-noise ratio)
            price_range          : forecast high - forecast low
            price_min_forecast   : minimum forecast low
            price_max_forecast   : maximum forecast high
            forecast_close       : numpy array of forecast close prices
            regime_label         : "BULL", "BEAR", or "RANGING" (based on trend_strength)
            raw_samples          : numpy array of raw sample forecasts (sample_count, pred_len, 6)
        """
        forecast_df, raw_samples = self._predict_with_raw(df)

        forecast_returns = forecast_df["close"].pct_change().dropna()

        # Volatility forecast
        vol_forecast = float(forecast_returns.std())
        if vol_forecast == 0:
            vol_forecast = 1e-8

        # Trend: relative change over the full forecast horizon
        last_close = float(df["close"].iloc[-1])
        trend = float((forecast_df["close"].iloc[-1] - last_close) / last_close)
        trend_strength = abs(trend) / vol_forecast

        # Price range
        price_min = float(forecast_df["low"].min())
        price_max = float(forecast_df["high"].max())
        price_range = price_max - price_min

        # Regime label
        if trend_strength >= KRONOS_TREND_STRENGTH_THRESHOLD:
            regime = "BULL" if trend > 0 else "BEAR"
        else:
            regime = "RANGING"

        return {
            "volatility_forecast": vol_forecast,
            "trend": trend,
            "trend_strength": trend_strength,
            "price_range": price_range,
            "price_min_forecast": price_min,
            "price_max_forecast": price_max,
            "forecast_close": forecast_df["close"].values,
            "forecast_open": forecast_df["open"].values,
            "forecast_high": forecast_df["high"].values,
            "forecast_low": forecast_df["low"].values,
            "regime_label": regime,
            "raw_samples": raw_samples,  # (sample_count, pred_len, 6)
        }

    def generate_synthetic(
        self,
        df: pd.DataFrame,
        n_scenarios: int = 100,
        noise_scale: float = 0.01,
    ) -> list:
        """
        Generate synthetic OHLCV scenarios by running Kronos with different
        random seeds. Useful for backtesting data augmentation.

        Parameters
        ----------
        df : pd.DataFrame
            Historical OHLCV data (seeded with the real tail context).
        n_scenarios : int
            Number of synthetic scenarios to generate.
        noise_scale : float
            Small noise added to historical data for scenario diversity.

        Returns
        -------
        list of pd.DataFrame, each with the same structure as the input.
        """
        scenarios = []
        for _ in range(n_scenarios):
            # Add small noise to the input for diversity
            noisy = df.copy()
            noisy[["open", "high", "low", "close"]] *= (
                1.0 + np.random.randn() * noise_scale
            )
            # Use a different temperature for each scenario
            temp = KRONOS_TEMPERATURE * (0.8 + 0.4 * np.random.random())
            forecast = self.predict(noisy, T=temp)
            scenarios.append(forecast)
        return scenarios