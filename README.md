# Quant Grid Bot – Professional Trading Platform

## Structure
- `live/` – bridge server, bridge client, simple grid bot
- `quant_env/` – core engine, strategies, analysis, ML, dashboard, backtest, optimization
- `backtest/` – standalone backtest files (yfinance)
- `docs/` – (placeholder)

## Quick Start
### Local Live Test (Mac + Windows VM)
1. On Windows VM, run `python live/mt5_bridge_server.py`
2. On Mac: `pip install -r quant_env/requirements.txt`
3. Edit `quant_env/config.py` → set `BRIDGE_URL` to VM IP
4. Launch dashboard: `python quant_env/dashboard/app.py`
   or headless: `python launcher.py live`
5. Open http://localhost:5050

### Production (Windows VPS)
Copy only `live/grid_bot.py` (or `quant_env/main.py`) to VPS, install `MetaTrader5`, run directly.

### Backtesting
`python launcher.py backtest`

### Optimization
`python launcher.py optimize`

### Full Analysis Report
`python launcher.py report`
