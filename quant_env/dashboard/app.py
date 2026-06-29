from flask import Flask, render_template, jsonify, request, send_file
from flask_socketio import SocketIO, emit
import threading, time, sys, os, io, csv, math, textwrap
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
        if trading_active:
            tick = connector.symbol_tick()
            if tick:
                strategy.on_tick(tick)
            acc = connector.account_info()
            pos = connector.get_positions()
            net = sum(p['volume'] if p['type']=='buy' else -p['volume'] for p in pos)
            if acc:
                logger.log_equity(acc.equity, acc.balance, net, len(strategy.active_orders))
                pnl = acc.equity - acc.balance
                pnl_pct = (pnl / acc.balance) * 100 if acc.balance > 0 else 0

                # Get regime info
                regime_name = "unknown"
                regime_confidence = 0.0
                if regime_adapter:
                    regime_name = regime_adapter.regime_name
                    regime_confidence = round(regime_adapter.confidence * 100, 1)

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
        return jsonify({'status': 'error'})
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
    if config.BRIDGE_URL == "":
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
