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


# ── Kronos-Augmented Monte Carlo (Item 7) ───────────────────────────────

def monte_carlo_with_kronos(
    equity_df,
    augmenter,
    historical_df,
    n_simulations=200,
    kronos_fraction=0.3,
    confidence_level=0.95,
):
    """
    Run Monte Carlo simulation that blends historical bootstrap resampling
    with Kronos-generated synthetic scenarios for regime-conditional
    scenario generation.

    This function delegates to the implementation in
    ``ml.kronos.backtest_augmenter.monte_carlo_with_kronos`` for the
    actual simulation logic.

    Parameters
    ----------
    equity_df : pd.DataFrame
        Equity curve from backtest (columns: timestamp, equity).
    augmenter : KronosBacktestDataAugmenter or None
        Initialized Kronos augmenter for synthetic scenario generation.
        If None, falls back to standard bootstrap.
    historical_df : pd.DataFrame
        Historical OHLCV data used as Kronos context for scenario generation.
    n_simulations : int
        Total number of simulation iterations.
    kronos_fraction : float
        Fraction of simulations using Kronos synthetic data (0.0 to 1.0).
        The remainder uses standard bootstrap resampling.
    confidence_level : float
        Confidence level for percentile intervals (default 0.95).

    Returns
    -------
    dict
        Same shape as :func:`monte_carlo_sharpe`:
        sharpe_mean, sharpe_ci_lower, sharpe_ci_upper, max_dd_mean, etc.
    """
    if augmenter is not None:
        try:
            from ml.kronos.backtest_augmenter import monte_carlo_with_kronos as _kronos_mc
            return _kronos_mc(
                equity_df=equity_df,
                augmenter=augmenter,
                historical_df=historical_df,
                n_simulations=n_simulations,
                kronos_fraction=kronos_fraction,
            )
        except ImportError:
            # Kronos not available — fallback silently
            pass
        except Exception as e:
            import logging
            logging.getLogger("QuantBot").warning(
                f"Kronos MC failed ({e}), falling back to standard bootstrap"
            )

    # Fallback: standard bootstrap Monte Carlo
    return monte_carlo_sharpe(equity_df, n_simulations=n_simulations, confidence_level=confidence_level)


def regim_conditional_monte_carlo(
    equity_df,
    regime_history,
    augmenter,
    historical_df,
    n_simulations=200,
    kronos_fraction=0.3,
    confidence_level=0.95,
):
    """
    Regime-conditional Monte Carlo: split the equity curve by market regime
    and apply Kronos scenarios from the matching regime.

    This allows the simulation to account for different return distributions
    in BULL vs BEAR vs RANGING market conditions.

    Parameters
    ----------
    equity_df : pd.DataFrame
        Columns: [timestamp, equity]
    regime_history : pd.DataFrame or dict-like
        Per-timestamp regime labels, keyed by timestamp or index.
    augmenter : KronosBacktestDataAugmenter or None
    historical_df : pd.DataFrame
        OHLCV data for Kronos scenario generation.
    n_simulations : int
        Number of simulations.
    confidence_level : float
        Confidence interval level.

    Returns
    -------
    dict
        Same structure as monte_carlo_sharpe.
    """
    if equity_df is None or len(equity_df) < 10:
        return _empty_monte_carlo()

    eq = equity_df["equity"].values.astype(float)
    returns = np.diff(eq) / eq[:-1]
    returns = returns[~np.isnan(returns)]

    if len(returns) < 5:
        return _empty_monte_carlo()

    n = len(returns)
    sharpes = []
    max_dds = []

    # Split returns by regime if regime_history is provided
    from collections import defaultdict
    regime_returns = defaultdict(list)

    if regime_history is not None and hasattr(regime_history, "__getitem__"):
        # Iterate over aligned timestamps
        timestamps = (
            equity_df["timestamp"].values
            if "timestamp" in equity_df.columns
            else equity_df.index
        )
        for i in range(len(returns)):
            ts = timestamps[i] if i < len(timestamps) else None
            if ts is not None and ts in regime_history:
                regime = regime_history[ts]
            else:
                regime = "RANGING"
            regime_returns[regime].append(returns[i])
    else:
        regime_returns["ALL"] = list(returns)

    for _ in range(n_simulations):
        sampled = np.random.choice(returns, size=n, replace=True)

        # Inject Kronos scenarios if available
        if augmenter is not None and kronos_fraction > 0:
            try:
                # Get current dominant regime (most common in sample)
                kronos_n = int(n * kronos_fraction)
                scenarios = augmenter.generate_scenarios(
                    historical_df,
                    n_scenarios=1,
                    regime=max(regime_returns.keys(), key=lambda r: len(regime_returns[r])),
                )
                if scenarios and len(scenarios[0]) > 1:
                    synth_ret = np.diff(scenarios[0]["close"].values) / scenarios[0]["close"].values[:-1]
                    n_replace = min(len(synth_ret), kronos_n)
                    if n_replace > 0:
                        idx = np.random.choice(n, n_replace, replace=False)
                        sampled[idx] = np.random.choice(synth_ret, size=n_replace, replace=True)
            except Exception:
                pass  # fallback to pure bootstrap

        sharpe = np.mean(sampled) / (np.std(sampled) + 1e-10) * np.sqrt(n)
        sharpes.append(sharpe)

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
        "sharpe_mean": float(np.mean(sharpes)),
        "sharpe_median": float(np.median(sharpes)),
        "sharpe_ci_lower": float(np.percentile(sharpes, lower_pct)),
        "sharpe_ci_upper": float(np.percentile(sharpes, upper_pct)),
        "sharpe_std": float(np.std(sharpes)),
        "all_sharpes": sharpes.tolist(),
        "max_dd_mean": float(np.mean(max_dds)),
        "max_dd_ci_lower": float(np.percentile(max_dds, lower_pct)),
        "max_dd_ci_upper": float(np.percentile(max_dds, upper_pct)),
    }
