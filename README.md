# Quant Grid Bot – Professional Trading Platform

A modular, production-ready algorithmic trading platform for MetaTrader 5 with grid trading strategies, machine learning regime classification, backtesting, walk-forward optimization, and a real-time dashboard.

## Architecture Overview

```
gridbots/
├── live/                           # MT5 bridge server & simple grid bot
│   ├── mt5_bridge_server.py       # Flask API running on Windows VM/VPS
│   ├── mt5_bridge.py              # Bridge client (requests to server)
│   └── grid_bot.py                # Standalone simple grid bot
│
├── quant_env/                      # Core trading engine (runs on Mac/Linux)
│   ├── main.py                    # Application entry point
│   ├── config.py                  # User configuration (copied from config.example.py)
│   ├── config.example.py          # Example config with env var overrides
│   │
│   ├── core/                      # Core infrastructure
│   │   ├── connector.py           # MT5 bridge client / direct MT5 connector
│   │   ├── risk_manager.py        # Risk checks (TP, SL, max drawdown, max position)
│   │   └── logger.py              # Rotating file + console logger
│   │
│   ├── strategies/                # Trading strategies
│   │   ├── base_strategy.py       # Abstract base class
│   │   └── grid_strategy.py       # Grid trading strategy implementation
│   │
│   ├── analysis/                  # Post-trade analysis & reporting
│   │   ├── trade_logger.py        # SQLite trade & equity snapshots
│   │   ├── trade_matcher.py       # FIFO buy/sell matching → closed trades
│   │   ├── performance.py         # Sharpe, drawdown, win rate, profit factor
│   │   ├── session_analyzer.py    # Per-session performance (Sydney/Tokyo/London/NY)
│   │   ├── monte_carlo.py         # Monte Carlo simulation of trade returns
│   │   ├── report_generator.py    # HTML report with Plotly charts
│   │   └── walkforward.py         # Walk-forward analysis
│   │
│   ├── backtest/                  # Historical backtesting
│   │   ├── data_loader.py         # YFinance data downloader
│   │   ├── engine.py              # Event-driven backtest engine
│   │   ├── optimizer.py           # Grid search parameter optimization
│   │   └── sensitivity.py         # Sensitivity analysis & plots
│   │
│   ├── ml/                        # Machine learning regime classification
│   │   ├── data_builder.py        # Feature engineering (ADX, volatility, volume)
│   │   ├── regime_model.py        # RandomForest classifier training/saving/loading
│   │   └── regime_adapter.py      # Live adapter: reclassifies regime, adjusts grid
│   │
│   ├── adaptive/                  # Adaptive parameter updating
│   │   └── updater.py             # Periodic walk-forward + grid parameter update
│   │
│   ├── data_feeds/                # Alternative data feeds
│   │   └── economic_news.py       # High-impact news filter (ForexFactory)
│   │
│   ├── optimization/              # Portfolio & genetic optimization
│   │   ├── portfolio_optimizer.py
│   │   └── genetic_optimizer.py
│   │
│   ├── dashboard/                 # Real-time web dashboard
│   │   └── app.py                 # Flask + SocketIO dashboard
│   │
│   ├── utils/                     # Utilities
│   │   ├── config_loader.py       # .env file loader
│   │   ├── emailer.py             # SMTP email sender with attachments
│   │   ├── health_checker.py      # System health & connectivity checks
│   │   └── notifications.py       # Telegram bot notifications
│   │
│   └── tests/                     # Test suite (46 tests)
│       ├── test_strategy.py       # Grid strategy unit tests
│       ├── test_backtest.py       # Backtest engine & optimization tests
│       ├── test_analysis.py       # Analysis & reporting tests
│       ├── test_ml.py             # ML regime classification tests
│       └── conftest.py            # Shared fixtures
│
├── launcher.py                    # Unified CLI: live | backtest | optimize | report | walkforward | train_ml
├── requirements.txt               # Python dependencies
├── .env.example                   # Environment variable template
└── .gitignore
```

## Quick Start

### 1. Installation

```bash
cd gridbots

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r quant_env/requirements.txt
```

### 2. Configuration

```bash
# Copy example config
cp quant_env/config.example.py quant_env/config.py

# Edit config.py with your settings
# For sensitive data, set env vars or copy .env.example to .env
cp .env.example .env
# Edit .env with your Telegram token, email credentials, etc.
```

### 3. Run Modes

All modes are accessible via `launcher.py`:

```bash
# Live trading (headless, requires MT5 bridge)
python launcher.py live

# Backtest with historical data
python launcher.py backtest

# Grid search optimization
python launcher.py optimize

# Generate live performance report
python launcher.py report

# Walk-forward analysis
python launcher.py walkforward

# Train ML regime classifier
python launcher.py train_ml

# Launch the web dashboard (trading starts paused — click Start in the UI)
python launcher.py dashboard
```

