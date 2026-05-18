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
