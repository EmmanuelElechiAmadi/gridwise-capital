from flask import Flask, render_template, jsonify, request, send_file
from flask_socketio import SocketIO, emit
import threading, time, sys, os, io, csv, math, textwrap, traceback
sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from quant_env.config import Config
from quant_env.core.connector import Connector
from quant_env.core.risk_manager import RiskManager
from quant_env.strategies.grid_strategy import GridStrategy
from quant_env.core.logger import setup_logger
from quant_env.analysis.trade_logger import TradeLogger
from quant_env.analysis.session_analyzer import session_performance
from quant_env.analysis.performance import compute_metrics
import pandas as pd

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)

config = Config
log = setup_logger()
connector = Connector(config)
risk = RiskManager(config, log)
logger = TradeLogger("quant_env/trades.db")
strategy = GridStrategy(connector, config, log)
strategy.logger = logger

# ── Regime Adapter ────────────────────────────────────────────────
regime_adapter = None
if getattr(config, 'ML_ENABLED', False):
    from quant_env.ml.regime_adapter import RegimeAdapter
    regime_adapter = RegimeAdapter(config)
    regime_adapter.start()
    log.info("Dashboard: RegimeAdapter started.")

# Global flag to pause/resume trading — start paused so user explicitly starts via UI
trading_active = False

# Hold recent log lines (for the dashboard)
log_lines = []

# ── Background task statuses ──────────────────────────────────────
task_status = {}
task_results = {}

class SocketLogHandler:
    """Redirects log messages to the WebSocket."""
    def __init__(self, socketio):
        self.socketio = socketio
    def write(self, msg):
        if msg.strip():
            log_lines.append(msg)
            if len(log_lines) > 100:
                log_lines.pop(0)
            self.socketio.emit('log', msg)
    def flush(self):
        pass

log_handler = SocketLogHandler(socketio)

def get_position_direction(net_position):
    """Return 'Long', 'Short', or 'Neutral' based on net position."""
    if net_position > 0.001:
        return "Long"
    elif net_position < -0.001:
        return "Short"
    return "Neutral"

def check_risk():
    """Check risk and emit alert if triggered."""
    acc = connector.account_info()
    pos = connector.get_positions()
    net = sum(p['volume'] if p['type']=='buy' else -p['volume'] for p in pos)
    if acc:
        action, val = risk.check(acc.equity, acc.balance, net)
        if action:
            msg = f"Risk trigger: {action} (value: {val})"
            log.warning(msg)
            socketio.emit('risk_alert', {'message': msg})
            connector.close_all_positions()
            strategy.reset_grid()
            return True
    return False

