import pandas as pd
from .trade_matcher import match_trades

SESSIONS = {
    'Sydney': (22,7), 'Tokyo': (0,9), 'London': (7,16), 'New York': (12,21)
}

def classify_session(dt_utc):
    hour = dt_utc.hour
    active = []
    for name, (start,end) in SESSIONS.items():
        if start <= hour < end:
            active.append(name)
        elif start > end and (hour >= start or hour < end):
            active.append(name)
    return active if active else ['Off-hours']

def session_performance(fills_df, equity_df):
    trades = match_trades(fills_df)
    if trades.empty:
        return pd.DataFrame()
    trades['exit_time'] = pd.to_datetime(trades['exit_time'])
    trades['session'] = trades['exit_time'].apply(classify_session)
    exploded = trades.explode('session')
    return exploded.groupby('session').agg(
        num_trades=('pnl','count'),
        total_pnl=('pnl','sum'),
        avg_pnl=('pnl','mean'),
        total_volume=('volume','sum')
    ).reset_index()
