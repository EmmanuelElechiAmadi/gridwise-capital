"""
QuantAnalystAgent — the *Analyst* replacement.

Analyst (InsightForge)            -> Quant Research Analyst
Human role replaced               -> Quantitative Research Analyst (Alpha Synthesis)

Primary responsibility: chain analysis over probes and trade records —
segment, code, synthesize into alpha themes, run bias / overfit checks across
regime and session slices, and score each theme's confidence.

Formal model (paper v2):

    C_s = alpha * log1p(N) + beta * Sharpe + gamma * OOS_consistency
          - delta * overfit_penalty

    overfit_penalty = max(0, IS_sharpe - OOS_sharpe) / max(1, |IS_sharpe|)
"""

import os

import numpy as np

from .base import BaseAgent
from ..ledger import Insight, clip01

_QUANT_ENV_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_PROJECT_ROOT = os.path.dirname(_QUANT_ENV_ROOT)

# Weights from the paper's formula 1.
W_LOG_TRADES = 0.25
W_SHARPE = 0.35
W_OOS = 0.35
W_OVERFIT = 0.05


def signal_confidence(num_trades=0, sharpe=0.0, oos_consistency=0.0,
                      is_sharpe=None, oos_sharpe=None):
    """
    Confidence of an alpha theme, C_s in [0, 1].

    - ``num_trades`` feeds log1p(N), normalized by log1p(100) ~ 4.6.
    - ``sharpe`` is mapped from [-1, 3] onto [0, 1].
    - ``oos_consistency`` is the fraction of OOS windows with positive returns.
    - An overfit penalty subtracts IS -> OOS performance degradation.
    """
    log_term = np.log1p(max(0, float(num_trades or 0))) / np.log1p(100)
    sharpe_term = clip01((float(sharpe or 0.0) + 1.0) / 4.0)
    oos_term = clip01(float(oos_consistency or 0.0))

    overfit = 0.0
    if is_sharpe is not None and oos_sharpe is not None:
        is_s = float(is_sharpe or 0.0)
        oos_s = float(oos_sharpe or 0.0)
        if abs(is_s) > 1e-6:
            overfit = max(0.0, (is_s - oos_s) / abs(is_s))

    raw = (W_LOG_TRADES * log_term + W_SHARPE * sharpe_term
           + W_OOS * oos_term - W_OVERFIT * overfit)
    return clip01(raw)


