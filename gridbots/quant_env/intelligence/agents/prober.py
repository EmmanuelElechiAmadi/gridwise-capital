"""
MarketProberAgent — the *Interviewer* replacement.

Interviewer (InsightForge)        -> Market Prober
Human role replaced               -> Quant Researcher (Hypothesis Testing)

Primary responsibility: "interview the market".  Instead of asking a human
questions, the Prober interrogates market data with regime-conditioned
backtests, optimization sweeps and out-of-sample walk-forward validation.
The market "answers" with fills, equity curves and PnL — and the Prober
adapts its parameter grid (interview guide) based on the answers it gets.
"""

import os

import pandas as pd

from .base import BaseAgent
from ..ledger import Probe

_QUANT_ENV_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_PROJECT_ROOT = os.path.dirname(_QUANT_ENV_ROOT)
_DEFAULT_SYMBOL = "GC=F"


class MarketProberAgent(BaseAgent):
    KEY = "prober"
    ROLE = "Market Prober"
    REPLACES = "Quant Researcher (Hypothesis Testing)"
    PRIMARY_RESPONSIBILITY = (
        "Interviews the market with backtests and out-of-sample validation, "
        "adapting the parameter grid dynamically based on the market's answers."
    )
    INTEGRATIONS = ["BacktestEngine", "Walk-forward", "Optimizer", "ML regime adapter"]

    def __init__(self, ctx=None):
        super().__init__(ctx)
        self.project_root = self.ctx.get("project_root") or _DEFAULT_PROJECT_ROOT
        self.max_bars = int(self.ctx.get("max_bars", 1500))
        self.probe_limit = int(self.ctx.get("probe_limit", 4))
        self.validate_oos = bool(self.ctx.get("validate_oos", True))
        raw_symbols = str(self.ctx.get("symbols") or os.getenv("RESEARCH_SYMBOLS", "GC=F"))
        self.symbols = [s.strip() for s in raw_symbols.split(",") if s.strip()] or ["GC=F"]
        self._data = None
        self._data_full = None
        self._data_cache = {}   # symbol -> (tail_df, full_df)

    # ── Run ───────────────────────────────────────────────────────────
    def run(self, ledger):
        from strategies.registry import list_strategies, get_class

        strategies = list_strategies() or []
        probed = 0
        skipped = 0
        validated = 0
        symbols_probed = []

        for symbol in self.symbols:
            data = self._load_data_for(symbol)
            if data is None:
                self.log(f"No cached data for {symbol} — skipping")
                continue
            symbols_probed.append(symbol)

            for meta in strategies:
                key = meta["key"]
                cls = get_class(key)
                if cls is None:
                    continue
                variants = self._build_variants(meta)
                for params in variants[: max(1, self.probe_limit)]:
                    probe = self._run_backtest(key, cls, data, params, symbol=symbol)
                    ledger.add_probe(probe)
                    probed += 1
                    if not probe.has_trades:
                        skipped += 1

            # Deep interview follow-up: validate each strategy's best probe
            # out-of-sample on an older, disjoint window of this symbol.
            if self.validate_oos:
                for meta in strategies:
                    key = meta["key"]
                    best = ledger.best_probe(key, symbol=symbol)
                    if best is None or not best.has_trades:
                        continue
                    cls = get_class(key)
                    if cls is None:
                        continue
                    oos_probe = self._run_oos_probe(key, cls, best.params, symbol=symbol)
                    if oos_probe is not None:
                        ledger.add_probe(oos_probe)
                        validated += 1

        if not symbols_probed:
            self.log("No cached market data — falling back to stored engine artifacts")
            for meta in strategies:
                key = meta["key"]
                cls = get_class(key)
                if cls is None:
                    continue
                for params in self._build_variants(meta)[: max(1, self.probe_limit)]:
                    probe = self._artifact_probe(key, params)
                    ledger.add_probe(probe)
                    probed += 1
                    if not probe.has_trades:
                        skipped += 1

        self.log(f"Probed {probed} strategy-variant combinations across {symbols_probed or ['artifacts']} "
                 f"({skipped} produced no trades, {validated} OOS revalidations)")

        return self._report(
            data_loaded=len(symbols_probed) > 0,
            bars=len(self._data) if self._data is not None else 0,
            symbols=symbols_probed,
            probes=[p.to_dict() for p in ledger.probes],
            probed=probed, skipped=skipped, validated=validated,
        )

    # ── Data loading (per-symbol cached CSVs) ─────────────────────────
    def _load_data(self):
        """Gold window (backward-compatible helper)."""
        return self._load_data_for("GC=F")

    def _load_data_for(self, symbol):
        """Recent-window OHLCV for a symbol, cached per symbol."""
        if symbol in self._data_cache:
            return self._data_cache[symbol][0]
        if symbol in ("GC=F", "XAUUSD.r", "XAUUSD=F"):
            full, tail = self._load_gold_data()
        else:
            from ..data import load_cached_history
            full = load_cached_history(self.project_root, symbol)
            tail = (full.tail(self.max_bars).copy()
                    if full is not None and not full.empty else None)
        self._data_cache[symbol] = (tail, full)
        return tail

    def _data_full_for(self, symbol):
        """Full cached frame for a symbol (for disjoint OOS windows)."""
        if symbol not in self._data_cache:
            self._load_data_for(symbol)
        entry = self._data_cache.get(symbol, (None, None))
        return entry[1] if entry else None

    def _load_gold_data(self):
        """Full + recent-window gold frame (existing behavior)."""
        path = os.path.join(self.project_root, "gold_data.csv")
        if not os.path.exists(path):
            self._data = None
            self._data_full = None
            return None, None
        try:
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            rename = {"Open": "open", "High": "high", "Low": "low",
                      "Close": "close", "Volume": "volume"}
            df.rename(columns=rename, inplace=True)
            df.index = pd.to_datetime(df.index)
            df = df.sort_index()
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=["open", "high", "low", "close"])
            self._data_full = df if not df.empty else None
            self._data = (df.tail(self.max_bars).copy()
                          if df is not None and not df.empty else None)
        except Exception as e:
            self.log(f"Failed to load cached data: {e}")
            self._data = None
            self._data_full = None
        return self._data_full, self._data

    # ── Interview guide ───────────────────────────────────────────────
    def _build_variants(self, meta):
        """
        Build the interview guide: the parameter grid we probe.  Variant 0 is
        the strategy's declared defaults; further variants widen the primary
        numeric parameter (a cheap adaptive follow-up).
        """
        defaults = {}
        for pname, pmeta in (meta.get("params") or {}).items():
            defaults[pname] = pmeta.get("default")
        variants = [defaults]
        numeric = [k for k, v in (meta.get("params") or {}).items()
                   if isinstance(v, dict) and v.get("type") == "number"
                   and isinstance(v.get("default"), (int, float))]
        if numeric:
            widened = dict(defaults)
            key = numeric[0]
            step = (meta["params"][key].get("step") or 1) or 1
            widened[key] = float(defaults[key]) + 2.0 * float(step)
            variants.append(widened)
        return variants

    # ── Asking the market ─────────────────────────────────────────────
    def _run_backtest(self, key, cls, data, params, oos=False, note=None, symbol=None):
        from backtest.engine import BacktestEngine
        from analysis.performance import compute_metrics

        safe = {k: v for k, v in params.items()
                if isinstance(v, (int, float, str, bool)) and v is not None}
        result = None
        try:
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                engine = BacktestEngine(data.copy(), cls, initial_cash=10000, **safe)
                result = engine.run()
            metrics = compute_metrics(result.fills_df, result.equity_df)
        except Exception as e:
            self.log(f"Probe failed for {key} {params}: {e}")
            metrics = {"error": str(e)}

        # Monte Carlo stress on the equity curve (cheap, numpy only).
        if result is not None:
            mc = self._monte_carlo_metrics(result.equity_df)
            if mc:
                metrics = dict(metrics)
                metrics["monte_carlo"] = mc

        regime = self._guess_regime(data)
        return Probe(
            strategy_key=key, symbol=symbol or _DEFAULT_SYMBOL, timeframe="1m",
            params=params, metrics=metrics, oos=oos, regime=regime,
            data_bars=len(data),
            note=note or ("out-of-sample validation" if oos else "live engine probe"),
        )

    def _run_oos_probe(self, key, cls, params, symbol="GC=F"):
        """Follow-up interview: same params on an older, disjoint window."""
        full = self._data_full_for(symbol)
        if full is None or len(full) < 2 * self.max_bars + 60:
            return None
        oos_slice = full.iloc[: self.max_bars].copy()
        if len(oos_slice) < 120:
            return None
        return self._run_backtest(key, cls, oos_slice, params, oos=True, symbol=symbol)

    @staticmethod
    def _monte_carlo_metrics(equity_df, sims=200, horizon=60):
        """Bootstrap the observed equity returns; return tail-risk stats."""
        try:
            import numpy as np
            if equity_df is None or equity_df.empty or len(equity_df) < 10:
                return {}
            eq = pd.to_numeric(equity_df["equity"]).values.astype(float)
            rets = np.diff(eq) / eq[:-1]
            rets = rets[np.isfinite(rets)]
            if len(rets) < 5:
                return {}
            rng = np.random.default_rng(42)
            curves = np.ones((sims, horizon))
            for i in range(sims):
                sampled = rng.choice(rets, size=horizon, replace=True)
                curves[i] = 1.0 + np.cumsum(sampled)
            finals = curves[:, -1]
            return {
                "mc_prob_profit_pct": round(float((finals > 1.0).mean() * 100), 1),
                "mc_var_95_pct": round(float((np.percentile(finals, 5) - 1.0) * 100), 2),
                "mc_median_max_dd_pct": round(float(np.median(
                    np.max(np.maximum.accumulate(curves, axis=1) - curves, axis=1)) * 100), 2),
            }
        except Exception:
            return {}

    def _artifact_probe(self, key, params):
        """Offline fallback: build a probe from stored strategy_results.json."""
        path = os.path.join(_QUANT_ENV_ROOT, "strategy_results.json")
        metrics = {}
        if os.path.exists(path):
            try:
                import json
                with open(path) as f:
                    results = json.load(f)
                op = (results.get(key) or {}).get("backtest") or {}
                metrics = op.get("metrics") or {}
            except Exception:
                pass
        return Probe(
            strategy_key=key, symbol=_DEFAULT_SYMBOL, timeframe="1m",
            params=params, metrics=metrics, oos=False, regime=None,
            data_bars=0, note="artifact fallback probe (no live data)",
        )

    def _guess_regime(self, data):
        """Cheap regime estimate from recent trend vs. volatility."""
        if data is None or len(data) < 60:
            return "unknown"
        try:
            close = data["close"]
            short = float(close.iloc[-1] / close.iloc[-20] - 1)
            long = float(close.iloc[-1] / close.iloc[-60] - 1)
            vol = float(close.pct_change().tail(20).std())
            if short > 0.02 and long > 0.02:
                return "bull"
            if short < -0.02 and long < -0.02:
                return "bear"
            if vol < 0.01:
                return "ranging"
            return "mixed"
        except Exception:
            return "unknown"
