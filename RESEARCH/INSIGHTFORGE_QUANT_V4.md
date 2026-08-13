# InsightForge for Quant v4: From Architecture to Evidence

**Self-aware consensus, risk rehearsal, and the Phase-4 empirical benchmark**

- **v2.0:** agent team (DataScout → MarketProber → QuantAnalyst → QuantStrategist → CQO), Cₛ / qRICE math, LLM narrative layer, human-gated deployment.
- **v3.0:** consensus of three brains (Kronos + RF + backtests + LLM) into one attributed MarketView, fact-checked LLM cross-validator, hard quality gates, shadow forward-testing, kill-switches.
- **v4.0 (this paper):** the system learns to *explain itself* (source-correlation penalty, per-source “why” drawer), *rehearse its own failure* (kill-switch drill, Monte-Carlo possibility cones), and *prove its edge — or admit it has none* — with a Phase-4 empirical benchmark (PBO/CSCV, Deflated Sharpe, live RF calibration, CPCV) run on the repository's real artifacts and published as numbers.

---

## 1. Motivation — The Next Leap Is Evidence, Not Agents

The v3 paper shipped the *architecture*: a consensus layer, quality gates, and safe auto-execution. What it did not ship was *numbers*. The roadmap deferred Phase 4 explicitly — PBO/DSR, LLM fact-check hit-rate, Kronos-vs-RF-vs-blend accuracy, shadow-forward results — to future work.

v4 closes that gap and adds the second half of the thesis: **the dashboard stops being a monitoring panel and becomes a war-room for self-awareness.** Three changes make that concrete:

1. **The consensus now knows its own redundancy.** Two brains built from the same bars (e.g. the grid backtest and the trend filter) can double-count the same information. v4 applies a variance-inflation (VIF) correction so `agreement_index` means what it claims: the share of *independent* evidence behind a call.
2. **The desk can rehearse failure without touching the broker.** A kill-switch drill replays recent consensus history through the live kill conditions; a Monte-Carlo possibility cone shows the forward 5th/50th/95th percentile of equity with P(ruin) and P(profit) as first-class tiles.
3. **The paper publishes what the system actually knows.** The Phase-4 benchmark runs on the repo's real probe corpus, walk-forward history and live RF model — and reports honest numbers, including where the system currently has *no* edge.

## 2. The Source-Correlation Penalty (v4 math)

### 2.1 The problem

The v3 fusion sums weighted votes:

```
consensus_value = Σ (dir_value · strength · confidence · weight) / Σ weight
agreement_index  = share of *weight* voting with the consensus
```

Two sources derived from the same bars — the backtest and the trend filter, or the RF classifier and the trend filter — can cast *the same information twice*. The v2 paper already observed this risk; v4 formalizes the fix.

### 2.2 Variance inflation and effective sample size

Every source type gets a prior pairwise correlation ρ (configurable, JSON via `CONSENSUS_SOURCE_CORRELATIONS`):

| Source A | Source B | ρ | Rationale |
| --- | --- | --- | --- |
| rf_regime | backtest | 0.50 | both built from the same bars/features |
| rf_regime | trend_filter | 0.45 | same price path |
| backtest | trend_filter | 0.40 | same price path |
| kronos | trend_filter | 0.30 | both price-derived |
| kronos | rf_regime / backtest / llm | 0.10–0.15 | quasi-independent |

For the source types present in a given cycle the engine builds the correlation matrix **C**, computes each source's **Variance Inflation Factor** `VIF_i = (C⁻¹)ᵢᵢ`, and down-weights its vote:

```
independent_weight_i = weight_i / VIF_i
agreement_index      = Σ_agree independent_weight / Σ_all independent_weight
```

A Kish-style effective sample size quantifies the panel's true independence:

```
n_eff = (Σ w)² / ( Σ wᵢ² + 2·Σ_{i<j} wᵢwⱼρᵢⱼ )
diversity_penalty = n_eff / n_sources
```

With perfect correlations `n_eff → 1` (the panel really has one opinion); with independent brains `n_eff ≈ n`. The correction is recorded on every contribution (`vif`, `independent_weight`) and on the MarketView (`effective_n`, `max_vif`, `diversity_penalty`, `raw_agreement_index`), so the dashboard can show *“5 votes, but only 3.2 independent ones.”*

### 2.3 Why this matters

The `agreement_index` now means “share of independent evidence,” not “share of votes.” A consensus that is 100% BULL across four brains that share one information source scores lower than four genuinely independent confirmations — which is exactly the behavior a human committee would show.

## 3. The Dashboard as a War-Room

### 3.1 Consensus Weather Radar (the flagship widget)

Each intelligence source becomes a spoke on a polar plot: **length = contribution**, **color = direction** (green BULL / red BEAR / amber RANGING), **opacity = confidence**. A compass needle points at the consensus direction; a dashed storm-ring shows `agreement_index`. The widget renders from the existing `contributions[]` and `/api/intelligence/market_view` — no new data plumbing.

