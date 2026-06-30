#!/usr/bin/env python3
"""
Flask + SocketIO dashboard for the GridBot trading environment.
Start with:  python3 launcher.py dashboard
"""

import io
import os
import sys
import json
import subprocess
import threading
import tempfile
from pathlib import Path

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit

# ── Ensure we can import from quant_env ──────────────────────────────
# app.py is at  gridbots/quant_env/dashboard/app.py
# project root is gridbots/ (3 levels up)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Config check ─────────────────────────────────────────────────────
CONFIG_PATH = PROJECT_ROOT / "quant_env" / "config.py"
if not CONFIG_PATH.exists():
    print("=" * 60)
    print("  ERROR: config.py not found!")
    print(f"  Expected at: {CONFIG_PATH}")
    print()
    print("  Create it from the example:")
    print(f"    cp {PROJECT_ROOT}/quant_env/config.example.py {CONFIG_PATH}")
    print("=" * 60)
    sys.exit(1)

print(f"  Using config: {CONFIG_PATH}")

app = Flask(__name__)
app.config['SECRET_KEY'] = 'seek-quant-dashboard-secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ── Shared state ──────────────────────────────────────────────────────
state = {
    'bot': None,               # GridBot instance (or None)
    'trading_active': False,   # start paused
    'thread': None,            # main trading thread
    'stop_event': threading.Event(),
}

# ── Helper: run analysis / backtest scripts ──────────────────────────

def _run_script(script_name, *args):
    """Run a quant_env script and capture stdout."""
    script = PROJECT_ROOT / "quant_env" / script_name
    if not script.exists():
        script = PROJECT_ROOT / script_name
    cmd = [sys.executable or "python3", str(script), *args]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
    return result.stdout + result.stderr


def _run_launcher_command(cmd_type):
    """Run a launcher.py subcommand."""
    launcher = PROJECT_ROOT / "launcher.py"
    cmd = [sys.executable or "python3", str(launcher), cmd_type]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
    return result.stdout + result.stderr


def _format_result(raw_text: str) -> str:
    """Convert raw CLI output into minimal HTML for the dashboard."""
    lines = raw_text.split("\n")
    html = "<div class='cli-result'>"
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if line.startswith("=" * 3):
            # Section header
            html += f"<div class='cli-section-header'>{stripped.strip('=')}</div>"
        else:
            html += f"<div class='cli-line'>{stripped}</div>"
    html += "</div>"
    return html


# ── Stub helpers for dashboard data ────────────────────────────────────

def _get_recent_trades(limit=50):
    """Return recent trades from DB as list of dicts."""
    from quant_env.analysis.trade_logger import TradeLogger
    try:
        logger = TradeLogger()
        return logger.get_recent(limit)
    except Exception:
        return []


def _get_performance_metrics():
    """Return aggregated performance metrics."""
    from quant_env.analysis.trade_logger import TradeLogger
    from quant_env.analysis.performance import compute_metrics
    try:
        logger = TradeLogger()
        trades = logger.get_recent(500)
        if trades:
            import pandas as pd
            fills = pd.DataFrame(trades)
            equity = pd.DataFrame({'equity': fills['equity'] if 'equity' in fills.columns else [10000] * len(fills)})
            return compute_metrics(fills, equity)
        return None
    except Exception:
        return None


def _get_equity_curve():
    """Return equity curve data points."""
    from quant_env.analysis.trade_logger import TradeLogger
    try:
        logger = TradeLogger()
        return logger.get_equity_curve()
    except Exception:
        return []


# ── Routes ────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('dashboard.html')


@app.route('/equity_chart')
def equity_chart():
    data = _get_equity_curve()
    return jsonify(data)


@app.route('/performance')
def performance():
    metrics = _get_performance_metrics()
    if metrics is None:
        return jsonify({'status': 'no_trades'})
    return jsonify({
        'status': 'ok',
        'win_rate_pct': metrics.get('win_rate_pct', 0),
        'profit_factor': metrics.get('profit_factor', 0),
        'sharpe_ratio': metrics.get('sharpe_ratio', 0),
        'num_trades': metrics.get('num_trades', 0),
        'total_return_pct': metrics.get('total_return_pct', 0),
        'avg_win': metrics.get('avg_win', 0),
        'avg_loss': metrics.get('avg_loss', 0),
        'max_drawdown_pct': metrics.get('max_drawdown_pct', 0),
    })


@app.route('/recent_trades')
def recent_trades():
    trades = _get_recent_trades(50)
    return jsonify(trades)


@app.route('/export_trades')
def export_trades():
    trades = _get_recent_trades(500)
    csv_rows = ["timestamp,symbol,side,price,volume,pnl"]
    for t in trades:
        csv_rows.append(
            f"{t.get('timestamp','')},{t.get('symbol','')},{t.get('side','')},"
            f"{t.get('price',0)},{t.get('volume',0)},{t.get('pnl',0)}"
        )
    csv_content = "\n".join(csv_rows)
    return csv_content, 200, {'Content-Type': 'text/csv', 'Content-Disposition': 'attachment; filename=trades.csv'}


