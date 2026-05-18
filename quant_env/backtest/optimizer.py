import itertools
from .engine import BacktestEngine
from analysis.performance import compute_metrics
import pandas as pd

def optimize(data, strategy_class, param_grid, capital=10000):
    keys = list(param_grid.keys())
    results = []
    for combo in itertools.product(*param_grid.values()):
        params = dict(zip(keys, combo))
        engine = BacktestEngine(data.copy(), strategy_class, capital, **params)
        res = engine.run()
        metrics = compute_metrics(res.fills_df, res.equity_df)
        # If no trades, metrics will be empty – assign a terrible Sharpe so it ends up last
        if not metrics:
            metrics = {
                'total_return_pct': 0.0,
                'total_pnl': 0.0,
                'sharpe_ratio': -999,   # terrible Sharpe, so it ends up last
                'max_drawdown_pct': 100.0,
                'num_trades': 0,
                'win_rate_pct': 0.0,
                'profit_factor': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
            }
        metrics.update(params)
        results.append(metrics)
    return pd.DataFrame(results).sort_values('sharpe_ratio', ascending=False)