"""
Feature builder and regime labeler for the ML system.

Labels are direction-aware 3-class regimes (BULL / RANGING / BEAR)
based on forward volatility-adjusted returns.

Features use only current/past data (no future leakage).
"""

import pandas as pd
import numpy as np

# Use the canonical ADX implementation from analysis/trend_filter
from analysis.trend_filter import compute_adx


def label_directional_regime(close_series, atr_series, lookahead=20, threshold=1.0):
    """
    Assign a directional regime label for each bar based on *future*
    volatility-adjusted return over the next `lookahead` bars.

    Returns
    -------
    pd.Series[int]
        1  = BULL  (forward return > +threshold * ATR)
        0  = RANGING (forward return within ±threshold * ATR)
       -1  = BEAR  (forward return < -threshold * ATR)

    This label *uses future information* (it defines what we want to
    forecast), but the features given to the model at prediction time
    use only current/past data — no leakage.
    """
    # Forward return over lookahead bars
    fwd_return = close_series.shift(-lookahead) - close_series
    # Average ATR over the lookahead window for normalization
    fwd_atr = atr_series.rolling(lookahead).mean().shift(-lookahead)

    # Avoid division by zero
    norm_return = fwd_return / fwd_atr.replace(0, np.nan)
    norm_return = norm_return.fillna(0)

    labels = pd.Series(0, index=close_series.index)
    labels[norm_return > threshold] = 1       # BULL
    labels[norm_return < -threshold] = -1     # BEAR
    return labels.astype(int)


def compute_atr(high, low, close, period=14):
    """Average True Range using Wilder's smoothing."""
    tr = pd.DataFrame({
        'h-l': high - low,
        'h-pc': np.abs(high - close.shift(1)),
        'l-pc': np.abs(low - close.shift(1))
    }).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    return atr


def build_features(df, lookback=20, adx_threshold=25, target_lookahead=20,
                   regime_threshold=1.0):
    """
    Build feature matrix X and target vector y.

    Features are computed from *current and past* bars only (no future leakage).
    The target is the directional regime (BULL=1 / RANGING=0 / BEAR=-1) over the
    *next* `target_lookahead` bars.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV data with columns: open, high, low, close, volume.
    lookback : int
        Rolling window for volatility and volume ratio features.
    adx_threshold : int
        ADX threshold (kept for backward compatibility, not used in target).
    target_lookahead : int
        Number of forward bars used to define the regime label.
    regime_threshold : float
        Number of ATR units to define trending vs ranging.

    Returns
    -------
    X : pd.DataFrame
        Feature matrix (current/past data only).
    y : pd.Series
        Target labels (1=BULL, 0=RANGING, -1=BEAR).
    """
    df = df.copy()

    # ── Core technical indicators (current bar only) ────────────────
    df['adx'] = compute_adx(df['high'], df['low'], df['close'], 14)
    df['atr'] = compute_atr(df['high'], df['low'], df['close'], 14)
    df['returns'] = df['close'].pct_change()

    # ── 1. Volatility features ──────────────────────────────────────
    df['volatility'] = df['returns'].rolling(lookback).std()
    df['atr_ratio'] = df['atr'] / df['atr'].rolling(lookback * 2).mean()

    # ── 2. Momentum features ────────────────────────────────────────
    df['rsi'] = _rsi(df['close'], 14)
    macd_line, macd_signal = _macd(df['close'])
    df['macd'] = macd_line
    df['macd_signal'] = macd_signal
    df['macd_hist'] = macd_line - macd_signal

    # ── 3. Trend features ───────────────────────────────────────────
    for ma_period in [20, 50, 200]:
        col = f'sma_{ma_period}'
        df[col] = df['close'].rolling(ma_period).mean()
        df[f'price_to_sma_{ma_period}'] = df['close'] / df[col] - 1.0
        df[f'sma_{ma_period}_slope'] = df[col].pct_change(5)

    # ── 4. Bollinger Bands ──────────────────────────────────────────
    bb_mid = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    df['bb_pct_b'] = (df['close'] - bb_mid) / (2 * bb_std)
    df['bb_width'] = (2 * bb_std) / bb_mid

    # ── 5. Volume features ──────────────────────────────────────────
    df['volume_ratio'] = df['volume'] / df['volume'].rolling(lookback).mean()
    df['high_low_ratio'] = (df['high'] - df['low']) / df['close']

    # ── 6. Current ADX (still useful) ───────────────────────────────
    df['adx_current'] = df['adx']

    # ── 7. Lagged returns and volatility ────────────────────────────
    for lag in range(1, 6):
        df[f'returns_lag{lag}'] = df['returns'].shift(lag)
        df[f'volatility_lag{lag}'] = df['volatility'].shift(lag)
        df[f'rsi_lag{lag}'] = df['rsi'].shift(lag)
        df[f'macd_hist_lag{lag}'] = df['macd_hist'].shift(lag)

    # ── Feature columns ─────────────────────────────────────────────
    features = [
        # Volatility
        'volatility', 'atr_ratio', 'bb_width',
        # Momentum
        'rsi', 'macd', 'macd_signal', 'macd_hist',
        # Trend
        'price_to_sma_20', 'price_to_sma_50', 'price_to_sma_200',
        'sma_20_slope', 'sma_50_slope',
        # Bollinger
        'bb_pct_b',
        # Volume / range
        'volume_ratio', 'high_low_ratio',
        # ADX
        'adx_current',
        # Returns
        'returns',
    ]
    for lag in range(1, 6):
        features.extend([
            f'returns_lag{lag}',
            f'volatility_lag{lag}',
            f'rsi_lag{lag}',
            f'macd_hist_lag{lag}',
        ])

    # ── Target (uses future data) ───────────────────────────────────
    df['target'] = label_directional_regime(
        df['close'], df['atr'],
        lookahead=target_lookahead, threshold=regime_threshold,
    )

    df.dropna(inplace=True)
    return df[features], df['target']


def _rsi(close, period=14):
    """Relative Strength Index."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(close, fast=12, slow=26, signal=9):
    """MACD line, signal line."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    macd_signal = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, macd_signal