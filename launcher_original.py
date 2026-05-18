import argparse, sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), 'quant_env'))

def run_live():
    from main import App
    App().run()

def run_backtest():
    from backtest.data_loader import load_yfinance
    from backtest.engine import BacktestEngine
    from strategies.grid_strategy import GridStrategy
    from analysis.performance import compute_metrics
    from analysis.session_analyzer import session_performance
    from analysis.report_generator import generate_report

    data = load_yfinance("GC=F", period="5d", interval="1m")
    engine = BacktestEngine(data, GridStrategy, 10000, spacing=0.1, levels=5, lot=0.01)
    result = engine.run()
    metrics = compute_metrics(result.fills_df, result.equity_df)
    session = session_performance(result.fills_df, result.equity_df)
    report_file = "backtest_report.html"
    generate_report(result.equity_df, result.fills_df, metrics, session, output_file=report_file)
    print(f"Backtest report saved: {report_file}")

def run_optimize():
    from backtest.data_loader import load_yfinance
    from backtest.optimizer import optimize as grid_optimize
    from strategies.grid_strategy import GridStrategy

    data = load_yfinance("GC=F", period="5d", interval="1m")
    param_grid = {'spacing': [0.05, 0.1, 0.2], 'levels': [3, 5, 7]}
    results = grid_optimize(data, GridStrategy, param_grid, 10000)
    print(results.head())

def run_report():
    from analysis.trade_logger import TradeLogger
    from analysis.performance import compute_metrics
    from analysis.session_analyzer import session_performance
    from analysis.report_generator import generate_report
    import pandas as pd

    logger = TradeLogger("quant_env/trades.db")
    fills_rows = logger.get_fills()
    if not fills_rows:
        print("No trades yet.")
        return
    fills_df = pd.DataFrame(fills_rows, columns=['id','timestamp','symbol','side','price','volume','pnl'])
    equity_rows = logger.get_equity_curve()
    equity_df = pd.DataFrame(equity_rows, columns=['timestamp','equity'])
    metrics = compute_metrics(fills_df, equity_df)
    session = session_performance(fills_df, equity_df)
    generate_report(equity_df, fills_df, metrics, session, output_file="live_report.html")
    logger.close()
    print("Live report saved.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Quant Grid Bot Launcher")
    parser.add_argument('mode', choices=['live', 'backtest', 'optimize', 'report'])
    args = parser.parse_args()
    if args.mode == 'live':
        run_live()
    elif args.mode == 'backtest':
        run_backtest()
    elif args.mode == 'optimize':
        run_optimize()
    elif args.mode == 'report':
        run_report()