def trading_loop():
    strategy.on_start()
    while True:
        tick = connector.symbol_tick()
        acc = connector.account_info()
        pos = connector.get_positions()
        net = sum(p['volume'] if p['type']=='buy' else -p['volume'] for p in pos)

        regime_name = "unknown"
        regime_confidence = 0.0
        if regime_adapter:
            regime_name = regime_adapter.regime_name
            regime_confidence = round(regime_adapter.confidence * 100, 1)

        if trading_active:
            if tick:
                strategy.on_tick(tick)
            if acc:
                logger.log_equity(acc.equity, acc.balance, net, len(strategy.active_orders))
                pnl = acc.equity - acc.balance
                pnl_pct = (pnl / acc.balance) * 100 if acc.balance > 0 else 0

                # Compute drawdown
                equity_df = pd.DataFrame(logger.get_equity_curve(), columns=['timestamp', 'equity'])
                max_dd_pct = 0.0
                if not equity_df.empty:
                    equity_series = pd.to_numeric(equity_df['equity'])
                    peak = equity_series.cummax()
                    dd = (peak - equity_series) / peak * 100
                    max_dd_pct = round(dd.max(), 2)

                position_dir = get_position_direction(net)

                socketio.emit('update', {
                    'trading_active': trading_active,
                    'balance': round(acc.balance, 2),
                    'equity': round(acc.equity, 2),
                    'pnl': round(pnl, 2),
                    'pnl_pct': round(pnl_pct, 2),
                    'net_position': round(net, 4),
                    'position_direction': position_dir,
                    'num_orders': len(strategy.active_orders),
                    'regime': regime_name,
                    'regime_confidence': regime_confidence,
                    'max_drawdown': max_dd_pct,
                    'grid_spacing': strategy.spacing,
                    'grid_levels': strategy.levels,
                    'latest_price': round(tick['bid'], 2) if tick else 0,
                })
                check_risk()
            else:
                # No broker connection — emit status update anyway
                socketio.emit('update', {
                    'trading_active': trading_active,
                    'balance': 0,
                    'equity': 0,
                    'pnl': 0,
                    'pnl_pct': 0,
                    'net_position': 0,
                    'position_direction': 'Neutral',
                    'num_orders': len(strategy.active_orders),
                    'regime': regime_name,
                    'regime_confidence': regime_confidence,
                    'max_drawdown': 0,
                    'grid_spacing': strategy.spacing,
                    'grid_levels': strategy.levels,
                    'latest_price': 0,
                    'broker_connected': False,
                })
        else:
            # Paused — still emit status so the UI shows live data
            position_dir = get_position_direction(net)
            socketio.emit('update', {
                'trading_active': trading_active,
                'balance': round(acc.balance, 2) if acc else 0,
                'equity': round(acc.equity, 2) if acc else 0,
                'pnl': round((acc.equity - acc.balance), 2) if acc else 0,
                'pnl_pct': round(((acc.equity - acc.balance) / acc.balance) * 100, 2) if acc and acc.balance > 0 else 0,
                'net_position': round(net, 4),
                'position_direction': position_dir,
                'num_orders': len(strategy.active_orders),
                'regime': regime_name,
                'regime_confidence': regime_confidence,
                'max_drawdown': 0,
                'grid_spacing': strategy.spacing,
                'grid_levels': strategy.levels,
                'latest_price': round(tick['bid'], 2) if tick else 0,
                'broker_connected': acc is not None,
            })
        time.sleep(1)

# ── Main page ─────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('dashboard.html')

# ── API: Equity curve data ────────────────────────────────────────
@app.route('/equity_chart')
def equity_chart():
    rows = logger.get_equity_curve()
    if not rows:
        return jsonify([])
    return jsonify([{'x': t, 'y': e} for t, e in rows])

# ── API: Session stats (per-session performance) ──────────────────
@app.route('/session_stats')
def session_stats():
    fills = logger.get_fills()
    if not fills:
        return jsonify([])
    fills_df = pd.DataFrame(fills, columns=['id','timestamp','symbol','side','price','volume','pnl'])
    equity_df = pd.DataFrame(logger.get_equity_curve(), columns=['timestamp','equity'])
    stats = session_performance(fills_df, equity_df)
    return jsonify(stats.to_dict(orient='records'))

# ── API: Overall performance metrics ──────────────────────────────
@app.route('/performance')
def performance():
    fills = logger.get_fills()
    if not fills:
        return jsonify({'status': 'no_trades'})
    fills_df = pd.DataFrame(fills, columns=['id','timestamp','symbol','side','price','volume','pnl'])
    equity_df = pd.DataFrame(logger.get_equity_curve(), columns=['timestamp','equity'])
    metrics = compute_metrics(fills_df, equity_df)
    return jsonify(metrics)

# ── API: Current regime ───────────────────────────────────────────
@app.route('/regime')
def regime():
    if regime_adapter:
        return jsonify({
            'regime': regime_adapter.regime_name,
            'confidence': round(regime_adapter.confidence * 100, 1),
            'spacing': regime_adapter.spacing,
            'levels': regime_adapter.levels,
            'enabled': True,
        })
    return jsonify({
        'regime': 'unknown',
        'confidence': 0.0,
        'spacing': strategy.spacing,
        'levels': strategy.levels,
        'enabled': False,
    })

# ── API: Current position ─────────────────────────────────────────
@app.route('/position')
def position():
    pos = connector.get_positions()
    net = sum(p['volume'] if p['type']=='buy' else -p['volume'] for p in pos)
    return jsonify({
        'direction': get_position_direction(net),
        'net_exposure': round(net, 4),
        'num_positions': len(pos),
    })

