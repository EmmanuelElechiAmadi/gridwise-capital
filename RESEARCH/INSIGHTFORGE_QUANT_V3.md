# InsightForge for Quant v3: Consensus, Guardrails, and Safe Auto-Execution

**An update to *InsightForge for Quant: A Multi-Agent Framework for Autonomous Quantitative Research and Alpha Discovery* (v2.0)**

- **v2.0:** agent team (DataScout → MarketProber → QuantAnalyst → QuantStrategist → CQO), Cₛ / qRICE math, LLM narrative layer, human-gated deployment.
- **v3.0:** this paper — the three "brains" (Kronos foundation model, RandomForest regime model, backtest/walk-forward evidence) are fused into a **single attributed market view**; the LLM becomes a **fact-checked cross-validator**; deployments are gated by **hard statistical quality gates**; and a **shadow-tested execution layer** turns approved research into auditable trades with kill-switches.

---

## 1. Motivation — Why a Common Conclusion?

The v2 agent team already produced themes and opportunities — but the **models that actually drive live decisions never spoke to each other**:

| Brain | Produces | Consumed by | Blind spot |
| --- | --- | --- | --- |
| Kronos | probabilistic forecast, `regime_label`, `trend_strength`, `volatility_forecast` | grid/breakout live adaptation only | no interpretability, no narrative, no statistical validation |
| RandomForest regime | BULL/RANGING/BEAR + class probability | `MetaRegimeAdapter` blend (spacing only) | 51% test accuracy ≈ coin flip |
| Research agents | themes (Cₛ), opportunities (qRICE) | deployment gate | backtest-based, small-sample fragile |
| LLM | narrative after the fact | human reading | can hallucinate numbers |

The result: **no single "market read"**, and — worse — the deployment gate would approve a study with **5 trades, −0.50 Sharpe and 0% Monte-Carlo probability of profit** (observed in `deployments.json`, status `approved`). v3 fixes both with three layers.

## 2. Layer 1 — The Consensus Engine (`intelligence/consensus/`)

### 2.1 Signals — the lingua franca

Every source casts a typed vote:

```
Signal(source, direction∈{BULL,BEAR,RANGING}, strength∈[0,1],
       confidence∈[0,1], horizon, symbol, evidence, note)
```

- `Signal.from_kronos(features)` — regime_label, trend_strength (SNR normalized over 0..2), volatility-penalized confidence.
- `Signal.from_rf_regime(regime, confidence)` — classifier output.
- `Signal.from_backtest(key, metrics)` — **trade-count discount**: a 2-trade Sharpe cannot dominate a 100-trade study; strength = f(SR, OOS consistency, MC prob-profit) × trade-factor.
- `Signal.from_trend_filter(trend, strength)` — cheap deterministic regime estimate.
- `Signal.from_llm_verdict(verdict)` — the cross-validator's structured JSON vote.

### 2.2 Fusion

```
consensus_value = Σ (dir_value * strength * confidence * source_weight) / Σ source_weight
direction = BULL if value > +0.2, BEAR if < −0.2, else RANGING
agreement_index = share of total weight voting with the consensus
consensus_strength = |consensus_value| × agreement_index
```

Source weights: Kronos 1.0, backtest 1.0, RF 0.6, LLM 0.5, trend 0.4.

### 2.3 Attribution — the "why"

Every MarketView records per-source contributions, disagreements, and the raw evidence each vote used:

```
MarketView { direction, direction_value, agreement_index, consensus_strength,
             contributions[ {source, direction, contribution, evidence} ],
             disagreements[ {source, direction, message} ], ... }
```

A conclusion is now *provable*: *"Consensus BULL at 0.54 strength because Kronos voted BULL (trend_strength 1.2, vol 0.02 → +0.31), the grid backtest voted BULL (SR 1.1, OOS 0.8 → +0.28), the RF model voted RANGING (conf 0.51 → +0.00), and no voice dissented."*

### 2.4 Fail-safe

With no signals the view is RANGING, strength 0, with an explicit `insufficient_evidence` flag. Missing brains never block a cycle.

## 3. Layer 2 — LLM as a Fact-Checked Cross-Validator (`intelligence/llm.py`)

The LLM no longer narrates after the fact; it **challenges the team's conclusion on the raw evidence bundle** and votes in the consensus:

1. `cross_validate(evidence_bundle)` — the capable model receives the raw signals, themes and opportunities, and must return **exactly one JSON object** with `direction`, `strength`, `confidence`, `horizon`, `key_risks`, `evidence_cited`.
2. `fact_check_verdict(verdict, bundle)` — **deterministic** verification: every number token in each `evidence_cited` string must exist verbatim in the evidence bundle. A verdict citing a made-up statistic is **discarded** and the LLM vote is simply omitted from the consensus.
3. `explain_market_view(market_view, top_contributions)` — a *why* narrative that must cite the top two contributing sources' exact numbers.

## 4. Layer 3 — Guardrails & Safe Auto-Execution

### 4.1 Hard deployment quality gates (`intelligence/deploy.py`)

