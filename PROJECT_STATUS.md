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
- **NEW — InsightForge for Quant agent team** (`quant_env/intelligence/`): autonomous
  multi-agent quantitative research where every agent is a *quant professional
  replacement* — DataScout (← Recruiter), MarketProber (← Interviewer), QuantAnalyst
  (← Analyst), QuantStrategist (← Strategist), CQO Coordinator (← Coordinator).
  Runs the full source→probe→synthesize→strategize→brief loop against the real
  backtest engine, ML artifacts and cached gold history; formal signal-confidence
  (Cₛ) and qRICE math; persistent OpportunityLedger + research brief JSON; CLI
  (`python -m quant_env.intelligence.runner` or `python3 launcher.py research`); Flask
  endpoints (`/api/intelligence/brief`, `/api/intelligence/ledger`) and a **"🤖 Agent
  Team" tab wired into the gridbot dashboard UI** (`dashboard/templates/dashboard.html`).
- **NEW — LLM narrative layer** (`intelligence/llm.py`): optional, fail-safe
  natural-language layer — CQO executive summary (fast model), deep theme synthesis
  and opportunity storyboards (capable model). No API key → deterministic fallback;
  enabled via `RESEARCH_LLM_ENABLED` + `LLM_PROVIDER`/`LLM_API_KEY`; surfaced in the
  brief, CLI and dashboard tab.
- **NEW — continuous research loop** (`intelligence/scheduler.py` + `main.py`):
  singleton-guarded `ResearchScheduler` starts with the bot when
  `RESEARCH_ENABLED=true` (interval `RESEARCH_INTERVAL_MINUTES`); also
  `python3 launcher.py research --interval 120 --llm` for a foreground loop.
- **NEW — deeper per-agent capabilities**: Scout reports data-health/readiness +
  stale artifacts; Prober runs out-of-sample revalidation probes + Monte Carlo
  stress; Analyst adds an ML regime-model insight and `oos-degradation` flags;
  Strategist specs include suggested capital allocation, MC tail-risk and a
  diversification note.
- **NEW — human-gated deployment** (`intelligence/deploy.py`): the CQO proposes
  the top opportunity (`auto_deploy_top` / `launcher.py research --deploy` /
  dashboard `POST /api/intelligence/deploy`); a human approves it
  (`--approve <id>` / dashboard); `main.py` then applies the approved params to

- **NEW (v4) — self-aware consensus + risk rehearsal + empirical benchmark**
  (`RESEARCH/INSIGHTFORGE_QUANT_V4.md`):
  - **Source-correlation penalty** (`intelligence/consensus/engine.py`): VIF-
    based independence correction — `agreement_index` now measures the share
    of *independent* evidence (backtest ↔ trend filter double-counting is
    punished); MarketView gains `effective_n`, `max_vif`, `diversity_penalty`,
    `raw_agreement_index`; per-source `vif`/`independent_weight` recorded.
  - **Kill-switch drill** (`intelligence/execution/live_apply.py` +
    `/api/intelligence/kill_drill`): replay the last N consensus snapshots
    through the live kill conditions — what WOULD have fired, no broker touch.
  - **Possibility cones** (`analysis/monte_carlo.py` +
    `/api/intelligence/risk_cone`): bootstrap Monte-Carlo forward 5/50/95
    percentile cone from realized trade PnL + P(profit)/P(ruin)/VaR tiles.
  - **Phase-4 empirical toolkit** (`intelligence/research_stats.py`):
    PBO/CSCV, Deflated Sharpe, calibration curves, CPCV splits, and a
    benchmark runner producing `intelligence/output/benchmark_report.json`
    from real artifacts (PBO 0.25 on a thin 2×8 breakout matrix; DSR 0.23,
    SR0 2.19; live RF Brier 0.308 / 52% hit-rate; CPCV 5×101).
  - **7th deployment gate** `DEPLOY_MAX_PBO` (optional — enforced only when
    the corpus yields a PBO estimate; missing ⇒ `enforced=false`, non-blocking).
  - **Dashboard**: Consensus Weather Radar (polar plot), click-to-open “Why”
    attribution drawer, one-click 🧪 Kill Drill timeline, 🎯 Possibility Cone
    block — all in the 🤖 Agent Team tab.
  - **Single UI — the Flask engine dashboard only**: the v4 war-room lives
    entirely in `dashboard/templates/dashboard.html` (🤖 Agent Team tab):
    interactive weather radar (floating hover tooltips + click-through to the
    why-drawer), per-source attribution drawer, scenario-capable kill drill
    (what-if drawdown/floor/snapshot sliders) and a tunable possibility cone
    (horizon/capital controls + hover crosshair readout).  The Next.js webapp
    is intentionally untouched — no duplicate/divergent features.
  - **Advanced interactivity**: kill-switch overrides are evaluated server-side
    (`evaluate_kill_switches(overrides=...)`) so drill scenarios never touch the
    live guard config; `/api/intelligence/kill_drill` accepts `drawdown_pct` /
    `consensus_floor`, `/api/intelligence/risk_cone` accepts `initial` capital.
  - **Advanced (v4.1) — the desk confronts its own track record**: interactive
    **belief curve** (time-travel replay — click any past view to re-see what
    the desk believed, colored by realized outcome), a per-source **hit-rate
    scorecard** (calibration beats accuracy: who calls it right, not who is
    loudest), a **regime-confusion alarm** (high-confidence brain voting hard
    against consensus → visual banner + log), and a **kill sensitivity matrix**
    (fired % per drawdown×floor threshold grid via
    `/api/intelligence/kill_drill?matrix=1`). Realized-outcome scoring lives in
    `intelligence/research_stats.py::score_consensus_history`.
  the live strategy on next start. Nothing reaches the engine without approval.
