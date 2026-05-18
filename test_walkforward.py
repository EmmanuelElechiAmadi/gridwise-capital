import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'quant_env'))

from backtest.data_loader import load_yfinance
from strategies.grid_strategy import GridStrategy
from analysis.walkforward import walkforward_analysis

# Use daily data so a few months give us plenty of bars
data = load_yfinance("GC=F", period="3mo", interval="1d")

wf = walkforward_analysis(
    data,
    GridStrategy,
    {'spacing': [0.1, 0.2], 'levels': [3, 5]},
    window_size=20,      # 20 trading days for in‑sample
    step_size=10,        # 10 trading days out‑of‑sample
    initial_capital=10000,
    lot=1.0
)

if wf.empty:
    print("Not enough data for walk‑forward with these window sizes.")
else:
    print(wf[['start_date', 'end_date', 'total_return_pct', 'sharpe_ratio', 'spacing', 'levels']])