from flask import Flask, render_template, jsonify, request, send_file
from flask_socketio import SocketIO, emit
import threading, time, sys, os, io, csv
sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from quant_env.config import Config
from quant_env.core.connector import Connector
from quant_env.core.risk_manager import RiskManager
from quant_env.strategies.grid_strategy import GridStrategy
from quant_env.core.logger import setup_logger
from quant_env.analysis.trade_logger import TradeLogger
from quant_env.analysis.session_analyzer import session_performance
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

# Global flag to pause/resume trading
trading_active = True

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
                socketio.emit('update', {
                    'balance':acc.balance,'equity':acc.equity,
                    'pnl':pnl,'net_position':net,
                    'num_orders':len(strategy.active_orders)
                })
                check_risk()
        time.sleep(1)

# ---------- Existing routes ----------
@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/equity_chart')
def equity_chart():
    rows = logger.get_equity_curve()
    return jsonify([{'x':t,'y':e} for t,e in rows])

@app.route('/session_stats')
def session_stats():
    fills = logger.get_fills()
    if not fills:
        return jsonify([])
    fills_df = pd.DataFrame(fills, columns=['id','timestamp','symbol','side','price','volume','pnl'])
    equity_df = pd.DataFrame(logger.get_equity_curve(), columns=['timestamp','equity'])
    stats = session_performance(fills_df, equity_df)
    return jsonify(stats.to_dict(orient='records'))

# ---------- NEW Control Routes ----------
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

# ---------- Socket Events ----------
@socketio.on('connect')
def handle_connect():
    # Send existing log lines on connect
    for msg in log_lines:
        emit('log', msg)

if __name__ == '__main__':
    # Start adaptive updater (if enabled in config)
    if config.ADAPTIVE_ENABLED:
        from quant_env.adaptive.updater import AdaptiveUpdater
        adaptive = AdaptiveUpdater(config, strategy, log)
        adaptive.start()

    threading.Thread(target=trading_loop, daemon=True).start()
    socketio.run(app, host='0.0.0.0', port=5050, debug=False)