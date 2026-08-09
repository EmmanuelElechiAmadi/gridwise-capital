# Seek Quant — Web Platform

Next.js 16 SaaS front-end for the **Seek Quant** algorithmic trading platform
(grid/breakout trading on Gold via MetaTrader 5). The app talks to the Flask
engine API (`gridbots/quant_env/dashboard/app.py`, port 5050).

## Pages

| Route          | Description                                                              |
| -------------- | ------------------------------------------------------------------------ |
| `/`            | Marketing landing (hero, strategy, performance, pricing)                 |
| `/pricing`     | Standalone pricing page (free / starter / professional / enterprise)     |
| `/contact`     | Contact-sales page                                                       |
| `/login`       | Sign in (demo: `admin@seekquant.com` / `admin123`, traders `trader123`)  |
| `/signup`      | Register (demo mode)                                                     |
| `/dashboard`   | Trader dashboard — live bot status, equity, performance, trades          |
| `/intelligence`| Analytics & predictions — backtests, optimization, walk-forward, ML, Kronos |
| `/admin`       | Admin panel — accounts, per-account performance, bot control             |
| `/billing`     | Subscription management (demo, localStorage-backed)                      |
| `/checkout`    | Plan checkout (demo)                                                     |

## Intelligence page

`/intelligence` is the analytics hub. It consumes the Flask engine API
(`/api/analytics/overview`, `optimization`, `walkforward`, `ml`, `equity`,
`live`) and falls back to embedded real artifacts when the engine is offline:

- KPI tiles (fills, matched trades, realized PnL, profit factor, ML accuracy)
- Strategy backtest comparison + metric cards
- Gold price series & live equity curve
- Optimization heatmap (spacing × levels)
- Walk-forward out-of-sample returns
- ML regime model (feature importances) — **Professional tier**
- Kronos foundation-model & risk panel — **Professional tier**

## Development

```bash
npm run dev        # http://localhost:3000
npm run build      # type-check + production build
npm run lint
```

The Flask backend must run for live data:

```bash
cd ../gridbots && python3 launcher.py dashboard   # serves API on :5050
```

If the backend is offline the Intelligence page uses the committed
`../gridbots/analytics_snapshot.json` data (export with
`python3 ../gridbots/export_analytics_snapshot.py`).

## Environment

Copy `.env.local` values (Supabase URL/key optional — empty values run the app
in demo mode with localStorage auth).
