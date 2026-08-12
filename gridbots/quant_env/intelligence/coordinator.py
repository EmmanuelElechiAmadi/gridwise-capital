"""
CoordinatorAgent — the *Coordinator* replacement, acting as Chief Quant Officer.

InsightForge Coordinator       -> Chief Quant Officer (CQO)
Human role replaced            -> Head of Systematic Research

Owns the research agenda, the session budget, inter-agent hand-offs and the
human-in-the-loop gates.  Runs the continuous discovery loop:

    scout -> prober -> analyst -> strategist -> brief
"""

import uuid

from .agents.base import BaseAgent
from .ledger import OpportunityLedger, _now_iso
from .agents import TEAM
from .llm import LLMNarrator

DEFAULT_LEDGER_PATH = None  # resolved by OpportunityLedger


class CoordinatorAgent(BaseAgent):
    KEY = "coordinator"
    ROLE = "Chief Quant Officer (CQO)"
    REPLACES = "Head of Systematic Research"
    PRIMARY_RESPONSIBILITY = (
        "Orchestrates the autonomous research cycle, manages session budget "
        "and enforces human-in-the-loop gates before deployment."
    )

    def __init__(self, ctx=None, narrator=None):
        super().__init__(ctx)
        self.team = [cls(ctx) for cls in TEAM]
        ledger_path = self.ctx.get("ledger_path")
        self.ledger = OpportunityLedger(path=ledger_path)
        # Optional LLM narrative layer (fail-safe: deterministic fallback).
        self.narrator = narrator or LLMNarrator(self.ctx)

    # ── The loop ──────────────────────────────────────────────────────
    def run_cycle(self, ledger=None):
        ledger = ledger or self.ledger
        results = {}
        # Cycle id used by the brief and the market view (stable within a run).
        self._brief_cycle_id = uuid.uuid4().hex[:12]
        for agent in self.team:
            self.log(f"{agent.ROLE} ({agent.KEY}) running…")
            results[agent.KEY] = agent.run(ledger)

        # Consensus step (Phase 1): fuse every available intelligence source
        # (Kronos forecast, RF regime, backtest probes, trend filter, LLM
        # verdict) into ONE attributed market view — the "common conclusion".
        market_view = self._build_market_view(ledger, results)
        if market_view is not None:
            ledger.add_market_view(market_view)

        ledger.save()

        # Human-gated deployment proposal: the CQO proposes the top
        # opportunity; it reaches the engine after a human approves it OR
        # after ``auto_approve_cycles`` consistent cycles (opt-in).
        deployment = None
        if self.ctx.get("auto_deploy_top"):
            from .deploy import DeploymentManager
            top = self.ledger.top_opportunities(1)
            if top:
                dm = DeploymentManager(self.ctx.get("deploy_path"))
                required = int(self.ctx.get("auto_approve_cycles") or 0)
                if required > 0:
                    deployment = dm.consider_auto_approve(top[0], required_cycles=required)
                else:
                    deployment = dm.propose(
                        top[0], note="auto-proposed by CQO; awaiting human approval")
                # Sync the ledger record with the gate outcome so the brief and
                # the ledger never disagree about a deployment's status.
                top[0].status = deployment.get("status", "proposed")
                ledger.save()
                self.log(f"Deployment {deployment['id']} for {top[0].strategy_key}: "
                         f"{deployment['status']} (consistent_cycles="
                         f"{deployment.get('consistent_cycles', 1)})")

        brief = self._build_brief(results, market_view)
        if deployment:
            brief["deployment"] = deployment
        brief = self._narrate(brief, results)
        return brief, ledger

    def _build_market_view(self, ledger, results):
        """Fuse all evidence sources into one attributed MarketView.

        The consensus is the CQO's "market read": direction + strength +
        agreement + per-source why.  It consumes:

            - Kronos forecast features (when the model is available)
            - RF regime model output
            - Backtest/walk-forward probes from the ledger
            - Deterministic trend filter
            - LLM structured verdict (Phase 2, when enabled)
        """
        try:
            from .consensus import ConsensusEngine, sources as consensus_sources
            engine = ConsensusEngine()
            signals = consensus_sources.collect_all_signals(
                ctx=self.ctx, ledger=ledger,
                project_root=self.ctx.get("project_root"),
                symbol=str(self.ctx.get("consensus_symbol") or "GC=F"))
            # LLM cross-validation verdict contributes a signal too.
            evidence_bundle = {
                "signals": [s.to_dict() for s in signals],
                "themes": [i.to_dict() for i in ledger.insights],
                "top_opportunities":
                    [o.to_dict() for o in ledger.top_opportunities(3)],
            }
            llm_verdict = self.narrator.cross_validate(evidence_bundle)
            results["coordinator_llm"] = {"verdict": llm_verdict} \
                if llm_verdict else {}
            if llm_verdict:
                from .consensus import Signal
                s = Signal.from_llm_verdict(llm_verdict)
                if s:
                    signals.append(s)
            view = engine.fuse(
                signals, symbol=str(self.ctx.get("consensus_symbol") or "GC=F"),
                horizon="medium", cycle_id=self._brief_cycle_id)
            view.llm_verdict = llm_verdict
            view.llm_fact_check = (llm_verdict or {}).get("_fact_check") \
                if llm_verdict else None
            self.log(f"Consensus: {view.summary()}")
            return view
        except Exception as e:
            self.log(f"Consensus skipped: {e}")
            return None

    def _build_brief(self, results, market_view=None):
        return {
            "cycle_id": self._brief_cycle_id,
            "generated_at": _now_iso(),
            "framework": "InsightForge for Quant v2.0",
            "coordinator": {
                "role": self.ROLE,
                "replaces": self.REPLACES,
                "primary_responsibility": self.PRIMARY_RESPONSIBILITY,
            },
            "team": [
                {
                    "key": agent.KEY,
                    "role": agent.ROLE,
                    "replaces": agent.REPLACES,
                    "primary_responsibility": agent.PRIMARY_RESPONSIBILITY,
                    "findings": results.get(agent.KEY, {}),
                }
                for agent in self.team
            ],
            "themes": [i.to_dict() for i in self.ledger.insights],
            "probe_count": len(self.ledger.probes),
            "instrument_count": len(self.ledger.instruments),
            "top_opportunities": [o.to_dict() for o in self.ledger.top_opportunities(3)],
            "market_view": market_view.to_dict() if market_view else None,
        }

    # ── Narrative layer (CQO commentary) ──────────────────────────────
    def _narrate(self, brief, results):
        """Attach narrative fields; always present (deterministic fallback)."""

        # Map opportunity ids -> strategist specs so narrations can cite them.
        specs_by_id = {}
        for spec in (results.get("strategist", {}) or {}).get("specs", []) or []:
            if isinstance(spec, dict) and spec.get("opportunity_id"):
                specs_by_id[spec["opportunity_id"]] = spec

        brief["narrative"] = self.narrator.executive_summary(brief)

        # Consensus "why": explain the market view with attribution.
        mv = brief.get("market_view")
        if mv:
            signals = (mv.get("contributions") or [])[:2]
            brief["market_view_narrative"] = \
                self.narrator.explain_market_view(mv, signals)

        for theme in brief.get("themes", [])[: self.narrator.max_items]:
            theme["narrative"] = self.narrator.narrate_theme(theme)

        for opp in brief.get("top_opportunities", [])[: self.narrator.max_items]:
            spec = specs_by_id.get(opp.get("id"))
            opp["narrative"] = self.narrator.narrate_opportunity(opp, spec)

        # Capture the layer LAST so ``last_model`` reflects the model that
        # actually answered the narrations, not the pre-call state.
        brief["narrative_layer"] = {
            "enabled": self.narrator.llm_enabled,
            **self.narrator.client.status(),
        }
        return brief