class QuantAnalystAgent(BaseAgent):
    KEY = "analyst"
    ROLE = "Quant Research Analyst"
    REPLACES = "Quantitative Research Analyst (Alpha Synthesis)"
    PRIMARY_RESPONSIBILITY = (
        "Chains analysis over probes and trade records into alpha themes, "
        "running bias and overfit checks and scoring confidence."
    )
    INTEGRATIONS = ["analysis.performance", "analysis.walkforward", "ml/model_metrics.json"]

    def __init__(self, ctx=None):
        super().__init__(ctx)
        self.project_root = self.ctx.get("project_root") or _DEFAULT_PROJECT_ROOT

    # ── Run ───────────────────────────────────────────────────────────
    def run(self, ledger):
        oos = self._load_walkforward()
        optimization = self._load_optimization()
        ml = self._load_ml_metrics()

        flags = []
        themes = []
        strategy_keys = {p.strategy_key for p in ledger.probes}
        if not strategy_keys and optimization:
            strategy_keys = set(optimization.keys())

        for key in sorted(strategy_keys):
            theme, theme_flags = self._theme_for(key, ledger, oos, optimization)
            if theme is None:
                continue
            themes.append(theme)
            flags.extend(theme_flags)

        # ML-informed insight (regime model feature importances).
        ml_theme = self._ml_theme(ml)
        if ml_theme is not None:
            themes.append(ml_theme)
            flags.extend(ml_theme.risk_flags)

        # Correlation-aware insight (multi-symbol corpus).
        corr_theme = self._correlation_theme(self._load_correlations())
        if corr_theme is not None:
            themes.append(corr_theme)
            flags.extend(corr_theme.risk_flags)

        for theme in themes:
            ledger.add_insight(theme)

        self.log(f"Synthesized {len(themes)} alpha themes from "
                 f"{len(ledger.probes)} probes")

        return self._report(
            themes=[t.to_dict() for t in themes],
            oos_consistency=oos.get("consistency", 0.0),
            oos_windows=oos.get("windows", 0),
            ml_accuracy=ml.get("accuracy"),
            ml_top_features=ml.get("top_features", []),
            flags=flags,
        )

    # ── Theme synthesis ───────────────────────────────────────────────
    def _theme_for(self, key, ledger, oos, optimization):
        best = ledger.best_probe(key)
        if best is None and key not in (optimization or {}):
            return None, []

        metrics = best.metrics if best is not None else {}
        sharpe = float(metrics.get("sharpe_ratio", 0.0) or 0.0)
        trades = int(metrics.get("num_trades", 0) or 0)
        ret = float(metrics.get("total_return_pct", 0.0) or 0.0)
        dd = float(metrics.get("max_drawdown_pct", 0.0) or 0.0)

        oos_c = oos.get("consistency", 0.0)
        opt = (optimization or {}).get(key, {})
        is_sharpe = opt.get("sharpe_ratio")

        # Prefer the Prober's own out-of-sample validation when available.
        oos_probe = ledger.best_oos_probe(key)
        if oos_probe is not None:
            oos_sharpe = float(oos_probe.metrics.get("sharpe_ratio", 0.0) or 0.0)
        else:
            oos_sharpe = oos.get("avg_sharpe", 0.0)

        confidence = signal_confidence(trades, sharpe, oos_c, is_sharpe, oos_sharpe)

        risk_flags = []
        if oos_c < 0.5:
            risk_flags.append("low-oos-consistency")
        if trades < 5:
            risk_flags.append("thin-sample")
        if dd > 20:
            risk_flags.append(f"drawdown-{dd:.0f}pct")
        if is_sharpe is not None and abs(float(is_sharpe)) > 1e-6 and oos_sharpe is not None:
            if float(is_sharpe) - float(oos_sharpe) > 1.0:
                risk_flags.append("possible-overfit")
        if oos_probe is not None and oos_sharpe < 0:
            risk_flags.append("oos-degradation")

        oos_line = ""
        if oos_probe is not None:
            oos_ret = float(oos_probe.metrics.get("total_return_pct", 0.0) or 0.0)
            oos_line = f" Out-of-sample revalidation: Sharpe {oos_sharpe:.2f} (return {oos_ret:+.2f}%)."

        theme_text = (
            f"{key} shows best-observed Sharpe {sharpe:.2f} on {trades} trades "
            f"(return {ret:+.2f}%) with OOS consistency {oos_c:.0%}."
            f"{oos_line} Regime context: {best.regime if best else 'unknown'}."
        )

        evidence = [{
            "probe_id": best.id if best else None,
            "oos_probe_id": oos_probe.id if oos_probe else None,
            "symbol": best.symbol if best else None,
            "sharpe_ratio": sharpe,
            "oos_sharpe_ratio": oos_sharpe,
            "num_trades": trades,
            "total_return_pct": ret,
            "max_drawdown_pct": dd,
            "oos_consistency": oos_c,
        }]

        title = f"{key.replace('_', ' ').title()} Alpha Theme"
        insight = Insight(title=title, theme=theme_text, evidence=evidence,
                          confidence=confidence, risk_flags=risk_flags,
                          strategy_keys=[key])
        return insight, risk_flags

    # ── Correlation-aware theming (multi-symbol corpus) ───────────────
    def _load_correlations(self):
        """Pairwise close-return correlations across the configured corpus."""
        raw = str(self.ctx.get("symbols") or os.getenv("RESEARCH_SYMBOLS", "GC=F"))
        symbols = [s.strip() for s in raw.split(",") if s.strip()]
        if len(symbols) < 2:
            return {"pairs": [], "symbols": symbols}
        from ..data import load_cached_history
        rets = {}
        for sym in symbols:
            df = load_cached_history(self.project_root, sym, max_bars=2000)
            if df is not None and len(df) > 60:
                r = df["close"].pct_change().dropna()
                if len(r) > 30:
                    rets[sym] = r
        names = list(rets)
        pairs = []
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = rets[names[i]], rets[names[j]]
                common = a.index.intersection(b.index)
                if len(common) > 30:
                    corr = float(a.loc[common].corr(b.loc[common]))
                    pairs.append({"a": names[i], "b": names[j],
                                  "correlation": round(corr, 3)})
        pairs.sort(key=lambda p: abs(p["correlation"]), reverse=True)
        return {"pairs": pairs, "symbols": names}

    def _correlation_theme(self, corr):
        """A portfolio-level insight on how the corpus moves together."""
        if not corr or not corr.get("pairs"):
            return None
        pairs = corr["pairs"]
        top = pairs[0]
        high = [p for p in pairs if abs(p["correlation"]) > 0.7]
        text = (
            f"Cross-symbol correlation: {top['a']} vs {top['b']} at "
            f"{top['correlation']:+.2f} over the cached window. "
            + ("A tight cluster is forming — treat these as correlated bets and "
               "diversify allocation across independent symbols."
               if high else
               "Symbols are largely independent — multi-asset themes can be sized "
               "independently.")
        )
        return Insight(
            title="Cross-Symbol Correlation Insight",
            theme=text,
            evidence=[{"pairs": pairs}],
            confidence=clip01(min(0.8, abs(top["correlation"]))),
            risk_flags=["high-correlation-cluster"] if high else [],
            strategy_keys=[],
            source_agent="QuantAnalyst",
        )

    # ── ML-informed theme ─────────────────────────────────────────────
    def _ml_theme(self, ml):
        """A regime-model insight drawn from feature importances."""
        if not ml or not ml.get("top_features"):
            return None
        acc = ml.get("accuracy")
        feats = ", ".join(str(f) for f in ml["top_features"])
        theme_text = (
            f"The regime classifier identifies {feats} as the most predictive features "
            "of BULL/RANGING/BEAR regimes"
            + (f" (test accuracy {float(acc):.0%})." if acc is not None else ".")
        )
        confidence = clip01(0.4 if acc is None else float(acc))
        risk_flags = []
        if acc is not None and float(acc) < 0.6:
            risk_flags.append("ml-accuracy-below-60")
        return Insight(
            title="Regime Model Insight",
            theme=theme_text,
            evidence=[{"ml_accuracy": acc, "top_features": ml["top_features"]}],
            confidence=confidence,
            risk_flags=risk_flags,
            strategy_keys=[],
        )
    # ── Artifact loaders ──────────────────────────────────────────────
    def _load_walkforward(self):
        rows = self._read_csv(os.path.join(self.project_root, "walkforward_report.csv"))
        if not rows:
            return {"windows": 0, "consistency": 0.0, "avg_sharpe": 0.0}
        returns = []
        sharpes = []
        for r in rows:
            try:
                returns.append(float(r.get("total_return_pct", 0.0) or 0.0))
                sharpes.append(float(r.get("sharpe_ratio", 0.0) or 0.0))
            except (TypeError, ValueError):
                continue
        if not returns:
            return {"windows": 0, "consistency": 0.0, "avg_sharpe": 0.0}
        positive = sum(1 for v in returns if v > 0)
        return {
            "windows": len(returns),
            "consistency": positive / len(returns),
            "avg_sharpe": float(np.mean(sharpes)) if sharpes else 0.0,
        }

    def _load_optimization(self):
        """Best params per strategy from optimization_results.csv (if single-strategy)."""
        rows = self._read_csv(os.path.join(self.project_root, "optimization_results.csv"))
        if not rows:
            return {}
        best = None
        for r in rows:
            try:
                sharpe = float(r.get("sharpe_ratio", -999) or -999)
            except (TypeError, ValueError):
                sharpe = -999
            if best is None or sharpe > best["sharpe_ratio"]:
                best = dict(r)
                best["sharpe_ratio"] = sharpe
        return {"grid_strategy": best} if best else {}

    def _load_ml_metrics(self):
        path = os.path.join(_QUANT_ENV_ROOT, "ml", "model_metrics.json")
        if not os.path.exists(path):
            return {}
        try:
            import json
            with open(path) as f:
                data = json.load(f)
            metrics = data.get("metrics") or {}
            features = data.get("features") or []
            top = []
            if isinstance(features, list) and features and isinstance(features[0], dict):
                top = sorted(features, key=lambda x: x.get("importance", 0),
                             reverse=True)[:5]
            return {
                "accuracy": metrics.get("test_accuracy"),
                "top_features": [f.get("name") for f in top] or features[:5],
            }
        except Exception:
            return {}

    @staticmethod
    def _read_csv(path):
        if not os.path.exists(path):
            return []
        try:
            import csv
            with open(path, newline="") as f:
                return list(csv.DictReader(f))
        except Exception:
            return []