### 3.2 The “Why” drill-down

Every contribution row is clickable and opens an attribution drawer showing the exact features the vote derived from, its strength/confidence/base-weight/VIF/independent-weight, the raw evidence JSON, and the implementing module. Explainability is a first-class UI object — the paper's core v3 claim (“a conclusion is now provable”) becomes visually interactive.

### 3.3 Kill-switch drill (chaos rehearsal)

`run_kill_drill()` in `execution/live_apply.py` replays the last N recorded MarketViews through the *live* kill conditions (`evaluate_kill_switches`) and reports what **would** have happened — how often the guard would have fired, on which step, for which reason (drawdown breach / consensus collapse / regime flip) — without placing a single broker order. Exposed at `/api/intelligence/kill_drill` with a one-click rehearsal timeline in the Execution Guard panel.

### 3.4 Monte-Carlo possibility cones

`possibility_cone()` in `analysis/monte_carlo.py` bootstraps the forward equity curve from **realized** trade PnLs (the live `trades.db`, falling back to the committed analytics snapshot): 5th/50th/95th percentile paths plus **P(profit)**, **P(ruin)**, expected equity, VaR₉₅ and median max-drawdown, rendered as an SVG cone at `/api/intelligence/risk_cone`. This is the most honest risk visualization a trading UI can have — the distribution, not a single backtest line.

## 4. The Phase-4 Empirical Benchmark

The v3 paper promised PBO/DSR, calibration and walk-forward statistics “as Phase 4.” v4 implements the toolkit (`intelligence/research_stats.py`) **and runs it** on the repository's real artifacts (`intelligence/output/benchmark_report.json`, regenerable with `run_benchmark_report()`). Every number below was computed from files in this repository — probes, walk-forward windows, and the live RF model on cached gold history.

### 4.1 PBO — Probability of Backtest Overfitting (CSCV)

**Method.** Bailey, Borwein, López de Prado & Zhu (2017): random symmetric splits of the (config × window) realized-return matrix; the IS-best strategy is flagged overfit when its OOS rank sits below the OOS median. 16 splits.

**Result on real data.** The probe corpus contains **2 distinct breakout configurations** (the grid family is excluded from batch backtesting because its backtest path carries live-bridge `time.sleep(0.8)` calls — itself a finding, see §6). Running both configs over 8 contiguous windows of the 509-bar cached gold history gives a real 2×8 aligned matrix:

```
PBO = 0.25   (16 CSCV splits, logit_mean 13.8, logit_std 23.9)
```

**Honest caveat.** Two strategies is a genuinely thin sample; a PBO this noisy is reported to demonstrate *that* the machinery works and to be transparent about what the current corpus can and cannot prove. The conclusion is not “PBO 0.25” — it is *“the corpus is too thin to claim anything about overfitting, and the system says so.”*

### 4.2 DSR — Deflated Sharpe Ratio

**Result on real data.** The probe corpus contains **12 probes across 4 distinct (strategy, params) configurations**. The best IS Sharpe among them is **0.00**; the committed walk-forward history (10 windows) contains a best window Sharpe of **11.82** but a **cumulative return of −9.62%**.

```
DSR = 0.2284   (4 trials, 30 periods, skew 0, kurtosis 3)
SR0_annualized = 2.19   ← the Sharpe luck alone would show after 4 trials
```

**Reading.** With only 4 trials, luck alone is worth ~2.2 annualized Sharpe. The current best IS strategy has no positive Sharpe, so the deflated probability of a real edge is **22.8%** — i.e., the deployment gates' conservative default is exactly right: **nothing currently passes**. This is the paper's most important empirical statement: the framework's honesty mechanism is working, and the strategy itself still needs re-tuning (the open item in PROJECT_STATUS).

### 4.3 Live RF calibration curve

The v3 paper worried that the RF vote “says 0.8 confidence but is right 51% of the time.” v4 measures it directly: the committed `ml/model.pkl` is loaded and re-run on the cached gold history (102 sampled bars), comparing predicted P(BULL) against the realized forward regime:

| Probability bin | n | Mean predicted | Realized BULL frequency |
| --- | --- | --- | --- |
| 0.00–0.20 | 57 | 0.150 | **0.404** |
| 0.20–0.40 | 28 | 0.272 | **0.643** |
| 0.40–0.60 | 12 | 0.502 | **0.583** |
| 0.60–0.80 | 5 | 0.629 | **0.600** |

```
Brier score = 0.308   ·   directional hit-rate = 51.96% (n = 102)
```

**Reading.** The model is **miscalibrated in exactly the dangerous direction**: when it says “low probability of BULL” the market is actually *more* likely to be BULL (0.15 predicted → 0.40 realized). Its directional accuracy (51.96%) confirms the v3 “coin flip” concern. This is a precise, actionable finding: the RF vote's confidence should be **temperature-flattened or conformally wrapped** (planned v4.5 work) before it is trusted as a consensus weight.

### 4.4 CPCV — Combinatorial Purged Cross-Validation

