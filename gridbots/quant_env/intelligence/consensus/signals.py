"""
Signals — typed, attributed votes from every intelligence source.

A Signal is the lingua franca of the consensus layer: every source (Kronos,
RF regime model, backtests, LLM verdict) is normalized into the same shape so
the engine can fuse them and explain the result.
"""

from dataclasses import dataclass, field, asdict
from typing import Dict

DIRECTIONS = ("BULL", "BEAR", "RANGING")
_DIR_VALUE = {"BULL": 1.0, "RANGING": 0.0, "BEAR": -1.0}


def clip01(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    if v != v:  # NaN
        return 0.0
    return max(0.0, min(1.0, v))


@dataclass
class Signal:
    """One normalized vote from one evidence source."""

    source: str                 # "kronos" | "rf_regime" | "backtest" | "llm" | "trend_filter"
    direction: str              # BULL / BEAR / RANGING
    strength: float = 0.0       # 0..1 how strongly the signal points that way
    confidence: float = 0.0     # 0..1 the source's self-reported reliability
    horizon: str = "medium"     # short / medium / long
    symbol: str = "GC=F"
    evidence: Dict = field(default_factory=dict)
    note: str = ""

    def __post_init__(self):
        self.direction = str(self.direction or "RANGING").upper()
        if self.direction not in DIRECTIONS:
            self.direction = "RANGING"
        self.strength = clip01(self.strength)
        self.confidence = clip01(self.confidence)

    @property
    def value(self) -> float:
        """Signed, weighted vote contribution in [-1, 1]."""
        return _DIR_VALUE[self.direction] * self.strength * self.confidence

    @property
    def weight(self) -> float:
        """Base weight assigned by source type (strength * confidence)."""
        return self.strength * self.confidence

    def to_dict(self) -> dict:
        return asdict(self)

    # ── Source adapters ────────────────────────────────────────────────
    @classmethod
    def from_kronos(cls, features, symbol="GC=F"):
        """Adapt a Kronos forecast_features dict into a Signal.

        features keys (from ml.kronos.predictor.get_forecast_features):
            regime_label / trend_strength / volatility_forecast / trend
        """
        if not features:
            return None
        label = str(features.get("regime_label") or "RANGING").upper()
        trend_strength = float(features.get("trend_strength") or 0.0)
        vol = float(features.get("volatility_forecast") or 0.0)
        # Normalize trend_strength onto [0,1]: 0..2 SNR is typical.
        strength = clip01(min(trend_strength, 2.0) / 2.0)
        # Confidence drops as forecast volatility rises (more uncertainty).
        conf = clip01(0.9 - 5.0 * vol)
        return cls(
            source="kronos", direction=label, strength=strength,
            confidence=conf, horizon="medium", symbol=symbol,
            evidence={
                "regime_label": label, "trend_strength": trend_strength,
                "volatility_forecast": vol,
                "trend": features.get("trend"),
            },
            note="Kronos foundation-model forecast (regime + signal-to-noise)",
        )

    @classmethod
    def from_rf_regime(cls, regime, confidence, symbol="GC=F"):
        """Adapt the RF regime classifier's output into a Signal."""
        if not regime:
            return None
        label = {"bull": "BULL", "bear": "BEAR", "ranging": "RANGING"}.get(
            str(regime).lower(), str(regime).upper())
        return cls(
            source="rf_regime", direction=label,
            strength=clip01(confidence), confidence=clip01(confidence),
            horizon="medium", symbol=symbol,
            evidence={"regime": str(regime), "classifier_confidence": confidence},
            note="RandomForest regime classifier (37 features)",
        )

    @classmethod
    def from_backtest(cls, strategy_key, metrics, symbol="GC=F",
                      source="backtest"):
        """Adapt one probe's metrics into a directional Signal.

        The direction comes from the strategy's realized edge: Sharpe > 0
        with enough trades and OOS consistency.  When the evidence is thin
        (few trades) the strength is crushed so it cannot dominate the vote.
        """
        metrics = metrics or {}
        trades = float(metrics.get("num_trades", 0) or 0)
        sharpe = float(metrics.get("sharpe_ratio", 0.0) or 0.0)
        ret = float(metrics.get("total_return_pct", 0.0) or 0.0)
        oos = float(metrics.get("oos_consistency",
                                metrics.get("consistency", 0.0)) or 0.0)
        mc = metrics.get("monte_carlo") or {}
        mc_prob = float(mc.get("mc_prob_profit_pct", 0.0) or 0.0)

        if sharpe > 0:
            direction = "BULL"
        elif sharpe < 0:
            direction = "BEAR"
        else:
            direction = "RANGING"

        # Strength = normalized Sharpe * OOS * trade-count discount.
        sharpe_norm = clip01((abs(sharpe) + 1.0) / 4.0)
        trade_factor = clip01(min(trades, 100.0) / 100.0)  # tiny samples crushed
        strength = clip01(sharpe_norm * 0.5
                          + clip01(oos) * 0.3
                          + clip01(mc_prob / 100.0) * 0.2) * trade_factor
        confidence = clip01(0.3 + 0.7 * trade_factor)
        return cls(
            source=source, direction=direction, strength=strength,
            confidence=confidence, horizon="medium", symbol=symbol,
            evidence={
                "strategy_key": strategy_key,
                "sharpe_ratio": sharpe, "total_return_pct": ret,
                "num_trades": trades, "oos_consistency": oos,
                "mc_prob_profit_pct": mc_prob,
            },
            note=f"backtest/walk-forward evidence for {strategy_key}",
        )



    @classmethod
    def from_llm_verdict(cls, verdict, symbol="GC=F"):
        """Adapt the LLM cross-validator's structured verdict into a Signal.

        verdict keys: direction / confidence / strengths_risks ...
        """
        if not verdict or not isinstance(verdict, dict):
            return None
        direction = str(verdict.get("direction") or "RANGING").upper()
        return cls(
            source="llm", direction=direction,
            strength=clip01(verdict.get("strength", 0.5)),
            confidence=clip01(verdict.get("confidence", 0.5)),
            horizon=str(verdict.get("horizon", "medium")),
            symbol=symbol,
            evidence=verdict,
            note="LLM cross-validation verdict over the full evidence bundle",
        )

    @classmethod
    def from_news(cls, verdict, symbol="GC=F"):
        """Adapt the News Desk's Claude Sonnet verdict into a Signal.

        The verdict is the output of ``LLMNarrator.analyze_news`` — already
        passed through ``fact_check_news_verdict`` (verbatim headline
        citations). News is an explicitly SHORT-horizon, low-weight source:
        sentiment is real but noisy and often already priced in.
        """
        if not verdict or not isinstance(verdict, dict):
            return None
        direction = str(verdict.get("direction") or "RANGING").upper()
        cited = list(verdict.get("evidence_cited") or [])
        return cls(
            source="news", direction=direction,
            strength=clip01(verdict.get("strength", 0.5)),
            confidence=clip01(verdict.get("confidence", 0.5)),
            horizon=str(verdict.get("horizon", "short")),
            symbol=symbol,
            evidence={
                "articles_cited": cited,
                "key_themes": list(verdict.get("key_themes") or []),
                "risks": list(verdict.get("risks") or []),
                "rationale": verdict.get("rationale", ""),
                "fact_check": verdict.get("_fact_check"),
            },
            note="News Desk verdict (Claude Sonnet over trading headlines), "
                 "verified against Kronos + RF in the consensus",
        )

    @classmethod
    def from_trend_filter(cls, trend, strength=0.5, symbol="GC=F"):
        """Adapt the deterministic trend filter into a Signal."""
        if not trend:
            return None
        direction = {"bull": "BULL", "bear": "BEAR", "ranging": "RANGING",
                     "sideways": "RANGING", "mixed": "RANGING"}.get(
            str(trend).lower(), str(trend).upper())
        return cls(
            source="trend_filter", direction=direction,
            strength=clip01(strength), confidence=0.6,
            horizon="short", symbol=symbol,
            evidence={"trend": str(trend), "strength": strength},
            note="deterministic trend filter (regime estimate from price path)",
        )
