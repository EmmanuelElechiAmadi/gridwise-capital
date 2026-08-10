#!/usr/bin/env python3
"""
MT5 Bridge Server — Mac-compatible version
Reads JSON files written by mt5_bridge_ea.mq5 inside MT5.
No MetaTrader5 Python library needed.
"""
import json
import os
import time
import glob
from pathlib import Path
from flask import Flask, request, jsonify

app = Flask(__name__)
MAGIC = 123456

# ── Locate MT5 Files directory ──
def find_mt5_files_dir():
    """Search common locations for the MT5 Files folder."""
    home = str(Path.home())
    candidates = [
        # User-specified via environment variable (highest priority)
        os.environ.get("MT5_FILES_DIR", ""),
        # Native MT5 Mac app (net.metaquotes.wine.metatrader5)
        os.path.join(home, "Library", "Application Support", "net.metaquotes.wine.metatrader5", "drive_c", "Program Files", "MetaTrader 5", "MQL5", "Files"),
        # Standard MT5 on Mac (Wine/Crossover)
        os.path.join(home, "Library", "Application Support", "MetaTrader 5", "MQL5", "Files"),
        # Alternative paths
        os.path.join(home, "Library", "Application Support", "MetaTrader 5", "Bots", "Files"),
        os.path.join(home, "Library", "Containers", "com.metatrader.5", "Data", "MQL5", "Files"),
        # Crossover-specific
        os.path.join(home, "Library", "Application Support", "Crossover", "Bottles", "MetaTrader5", "drive_c", "Program Files", "MetaTrader 5", "MQL5", "Files"),
        # Wine-specific
        os.path.join(home, ".wine", "drive_c", "Program Files", "MetaTrader 5", "MQL5", "Files"),
    ]
    for path in candidates:
        if path and os.path.isdir(path):
            # Check if EA files exist
            if any(fname.startswith("mt5_") and fname.endswith(".json") for fname in os.listdir(path)):
                print(f"✅ Found MT5 Files directory: {path}")
                return path
            # Also accept if directory exists even without files yet (EA might not be running)
            print(f"⚠️  Found MT5 directory but no EA files yet: {path}")
            return path
    return None

MT5_FILES = find_mt5_files_dir()
if MT5_FILES:
    print(f"📁 MT5 data directory: {MT5_FILES}")
else:
    print("⚠️  MT5 Files directory not found. Running in DEMO mode.")
    print("   Set MT5_FILES_DIR env var or start mt5_bridge_ea.mq5 in MT5.")
    print("   The bridge will keep re-checking on each request — start MT5 anytime.")


def _ensure_mt5_files():
    """Re-locate the MT5 Files directory if it wasn't found at startup
    (e.g. MT5 was launched after the bridge)."""
    global MT5_FILES
    if MT5_FILES is None:
        MT5_FILES = find_mt5_files_dir()
        if MT5_FILES:
            print(f"🔄 MT5 Files directory found now: {MT5_FILES}")
    return MT5_FILES

# ── File path helpers ──
def mt5_path(filename):
    if MT5_FILES:
        return os.path.join(MT5_FILES, filename)
    return None

def read_json(filename):
    path = mt5_path(filename)
    if not path or not os.path.exists(path):
        return None
    # MT5 on Mac (native Wine app) writes files in UTF-16 LE with BOM (0xFF 0xFE).
    # Try UTF-16 first, then fall back to UTF-8.
    for enc in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            with open(path, "r", encoding=enc) as f:
                raw = f.read().strip()
            # Strip any stray null bytes / whitespace that Wine sometimes adds
            raw = raw.replace("\x00", "")
            # MT5 EA sometimes writes arrays starting with [, (leading comma) — fix it
            if raw.startswith("[,"):
                raw = "[" + raw[2:]
            return json.loads(raw)
        except (UnicodeDecodeError, UnicodeError):
            continue
        except (json.JSONDecodeError, IOError):
            return None
    return None

def write_json(filename, data):
    path = mt5_path(filename)
    if not path:
        return False
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        # Small delay after write to let Wine filesystem sync complete.
        # Without this, the EA may FileIsExist() == true but read a partial file.
        time.sleep(0.3)
        return True
    except IOError:
        return False

def delete_file(filename):
    path = mt5_path(filename)
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass

# ── Symbol helper ──
def _mt5_symbol(sym: str) -> str:
    """Return the symbol as-is. The EA writes full broker symbols (e.g. XAUUSD.r),
    and OrderSend requires the exact broker symbol — do NOT strip suffixes."""
    return sym