# ── API: Grid status ──────────────────────────────────────────────
@app.route('/grid_status')
def grid_status():
    return jsonify({
        'active_orders': len(strategy.active_orders),
        'spacing': strategy.spacing,
        'levels': strategy.levels,
        'buy_levels': [round(p, 2) for p in sorted(strategy.buy_levels)],
        'sell_levels': [round(p, 2) for p in sorted(strategy.sell_levels)],
    })

# ── API: Recent trades ────────────────────────────────────────────
@app.route('/recent_trades')
def recent_trades():
    fills = logger.get_fills()
    if not fills:
        return jsonify([])
    trades = []
    for f in fills[-50:]:  # last 50 trades
        trades.append({
            'timestamp': f[1],
            'symbol': f[2],
            'side': f[3].upper(),
            'price': round(f[4], 2),
            'volume': round(f[5], 4),
            'pnl': round(f[6], 2),
        })
    return jsonify(list(reversed(trades)))

# ── API: Account summary ──────────────────────────────────────────
@app.route('/account_summary')
def account_summary():
    acc = connector.account_info()
    if not acc:
        return jsonify({'status': 'error', 'broker_connected': False})
    pos = connector.get_positions()
    net = sum(p['volume'] if p['type']=='buy' else -p['volume'] for p in pos)
    pnl = acc.equity - acc.balance
    pnl_pct = (pnl / acc.balance) * 100 if acc.balance > 0 else 0
    return jsonify({
        'balance': round(acc.balance, 2),
        'equity': round(acc.equity, 2),
        'pnl': round(pnl, 2),
        'pnl_pct': round(pnl_pct, 2),
        'net_position': round(net, 4),
        'position_direction': get_position_direction(net),
        'num_orders': len(strategy.active_orders),
        'broker_connected': True,
    })

# ── Control Routes ────────────────────────────────────────────────
@app.route('/start_strategy', methods=['POST'])
def start_strategy():
    global trading_active
    trading_active = True
    if not strategy.active_orders:
        strategy.reset_grid()
    return jsonify({'status': 'started'})

@app.route('/stop_strategy', methods=['POST'])
def stop_strategy():
    global trading_active
    trading_active = False
    connector.close_all_positions()
    return jsonify({'status': 'stopped'})

@app.route('/update_params', methods=['POST'])
def update_params():
    data = request.get_json()
    if 'spacing' in data:
        strategy.spacing = float(data['spacing'])
    if 'levels' in data:
        strategy.levels = int(data['levels'])
    strategy.reset_grid()
    return jsonify({'status': 'updated', 'spacing': strategy.spacing, 'levels': strategy.levels})

@app.route('/close_all', methods=['POST'])
def close_all():
    connector.close_all_positions()
    return jsonify({'status': 'all positions closed, pending orders cancelled'})

@app.route('/reset_grid', methods=['POST'])
def reset_grid():
    strategy.reset_grid()
    return jsonify({'status': 'grid reset'})

@app.route('/regime_refresh', methods=['POST'])
def regime_refresh():
    if regime_adapter:
        regime_adapter.refresh_now()
        return jsonify({'status': 'refreshed', 'regime': regime_adapter.regime_name})
    return jsonify({'status': 'ml_disabled'})

@app.route('/export_trades')
def export_trades():
    fills = logger.get_fills()
    if not fills:
        return "No trades", 404
    df = pd.DataFrame(fills, columns=['id','timestamp','symbol','side','price','volume','pnl'])
    output = io.StringIO()
    df.to_csv(output, index=False)
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='trades.csv'
    )

# ═══════════════════════════════════════════════════════════════════
#  DASHBOARD TABS — Backtest / Optimize / Report / Walkforward / ML
# ═══════════════════════════════════════════════════════════════════

def _run_task(task_id, fn, *args, **kwargs):
    """Run a task in a background thread, tracking status & results."""
    def wrapper():
        global task_status, task_results
        try:
            task_status[task_id] = 'running'
            result = fn(*args, **kwargs)
            task_results[task_id] = result
            task_status[task_id] = 'done'
        except Exception as e:
            task_results[task_id] = {'error': str(e), 'traceback': traceback.format_exc()}
            task_status[task_id] = 'error'
            socketio.emit('log', f"ERROR [{task_id}]: {e}")
    thread = threading.Thread(target=wrapper, daemon=True)
    thread.start()

