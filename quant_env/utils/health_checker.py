import pandas as pd
from quant_env.analysis.trade_logger import TradeLogger

def run_health_check(db_path="quant_env/trades.db", expected_daily_return=0.01, telegram=None):
    logger = TradeLogger(db_path)
    fills = logger.get_fills()
    if not fills: return
    fills_df = pd.DataFrame(fills, columns=['id','timestamp','symbol','side','price','volume','pnl'])
    equity_rows = logger.get_equity_curve()
    equity_df = pd.DataFrame(equity_rows, columns=['timestamp','equity'])
    now = pd.Timestamp.now(tz='UTC')
    recent = equity_df[pd.to_datetime(equity_df['timestamp']).dt.tz_convert('UTC') > (now - pd.Timedelta(days=1))]
    if recent.empty: return
    ret = (recent['equity'].iloc[-1] / recent['equity'].iloc[0]) - 1
    peak = recent['equity'].cummax()
    dd = (peak - recent['equity']).max()
    alert = None
    if ret < expected_daily_return*0.5: alert = f"Low daily return {ret:.2%}"
    if dd > recent['equity'].iloc[0]*0.02: alert = f"Intraday drawdown ${dd:.2f}"
    if alert and telegram: telegram.send(alert)
    logger.close()