def _normalize_for_match(sym: str) -> str:
    """Strip common broker suffixes so XAUUSD.r / XAUUSD / XAUUSDm all match."""
    base = (sym or "").strip()
    for suffix in (".r", ".m", "-cash", ".i"):
        if base.lower().endswith(suffix):
            base = base[:-len(suffix)]
            break
    return base

# ── API Endpoints ──

@app.route('/account_info')
def account_info():
    data = read_json("mt5_account.json")
    if data:
        return jsonify(data)
    return jsonify({'error': 'no account data. Is MT5 running with the EA?'}), 503

@app.route('/symbol_tick')
def symbol_tick():
    sym = request.args.get('symbol') or "XAUUSD"
    ticks = read_json("mt5_tick.json")
    if ticks:
        # Try exact match first
        for tick in ticks:
            if tick.get("symbol") == sym:
                return jsonify(tick)
        # Try suffix-normalised match (XAUUSD.r <-> XAUUSD <-> XAUUSDm)
        want = _normalize_for_match(sym)
        for tick in ticks:
            ts = tick.get("symbol", "")
            if ts == sym or ts.startswith(want) or _normalize_for_match(ts) == want:
                return jsonify(tick)
        # Return first tick as fallback with a note
        first = ticks[0]
        first["_note"] = f"Symbol {sym} not found; returning {first.get('symbol')}"
        return jsonify(first)
    return jsonify({'error': 'no tick data'}), 503

@app.route('/place_limit_order', methods=['POST'])
def place_limit_order():
    if not _ensure_mt5_files():
        return jsonify({'error': 'MT5 not connected (no Files dir). Attach mt5_bridge_ea.mq5 or set MT5_FILES_DIR.'}), 503

    data = request.get_json()
    symbol = _mt5_symbol(data['symbol'])
    order_type = data['order_type']
    price = float(data['price'])
    volume = float(data['volume'])
    comment = data.get('comment', 'Bridge')

    cmd = {
        "action": "place_limit",
        "symbol": str(symbol),
        "type": str(order_type),
        "price": str(price),        # quoted strings — the EA parses these reliably
        "volume": str(volume),
        "comment": str(comment),
        "magic": str(MAGIC),
    }

    # Remove old result file
    delete_file("mt5_cmd_result.json")

    # Write command for EA to pick up
    if not write_json("mt5_cmd.json", cmd):
        return jsonify({'error': 'cannot write command file'}), 500
    print(f"🧾 CMD sent: {json.dumps(cmd)}")

    # Wait for EA to process and write result
    for _ in range(150):  # 15 second timeout (Wine filesystem sync can be slow)
        time.sleep(0.1)
        result = read_json("mt5_cmd_result.json")
        if result:
            retcode = result.get("retcode")
            if retcode == -1:
                # EA is still parsing (partial write / parse retry) — keep waiting
                continue
            delete_file("mt5_cmd_result.json")
            if retcode == 10009:  # TRADE_RETCODE_DONE
                return jsonify({
                    'ticket': result.get("ticket", 0),
                    'price': price,
                    'side': order_type,
                    'symbol': result.get("symbol", symbol),
                    'comment': result.get("comment", ""),
                })
            return jsonify({
                'error': result.get("comment", "unknown"),
                'retcode': retcode,
                'symbol': result.get("symbol", symbol),
            }), 400

    # Timeout — return diagnostics so the dashboard/terminal can explain why
    diag = {
        'cmd_file_exists': bool(MT5_FILES and os.path.exists(mt5_path("mt5_cmd.json"))),
        'result_file_exists': bool(MT5_FILES and os.path.exists(mt5_path("mt5_cmd_result.json"))),
        'cmd_content': None,
    }
    if MT5_FILES and os.path.exists(mt5_path("mt5_cmd.json")):
        try:
            with open(mt5_path("mt5_cmd.json"), encoding="utf-8") as f:
                diag['cmd_content'] = f.read()[:200]
        except Exception:
            diag['cmd_content'] = '<unreadable>'
    return jsonify({'error': 'timeout waiting for MT5 response', 'diag': diag}), 504

@app.route('/positions')
def positions():
    sym = request.args.get('symbol')
    if sym:
        sym = _mt5_symbol(sym)
    all_pos = read_json("mt5_positions.json") or []
    if sym:
        all_pos = [p for p in all_pos if p.get("symbol") == sym]
    # Filter by magic
    all_pos = [p for p in all_pos if p.get("magic") == MAGIC]
    return jsonify(all_pos)

