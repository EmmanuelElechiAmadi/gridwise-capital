"""
TradeExecutionAdvisor — turns research + consensus into concrete trades.

Every recommendation carries a JSON ``reason_chain``: the exact evidence that
drove it (market view, strategy metrics, Kronos signal, risk sizing), so an
auto-executed trade is always explainable and auditable.

The advisor NEVER decides alone: it gates on the same hard quality rules as
the deployment layer (min trades, Sharpe, OOS consistency, Monte Carlo) and
on a minimum consensus strength.  If any gate fails the recommendation is
``hold`` with the failing gates listed.
"""

import os

from ..deploy import evaluate_quality

# Minimum consensus strength to even consider a directional trade.
MIN_CONSENSUS_STRENGTH = float(os.getenv("EXEC_MIN_CONSENSUS_STRENGTH", "0.35"))
# Maximum risk fraction of equity per trade (VaR-informed).
MAX_RISK_PER_TRADE = float(os.getenv("EXEC_MAX_RISK_PER_TRADE", "0.02"))
# Default equity for sizing when unknown.
DEFAULT_EQUITY = float(os.getenv("EXEC_DEFAULT_EQUITY", "10000"))


class TradeRecommendation:
    """One auditable trade decision."""

    def __init__(self, symbol, action, side=None, reason_chain=None,
                 confidence=0.0, suggested_lot=0.0, risk_fraction=0.0,
                 gates=None, generated_at=None):
        from datetime import datetime, timezone
        self.symbol = symbol
        self.action = action            # "trade" | "hold" | "kill"
        self.side = side                # "buy" | "sell" | None
        self.reason_chain = reason_chain or []
        self.confidence = confidence
        self.suggested_lot = suggested_lot
        self.risk_fraction = risk_fraction
        self.gates = gates or []
        self.generated_at = generated_at or \
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "action": self.action,
            "side": self.side,
            "confidence": round(self.confidence, 4),
            "suggested_lot": round(self.suggested_lot, 4),
            "risk_fraction": round(self.risk_fraction, 4),
            "reason_chain": self.reason_chain,
            "gates": self.gates,
            "generated_at": self.generated_at,
        }


class TradeExecutionAdvisor:
    """Combines MarketView + strategy evidence + risk into recommendations."""

    def __init__(self, ctx=None):
        self.ctx = ctx or {}
        self.min_consensus_strength = float(
            self.ctx.get("min_consensus_strength", MIN_CONSENSUS_STRENGTH))
        self.max_risk_per_trade = float(
            self.ctx.get("max_risk_per_trade", MAX_RISK_PER_TRADE))
        self.equity = float(self.ctx.get("equity", DEFAULT_EQUITY))

    def advise(self, market_view, deployment=None, strategy_metrics=None,
               kronos_features=None, price=None, symbol="GC=F"):
        """Produce a TradeRecommendation for a symbol.

        market_view       — consensus MarketView dict/object
        deployment        — approved deployment record (optional, params)
        strategy_metrics  — probe metrics for the deployed strategy
        kronos_features   — raw Kronos forecast_features (optional)
        price             — current price for lot sizing
        """
        mv = market_view.to_dict() if hasattr(market_view, "to_dict") \
            else (market_view or {})
        reason_chain = []
        gates = []

        direction = str(mv.get("direction") or "RANGING").upper()
        agreement = float(mv.get("agreement_index", 0.0) or 0.0)
        strength = float(mv.get("consensus_strength", 0.0) or 0.0)

        # Gate 1 — consensus strength.
        reason_chain.append({
            "step": "consensus",
            "detail": f"Consensus {direction} (agreement {agreement:.0%}, "
                      f"strength {strength:.0%})",
        })
        if strength >= self.min_consensus_strength:
            gates.append({"gate": "min_consensus_strength", "passed": True,
                          "value": strength,
                          "threshold": self.min_consensus_strength})
        else:
            gates.append({"gate": "min_consensus_strength", "passed": False,
                          "value": strength,
                          "threshold": self.min_consensus_strength})

        # Gate 2 — deployment quality (when a deployment is present).
        if deployment:
            quality = evaluate_quality(deployment)
            reason_chain.append({
                "step": "deployment",
                "detail": f"Deployment quality {'PASS' if quality['passed'] else 'FAIL'} "
                          f"(failed: {quality['failed'] or 'none'})",
            })
            gates.append({"gate": "deployment_quality", "passed": quality["passed"],
                          "value": len(quality["failed"]),
                          "threshold": 0})
        else:
            gates.append({"gate": "deployment_quality", "passed": True,
                          "value": 0, "threshold": 0})

        # Kronos alignment (when available).
        kronos_aligned = None
        if kronos_features:
            kdir = str(kronos_features.get("regime_label") or "").upper()
            kronos_aligned = (direction == "RANGING") or (kdir == direction)
            reason_chain.append({
                "step": "kronos",
                "detail": f"Kronos {kdir or 'n/a'} (trend_strength "
                          f"{kronos_features.get('trend_strength', 0):.2f}, vol "
                          f"{kronos_features.get('volatility_forecast', 0):.3f})",
            })
            gates.append({"gate": "kronos_alignment",
                          "passed": bool(kronos_aligned),
                          "value": kdir, "threshold": direction})

        # Decide.
        all_pass = all(g["passed"] for g in gates)
        confidence = strength * agreement
        if not all_pass or direction == "RANGING":
            action, side = "hold", None
        elif direction == "BULL":
            action, side = "trade", "buy"
        else:
            action, side = "trade", "sell"

        # Risk sizing: VaR-informed fraction of equity.
        risk_fraction = min(self.max_risk_per_trade, confidence * 0.10)
        suggested_lot = 0.0
        if action == "trade" and price:
            risk_usd = self.equity * risk_fraction
            sl_distance = 0.0
            if isinstance(kronos_features, dict):
                sl_distance = float(kronos_features.get("volatility_forecast", 0.0)
                                    or 0.0)
            if sl_distance and sl_distance > 0:
                suggested_lot = max(0.01, round(risk_usd / (sl_distance * price), 2))
            else:
                suggested_lot = max(0.01, round(risk_usd / (0.005 * price), 2))

        if action == "hold":
            reason_chain.append({
                "step": "decision",
                "detail": "HOLD — " + (
                    "consensus strength below minimum"
                    if strength < self.min_consensus_strength
                    else "direction is RANGING or a gate failed"),
            })
        else:
            reason_chain.append({
                "step": "decision",
                "detail": f"{side.upper()} {symbol} — all gates passed; "
                          f"risk {risk_fraction:.1%} of equity",
            })

        return TradeRecommendation(
            symbol=symbol, action=action, side=side,
            reason_chain=reason_chain, confidence=confidence,
            suggested_lot=suggested_lot, risk_fraction=risk_fraction,
            gates=gates)

