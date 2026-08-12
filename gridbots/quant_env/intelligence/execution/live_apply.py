"""
LiveApply — hot-applies approved deployments to a running strategy and
enforces kill-switches.

Kill-switches (all can be independently disabled via env):
    EXEC_KILL_MAX_DRAWDOWN_PCT  — flatten when account drawdown breaches
    EXEC_KILL_CONSENSUS_COLLAPSE — flatten when consensus strength collapses
    EXEC_KILL_REGIME_FLIP       — flatten when the consensus direction flips
"""

import json
import os
from datetime import datetime, timezone

EXEC_KILL_MAX_DRAWDOWN_PCT = float(os.getenv("EXEC_KILL_MAX_DRAWDOWN_PCT", "15.0"))
EXEC_KILL_CONSENSUS_COLLAPSE = \
    os.getenv("EXEC_KILL_CONSENSUS_COLLAPSE", "true").lower() == "true"
EXEC_KILL_CONSENSUS_FLOOR = float(os.getenv("EXEC_KILL_CONSENSUS_FLOOR", "0.15"))
EXEC_KILL_REGIME_FLIP = \
    os.getenv("EXEC_KILL_REGIME_FLIP", "true").lower() == "true"

HOT_APPLIED_PATH = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "output", "hot_applied.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_hot_applied():
    if os.path.exists(HOT_APPLIED_PATH):
        try:
            with open(HOT_APPLIED_PATH) as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save_hot_applied(records):
    os.makedirs(os.path.dirname(HOT_APPLIED_PATH), exist_ok=True)
    with open(HOT_APPLIED_PATH, "w") as f:
        json.dump(records[-25:], f, indent=2, default=str)


def list_hot_applied():
    """Return the persisted hot-apply log (for the dashboard)."""
    return _load_hot_applied()


def apply_hot(strategy, deployment):
    """Apply an approved deployment's params to a RUNNING strategy instance
    (no restart).  Reuses the canonical DeploymentManager.apply_to_strategy
    so transforms (pct/100, tp strings, Kronos attach) stay consistent.

    The apply is persisted to ``output/hot_applied.json`` so the dashboard
    can show which deployments are live on the running bot.
    """
    from ..deploy import DeploymentManager
    applied = DeploymentManager.apply_to_strategy(strategy, deployment)
    records = _load_hot_applied()
    records.append({
        "deployment_id": (deployment or {}).get("id"),
        "strategy_key": (deployment or {}).get("strategy_key"),
        "params": dict((deployment or {}).get("params") or {}),
        "applied": applied,
        "applied_at": _now_iso(),
    })
    _save_hot_applied(records)
    return {
        "applied": applied,
        "strategy_key": (deployment or {}).get("strategy_key"),
        "hot": True,
        "applied_at": _now_iso(),
    }


def evaluate_kill_switches(market_view=None, current_drawdown_pct=0.0,
                           last_direction=None, deployed_direction=None):
    """Check every kill-switch.  Returns ``(should_flatten, reasons)``.

    market_view         — current consensus MarketView (dict/object)
    current_drawdown_pct — current account drawdown from peak (%)
    last_direction      — direction the strategy was deployed under
    deployed_direction  — direction of the deployed strategy (for flip check)
    """
    mv = market_view.to_dict() if hasattr(market_view, "to_dict") \
        else (market_view or {})
    reasons = []

    if current_drawdown_pct and current_drawdown_pct >= EXEC_KILL_MAX_DRAWDOWN_PCT:
        reasons.append(f"drawdown {current_drawdown_pct:.1f}% >= "
                       f"kill threshold {EXEC_KILL_MAX_DRAWDOWN_PCT:.0f}%")

    if EXEC_KILL_CONSENSUS_COLLAPSE and mv:
        strength = float(mv.get("consensus_strength", 0.0) or 0.0)
        if strength < EXEC_KILL_CONSENSUS_FLOOR:
            reasons.append(f"consensus strength {strength:.2f} < "
                           f"kill floor {EXEC_KILL_CONSENSUS_FLOOR:.2f}")

    if EXEC_KILL_REGIME_FLIP and deployed_direction and mv:
        current = str(mv.get("direction") or "RANGING").upper()
        if deployed_direction.upper() in ("BULL", "BEAR") \
                and current not in ("BULL", "BEAR", "RANGING"):
            reasons.append(f"consensus flipped away from {deployed_direction}")
        elif deployed_direction.upper() == "BULL" and current == "BEAR":
            reasons.append("consensus flipped BULL -> BEAR")
        elif deployed_direction.upper() == "BEAR" and current == "BULL":
            reasons.append("consensus flipped BEAR -> BULL")

    return (bool(reasons), reasons)