- **NEW — deployment gate on the dashboard UI**: the 🤖 Agent Team tab now has a
  full approval panel — 🛠 Propose Top Opportunity, per-opportunity 🛠 Deploy
  buttons, a deployment ledger (proposed/approved/rejected/superseded with
  consistent-cycle counts), and ✓ Approve / ✕ Reject buttons (no terminal needed).
- **NEW — Consensus Engine (v3, `intelligence/consensus/`)**: the three brains
  (Kronos forecast, RF regime model, backtest/walk-forward probes, trend filter,
  LLM verdict) cast typed `Signal`s fused by weighted vote into one attributed
  `MarketView` (direction / agreement / consensus_strength / per-source why +
  disagreements). Fail-safe: missing brains never block a cycle.
- **NEW — LLM cross-validation + fact-check (v3, `intelligence/llm.py`)**:
  capable model challenges the evidence bundle with a structured JSON verdict
  (`cross_validate`); a deterministic `fact_check_verdict` rejects any citation
  not verbatim in the bundle; `explain_market_view` writes the "why".
- **NEW — hard deployment quality gates (v3, `intelligence/deploy.py`)**:
  min trades ≥ 30, Sharpe ≥ 0.8, OOS consistency ≥ 0.6, MC prob-profit ≥ 60%,
  qRICE ≥ 0.03, drawdown ≤ 20%. Failing proposals are `blocked_by_gates`;
  legacy pre-gate approvals are re-validated at engine start; force-approve is
  auditable (`approved_by="human:FORCE"`). The two shipped negative-Sharpe
  approvals were voided.
- **NEW — execution layer (v3, `intelligence/execution/`)**: `TradeExecutionAdvisor`
  (consensus + gates + Kronos alignment → auditable trade with reason chain and
  VaR-informed sizing), `ShadowForwardTester` (forward-test an approved
  deployment on a held-out window before live promotion), and
  `live_apply.evaluate_kill_switches` (drawdown / consensus collapse / regime
  flip) + `apply_hot` (hot-reload approved params onto the running strategy).
  Wired into the engine via `main.py._execution_guard()`.
- **NEW — dashboard wiring (v3, ADVANCED-GRADE UI)**: Flask
  `/api/intelligence/market_view`, `/api/intelligence/advise`,
  `/api/intelligence/shadow` (GET history + POST run), `/api/intelligence/execution`
  (kill-switch config + live consensus strength + drawdown + hot-applied log),
  and `/api/intelligence/scheduler` (GET status + POST start/stop), plus
  force-approve/void deploy actions. **Both** dashboards render the v3 panels;
  the gridbot's Agent Team tab (`dashboard/templates/dashboard.html`) is now
  advanced-grade: consensus meter (BULL↔BEAR gradient + marker), agreement /
  strength dual bars, per-source diverging contribution bars with expandable
  evidence, consensus-history sparkline, Trade Execution Advisor with risk
  gauge + gate progress bars, Execution Guard panel (kill-switch tiles,
  drawdown vs threshold bar, hot-applied deployments), deployment status filter
  chips + aggregate gate summary + confirm dialogs for Force/Void + shadow-test
  history, and research-loop Start/Stop controls with a live next-cycle
  countdown — all auto-refreshing (30s).