def _run_backtest_task(symbol="GC=F", period="5d", interval="1m",
                        initial_capital=10000, spacing=0.1, levels=5, lot=1.0):
    from quant_env.backtest.data_loader import load_yfinance
    from quant_env.backtest.engine import BacktestEngine
    from quant_env.strategies.grid_strategy import GridStrategy
    from quant_env.analysis.performance import compute_metrics
    from quant_env.analysis.report_generator import generate_report

    socketio.emit('log', f"Backtest: downloading {symbol} ({period}, {interval})...")
    data = load_yfinance(symbol, period=period, interval=interval)
    if data is None or data.empty:
        return {'error': 'No data downloaded — check symbol/internet'}

    socketio.emit('log', f"Backtest: running engine (spacing={spacing}, levels={levels})...")
    engine = BacktestEngine(data, GridStrategy, initial_capital,
                            spacing=spacing, levels=levels, lot=lot)
    result = engine.run()
    metrics = compute_metrics(result.fills_df, result.equity_df)

    report_file = f"backtest_report_{int(time.time())}.html"
    from quant_env.analysis.session_analyzer import session_performance
    session = session_performance(result.fills_df, result.equity_df)
    generate_report(result.equity_df, result.fills_df, metrics, session, output_file=report_file)

    socketio.emit('log', f"Backtest: report saved → {report_file}")
    return {
        'status': 'done',
        'report_file': report_file,
        'metrics': metrics,
        'num_trades': len(result.fills_df) if result.fills_df is not None else 0,
    }

@app.route('/backtest', methods=['POST'])
def backtest_route():
    data = request.get_json() or {}
    task_id = f"backtest_{int(time.time())}"
    _run_task(task_id, _run_backtest_task,
              symbol=data.get('symbol', 'GC=F'),
              period=data.get('period', '5d'),
              interval=data.get('interval', '1m'),
              initial_capital=float(data.get('capital', 10000)),
              spacing=float(data.get('spacing', 0.1)),
              levels=int(data.get('levels', 5)),
              lot=float(data.get('lot', 1.0)))
    return jsonify({'task_id': task_id, 'status': 'started'})

# ────────────────────────────────────────────────────────────────
# Optimize
# ────────────────────────────────────────────────────────────────
def _run_optimize_task(symbol="GC=F", period="5d", interval="1m",
                         initial_capital=10000, lot=1.0):
    from quant_env.backtest.data_loader import load_yfinance
    from quant_env.backtest.engine import BacktestEngine
    from quant_env.analysis.performance import compute_metrics
    from quant_env.strategies.grid_strategy import GridStrategy

    socketio.emit('log', f"Optimize: downloading {symbol}...")
    data = load_yfinance(symbol, period=period, interval=interval)
    if data is None or data.empty:
        return {'error': 'No data downloaded'}

    spacings = [0.05, 0.1, 0.15, 0.2, 0.25]
    levels_list = [3, 5, 7, 9]
    results = []
    total = len(spacings) * len(levels_list)
    done = 0

    for sp in spacings:
        for lv in levels_list:
            engine = BacktestEngine(data.copy(), GridStrategy, initial_capital,
                                    spacing=sp, levels=lv, lot=lot)
            res = engine.run()
            m = compute_metrics(res.fills_df, res.equity_df)
            m['spacing'] = sp
            m['levels'] = lv
            results.append(m)
            done += 1
            socketio.emit('log', f"Optimize: {done}/{total} — spacing={sp}, levels={lv}")

    df = pd.DataFrame(results).sort_values('sharpe_ratio', ascending=False)
    csv_file = f"optimization_results_{int(time.time())}.csv"
    df.to_csv(csv_file, index=False)
    socketio.emit('log', f"Optimize: results saved → {csv_file}")

    top5 = df.head(5).to_dict(orient='records')
    return {'status': 'done', 'result_file': csv_file, 'top_results': top5}

