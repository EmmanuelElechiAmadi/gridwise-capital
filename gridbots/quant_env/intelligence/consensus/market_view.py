"""
MarketView — the consensus conclusion with full attribution.

A MarketView is what answers "what do all the models agree on, and why?":

    direction: BULL/BEAR/RANGING            the common conclusion
    direction_value: signed [-1, 1]         how strong that conclusion is
    agreement_index: 0..1                   how much the sources agree
    contributions: [per-source detail]      the "why" (attribution chain)
    disagreements: [source summaries]       the voices that dissent
    consensus_strength: 0..1                strength * agreement

v4 additions (source-correlation penalty):

    raw_agreement_index: 0..1               nominal-weight agreement (uncorrected)
    effective_n: float                      independent votes (Kish effective size)
    max_vif: float                          worst per-source variance inflation
    diversity_penalty: 0..1                 effective_n / n_sources
"""

import uuid
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class MarketView:
    """Serializable consensus output of the ConsensusEngine."""

    def __init__(self, direction="RANGING", direction_value=0.0, strength=0.0,
                 agreement_index=0.0, consensus_strength=0.0,
                 contributions=None, disagreements=None,
                 horizon="medium", symbol="GC=F", sources=None,
                 generated_at=None, cycle_id=None,
                 raw_agreement_index=None, effective_n=None,
                 max_vif=1.0, diversity_penalty=1.0):
        self.id = uuid.uuid4().hex[:12]
        self.direction = str(direction or "RANGING").upper()
        self.direction_value = float(direction_value)
        self.strength = max(0.0, min(1.0, float(strength)))
        self.agreement_index = max(0.0, min(1.0, float(agreement_index)))
        self.consensus_strength = max(0.0, min(1.0, float(consensus_strength)))
        self.contributions = contributions or []
        self.disagreements = disagreements or []
        self.horizon = horizon
        self.symbol = symbol
        self.sources = sources or []
        self.generated_at = generated_at or _now_iso()
        self.cycle_id = cycle_id
        # Phase 2 additions (attached after fusion by the coordinator).
        self.llm_verdict = None
        self.llm_fact_check = None
        # v4 source-correlation penalty fields.
        self.raw_agreement_index = (
            float(raw_agreement_index) if raw_agreement_index is not None
            else self.agreement_index)
        self.effective_n = effective_n
        self.max_vif = max_vif
        self.diversity_penalty = max(0.0, min(1.0, float(diversity_penalty)))

    def to_dict(self):
        d = {
            "id": self.id,
            "direction": self.direction,
            "direction_value": round(self.direction_value, 4),
            "strength": round(self.strength, 4),
            "agreement_index": round(self.agreement_index, 4),
            "consensus_strength": round(self.consensus_strength, 4),
            "contributions": self.contributions,
            "disagreements": self.disagreements,
            "horizon": self.horizon,
            "symbol": self.symbol,
            "sources": self.sources,
            "generated_at": self.generated_at,
            "cycle_id": self.cycle_id,
            "llm_verdict": self.llm_verdict,
            "llm_fact_check": self.llm_fact_check,
            "raw_agreement_index": round(self.raw_agreement_index, 4),
            "effective_n": self.effective_n,
            "max_vif": round(self.max_vif, 4),
            "diversity_penalty": round(self.diversity_penalty, 4),
        }
        return d

    def summary(self) -> str:
        return (
            f"Consensus {self.direction} (value {self.direction_value:+.2f}, "
            f"agreement {self.agreement_index:.0%}, strength "
            f"{self.consensus_strength:.0%}) across {len(self.sources)} sources"
        )