@app.route('/api/status')
def api_status():
    """JSON status for polling."""
    grid_status = {}
    if state['bot'] is not None:
        try:
            gs = state['bot'].get_status()
            grid_status = {
                'active_orders': gs.get('active_orders', 0),
                'pnl': gs.get('total_pnl', 0.0),
                'open_positions': gs.get('open_positions', 0),
                'current_price': gs.get('current_price', 0.0),
            }
        except Exception:
            grid_status = {}
    
    return jsonify({
        'trading_active': state['trading_active'],
        'has_bot': state['bot'] is not None,
        'broker_connected': state['bot'] is not None and hasattr(state['bot'], 'connected') and state['bot'].connected,
        'grid_status': grid_status,
    })


# ── Bot control routes ────────────────────────────────────────────────

def _start_bot_in_thread():
    """Import and start GridBot in a background thread."""
    from quant_env.main import GridBot
    bot = GridBot()
    state['bot'] = bot
    # Auto-resume if the user already requested trading to be active
    if state['trading_active']:
        bot.resume()
    bot.run()


@app.route('/api/bot/start', methods=['POST'])
def api_bot_start():
    if state['trading_active']:
        return jsonify({'status': 'already_active', 'message': 'Bot is already running.'})
    if state['thread'] is None or not state['thread'].is_alive():
        state['stop_event'].clear()
        state['trading_active'] = True
        t = threading.Thread(target=_start_bot_in_thread, daemon=True)
        t.start()
        state['thread'] = t
    else:
        state['trading_active'] = True
        if state['bot']:
            state['bot'].resume()
    return jsonify({'status': 'started', 'message': 'Bot started.'})


@app.route('/api/bot/stop', methods=['POST'])
def api_bot_stop():
    state['trading_active'] = False
    if state['bot']:
        state['bot'].pause()
    return jsonify({'status': 'stopped', 'message': 'Bot paused.'})


@app.route('/api/bot/close_all', methods=['POST'])
def api_bot_close_all():
    if state['bot']:
        state['bot'].close_all_positions()
    return jsonify({'status': 'closed', 'message': 'Positions closed.'})


@app.route('/api/bot/reset_grid', methods=['POST'])
def api_bot_reset_grid():
    if state['bot']:
        state['bot'].reset_grid()
    return jsonify({'status': 'reset', 'message': 'Grid reset.'})


@app.route('/api/bot/refresh_regime', methods=['POST'])
def api_bot_refresh_regime():
    if state['bot']:
        regime = state['bot'].detect_regime()
        return jsonify({'status': 'refreshed', 'regime': regime})
    return jsonify({'status': 'no_bot', 'regime': 'unknown'})


# ── Operation routes (background tasks) ──────────────────────────────

@app.route('/api/operation/backtest', methods=['POST'])
def op_backtest():
    data = request.get_json() or {}
    symbol = data.get('symbol', 'XAUUSD.r')
    output = _run_launcher_command('backtest')
    return jsonify({
        'status': 'done',
        'result_html': _format_result(output),
    })


@app.route('/api/operation/optimize', methods=['POST'])
def op_optimize():
    output = _run_launcher_command('optimize')
    return jsonify({
        'status': 'done',
        'result_html': _format_result(output),
    })


@app.route('/api/operation/report', methods=['POST'])
def op_report():
    output = _run_launcher_command('report')
    return jsonify({
        'status': 'done',
        'result_html': _format_result(output),
    })


@app.route('/api/operation/walkforward', methods=['POST'])
def op_walkforward():
    output = _run_launcher_command('walkforward')
    return jsonify({
        'status': 'done',
        'result_html': _format_result(output),
    })


@app.route('/api/operation/train_ml', methods=['POST'])
def op_train_ml():
    output = _run_launcher_command('train_ml')
    return jsonify({
        'status': 'done',
        'result_html': _format_result(output),
    })


# ── SocketIO (live status) ────────────────────────────────────────────

def _emit_status():
    """Periodically broadcast status to connected clients.
    
    Emits 'update' event with the rich data structure expected by
    the dashboard JavaScript (dashboard.html socket.on('update', ...)).
    """
    while not state['stop_event'].is_set():
        try:
            gs = {}
            if state['bot'] is not None:
                try:
                    gs = state['bot'].get_status()
                except Exception:
                    gs = {}
            regime = gs.get('regime', 'unknown')
            pos_dir = gs.get('position_direction', 'Neutral')
            price = gs.get('current_price', 0.0)
            pnl = gs.get('total_pnl', 0.0)
            broker_ok = state['bot'] is not None and getattr(state['bot'], 'connected', False)

            socketio.emit('update', {
                'trading_active': state['trading_active'],
                'has_bot': state['bot'] is not None,
                'broker_connected': broker_ok,
                'balance': gs.get('balance', None),
                'equity': gs.get('equity', None),
                'pnl': pnl,
                'pnl_pct': gs.get('pnl_pct', 0.0),
                'num_orders': gs.get('active_orders', 0),
                'max_drawdown': gs.get('max_drawdown_pct', 0.0),
                'regime': regime,
                'regime_confidence': gs.get('regime_confidence', 0.0),
                'position_direction': pos_dir,
                'net_position': gs.get('net_position', 0.0),
                'latest_price': price,
                'grid_spacing': gs.get('grid_spacing', None),
                'grid_levels': gs.get('grid_levels', None),
            })
        except Exception:
            pass
        state['stop_event'].wait(5)


if __name__ == '__main__':
    socketio.start_background_task(_emit_status)
    print("=" * 50)
    print("  Dashboard:  http://localhost:5050")
    print("  Bot starts paused — click 'Start' in the sidebar.")
    print("=" * 50)
    socketio.run(app, host='0.0.0.0', port=5050, debug=False, allow_unsafe_werkzeug=True)