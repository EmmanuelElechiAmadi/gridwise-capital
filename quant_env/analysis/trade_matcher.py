from collections import deque
import pandas as pd

def match_trades(fills_df):
    buys = fills_df[fills_df['side'] == 'buy'].copy()
    sells = fills_df[fills_df['side'] == 'sell'].copy()
    buys = buys.sort_values('timestamp').reset_index(drop=True)
    sells = sells.sort_values('timestamp').reset_index(drop=True)
    buy_queue = deque()
    trades = []
    for _, buy in buys.iterrows():
        buy_queue.append(buy)
    for _, sell in sells.iterrows():
        remaining_vol = sell.volume
        while remaining_vol > 0 and buy_queue:
            oldest = buy_queue[0]
            if oldest.volume <= remaining_vol:
                pnl = (sell.price - oldest.price) * oldest.volume
                trades.append({'entry_time': oldest.timestamp, 'exit_time': sell.timestamp,
                               'entry_price': oldest.price, 'exit_price': sell.price,
                               'volume': oldest.volume, 'pnl': pnl})
                remaining_vol -= oldest.volume
                buy_queue.popleft()
            else:
                pnl = (sell.price - oldest.price) * remaining_vol
                trades.append({'entry_time': oldest.timestamp, 'exit_time': sell.timestamp,
                               'entry_price': oldest.price, 'exit_price': sell.price,
                               'volume': remaining_vol, 'pnl': pnl})
                oldest.volume -= remaining_vol
                remaining_vol = 0
    return pd.DataFrame(trades)
