import pandas as pd
import numpy as np

def build_features(df, lookback=20, adx_threshold=25):
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
    df['adx'] = compute_adx(df['high'], df['low'], df['close'], 14)
    df['returns'] = df['close'].pct_change()
    df['volatility'] = df['returns'].rolling(lookback).std()
    df['volume_ratio'] = df['volume'] / df['volume'].rolling(lookback).mean()
    df['high_low_ratio'] = (df['high']-df['low'])/df['close']
    df['target'] = (df['adx'].shift(-1) > adx_threshold).astype(int)
    features = ['volatility','volume_ratio','high_low_ratio','returns']
    for lag in range(1,6):
        for f in ['returns','volatility']:
            df[f'{f}_lag{lag}'] = df[f].shift(lag)
            features.append(f'{f}_lag{lag}')
    df.dropna(inplace=True)
    return df[features], df['target']
