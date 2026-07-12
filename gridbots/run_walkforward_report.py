import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'quant_env'))

from backtest.data_loader import load_yfinance
from strategies.grid_strategy import GridStrategy
from analysis.walkforward import walkforward_analysis
import pandas as pd

# Download 6 months of daily gold futures data
data = load_yfinance("GC=F", period="6mo", interval="1d")

# Parameter grid to test
param_grid = {'spacing': [0.5, 1.0, 2.0], 'levels': [3, 5]}

# Run walk‑forward: 1 month in‑sample, 2 weeks out‑of‑sample
wf = walkforward_analysis(
    data,
    GridStrategy,
    param_grid,
    window_size=20,       # ~1 month of trading days
    step_size=10,         # ~2 weeks of trading days
    initial_capital=10000,
    lot=1.0               # your live lot size
)

if wf.empty:
    print("Not enough data for walk‑forward with these window sizes.")
else:
    # Keep only key columns
    report = wf[['start_date', 'end_date', 'total_return_pct', 'sharpe_ratio',
                 'max_drawdown_pct', 'win_rate_pct', 'profit_factor', 'spacing', 'levels']]
    print(report)
    report.to_csv('walkforward_report.csv', index=False)
    print("Saved walkforward_report.csv")

    # Summary stats
    avg_return = report['total_return_pct'].mean()
    avg_sharpe = report['sharpe_ratio'].mean()
    worst_return = report['total_return_pct'].min()
    print(f"\nAvg Out‑of‑Sample Return: {avg_return:.2f}%")
    print(f"Avg Sharpe: {avg_sharpe:.2f}")
    print(f"Worst Window Return: {worst_return:.2f}%")