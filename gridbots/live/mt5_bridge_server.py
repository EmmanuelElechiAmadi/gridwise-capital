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
    """Strip broker suffix (e.g. XAUUSD.r -> XAUUSD) for MT5 compatibility."""
    return sym.split(".")[0]

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
        # Try stripping broker suffix (e.g. XAUUSD.r -> XAUUSD) or adding it
        sym_base = _mt5_symbol(sym)
        for tick in ticks:
            ts = tick.get("symbol", "")
            if ts == sym_base or ts.startswith(sym_base):
                return jsonify(tick)
        # Return first tick as fallback with a note
        first = ticks[0]
        first["_note"] = f"Symbol {sym} not found; returning {first.get('symbol')}"
        return jsonify(first)
    return jsonify({'error': 'no tick data'}), 503

@app.route('/place_limit_order', methods=['POST'])
def place_limit_order():
    if not MT5_FILES:
        return jsonify({'error': 'MT5 not connected'}), 503

    data = request.get_json()
    symbol = _mt5_symbol(data['symbol'])
    order_type = data['order_type']
    price = float(data['price'])
    volume = float(data['volume'])
    comment = data.get('comment', 'Bridge')

    cmd = {
        "action": "place_limit",
        "symbol": symbol,
        "type": order_type,
        "price": price,
        "volume": volume,
        "comment": comment,
        "magic": MAGIC
    }

    # Remove old result file
    delete_file("mt5_cmd_result.json")

    # Write command for EA to pick up
    if not write_json("mt5_cmd.json", cmd):
        return jsonify({'error': 'cannot write command file'}), 500

    # Wait for EA to process and write result
    for _ in range(30):  # 3 second timeout
        time.sleep(0.1)
        result = read_json("mt5_cmd_result.json")
        if result:
            delete_file("mt5_cmd_result.json")
            if result.get("retcode") == 10009:  # TRADE_RETCODE_DONE
                return jsonify({'ticket': result.get("ticket", 0), 'price': price, 'side': order_type})
            else:
                return jsonify({'error': result.get("comment", "unknown"), 'retcode': result.get("retcode")}), 400

    return jsonify({'error': 'timeout waiting for MT5 response'}), 504

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

@app.route('/close_positions', methods=['POST'])
def close_positions():
    if not MT5_FILES:
        return jsonify({'error': 'MT5 not connected'}), 503

    data = request.get_json()
    symbol = _mt5_symbol(data.get('symbol', 'XAUUSD'))

    cmd = {
        "action": "close_positions",
        "symbol": symbol,
        "magic": MAGIC
    }

    delete_file("mt5_cmd_result.json")

    if not write_json("mt5_cmd.json", cmd):
        return jsonify({'error': 'cannot write command file'}), 500

    for _ in range(30):
        time.sleep(0.1)
        result = read_json("mt5_cmd_result.json")
        if result:
            delete_file("mt5_cmd_result.json")
            return jsonify(result)

    return jsonify({'error': 'timeout waiting for MT5 response'}), 504

@app.route('/health')
def health():
    has_mt5 = MT5_FILES is not None
    has_account = read_json("mt5_account.json") is not None
    return jsonify({
        'mt5_files_dir': MT5_FILES,
        'ea_running': has_account,
        'mode': 'demo' if not has_mt5 else 'live'
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    print(f"🚀 Starting MT5 Bridge Server on port {port}")
    print(f"   Magic number: {MAGIC}")
    print(f"   Mode: {'LIVE (EA data)' if MT5_FILES else 'DEMO (no MT5 files)'}")
    app.run(host='0.0.0.0', port=port)