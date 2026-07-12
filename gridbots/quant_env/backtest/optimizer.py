import itertools
from .engine import BacktestEngine
from analysis.performance import compute_metrics
import pandas as pd

def optimize(data, strategy_class, param_grid, capital=10000):
    keys = list(param_grid.keys())
    results = []
    # If param_grid is empty, return empty DataFrame immediately
    if not keys:
        return pd.DataFrame()
    for combo in itertools.product(*param_grid.values()):
        params = dict(zip(keys, combo))
        engine = BacktestEngine(data.copy(), strategy_class, capital, **params)
        res = engine.run()
        metrics = compute_metrics(res.fills_df, res.equity_df)
        # _empty_metrics() inside compute_metrics already assigns sharpe_ratio=-999 for no-trade results
        metrics.update(params)
        results.append(metrics)
    return pd.DataFrame(results).sort_values('sharpe_ratio', ascending=False)