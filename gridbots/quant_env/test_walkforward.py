import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'quant_env'))

from backtest.data_loader import load_yfinance
from strategies.grid_strategy import GridStrategy
from analysis.walkforward import walkforward_analysis

data = load_yfinance("GC=F", period="1mo", interval="1h")   # 1‑hour bars for speed

param_grid = {'spacing': [0.1, 0.2], 'levels': [3, 5]}
wf_df = walkforward_analysis(
    data,
    GridStrategy,
    param_grid,
    window_size=500,      # number of bars per window
    step_size=500,
    initial_capital=10000,
    lot=1.0               # your live lot size
)

print(wf_df[['start_date', 'end_date', 'total_return_pct', 'sharpe_ratio', 'spacing', 'levels']])