@app.route('/open_orders')
def open_orders():
    sym = request.args.get('symbol')
    if sym:
        sym = _mt5_symbol(sym)
    all_orders = read_json("mt5_orders.json") or []
    if sym:
        all_orders = [o for o in all_orders if o.get("symbol") == sym]
    # Filter by magic
    all_orders = [o for o in all_orders if o.get("magic") == MAGIC]
    return jsonify(all_orders)

@app.route('/cancel_order', methods=['POST'])
def cancel_order():
    if not _ensure_mt5_files():
        return jsonify({'error': 'MT5 not connected (no Files dir). Attach mt5_bridge_ea.mq5 or set MT5_FILES_DIR.'}), 503

    data = request.get_json()
    symbol = _mt5_symbol(data.get('symbol', 'XAUUSD'))
    price_or_ticket = data.get('price_or_ticket')

    cmd = {
        "action": "cancel_order",
        "symbol": str(symbol),
        "price_or_ticket": str(price_or_ticket),
        "magic": str(MAGIC)
    }

    delete_file("mt5_cmd_result.json")

    if not write_json("mt5_cmd.json", cmd):
        return jsonify({'error': 'cannot write command file'}), 500

    for _ in range(150):
        time.sleep(0.1)
        result = read_json("mt5_cmd_result.json")
        if result:
            retcode = result.get("retcode")
            if retcode == -1:
                continue
            delete_file("mt5_cmd_result.json")
            if retcode == 10009:  # TRADE_RETCODE_DONE
                return jsonify({'success': True, 'ticket': result.get("ticket", 0), 'comment': result.get("comment", "")})
            return jsonify({'error': result.get("comment", "unknown"), 'retcode': retcode}), 400

    return jsonify({'error': 'timeout waiting for MT5 response'}), 504


@app.route('/close_positions', methods=['POST'])
def close_positions():
    if not _ensure_mt5_files():
        return jsonify({'error': 'MT5 not connected (no Files dir). Attach mt5_bridge_ea.mq5 or set MT5_FILES_DIR.'}), 503

    data = request.get_json()
    symbol = _mt5_symbol(data.get('symbol', 'XAUUSD'))

    cmd = {
        "action": "close_positions",
        "symbol": str(symbol),
        "magic": str(MAGIC)
    }

    delete_file("mt5_cmd_result.json")

    if not write_json("mt5_cmd.json", cmd):
        return jsonify({'error': 'cannot write command file'}), 500

    for _ in range(150):
        time.sleep(0.1)
        result = read_json("mt5_cmd_result.json")
        if result:
            retcode = result.get("retcode")
            if retcode == -1:
                continue
            delete_file("mt5_cmd_result.json")
            return jsonify(result)

    return jsonify({'error': 'timeout waiting for MT5 response'}), 504

@app.route('/health')
def health():
    mt5 = _ensure_mt5_files()
    has_mt5 = mt5 is not None
    has_account = read_json("mt5_account.json") is not None
    return jsonify({
        'mt5_files_dir': mt5,
        'ea_running': has_account,
        'mode': 'demo' if not has_mt5 else 'live'
    })


@app.route('/status')
def status():
    """Rich diagnostic status consumed by the dashboard (bridge mode, files)."""
    mt5 = _ensure_mt5_files()
    files = {}
    if mt5:
        for f in ("mt5_account.json", "mt5_tick.json", "mt5_positions.json", "mt5_orders.json"):
            files[f] = os.path.exists(mt5_path(f)) if mt5 else False
    return jsonify({
        'mode': 'live' if mt5 else 'demo',
        'mt5_files_dir': mt5,
        'ea_running': read_json("mt5_account.json") is not None,
        'files': files,
        'hint': (
            'OK' if mt5 else
            'MT5 Files dir not found. Attach mt5_bridge_ea.mq5 to a chart, '
            'enable Algo Trading, and ensure MT5_FILES_DIR in gridbots/.env is correct.'
        ),
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    print(f"🚀 Starting MT5 Bridge Server on port {port}")
    print(f"   Magic number: {MAGIC}")
    print(f"   Mode: {'LIVE (EA data)' if MT5_FILES else 'DEMO (no MT5 files)'}")
    app.run(host='0.0.0.0', port=port)