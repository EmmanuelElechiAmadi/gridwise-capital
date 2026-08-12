"""
QuantStrategistAgent — the *Strategist* replacement.

Strategist (InsightForge)         -> Quant Strategist / Portfolio Manager
Human role replaced               -> Portfolio Manager / Head of Quant Strategy

Primary responsibility: map alpha themes onto the opportunity solution tree,
prioritize with the formal qRICE model, draft strategy specs ("user stories")
with explicit risk gates, and push them into the strategy registry and PM
tooling.

Formal model (paper v2):

    O_s = (R * I * C) / E
    R = tradable capacity / reach,  I = expected impact,
    C = theme confidence,           E = normalized engineering effort.
"""

import os

from .base import BaseAgent
from ..ledger import Opportunity, clip01

_QUANT_ENV_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Baseline engineering effort (hours) per strategy family.
DEFAULT_EFFORT_HOURS = {
    "grid_strategy": 6.0,
    "breakout_strategy": 10.0,
}
BASE_EFFORT_HOURS = 8.0


class QuantStrategistAgent(BaseAgent):
    KEY = "strategist"
    ROLE = "Quant Strategist / Portfolio Manager"
    REPLACES = "Portfolio Manager / Head of Quant Strategy"
    PRIMARY_RESPONSIBILITY = (
        "Maps alpha themes to the opportunity solution tree, prioritizes with "
        "qRICE, drafts strategy specs and routes them to the registry + PM tools."
    )
    INTEGRATIONS = ["OpportunityLedger (qRICE)", "strategies.registry", "Jira/Linear", "dashboard"]

    def __init__(self, ctx=None):
        super().__init__(ctx)
        self.top_n = int(self.ctx.get("top_n", 3))

    # ── Run ───────────────────────────────────────────────────────────
    def run(self, ledger):
        opportunities = self._build_opportunities(ledger)
        for opp in opportunities:
            ledger.add_opportunity(opp)

        ranked = sorted(ledger.opportunities, key=lambda o: o.qrice(), reverse=True)
        for opp in ranked[: self.top_n]:
            opp.status = "prioritized"

        specs = [self._draft_spec(opp) for opp in ranked[: self.top_n]]
        self.log(f"Built {len(opportunities)} opportunities; "
                 f"prioritized {min(self.top_n, len(ranked))}")

        return self._report(
            opportunities=[o.to_dict() for o in ranked],
            specs=specs,
            top=self.top_n,
        )

    # ── Opportunity construction ──────────────────────────────────────
    def _build_opportunities(self, ledger):
        opportunities = []
        for insight in ledger.insights:
            for key in insight.strategy_keys:
                opportunities.append(self._opportunity_from_insight(insight, key, ledger))
        return opportunities

    def _opportunity_from_insight(self, insight, key, ledger):
        best = ledger.best_probe(key)
        metrics = best.metrics if best else insight.evidence[0] if insight.evidence else {}

        sharpe = float(metrics.get("sharpe_ratio", 0.0) or 0.0)
        reach = clip01(0.5 + 0.5 * (1.0 if best and best.data_bars > 500 else 0.4))
        impact = clip01((sharpe + 1.0) / 4.0)  # map Sharpe [-1,3] -> [0,1]
        confidence = insight.confidence
        effort = DEFAULT_EFFORT_HOURS.get(key, BASE_EFFORT_HOURS)

        title = f"{key.replace('_', ' ').title()} — production-grade strategy spec"
        opp = Opportunity(
            title=title,
            strategy_key=key,
            source_agent=self.KEY,
            params=best.params if best else {},
            metrics=metrics,
            reach=reach,
            impact=impact,
            confidence=confidence,
            effort_hours=effort,
            status="hypothesis",
        )
        return opp

    # ── Strategy spec ("user story") ──────────────────────────────────
    def _draft_spec(self, opp):
        params_summary = ", ".join(f"{k}={v}" for k, v in opp.params.items())
        mc = opp.metrics.get("monte_carlo") or {}
        mc_line = (f"MC: {mc.get('mc_prob_profit_pct', '--')}% prob profit, "
                   f"95% VaR {mc.get('mc_var_95_pct', '--')}%, "
                   f"median max DD {mc.get('mc_median_max_dd_pct', '--')}%"
                   if mc else "Monte Carlo stress not computed (no trades).")
        allocation_pct = min(20.0, round(100.0 * opp.impact * opp.confidence, 1))
        return {
            "opportunity_id": opp.id,
            "title": opp.title,
            "strategy_key": opp.strategy_key,
            "params": params_summary,
            "expected_sharpe": opp.metrics.get("sharpe_ratio"),
            "qrice": opp.qrice(),
            "suggested_allocation_pct": allocation_pct,
            "monte_carlo": mc_line,
            "risk_gates": [
                "max_drawdown_pct <= 20",
                "max_daily_loss_pct <= 5",
                "max_position_oz <= config.max_position_oz",
                f"portfolio cap: allocation <= {allocation_pct:.1f}%",
            ],
            "validation": [
                "run walk-forward with 10 OOS windows",
                "confirm OOS consistency >= 0.6",
                "Monte Carlo 1,000 sims; 95th pct drawdown within risk budget",
                "revalidate out-of-sample before deployment (Prober follow-up)",
            ],
            "deploy": [
                f"register params in strategies/{opp.strategy_key}.py PARAMS",
                "attach ML regime adapter (BULL/RANGING/BEAR)",
                "gate behind human approval in dashboard (human-in-the-loop)",
            ],
            "diversification_note": (
                f"Suggested starting allocation {allocation_pct:.1f}% of risk budget — "
                "rebalance across the opportunity ledger so no single strategy "
                "concentrates more than the portfolio cap."
            ),
        }