Open [http://localhost:5050](http://localhost:5050) in your browser.

> **Note:** The dashboard is the recommended way to run live trading. Trading starts **paused** — click the **"Start"** button in the sidebar to begin. You can stop, close positions, reset the grid, and refresh the regime all from the UI without touching the terminal.

Or run individual components:

```bash
# Launch the web dashboard directly
python quant_env/dashboard/app.py

# Run all tests
cd quant_env && python -m pytest tests/ -v
```

## Live Trading Setup

### Architecture

```
┌─────────────────────┐         ┌──────────────────────┐
│   Mac / Linux       │         │   Windows VM / VPS   │
│                     │  HTTP   │                      │
│  quant_env/main.py  │◄───────►│  mt5_bridge_server.py│
│  (strategy engine)  │ REST    │  (Flask API)          │
│                     │         │       │               │
└─────────────────────┘         │  MetaTrader 5        │
                                │  (trading terminal)  │
                                └──────────────────────┘
```

### Windows VM Setup

1. Install MetaTrader 5 on your Windows VM
2. Log in to your broker account in MT5
3. Run the bridge server:
   ```bash
   python live/mt5_bridge_server.py
   ```
4. Note the VM's IP address

### Mac Setup

1. Set `BRIDGE_URL` in `config.py` to the VM's IP address
2. Launch the trading engine:
   ```bash
   python launcher.py live
   ```
   Or with dashboard:
   ```bash
   python quant_env/dashboard/app.py
   ```
   Then open http://localhost:5050

## Production Deployment (Windows VPS)

For a Windows VPS with direct MT5 access:

1. Install Python 3.10+ and MetaTrader5 package
2. Copy `quant_env/` to the VPS
3. Set `MODE = "direct"` in `config.py`
4. Run `python launcher.py live`

The engine has built-in:
- **Graceful shutdown** on SIGINT/SIGTERM (closes all positions before exit)
- **Auto-recovery mode** with exponential backoff on connection loss (3 retries, 2x backoff)
- **Rotating file logs** (10 MB per file, 5 backup files) + console output
- **Health checker** for bridge, internet, and data feed connectivity
- **Email notifications** with report attachments (HTML + trade DB backup)
- **Telegram notifications** for risk events and critical alerts
- **Configurable risk limits** (max drawdown %, max position size, TP/SL in dollars)

## Machine Learning

### Training

```bash
python launcher.py train_ml
```

Downloads 3 months of 1-hour gold futures data, builds features (ADX, volatility, volume ratios, lagged returns), trains a RandomForest classifier, and saves the model to `quant_env/ml/model.pkl`.

### Live Usage

Set `ML_ENABLED = True` in `config.py`. The RegimeAdapter will:
1. Periodically reclassify the market regime (trending vs ranging)
2. Adjust grid spacing and number of levels accordingly
3. Pause trading during high-volatility regime transitions

## Backtesting

```bash
python launcher.py backtest
```

Downloads 5 days of 1-minute gold futures data, runs the grid strategy, computes performance metrics, and generates an HTML report. The report includes:
- Equity curve & drawdown chart
- Performance metrics (Sharpe, win rate, profit factor, max drawdown)
- Session analysis (performance by trading session)
- Monte Carlo simulation (1000 simulations, 252-period horizon)

### Optimization

```bash
python launcher.py optimize
```

Grid search over spacing and level parameters, ranked by Sharpe ratio. Results saved to `optimization_results.csv`.

### Walk-Forward Analysis

```bash
python launcher.py walkforward
```

Sliding window walk-forward with in-sample optimization and out-of-sample validation. Results saved to `walkforward_results.csv`.

## Testing

The project includes **46 passing tests** covering all major components:

```bash
cd gridbots/quant_env
python -m pytest tests/ -v
```

### Test Coverage

| Test File | Tests | What It Covers |
|-----------|-------|----------------|
| `test_strategy.py` | 11 | Grid initialization, order placement, fill handling, reset, edge cases |
| `test_backtest.py` | 11 | Data loading, engine execution, optimization, sensitivity analysis, error handling |
| `test_analysis.py` | 12 | Trade matching, performance metrics, session analysis, Monte Carlo, report generation |
| `test_ml.py` | 12 | Feature engineering, model training/saving/loading, regime adapter, error handling |

## Configuration Reference

| Parameter | Default | Description |
|-----------|---------|-------------|
| `SYMBOL` | `XAUUSD.r` | Trading symbol |
| `LOT_SIZE` | `0.01` | Position size |
| `GRID_SPACING` | `2.0` | Distance between grid levels |
| `NUM_LEVELS` | `3` | Number of grid levels per side |
| `TAKE_PROFIT_DOLLARS` | `2.0` | Take profit in account currency |
| `STOP_LOSS_DOLLARS` | `0` | Stop loss in account currency |
| `MAX_POSITION_OZ` | `1.0` | Maximum net position in ounces |
| `MAX_DRAWDOWN_PERCENT` | `0` | Maximum drawdown percentage |
| `MODE` | `bridge` | `bridge` or `direct` |
| `ADAPTIVE_ENABLED` | `True` | Enable adaptive walk-forward updates |
| `ML_ENABLED` | `False` | Enable ML regime classification |
| `NEWS_FILTER_ENABLED` | `True` | Pause around high-impact news |

All sensitive parameters (passwords, tokens, URLs) can be overridden via environment variables. See `.env.example` for available variables.

## Development

### Running Tests

```bash
cd gridbots/quant_env
python -m pytest tests/ -v --tb=short
```

To run specific test files:

```bash
python -m pytest tests/test_strategy.py -v
python -m pytest tests/test_backtest.py -v
python -m pytest tests/test_analysis.py -v
python -m pytest tests/test_ml.py -v
```

### Code Style

- Uses PEP 8 conventions
- Comprehensive docstrings for all public methods
- Type hints encouraged

## License

Private use. All rights reserved.