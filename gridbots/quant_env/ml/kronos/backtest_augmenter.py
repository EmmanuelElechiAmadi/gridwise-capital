"""
KronosBacktestDataAugmenter – generates synthetic OHLCV scenarios using Kronos
and feeds them into the backtest Monte Carlo engine for regime-conditional
scenario generation.

Usage::
    from ml.kronos.backtest_augmenter import KronosBacktestDataAugmenter

    augmenter = KronosBacktestDataAugmenter(predictor)
    synthetic_scenarios = augmenter.generate_scenarios(
        df, n_scenarios=100, regime="RANGING"
    )
    # Use in Monte Carlo:
    from ml.kronos.backtest_augmenter import monte_carlo_with_kronos
    results = monte_carlo_with_kronos(equity_df, predictor, df, n_simulations=200)
"""

import logging
import numpy as np
import pandas as pd
from typing import Optional, List

log = logging.getLogger("QuantBot")


class KronosBacktestDataAugmenter:
    """
    Generates synthetic OHLCV scenarios using Kronos for backtesting data
    augmentation. Scenarios are conditioned on the current market regime
    (BULL / BEAR / RANGING) for more realistic Monte Carlo simulations.

    Parameters
    ----------
    predictor : KronosPricePredictor
        An initialized KronosPricePredictor instance.
    """

    def __init__(self, predictor):
        self._predictor = predictor

    def generate_scenarios(
        self,
        df: pd.DataFrame,
        n_scenarios: int = 100,
        regime: Optional[str] = None,
        temperature_range: tuple = (0.7, 1.4),
    ) -> List[pd.DataFrame]:
        """
        Generate synthetic OHLCV scenarios by running Kronos with varying
        temperatures and noise seeds.

        Parameters
        ----------
        df : pd.DataFrame
            Historical OHLCV data (tail used as context).
        n_scenarios : int
            Number of synthetic scenarios to generate.
        regime : str or None
            If "BULL", bias sampling toward bullish trajectories.
            If "BEAR", bias toward bearish trajectories.
            If "RANGING" or None, no bias applied.
        temperature_range : tuple
            (min_temp, max_temp) for sampling diversity.

        Returns
        -------
        list of pd.DataFrame, each with columns [open, high, low, close, volume, amount]
        and a DatetimeIndex spanning the forecast horizon.
        """
        scenarios = []
        # Tune sample count to get reasonable generation speed
        # We generate sequentially to get diverse trajectories
        for i in range(n_scenarios):
            temp = np.random.uniform(*temperature_range)
            # Add small noise to input for diversity
            noisy_df = df.copy()
            noise = 1.0 + np.random.randn() * 0.005  # 0.5% noise
            for col in ["open", "high", "low", "close"]:
                if col in noisy_df.columns:
                    noisy_df[col] = noisy_df[col] * noise

            forecast = self._predictor.predict(noisy_df, T=temp)

            # Apply regime conditioning if specified
            if regime == "BULL":
                # Ensure the forecast is net bullish (or invert if needed)
                last_close = df["close"].iloc[-1]
                forecast_close = forecast["close"].iloc[-1]
                if forecast_close < last_close:
                    # Invert the trajectory symmetrically around last close
                    for col in ["open", "high", "low", "close"]:
                        forecast[col] = last_close + (last_close - forecast[col])
            elif regime == "BEAR":
                last_close = df["close"].iloc[-1]
                forecast_close = forecast["close"].iloc[-1]
                if forecast_close > last_close:
                    for col in ["open", "high", "low", "close"]:
                        forecast[col] = last_close + (last_close - forecast[col])

            scenarios.append(forecast)

        return scenarios

    def generate_ensemble_forecast(
        self,
        df: pd.DataFrame,
        n_scenarios: int = 50,
    ) -> pd.DataFrame:
        """
        Generate an ensemble forecast by averaging multiple Kronos scenarios.

        Returns a single DataFrame with the mean of all scenarios.
        """
        scenarios = self.generate_scenarios(df, n_scenarios=n_scenarios)
        if not scenarios:
            return pd.DataFrame()

        # Average all scenarios
        mean_df = scenarios[0].copy()
        for col in mean_df.columns:
            values = np.mean([s[col].values for s in scenarios], axis=0)
            mean_df[col] = values
        return mean_df


