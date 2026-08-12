"""
Signal collection — gather evidence from the engine's real components.

Every collector is fail-safe: if a component is unavailable (no Kronos model,
no ML artifacts, no cached data) it simply contributes no signal.  A consensus
never blocks on a missing brain; it just reflects the brains that are present.
"""

import os

from .signals import Signal

_QUANT_ENV_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_DEFAULT_PROJECT_ROOT = os.path.dirname(_QUANT_ENV_ROOT)


# ── Kronos ─────────────────────────────────────────────────────────────
def collect_kronos(ctx, project_root=_DEFAULT_PROJECT_ROOT, symbol="GC=F"):
    """Collect the Kronos forecast signal.

    Tries to build a KronosRegimeAdapter and force a refresh on cached data.
    Without torch / the HF model this returns no signal (Kronos stays a
    silent partner instead of a blocker).
    """
    try:
        from ml.kronos import KronosRegimeAdapter
        from intelligence.data import load_cached_history
    except Exception:
        return None

    df = load_cached_history(project_root, symbol, max_bars=None)
    if df is None or len(df) < 120:
        return None
    try:
        adapter = KronosRegimeAdapter(ctx or {}, None)
        adapter.update(df)
        features = getattr(adapter, "forecast_features", None) or {}
        return Signal.from_kronos(features, symbol=symbol)
    except Exception:
        try:
            # Direct predictor path (no adapter wiring needed).
            from ml.kronos import KronosPricePredictor
            predictor = KronosPricePredictor()   # auto device, default model
            if not predictor.is_available():
                return None
            features = predictor.get_forecast_features(df.tail(512))
            return Signal.from_kronos(features, symbol=symbol)
        except Exception:
            return None


# ── RF regime model ────────────────────────────────────────────────────
def collect_rf_regime(ctx, project_root=_DEFAULT_PROJECT_ROOT, symbol="GC=F"):
    """Classify the most recent cached bars with the RF regime model.

    Loads the committed ``ml/model.pkl`` directly (the adapter only loads it
    when ``ML_ENABLED`` is set, which would silently kill this signal) and
    classifies the cached history with ``predict_with_confidence``.
    """
    try:
        from intelligence.data import load_cached_history
        from ml.regime_model import RegimeClassifier
        from ml.data_builder import build_features
    except Exception:
        return None

    model_path = os.path.join(_QUANT_ENV_ROOT, "ml", "model.pkl")
    if not os.path.exists(model_path):
        return None
    try:
        model = RegimeClassifier.load(model_path)
    except Exception:
        return None

    df = load_cached_history(project_root, symbol, max_bars=2000)
    if df is None or len(df) < 120:
        return None
    try:
        X, _ = build_features(df, lookback=model.lookback,
                              regime_threshold=model.regime_threshold)
        if X is None or X.empty:
            return None
        result = model.predict_with_confidence(X.iloc[-1:])
        return Signal.from_rf_regime(
            result.get("regime_name") or "ranging",
            result.get("confidence", 0.5),
            symbol=symbol)
    except Exception:
        return None


# ── Backtest / walk-forward probes from the ledger ─────────────────────
def collect_backtest(ledger, symbol="GC=F"):
    """One signal per (strategy, symbol) that produced tradable evidence."""
    if ledger is None:
        return []
    signals = []
    seen = set()
    for probe in ledger.probes:
        key = probe.strategy_key
        sym = probe.symbol or symbol
        dedup = (key, sym)
        if dedup in seen or not probe.has_trades:
            continue
        seen.add(dedup)
        # Prefer the out-of-sample probe when present; else the best IS probe.
        best = ledger.best_oos_probe(key, symbol=sym) or \
            ledger.best_probe(key, symbol=sym)
        if best is None:
            continue
        s = Signal.from_backtest(key, best.metrics, symbol=sym)
        if s:
            signals.append(s)
    return signals


# ── Deterministic trend filter ─────────────────────────────────────────
def collect_trend_filter(ctx, project_root=_DEFAULT_PROJECT_ROOT, symbol="GC=F"):
    """Cheap regime estimate from recent price path (no model required)."""
    try:
        from intelligence.data import load_cached_history
    except Exception:
        return None
    df = load_cached_history(project_root, symbol, max_bars=2000)
    if df is None or len(df) < 60:
        return None
    try:
        close = df["close"]
        short = float(close.iloc[-1] / close.iloc[-20] - 1)
        long = float(close.iloc[-1] / close.iloc[-60] - 1)
        vol = float(close.pct_change().tail(20).std())
        if short > 0.02 and long > 0.02:
            trend, strength = "bull", min(1.0, abs(short) * 5.0)
        elif short < -0.02 and long < -0.02:
            trend, strength = "bear", min(1.0, abs(short) * 5.0)
        elif vol < 0.01:
            trend, strength = "ranging", 0.5
        else:
            trend, strength = "mixed", 0.3
        return Signal.from_trend_filter(trend, strength, symbol=symbol)
    except Exception:
        return None


# ── Master collector ───────────────────────────────────────────────────
def collect_all_signals(ctx=None, ledger=None, project_root=_DEFAULT_PROJECT_ROOT,
                        symbol="GC=F"):
    """Collect every available signal, never raising."""
    ctx = ctx or {}
    project_root = project_root or _DEFAULT_PROJECT_ROOT
    signals = []
    for collector in (collect_kronos, collect_rf_regime, collect_trend_filter):
        try:
            s = collector(ctx, project_root=project_root, symbol=symbol)
            if s:
                signals.append(s)
        except Exception:
            pass
    try:
        signals.extend(collect_backtest(ledger, symbol=symbol))
    except Exception:
        pass
    return signals
