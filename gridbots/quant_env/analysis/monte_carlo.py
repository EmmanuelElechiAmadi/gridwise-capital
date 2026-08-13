import numpy as np
import plotly.graph_objects as go

def run_monte_carlo(trade_returns, num_sim=1000, horizon=252, initial=10000):
    if len(trade_returns)==0:
        return None, {}
    rets = np.array(trade_returns)
    curves = np.zeros((num_sim, horizon))
    for i in range(num_sim):
        sampled = np.random.choice(rets, size=horizon, replace=True)
        curves[i] = initial + np.cumsum(sampled)
    finals = curves[:,-1]
    stats = {
        'prob_profit': (finals > initial).mean()*100,
        'expected_equity': finals.mean(),
        'var_95': np.percentile(finals,5)-initial,
        'median_max_dd': np.median(np.max(np.maximum.accumulate(curves,axis=1)-curves, axis=1))
    }
    fig = go.Figure()
    for i in range(min(100,num_sim)):
        fig.add_trace(go.Scatter(x=np.arange(horizon), y=curves[i], mode='lines', line=dict(color='lightblue', width=0.5), showlegend=False))
    p95 = np.percentile(curves,95,axis=0)
    p5 = np.percentile(curves,5,axis=0)
    median = np.median(curves,axis=0)
    fig.add_trace(go.Scatter(x=np.arange(horizon), y=median, name='Median'))
    fig.add_trace(go.Scatter(x=np.arange(horizon), y=p95, name='95th'))
    fig.add_trace(go.Scatter(x=np.arange(horizon), y=p5, name='5th'))
    return fig, stats


def possibility_cone(dollar_returns, num_sim=1000, horizon=120, initial=10000.0,
                     ruin_floor=0.0, seed=None):
    """
    Bootstrap Monte-Carlo "possibility cone" forward from the current equity
    point — the 5th / 50th / 95th percentile paths plus P(ruin) and P(profit).

    Parameters
    ----------
    dollar_returns : sequence of realized per-trade (or per-bar) dollar PnL.
        Sampled with replacement to build forward equity paths.
    num_sim : number of forward paths.
    horizon : number of forward steps plotted.
    initial : current equity (start of the cone).
    ruin_floor : equity level counted as "ruin" (default 0 → below zero).

    Returns
    -------
    ``(curves, stats)`` — curves is the raw (num_sim, horizon) ndarray (or
    None on empty input); stats is a JSON-friendly dict with percentile
    bands and probabilities.  Plotly-free on purpose so the dashboard can
    render the cone in plain SVG.
    """
    if dollar_returns is None or len(dollar_returns) == 0:
        return None, {}
    rng = np.random.default_rng(seed)
    rets = np.asarray(dollar_returns, dtype=float)
    curves = np.empty((num_sim, horizon))
    for i in range(num_sim):
        sampled = rng.choice(rets, size=horizon, replace=True)
        curves[i] = initial + np.cumsum(sampled)
    finals = curves[:, -1]
    p5 = np.percentile(curves, 5, axis=0)
    p50 = np.percentile(curves, 50, axis=0)
    p95 = np.percentile(curves, 95, axis=0)
    peak = np.maximum.accumulate(curves, axis=1)
    dd_dollars = np.max(peak - curves, axis=1)
    stats = {
        "prob_profit_pct": round(float((finals > initial).mean() * 100), 2),
        "prob_ruin_pct": round(float((finals < ruin_floor).mean() * 100), 2),
        "expected_equity": round(float(finals.mean()), 2),
        "var_95": round(float(np.percentile(finals, 5) - initial), 2),
        "median_max_drawdown_pct": round(
            float(np.median(dd_dollars)) / initial * 100, 2),
        "num_sim": num_sim,
        "horizon": int(horizon),
        "initial": round(float(initial), 2),
        "sample_size": int(len(rets)),
        "p5": [round(float(x), 2) for x in p5],
        "p50": [round(float(x), 2) for x in p50],
        "p95": [round(float(x), 2) for x in p95],
    }
    return curves, stats
