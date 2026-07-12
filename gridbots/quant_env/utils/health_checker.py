"""
Health checker – monitors live trading, sends alerts, and includes retry logic
for transient failures.
"""

import time
import logging
import pandas as pd

log = logging.getLogger("QuantBot")


def retry(max_attempts=3, delay=1.0, exceptions=(Exception,)):
    """Decorator: retry a function up to max_attempts times on failure."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    log.warning(
                        f"{func.__name__} attempt {attempt}/{max_attempts} failed: {e}"
                    )
                    if attempt < max_attempts:
                        time.sleep(delay)
            raise last_exc
        return wrapper
    return decorator


@retry(max_attempts=3, delay=2.0)
def run_health_check(db_path="quant_env/trades.db",
                     expected_daily_return=0.01,
                     max_drawdown_pct=2.0,
                     telegram=None):
    """
    Evaluate recent trading performance and send alerts if thresholds are breached.

    Parameters
    ----------
    db_path : str
        Path to the SQLite trade database.
    expected_daily_return : float
        Expected daily return (decimal, e.g. 0.01 = 1 %).
    max_drawdown_pct : float
        Maximum tolerable intraday drawdown as % of starting equity.
    telegram : TelegramNotifier, optional
        Notifier to send alerts.
    """
    from quant_env.analysis.trade_logger import TradeLogger

    logger = TradeLogger(db_path)
    try:
        fills = logger.get_fills()
        if not fills:
            log.info("Health check: no fills in DB yet.")
            return

        fills_df = pd.DataFrame(
            fills, columns=['id', 'timestamp', 'symbol', 'side', 'price', 'volume', 'pnl']
        )

        equity_rows = logger.get_equity_curve()
        if not equity_rows:
            log.info("Health check: no equity data yet.")
            return

        equity_df = pd.DataFrame(equity_rows, columns=['timestamp', 'equity'])
        now = pd.Timestamp.now(tz='UTC')

        # Last 24 hours
        recent = equity_df[
            pd.to_datetime(equity_df['timestamp']).dt.tz_convert('UTC') > (
                now - pd.Timedelta(days=1))
        ]
        if recent.empty:
            log.info("Health check: no equity data in last 24 h.")
            return

        start_eq = recent['equity'].iloc[0]
        end_eq = recent['equity'].iloc[-1]
        daily_ret = (end_eq / start_eq) - 1

        peak = recent['equity'].cummax()
        dd = (peak - recent['equity']).max()
        dd_pct = dd / start_eq * 100 if start_eq > 0 else 0

        messages = []
        if daily_ret < expected_daily_return * 0.5:
            messages.append(
                f"Low daily return: {daily_ret:.2%} (expected {expected_daily_return:.2%})"
            )
        if dd_pct > max_drawdown_pct:
            messages.append(
                f"High drawdown: ${dd:.2f} ({dd_pct:.2f}%)"
            )

        log.info(
            f"Health check: daily ret={daily_ret:.2%} | "
            f"drawdown=${dd:.2f} ({dd_pct:.2f}%) | "
            f"fills={len(fills_df)}"
        )

        if messages:
            alert = " | ".join(messages)
            log.warning(alert)
            if telegram:
                telegram.send(f"⚠️ {alert}")

    finally:
        logger.close()