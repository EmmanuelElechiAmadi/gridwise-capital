import pandas as pd
import numpy as np


def compute_adx(high, low, close, period=14):
    """Return ADX series (uses only past data)."""
    tr = pd.DataFrame({
        'h-l': high - low,
        'h-pc': (high - close.shift(1)).abs(),
        'l-pc': (low - close.shift(1)).abs(),
    }).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    plus_di = 100 * pd.Series(plus_dm).ewm(alpha=1 / period, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm).ewm(alpha=1 / period, adjust=False).mean() / atr
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di) * 100).fillna(0)
    return dx.ewm(alpha=1 / period, adjust=False).mean()


def label_regime(adx_series, lookahead=20, adx_threshold=25):
    """
    Assign a regime label for each bar based on *future* ADX over the next `lookahead` bars.

    Trending (1):  Average ADX over the next `lookahead` bars >= threshold
    Ranging  (0):  Average ADX over the next `lookahead` bars < threshold

    This label *uses future information* (it defines what we want to
    forecast), but the features given to the model at prediction time
    use only current/past data — no leakage.
    """
    adx_fwd = adx_series.rolling(lookahead).mean().shift(-lookahead)
    return (adx_fwd >= adx_threshold).astype(int)


def build_features(df, lookback=20, adx_threshold=25, target_lookahead=20):
    """
    Build feature matrix X and target vector y.

    Features are computed from *current and past* bars only (no future leakage).
    The target is the regime (trending=1 / ranging=0) over the *next*
    `target_lookahead` bars — a genuine forecasting task.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV data with columns: open, high, low, close, volume.
    lookback : int
        Rolling window for volatility and volume ratio features.
    adx_threshold : int
        ADX threshold for trending vs ranging classification.
    target_lookahead : int
        Number of forward bars used to define the regime label.
        Larger values make the task harder but more meaningful.

    Returns
    -------
    X : pd.DataFrame
        Feature matrix (current/past data only).
    y : pd.Series
        Target labels (1=trending, 0=ranging) for the next `target_lookahead` bars.
    """
    df = df.copy()

    # ── ADX (current bar only — uses only past/current data) ───────
    df['adx'] = compute_adx(df['high'], df['low'], df['close'], 14)

    # ── Features (all use only current + lagged data) ──────────────
    df['returns'] = df['close'].pct_change()
    df['volatility'] = df['returns'].rolling(lookback).std()
    df['volume_ratio'] = df['volume'] / df['volume'].rolling(lookback).mean()
    df['high_low_ratio'] = (df['high'] - df['low']) / df['close']
    df['adx_current'] = df['adx']  # current ADX value (useful feature)

    features = [
        'volatility', 'volume_ratio', 'high_low_ratio',
        'returns', 'adx_current',
    ]
    for lag in range(1, 6):
        for f in ['returns', 'volatility']:
            col = f'{f}_lag{lag}'
            df[col] = df[f].shift(lag)
            features.append(col)

    # ── Target (uses future ADX — this is what we're forecasting) ──
    df['target'] = label_regime(
        df['adx'], lookahead=target_lookahead, adx_threshold=adx_threshold
    )

    df.dropna(inplace=True)
    return df[features], df['target']
