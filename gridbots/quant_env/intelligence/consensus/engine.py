"""
ConsensusEngine — weighted-vote fusion of all intelligence sources.

How it works
------------
1. Every source casts a Signal (direction + strength + confidence + evidence).
2. The engine sums signed contributions::

       consensus_value = Σ (dir_value * strength * confidence * source_weight)

3. Thresholds turn the value into a direction (BULL > +0.2, BEAR < -0.2).
4. The agreement index measures how much of the *weight* agrees with the
   consensus direction (unweighted voices that dissent are listed).
5. A MarketView is produced with the full attribution chain so humans can see
   exactly WHY the team concluded a direction.

Fail-safe: with no signals the view is RANGING with strength 0.0 and an
explicit ``insufficient_evidence`` flag.
"""

import os

from .signals import Signal
from .market_view import MarketView

# Direction value map.
_DIR_VALUE = {"BULL": 1.0, "RANGING": 0.0, "BEAR": -1.0}

# Source-type base weights (Kronos + backtests are the strongest evidence).
DEFAULT_SOURCE_WEIGHTS = {
    "kronos": 1.0,
    "backtest": 1.0,
    "rf_regime": 0.6,
    "trend_filter": 0.4,
    "llm": 0.5,
}

# Direction decided when |value| exceeds this.
DIRECTION_THRESHOLD = float(os.getenv("CONSENSUS_DIRECTION_THRESHOLD", "0.2"))


class ConsensusEngine:
    """Fuses Signals into a MarketView with attribution."""

    def __init__(self, source_weights=None, direction_threshold=None):
        self.source_weights = dict(DEFAULT_SOURCE_WEIGHTS)
        if source_weights:
            self.source_weights.update(source_weights)
        self.direction_threshold = direction_threshold or DIRECTION_THRESHOLD

    # ── Core fusion ────────────────────────────────────────────────────
    def fuse(self, signals, symbol="GC=F", horizon="medium", cycle_id=None):
        signals = [s for s in signals if s is not None]
        if not signals:
            view = MarketView(symbol=symbol, horizon=horizon, cycle_id=cycle_id)
            view.contributions = []
            view.disagreements = [{
                "source": "engine",
                "message": "insufficient evidence — no signals available",
            }]
            view.sources = []
            return view

        weighted_total = 0.0
        total_weight = 0.0
        contributions = []
        for s in signals:
            base = self.source_weights.get(s.source, 0.5)
            contribution = _DIR_VALUE[s.direction] * s.strength * s.confidence * base
            weighted_total += contribution
            total_weight += base
            contributions.append({
                "source": s.source,
                "direction": s.direction,
                "strength": round(s.strength, 4),
                "confidence": round(s.confidence, 4),
                "base_weight": base,
                "contribution": round(contribution, 4),
                "evidence": s.evidence,
                "note": s.note,
            })

        if total_weight <= 0:
            consensus_value = 0.0
        else:
            consensus_value = weighted_total / total_weight

        direction = "RANGING"
        if consensus_value > self.direction_threshold:
            direction = "BULL"
        elif consensus_value < -self.direction_threshold:
            direction = "BEAR"

        # Agreement = share of weight that votes with the consensus direction.
        agree_weight = sum(
            c["base_weight"] for c in contributions
            if c["direction"] == direction or
            (direction == "RANGING" and c["direction"] == "RANGING"))
        agreement = agree_weight / total_weight if total_weight else 0.0

        # Strength of the conclusion.
        strength = min(1.0, abs(consensus_value))

        # Voices that disagree with the conclusion.
        disagreements = [
            {"source": c["source"], "direction": c["direction"],
             "contribution": c["contribution"],
             "message": f"{c['source']} votes {c['direction']} "
                        f"(strength {c['strength']:.0%}, conf {c['confidence']:.0%}) "
                        "against the consensus"}
            for c in contributions
            if c["direction"] != direction
            and not (direction == "RANGING" and c["direction"] == "RANGING")
        ]

        return MarketView(
            direction=direction,
            direction_value=consensus_value,
            strength=strength,
            agreement_index=agreement,
            consensus_strength=strength * agreement,
            contributions=contributions,
            disagreements=disagreements,
            horizon=horizon,
            symbol=symbol,
            sources=[c["source"] for c in contributions],
            cycle_id=cycle_id,
        )

    # ── Convenience ────────────────────────────────────────────────────
    def fuse_dicts(self, signal_dicts, **kwargs):
        """Fuse raw dicts (e.g. loaded from JSON) into a MarketView."""
        signals = []
        for d in signal_dicts or []:
            if isinstance(d, Signal):
                signals.append(d)
            elif isinstance(d, dict):
                try:
                    signals.append(Signal(
                        source=d.get("source", "unknown"),
                        direction=d.get("direction", "RANGING"),
                        strength=d.get("strength", 0.0),
                        confidence=d.get("confidence", 0.0),
                        horizon=d.get("horizon", "medium"),
                        symbol=d.get("symbol", "GC=F"),
                        evidence=d.get("evidence") or {},
                        note=d.get("note", ""),
                    ))
                except Exception:
                    continue
        return self.fuse(signals, **kwargs)