@app.route('/optimize', methods=['POST'])
def optimize_route():
    data = request.get_json() or {}
    task_id = f"optimize_{int(time.time())}"
    _run_task(task_id, _run_optimize_task,
              symbol=data.get('symbol', 'GC=F'),
              period=data.get('period', '5d'),
              interval=data.get('interval', '1m'),
              initial_capital=float(data.get('capital', 10000)),
              lot=float(data.get('lot', 1.0)))
    return jsonify({'task_id': task_id, 'status': 'started'})

# ────────────────────────────────────────────────────────────────
# Report (live)
# ────────────────────────────────────────────────────────────────
def _run_report_task():
    from quant_env.analysis.trade_logger import TradeLogger
    from quant_env.analysis.performance import compute_metrics
    from quant_env.analysis.session_analyzer import session_performance
    from quant_env.analysis.report_generator import generate_report

    db_path = "quant_env/trades.db"
    tlog = TradeLogger(db_path)
    fills_rows = tlog.get_fills()
    if not fills_rows:
        tlog.close()
        return {'error': 'No trades yet — live report empty.'}

    fills_df = pd.DataFrame(fills_rows, columns=['id','timestamp','symbol','side','price','volume','pnl'])
    equity_rows = tlog.get_equity_curve()
    equity_df = pd.DataFrame(equity_rows, columns=['timestamp','equity'])
    metrics = compute_metrics(fills_df, equity_df)
    session = session_performance(fills_df, equity_df)
    report_file = f"live_report_{int(time.time())}.html"
    generate_report(equity_df, fills_df, metrics, session, output_file=report_file)
    tlog.close()
    socketio.emit('log', f"Report: saved → {report_file}")
    return {'status': 'done', 'report_file': report_file}

@app.route('/report', methods=['POST'])
def report_route():
    task_id = f"report_{int(time.time())}"
    _run_task(task_id, _run_report_task)
    return jsonify({'task_id': task_id, 'status': 'started'})

# ────────────────────────────────────────────────────────────────
# Walkforward
# ────────────────────────────────────────────────────────────────
def _run_walkforward_task(symbol="GC=F", period="1mo", interval="1h",
                          window_size=500, step_size=500,
                          initial_capital=10000, lot=1.0):
    from quant_env.backtest.data_loader import load_yfinance
    from quant_env.strategies.grid_strategy import GridStrategy
    from quant_env.analysis.walkforward import walkforward_analysis

    socketio.emit('log', f"Walkforward: downloading {symbol}...")
    data = load_yfinance(symbol, period=period, interval=interval)
    if data is None or data.empty:
        return {'error': 'No data downloaded'}

    param_grid = {'spacing': [0.1, 0.2], 'levels': [3, 5]}
    socketio.emit('log', "Walkforward: running analysis...")
    wf_df = walkforward_analysis(data, GridStrategy, param_grid,
                                 window_size=window_size, step_size=step_size,
                                 initial_capital=initial_capital, lot=lot)
    csv_file = f"walkforward_results_{int(time.time())}.csv"
    wf_df.to_csv(csv_file, index=False)
    socketio.emit('log', f"Walkforward: saved → {csv_file}")
    return {'status': 'done', 'result_file': csv_file, 'rows': len(wf_df)}

@app.route('/walkforward', methods=['POST'])
def walkforward_route():
    data = request.get_json() or {}
    task_id = f"walkforward_{int(time.time())}"
    _run_task(task_id, _run_walkforward_task,
              symbol=data.get('symbol', 'GC=F'),
              period=data.get('period', '1mo'),
              interval=data.get('interval', '1h'),
              window_size=int(data.get('window', 500)),
              step_size=int(data.get('step', 500)),
              initial_capital=float(data.get('capital', 10000)),
              lot=float(data.get('lot', 1.0)))
    return jsonify({'task_id': task_id, 'status': 'started'})

