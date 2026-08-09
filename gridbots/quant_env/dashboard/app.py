#!/usr/bin/env python3
"""
Flask dashboard for the GridBot trading environment.
Start with:  python3 launcher.py dashboard

Supports MULTI-ACCOUNT trading — each broker account runs its own
GridBot in a background thread, fully isolated.
"""
import json
import os
import subprocess
import sys
import threading
import tempfile
import time
import random
import math
from pathlib import Path

from flask import Flask, render_template, request, jsonify
import requests as http_requests

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

from quant_env.config import Config

app = Flask(__name__)


@app.after_request
def _add_cors_headers(response):
    """Allow the Next.js dashboard (any origin, dev-friendly) to call this API."""
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return response


@app.route('/api/<path:_path>', methods=['OPTIONS'])
def _cors_preflight(_path):
    return ('', 204)

# ── Shared state ──────────────────────────────────────────────────────
# manager is a GridBotManager instance that orchestrates all accounts
_manager = None
_manager_lock = threading.Lock()

_BRIDGE_SESSION = None

# ── Strategy results storage ──────────────────────────────────────────
STRATEGY_RESULTS_PATH = PROJECT_ROOT / "quant_env" / "strategy_results.json"


def _get_manager():
    """Lazy-initialize and return the GridBotManager singleton."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                from quant_env.main import GridBotManager
                _manager = GridBotManager()
                # Ensure at least one default account exists
                _manager.account_manager.ensure_default_account()
    return _manager


def _load_strategy_results() -> dict:
    """Load persisted strategy performance results from disk."""
    if STRATEGY_RESULTS_PATH.exists():
        try:
            with open(STRATEGY_RESULTS_PATH, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_strategy_results(results: dict):
    """Persist strategy performance results to disk."""
    try:
        STRATEGY_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(STRATEGY_RESULTS_PATH, 'w') as f:
            json.dump(results, f, indent=2, default=str)
    except Exception as e:
        print(f"[StrategyResults] Could not save: {e}")


def _update_strategy_result(strategy_key: str, operation: str, metrics: dict):
    """Update the stored result for a strategy after a backtest/optimize/etc."""
    results = _load_strategy_results()
    if strategy_key not in results:
        results[strategy_key] = {}
    results[strategy_key][operation] = {
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'metrics': metrics,
    }
    _save_strategy_results(results)


def _get_bridge_url() -> str:
    """Return the broker bridge URL from Config or env, fallback to localhost."""
    return (os.environ.get('BRIDGE_URL')
            or getattr(Config, 'BRIDGE_URL', 'http://127.0.0.1:8080'))


def _try_bridge_status():
    """Fetch live account/status from the MT5 bridge server."""
    global _BRIDGE_SESSION
    if _BRIDGE_SESSION is None:
        _BRIDGE_SESSION = http_requests.Session()
    url = f"{_get_bridge_url()}/account_info"
    try:
        resp = _BRIDGE_SESSION.get(url, timeout=1.5)
        if resp.status_code == 200:
            acct = resp.json()
            pos_url = f"{_get_bridge_url()}/positions"
            try:
                pos_resp = _BRIDGE_SESSION.get(pos_url, timeout=1.0)
                positions = pos_resp.json() if pos_resp.status_code == 200 else []
            except Exception:
                positions = []

            net_pos = 0.0
            dir_str = "Neutral"
            if positions:
                for p in positions:
                    vol = float(p.get("volume", 0))
                    net_pos += vol if p.get("type") == "buy" else -vol
                dir_str = "Long" if net_pos > 0 else "Short"

            from quant_env.config import Config as Cfg
            sym = Cfg.SYMBOL if hasattr(Cfg, 'SYMBOL') else "XAUUSD"
            tick_url = f"{_get_bridge_url()}/symbol_tick?symbol={sym}"
            latest_price = None
            try:
                tr = _BRIDGE_SESSION.get(tick_url, timeout=1.0)
                if tr.status_code == 200:
                    latest_price = tr.json().get("bid")
            except Exception:
                pass

            balance = float(acct.get("balance", 0))
            equity = float(acct.get("equity", 0))
            pnl = equity - balance
            pnl_pct = (pnl / balance * 100) if balance else 0.0

            return {
                "balance": round(balance, 2),
                "equity": round(equity, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "num_orders": len(positions),
                "max_drawdown": 0.0,
                "regime": "unknown",
                "regime_confidence": 0.0,
                "position_direction": dir_str,
                "net_position": round(net_pos, 2),
                "latest_price": latest_price,
                "grid_spacing": None,
                "grid_levels": None,
            }
    except (http_requests.exceptions.ConnectionError,
            http_requests.exceptions.Timeout):
        pass
    return None


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
            html += f"<div class='cli-section-header'>{stripped.strip('=')}</div>"
        else:
            html += f"<div class='cli-line'>{stripped}</div>"
    html += "</div>"
    return html


# ── Stub helpers for dashboard data ────────────────────────────────────

def _get_recent_trades(account_id=None, limit=50):
    """Return recent trades from DB as list of dicts.

    Reads the per-account trade DB first, then falls back to the legacy
    engine DB (gridbots/quant_env/trades.db) which holds historical fills
    written before multi-account split.
    """
    from quant_env.analysis.trade_logger import TradeLogger
    try:
        logger = TradeLogger(account_id=account_id or "default")
        rows = logger.get_recent(limit)
        logger.close()
        if rows:
            return rows
    except Exception:
        pass

    # Legacy single-file DB fallback
    legacy = PROJECT_ROOT / "quant_env" / "trades.db"
    if legacy.exists():
        try:
            import sqlite3 as _sql
            conn = _sql.connect(str(legacy), timeout=5.0)
            rows = conn.execute(
                "SELECT timestamp, symbol, side, price, volume, pnl FROM fills ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            conn.close()
            return [
                {"timestamp": ts, "symbol": sym, "side": side, "price": float(price or 0),
                 "volume": float(vol or 0), "pnl": float(pnl or 0)}
                for ts, sym, side, price, vol, pnl in rows
            ]
        except Exception:
            pass
    return []


def _get_performance_metrics(account_id=None):
    """Return aggregated performance metrics (per-account DB, then legacy)."""
    from quant_env.analysis.trade_logger import TradeLogger
    from quant_env.analysis.performance import compute_metrics
    try:
        logger = TradeLogger(account_id=account_id or "default")
        trades = logger.get_recent(500)
        logger.close()
        if not trades:
            trades = _get_recent_trades(account_id, 500)
        if trades:
            import pandas as pd
            fills = pd.DataFrame(trades)
            if 'equity' not in fills.columns:
                equity = pd.DataFrame({'equity': [10000] * len(fills)})
            else:
                equity = pd.DataFrame({'equity': fills['equity']})
            return compute_metrics(fills, equity)
        return None
    except Exception:
        return None


def _get_equity_curve(account_id=None):
    """Return equity curve data points (per-account DB, then legacy)."""
    from quant_env.analysis.trade_logger import TradeLogger
    try:
        logger = TradeLogger(account_id=account_id or "default")
        rows = logger.get_equity_curve()
        logger.close()
        if rows:
            return rows
    except Exception:
        pass

    legacy = PROJECT_ROOT / "quant_env" / "trades.db"
    if legacy.exists():
        try:
            import sqlite3 as _sql
            conn = _sql.connect(str(legacy), timeout=5.0)
            rows = conn.execute(
                "SELECT timestamp, equity FROM equity_snapshots ORDER BY timestamp"
            ).fetchall()
            conn.close()
            return rows
        except Exception:
            pass
    return []


# ── Simulation helpers (demo mode when no broker connected) ──────────

_sim_start_time = time.time()

def _generate_demo_status():
    """Generate realistic demo data when no broker/bot is connected."""
    elapsed = time.time() - _sim_start_time
    base_balance = 10000.0
    drift = 50.0 * math.sin(elapsed / 30.0) + 20.0 * math.sin(elapsed / 7.0)
    sim_equity = base_balance + drift
    sim_pnl = sim_equity - base_balance
    sim_pnl_pct = (sim_pnl / base_balance) * 100.0
    regimes = ['ranging', 'trending', 'unknown']
    regime_idx = int((elapsed // 20) % 3)
    regime = regimes[regime_idx]
    conf = 45.0 + 40.0 * (0.5 + 0.5 * math.sin(elapsed / 10.0))
    sim_price = 2350.0 + 5.0 * math.sin(elapsed / 15.0) + random.gauss(0, 0.5)
    return {
        'trading_active': False,
        'has_bot': False,
        'broker_connected': False,
        'balance': base_balance,
        'equity': round(sim_equity, 2),
        'pnl': round(sim_pnl, 2),
        'pnl_pct': round(sim_pnl_pct, 2),
        'num_orders': 0,
        'max_drawdown': round(abs(drift) / base_balance * 100, 2),
        'regime': regime,
        'regime_confidence': round(min(conf, 95.0), 1),
        'position_direction': 'Neutral',
        'net_position': 0.0,
        'latest_price': round(sim_price, 2),
        'grid_spacing': 2.0,
        'grid_levels': 3,
        'active_strategy': None,
    }


# ── Routes ────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('dashboard.html')


@app.route('/api/equity_chart')
@app.route('/equity_chart')
def equity_chart():
    account_id = request.args.get('account_id')
    data = _get_equity_curve(account_id)
    return jsonify(data)


@app.route('/api/performance')
@app.route('/performance')
def performance():
    account_id = request.args.get('account_id')
    metrics = _get_performance_metrics(account_id)
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


@app.route('/api/recent_trades')
@app.route('/recent_trades')
def recent_trades():
    account_id = request.args.get('account_id')
    trades = _get_recent_trades(account_id, 50)
    return jsonify(trades)


@app.route('/export_trades')
def export_trades():
    account_id = request.args.get('account_id')
    trades = _get_recent_trades(account_id, 500)
    csv_rows = ["timestamp,symbol,side,price,volume,pnl"]
    for t in trades:
        csv_rows.append(
            f"{t.get('timestamp','')},{t.get('symbol','')},{t.get('side','')},"
            f"{t.get('price',0)},{t.get('volume',0)},{t.get('pnl',0)}"
        )
    csv_content = "\n".join(csv_rows)
    return csv_content, 200, {'Content-Type': 'text/csv', 'Content-Disposition': 'attachment; filename=trades.csv'}


# ═══════════════════════════════════════════════════════════════════════
#  ACCOUNT API ROUTES
# ═══════════════════════════════════════════════════════════════════════

@app.route('/api/accounts', methods=['GET'])
def api_list_accounts():
    """List all brokerage accounts with their status."""
    mgr = _get_manager()
    accounts = mgr.account_manager.list_accounts()
    statuses = {s['account_id']: s for s in mgr.all_statuses()}
    result = []
    for acct in accounts:
        info = statuses.get(acct.id, {})
        result.append({
            'id': acct.id,
            'label': acct.label,
            'user_id': acct.user_id,
            'broker_type': acct.broker_type.value,
            'connection_status': acct.status.value,
            'enabled': acct.enabled,
            'created_at': acct.created_at.isoformat(),
            'updated_at': acct.updated_at.isoformat(),
            'last_error': acct.last_error,
            # Live data from the bot if running
            'balance': info.get('balance', 0.0),
            'equity': info.get('equity', 0.0),
            'total_pnl': info.get('total_pnl', 0.0),
            'active_orders': info.get('active_orders', 0),
            'open_positions': info.get('open_positions', 0),
            'paused': info.get('paused', True),
            'regime': info.get('regime', 'unknown'),
            'position_direction': info.get('position_direction', 'Neutral'),
        })
    return jsonify({'accounts': result})


@app.route('/api/accounts/<account_id>', methods=['GET'])
def api_get_account(account_id):
    """Get details for a single account."""
    mgr = _get_manager()
    acct = mgr.account_manager.get_account(account_id)
    if acct is None:
        return jsonify({'status': 'error', 'message': 'Account not found'}), 404
    statuses = {s['account_id']: s for s in mgr.all_statuses()}
    info = statuses.get(account_id, {})
    return jsonify({
        'id': acct.id,
        'label': acct.label,
        'user_id': acct.user_id,
        'broker_type': acct.broker_type.value,
        'connection_status': acct.status.value,
        'enabled': acct.enabled,
        'connection_config': {k: v for k, v in acct.connection_config.items()
                              if k != 'password'},
        'trading_config': acct.trading_config,
        'risk_config': acct.risk_config,
        'created_at': acct.created_at.isoformat(),
        'updated_at': acct.updated_at.isoformat(),
        'last_error': acct.last_error,
        'balance': info.get('balance', 0.0),
        'equity': info.get('equity', 0.0),
        'total_pnl': info.get('total_pnl', 0.0),
    })


@app.route('/api/accounts', methods=['POST'])
def api_create_account():
    """Create a new brokerage account."""
    data = request.get_json() or {}
    label = data.get('label', '')
    broker_type = data.get('broker_type', 'mt5_bridge')
    connection_config = data.get('connection_config', {})
    trading_config = data.get('trading_config', {})
    risk_config = data.get('risk_config', {})

    if not label:
        return jsonify({'status': 'error', 'message': 'Label is required'}), 400

    from quant_env.accounts.models import BrokerType
    try:
        bt = BrokerType(broker_type)
    except ValueError:
        return jsonify({'status': 'error', 'message': f'Invalid broker_type: {broker_type}'}), 400

    mgr = _get_manager()
    acct = mgr.account_manager.create_account(
        label=label,
        broker_type=bt,
        connection_config=connection_config,
        trading_config=trading_config,
        risk_config=risk_config,
    )
    return jsonify({'status': 'ok', 'account': {'id': acct.id, 'label': acct.label}}), 201


@app.route('/api/accounts/<account_id>', methods=['PUT'])
def api_update_account(account_id):
    """Update an existing account."""
    data = request.get_json() or {}
    mgr = _get_manager()
    acct = mgr.account_manager.update_account(account_id, data)
    if acct is None:
        return jsonify({'status': 'error', 'message': 'Account not found'}), 404
    return jsonify({'status': 'ok', 'account': {'id': acct.id, 'label': acct.label}})


@app.route('/api/accounts/<account_id>', methods=['DELETE'])
def api_delete_account(account_id):
    """Delete an account and stop its bot if running."""
    mgr = _get_manager()
    mgr.stop_bot(account_id)
    deleted = mgr.account_manager.delete_account(account_id)
    if not deleted:
        return jsonify({'status': 'error', 'message': 'Account not found'}), 404
    return jsonify({'status': 'ok', 'message': 'Account deleted'})


@app.route('/api/accounts/<account_id>/test', methods=['POST'])
def api_test_account_connection(account_id):
    """Test connection to the broker for this account."""
    mgr = _get_manager()
    ok = mgr.account_manager.test_connection(account_id)
    acct = mgr.account_manager.get_account(account_id)
    return jsonify({
        'status': 'ok' if ok else 'error',
        'connected': ok,
        'connection_status': acct.status.value if acct else 'unknown',
        'last_error': acct.last_error if acct else None,
    })


# ═══════════════════════════════════════════════════════════════════════
#  BOT CONTROL API ROUTES
# ═══════════════════════════════════════════════════════════════════════

def _build_account_status(acct, bridge_data=None, bot_status=None):
    """
    Build a unified BotStatus dict for a single account.
    
    Merges data from:
      - The BrokerAccount itself (identity, connection status)
      - A running bot's status dict (if available)
      - Live bridge data from _try_bridge_status (if no bot running)
    
    Returns a dict matching the BotStatus interface the frontend expects.
    """
    result = {
        'account_id': acct.id,
        'label': acct.label,
        'broker_type': acct.broker_type.value,
        'connection_status': acct.status.value,
        'balance': 0.0,
        'equity': 0.0,
        'total_pnl': 0.0,
        'pnl': 0.0,
        'pnl_pct': 0.0,
        'active_orders': 0,
        'open_positions': 0,
        'net_position': 0.0,
        'num_orders': 0,
        'paused': True,
        'trading_active': False,
        'has_bot': False,
        'broker_connected': False,
        'regime': 'unknown',
        'regime_confidence': 0.0,
        'position_direction': 'Neutral',
        'latest_price': None,
        'grid_spacing': None,
        'grid_levels': None,
        'max_drawdown': 0.0,
        'max_drawdown_pct': 0.0,
    }

    # Priority 1: running bot status (most accurate)
    if bot_status:
        result.update(bot_status)
        result['has_bot'] = True
        result['trading_active'] = True
        result['broker_connected'] = bot_status.get('broker_connected', False)
        # Normalise pnl fields
        if 'total_pnl' in bot_status and 'pnl' not in bot_status:
            result['pnl'] = bot_status['total_pnl']
        if 'pnl' in bot_status and 'total_pnl' not in bot_status:
            result['total_pnl'] = bot_status['pnl']
        return result

    # Priority 2: live bridge data (no bot running, but bridge is reachable)
    if bridge_data:
        result.update(bridge_data)
        result['has_bot'] = False
        result['trading_active'] = False
        result['paused'] = True
        result['broker_connected'] = True
        result['total_pnl'] = bridge_data.get('pnl', 0.0)
        # connection_status becomes 'connected' since bridge responded
        result['connection_status'] = 'connected'
        return result

    # Priority 3: account record only — bridge is unreachable
    result['connection_status'] = acct.status.value if acct.status else 'disconnected'
    result['broker_connected'] = False
    result['last_error'] = acct.last_error
    return result


@app.route('/api/status')
def api_status():
    """
    JSON status — returns all accounts and aggregate dashboard data.
    Called every 5 s by pollStatus() in dashboard.html.
    Always wraps individual results in { accounts: [ … ] } for the frontend.
    """
    mgr = _get_manager()
    account_id = request.args.get('account_id')

    # ── Aggregate: return all accounts FROM RUNNING BOTS ───────────────
    # Check if any bot threads are actually running before trusting
    # all_statuses() — it returns stored account data even when idle.
    has_active_bots = bool(mgr._bots) and any(
        hasattr(b, '_thread') and b._thread and b._thread.is_alive()
        for b in mgr._bots.values()
    )
    statuses = mgr.all_statuses() if has_active_bots else []

    if statuses:
        total_balance = sum(s.get('balance', 0.0) for s in statuses)
        total_equity = sum(s.get('equity', 0.0) for s in statuses)
        total_pnl = sum(s.get('total_pnl', 0.0) for s in statuses)
        return jsonify({
            'accounts': statuses,
            'total_balance': round(total_balance, 2),
            'total_equity': round(total_equity, 2),
            'total_pnl': round(total_pnl, 2),
            'total_pnl_pct': round((total_pnl / total_balance * 100) if total_balance else 0.0, 2),
            'num_accounts': len(statuses),
        })

    # No running bots — try reading live data from the bridge directly
    bridge_data = _try_bridge_status()
    if bridge_data:
        # All accounts from the store with bridge data merged in
        accounts = mgr.account_manager.list_accounts()
        acc_list = []
        if accounts:
            for acct in accounts:
                acc_list.append(_build_account_status(acct, bridge_data=bridge_data))
        else:
            # No accounts configured — show bridge data as a single demo account
            demo = _generate_demo_status()
            demo.update(bridge_data)
            demo['broker_connected'] = True
            demo['connection_status'] = 'connected'
            acc_list.append(demo)

        total_balance = sum(s.get('balance', 0.0) for s in acc_list)
        total_equity = sum(s.get('equity', 0.0) for s in acc_list)
        total_pnl = sum(s.get('pnl', 0.0) for s in acc_list)
        return jsonify({
            'accounts': acc_list,
            'total_balance': round(total_balance, 2),
            'total_equity': round(total_equity, 2),
            'total_pnl': round(total_pnl, 2),
            'total_pnl_pct': round((total_pnl / total_balance * 100) if total_balance else 0.0, 2),
            'num_accounts': len(acc_list),
        })

    # Bridge is unreachable and no bots running.
    # If configured accounts exist, show demo data so the dashboard
    # has realistic placeholder values rather than all zeros.
    # Mark broker_connected=False so the UI can show a "not connected" indicator.
    demo = _generate_demo_status()
    accounts = mgr.account_manager.list_accounts()
    if accounts:
        # Use the first account's label/ID for context
        demo['account_id'] = accounts[0].id
        demo['label'] = accounts[0].label
        demo['connection_status'] = 'disconnected'
        demo['broker_connected'] = False
        demo['regime'] = 'unknown'
        demo['regime_confidence'] = 0.0
        demo['position_direction'] = 'Neutral'
        # Reset trading-specific fields since no bot/bridge is active
        demo['num_orders'] = 0
        demo['active_orders'] = 0
        demo['open_positions'] = 0
        demo['net_position'] = 0.0
        demo['grid_spacing'] = None
        demo['grid_levels'] = None
        demo['trading_active'] = False
        demo['has_bot'] = False
        # But keep realistic balance/equity/pnl so the UI doesn't show zeros
        # balance, equity, pnl are already set by _generate_demo_status()
    else:
        # No accounts at all — pure demo mode
        demo['connection_status'] = 'demo'
    return jsonify({'accounts': [demo]})


@app.route('/api/bot/start', methods=['POST'])
def api_bot_start():
    """Start trading for a specific account (or all accounts)."""
    try:
        data = request.get_json(silent=True) or {}
        account_id = data.get('account_id')

        mgr = _get_manager()

        if account_id:
            mgr.start_bot(account_id)
            mgr.resume_bot(account_id)
            return jsonify({'status': 'started', 'account_id': account_id, 'message': 'Started'})
        else:
            # Start all accounts
            accounts = mgr.account_manager.list_accounts()
            for acct in accounts:
                mgr.start_bot(acct.id)
                mgr.resume_bot(acct.id)
            return jsonify({'status': 'started', 'num_accounts': len(accounts), 'message': f'Started {len(accounts)} account(s)'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/bot/stop', methods=['POST'])
def api_bot_stop():
    """Stop trading for a specific account (or all accounts)."""
    try:
        data = request.get_json(silent=True) or {}
        account_id = data.get('account_id')

        mgr = _get_manager()
        if account_id:
            mgr.stop_bot(account_id)
            return jsonify({'status': 'stopped', 'account_id': account_id, 'message': 'Stopped'})
        else:
            mgr.stop_all()
            return jsonify({'status': 'stopped', 'message': 'All bots paused'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/bot/close_all', methods=['POST'])
def api_bot_close_all():
    """Close all positions for a specific account (or all accounts)."""
    try:
        data = request.get_json(silent=True) or {}
        account_id = data.get('account_id')

        mgr = _get_manager()
        if account_id:
            bot = mgr.get_bot(account_id)
            if bot:
                bot.close_all_positions()
            return jsonify({'status': 'closed', 'account_id': account_id, 'message': 'Positions closed'})
        else:
            for bot in mgr._bots.values():
                bot.close_all_positions()
            return jsonify({'status': 'closed', 'message': 'All positions closed'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/bot/reset_grid', methods=['POST'])
def api_bot_reset_grid():
    """Reset the grid for a specific account (or all accounts)."""
    try:
        data = request.get_json(silent=True) or {}
        account_id = data.get('account_id')

        mgr = _get_manager()
        if account_id:
            bot = mgr.get_bot(account_id)
            if bot:
                bot.reset_grid()
            return jsonify({'status': 'reset', 'account_id': account_id})
        else:
            for bot in mgr._bots.values():
                bot.reset_grid()
            return jsonify({'status': 'reset', 'message': 'All grids reset'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/bot/refresh_regime', methods=['POST'])
def api_bot_refresh_regime():
    """Force regime refresh for a specific account (or all accounts)."""
    try:
        data = request.get_json(silent=True) or {}
        account_id = data.get('account_id')

        mgr = _get_manager()
        accounts = mgr.account_manager.list_accounts()

        if account_id:
            # Refresh for a specific account
            bot = mgr.get_bot(account_id)
            if bot:
                regime = bot.detect_regime()
            else:
                regime = 'unknown'
            return jsonify({'status': 'refreshed', 'regime': regime, 'account_id': account_id})
        else:
            # Refresh for all accounts
            results = {}
            for acct in accounts:
                bot = mgr.get_bot(acct.id)
                if bot:
                    try:
                        results[acct.id] = bot.detect_regime()
                    except Exception:
                        results[acct.id] = 'error'
                else:
                    results[acct.id] = 'unknown'
            if not results:
                return jsonify({'status': 'refreshed', 'regime': 'unknown', 'message': 'No active bots running. Start a bot to refresh regime.'})
            first_regime = next(iter(results.values()), 'unknown')
            return jsonify({'status': 'refreshed', 'regime': first_regime, 'accounts': results})
    except Exception as e:
        return jsonify({'status': 'error', 'regime': 'unknown', 'message': str(e)})


# ── Strategy API routes ───────────────────────────────────────────────

@app.route('/api/strategies')
def api_strategies():
    """Return list of all discovered strategies with metadata."""
    try:
        from quant_env.strategies.registry import list_strategies
        strategies = list_strategies()
        return jsonify({
            'status': 'ok',
            'strategies': strategies,
            'active': None,    # per-account active strategy TBD
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e), 'strategies': []})


@app.route('/api/strategies/reload', methods=['POST'])
def api_strategies_reload():
    """Force re-scan of the strategies folder."""
    try:
        from quant_env.strategies.registry import reload, list_strategies
        reload()
        strategies = list_strategies()
        return jsonify({
            'status': 'ok',
            'message': f'Reloaded {len(strategies)} strategies.',
            'strategies': strategies,
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/api/strategy/select', methods=['POST'])
def api_strategy_select():
    """Set the active strategy for a specific account."""
    data = request.get_json() or {}
    key = data.get('strategy')
    account_id = data.get('account_id')
    if not key:
        return jsonify({'status': 'error', 'message': 'No strategy key provided.'})
    # Strategy selection is per-account; for now just acknowledge
    return jsonify({'status': 'ok', 'message': f'Strategy "{key}" noted for account {account_id or "default"}.', 'strategy': key})


@app.route('/api/strategy/performance')
def api_strategy_performance():
    """Return stored performance results for all strategies."""
    results = _load_strategy_results()
    return jsonify({'status': 'ok', 'results': results})


# ── Operation routes (background tasks) ──────────────────────────────

def _run_backtest_for_strategy(strategy_key: str, params: dict) -> dict:
    """
    Run a backtest for the given strategy key with the provided params.
    Returns a dict with 'metrics' and 'result_html'.
    """
    try:
        from quant_env.strategies.registry import get_class
        from quant_env.backtest.data_loader import load_yfinance
        from quant_env.backtest.engine import BacktestEngine
        from quant_env.analysis.performance import compute_metrics

        strategy_cls = get_class(strategy_key)
        if strategy_cls is None:
            return {'error': f'Strategy "{strategy_key}" not found.'}

        symbol   = params.get('symbol', 'GC=F')
        period   = params.get('period', '1mo')
        interval = params.get('interval', '1h')
        capital  = float(params.get('capital', 10000))

        # Build strategy kwargs from remaining params (exclude meta params)
        meta_keys = {'symbol', 'period', 'interval', 'capital', 'strategy'}
        strategy_kwargs = {k: v for k, v in params.items() if k not in meta_keys}
        # Convert numeric strings
        for k, v in strategy_kwargs.items():
            try:
                strategy_kwargs[k] = float(v)
            except (ValueError, TypeError):
                pass

        data = load_yfinance(symbol, period=period, interval=interval)
        engine = BacktestEngine(data, strategy_cls, capital, **strategy_kwargs)
        result = engine.run()
        metrics = compute_metrics(result.fills_df, result.equity_df)

        # Persist results
        _update_strategy_result(strategy_key, 'backtest', metrics)

        lines = [
            f"Strategy: {getattr(strategy_cls, 'STRATEGY_NAME', strategy_key)}",
            f"Symbol: {symbol}  Period: {period}  Interval: {interval}",
            f"Capital: ${capital:,.0f}",
            "=" * 40,
            f"Total Return:   {metrics.get('total_return_pct', 0):.2f}%",
            f"Sharpe Ratio:   {metrics.get('sharpe_ratio', 0):.2f}",
            f"Max Drawdown:   {metrics.get('max_drawdown_pct', 0):.2f}%",
            f"Win Rate:       {metrics.get('win_rate_pct', 0):.2f}%",
            f"Profit Factor:  {metrics.get('profit_factor', 0):.2f}",
            f"Total Trades:   {metrics.get('num_trades', 0)}",
            f"Avg Win:        ${metrics.get('avg_win', 0):.2f}",
            f"Avg Loss:       ${metrics.get('avg_loss', 0):.2f}",
        ]
        return {
            'metrics': metrics,
            'result_html': _format_result('\n'.join(lines)),
        }
    except Exception as e:
        import traceback
        return {'error': str(e), 'result_html': _format_result(f'ERROR: {e}\n{traceback.format_exc()}')}


@app.route('/api/operation/backtest', methods=['POST'])
def op_backtest():
    data = request.get_json() or {}
    strategy_key = data.get('strategy') or 'grid_strategy'

    try:
        from quant_env.strategies.registry import get_class
        cls = get_class(strategy_key)
        if cls is not None:
            result = _run_backtest_for_strategy(strategy_key, data)
            if 'error' in result and 'result_html' not in result:
                return jsonify({'status': 'error', 'result_html': _format_result(result['error'])})
            return jsonify({'status': 'done', **result})
    except Exception:
        pass

    output = _run_launcher_command('backtest')
    return jsonify({'status': 'done', 'result_html': _format_result(output)})


@app.route('/api/operation/optimize', methods=['POST'])
def op_optimize():
    data = request.get_json() or {}
    strategy_key = data.get('strategy') or 'grid_strategy'

    try:
        from quant_env.strategies.registry import get_class, list_strategies
        from quant_env.backtest.data_loader import load_yfinance
        from quant_env.backtest.engine import BacktestEngine
        from quant_env.analysis.performance import compute_metrics
        import pandas as pd
        import itertools

        strategy_cls = get_class(strategy_key)
        if strategy_cls is not None:
            symbol   = data.get('symbol', 'GC=F')
            period   = data.get('period', '1mo')
            interval = data.get('interval', '1h')
            capital  = float(data.get('capital', 10000))

            # Build param_grid from the strategy's own PARAMS dict
            # Look up the strategy metadata to get parameter definitions
            all_strategies = list_strategies()
            meta = next((s for s in all_strategies if s['key'] == strategy_key), {})
            params_def = meta.get('params', {})

            # Build param_grid: each param can be swept over 3 values
            param_grid = {}
            for pname, pdef in params_def.items():
                default = pdef.get('default', 1)
                # Use request values if provided, otherwise generate 3 values around default
                req_vals = data.get(f'{pname}s') or data.get(pname)
                if req_vals is not None:
                    if isinstance(req_vals, str):
                        req_vals = [float(v) for v in req_vals.split(',') if v.strip()]
                    elif not isinstance(req_vals, list):
                        req_vals = [float(req_vals)]
                    param_grid[pname] = req_vals
                else:
                    # Auto-generate 3 values: default * 0.5, default, default * 1.5
                    base = float(default)
                    if isinstance(default, int) or pdef.get('type') == 'number' and pdef.get('step', 1) >= 1:
                        vals = [int(base * 0.5) or 1, int(base), int(base * 1.5)]
                    else:
                        vals = [round(base * 0.5, 4), base, round(base * 1.5, 4)]
                    param_grid[pname] = vals

            if not param_grid:
                return jsonify({'status': 'error', 'message': 'No sweepable parameters defined for this strategy.'})

            hist_data = load_yfinance(symbol, period=period, interval=interval)
            keys = list(param_grid.keys())
            results = []
            for combo in itertools.product(*param_grid.values()):
                params = dict(zip(keys, combo))
                # Convert numeric types appropriately
                engine_params = {}
                for k, v in params.items():
                    pdef = params_def.get(k, {})
                    if pdef.get('type') == 'number' and pdef.get('step', 1) >= 1:
                        engine_params[k] = int(v) if not isinstance(v, int) else v
                    else:
                        engine_params[k] = float(v)
                try:
                    engine = BacktestEngine(
                        hist_data.copy(), strategy_cls, capital, **engine_params
                    )
                    res = engine.run()
                    m = compute_metrics(res.fills_df, res.equity_df)
                    m.update(engine_params)
                    results.append(m)
                except Exception:
                    pass

            if results:
                df = pd.DataFrame(results).sort_values('sharpe_ratio', ascending=False)
                best = df.iloc[0].to_dict()
                _update_strategy_result(strategy_key, 'optimize', best)

                lines = [f"Optimization — {getattr(strategy_cls, 'STRATEGY_NAME', strategy_key)}", "=" * 40]
                for _, r in df.iterrows():
                    param_str = '  '.join(f"{k}={r[k]}" for k in keys)
                    lines.append(f"  {param_str}  sharpe={r['sharpe_ratio']:.2f}  return={r['total_return_pct']:.2f}%  dd={r['max_drawdown_pct']:.2f}%")
                lines.append("=" * 40)
                best_param_str = '  '.join(f"{k}={best[k]}" for k in keys)
                lines.append(f"Best: {best_param_str}  sharpe={best['sharpe_ratio']:.2f}")
                return jsonify({'status': 'done', 'result_html': _format_result('\n'.join(lines)), 'best': best})
    except Exception as e:
        pass

    output = _run_launcher_command('optimize')
    return jsonify({'status': 'done', 'result_html': _format_result(output)})


@app.route('/api/operation/report', methods=['POST'])
def op_report():
    output = _run_launcher_command('report')
    return jsonify({
        'status': 'done',
        'result_html': _format_result(output),
    })


@app.route('/api/operation/walkforward', methods=['POST'])
def op_walkforward():
    data = request.get_json() or {}
    strategy_key = data.get('strategy') or 'grid_strategy'

    try:
        from quant_env.strategies.registry import get_class, list_strategies
        from quant_env.backtest.data_loader import load_yfinance
        from quant_env.analysis.walkforward import walkforward_analysis

        strategy_cls = get_class(strategy_key)
        if strategy_cls is not None:
            symbol   = data.get('symbol', 'GC=F')
            period   = data.get('period', '3mo')
            interval = data.get('interval', '1h')
            capital  = float(data.get('capital', 10000))
            window   = int(data.get('window', 500))
            step     = int(data.get('step', 500))

            # Build param_grid from the strategy's own PARAMS dict
            all_strategies = list_strategies()
            meta = next((s for s in all_strategies if s['key'] == strategy_key), {})
            params_def = meta.get('params', {})

            param_grid = {}
            for pname, pdef in params_def.items():
                default = pdef.get('default', 1)
                req_vals = data.get(f'{pname}s') or data.get(pname)
                if req_vals is not None:
                    if isinstance(req_vals, str):
                        req_vals = [float(v) for v in req_vals.split(',') if v.strip()]
                    elif not isinstance(req_vals, list):
                        req_vals = [float(req_vals)]
                    param_grid[pname] = req_vals
                else:
                    # Auto-generate 2 values: default, default * 1.5
                    base = float(default)
                    if isinstance(default, int) or pdef.get('type') == 'number' and pdef.get('step', 1) >= 1:
                        vals = [int(base), int(base * 1.5)]
                    else:
                        vals = [base, round(base * 1.5, 4)]
                    param_grid[pname] = vals

            if not param_grid:
                return jsonify({'status': 'error', 'message': 'No sweepable parameters defined for this strategy.'})

            hist_data = load_yfinance(symbol, period=period, interval=interval)
            wf_df = walkforward_analysis(
                hist_data, strategy_cls, param_grid,
                window_size=window, step_size=step,
                initial_capital=capital
            )
            summary = wf_df.to_dict(orient='records') if not wf_df.empty else []
            if summary:
                _update_strategy_result(strategy_key, 'walkforward', {'windows': len(summary)})

            lines = [f"Walk-Forward — {getattr(strategy_cls, 'STRATEGY_NAME', strategy_key)}", "=" * 40]
            for row in summary:
                lines.append(str(row))
            return jsonify({'status': 'done', 'result_html': _format_result('\n'.join(lines))})
    except Exception as e:
        pass

    output = _run_launcher_command('walkforward')
    return jsonify({'status': 'done', 'result_html': _format_result(output)})


@app.route('/api/operation/train_ml', methods=['POST'])
def op_train_ml():
    data = request.get_json() or {}
    strategy_key = data.get('strategy')

    output = _run_launcher_command('train_ml')

    if strategy_key:
        _update_strategy_result(strategy_key, 'train_ml', {
            'trained_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'output_summary': output[:500],
        })

    return jsonify({
        'status': 'done',
        'result_html': _format_result(output),
    })


@app.route('/api/operation/benchmark_all', methods=['POST'])
def op_benchmark_all():
    """Run backtest for ALL discovered strategies and return comparison."""
    data = request.get_json() or {}
    symbol   = data.get('symbol', 'GC=F')
    period   = data.get('period', '1mo')
    interval = data.get('interval', '1h')
    capital  = float(data.get('capital', 10000))

    try:
        from quant_env.strategies.registry import list_strategies
        strategies = list_strategies()
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

    comparison = []
    for s in strategies:
        key = s['key']
        params = {'symbol': symbol, 'period': period, 'interval': interval, 'capital': capital}
        for pname, pdef in s.get('params', {}).items():
            params[pname] = pdef.get('default', 1.0)

        result = _run_backtest_for_strategy(key, params)
        metrics = result.get('metrics', {})
        comparison.append({
            'key': key,
            'name': s['name'],
            'total_return_pct': metrics.get('total_return_pct', 0),
            'sharpe_ratio': metrics.get('sharpe_ratio', 0),
            'win_rate_pct': metrics.get('win_rate_pct', 0),
            'profit_factor': metrics.get('profit_factor', 0),
            'max_drawdown_pct': metrics.get('max_drawdown_pct', 0),
            'num_trades': metrics.get('num_trades', 0),
            'error': result.get('error'),
        })

    return jsonify({'status': 'done', 'comparison': comparison})


# ═══════════════════════════════════════════════════════════════════════
#  ANALYTICS API — structured JSON for the Next.js Intelligence page
#  Serves the real artifacts produced by the engine:
#    strategy_results.json · optimization_results.csv · walkforward_*.csv
#    ml/model_metrics.json · gold_data.csv · live trade DBs
# ═══════════════════════════════════════════════════════════════════════

import csv as _csv


def _read_csv_rows(path, limit=20000):
    """Read a CSV into a list of dicts (string values preserved)."""
    if not os.path.exists(str(path)):
        return []
    try:
        with open(str(path), newline='', encoding='utf-8') as f:
            rows = list(_csv.DictReader(f))
        return rows[:limit]
    except Exception as e:
        print(f"[Analytics] CSV read failed {path}: {e}")
        return []


def _num(value, default=0.0):
    """Best-effort numeric cast (handles None / empty / weird strings)."""
    try:
        if value is None:
            return default
        s = str(value).strip()
        if not s:
            return default
        return float(s)
    except (ValueError, TypeError):
        return default


def _load_live_engine_data():
    """
    Load the legacy engine trade DB (the one with real fills) plus the
    per-account DBs, deduplicated.  Returns { fills, equity, trades, metrics }.
    Realized PnL is computed on the fly with the FIFO trade matcher because
    fills are logged without a pnl value.
    """
    import pandas as pd
    import sqlite3
    from quant_env.analysis.trade_matcher import match_trades
    from quant_env.analysis.performance import compute_metrics

    candidates = [
        PROJECT_ROOT / "quant_env" / "trades.db",   # legacy single-file DB
        PROJECT_ROOT / "trades.db",                 # root-level copy
    ]
    fill_rows = []
    seen = set()
    for db_path in candidates:
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(str(db_path), timeout=5.0)
            rows = conn.execute(
                "SELECT timestamp, symbol, side, price, volume, pnl FROM fills ORDER BY timestamp"
            ).fetchall()
            conn.close()
            for ts, sym, side, price, vol, pnl in rows:
                key = (ts, sym, side, float(price or 0), float(vol or 0))
                if key in seen:
                    continue
                seen.add(key)
                fill_rows.append({
                    "timestamp": ts, "symbol": sym, "side": side,
                    "price": float(price or 0), "volume": float(vol or 0),
                    "pnl": float(pnl or 0),
                })
        except Exception as e:
            print(f"[Analytics] Could not read {db_path}: {e}")

    equity_rows = []
    for db_path in candidates:
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(str(db_path), timeout=5.0)
            rows = conn.execute(
                "SELECT timestamp, equity, balance FROM equity_snapshots ORDER BY timestamp"
            ).fetchall()
            conn.close()
            for ts, eq, bal in rows:
                equity_rows.append({"timestamp": ts, "equity": float(eq or 0), "balance": float(bal or 0)})
            if equity_rows:
                break  # first DB that has equity wins
        except Exception:
            continue

    result = {"fills": fill_rows, "equity": equity_rows, "trades": [], "metrics": None}
    if fill_rows:
        try:
            fills_df = pd.DataFrame(fill_rows)
            trades_df = match_trades(fills_df)
            if not trades_df.empty:
                result["trades"] = trades_df.to_dict(orient="records")
                eq_series = [e["equity"] for e in equity_rows] if equity_rows else []
                if len(eq_series) > 1:
                    import numpy as np
                    eq_idx = pd.date_range("2026-05-11", periods=len(eq_series), freq="h")
                    eq_df = pd.DataFrame({"timestamp": eq_idx, "equity": eq_series})
                else:
                    eq_df = pd.DataFrame({"timestamp": [], "equity": []})
                result["metrics"] = compute_metrics(fills_df, eq_df)
        except Exception as e:
            print(f"[Analytics] PnL matching failed: {e}")
    return result



@app.route('/api/analytics/overview')
def api_analytics_overview():
    """Top-level dashboard: strategy results, ML summary, live stats, flags."""
    strategy_results = _load_strategy_results()
    live = _load_live_engine_data()

    strategies = {}
    for key, ops in strategy_results.items():
        strategies[key] = {
            "name": key.replace("_", " ").title(),
            "backtest": (ops.get("backtest") or {}).get("metrics"),
            "optimize": (ops.get("optimize") or {}).get("metrics"),
            "walkforward": (ops.get("walkforward") or {}).get("metrics"),
            "train_ml": (ops.get("train_ml") or {}).get("metrics"),
        }

    return jsonify({
        "status": "ok",
        "strategies": strategies,
        "live": {
            "fill_count": len(live["fills"]),
            "trade_count": len(live["trades"]),
            "equity_points": len(live["equity"]),
            "first_fill": live["fills"][0]["timestamp"] if live["fills"] else None,
            "last_fill": live["fills"][-1]["timestamp"] if live["fills"] else None,
            "metrics": live["metrics"],
            "side_split": {
                "buy": sum(1 for f in live["fills"] if f["side"] == "buy"),
                "sell": sum(1 for f in live["fills"] if f["side"] == "sell"),
            },
        },
        "config": {
            "symbol": getattr(Config, "SYMBOL", "XAUUSD.r"),
            "yahoo_symbol": getattr(Config, "YAHOO_SYMBOL", "GC=F"),
            "ml_enabled": getattr(Config, "ML_ENABLED", False),
            "kronos_enabled": getattr(Config, "KRONOS_ENABLED", False),
            "kronos_blend_enabled": getattr(Config, "KRONOS_BLEND_ENABLED", False),
            "kronos_risk_metrics": getattr(Config, "KRONOS_RISK_METRICS_ENABLED", False),
            "kronos_symbols": getattr(Config, "KRONOS_SYMBOLS", ""),
            "kronos_model": getattr(Config, "KRONOS_MODEL", "NeoQuasar/Kronos-small"),
            "adaptive_enabled": getattr(Config, "ADAPTIVE_ENABLED", False),
        },
    })


@app.route('/api/analytics/optimization')
def api_analytics_optimization():
    """Grid-search optimization results + derived best params."""
    rows = _read_csv_rows(PROJECT_ROOT / "optimization_results.csv")
    parsed = []
    for r in rows:
        parsed.append({
            "spacing": _num(r.get("spacing")),
            "levels": _num(r.get("levels")),
            "total_return_pct": _num(r.get("total_return_pct")),
            "total_pnl": _num(r.get("total_pnl")),
            "sharpe_ratio": _num(r.get("sharpe_ratio")),
            "max_drawdown_pct": _num(r.get("max_drawdown_pct")),
            "num_trades": _num(r.get("num_trades")),
            "win_rate_pct": _num(r.get("win_rate_pct")),
            "profit_factor": _num(r.get("profit_factor")),
        })
    best = None
    if parsed:
        best = max(parsed, key=lambda p: p["sharpe_ratio"])
    return jsonify({"status": "ok", "rows": parsed, "best": best})


@app.route('/api/analytics/walkforward')
def api_analytics_walkforward():
    """Walk-forward analysis: per-window OOS results (both result files)."""
    primary = _read_csv_rows(PROJECT_ROOT / "walkforward_report.csv")
    secondary = _read_csv_rows(PROJECT_ROOT / "walkforward_results.csv")
    return jsonify({"status": "ok", "windows": primary, "raw": secondary})



@app.route('/api/analytics/ml')
def api_analytics_ml():
    """ML model metrics + feature importances."""
    path = PROJECT_ROOT / "quant_env" / "ml" / "model_metrics.json"
    model_metrics = {}
    if path.exists():
        try:
            with open(str(path)) as f:
                model_metrics = json.load(f)
        except Exception:
            pass
    return jsonify({
        "status": "ok",
        "model": model_metrics,
        "trained": model_metrics is not None and bool(model_metrics),
    })


@app.route('/api/analytics/equity')
def api_analytics_equity():
    """Price series (gold_data.csv, sampled) + live equity curve."""
    gold_rows = _read_csv_rows(PROJECT_ROOT / "gold_data.csv", limit=200000)
    sampled = []
    step = max(1, len(gold_rows) // 480)  # ~480 points max for the chart
    for i in range(0, len(gold_rows), step):
        r = gold_rows[i]
        sampled.append({
            "t": r.get("Datetime", ""),
            "close": _num(r.get("Close")),
            "high": _num(r.get("High")),
            "low": _num(r.get("Low")),
        })
    live = _load_live_engine_data()
    equity = []
    step_e = max(1, len(live["equity"]) // 480)
    for i in range(0, len(live["equity"]), step_e):
        equity.append(live["equity"][i])
    return jsonify({
        "status": "ok",
        "price": sampled,
        "live_equity": equity,
        "fills": live["fills"][-200:],
    })


@app.route('/api/analytics/live')
def api_analytics_live():
    """Realized PnL trades (FIFO) + fill activity series."""
    live = _load_live_engine_data()
    return jsonify({
        "status": "ok",
        "trades": live["trades"],
        "fills": live["fills"],
        "metrics": live["metrics"],
    })


# ── Entry point ────────────────────────────────────────────────────────
# ── Entry point ────────────────────────────────────────────────────────

def find_available_port(start=5050, max_attempts=100):
    """Find the next available port starting from `start`."""
    import socket
    for port in range(start, start + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('0.0.0.0', port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No available port found in range {start}-{start + max_attempts - 1}")


if __name__ == '__main__':
    port = find_available_port(5050)
    bridge_url = _get_bridge_url()
    print("=" * 50)
    print(f"  Dashboard:  http://localhost:{port}")
    print(f"  Bridge URL: {bridge_url}")
    print("  Bot starts paused — click 'Start' in the sidebar.")
    mgr = _get_manager()
    accounts = mgr.account_manager.list_accounts()
    print(f"  Accounts: {len(accounts)} configured")
    for acct in accounts:
        bot = mgr.get_bot(acct.id)
        status = "✅ connected" if (bot and bot.connected) else "⏹️ paused"
        print(f"    - {acct.label} ({acct.id[:8]}...) {status}")
    if not accounts:
        bridge_test = _try_bridge_status()
        if bridge_test:
            print(f"  ✅ Broker connected — balance: {bridge_test['balance']}")
        else:
            print("  ⚠️  Bridge not responding — demo data shown")
    print("=" * 50)
    try:
        import waitress
        waitress.serve(app, host='0.0.0.0', port=port)
    except ImportError:
        app.run(host='0.0.0.0', port=port, debug=False, threaded=False)