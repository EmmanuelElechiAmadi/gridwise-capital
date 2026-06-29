"""
Monte Carlo simulation for backtest results.

Resamples the sequence of PnL from fills to generate N synthetic equity curves,
then reports confidence intervals for key metrics (Sharpe, max drawdown, total return).
"""

import pandas as pd
import numpy as np
from analysis.performance import compute_metrics


def monte_carlo_sharpe(equity_df, n_simulations=500, confidence_level=0.95):
    """
    Bootstrap resample the equity curve returns and recompute Sharpe ratio
    for each simulation.

    Parameters
    ----------
    equity_df : pd.DataFrame
        DataFrame with columns ['timestamp', 'equity'] (equity curve from backtest).
    n_simulations : int
        Number of bootstrap iterations.
    confidence_level : float
        Confidence level for percentile intervals (default 0.95 → 2.5%–97.5%).

    Returns
    -------
    dict
        {
            'sharpe_mean': float,
            'sharpe_median': float,
            'sharpe_ci_lower': float,
            'sharpe_ci_upper': float,
            'sharpe_std': float,
            'all_sharpes': list[float],
            'max_dd_mean': float,
            'max_dd_ci_lower': float,
            'max_dd_ci_upper': float,
        }
    """
    if equity_df is None or len(equity_df) < 10:
        return _empty_monte_carlo()

    eq = equity_df['equity'].values.astype(float)
    returns = np.diff(eq) / eq[:-1]
    returns = returns[~np.isnan(returns)]

    if len(returns) < 5:
        return _empty_monte_carlo()

    n = len(returns)
    sharpes = []
    max_dds = []

    for _ in range(n_simulations):
        sampled = np.random.choice(returns, size=n, replace=True)
        sampled_series = pd.Series(sampled)

        # Annualised Sharpe (assuming 1-min bars → 1440 * 252 ≈ 362,880 per year)
        # We'll use bar count as a stand-in; user can adjust factor.
        sharpe = sampled_series.mean() / (sampled_series.std() + 1e-10) * np.sqrt(n)
        sharpes.append(sharpe)

        # Max drawdown for this sampled sequence
        sim_equity = 10000 * (1 + sampled).cumprod()
        running_max = np.maximum.accumulate(sim_equity)
        dd = (sim_equity - running_max) / running_max
        max_dds.append(abs(dd.min()) * 100)

    sharpes = np.array(sharpes)
    max_dds = np.array(max_dds)
    alpha = 1.0 - confidence_level
    lower_pct = alpha / 2 * 100
    upper_pct = (1.0 - alpha / 2) * 100

    return {
        'sharpe_mean': float(np.mean(sharpes)),
        'sharpe_median': float(np.median(sharpes)),
        'sharpe_ci_lower': float(np.percentile(sharpes, lower_pct)),
        'sharpe_ci_upper': float(np.percentile(sharpes, upper_pct)),
        'sharpe_std': float(np.std(sharpes)),
        'all_sharpes': sharpes.tolist(),
        'max_dd_mean': float(np.mean(max_dds)),
        'max_dd_ci_lower': float(np.percentile(max_dds, lower_pct)),
        'max_dd_ci_upper': float(np.percentile(max_dds, upper_pct)),
    }


def monte_carlo_returns(equity_df, n_simulations=500, confidence_level=0.95):
    """
    Bootstrap the equity curve and return percentile bands for plotting.

    Parameters
    ----------
    equity_df : pd.DataFrame
        Columns: timestamp, equity
    n_simulations : int
        Number of bootstrap resamples.
    confidence_level : float
        Confidence level for the bands.

    Returns
    -------
    pd.DataFrame
        Columns: timestamp, equity_median, equity_lower, equity_upper
    """
    if equity_df is None or len(equity_df) < 10:
        return pd.DataFrame()

    eq = equity_df['equity'].values.astype(float)
    returns = np.diff(eq) / eq[:-1]
    returns = returns[~np.isnan(returns)]
    n = len(returns)
    timestamps = equity_df['timestamp'].values
    alpha = 1.0 - confidence_level

    # Generate multiple equity curves
    all_curves = []
    init_capital = eq[0]
    for _ in range(n_simulations):
        sampled = np.random.choice(returns, size=n, replace=True)
        curve = init_capital * (1 + sampled).cumprod()
        curve = np.insert(curve, 0, init_capital)
        all_curves.append(curve)

    all_curves = np.array(all_curves)  # (n_sim, n+1)
    median = np.median(all_curves, axis=0)
    lower = np.percentile(all_curves, alpha / 2 * 100, axis=0)
    upper = np.percentile(all_curves, (1.0 - alpha / 2) * 100, axis=0)

    return pd.DataFrame({
        'timestamp': timestamps,
        'equity_median': median,
        'equity_lower': lower,
        'equity_upper': upper,
    })


def _empty_monte_carlo():
    return {
        'sharpe_mean': 0.0, 'sharpe_median': 0.0,
        'sharpe_ci_lower': 0.0, 'sharpe_ci_upper': 0.0,
        'sharpe_std': 0.0, 'all_sharpes': [],
        'max_dd_mean': 0.0, 'max_dd_ci_lower': 0.0, 'max_dd_ci_upper': 0.0,
    }