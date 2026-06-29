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
PROJECT_ROOT = Path(__file__).resolve().parent.parent
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
socketio = SocketIO(app, cors_allowed_origins="*")

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


# ── Routes ────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('dashboard.html')


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
    """Periodically broadcast status to connected clients."""
    while not state['stop_event'].is_set():
        try:
            grid_status = {}
            if state['bot'] is not None:
                gs = state['bot'].get_status()
                grid_status = {
                    'active_orders': gs.get('active_orders', 0),
                    'pnl': gs.get('total_pnl', 0.0),
                    'open_positions': gs.get('open_positions', 0),
                    'current_price': gs.get('current_price', 0.0),
                }
            broker_ok = state['bot'] is not None and getattr(state['bot'], 'connected', False)
            socketio.emit('status', {
                'trading_active': state['trading_active'],
                'has_bot': state['bot'] is not None,
                'broker_connected': broker_ok,
                'grid_status': grid_status,
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