A deployment cannot be approved unless **every** gate passes (or a human uses force-approve, which is auditable as `approved_by="human:FORCE"`):

| Gate | Metric | Threshold |
| --- | --- | --- |
| min_trades | `num_trades` | ≥ 30 |
| min_sharpe | `sharpe_ratio` | ≥ 0.8 |
| min_oos_consistency | `oos_consistency` | ≥ 0.6 |
| min_mc_prob_profit | `mc_prob_profit_pct` (nested in `monte_carlo`) | ≥ 60% |
| min_qrice | `qrice` | ≥ 0.03 |
| max_drawdown | `max_drawdown_pct` | ≤ 20% |

- Proposals that fail are recorded as `blocked_by_gates` with a per-gate report.
- `approved_for()` **re-validates** legacy approvals at engine start — a once-approved losing study can no longer reach the live strategy.
- Auto-approval (`RESEARCH_AUTO_APPROVE_CYCLES`) requires N consistent cycles **and** all gates passing every cycle.

### 4.2 Shadow forward-testing (`intelligence/execution/shadow.py`)

An approved deployment is not trusted on backtest alone. `ShadowForwardTester.test(deployment, history, window)` reruns the **real backtest engine** (commission, slippage, partial fills, drawdown stop) on a recent held-out window and promotes to `live_ready` only if the forward curve clears `SHADOW_MIN_TRADES / SHADOW_MIN_SHARPE / SHADOW_MIN_MC_PROB`.

### 4.3 TradeExecutionAdvisor (`intelligence/execution/advisor.py`)

Combines MarketView + deployment quality + (optional) Kronos alignment into a concrete recommendation with a JSON **reason chain** and VaR-informed sizing. Never decides alone — if consensus strength is below minimum, the direction is RANGING, or the deployment fails its gates, the answer is `HOLD` with the failing gates listed.

### 4.4 Kill-switches & hot reload (`intelligence/execution/live_apply.py`, `main.py`)

- `evaluate_kill_switches()` → flatten positions on: drawdown ≥ `EXEC_KILL_MAX_DRAWDOWN_PCT` (default 15%), consensus strength collapse below `EXEC_KILL_CONSENSUS_FLOOR`, or a consensus regime flip against the deployed direction.
- `apply_hot()` — approved deployments are applied to the **running** strategy (no restart) via the canonical `DeploymentManager.apply_to_strategy` transforms.
- Both run inside the engine's `_execution_guard()` loop.

## 5. What Changed On Disk

```
gridbots/quant_env/
├── intelligence/
│   ├── consensus/            NEW — signals.py, engine.py, market_view.py, sources.py
│   ├── execution/            NEW — advisor.py, shadow.py, live_apply.py
│   ├── deploy.py             quality gates + evaluate_quality + force/void
│   ├── llm.py                cross_validate, fact_check_verdict, explain_market_view
│   ├── ledger.py             market_views records (schema v3)
│   ├── coordinator.py        consensus step in run_cycle; market_view in brief
│   └── output/
│       ├── deployments.json  voided the two pre-gate negative-Sharpe approvals
│       └── shadow_reports.json   NEW
├── dashboard/app.py          /api/intelligence/{market_view,advise,shadow} + force/void deploy
├── dashboard/templates/dashboard.html   Agent Team tab: consensus + advisor + gate chips + force/void/shadow
├── config.example.py         CONSENSUS_* / DEPLOY_* / EXEC_* / SHADOW_* knobs
├── main.py                   _execution_guard() (kill-switch + hot-apply) + drawdown tracking
└── tests/test_intelligence.py   +18 tests (gates, consensus, advisor, shadow, kill-switch)
```

## 6. How to Use

```bash
# Run a research cycle → brief now contains the consensus MarketView
cd gridbots && python3 launcher.py research

# See the advisor's recommendation for the current consensus
python3 launcher.py research --advise

# Approve a deployment (blocked by gates unless quality passes)
python3 launcher.py research --approve <id>
python3 launcher.py research --force-approve <id>    # auditable override

# Forward-test an approved deployment before it goes live
python3 launcher.py research --shadow <id>

# Dashboard
python3 launcher.py dashboard     # then open the Intelligence page on :3000
```

## 7. Ethics, Risk & Compliance (v3 additions)

- **Auditability:** every gate result, force-approval, recommendation reason-chain and shadow report is persisted and exposed on the dashboard.
- **No silent auto-execution:** the advisor's default output is `HOLD`; auto-execution requires the consensus strength gate, deployment quality gates and (before live promotion) a passing shadow forward-test.
- **Kill-switches are the last line of defense** against consensus collapse, regime flips and drawdown breaches — and they can be independently disabled via env for staging.

> Past performance is not indicative of future results. No agent deploys capital without the human approval gate. This paper documents the v3 architecture; the empirical benchmark (PBO/DSR, LLM fact-check hit-rate, Kronos-vs-RF-vs-blend accuracy) is scheduled as Phase 4 of the roadmap.

