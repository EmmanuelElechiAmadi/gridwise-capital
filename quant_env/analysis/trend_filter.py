import pandas as pd
import numpy as np

def compute_adx(high, low, close, period=14):
    tr = pd.DataFrame({
        'h-l': high - low,
        'h-pc': np.abs(high - close.shift(1)),
        'l-pc': np.abs(low - close.shift(1))
    }).max(axis=1)
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    up = high.diff().clip(lower=0)
    down = -low.diff().clip(upper=0)
    plus_dm = up.where(up > down, 0.0).ewm(alpha=1/period, adjust=False).mean()
    minus_dm = down.where(down > up, 0.0).ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * plus_dm / atr
    minus_di = 100 * minus_dm / atr
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    return adx

def is_trending(data_frame, adx_threshold=25):
    """Return True if the last bar's ADX is above threshold."""
    if len(data_frame) < 30:
        return False
    recent = data_frame.iloc[-30:]
    adx = compute_adx(recent['high'], recent['low'], recent['close'])
    return adx.iloc[-1] > adx_threshold