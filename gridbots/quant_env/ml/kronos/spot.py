"""Live XAU/USD spot + futures-basis re-anchoring for the live signal paths.

The bot trades ``XAUUSD.r`` (spot gold) but the Kronos adapter and the
breakout enhancer download ``GC=F`` FUTURES bars.  Futures carry a basis
premium/discount vs spot (e.g. +$56 on 2026-08-14), so any ABSOLUTE price
level derived from futures bars — forecast low/high, breakout entries,
VaR prices — is wrong for the traded instrument.

This module provides:

  * ``fetch_live_spot()`` — fail-safe live spot quote (gold-api.com, free,
    no key, ~6s timeout, 45s cache).  Returns a float or ``None``.
  * ``reanchor_to_spot(df)`` — shifts an OHLCV frame so its last close
    equals the live spot.  Direction / volatility / trend (relative
    measures) are invariant to the shift; only absolute levels change.
"""

import time

_spot_cache = {"ts": 0.0, "data": None}


def fetch_live_spot(max_age=45.0):
    """Live XAU/USD spot price from gold-api.com.  Float or ``None``.

    Fail-safe: returns ``None`` on any error so callers keep using their
    existing (futures) data rather than failing.
    """
    global _spot_cache
    now = time.time()
    if _spot_cache["data"] is not None and (now - _spot_cache["ts"]) < max_age:
        return _spot_cache["data"]
    price = None
    try:
        import requests
        r = requests.get("https://api.gold-api.com/price/XAU", timeout=6.0,
                         headers={"User-Agent": "insightforge-quant/1.0"})
        if r.status_code == 200:
            p = float(r.json().get("price") or 0.0)
            if p > 0:
                price = round(p, 2)
    except Exception:
        price = None
    _spot_cache = {"ts": now, "data": price}
    return price


_GOLD_SYMBOLS = ("GC=F", "XAUUSD", "XAUUSD.r", "XAUUSD=F", "XAU", "GOLD")


def is_gold_symbol(symbol):
    """True when the symbol refers to gold (the XAU spot shift is valid)."""
    s = str(symbol or "").upper().replace(" ", "")
    return any(s == g or s.startswith(g) for g in _GOLD_SYMBOLS)


def reanchor_to_spot(df, spot_price=None):
    """Shift an OHLCV frame so its last close equals the live XAU/USD spot.

    Returns the shifted copy — or the ORIGINAL frame when no spot is
    available / the frame is unusable (never breaks the caller).
    """
    if df is None or df.empty or "close" not in df.columns:
        return df
    if spot_price is None:
        spot_price = fetch_live_spot()
    if not spot_price:
        return df
    try:
        last_close = float(df["close"].iloc[-1])
        if last_close <= 0:
            return df
        basis = last_close - spot_price
        out = df.copy()
        for col in ("open", "high", "low", "close"):
            if col in out.columns:
                out[col] = out[col].astype(float) - basis
        return out
    except Exception:
        return df