- **NEW — config knobs (v3)**: `CONSENSUS_*`, `DEPLOY_*`, `EXEC_*`, `SHADOW_*`
  env-tunable defaults in `config.example.py`.
- **NEW — research paper v3**: `RESEARCH/INSIGHTFORGE_QUANT_V3.md` documents the
  consensus model, LLM fact-checking, deployment gates, shadow forward-testing
  and execution kill-switches.
- **NEW — tests (v3)**: deployment gates (blocked / force / legacy re-validation),
  consensus fusion + attribution + ledger roundtrip, signal adapters, LLM
  fact-check, advisor (hold/trade/block), shadow tester, kill-switches.

- **NEW — full pipeline on the dashboard**: last completed brief loads on page
  open (`/api/intelligence/last_brief` — narrative + deployment + themes);
  LLM-layer telemetry tiles (enabled/provider/answered_by); corpus coverage
  strip (symbol × bars); continuous-loop status + cycles + auto-approve config
  (`/api/intelligence/scheduler`); and strategy-spec detail on opportunities
  (allocation %, Monte Carlo, risk gates).
- **NEW — auto-approve after N consistent cycles**: `--auto-approve N` /
  `RESEARCH_AUTO_APPROVE_CYCLES` — a deployment is only auto-approved after the
  same strategy+params is the top opportunity for N consecutive cycles
  (`DeploymentManager.consider_auto_approve`); a change of top resets/supersedes.
- **NEW — breakout-strategy deployments**: `PARAM_ALIASES` maps param names to
  live breakout attributes (lookback_4h, threshold /100, TP string→float list,
  Kronos flag); propose via `--deploy-strategy breakout_strategy` or dashboard
  `{"action":"propose","strategy_key":"breakout_strategy"}`.
- **NEW — correlation-aware theming**: the Analyst computes pairwise return
  correlations across the multi-symbol corpus and emits a **Cross-Symbol
  Correlation Insight** theme (high-correlation-cluster flag → treat as
  correlated bets / diversify); per-strategy themes now record the symbol.
- **NEW — multi-symbol corpus**: `intelligence/data.py` loads per-symbol cached
  CSVs (gold_data.csv, SIF.csv, CLF.csv); the Prober probes each symbol with
  cached history and tags probes; `refresh_multi_symbol.py` downloads the corpus
  (`--symbols GC=F,SI=F,CL=F`); `RESEARCH_SYMBOLS` config + `--symbols` CLI.
- **NEW — prompt tuning**: calibrated narration prompts (`_PROMPTS` constants in
  `intelligence/llm.py`) with structured output, "never invent statistics" and
  the human-approval gate, plus per-narration temperatures (summary 0.3, deep
  synthesis 0.4).
  Research paper in `RESEARCH/INSIGHTFORGE_QUANT_V2.md`. **45→46 tests.**
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
   (The v3 quality gates + shadow forward-test now block deploying anything
   that fails this bar, but the *strategy itself* still needs re-tuning.)
2. **ML uplift**: retrain with balanced data + feature selection; target >60%
   accuracy so the RF regime vote in the consensus gets stronger.
3. **Live hardening**: bridge auto-reconnect, order-state reconciliation,
   idempotent commands; then run the ShadowForwardTester on real forward data
   before promoting any deployment to live (Tier 1/2 auto-execution).
4. **Productization**: real Supabase auth, Stripe checkout, subscription-gated
   features (the new Consensus + Execution panels are Professional-tier).
5. **Infrastructure**: Docker for engine + webapp, CI pipeline, monitoring
   (health/alerting on consensus disagreement spikes + kill-switch firings).
6. ~~Research v3 → v4~~ **DONE** — empirical benchmark shipped in
   `RESEARCH/INSIGHTFORGE_QUANT_V4.md` with real numbers (PBO/CSCV, DSR,
   live RF calibration, CPCV). **Next**: enrich the probe corpus (more configs)
   so PBO becomes statistically meaningful; batch the LLM fact-check hit-rate
   once an API key is configured; benchmark Kronos once the HF model is downloaded.

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
