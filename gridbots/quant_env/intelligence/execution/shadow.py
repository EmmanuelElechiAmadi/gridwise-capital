"""
ShadowForwardTester — prove a deployment in simulation BEFORE it goes live.

An approved deployment is not trusted on backtest alone: it must survive a
"forward test" on a disjoint, recent slice of history it never saw during the
original probe.  Only a deployment whose forward-test metrics clear the same
hard quality gates is promoted (``status = "promoted"``); anything else stays
``held`` (or ``insufficient_data`` when there is no history).

Shadow reports are written to ``output/shadow_reports.json`` and exposed on
the dashboard.
"""

import json
import os
import uuid
from datetime import datetime, timezone

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "output")
SHADOW_REPORTS_PATH = os.path.join(OUTPUT_DIR, "shadow_reports.json")

# Forward-test requirements (configurable via env).
SHADOW_MIN_TRADES = int(os.getenv("SHADOW_MIN_TRADES", "20"))
SHADOW_MIN_SHARPE = float(os.getenv("SHADOW_MIN_SHARPE", "0.6"))
SHADOW_MIN_MC_PROB = float(os.getenv("SHADOW_MIN_MC_PROB", "55.0"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ShadowForwardTester:
    """Runs a deployment on a held-out forward window and decides promote/hold."""

    def __init__(self, path=None):
        self.path = path or SHADOW_REPORTS_PATH
        self.reports = []
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    self.reports = json.load(f)
            except Exception:
                self.reports = []

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self.reports, f, indent=2, default=str)

    def test(self, deployment, history, forward_window=200):
        """Run the deployment's strategy on the most recent ``forward_window``
        bars (disjoint from the probe's in-sample window) and evaluate.

        ``history`` is an OHLCV DataFrame.  Returns a shadow report dict with
        ``status`` in (``promoted``, ``held``, ``insufficient_data``).
        """
        report = {
            "id": uuid.uuid4().hex[:12],
            "deployment_id": (deployment or {}).get("id"),
            "strategy_key": (deployment or {}).get("strategy_key"),
            "params": dict((deployment or {}).get("params") or {}),
            "run_at": _now_iso(),
        }
        if history is None or len(history) < 60:
            report.update(status="insufficient_data", reason="history too short")
            self.reports.append(report)
            self.save()
            return report

        window = history.tail(forward_window).copy()
        try:
            metrics = self._forward_backtest(
                (deployment or {}).get("strategy_key", "grid_strategy"),
                (deployment or {}).get("params") or {}, window)
        except Exception as e:
            report.update(status="held", reason=f"forward backtest failed: {e}")
            self.reports.append(report)
            self.save()
            return report

        trades = int(metrics.get("num_trades", 0) or 0)
        sharpe = float(metrics.get("sharpe_ratio", 0.0) or 0.0)
        mc = metrics.get("monte_carlo") or {}
        mc_prob = float(mc.get("mc_prob_profit_pct", 0.0) or 0.0)

        gates = [
            {"gate": "shadow_min_trades", "passed": trades >= SHADOW_MIN_TRADES,
             "value": trades, "threshold": SHADOW_MIN_TRADES},
            {"gate": "shadow_min_sharpe", "passed": sharpe >= SHADOW_MIN_SHARPE,
             "value": sharpe, "threshold": SHADOW_MIN_SHARPE},
            {"gate": "shadow_min_mc_prob", "passed": mc_prob >= SHADOW_MIN_MC_PROB,
             "value": mc_prob, "threshold": SHADOW_MIN_MC_PROB},
        ]
        passed = all(g["passed"] for g in gates)
        report.update({
            "status": "promoted" if passed else "held",
            "metrics": metrics,
            "gates": gates,
            "window_bars": len(window),
            "reason": ("forward test cleared all gates"
                       if passed else "forward test failed gates"),
        })
        self.reports.append(report)
        self.save()
        return report

    def _forward_backtest(self, strategy_key, params, df):
        """Run the real backtest engine on the forward window (reuses the
        engine's cost model, commission, slippage, drawdown stop)."""
        from strategies.registry import get_class
        from backtest.engine import BacktestEngine
        from analysis.performance import compute_metrics

        cls = get_class(strategy_key)
        if cls is None:
            raise ValueError(f"unknown strategy {strategy_key}")

        engine = BacktestEngine(df, cls, initial_cash=10000, **params)
        result = engine.run()
        metrics = compute_metrics(result.fills_df, result.equity_df)
        if metrics is not None:
            return dict(metrics)
        return {}
