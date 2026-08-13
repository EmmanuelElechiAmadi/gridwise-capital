"""
DeploymentManager — human-gated wiring of the top opportunity back into the engine.

Flow:

    research cycle (auto_deploy_top=True)
      -> DeploymentManager.propose(top_opportunity)     status = "proposed"
      -> human approval (dashboard button / CLI --approve)  status = "approved"
      -> engine start (main.py) applies approved params
         to the live strategy instance.

Nothing reaches the engine without explicit human approval — the deployment
gate from the research paper — AND without passing the hard quality gates
below (a human cannot approve a study with no statistical edge).

Quality gates (enforced on approve / auto-approve / engine apply):
    DEPLOY_MIN_TRADES          int    — minimum fills for the Sharpe to mean anything
    DEPLOY_MIN_SHARPE          float  — minimum (IS) Sharpe to consider deployment
    DEPLOY_MIN_OOS_CONSISTENCY float  — fraction of walk-forward windows > 0
    DEPLOY_MIN_MC_PROB_PROFIT  float  — Monte Carlo probability-of-profit (%)
    DEPLOY_MIN_Q_RICE          float  — minimum opportunity score
    DEPLOY_MAX_DRAWDOWN_PCT    float  — max observed backtest drawdown (%)

A deployment whose metrics fail a gate is marked ``blocked_by_gates`` and
cannot be approved unless ``force=True`` (dashboard/CLI force-approve is
logged as ``approved_by="human:FORCE"`` so the override is auditable).
"""

import json
import os
import uuid
from datetime import datetime, timezone

# ── Hard quality gates (override via env: DEPLOY_MIN_TRADES etc.) ─────
DEPLOY_MIN_TRADES = int(os.getenv("DEPLOY_MIN_TRADES", "30"))
DEPLOY_MIN_SHARPE = float(os.getenv("DEPLOY_MIN_SHARPE", "0.8"))
DEPLOY_MIN_OOS_CONSISTENCY = float(os.getenv("DEPLOY_MIN_OOS_CONSISTENCY", "0.6"))
DEPLOY_MIN_MC_PROB_PROFIT = float(os.getenv("DEPLOY_MIN_MC_PROB_PROFIT", "60.0"))
DEPLOY_MIN_Q_RICE = float(os.getenv("DEPLOY_MIN_Q_RICE", "0.03"))
DEPLOY_MAX_DRAWDOWN_PCT = float(os.getenv("DEPLOY_MAX_DRAWDOWN_PCT", "20.0"))
# Probability of Backtest Overfitting (PBO, Bailey et al. 2017) — a v4 gate.
# Unlike the mandatory gates this one is *optional*: it is only enforced when
# the probe corpus is rich enough to produce a PBO estimate (the gate spec
# below is tagged ``GATE_OPTIONAL``). A PBO above this threshold means the
# IS-best strategy is likely overfit.
DEPLOY_MAX_PBO = float(os.getenv("DEPLOY_MAX_PBO", "0.5"))

# Gates evaluation: name -> (metric_key_in_metrics, comparator, threshold).
GATE_SPECS = [
    ("min_trades", "num_trades", lambda v, t: v >= t, DEPLOY_MIN_TRADES),
    ("min_sharpe", "sharpe_ratio", lambda v, t: v >= t, DEPLOY_MIN_SHARPE),
    ("min_oos_consistency", "oos_consistency",
     lambda v, t: v >= t, DEPLOY_MIN_OOS_CONSISTENCY),
    ("min_mc_prob_profit", "mc_prob_profit_pct",
     lambda v, t: v >= t, DEPLOY_MIN_MC_PROB_PROFIT),
    ("min_qrice", "qrice", lambda v, t: v >= t, DEPLOY_MIN_Q_RICE),
    ("max_drawdown", "max_drawdown_pct",
     lambda v, t: v <= t, DEPLOY_MAX_DRAWDOWN_PCT),
    ("max_pbo", "pbo",
     lambda v, t: v <= t, DEPLOY_MAX_PBO),
]

# Optional gates: missing metrics do NOT block approval, but are reported as
# ``enforced=False`` so the UI is transparent about what could not be measured.
GATE_OPTIONAL = {"max_pbo": True}


