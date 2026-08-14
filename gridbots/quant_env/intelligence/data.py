"""
Multi-symbol cached-history helpers for the agent team.

Convention for cached OHLCV CSVs (matching the existing ``gold_data.csv``):

    GC=F / XAUUSD.r / XAUUSD=F  ->  gold_data.csv   (legacy name)
    any other symbol            ->  <symbol>.csv    e.g. SIF.csv, CLF.csv

The Prober probes every symbol that has a cached CSV, so the research corpus
covers a real multi-asset portfolio (gold, silver, crude) instead of gold only.
"""

import os

DEFAULT_SYMBOLS = ["GC=F", "SI=F", "CL=F"]
_GOLD_SYMBOLS = ("GC=F", "XAUUSD.r", "XAUUSD=F")


def sanitize(symbol):
    """Filesystem-safe token for a symbol: GC=F -> GCF, CL=F -> CLF."""
    return str(symbol).replace("=", "").replace("/", "_")


def symbol_csv_path(project_root, symbol):
    if symbol in _GOLD_SYMBOLS:
        return os.path.join(project_root, "gold_data.csv")
    return os.path.join(project_root, f"{sanitize(symbol)}.csv")


def load_cached_history(project_root, symbol, max_bars=None):
    """
    Load an OHLCV DataFrame for a symbol from its cached CSV.

    Returns a lower-case-column DataFrame with a DatetimeIndex, or None when
    the CSV is missing/unreadable/empty.  ``max_bars`` optionally trims to the
    most recent rows.
    """
    path = symbol_csv_path(project_root, symbol)
    if not os.path.exists(path):
        return None
    try:
        import pandas as pd
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        rename = {"Open": "open", "High": "high", "Low": "low",
                  "Close": "close", "Volume": "volume"}
        df.rename(columns=rename, inplace=True)
        df.index = pd.to_datetime(df.index, errors="coerce")
        df = df.sort_index()
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close"])
        if df.empty:
            return None
        return df.tail(max_bars).copy() if max_bars else df
    except Exception:
        return None


def scan_cached_symbols(project_root):
    """Return ``{symbol: coverage_bars}`` for every cached OHLCV CSV present."""
    found = {}
    for sym in DEFAULT_SYMBOLS:
        path = symbol_csv_path(project_root, sym)
        if os.path.exists(path):
            try:
                with open(path) as f:
                    found[sym] = max(0, sum(1 for _ in f) - 1)  # minus header
            except Exception:
                continue
    return found


def ensure_fresh_corpus(project_root, symbols=None, max_age_hours=8.0,
                        period="3mo", interval="1h", force=False):
    """Keep the cached OHLCV corpus fresh enough for live signals.

    The RF regime model, the trend filter, the Kronos adapter and the
    breakout strategy all read the cached CSVs (``gold_data.csv`` etc.).
    If the newest cached bar is older than ``max_age_hours`` (or ``force``),
    re-download the corpus from Yahoo Finance.  Fail-safe: never raises,
    returns ``{"refreshed": [...], "skipped": [...], "error": ...}``.
    """
    import time

    import pandas as pd

    symbols = symbols or list(DEFAULT_SYMBOLS)
    result = {"refreshed": [], "skipped": [], "error": None}
    try:
        import yfinance as yf
    except Exception as e:
        result["error"] = f"yfinance unavailable: {e}"
        return result

    for sym in symbols:
        path = symbol_csv_path(project_root, sym)
        if os.path.exists(path):
            try:
                age_h = (time.time() - os.path.getmtime(path)) / 3600.0
            except Exception:
                age_h = 0.0
            if not force and age_h <= max_age_hours:
                result["skipped"].append(f"{sym} (fresh, {age_h:.1f}h old)")
                continue
        try:
            df = yf.download(sym, period=period, interval=interval,
                             progress=False, auto_adjust=False)
            if df is None or df.empty:
                result["skipped"].append(f"{sym} (yfinance returned no data)")
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.rename(columns={"Open": "open", "High": "high",
                                    "Low": "low", "Close": "close",
                                    "Volume": "volume"})
            df = df[["open", "high", "low", "close", "volume"]].dropna()
            if df.empty:
                result["skipped"].append(f"{sym} (no OHLCV rows)")
                continue
            os.makedirs(os.path.dirname(path), exist_ok=True)
            df.to_csv(path)
            result["refreshed"].append(
                f"{sym} -> {len(df)} bars, last {df.index[-1]}")
        except Exception as e:
            result["skipped"].append(f"{sym} (error: {e})")
    return result
