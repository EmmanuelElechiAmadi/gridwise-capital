import argparse
import sys
import os
import shutil

# Make sure we can import from the quant_env folder
sys.path.append(os.path.join(os.path.dirname(__file__), 'quant_env'))

from config import Config
from utils.emailer import Emailer

def get_emailer():
    """Return an Emailer instance if email is enabled and configured."""
    if Config.EMAIL_ENABLED:
        try:
            return Emailer(
                Config.EMAIL_SMTP_SERVER,
                Config.EMAIL_PORT,
                Config.EMAIL_USERNAME,
                Config.EMAIL_PASSWORD,
            )
        except Exception as e:
            print(f"Email not available: {e}")
    return None


def run_live():
    from main import App
    from adaptive.updater import AdaptiveUpdater

    app = App()
    # Start adaptive updater if enabled
    if app.config.ADAPTIVE_ENABLED:
        updater = AdaptiveUpdater(app.config, app.strategy, app.log)
        updater.start()
    app.run()


def run_backtest():
    from backtest.data_loader import load_yfinance
    from backtest.engine import BacktestEngine
    from strategies.grid_strategy import GridStrategy
    from analysis.performance import compute_metrics
    from analysis.session_analyzer import session_performance
    from analysis.report_generator import generate_report

    data = load_yfinance("GC=F", period="5d", interval="1m")
    engine = BacktestEngine(data, GridStrategy, 10000, spacing=0.1, levels=5, lot=1.0)
    result = engine.run()
    metrics = compute_metrics(result.fills_df, result.equity_df)
    session = session_performance(result.fills_df, result.equity_df)
    report_file = "backtest_report.html"
    generate_report(result.equity_df, result.fills_df, metrics, session, output_file=report_file)
    print(f"Backtest report saved: {report_file}")

    # ---- Email ----
    emailer = get_emailer()
    if emailer:
        emailer.send(
            to=Config.EMAIL_TO,
            subject="Quant Grid Bot – Backtest Report",
            body="<h3>Backtest completed. Report attached.</h3>",
            attachments=[report_file],
        )
def run_optimize():
    from backtest.data_loader import load_yfinance
    from backtest.engine import BacktestEngine
    from analysis.performance import compute_metrics
    from strategies.grid_strategy import GridStrategy
    import pandas as pd

    data = load_yfinance("GC=F", period="5d", interval="1m")
    spacings = [0.05, 0.1, 0.2]
    levels = [3, 5, 7]
    results = []

    for sp in spacings:
        for lv in levels:
            engine = BacktestEngine(data.copy(), GridStrategy, 10000,
                                    spacing=sp, levels=lv, lot=1.0)
            res = engine.run()
            metrics = compute_metrics(res.fills_df, res.equity_df)
            metrics['spacing'] = sp
            metrics['levels'] = lv
            results.append(metrics)

    df = pd.DataFrame(results).sort_values('sharpe_ratio', ascending=False)
    print(df)
    csv_file = "optimization_results.csv"
    df.to_csv(csv_file, index=False)

    # ---- Email ----
    emailer = get_emailer()
    if emailer:
        emailer.send(
            to=Config.EMAIL_TO,
            subject="Quant Grid Bot – Optimization Results",
            body="<h3>Optimization run completed. Results attached.</h3>",
            attachments=[csv_file],
        )
def run_report():
    from analysis.trade_logger import TradeLogger
    from analysis.performance import compute_metrics
    from analysis.session_analyzer import session_performance
    from analysis.report_generator import generate_report
    import pandas as pd

    db_path = "quant_env/trades.db"
    logger = TradeLogger(db_path)
    fills_rows = logger.get_fills()
    if not fills_rows:
        print("No trades yet – live report empty.")
        logger.close()
        return

    fills_df = pd.DataFrame(fills_rows, columns=['id','timestamp','symbol','side','price','volume','pnl'])
    equity_rows = logger.get_equity_curve()
    equity_df = pd.DataFrame(equity_rows, columns=['timestamp','equity'])
    metrics = compute_metrics(fills_df, equity_df)
    session = session_performance(fills_df, equity_df)
    report_file = "live_report.html"
    generate_report(equity_df, fills_df, metrics, session, output_file=report_file)
    logger.close()
    print(f"Live report saved: {report_file}")

    emailer = get_emailer()
    if emailer:
        # Also attach a backup of the trade database
        backup_db = "trades_backup.db"
        shutil.copy(db_path, backup_db)
        emailer.send(
            to=Config.EMAIL_TO,
            subject="Quant Grid Bot – Live Performance Report",
            body="<h3>Live performance report attached.</h3>",
            attachments=[report_file, backup_db],
        )

def run_walkforward():
    from backtest.data_loader import load_yfinance
    from strategies.grid_strategy import GridStrategy
    from analysis.walkforward import walkforward_analysis

    data = load_yfinance("GC=F", period="1mo", interval="1h")
    param_grid = {'spacing': [0.1, 0.2], 'levels': [3, 5]}
    wf_df = walkforward_analysis(data, GridStrategy, param_grid,
                                 window_size=500, step_size=500,
                                 initial_capital=10000, lot=1.0)
    print(wf_df)
    wf_df.to_csv('walkforward_results.csv', index=False)
    
    
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Quant Grid Bot Launcher (with Email)")
    parser.add_argument('mode', choices=['live', 'backtest', 'optimize', 'report', 'walkforward'], help="Mode to run: live trading, backtest, optimization, report generation, or walk-forward analysis")
    args = parser.parse_args()

    if args.mode == 'live':
        run_live()
    elif args.mode == 'backtest':
        run_backtest()
    elif args.mode == 'optimize':
        run_optimize()
    elif args.mode == 'report':
        run_report()
    elif args.mode == 'walkforward':
        run_walkforward()    