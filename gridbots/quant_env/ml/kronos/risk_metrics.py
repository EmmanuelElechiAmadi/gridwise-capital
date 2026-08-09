"""
KronosRiskMetrics – Extracts probabilistic risk metrics from Kronos raw forecast samples.

Uses the distribution of sample_count individual forecasts (rather than just the mean)
to compute VaR, CVaR, and dynamic position sizing adjustments.

Usage::
    from ml.kronos.risk_metrics import KronosRiskMetrics

    metrics = KronosRiskMetrics(config)
    features = predictor.get_forecast_features(df)
    var95, cvar95 = metrics.compute_var_cvar(raw_samples=features["raw_samples"])
    adjustment = metrics.position_size_adjustment(var95, cvar95)
    # -> adjustment 0.8 means "reduce position to 80%"
"""

import numpy as np
from typing import Optional

from .config import (
    KRONOS_VAR_CONFIDENCE,
    KRONOS_MAX_RISK_PER_TRADE,
)


def compute_var_cvar(
    raw_samples: np.ndarray,
    confidence: float = 0.95,
    horizon_bars: int = None,
) -> tuple:
    """
    Compute Value-at-Risk (VaR) and Conditional VaR (CVaR / Expected Shortfall)
    from the raw sample distribution of Kronos forecast samples.

    Parameters
    ----------
    raw_samples : np.ndarray
        Shape (sample_count, pred_len, 6) — the raw forecast samples from
        Kronos where axis=-1 is [open, high, low, close, volume, amount].
    confidence : float
        Confidence level for VaR (e.g. 0.95 means 95% VaR).
    horizon_bars : int or None
        Number of bars to use for the return calculation. If None, uses the
        full pred_len (entire forecast horizon).

    Returns
    -------
    tuple (var, cvar)
        var  : float — the return threshold such that P(return <= var) = 1-confidence.
                e.g. var=-0.02 means "5% chance of losing >2%".
        cvar : float — the expected return given that return <= var (expected shortfall).
        Both expressed as decimal fractions (e.g. -0.02 = -2%).
    """
    if raw_samples.ndim != 3 or raw_samples.shape[-1] < 4:
        raise ValueError(
            f"raw_samples must have shape (sample_count, pred_len, 6), got {raw_samples.shape}"
        )

    sample_count = raw_samples.shape[0]
    horizon = raw_samples.shape[1] if horizon_bars is None else min(horizon_bars, raw_samples.shape[1])

    # Compute returns: (close at horizon - close at bar 0) / close at bar 0 for each sample
    starting_close = raw_samples[:, 0, 3]  # (sample_count,)  close at first forecast bar
    ending_close = raw_samples[:, horizon - 1, 3]  # (sample_count,)  close at horizon

    # Avoid division by zero
    starting_close = np.where(starting_close == 0, 1e-8, starting_close)
    returns = (ending_close - starting_close) / starting_close

    # Sort returns ascending
    sorted_ret = np.sort(returns)
    n = len(sorted_ret)
    alpha = 1.0 - confidence

    # VaR: worst return below the alpha quantile
    var_idx = int(np.floor(alpha * n))
    var_idx = max(0, min(var_idx, n - 1))
    var = float(sorted_ret[var_idx])

    # CVaR: mean of returns that are <= VaR
    tail = sorted_ret[: var_idx + 1]
    cvar = float(np.mean(tail)) if len(tail) > 0 else var

    return var, cvar


def compute_sample_volatility(raw_samples: np.ndarray) -> float:
    """
    Compute the standard deviation of forecast returns from raw samples.
    This is a distributional volatility (uncertainty measure), not a
    simple point-estimate volatility.

    Parameters
    ----------
    raw_samples : np.ndarray
        Shape (sample_count, pred_len, 6).

    Returns
    -------
    float : volatility of returns across samples.
    """
    if raw_samples.ndim != 3 or raw_samples.shape[-1] < 4:
        return 0.0

    starting_close = raw_samples[:, 0, 3]
    ending_close = raw_samples[:, -1, 3]
    starting_close = np.where(starting_close == 0, 1e-8, starting_close)
    returns = (ending_close - starting_close) / starting_close

    return float(np.std(returns))


def position_size_adjustment(var: float, cvar: float, max_risk_per_trade: float = 0.02) -> float:
    """
    Compute a position size multiplier based on VaR/CVaR.

    The idea: if VaR says we have a 5% chance of losing X%, we scale back
    positions proportionally when risk is elevated.

    Parameters
    ----------
    var : float
        VaR (negative decimal, e.g. -0.02 for 2% loss).
    cvar : float
        CVaR (negative decimal, expected shortfall).
    max_risk_per_trade : float
        Maximum acceptable loss fraction per trade (e.g. 0.02 = 2%).

    Returns
    -------
    float : multiplier in [0.1, 1.0] to apply to position size.
            1.0 = no reduction, 0.1 = 90% reduction.
    """
    abs_var = abs(var)
    if abs_var <= 1e-8:
        return 1.0

    # If the VaR loss exceeds our max risk tolerance, scale down proportionally
    ratio = abs_var / max_risk_per_trade
    if ratio <= 1.0:
        return 1.0  # risk is within tolerance

    # Scale down: e.g., if VaR says 4% but max is 2%, reduce by half
    multiplier = max(0.1, 1.0 / ratio)
    return multiplier


class KronosRiskMetrics:
    """
    Convenience wrapper around the VaR/CVaR computation functions that reads
    configuration at construction time.

    Parameters
    ----------
    config : object, optional
        Global QuantEnv config object. Reads:
          - KRONOS_VAR_CONFIDENCE (float, default 0.95)
          - KRONOS_MAX_RISK_PER_TRADE (float, default 0.02)
          - KRONOS_RISK_METRICS_ENABLED (bool, default False)
    """

    def __init__(self, config=None):
        self._enabled = (
            getattr(config, "KRONOS_RISK_METRICS_ENABLED", False)
            if config is not None
            else False
        )
        self._confidence = (
            getattr(config, "KRONOS_VAR_CONFIDENCE", KRONOS_VAR_CONFIDENCE)
            if config is not None
            else KRONOS_VAR_CONFIDENCE
        )
        self._max_risk = (
            getattr(config, "KRONOS_MAX_RISK_PER_TRADE", KRONOS_MAX_RISK_PER_TRADE)
            if config is not None
            else KRONOS_MAX_RISK_PER_TRADE
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def confidence(self) -> float:
        return self._confidence

    def compute_var_cvar(
        self,
        raw_samples: np.ndarray,
        confidence: float = None,
        horizon_bars: int = None,
    ) -> tuple:
        """
        Compute VaR and CVaR from raw Kronos forecast samples.

        Delegates to the module-level :func:`compute_var_cvar`.
        """
        conf = confidence if confidence is not None else self._confidence
        return compute_var_cvar(raw_samples, confidence=conf, horizon_bars=horizon_bars)

    def compute_sample_volatility(self, raw_samples: np.ndarray) -> float:
        """Delegate to :func:`compute_sample_volatility`."""
        return compute_sample_volatility(raw_samples)

    def position_size_adjustment(self, var: float, cvar: float) -> float:
        """
        Compute position size adjustment factor (0.1 .. 1.0).

        Delegates to :func:`position_size_adjustment` using configured max risk.
        """
        return position_size_adjustment(var, cvar, max_risk_per_trade=self._max_risk)

    def __repr__(self):
        return (
            f"KronosRiskMetrics(enabled={self._enabled}, "
            f"confidence={self._confidence}, max_risk={self._max_risk})"
        )
