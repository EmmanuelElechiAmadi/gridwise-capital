"""
ConsensusEngine — weighted-vote fusion of all intelligence sources.

How it works
------------
1. Every source casts a Signal (direction + strength + confidence + evidence).
2. The engine sums signed contributions::

       consensus_value = Σ (dir_value * strength * confidence * source_weight)

3. Thresholds turn the value into a direction (BULL > +0.2, BEAR < -0.2).
4. The agreement index measures how much of the *effective* weight agrees
   with the consensus direction.  Effective weights apply a **variance
   inflation (VIF) correction** so two highly-correlated brains (e.g. the
   backtest and the trend filter, both derived from the same bars) cannot
   double-count the same information — the v4 "source-correlation penalty".
   ``effective_n`` (Kish-style) is how many independent votes the panel
   really has; ``diversity_penalty`` = effective_n / n_sources.
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
# The News Desk (Phase 5) is deliberately modest: real sentiment, but noisy
# and often already priced in — it adds diversity, never dominance.
DEFAULT_SOURCE_WEIGHTS = {
    "kronos": 1.0,
    "backtest": 1.0,
    "rf_regime": 0.6,
    "trend_filter": 0.4,
    "llm": 0.5,
    "news": 0.35,
}

# Direction decided when |value| exceeds this.
DIRECTION_THRESHOLD = float(os.getenv("CONSENSUS_DIRECTION_THRESHOLD", "0.2"))

# ── v4: source-correlation penalty ─────────────────────────────────────
# Prior pairwise correlation between source *types*.  Sources that share the
# same bars / features (backtest ↔ trend_filter ↔ rf_regime) are deliberately
# correlated; independent brains (Kronos, the LLM cross-validator, the News
# Desk) stay near 0.10.  The matrix is symmetric, values in [0, 1], and can be
# overridden wholesale via CONSENSUS_SOURCE_CORRELATIONS (JSON with "a,b" keys).
# News is the most independent brain in the panel (it reads TEXT, not bars) —
# keep it at ~0.05-0.10 so it genuinely RAISES the effective sample size.
DEFAULT_SOURCE_CORRELATIONS = {
    ("kronos", "rf_regime"): 0.15,
    ("kronos", "backtest"): 0.10,
    ("kronos", "trend_filter"): 0.30,
    ("kronos", "llm"): 0.10,
    ("kronos", "news"): 0.05,
    ("rf_regime", "backtest"): 0.50,
    ("rf_regime", "trend_filter"): 0.45,
    ("rf_regime", "llm"): 0.20,
    ("rf_regime", "news"): 0.05,
    ("backtest", "trend_filter"): 0.40,
    ("backtest", "llm"): 0.15,
    ("backtest", "news"): 0.05,
    ("trend_filter", "llm"): 0.25,
    ("trend_filter", "news"): 0.10,
    ("llm", "news"): 0.15,
}

# Unknown source pairs fall back to this correlation.
DEFAULT_PAIR_FALLBACK = 0.15

# Whether the VIF / effective-sample-size correction is applied to agreement.
CONSENSUS_DIVERSITY_ADJUST = os.getenv(
    "CONSENSUS_DIVERSITY_ADJUST", "true").lower() == "true"


def _load_correlations():
    """Parse CONSENSUS_SOURCE_CORRELATIONS (JSON) into the pair table."""
    raw = os.getenv("CONSENSUS_SOURCE_CORRELATIONS", "").strip()
    if not raw:
        return dict(DEFAULT_SOURCE_CORRELATIONS)
    try:
        import json
        data = json.loads(raw)
    except Exception:
        return dict(DEFAULT_SOURCE_CORRELATIONS)
    out = dict(DEFAULT_SOURCE_CORRELATIONS)
    for key, val in (data or {}).items():
        parts = [p.strip().lower() for p in str(key).replace(" ", "").split(",")]
        if len(parts) == 2 and all(parts):
            try:
                out[(parts[0], parts[1]) if parts[0] < parts[1]
                    else (parts[1], parts[0])] = float(val)
            except (TypeError, ValueError):
                continue
    return out


_SOURCE_CORRELATIONS = _load_correlations()


def _pair_corr(a, b):
    """Correlation between two source types (symmetric, self=1.0)."""
    if a == b:
        return 1.0
    key = (a, b) if a < b else (b, a)
    return _SOURCE_CORRELATIONS.get(key, DEFAULT_PAIR_FALLBACK)


def _correlation_matrix(sources):
    """Sorted unique source types + their symmetric correlation matrix."""
    types = sorted(set(sources))
    n = len(types)
    mat = [[_pair_corr(a, b) for b in types] for a in types]
    return types, mat


def _vif_correction(sources, weights):
    """
    Per-source Variance Inflation Factor + Kish effective sample size.

    Returns ``(vifs_by_type, n_eff, max_vif)`` — or ``(None, None, 1.0)``
    when the correction cannot be computed (e.g. duplicate source types make
    the correlation matrix singular).  Never raises.
    """
    types, mat = _correlation_matrix(sources)
    n = len(types)
    if n < 2:
        return {types[0]: 1.0}, 1.0, 1.0
    try:
        import numpy as np
        C = np.array(mat, dtype=float)
        Cinv = np.linalg.inv(C)
        vifs = {t: float(Cinv[i, i]) for i, t in enumerate(types)}
        # Kish-style effective sample size for a weighted sum of correlated
        # votes: n_eff = (Σw)² / (Σw² + 2·Σ_{i<j} w_i w_j ρ_ij).
        total_w = sum(weights)
        w_by_type = {t: 0.0 for t in types}
        for w, s in zip(weights, sources):
            w_by_type[s] = w_by_type.get(s, 0.0) + w
        var_sum = sum(w * w for w in weights)
        for i in range(n):
            for j in range(i + 1, n):
                var_sum += 2.0 * w_by_type[types[i]] * w_by_type[types[j]] * mat[i][j]
        n_eff = (total_w * total_w) / var_sum if var_sum > 0 else 1.0
        return vifs, float(n_eff), max(vifs.values())
    except Exception:
        return None, None, 1.0


class ConsensusEngine:
    """Fuses Signals into a MarketView with attribution."""

    def __init__(self, source_weights=None, direction_threshold=None,
                 diversity_adjust=None):
        self.source_weights = dict(DEFAULT_SOURCE_WEIGHTS)
        if source_weights:
            self.source_weights.update(source_weights)
        self.direction_threshold = direction_threshold or DIRECTION_THRESHOLD
        self.diversity_adjust = (CONSENSUS_DIVERSITY_ADJUST
                                 if diversity_adjust is None
                                 else bool(diversity_adjust))

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

        # ── v4: source-correlation penalty ─────────────────────────────
        # Down-weight redundant brains: each source's effective weight is
        # weight / VIF.  Agreement is then the share of INDEPENDENT
        # information behind the conclusion, so two perfectly-correlated
        # sources cannot count twice in `agreement_index`.
        sources = [c["source"] for c in contributions]
        weights = [c["base_weight"] for c in contributions]
        vifs, n_eff, max_vif = _vif_correction(sources, weights)
        diversity_penalty = 1.0
        if self.diversity_adjust and vifs:
            diversity_penalty = max(0.0, min(1.0, n_eff / len(sources))) \
                if len(sources) else 1.0
        for c, s_type, w in zip(contributions, sources, weights):
            c["vif"] = round(vifs.get(s_type, 1.0), 4) if vifs else 1.0
            c["independent_weight"] = round(w / c["vif"], 4) \
                if self.diversity_adjust and c["vif"] else w

        # Raw (uncorrected) agreement — share of nominal weight agreeing.
        agree_weight = sum(
            c["base_weight"] for c in contributions
            if c["direction"] == direction or
            (direction == "RANGING" and c["direction"] == "RANGING"))
        agreement = agree_weight / total_weight if total_weight else 0.0

        # Independence-corrected agreement.
        eff_agree = sum(
            c["independent_weight"] for c in contributions
            if c["direction"] == direction or
            (direction == "RANGING" and c["direction"] == "RANGING"))
        eff_total = sum(c["independent_weight"] for c in contributions)
        eff_agreement = eff_agree / eff_total if eff_total > 0 else agreement

        # Strength of the conclusion.
        strength = min(1.0, abs(consensus_value))
        final_agreement = eff_agreement if self.diversity_adjust else agreement

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
            agreement_index=final_agreement,
            raw_agreement_index=agreement,
            consensus_strength=strength * final_agreement,
            contributions=contributions,
            disagreements=disagreements,
            horizon=horizon,
            symbol=symbol,
            sources=[c["source"] for c in contributions],
            cycle_id=cycle_id,
            effective_n=round(n_eff, 4) if n_eff is not None else None,
            max_vif=round(max_vif, 4),
            diversity_penalty=round(diversity_penalty, 4),
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