def monte_carlo_with_kronos(
    equity_df: pd.DataFrame,
    augmenter: KronosBacktestDataAugmenter,
    historical_df: pd.DataFrame,
    n_simulations: int = 200,
    kronos_fraction: float = 0.3,
) -> dict:
    """
    Run Monte Carlo simulation that blends historical bootstrap resampling
    with Kronos-generated synthetic scenarios.

    Parameters
    ----------
    equity_df : pd.DataFrame
        Equity curve from backtest (columns: timestamp, equity).
    augmenter : KronosBacktestDataAugmenter
        Initialized augmenter for generating synthetic scenarios.
    historical_df : pd.DataFrame
        Historical OHLCV data (used as Kronos context).
    n_simulations : int
        Total number of simulation iterations.
    kronos_fraction : float
        Fraction of simulations that use Kronos synthetic data (0.0 to 1.0).
        The remainder uses standard bootstrap resampling.

    Returns
    -------
    dict with keys:
        sharpe_mean, sharpe_ci_lower, sharpe_ci_upper,
        max_dd_mean, max_dd_ci_lower, max_dd_ci_upper,
        all_sharpes (list), all_max_dds (list)
    """
    if equity_df is None or len(equity_df) < 10:
        return _empty_kronos_mc()

    eq = equity_df["equity"].values.astype(float)
    returns = np.diff(eq) / eq[:-1]
    returns = returns[~np.isnan(returns)]

    if len(returns) < 5:
        return _empty_kronos_mc()

    n = len(returns)
    n_kronos = int(n_simulations * kronos_fraction)
    n_bootstrap = n_simulations - n_kronos

    sharpes = []
    max_dds = []

    # Generate Kronos synthetic scenarios
    kronos_scenarios = []
    if n_kronos > 0 and augmenter is not None:
        try:
            kronos_scenarios = augmenter.generate_scenarios(
                historical_df, n_scenarios=n_kronos
            )
        except Exception as e:
            log.warning(f"Kronos MC: scenario generation failed ({e}), falling back to bootstrap")
            n_kronos = 0
            n_bootstrap = n_simulations

    # Process Kronos scenarios
    for scenario in kronos_scenarios:
        # Compute synthetic returns from the Kronos forecast
        synth_close = scenario["close"].values
        synth_returns = np.diff(synth_close) / synth_close[:-1]

        if len(synth_returns) < 2:
            continue

        # Blend with historical returns
        blended = np.random.choice(returns, size=n, replace=True)
        # Replace a random subset with Kronos synthetic returns
        n_replace = min(len(synth_returns), n // 2)
        if n_replace > 0:
            replace_idx = np.random.choice(n, n_replace, replace=False)
            blended[replace_idx] = np.random.choice(
                synth_returns, size=n_replace, replace=True
            )

        sharpe = blended.mean() / (blended.std() + 1e-10) * np.sqrt(n)
        sharpes.append(sharpe)

        sim_equity = 10000 * (1 + blended).cumprod()
        running_max = np.maximum.accumulate(sim_equity)
        dd = (sim_equity - running_max) / running_max
        max_dds.append(abs(dd.min()) * 100)

    # Standard bootstrap for the rest
    for _ in range(n_bootstrap):
        sampled = np.random.choice(returns, size=n, replace=True)
        sharpe = sampled.mean() / (sampled.std() + 1e-10) * np.sqrt(n)
        sharpes.append(sharpe)

        sim_equity = 10000 * (1 + sampled).cumprod()
        running_max = np.maximum.accumulate(sim_equity)
        dd = (sim_equity - running_max) / running_max
        max_dds.append(abs(dd.min()) * 100)

    sharpes = np.array(sharpes)
    max_dds = np.array(max_dds)

    return {
        "sharpe_mean": float(np.mean(sharpes)),
        "sharpe_ci_lower": float(np.percentile(sharpes, 2.5)),
        "sharpe_ci_upper": float(np.percentile(sharpes, 97.5)),
        "sharpe_std": float(np.std(sharpes)),
        "all_sharpes": sharpes.tolist(),
        "max_dd_mean": float(np.mean(max_dds)),
        "max_dd_ci_lower": float(np.percentile(max_dds, 2.5)),
        "max_dd_ci_upper": float(np.percentile(max_dds, 97.5)),
    }


def _empty_kronos_mc():
    return {
        "sharpe_mean": 0.0,
        "sharpe_ci_lower": 0.0,
        "sharpe_ci_upper": 0.0,
        "sharpe_std": 0.0,
        "all_sharpes": [],
        "max_dd_mean": 0.0,
        "max_dd_ci_lower": 0.0,
        "max_dd_ci_upper": 0.0,
    }