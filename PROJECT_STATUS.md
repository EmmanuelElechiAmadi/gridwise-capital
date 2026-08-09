# Seek Quant — Project Status & Intelligence Map

_Generated 2026-08-09 from a full repository investigation._

## System overview

```
seek quant/
├── gridbots/                     Python algorithmic trading engine (MetaTrader 5)
│   ├── live/                     MT5 bridge server, client, MQL5 EA
│   ├── quant_env/                Core engine: strategies · ML · backtest · dashboard
│   ├── launcher.py               CLI (live | backtest | optimize | report | walkforward | train_ml | dashboard)
│   ├── export_analytics_snapshot.py   → analytics_snapshot.json (committed data)
│   └── analytics_snapshot.json   Real engine artifacts exported for the webapp
└── seek-quant-landing/           Next.js 16 web platform (landing · dashboard · intelligence · admin)
```

## What is DONE ✅

### Trading engine (`gridbots/quant_env`)
- Multi-account architecture: `GridBotManager`, `BrokerAccountManager`, per-account
  connectors/strategies/trade DBs (`accounts/`).
- Strategies: `GridStrategy` (regime-aware asymmetric grid) and `BreakoutStrategy`
  (5M/1H/4H breakout, partial TP $3/$5/$10, Kronos enhancer), auto-discovered via
  strategy registry.
- ML regime classification: RandomForest, 37 features, trained model + metrics
  (`ml/model.pkl`, `ml/model_metrics.json`).
- Kronos foundation-model integration (3,400+ LOC): price predictor, regime adapter,
  confidence-blended `MetaRegimeAdapter`, VaR/CVaR risk sizing, backtest data
  augmenter, incremental inference, breakout enhancer, multi-symbol portfolio
  optimizer.
- Backtest engine (commission, slippage, partial fills, drawdown stop, trend filter),
  grid-search optimizer, walk-forward analysis, sensitivity analysis.
- Analytics: Sharpe / drawdown / win-rate / profit factor, session analysis,
  Monte Carlo (1,000 sims), Plotly HTML reports.
- Trade logging (SQLite), FIFO trade matching, **FIFO realized-PnL attribution on fills** (new).
- Risk manager (TP/SL, max drawdown, daily loss → auto-close + Telegram/email),
  ForexFactory news filter, adaptive walk-forward updater.
- MT5 bridge: Flask server (Mac + Wine UTF-16 JSON bridge), client, MQL5 EA.
- Flask dashboard API on `:5050` — status, performance, trades, account CRUD,
  bot control, strategy management, operations (backtest/optimize/walkforward/train_ml/benchmark_all),
  **new analytics endpoints** (`/api/analytics/*`).
- **52/52 tests passing** (`python -m pytest tests/ -v`).

### Web platform (`seek-quant-landing`)
- Landing page (hero, strategy, performance, pricing), login/signup (demo mode,
  Supabase-ready), dashboard (live Flask data), admin panel, billing/checkout,
  subscription tiers + feature flags.
- **NEW `/intelligence`** — analytics & predictions page with dependency-free SVG
  charts: KPI tiles, strategy comparison, gold price + live equity, optimization
  heatmap, walk-forward bars, ML feature importances, Kronos/risk panel
  (Professional-tier gated via feature flags).
- **NEW `/pricing`** and **NEW `/contact`** pages (fixes broken links).
- **Next.js production build passes** (11 routes, TypeScript clean).

### Real data captured
- 550 grid fills + 28,436 equity snapshots (XAUUSD.r, May 11 – Jun 29 2026).
- Optimization grid results (9 combos), walk-forward windows (10), ML model metrics.
- Gold price history (`gold_data.csv`, 6,522 bars).

## What is UNDONE / needs work ⚠️

| Area | Gap | Recommendation |
| --- | --- | --- |
| Strategy profitability | Current backtests / live fills are net negative (walk-forward avg return negative; live realized PnL −$15.47 on 241 trades) | Re-tune grid parameters with realistic costs; review TP/SL; re-run optimization with 6mo+ data |
| ML accuracy | 51% test accuracy (≈ coin flip); BEAR class 46.6% | Add features, class balancing, longer training data, validation harness |
| Live trading | No real MT5 session currently connected (bridge unreachable, bot idle) | Attach EA in MT5, run bridge server, verify fills |
| Kronos | Disabled by default; needs HuggingFace model download + GPU | Enable in staging, benchmark forecast quality |
| Auth | Demo mode (localStorage); Supabase keys present but unused | Wire real Supabase auth + RLS |
| Payments | Checkout is simulated; Stripe dependency unused | Integrate Stripe Checkout + webhooks |
| Landing stats | `+34.2%`, `2.41 Sharpe` are fictional | Source from real analytics or mark as illustrative |
| Free-tier dashboard | Dashboard not gated; all demo users can view | Apply `SubscriptionGuard` / feature flags |
| Tests | No coverage for Kronos modules or analytics endpoints | Add unit tests for `ml/kronos/*` and `/api/analytics/*` |
| Deployment | No Docker / CI / hosting config for either app | Add Dockerfiles, GitHub Actions, Vercel config |

## Roadmap (priority order)

1. **Backtesting quality**: fix cost model, re-optimize, target Sharpe > 1 OOS.
2. **ML uplift**: retrain with balanced data + feature selection; target >60% accuracy.
3. **Live hardening**: bridge auto-reconnect, order-state reconciliation, idempotent commands.
4. **Productization**: real Supabase auth, Stripe checkout, subscription-gated features.
5. **Infrastructure**: Docker for engine + webapp, CI pipeline, monitoring (health/alerting).
6. **Research**: Kronos forecast quality benchmark; multi-symbol portfolio (gold/silver/oil).

## How to run

```bash
# Engine API (port 5050)
cd gridbots && python3 launcher.py dashboard

# Web app (port 3000)
cd seek-quant-landing && npm install && npm run dev

# Refresh the committed analytics snapshot
cd gridbots && python3 export_analytics_snapshot.py

# Tests
cd gridbots/quant_env && python3 -m pytest tests/ -v
```

> Past performance is not indicative of future results.
