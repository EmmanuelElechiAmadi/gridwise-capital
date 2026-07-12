import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pandas as pd
import numpy as np
from backtest.engine import BacktestEngine
from analysis.performance import compute_metrics
from backtest.optimizer import optimize

def walkforward_analysis(data, strategy_class, param_grid, window_size=1440, step_size=1440, initial_capital=10000, **fixed_kwargs):
    results = []
    total_bars = len(data)
    start = 0

    while start + window_size + step_size < total_bars:
        in_sample = data.iloc[start : start+window_size]
        out_sample = data.iloc[start+window_size : start+window_size+step_size]

        # Optimize on in-sample
        opt_results = optimize(in_sample, strategy_class, param_grid, capital=initial_capital)
        best_params = opt_results.iloc[0].to_dict()

        # Extract and cast parameters to prevent float/int TypeError.
        # Use the strategy class __init__ signature to infer type hints.
        import inspect
        sig = inspect.signature(strategy_class.__init__)
        param_types = {}
        for pname, param in sig.parameters.items():
            if param.annotation is not inspect.Parameter.empty:
                param_types[pname] = param.annotation

        params = {}
        for k in param_grid.keys():
            if k not in best_params:
                continue
            value = best_params[k]
            # Cast to the declared type if possible
            expected = param_types.get(k)
            if expected is int:
                value = int(value)
            elif expected is float:
                value = float(value)
            params[k] = value

        # Run out-of-sample with best parameters AND our risk guards (fixed_kwargs)
        engine = BacktestEngine(
            out_sample.copy(), 
            strategy_class, 
            initial_capital, 
            **params, 
            **fixed_kwargs
        )
        res = engine.run()

        # Calculate metrics
        metrics = compute_metrics(res.fills_df, res.equity_df)

        # Handle empty windows (no trades) gracefully
        if not metrics:
            metrics = {
                'total_return_pct': 0.0,
                'sharpe_ratio': 0.0,
                'max_dd_pct': 0.0,
                'win_rate': 0.0,
                'profit_factor': 0.0
            }

        # Append metadata — record all optimised params
        metrics['start_date'] = out_sample.index[0]
        metrics['end_date'] = out_sample.index[-1]
        for k in param_grid:
            metrics[k] = params.get(k)

        results.append(metrics)
        start += step_size

    return pd.DataFrame(results)