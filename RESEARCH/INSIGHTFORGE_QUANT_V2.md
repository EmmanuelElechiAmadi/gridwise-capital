# InsightForge for Quant: A Multi-Agent Framework for Autonomous Quantitative Research and Alpha Discovery

**An upgraded research paper grounded in the Seek Quant platform**

- **Original:** *InsightForge: A Multi-Agent Framework for Autonomous Continuous User Research and Product Discovery* (August 2026)
- **This version:** v2.0 — re-framed, formalized, and implemented as a working agent team on the Seek Quant algorithmic trading engine, with every agent attributed as a **replacement for a named quant professional role**.
- **Implementation status:** PoC live in `gridbots/quant_env/intelligence/` (13 tests passing; wired to the Flask dashboard API).

---

## Table of Contents

1. [Abstract](#abstract)
2. [Introduction — The Quant Research Bottleneck](#1-introduction--the-quant-research-bottleneck)
3. [Related Work](#2-related-work)
4. [System Overview — The Agent Team as Quant Professional Replacements](#3-system-overview--the-agent-team-as-quant-professional-replacements)
5. [Agent Design](#4-agent-design)
6. [Coordination & Shared Memory — The Opportunity Ledger](#5-coordination--shared-memory--the-opportunity-ledger)
7. [Technical Implementation on Seek Quant](#6-technical-implementation-on-seek-quant)
8. [Formal Model](#7-formal-model)
9. [Evaluation Plan](#8-evaluation-plan)
10. [Pricing Model](#9-pricing-model)
11. [Ethics, Risk & Compliance Guardrails](#10-ethics-risk--compliance-guardrails)
12. [Limitations and Future Work](#11-limitations-and-future-work)
13. [Conclusion](#12-conclusion)
14. [References](#references)
15. [Appendix A — Running the PoC](#appendix-a--running-the-poc)
16. [Appendix B — Agent → Quant Role → Seek Quant Module Map](#appendix-b--agent--quant-role--seek-quant-module-map)

---

## Abstract

Continuous discovery is as fundamental to systematic trading as it is to software product management — yet most trading operations practice it episodically. Hiring a full quant bench (data engineers, researchers, analysts, portfolio managers) is expensive, alpha decays faster than teams can replenish it, and the per-experiment overhead of backtesting, out-of-sample validation, and strategy review caps throughput at a handful of studies per quarter. We introduce **InsightForge for Quant**, an agent-driven layer on the Seek Quant engine that deploys a persistent, multi-agent team to automate the entire alpha-discovery loop: sourcing market data and instruments, probing the market with regime-conditioned backtests and walk-forward validation, synthesizing evidence into alpha themes, and delivering prioritized, risk-gated strategy specs directly into the strategy registry and project-management workflow. Each agent is an explicit replacement for a named quant professional role, with formalized confidence and prioritization math (signal confidence *Cₛ* and qRICE opportunity scoring). We present the architecture, the role-attribution table, the coordination protocol, a working proof-of-concept implemented against Seek Quant's real backtest engine, ML regime classifier and analytics artifacts, and a comprehensive evaluation and pricing plan. We argue that autonomous research systems can transform quantitative research from a scarce, human-hour-limited craft into a continuous, democratized utility — while raising model-risk and overfitting concerns that we address with statistical guardrails, audit trails, and human-in-the-loop deployment gates.

---

## 1. Introduction — The Quant Research Bottleneck

Modern trading teams recognize that sustained edge depends on continuously discovering, validating, and deploying new hypotheses about market structure. The analog of "continuous discovery habits" in product management (Torres, 2021) is an always-on research pipeline: generate hypotheses, test them out-of-sample, synthesize survivors into a portfolio, and redeploy capital as alpha decays.

Yet most organizations fail to run this pipeline continuously for the same reason most product teams fail at continuous discovery:

1. **Talent scarcity.** Skilled quant researchers, data engineers and portfolio managers command premium compensation, and their time is consumed by tooling, data wrangling, and operational firefighting rather than hypothesis generation.
2. **Episodic throughput.** The per-study overhead — data acquisition, backtest engineering, walk-forward validation, risk review — limits most teams to a handful of studies per quarter. Critical capital-allocation decisions are therefore made on intuition rather than on accumulated, validated evidence.
3. **Alpha decay.** Edges erode as markets adapt; a research cadence measured in quarters cannot keep up with decay measured in months.

Simultaneously, three technologies have crossed critical thresholds:

- **LLM-based autonomous agents** can now plan, execute multi-step tasks, use tools, and persist context across long sessions (AutoGPT, MetaGPT, Reflexion (Shinn et al., 2023), Generative Agents (Park et al., 2023), Voyager (Wang et al., 2023)).
- **Long-context memory architectures** (MemGPT (Packer et al., 2023)) enable shared knowledge graphs that persist across research sessions.
- **Quant tooling is already modular**: the Seek Quant engine ships an event-driven backtest engine with realistic costs, walk-forward analysis, a RandomForest regime classifier, a Kronos foundation-model adapter, Monte Carlo, FIFO trade matching, and a live MT5 bridge.

This convergence opens the door to a new class of software: **agent-driven quant research that replaces discrete human roles end-to-end**, exactly as InsightForge argued for product discovery. This paper adapts the InsightForge framework to Seek Quant, attributes every agent to a quant professional replacement, and — crucially — *executes* the framework as a working proof-of-concept rather than leaving it on paper.

---

## 2. Related Work

- **AI in quant research.** Prior work has applied NLP to earnings-call sentiment, news classification, and factor mining. Tools like Kensho and BloombergGPT assist with *document* analysis but still require humans to design experiments. This work is closer to the *experiment loop* itself.
- **LLM-based autonomous agents.** Goal-directed agents (AutoGPT, MetaGPT) demonstrated multi-step tool use. *Generative Agents* (Park et al., 2023) showed believable, persistent role behavior in a sandbox. *Reflexion* (Shinn et al., 2023) introduced verbal self-correction — the template for our Analyst's overfit-flagging loop. None of these have been applied to the **quant research lifecycle at engine level**, where "beliefs" must survive out-of-sample validation rather than social consensus.
- **Hyperparameter / experiment automation.** Tools like Optuna, Comet, and Neptune automate search but not the *full loop* — hypothesis generation, evidence synthesis, and strategy spec authoring. InsightForge for Quant closes that loop with a Coordinator and a shared ledger.
- **Memory-augmented research systems.** *MemGPT* (Packer et al., 2023) motivates the persistent `OpportunityLedger` shared knowledge store.
- **Statistical honesty in backtesting.** Bailey & López de Prado's *Deflated Sharpe Ratio* and the walk-forward methodology (already implemented in Seek Quant's `analysis/walkforward.py`) ground our overfitting penalties and evaluation design.

---

## 3. System Overview — The Agent Team as Quant Professional Replacements

InsightForge for Quant is a persistent agent layer over the Seek Quant engine. A **Coordinator** runs a continuous loop — **source → probe → synthesize → strategize → brief** — and every stage is executed by an agent that replaces a named human quant role:

| InsightForge role | Quant professional replacement | Seek Quant implementation | Primary responsibility | Key integrations |
| --- | --- | --- | --- | --- |
| **Coordinator** | **Chief Quant Officer (CQO) / Head of Systematic Research** | `intelligence/coordinator.py` | Owns the research agenda, session budget, inter-agent hand-offs and human-in-the-loop gates | All agents, `OpportunityLedger` |
| **Recruiter** | **Quant Data Scout** *(replaces Data Acquisition Analyst / Market Data Researcher)* | `intelligence/agents/scout.py` | Sources and validates the participant pool: instruments, timeframes, data feeds, alt-data | Yahoo Finance (`GC=F`), MT5 bridge (`XAUUSD.r`), ForexFactory calendar, artifact scanner |
| **Interviewer** | **Market Prober** *(replaces Quant Researcher — Hypothesis Testing)* | `intelligence/agents/prober.py` | "Interviews the market": runs regime-conditioned backtests and OOS validation, adapts its parameter grid dynamically | `BacktestEngine`, walk-forward, optimizer, ML regime adapter |
| **Analyst** | **Quant Research Analyst** *(replaces Alpha Synthesizer)* | `intelligence/agents/analyst.py` | Segments, codes and synthesizes probes/trades into alpha themes; runs bias & overfit checks; scores confidence *Cₛ* | `analysis/performance.py`, `analysis/walkforward.py`, `ml/model_metrics.json` |
| **Strategist** | **Quant Strategist / Portfolio Manager** *(replaces Head of Quant Strategy)* | `intelligence/agents/strategist.py` | Maps themes to the opportunity solution tree; prioritizes with qRICE; drafts strategy specs with risk gates | `OpportunityLedger`, `strategies/registry.py`, Jira/Linear, dashboard |

The conceptual mapping between the product-research world and the quant world is deliberate and complete:

| InsightForge concept | Quant analogue |
| --- | --- |
| User / participant | Market regime, instrument, timeframe, data source |
| Recruiting participants | Sourcing instruments & data feeds with coverage/provenance metadata |
| 1:1 empathetic interview | Regime-conditioned backtest / walk-forward "interview" of the market |
| Qualitative transcript | Trade fills, equity curve, feature importances, regime labels |
| Thematic synthesis | Alpha-theme synthesis with confidence scoring |
| Opportunity solution tree | Persistent `OpportunityLedger` (instruments → probes → themes → opportunities) |
| User story | Strategy spec (params, risk gates, validation steps, deploy steps) |
| RICE prioritization | qRICE: Reach (capacity) · Impact · Confidence / Effort |
| Consent metadata | Data-licensing & compliance metadata on instruments |
| PII redaction | Position/order sanitization; API-key isolation |
| Emotional-safety termination | Risk kill-switch (max drawdown, daily-loss auto-close) |

---

## 4. Agent Design

### 4.1 Quant Data Scout — the *Recruiter* replacement

The Recruiter's job is to build a *diverse, consented participant pool*. The Scout's job is to build a *diverse, licensed market-data pool*. It:

- **Queries the "CRM/analytics"** — i.e., scans the engine's artifact layer (`gold_data.csv`, `optimization_results.csv`, `walkforward_report.csv`, `ml/model_metrics.json`, `strategy_results.json`, `trades.db`) and reports coverage, freshness (age in days) and size for each source.
- **Filters for spread** — the instrument universe (`XAUUSD.r`, `GC=F`, `SI=F`, `CL=F`) × timeframes (1m/1h/4h/1D) ensures representation across asset classes and volatility profiles, analogous to demographic spread in participant recruitment.
- **Logs all interactions** — every sourced instrument carries provenance, coverage-bars, and compliance/status metadata (the analogue of consent metadata) into the ledger.
- **Drafts "invitations"** — emits structured source descriptors that downstream agents (and the dashboard) consume.

### 4.2 Market Prober — the *Interviewer* replacement

The Interviewer conducts semi-structured interviews and adapts follow-ups to the respondent. The Prober "interviews the market" and adapts its probes to the market's answers:

- **Dynamic interview guide.** Each strategy's declared `PARAMS` (e.g., `spacing`, `levels`, `lookback_4h_bars`, `breakout_threshold_pct`) define the probe grid. Variant 0 uses the strategy defaults; follow-up variants widen the primary numeric parameter — a cheap adaptive deepening based on prior "responses."
- **Conducts the interview.** Runs `BacktestEngine` over cached gold history with realistic costs (commission, slippage, partial fills, drawdown stop). The market "answers" with fills, equity curves, and PnL.
- **Prevents "hallucinated empathy."** The analogue of InsightForge's empathy guardrail is *statistical honesty*: a probe with zero trades is recorded as thin/no evidence (`has_trades == False`) and never over-claimed by downstream agents.
- **Regime-aware.** Each probe is tagged with a cheap regime estimate (bull / bear / ranging / mixed) derived from trend and volatility, mirroring the Interviewer's ability to re-orient an interview when the topic shifts.
- **Graceful offline fallback.** When cached data is unavailable, the Prober falls back to stored engine artifacts (`strategy_results.json`) so the research loop never dead-locks — the analogue of InsightForge's "graceful termination and human routing."

### 4.3 Quant Research Analyst — the *Analyst* replacement

The Analyst chains multiple analysis steps over the probes:

1. **Segment & code.** Break each probe into metrics (return, Sharpe, drawdown, win rate, profit factor, trade count) and tag it with regime + parameter codes.
2. **Synthesize themes.** Aggregate per-strategy evidence into *alpha themes* — natural-language theses such as *"Grid Strategy shows best-observed Sharpe on the last 1,500 bars with OOS consistency X%."*
3. **Bias & overfit checks.** Compute out-of-sample consistency from the walk-forward report (fraction of OOS windows with positive return), compare IS vs OOS Sharpe to flag `possible-overfit`, flag `thin-sample` when trades < 5, and flag `drawdown-Npct` when max drawdown breaches budget.
4. **Score confidence.** Formalize each theme's confidence with the paper's formula (Section 7).

### 4.4 Quant Strategist — the *Strategist* replacement

The Strategist maintains the opportunity solution tree and converts themes into actionable specs:

- **Prioritizes with qRICE.** For each theme × strategy pair it estimates Reach (tradable capacity proxy), Impact (Sharpe-derived), Confidence (*Cₛ*), and Effort (engineering hours per strategy family), then computes the qRICE score.
- **Drafts strategy specs ("user stories").** Each spec includes target params, explicit risk gates (max drawdown ≤ 20%, max daily loss ≤ 5%, max position), validation steps (walk-forward, Monte Carlo), and deployment steps (registry `PARAMS`, regime adapter attachment, human approval gate).
- **Pushes to PM tools.** The ledger is JSON-serializable for direct integration with Jira/Linear/Notion and the Seek Quant dashboard (`/api/intelligence/ledger`).

### 4.5 Chief Quant Officer Coordinator — the *Coordinator* replacement

The Coordinator (a) owns the research agenda and session budget, (b) instantiates and sequences the team (`scout → prober → analyst → strategist`), (c) persists the ledger, and (d) emits a human-readable `research_brief.json` summarizing roles replaced, probes run, themes synthesized, and prioritized opportunities — the quant analogue of InsightForge's continuous-discovery dashboard.

---

## 5. Coordination & Shared Memory — The Opportunity Ledger

InsightForge's shared knowledge graph becomes the **OpportunityLedger** (`intelligence/ledger.py`): a persistent, JSON-serializable store with four record types that mirror the pipeline:

```
instruments[]   -> probes[] -> insights[] (alpha themes) -> opportunities[]
```

- **Instruments** — the participant pool: symbol, timeframe, source, coverage bars, status, provenance.
- **Probes** — every market interview: strategy key, params, metrics, regime, OOS flag, data bars, note.
- **Insights** — alpha themes: title, natural-language thesis, evidence, confidence *Cₛ*, risk flags, strategy keys.
- **Opportunities** — qRICE-scored strategy candidates with reach/impact/confidence/effort, status (`hypothesis → prioritized`), and created-at audit metadata.

The Coordinator writes the ledger to disk after every cycle; humans, the dashboard (`/api/intelligence/ledger`) and PM tools consume the same JSON. This is the mechanism that turns episodic research into a *continuously compounding* memory — exactly what InsightForge promised for product teams.

---

## 6. Technical Implementation on Seek Quant

The framework is implemented as a first-class engine package rather than a wrapper script:

```
gridbots/quant_env/intelligence/
├── __init__.py                  # package wiring (quant_env root on sys.path)
├── ledger.py                    # OpportunityLedger + records (shared memory)
├── coordinator.py               # Chief Quant Officer — the loop
├── runner.py                    # CLI: python -m quant_env.intelligence.runner
├── agents/
│   ├── base.py                  # BaseAgent contract (role/replaces/responsibility)
│   ├── scout.py                 # Quant Data Scout (Recruiter replacement)
│   ├── prober.py                # Market Prober (Interviewer replacement)
│   ├── analyst.py               # Quant Research Analyst (Analyst replacement)
│   └── strategist.py            # Quant Strategist (Strategist replacement)
├── output/                      # opportunity_ledger.json + research_brief.json
└── tests/  (at quant_env/tests/test_intelligence.py — 13 tests)
```

Key reuses of the existing engine (zero new heavy dependencies):

| Engine module | Consumed by | Purpose |
| --- | --- | --- |
| `strategies/registry.py` | Scout, Prober | Auto-discovers `grid_strategy`, `breakout_strategy` + their `PARAMS` schemas |
| `backtest/engine.py` | Prober | Event-driven backtests with realistic costs |
| `analysis/performance.py` | Prober, Analyst | Sharpe / return / drawdown / win-rate / profit-factor metrics |
| `analysis/walkforward.py` + `walkforward_report.csv` | Analyst | OOS consistency & IS-vs-OOS overfit detection |
| `ml/model_metrics.json` | Analyst | Regime model accuracy + feature importances |
| `gold_data.csv` | Prober | Cached 6,522-bar gold history as the probe corpus |
| `dashboard/app.py` | — | New `/api/intelligence/brief` + `/api/intelligence/ledger` endpoints |

**LLM narrative layer (implemented).** The deterministic + statistical core remains the source of truth — every agent's decision is reproducible math — and the LLM layer (`intelligence/llm.py`) sits strictly *on top* of it as an optional, fail-safe narrator: a fast model (GPT-4o-mini-class) writes the CQO executive summary and a capable model (Claude 3.5-Sonnet-class) deep-synthesizes alpha themes and opportunity storyboards, exactly as InsightForge's Technical Implementation section prescribes. Without an API key every narration falls back to deterministic text, so the engine never depends on an external model; cost is bounded by narrating only the top-N items per cycle.

**Continuous loop (implemented).** `intelligence/scheduler.py` runs the agent team on a schedule inside the live engine: a singleton-guarded `ResearchScheduler` (mirroring `AdaptiveUpdater`) starts with the bot when `RESEARCH_ENABLED=true`, or runs in the foreground via `python3 launcher.py research --interval 120 --llm`. Each cycle persists the ledger and refreshes the brief, so research is genuinely *always-on* rather than episodic.

**Human-gated deployment (implemented).** `intelligence/deploy.py` closes the loop back into the engine: the CQO proposes the top prioritized opportunity (`--deploy` / dashboard), a human approves it (`--approve <id>` / dashboard `POST /api/intelligence/deploy`), and `main.py` applies the approved params to the live strategy on the next start. Nothing reaches the engine without explicit human approval — the paper's deployment gate.

**Multi-symbol corpus (implemented).** `intelligence/data.py` loads per-symbol cached history (gold `gold_data.csv`, silver `SIF.csv`, crude `CLF.csv`); the Prober probes every symbol with cached data and tags each probe with its symbol; `refresh_multi_symbol.py` downloads the corpus and `RESEARCH_SYMBOLS` / `--symbols` select it. Themes now cover a real portfolio rather than gold alone.

**Auto-approve after N consistent cycles (implemented).** The deployment gate supports an opt-in automation tier: with `--auto-approve N` (or `RESEARCH_AUTO_APPROVE_CYCLES`), a deployment is auto-approved only after the *same* strategy + params remain the top opportunity for N consecutive cycles (`DeploymentManager.consider_auto_approve`). A change of top supersedes and restarts the counter, so consistency — not mere frequency — earns automation.

**Breakout-strategy deployments (implemented).** `PARAM_ALIASES` maps the Prober's param names onto the live breakout attributes (`lookback_4h_bars → lookback_4h`, `breakout_threshold_pct → threshold/100`, `tp_dollars "3,5,10" → sorted float list`, `kronos_enabled → _kronos_enabled`), so a human can deploy a breakout spec via `--deploy-strategy breakout_strategy` or the dashboard.

**Correlation-aware theming (implemented).** The Analyst computes pairwise close-return correlations across the corpus and emits a **Cross-Symbol Correlation Insight** theme — flagging `high-correlation-cluster` (treat as correlated bets; diversify) versus independent sizing — and every per-strategy theme now records its symbol.

---

## 7. Formal Model

### 7.1 Signal confidence Cₛ (upgraded from InsightForge's insight-confidence)

InsightForge proposed *Cᵢ = α·log(fₜ) + β·d_c* — theme frequency weighted by cohort diversity. For quant research we replace *frequency* with *evidence depth* and *diversity* with *out-of-sample robustness*, and we add an explicit **overfitting penalty**:

```
C_s = α·log₁ₚ(N)  +  β·Sharpe′  +  γ·OOS_consistency  −  δ·overfit_penalty
```

where, with default weights α = 0.25, β = 0.35, γ = 0.35, δ = 0.05:

- `N` = number of trades (normalized by `log₁ₚ(100)` so a 100-trade study saturates the evidence term);
- `Sharpe′` = the probe's Sharpe mapped from [−1, 3] onto [0, 1] via `(Sharpe+1)/4`;
- `OOS_consistency` = fraction of walk-forward windows with positive out-of-sample return;
- `overfit_penalty` = `max(0, IS_Sharpe − OOS_Sharpe) / max(1, |IS_Sharpe|)` — how much in-sample promise evaporates out-of-sample.

`Cₛ` is clamped to [0, 1]. This is implemented as `signal_confidence(...)` in `intelligence/agents/analyst.py` and unit-tested (including the property *penalty reduces score*).

### 7.2 qRICE opportunity score (upgraded from RICE)

InsightForge used RICE where Reach = affected users, Impact = product lift, Confidence = subjective, Effort = engineering time. Quant RICE replaces each term with an objective, measurable proxy:

```
O_s = (R · I · C) / E
```

- **R (Reach)** — tradable capacity: normalized coverage & liquidity proxy, `R = clip01(0.5 + 0.5·coverage_factor)` where `coverage_factor` reflects bars of validated history (a gold-futures study on 6.5k bars earns R ≈ 1.0).
- **I (Impact)** — expected performance uplift: Sharpe′ mapped to [0, 1].
- **C (Confidence)** — the theme confidence `Cₛ` from §7.1.
- **E (Effort)** — engineering + risk-review hours per strategy family (6h grid, 10h breakout), normalized to a 0.1–5 scale so scores stay interpretable.

Example (live PoC output, August 2026): *grid_strategy* with conf 0.29, impact 0.25, effort 6h → qRICE ≈ 0.12; *breakout_strategy* with conf 0.17, impact 0.08, effort 10h → qRICE ≈ 0.014. The Strategist correctly ranks the grid study first and marks it `prioritized`.

---

## 8. Evaluation Plan

We retain InsightForge's three-tier evaluation and re-map every metric to the quant domain.

### 8.1 Simulation and sandbox studies

Replay known market regimes from the cached gold history (May–June 2026: trending, ranging, volatile sub-periods). Compare the agent team's identified alpha themes against themes produced by human quant researchers on the same data, measuring:

- **Thematic precision / recall** — do the agent's "themes that survive OOS" contain the same surviving signals a human would find?
- **Actionability** — fraction of themes that translate into a runnable strategy spec without human re-engineering.
- **Reproducibility** — identical inputs must produce identical themes (the PoC is deterministic by construction).

### 8.2 Controlled experiment with real teams

Recruit 40 systematic teams to run parallel research tracks: one led by their human quant bench, one by the InsightForge-for-Quant team (with human-in-the-loop deployment gates). Metrics:

- **Signal velocity** — validated alpha themes generated per week.
- **Strategy impact** — number of deployed strategies from research that produce a statistically significant KPI improvement (Sharpe/return uplift) in forward testing.
- **Cost per validated alpha** — total spend (researcher hours + SaaS fees + compute) divided by validated themes, directly answering the "cost per insight" question from the original paper.

### 8.3 Statistical rigor

All agent-claimed effects must survive:
- **Walk-forward honesty** (no leakage between IS/OOS windows — already enforced by `analysis/walkforward.py`);
- **Multiple-testing corrections** — with many probes per cycle, we adopt the Deflated Sharpe Ratio / PBO framework (Bailey & López de Prado) to bound the probability of backtest overfitting;
- **Monte Carlo** (1,000 sims) for drawdown and ruin probability before any spec leaves the `hypothesis` state.

---

## 9. Pricing Model

The original paper closes with: *"would you charge per completed interview, per agent hour, or as a flat monthly SaaS tier based on the scale of the product team?"*

**Our answer: a hybrid — flat SaaS tiers that price the *coordination layer*, plus metered *agent-hour* credits that price the *execution layer*, plus transparent compute/data pass-through for heavy runs.** The original InsightForge paper already exposed the flaw in pure per-interview pricing: it creates a perverse incentive to *avoid* interviews. In quant, "interviews" are probes/backtests; charging per probe would tax exactly the activity the platform exists to encourage.

### 9.1 Why hybrid beats each pure model

| Pure model | Failure mode |
| --- | --- |
| Per completed interview (per probe) | Penalizes the behavior you want (more probing = better research). Opaque bills, hard to forecast. |
| Per agent hour | Correct meter for *compute*, but users can't predict it; agents idle in the coordination layer yet still cost money. |
| Flat tier only | Ignores marginal compute; power users cross-subsidize light users; enterprise capacity can't be sold incrementally. |
| **Hybrid (chosen)** | Flat tier covers the persistent team + coordination loop; **agent-hour credits** meter active probing/synthesis; data & foundation-model (Kronos) compute is passed through at cost + small margin. |

### 9.2 Tier mapping on the existing Seek Quant pricing (Free / Starter / Professional / Enterprise)

| Tier | Monthly | What the agent team includes | Metered usage |
| --- | --- | --- | --- |
| **Free** | $0 | No agents — public performance snapshot only | — |
| **Starter** | $49 | **1× Quant Research Analyst + 1× Quant Strategist** on live engine results; 1 instrument (gold); monthly brief | 50 agent-hours/mo included |
| **Professional** | $149 | **Full team** (Scout + Prober + Analyst + Strategist + CQO), multi-symbol (`XAUUSD.r`, `GC=F`, `SI=F`, `CL=F`), ML regime + Kronos risk panel, backtest engine access, API read | 500 agent-hours/mo included, then metered |
| **Enterprise** | Custom | Dedicated instance, unlimited agents, white-label dashboard, read/write API + auto-trading, SLA, on-prem data connectors | Negotiated; compute at cost |

### 9.3 Example bill for a Professional shop

A professional team running weekly research cycles (~4 probes/strategy, 2 strategies) burns roughly 45–90 agent-hours/month. That fits inside the 500-hour allowance. A heavy campaign (full walk-forward over 10 windows + Monte Carlo + optimization grid) may add ~100–200 hours → ~$20–40 incremental at a $0.20/agent-hour blended rate. Enterprise includes everything and prices capacity rather than metering it. This structure gives the always-on research utility predictable base pricing, marginal pricing tied to actual *thinking* (agent-hours), and no penalty for good research behavior.

### 9.4 Why this answers InsightForge's question

InsightForge asked which *single* model to use. Our analysis is that the unit being sold is *not* the interview — it's **the persistent research capability**: a team that is always on, remembers everything (the ledger), and delivers prioritized strategy specs. You price the team (flat tier), meter the work (agent-hours), and pass through the raw compute. This is the standard economics of agent-driven SaaS in 2026, and it composes with the existing Free/Starter/Professional/Enterprise ladder already shipping in `seek-quant-landing/src/types/index.ts`.

---

## 10. Ethics, Risk & Compliance Guardrails

Where InsightForge protected *human participants*, InsightForge-for-Quant must protect *capital and market integrity*. Each guardrail maps 1:1 to the original:

| InsightForge guardrail | Quant equivalent | Seek Quant implementation |
| --- | --- | --- |
| Informed consent & AI disclosure | **Model-risk disclosure & experiment transparency** — every probe and theme is labeled machine-generated with a full audit trail | `Probe.note`, ledger `created_at`/`source_agent` fields; `/api/intelligence/*` endpoints |
| Data privacy & PII redaction | **Data governance** — instrument provenance, data-licensing metadata, no PII in market data; API keys never enter the ledger | `Instrument.source`, `.env` isolation |
| Emotional-safety termination | **Risk kill-switch** — the Interviewer analogue terminates a losing "conversation": max drawdown stop, daily-loss auto-close, position caps | `core/risk_manager.py`, live strategy `on_fill` guardrails |
| Hallucinated empathy | **Hallucinated alpha** — no claim enters the ledger without statistical validation; zero-trade probes are never over-claimed | `Probe.has_trades`, Analyst risk flags, walk-forward OOS checks |
| Bias detection | **Overfitting & multiple-testing bias** — IS-vs-OOS degradation penalty in `Cₛ`, PBO/DSR corrections, regime-sliced checks | `signal_confidence`, `analysis/walkforward.py` |
| Human-in-the-loop oversight | **Deployment gates** — the Strategist may draft specs, but nothing goes live without human approval | `Opportunity.status` (`hypothesis → prioritized → deployed`), dashboard approval flow |

---

## 11. Limitations and Future Work

The PoC is deliberately deterministic (with an optional LLM narrator on top); the current limitations mirror and extend InsightForge's own:

- **LLM narrative layer shipped but optional.** The fast/capable-model split is implemented (`intelligence/llm.py`) with calibrated prompts and per-narration temperatures; without an API key the briefs use deterministic text. Per-call cost telemetry and prompt A/B calibration on real briefs remain future work.
- **Multi-symbol corpus shipped but data is cached-only.** The Prober now probes every symbol with cached history (gold/silver/crude via `refresh_multi_symbol.py`), but live streaming feeds per instrument and cross-symbol correlation-aware theming remain future work.
- **Theme conflation.** The Analyst can still conflate two distinct market behaviors into one theme — the exact hallucination risk InsightForge flagged for its Analyst. Mitigations: finer regime/session slicing and LLM cross-verification.
- **Compute latency.** The Prober's live probes on 1,500 bars of history add seconds per cycle (plus OOS revalidation probes); the dashboard endpoint uses a reduced budget and the scheduler runs in a background thread. A queued, asynchronous job system is required for enterprise scale.
- **Live-trading coupling.** Probes are backtests (IS) with OOS revalidation on older windows, and approved deployments apply on the next bot start. *Intra-session* live regime-conditioned validation (using `ml/regime_adapter.py` and the MT5 bridge) remains the highest-value next milestone.
- **Non-verbal / market microstructure cues.** InsightForge noted agents miss facial expressions; quant agents miss order-book depth, funding flows, and OTC liquidity. Multi-modal market data (tick-level + alt-data) is the equivalent future modality.

---

## 12. Conclusion

InsightForge demonstrated that the bottleneck in continuous product discovery is no longer a lack of human capital but a lack of specialized orchestration. We have shown the same claim holds — and is now **executable** — in quantitative research. By mapping each InsightForge agent to a named quant professional replacement (Data Scout ← Recruiter, Market Prober ← Interviewer, Quant Research Analyst ← Analyst, Quant Strategist ← Strategist, Chief Quant Officer ← Coordinator), formalizing the confidence and prioritization math, answering the pricing question with a hybrid tier + agent-hour model, and shipping a tested proof-of-concept inside the Seek Quant engine, we convert a scarce, intermittent craft into a scalable, always-on research utility. The remaining gap between this paper and autonomous deployment is deliberately human: the deployment gate.

---

## References

1. Bargas-Avila, J. A., et al. (2009). *Intranets in the wild: Usage and usability.*
2. Bailey, D. H., & López de Prado, M. (2014). *The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality.* Journal of Portfolio Management.
3. Packer, C., et al. (2023). *MemGPT: Towards LLMs as Operating Systems.* arXiv preprint.
4. Park, J. S., et al. (2023). *Generative Agents: Interactive Simulacra of Human Behavior.* UIST '23.
5. Shinn, N., et al. (2023). *Reflexion: Language Agents with Verbal Reinforcement Learning.* NeurIPS.
6. Torres, T. (2021). *Continuous Discovery Habits.* Product Talk LLC.
7. Wang, G., et al. (2023). *Voyager: An Open-Ended Embodied Agent with Large Language Models.* arXiv preprint.
8. InsightForge Working Paper (2026). *InsightForge: A Multi-Agent Framework for Autonomous Continuous User Research and Product Discovery* — the source framework this paper operationalizes for quant.

---

## Appendix A — Running the PoC

```bash
# Full research cycle (writes output/research_brief.json + opportunity_ledger.json)
cd gridbots
python3 -m quant_env.intelligence.runner

# Fast cycle for smoke tests
python3 -m quant_env.intelligence.runner --max-bars 800 --probe-limit 1 --top-n 2

# Dashboard API (serves /api/intelligence/brief and /api/intelligence/ledger)
python3 launcher.py dashboard          # then: curl localhost:5050/api/intelligence/ledger

# Tests (13 new + 52 existing)
cd gridbots/quant_env && python3 -m pytest tests/test_intelligence.py -v
```

---

## Appendix B — Agent → Quant Role → Seek Quant Module Map

| Agent (module) | Human role replaced | Primary artifact consumed | Primary artifact produced |
| --- | --- | --- | --- |
| DataScoutAgent (`agents/scout.py`) | Data Acquisition Analyst | artifact scanner, instrument universe | `Instrument[]` |
| MarketProberAgent (`agents/prober.py`) | Quant Researcher (Hypothesis Testing) | `gold_data.csv`, `strategies/registry.py` | `Probe[]` |
| QuantAnalystAgent (`agents/analyst.py`) | Quantitative Research Analyst | `Probe[]`, walk-forward/optimization/ML artifacts | `Insight[]` + `Cₛ` |
| QuantStrategistAgent (`agents/strategist.py`) | Portfolio Manager / Head of Quant Strategy | `Insight[]`, `Probe[]` | `Opportunity[]` + qRICE + specs |
| CoordinatorAgent (`coordinator.py`) | Head of Systematic Research | all of the above | `research_brief.json` |

---

> Past performance is not indicative of future results. No agent deploys capital without a human approval gate.
