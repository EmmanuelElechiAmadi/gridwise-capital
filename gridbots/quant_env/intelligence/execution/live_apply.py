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
                           last_direction=None, deployed_direction=None,
                           overrides=None):
    """Check every kill-switch.  Returns ``(should_flatten, reasons)``.

    market_view          — current consensus MarketView (dict/object)
    current_drawdown_pct — current account drawdown from peak (%)
    last_direction       — direction the strategy was deployed under
    deployed_direction   — direction of the deployed strategy (flip check)
    overrides            — optional dict for WHAT-IF drills: keys
        max_drawdown_pct / consensus_floor / consensus_collapse_armed /
        regime_flip_armed.  The live guard calls this with no overrides;
        the dashboard drill passes scenario sliders through here.
    """
    ov = overrides or {}
    dd_thresh = float(ov.get("max_drawdown_pct", EXEC_KILL_MAX_DRAWDOWN_PCT))
    cs_floor = float(ov.get("consensus_floor", EXEC_KILL_CONSENSUS_FLOOR))
    collapse_armed = bool(ov.get("consensus_collapse_armed",
                                 EXEC_KILL_CONSENSUS_COLLAPSE))
    flip_armed = bool(ov.get("regime_flip_armed", EXEC_KILL_REGIME_FLIP))

    mv = market_view.to_dict() if hasattr(market_view, "to_dict") \
        else (market_view or {})
    reasons = []

    if current_drawdown_pct and current_drawdown_pct >= dd_thresh:
        reasons.append(f"drawdown {current_drawdown_pct:.1f}% >= "
                       f"kill threshold {dd_thresh:.1f}%")

    if collapse_armed and mv:
        strength = float(mv.get("consensus_strength", 0.0) or 0.0)
        if strength < cs_floor:
            reasons.append(f"consensus strength {strength:.2f} < "
                           f"kill floor {cs_floor:.2f}")

    if flip_armed and deployed_direction and mv:
        current = str(mv.get("direction") or "RANGING").upper()
        if deployed_direction.upper() in ("BULL", "BEAR") \
                and current not in ("BULL", "BEAR", "RANGING"):
            reasons.append(f"consensus flipped away from {deployed_direction}")
        elif deployed_direction.upper() == "BULL" and current == "BEAR":
            reasons.append("consensus flipped BULL -> BEAR")
        elif deployed_direction.upper() == "BEAR" and current == "BULL":
            reasons.append("consensus flipped BEAR -> BULL")

    return (bool(reasons), reasons)


# ── Kill-switch drill WHAT-IF MATRIX (advanced: sensitivity grid) ───────
def run_kill_drill_matrix(market_views=None, dd_grid=(5, 10, 15, 20),
                          floor_grid=(0.05, 0.15, 0.3, 0.5),
                          current_drawdown_pct=0.0, horizon=12,
                          deployed_direction=None):
    """What-if grid for the kill-switch drill: fired-count per (drawdown,
    floor) cell across the SAME consensus history.

    The single-scenario drill answers "would the guard have fired?" — this
    matrix answers "how SENSITIVE is the guard to its thresholds?"  Each cell
    replays the history under a different simulated threshold pair, giving an
    honest view of how close the system is to tripping.
    """
    views = list(market_views or [])[-horizon:]
    rows = []
    for dd in dd_grid:
        row = {"drawdown_pct": dd, "cells": []}
        for fl in floor_grid:
            fired = 0
            for mv in views:
                flatten, _ = evaluate_kill_switches(
                    market_view=mv,
                    current_drawdown_pct=current_drawdown_pct,
                    deployed_direction=deployed_direction,
                    overrides={"max_drawdown_pct": float(dd),
                               "consensus_floor": float(fl)})
                if flatten:
                    fired += 1
            row["cells"].append({"consensus_floor": float(fl),
                                  "fired": fired})
        rows.append(row)
    return {
        "drill_matrix": True,
        "rows": rows,
        "horizon": len(views),
        "dd_grid": [float(x) for x in dd_grid],
        "floor_grid": [float(x) for x in floor_grid],
        "run_at": _now_iso(),
    }

# ── Kill-switch DRILL (v4: chaos rehearsal) ────────────────────────────
def run_kill_drill(market_views=None, current_drawdown_pct=0.0,
                   deployed_direction=None, horizon=12, overrides=None):
    """Kill-switch DRILL — replay the last N recorded market views through
    the live kill conditions and report what WOULD have happened, without
    touching the broker.

    Pilots train on simulators; systematic traders should drill too.  Each
    recorded MarketView is scored by ``evaluate_kill_switches`` (drawdown
    breach / consensus collapse / regime flip) exactly as the live
    ``_execution_guard()`` loop would, and the summary shows how often the
    guard would have fired in the recent past.

    Returns a JSON report: per-step evaluation, fired count, first fired
    index and a histogram of kill reasons.
    """
    views = list(market_views or [])[-horizon:]
    steps = []
    fired = 0
    for i, mv in enumerate(views):
        flatten, reasons = evaluate_kill_switches(
            market_view=mv,
            current_drawdown_pct=current_drawdown_pct,
            deployed_direction=deployed_direction,
            overrides=overrides)
        if isinstance(mv, dict):
            gen_at = mv.get("generated_at")
            direction = mv.get("direction")
            strength = float(mv.get("consensus_strength", 0.0) or 0.0)
        else:
            gen_at = getattr(mv, "generated_at", None)
            direction = getattr(mv, "direction", "RANGING")
            strength = float(getattr(mv, "consensus_strength", 0.0) or 0.0)
        steps.append({
            "index": i,
            "generated_at": gen_at,
            "direction": direction,
            "consensus_strength": round(strength, 4),
            "kill_triggered": bool(flatten),
            "reasons": reasons,
        })
        if flatten:
            fired += 1

    reason_hist = {}
    for st in steps:
        for r in st["reasons"]:
            reason_hist[r] = reason_hist.get(r, 0) + 1

    return {
        "drill": True,
        "simulated_steps": len(views),
        "steps": steps,
        "fired_steps": fired,
        "fired_fraction": round(fired / len(views), 4) if views else 0.0,
        "first_fired_index": next((st["index"] for st in steps
                                   if st["kill_triggered"]), None),
        "reason_histogram": reason_hist,
        "run_at": _now_iso(),
        "config": {
            "max_drawdown_pct": float((overrides or {}).get(
                "max_drawdown_pct", EXEC_KILL_MAX_DRAWDOWN_PCT)),
            "consensus_floor": float((overrides or {}).get(
                "consensus_floor", EXEC_KILL_CONSENSUS_FLOOR)),
            "consensus_collapse_armed": bool((overrides or {}).get(
                "consensus_collapse_armed", EXEC_KILL_CONSENSUS_COLLAPSE)),
            "regime_flip_armed": bool((overrides or {}).get(
                "regime_flip_armed", EXEC_KILL_REGIME_FLIP)),
        },
    }