`cpcv_splits()` implements leakage-resistant splits (López de Prado 2018, ch. 12) with an embargo. Applied to the 509-bar gold history (5 splits, 1% embargo, 20% test):

```
test sizes  [101, 101, 101, 101, 101]   train sizes [403, 398, 398, 398, 398]
```

### 4.5 What could not be measured (honest `null`s)

- **LLM fact-check hit-rate** — no `LLM_API_KEY` configured in the environment; the deterministic fallback was used. (Planned: batch the evidence bundle through the cross-validator and report pass/fail per citation.)
- **Kronos-vs-RF-vs-blend accuracy** — Kronos requires the HuggingFace model download + torch GPU; not available in this environment.
- **Shadow forward-test results** — no deployment has yet cleared the quality gates, so there is nothing to forward-test (the guard working as designed).

## 5. A Seventh Deployment Gate: `DEPLOY_MAX_PBO`

The empirical toolkit feeds the deployment pipeline. v4 adds a **7th gate** — `DEPLOY_MAX_PBO` (default 0.5) — evaluated on a `pbo` metric when present. Unlike the six mandatory gates, the PBO gate is **optional**: a missing PBO estimate is reported as `enforced=false` and does **not** block approval, so existing corpora are not retroactively broken. The moment a probe corpus is rich enough to produce a PBO, overfit winners are blocked exactly as a human gatekeeper would.

## 6. Findings Beyond the Benchmark

1. **The grid backtest path sleeps for the broker.** `strategies/grid_strategy.py` calls `time.sleep(0.8)` per grid level inside its placement loop, and the backtest engine constructs strategies through the live path — so a 60-bar grid backtest takes a constant ~8s and cannot be batch-parallelized. This is a genuine engine defect worth fixing (mock connector should not simulate Wine/MT5 latency).
2. **The RF model's confidence is not calibrated.** Quantified in §4.3 — the highest-leverage ML fix in the backlog.
3. **The corpus is too thin for PBO.** 2 breakout configs, 4 total configs. The path to a *strong* PBO statement is the roadmap item “re-run optimization with 6mo+ data” plus parameter-grid exploration — each additional distinct config strengthens the deflation and the CSCV matrix.

## 7. What Changed On Disk

```
gridbots/quant_env/
├── intelligence/
│   ├── consensus/
│   │   ├── engine.py            v4: VIF correction, effective_n, per-source vif
│   │   └── market_view.py       + effective_n / max_vif / diversity_penalty / raw_agreement_index
│   ├── execution/live_apply.py  + run_kill_drill() (chaos rehearsal)
│   ├── research_stats.py        NEW — PBO/CSCV, DSR, calibration, CPCV, benchmark runner
│   ├── deploy.py                + DEPLOY_MAX_PBO (optional 7th gate, enforced when measurable)
│   └── output/benchmark_report.json   NEW — real Phase-4 numbers
├── analysis/monte_carlo.py      + possibility_cone() (5/50/95 cone + P(ruin)/P(profit))
├── dashboard/app.py             market_view live-fallback · /api/intelligence/kill_drill · /api/intelligence/risk_cone
├── dashboard/app.py             kill_drill/risk_cone accept scenario params (drawdown_pct, consensus_floor, initial)
├── dashboard/templates/dashboard.html   SINGLE UI — Weather Radar (floating hover + click-through) · Why-drawer · Kill Drill + scenario sliders · Possibility Cone + horizon/capital controls + hover crosshair
├── dashboard/app.py             + /api/intelligence/consensus_history (belief curve + hit-rate scorecard)
├── intelligence/research_stats.py  + score_consensus_history (realized-outcome scoring)
├── config.example.py            CONSENSUS_DIVERSITY_ADJUST · CONSENSUS_SOURCE_CORRELATIONS · DEPLOY_MAX_PBO
└── tests/                       75 intelligence + 14 research_stats + 20 analysis (incl. drill scenario-override tests)
```

## 8. How to Use

```bash
cd gridbots && python3 launcher.py dashboard      # weather radar + drill + cone in the Agent Team tab

# Regenerate the Phase-4 empirical report from real artifacts
cd gridbots/quant_env && python3 -c \
  "from intelligence.research_stats import run_benchmark_report; import json; \
   print(json.dumps(run_benchmark_report(project_root='..'), indent=2)[:2000])"
```

## 9. Ethics, Risk & Compliance

- The kill-switch drill and possibility cone are **simulations**; they place no orders and the UI says so explicitly.
- The empirical chapter publishes negative results (DSR 0.23, RF hit-rate 52%) — a deliberate, honest alternative to the industry pattern of publishing only surviving backtests.
- The PBO gate is optional precisely so that small corpora are not blocked by an unmeasurable statistic; when measurable, it is enforced like every other gate.

> Past performance is not indicative of future results. No agent deploys capital without the human approval gate. The Phase-4 numbers above were produced by this repository's own code and data; they are published to be falsified, not to be sold.
