import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd
import numpy as np
from backtest.engine import BacktestEngine
from analysis.performance import compute_metrics
from backtest.optimizer import optimize

def walkforward_analysis(data, strategy_class, param_grid, window_size=1440, step_size=1440,
                         initial_capital=10000, **fixed_kwargs):
    results = []
    total_bars = len(data)
    start = 0
    while start + window_size + step_size < total_bars:
        in_sample  = data.iloc[start : start+window_size]
        out_sample = data.iloc[start+window_size : start+window_size+step_size]

        # Optimise on in‑sample
        opt_results = optimize(in_sample, strategy_class, param_grid, initial_capital)
        best_params = opt_results.iloc[0].to_dict()

        # ---- FIX: ensure parameters have correct types ----
        # Keep only the param keys we need
        params = {k: best_params[k] for k in param_grid.keys()}
        # Convert levels to int, spacing to float (in case they came from pandas as floats)
        if 'levels' in params:
            params['levels'] = int(params['levels'])
        if 'spacing' in params:
            params['spacing'] = float(params['spacing'])

        # Run on out‑of‑sample with best params
        engine = BacktestEngine(out_sample.copy(), strategy_class, initial_capital,
                                **params, **fixed_kwargs)
        res = engine.run()
        metrics = compute_metrics(res.fills_df, res.equity_df)
        metrics['start_date'] = out_sample.index[0]
        metrics['end_date']   = out_sample.index[-1]
        metrics.update(params)
        results.append(metrics)
        start += step_size
    return pd.DataFrame(results)