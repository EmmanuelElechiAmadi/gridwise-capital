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


# ── News Desk (Phase 5) ────────────────────────────────────────────────
def collect_news(report, symbol="GC=F"):
    """Build a Signal from the News Research Analyst's report.

    The report carries the curated article corpus; the coordinator attaches a
    ``news_verdict`` (Claude Sonnet, already fact-checked).  No verdict -> no
    signal (fail-safe: news never forces a vote).
    """
    if not report:
        return None
    verdict = report.get("news_verdict")
    if not verdict:
        return None
    try:
        return Signal.from_news(verdict, symbol=symbol)
    except Exception:
        return None


# The model brains that VERIFY the news read: price-derived, independent of
# the text corpus.  A news conclusion that agrees with them is confirmed; one
# that disagrees is a watch-out (mean-reversion setup OR regime break).
_MODEL_SOURCES = ("kronos", "rf_regime")


def compute_news_confirmation(news_signal, signals):
    """Sign-agreement between the News Desk vote and the model brains.

    The model read is the strength*confidence-weighted blend of the Kronos and
    RF-regime votes (thresholded at ±0.1).  Returns a dict with ``agrees`` /
    ``news_direction`` / ``model_direction``, or an ``available=False`` block
    when the news vote or the model brains are absent.
    """
    if news_signal is None:
        return {"available": False, "agrees": None, "news_direction": None,
                "model_direction": None, "model_value": None,
                "model_sources": [], "semantics": "no news verdict this cycle"}
    models = [s for s in signals if s is not None and s.source in _MODEL_SOURCES]
    if not models:
        return {"available": False, "agrees": None,
                "news_direction": news_signal.direction,
                "model_direction": None, "model_value": None,
                "model_sources": [],
                "semantics": "no Kronos/RF model read available to verify the news"}
    dir_v = {"BULL": 1.0, "BEAR": -1.0, "RANGING": 0.0}
    acc = 0.0
    w_total = 0.0
    for s in models:
        w = s.strength * s.confidence
        acc += dir_v.get(s.direction, 0.0) * w
        w_total += w
    model_value = acc / w_total if w_total > 0 else 0.0
    model_dir = ("BULL" if model_value > 0.1
                 else "BEAR" if model_value < -0.1 else "RANGING")
    news_dir = news_signal.direction
    agrees = bool(news_dir == model_dir)
    return {
        "available": True,
        "agrees": agrees,
        "news_direction": news_dir,
        "model_direction": model_dir,
        "model_value": round(model_value, 4),
        "model_sources": [s.source for s in models],
        "semantics": (
            "news vote CONFIRMED by the Kronos + RF model blend"
            if agrees else
            "news vote DIVERGES from the model brains — treat as a watch-out "
            "(mean-reversion setup or a regime break the models have not seen)"),
    }


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
