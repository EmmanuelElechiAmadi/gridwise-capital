import pandas as pd
from .engine import BacktestEngine
from quant_env.analysis.performance import compute_metrics
import plotly.graph_objects as go

def sensitivity(data, strategy_class, param_name, param_values, fixed_kwargs, metric='sharpe_ratio', capital=10000):
    results = []
    for val in param_values:
        kwargs = {**fixed_kwargs, param_name: val}
        engine = BacktestEngine(data.copy(), strategy_class, capital, **kwargs)
        res = engine.run()
        metrics = compute_metrics(res.fills_df, res.equity_df)
        metrics[param_name] = val
        results.append(metrics)
    df = pd.DataFrame(results)
    fig = go.Figure(go.Scatter(x=df[param_name], y=df[metric], mode='lines+markers'))
    fig.update_layout(title=f'{metric} vs {param_name}')
    return df, fig
