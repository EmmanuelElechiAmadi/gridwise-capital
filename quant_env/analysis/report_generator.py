import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime

def generate_report(equity_df, fills_df, metrics, session_stats, mc_fig=None, output_file="report.html"):
    equity_series = pd.Series(equity_df['equity'].values, index=pd.to_datetime(equity_df['timestamp']))
    peak = equity_series.cummax()
    dd = peak - equity_series
    fig1 = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05)
    fig1.add_trace(go.Scatter(x=equity_series.index, y=equity_series, name='Equity'), row=1, col=1)
    fig1.add_trace(go.Scatter(x=dd.index, y=-dd, fill='tozeroy', name='Drawdown'), row=2, col=1)
    plot_div = fig1.to_html(full_html=False)
    mc_div = mc_fig.to_html(full_html=False) if mc_fig else ""
    html = f'''<html><head><title>Report {datetime.now().date()}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script></head>
    <body class="container"><h1>Quant Grid Bot Report</h1>
    <h3>Metrics</h3>{pd.DataFrame([metrics]).to_html(classes='table')}
    <h3>Equity & Drawdown</h3>{plot_div}
    <h3>Session Stats</h3>{session_stats.to_html(classes='table') if not session_stats.empty else 'N/A'}
    <h3>Monte Carlo</h3>{mc_div}
    </body></html>'''
    with open(output_file, 'w') as f: f.write(html)