def _metric(record, key):
    """Pull a metric from the record's ``metrics`` dict (with qrice fallback).

    ``mc_prob_profit_pct`` lives inside ``metrics["monte_carlo"]`` (the probe
    convention), so it is looked up in both places.
    """
    metrics = (record or {}).get("metrics") or {}
    if key == "qrice":
        return record.get("qrice", 0.0) if record else 0.0
    v = metrics.get(key)
    if v is None and key == "mc_prob_profit_pct":
        mc = metrics.get("monte_carlo") or {}
        v = mc.get("mc_prob_profit_pct")
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def evaluate_quality(record):
    """Evaluate a deployment record against the hard quality gates.

    Returns a report dict::

        {
          "passed": bool,                     # all gates passed
          "blocked_by_gates": bool,           # NOT passed
          "gates": [                          # one entry per gate
            {"gate": name, "metric": key, "value": v|None,
             "threshold": t, "passed": bool}
          ],
          "failed": [gate_names...],
          "missing_metrics": [keys...],       # metrics we could not evaluate
          "evaluated_at": ISO
        }

    Missing metrics count as FAILED (a deployment cannot be approved on
    unverified numbers) but are listed separately so the UI can explain.
    """
    gates = []
    failed = []
    missing = []
    for name, key, cmp_, threshold in GATE_SPECS:
        v = _metric(record, key)
        if v is None:
            if GATE_OPTIONAL.get(name):
                # Could not be measured -> not enforced, but not blocking.
                gates.append({"gate": name, "metric": key, "value": None,
                              "threshold": threshold, "passed": True,
                              "enforced": False})
                missing.append(key)
                continue
            gates.append({"gate": name, "metric": key, "value": None,
                          "threshold": threshold, "passed": False})
            failed.append(name)
            missing.append(key)
            continue
        gates.append({"gate": name, "metric": key, "value": v,
                      "threshold": threshold, "passed": bool(cmp_(v, threshold)),
                      "enforced": True})
        ok = bool(cmp_(v, threshold))
        gates.append({"gate": name, "metric": key, "value": v,
                      "threshold": threshold, "passed": ok})
        if not ok:
            failed.append(name)
    return {
        "passed": not failed,
        "blocked_by_gates": bool(failed),
        "gates": gates,
        "failed": failed,
        "missing_metrics": missing,
        "evaluated_at": _now_iso(),
    }

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
DEPLOYMENTS_PATH = os.path.join(OUTPUT_DIR, "deployments.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Param-name -> strategy-attribute mapping per strategy family.  The Prober's
# param names follow the strategy's PARAMS schema; live strategy attributes may
# differ (e.g. breakout stores lookback_4h_bars as ``lookback_4h`` and stores
# breakout_threshold_pct / 100 as ``breakout_threshold``).
PARAM_ALIASES = {
    "breakout_strategy": {
        "lookback_4h_bars": "lookback_4h",
        "breakout_threshold_pct": "breakout_threshold",
        "confirmation_bars_1h": "confirmation_bars",
        "max_positions": "max_positions",
        "tp_dollars": "tp_dollars",
        "sl_dollars": "sl_dollars",
        "kronos_enabled": "_kronos_enabled",
    },
    "grid_strategy": {},
}


class DeploymentManager:
    """Persistent, human-approved strategy deployments (JSON-backed)."""

    def __init__(self, path=None):
        self.path = path or DEPLOYMENTS_PATH
        self.records = []
        self._load()

    # ── Persistence ──────────────────────────────────────────────────
    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    self.records = json.load(f)
            except Exception:
                self.records = []

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self.records, f, indent=2, default=str)

    # ── Lifecycle ────────────────────────────────────────────────────
    def _signature(self, opportunity):
        """Deterministic signature of an opportunity's params (for consistency tracking)."""
        import json as _json
        return _json.dumps(sorted((opportunity.params or {}).items()), sort_keys=True)

    def propose(self, opportunity, note="", approved_by=None):
        """Propose the top opportunity for deployment (status: proposed).

        A new proposal supersedes any other pending proposal, so only one
        active deployment is in flight at a time.  The proposal records a
        quality-gate evaluation so approvers see exactly why it is (or is
        not) eligible before they click approve.
        """
        quality = evaluate_quality({
            "qrice": opportunity.qrice(),
            "metrics": dict(opportunity.metrics),
        })
        record = {
            "id": uuid.uuid4().hex[:12],
            "opportunity_id": opportunity.id,
            "strategy_key": opportunity.strategy_key,
            "params": dict(opportunity.params),
            "metrics": dict(opportunity.metrics),
            "qrice": opportunity.qrice(),
            "status": "blocked_by_gates" if not quality["passed"] else "proposed",
            "proposed_at": _now_iso(),
            "updated_at": _now_iso(),
            "approved_by": approved_by,
            "approved_at": None,
            "params_signature": self._signature(opportunity),
            "consistent_cycles": 1,
            "quality": quality,
            "note": note,
        }
        for r in self.records:
            if r["status"] in ("proposed", "blocked_by_gates") \
                    and r.get("id") != record["id"]:
                r["status"] = "superseded"
        self.records.append(record)
        self.save()
        return record

    def consider_auto_approve(self, opportunity, required_cycles=0):
        """
        Auto-approve a deployment only after the SAME strategy+params keeps
        being the top opportunity for ``required_cycles`` consecutive cycles
        AND passes the hard quality gates on every one of those cycles.

        - Same signature as the latest pending/approved proposal -> increment
          its consistency counter; approve once it reaches ``required_cycles``.
        - Different signature -> new proposal (old pending is superseded).
        - A proposal that fails the quality gates is marked
          ``blocked_by_gates`` and is NEVER auto-approved.

        ``required_cycles <= 0`` disables auto-approval (human gate stays on).
        """
        sig = self._signature(opportunity)
        latest = next((r for r in reversed(self.records)
                       if r["strategy_key"] == opportunity.strategy_key
                       and r.get("params_signature") == sig
                       and r["status"] in ("proposed", "approved",
                                           "blocked_by_gates")), None)
        quality = evaluate_quality({
            "qrice": opportunity.qrice(),
            "metrics": dict(opportunity.metrics),
        })
        if latest is not None:
            if latest["status"] == "approved":
                return latest
            if not quality["passed"]:
                latest["status"] = "blocked_by_gates"
                latest["quality"] = quality
                latest["updated_at"] = _now_iso()
                self.save()
                return latest
            latest["consistent_cycles"] = int(latest.get("consistent_cycles", 1)) + 1
            latest["quality"] = quality
            latest["updated_at"] = _now_iso()
            if required_cycles and latest["consistent_cycles"] >= int(required_cycles):
                latest["status"] = "approved"
                latest["approved_by"] = f"auto: {latest['consistent_cycles']} consistent cycles"
                latest["approved_at"] = _now_iso()
            self.save()
            return latest
        if not quality["passed"]:
            # Record a blocked proposal so the dashboard can show why it
            # is not eligible for auto-approval.
            rec = self.propose(opportunity, note="auto-proposed by CQO; blocked by quality gates")
            return rec
        return self.propose(opportunity, note="auto-proposed by CQO")

    def approve(self, deployment_id, approved_by="human", force=False):
        """
        Human approval gate.  Enforces the hard quality gates unless
        ``force=True`` (auditable: ``approved_by="human:FORCE"``).

        Returns the record (status ``approved``), or a record with status
        ``blocked_by_gates`` when the gates fail, or None when not found.
        """
        for r in self.records:
            if r["id"] == deployment_id:
                quality = evaluate_quality(r)
                r["quality"] = quality
                if not quality["passed"] and not force:
                    r["status"] = "blocked_by_gates"
                    r["updated_at"] = _now_iso()
                    self.save()
                    return r
                r["status"] = "approved"
                if force:
                    r["approved_by"] = f"{approved_by}:FORCE"
                else:
                    r["approved_by"] = approved_by
                r["approved_at"] = _now_iso()
                r["updated_at"] = _now_iso()
                self.save()
                return r
        return None

    def void(self, deployment_id, reason=""):
        """Void a deployment (e.g. an old pre-gate approval with no edge).

        A voided deployment can never be applied by the engine.
        """
        for r in self.records:
            if r["id"] == deployment_id:
                r["status"] = "voided"
                r["note"] = (reason or r.get("note", "")) + " [voided]"
                r["updated_at"] = _now_iso()
                self.save()
                return r
        return None

    def reject(self, deployment_id):
        for r in self.records:
            if r["id"] == deployment_id:
                r["status"] = "rejected"
                self.save()
                return r
        return None

    # ── Queries ──────────────────────────────────────────────────────
    def list(self):
        """Return all records, each with a freshly-computed quality report."""
        out = []
        for r in self.records:
            rec = dict(r)
            rec["quality"] = evaluate_quality(r)
            out.append(rec)
        return out

    def pending(self):
        return [r for r in self.records if r["status"] == "proposed"]

    def blocked(self):
        return [r for r in self.records if r["status"] == "blocked_by_gates"]

    def approved_for(self, strategy_key):
        """Latest approved deployment for a strategy — but ONLY if it still
        passes the quality gates (or was explicitly force-approved).

        Legacy approvals created before the gates existed (e.g. negative
        Sharpe) are therefore never applied by the engine automatically.
        """
        for r in reversed(self.records):
            if r["strategy_key"] == strategy_key and r["status"] == "approved":
                quality = evaluate_quality(r)
                r["quality"] = quality
                force = str(r.get("approved_by", "")).endswith(":FORCE")
                if quality["passed"] or force:
                    return r
                # A once-approved deployment now fails the gates -> hold it.
                r["status"] = "blocked_by_gates"
                r["updated_at"] = _now_iso()
                self.save()
        return None

    # ── Apply to engine ──────────────────────────────────────────────
    @staticmethod
    def _attach_kronos(strategy):
        """Best-effort attach of the Kronos breakout enhancer (explicit opt-in).

        ``kronos_enabled=True`` in a deployment is an explicit opt-in, so the
        enhancer is created (if importable) and force-enabled.  Without torch /
        the Kronos package this fails safely and leaves ``_kronos=None``.
        """
        try:
            from ml.kronos import KronosBreakoutEnhancer
            enhancer = KronosBreakoutEnhancer(getattr(strategy, "config", None),
                                              logger=getattr(strategy, "log", None))
            enhancer._enabled = True   # deployment opt-in: allow refresh/filter
            strategy._kronos = enhancer
            return True
        except Exception:
            strategy._kronos = None
            return False

    @staticmethod
    def apply_to_strategy(strategy, deployment):
        """
        Set the deployment's params on a live strategy instance.

        Param names follow the strategy's PARAMS schema (PARAM_ALIASES maps
        them onto the live attributes).  Grid handles spacing/levels/lot;
        breakout handles threshold-pct (stored /100), TP levels (string ->
        sorted float list) and the Kronos flag (attaches the enhancer, not just
        a boolean).  Returns applied param names.
        """
        applied = []
        params = (deployment or {}).get("params") or {}
        family = (deployment or {}).get("strategy_key")
        aliases = PARAM_ALIASES.get(family, {})

        for pname, value in params.items():
            attr = aliases.get(pname, pname)
            if not hasattr(strategy, attr):
                continue

            # Kronos flag: a deployment can OPT IN to Kronos (true) — it
            # attaches the enhancer.  ``false`` reflects research scope (the
            # prober used base params) and must NOT force-disable a
            # config-driven Kronos switch, so it is a no-op here.
            if family == "breakout_strategy" and pname == "kronos_enabled":
                if value:
                    setattr(strategy, "_kronos_enabled", True)
                    DeploymentManager._attach_kronos(strategy)
                    applied.append(pname)
                continue

            # Breakout-specific transforms.
            if family == "breakout_strategy":
                if pname == "breakout_threshold_pct":
                    try:
                        setattr(strategy, attr, float(value) / 100.0)
                        applied.append(pname)
                    except (TypeError, ValueError):
                        continue
                    continue
                if pname == "tp_dollars":
                    try:
                        levels = sorted(float(x.strip())
                                        for x in str(value).split(",") if x.strip())
                        setattr(strategy, attr, levels)
                        applied.append(pname)
                    except (TypeError, ValueError):
                        continue
                    continue

            # Generic coercion.
            if isinstance(value, bool):
                setattr(strategy, attr, value)
            elif isinstance(value, int):
                setattr(strategy, attr, int(value))
            elif isinstance(value, float):
                setattr(strategy, attr, float(value))
            else:
                setattr(strategy, attr, value)  # strings (e.g. "3,5,10") kept as-is
            applied.append(pname)
        return applied