# ────────────────────────────────────────────────────────────────
# Train ML
# ────────────────────────────────────────────────────────────────
def _run_train_ml_task(symbol="GC=F", period="3mo", interval="1h", lookback=20, threshold=25):
    from quant_env.ml.regime_model import RegimeClassifier
    from quant_env.backtest.data_loader import load_yfinance

    socketio.emit('log', f"Train ML: downloading {symbol} ({period}, {interval})...")
    data = load_yfinance(symbol, period=period, interval=interval)
    if data is None or data.empty:
        return {'error': 'No data downloaded'}

    socketio.emit('log', f"Train ML: {len(data)} bars. Training classifier...")
    clf = RegimeClassifier(lookback=lookback, threshold=threshold)
    clf.train(data)

    model_dir = os.path.join(os.path.dirname(__file__), '..', 'ml')
    os.makedirs(model_dir, exist_ok=True)
    model_path = os.path.join(model_dir, 'model.pkl')
    clf.save(model_path)
    socketio.emit('log', f"Train ML: model saved → {model_path}")
    return {'status': 'done', 'model_path': model_path}

@app.route('/train_ml', methods=['POST'])
def train_ml_route():
    data = request.get_json() or {}
    task_id = f"train_ml_{int(time.time())}"
    _run_task(task_id, _run_train_ml_task,
              symbol=data.get('symbol', 'GC=F'),
              period=data.get('period', '3mo'),
              interval=data.get('interval', '1h'),
              lookback=int(data.get('lookback', 20)),
              threshold=int(data.get('threshold', 25)))
    return jsonify({'task_id': task_id, 'status': 'started'})

# ── Task status polling ─────────────────────────────────────────
@app.route('/task_status/<task_id>')
def task_status_route(task_id):
    return jsonify({
        'status': task_status.get(task_id, 'not_found'),
        'result': task_results.get(task_id),
    })

# ── Socket Events ─────────────────────────────────────────────────
@socketio.on('connect')
def handle_connect():
    for msg in log_lines:
        emit('log', msg)

# ── API: Health & connection status ───────────────────────────────
@app.route('/health')
def health():
    """Return connection health status for the dashboard indicator."""
    status = {'dashboard': 'running', 'trading_active': trading_active}
    # Check connector
    try:
        acc = connector.account_info()
        status['broker_connected'] = acc is not None
        if acc:
            status['balance'] = round(acc.balance, 2)
            status['equity'] = round(acc.equity, 2)
    except Exception:
        status['broker_connected'] = False
    # Check bridge connectivity (for MODE=bridge)
    if config.MODE == 'bridge':
        try:
            import requests
            r = requests.get(f"{config.BRIDGE_URL}/status", timeout=5)
            status['bridge_connected'] = r.status_code == 200
        except Exception:
            status['bridge_connected'] = False
    else:
        status['bridge_connected'] = None  # direct mode, N/A
    return jsonify(status)


if __name__ == '__main__':
    # ── Config file check ──────────────────────────────────────────
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config.py')
    example_path = os.path.join(os.path.dirname(__file__), '..', 'config.example.py')
    if not os.path.exists(config_path):
        print("=" * 60)
        print("  ERROR: config.py not found!")
        print("=" * 60)
        print(f"  Copy the example config and edit it:")
        print(f"    cp {example_path} {config_path}")
        print(f"  Then edit {config_path} with your broker settings.")
        print("=" * 60)
        sys.exit(1)
    print(f"  ✓ Using config: {config_path}")

    # Quick sanity checks
    checks = []
    if config.SYMBOL == "":
        checks.append("SYMBOL is empty — set a trading symbol in config.py")
    if config.BRIDGE_URL == "" and config.MODE == 'bridge':
        checks.append("BRIDGE_URL is empty — set your MT5 bridge IP in config.py")
    if checks:
        print("⚠️  Configuration warnings:")
        for c in checks:
            print(f"    - {c}")
        print()

    # Start adaptive updater (if enabled in config)
    if config.ADAPTIVE_ENABLED:
        from quant_env.adaptive.updater import AdaptiveUpdater
        adaptive = AdaptiveUpdater(config, strategy, log)
        adaptive.start()
        print("  ✓ Adaptive updater started")

    print(f"  ✓ Dashboard: http://localhost:5050")
    print(f"  ⏸️  Trading starts PAUSED — click 'Start' in the dashboard to begin.")
    print()

    threading.Thread(target=trading_loop, daemon=True).start()
    socketio.run(app, host='0.0.0.0', port=5050, debug=False)