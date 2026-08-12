"""
OpportunityLedger — shared knowledge store for the agent team.

In InsightForge terms this is the *opportunity solution tree*: a persistent,
graph-shaped memory that connects instruments (participants), probes
(interviews), alpha themes (insights) and strategy opportunities (user
stories).  It is written as JSON so humans, the dashboard and downstream PM
tools (Jira/Linear) can all consume it.
"""

import json
import os
import uuid
from datetime import datetime, timezone

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
LEDGER_PATH = os.path.join(OUTPUT_DIR, "opportunity_ledger.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clip01(x) -> float:
    """Clamp a value into [0, 1], tolerating None/NaN."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    if v != v:  # NaN
        return 0.0
    return max(0.0, min(1.0, v))


# ══════════════════════════════════════════════════════════════════════
# Domain records
# ══════════════════════════════════════════════════════════════════════


class Instrument:
    """A sourced market participant — the quant analogue of a recruited user."""

    def __init__(self, symbol, timeframe, source, coverage_bars=0,
                 status="sourced", source_agent="DataScout", note=""):
        self.symbol = symbol
        self.timeframe = timeframe
        self.source = source
        self.coverage_bars = int(coverage_bars or 0)
        self.status = status
        self.source_agent = source_agent
        self.note = note
        self.sourced_at = _now_iso()

    def to_dict(self):
        return {
            "symbol": self.symbol, "timeframe": self.timeframe,
            "source": self.source, "coverage_bars": self.coverage_bars,
            "status": self.status, "source_agent": self.source_agent,
            "note": self.note, "sourced_at": self.sourced_at,
        }


class Probe:
    """One market interview: a single backtest / OOS validation run."""

    def __init__(self, strategy_key, symbol="GC=F", timeframe="1h", params=None,
                 metrics=None, oos=False, regime=None, data_bars=0,
                 source_agent="MarketProber", note=""):
        self.id = uuid.uuid4().hex[:12]
        self.strategy_key = strategy_key
        self.symbol = symbol
        self.timeframe = timeframe
        self.params = params or {}
        self.metrics = metrics or {}
        self.oos = bool(oos)
        self.regime = regime
        self.data_bars = int(data_bars or 0)
        self.source_agent = source_agent
        self.note = note
        self.probed_at = _now_iso()

    @property
    def has_trades(self) -> bool:
        return int(self.metrics.get("num_trades", 0) or 0) > 0

    def to_dict(self):
        return {
            "id": self.id, "strategy_key": self.strategy_key,
            "symbol": self.symbol, "timeframe": self.timeframe,
            "params": self.params, "metrics": self.metrics, "oos": self.oos,
            "regime": self.regime, "data_bars": self.data_bars,
            "source_agent": self.source_agent, "note": self.note,
            "probed_at": self.probed_at,
        }


class Insight:
    """An alpha theme — the quant analogue of a synthesized qualitative insight."""

    def __init__(self, title, theme, evidence=None, confidence=0.0, risk_flags=None,
                 strategy_keys=None, source_agent="QuantAnalyst"):
        self.id = uuid.uuid4().hex[:12]
        self.title = title
        self.theme = theme
        self.evidence = evidence or []
        self.confidence = clip01(confidence)
        self.risk_flags = risk_flags or []
        self.strategy_keys = strategy_keys or []
        self.source_agent = source_agent
        self.created_at = _now_iso()

    def to_dict(self):
        return {
            "id": self.id, "title": self.title, "theme": self.theme,
            "evidence": self.evidence, "confidence": self.confidence,
            "risk_flags": self.risk_flags, "strategy_keys": self.strategy_keys,
            "source_agent": self.source_agent, "created_at": self.created_at,
        }


class Opportunity:
    """A prioritized strategy candidate — the quant analogue of a user story."""

    def __init__(self, title, strategy_key, source_agent, params=None, metrics=None,
                 reach=0.0, impact=0.0, confidence=0.0, effort_hours=8.0,
                 status="hypothesis"):
        self.id = uuid.uuid4().hex[:12]
        self.title = title
        self.strategy_key = strategy_key
        self.source_agent = source_agent
        self.params = params or {}
        self.metrics = metrics or {}
        self.reach = clip01(reach)
        self.impact = clip01(impact)
        self.confidence = clip01(confidence)
        self.effort_hours = max(0.1, float(effort_hours or 0.1))
        self.status = status
        self.created_at = _now_iso()

    def qrice(self) -> float:
        """
        qRICE opportunity score (quant RICE):
            O_s = (R * I * C) / E
        R = reach / capacity, I = impact, C = confidence, E = normalized effort.
        Effort is normalized to a 0.1..5 scale (effort_hours / 10) so the
        score stays interpretable in [0, 1] territory.
        """
        effort_norm = max(0.1, self.effort_hours / 10.0)
        return round((self.reach * self.impact * self.confidence) / effort_norm, 4)

    def to_dict(self):
        return {
            "id": self.id, "title": self.title, "strategy_key": self.strategy_key,
            "source_agent": self.source_agent, "params": self.params,
            "metrics": self.metrics, "reach": self.reach, "impact": self.impact,
            "confidence": self.confidence, "effort_hours": self.effort_hours,
            "qrice": self.qrice(), "status": self.status, "created_at": self.created_at,
        }


class OpportunityLedger:
    """Persistent shared memory: instruments, probes, insights, opportunities."""

    def __init__(self, path=None):
        self.path = path or LEDGER_PATH
        self.instruments = []
        self.probes = []
        self.insights = []
        self.opportunities = []
        self.market_views = []
        self.created_at = _now_iso()
        self.updated_at = _now_iso()

    # ── Mutators ──────────────────────────────────────────────────────
    def add_instrument(self, instrument: Instrument) -> None:
        self.instruments.append(instrument)
        self.updated_at = _now_iso()

    def add_probe(self, probe: Probe) -> None:
        self.probes.append(probe)
        self.updated_at = _now_iso()

    def add_insight(self, insight: Insight) -> None:
        self.insights.append(insight)
        self.updated_at = _now_iso()

    def add_opportunity(self, opportunity: Opportunity) -> None:
        self.opportunities.append(opportunity)
        self.updated_at = _now_iso()

    def add_market_view(self, market_view) -> None:
        """Record a consensus MarketView (dict or MarketView)."""
        self.market_views.append(
            market_view.to_dict() if hasattr(market_view, "to_dict")
            else market_view)
        self.updated_at = _now_iso()

    # ── Queries ───────────────────────────────────────────────────────
    def top_opportunities(self, n=3):
        return sorted(self.opportunities, key=lambda o: o.qrice(), reverse=True)[:n]

    def probes_for(self, strategy_key: str, symbol=None):
        ps = [p for p in self.probes if p.strategy_key == strategy_key]
        if symbol:
            ps = [p for p in ps if p.symbol == symbol]
        return ps

    def best_probe(self, strategy_key: str, include_oos=False, symbol=None):
        scored = [p for p in self.probes_for(strategy_key, symbol)
                  if p.has_trades and (include_oos or not p.oos)]
        if not scored:
            return None
        return max(scored, key=lambda p: p.metrics.get("sharpe_ratio", -999))

    def best_oos_probe(self, strategy_key: str, symbol=None):
        scored = [p for p in self.probes_for(strategy_key, symbol) if p.oos and p.has_trades]
        if not scored:
            return None
        return max(scored, key=lambda p: p.metrics.get("sharpe_ratio", -999))

    # ── Serialization ─────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "schema": "insightforge.quant.ledger/v3",
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "instruments": [i.to_dict() for i in self.instruments],
            "probes": [p.to_dict() for p in self.probes],
            "insights": [i.to_dict() for i in self.insights],
            "opportunities": [o.to_dict() for o in self.opportunities],
            "market_views": list(self.market_views),
        }

    def save(self, path=None) -> str:
        target = path or self.path
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w") as f:
            json.dump(self.to_dict(), f, indent=2, default=str)
        return target

    @classmethod
    def load(cls, path=None) -> "OpportunityLedger":
        target = path or LEDGER_PATH
        ledger = cls(path=target)
        if not os.path.exists(target):
            return ledger
        try:
            with open(target) as f:
                data = json.load(f)
        except Exception:
            return ledger
        for inst in data.get("instruments", []):
            ledger.add_instrument(Instrument(
                inst.get("symbol", ""), inst.get("timeframe", ""),
                inst.get("source", ""), inst.get("coverage_bars", 0),
                inst.get("status", "sourced"), inst.get("source_agent", "DataScout"),
                inst.get("note", "")))
        for pr in data.get("probes", []):
            ledger.add_probe(Probe(
                pr.get("strategy_key", ""), pr.get("symbol", "GC=F"),
                pr.get("timeframe", "1h"), pr.get("params", {}),
                pr.get("metrics", {}), pr.get("oos", False),
                pr.get("regime"), pr.get("data_bars", 0),
                pr.get("source_agent", "MarketProber"), pr.get("note", "")))
        for ins in data.get("insights", []):
            ledger.add_insight(Insight(
                ins.get("title", ""), ins.get("theme", ""),
                ins.get("evidence", []), ins.get("confidence", 0.0),
                ins.get("risk_flags", []), ins.get("strategy_keys", []),
                ins.get("source_agent", "QuantAnalyst")))
        for opp in data.get("opportunities", []):
            ledger.add_opportunity(Opportunity(
                opp.get("title", ""), opp.get("strategy_key", ""),
                opp.get("source_agent", "QuantStrategist"), opp.get("params", {}),
                opp.get("metrics", {}), opp.get("reach", 0.0),
                opp.get("impact", 0.0), opp.get("confidence", 0.0),
                opp.get("effort_hours", 8.0), opp.get("status", "hypothesis")))
        for mv in data.get("market_views", []):
            if isinstance(mv, dict):
                ledger.market_views.append(mv)
        return ledger

    def summary(self) -> str:
        lines = [
            "Opportunity Ledger",
            f"  instruments  : {len(self.instruments)}",
            f"  probes       : {len(self.probes)}",
            f"  alpha themes : {len(self.insights)}",
            f"  opportunities: {len(self.opportunities)}",
            f"  market views : {len(self.market_views)}",
        ]
        if self.opportunities:
            lines.append("  top qRICE:")
            for o in self.top_opportunities(3):
                lines.append(f"    - {o.strategy_key}  qRICE={o.qrice():.3f}  {o.status}")
        if self.market_views:
            latest = self.market_views[-1]
            lines.append(f"  latest consensus: {latest.get('direction', '?')} "
                         f"agreement={latest.get('agreement_index', 0):.0%}")
        return "\n".join(lines)
