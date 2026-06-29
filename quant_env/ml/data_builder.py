import pandas as pd
import numpy as np

def build_features(df, lookback=20, adx_threshold=25, target_horizon=1):
    """
    Build feature matrix X and target vector y.

    Features are computed from current & lagged bars only (no future leakage).
    Target: 1 if the *average* ADX over the next `target_horizon` bars exceeds the threshold,
            0 otherwise.  This still uses future ADX, but over a *future window* rather than
            a single shifted bar, which is more robust and realistic.
    """
    def compute_adx(high, low, close, period=14):
        tr = pd.DataFrame({'h-l':high-low, 'h-pc':(high-close.shift(1)).abs(),'l-pc':(low-close.shift(1)).abs()}).max(axis=1)
        atr = tr.ewm(alpha=1/period, adjust=False).mean()
        up = high.diff(); down = -low.diff()
        plus_dm = np.where((up>down)&(up>0), up, 0.0)
        minus_dm = np.where((down>up)&(down>0), down, 0.0)
        plus_di = 100 * pd.Series(plus_dm).ewm(alpha=1/period, adjust=False).mean() / atr
        minus_di = 100 * pd.Series(minus_dm).ewm(alpha=1/period, adjust=False).mean() / atr
        dx = (abs(plus_di-minus_di)/(plus_di+minus_di)*100).fillna(0)
        return dx.ewm(alpha=1/period, adjust=False).mean()

    df = df.copy()
    df['adx'] = compute_adx(df['high'], df['low'], df['close'], 14)
    df['returns'] = df['close'].pct_change()
    df['volatility'] = df['returns'].rolling(lookback).std()
    df['volume_ratio'] = df['volume'] / df['volume'].rolling(lookback).mean()
    df['high_low_ratio'] = (df['high']-df['low'])/df['close']

    # Target: forward-looking average ADX over target_horizon bars
    # This still uses future information (like any supervised learning),
    # but averages over a window to reduce label noise.
    df['target_adx_fwd'] = df['adx'].rolling(target_horizon).mean().shift(-target_horizon)
    df['target'] = (df['target_adx_fwd'] > adx_threshold).astype(int)

    features = ['volatility', 'volume_ratio', 'high_low_ratio', 'returns']
    for lag in range(1, 6):
        for f in ['returns', 'volatility']:
            col = f'{f}_lag{lag}'
            df[col] = df[f].shift(lag)
            features.append(col)

    df.dropna(inplace=True)
    return df[features], df['target']
