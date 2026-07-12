#!/usr/bin/env python3
"""
Quant Grid Bot – Complete Project Generator
Run this script on your Mac to create the full quant environment.
"""
import os

PROJECT_ROOT = "gridbots"

FILES = {
    "README.md": """# Quant Grid Bot – Professional Trading Platform

## Structure
- `live/` – bridge server, bridge client, simple grid bot
- `quant_env/` – core engine, strategies, analysis, ML, dashboard, backtest, optimization
- `backtest/` – standalone backtest files (yfinance)
- `docs/` – (placeholder)

## Quick Start
### Local Live Test (Mac + Windows VM)
1. On Windows VM, run `python live/mt5_bridge_server.py`
2. On Mac: `pip install -r quant_env/requirements.txt`
3. Edit `quant_env/config.py` → set `BRIDGE_URL` to VM IP
4. Launch dashboard: `python quant_env/dashboard/app.py`
   or headless: `python launcher.py live`
5. Open http://localhost:5050

### Production (Windows VPS)
Copy only `live/grid_bot.py` (or `quant_env/main.py`) to VPS, install `MetaTrader5`, run directly.

### Backtesting
`python launcher.py backtest`

### Optimization
`python launcher.py optimize`

### Full Analysis Report
`python launcher.py report`
""",

    "live/mt5_bridge_server.py": """import MetaTrader5 as mt5
from flask import Flask, request, jsonify

app = Flask(__name__)
MAGIC = 123456

if not mt5.initialize():
    raise RuntimeError("MT5 initialize() failed. Make sure MT5 is running and logged in.")
print("✅ Bridge server connected to MT5")

@app.route('/account_info')
def account_info():
    acc = mt5.account_info()
    if acc:
        return jsonify({'login': acc.login, 'balance': acc.balance, 'equity': acc.equity})
    return jsonify({'error': 'no account'}), 500

@app.route('/symbol_tick')
def symbol_tick():
    sym = request.args.get('symbol') or "XAUUSD"
    tick = mt5.symbol_info_tick(sym)
    if tick:
        return jsonify({'bid': tick.bid, 'ask': tick.ask})
    return jsonify({'error': f'Symbol {sym} not found'}), 404

@app.route('/place_limit_order', methods=['POST'])
def place_limit_order():
    data = request.get_json()
    symbol = data['symbol']
    order_type = data['order_type']
    price = float(data['price'])
    volume = float(data['volume'])
    comment = data.get('comment', 'Bridge')

    mt_type = mt5.ORDER_TYPE_BUY_LIMIT if order_type == 'buy_limit' else mt5.ORDER_TYPE_SELL_LIMIT
    req = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": symbol,
        "volume": volume,
        "type": mt_type,
        "price": price,
        "deviation": 5,
        "magic": MAGIC,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(req)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        return jsonify({'ticket': result.order, 'price': price, 'side': order_type})
    else:
        return jsonify({'error': result.comment, 'retcode': result.retcode}), 400

@app.route('/positions')
def positions():
    sym = request.args.get('symbol')
    pos = mt5.positions_get(symbol=sym, magic=MAGIC) if sym else mt5.positions_get(magic=MAGIC)
    out = []
    if pos:
        for p in pos:
            out.append({
                'ticket': p.ticket, 'symbol': p.symbol,
                'type': 'buy' if p.type == mt5.POSITION_TYPE_BUY else 'sell',
                'volume': p.volume, 'open_price': p.price_open
            })
    return jsonify(out)

@app.route('/open_orders')
def open_orders():
    sym = request.args.get('symbol')
    orders = mt5.orders_get(symbol=sym, magic=MAGIC) if sym else mt5.orders_get(magic=MAGIC)
    out = []
    if orders:
        for o in orders:
            out.append({
                'ticket': o.ticket, 'symbol': o.symbol,
                'type': 'buy_limit' if o.type == mt5.ORDER_TYPE_BUY_LIMIT else 'sell_limit',
                'volume': o.volume_initial, 'price': o.price_open
            })
    return jsonify(out)

@app.route('/close_positions', methods=['POST'])
def close_positions():
    data = request.get_json()
    symbol = data.get('symbol', 'XAUUSD')
    positions = mt5.positions_get(symbol=symbol, magic=MAGIC)
    closed = 0
    if positions:
        for pos in positions:
            order_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
            price = mt5.symbol_info_tick(symbol).bid if pos.type == mt5.POSITION_TYPE_BUY else mt5.symbol_info_tick(symbol).ask
            req = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": pos.volume,
                "type": order_type,
                "position": pos.ticket,
                "price": price,
                "deviation": 10,
                "magic": MAGIC,
                "comment": "GridBotClose",
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(req)
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                closed += 1
    orders = mt5.orders_get(symbol=symbol, magic=MAGIC)
    cancelled = 0
    if orders:
        for o in orders:
            mt5.order_close(o.ticket)
            cancelled += 1
    return jsonify({'closed_positions': closed, 'cancelled_orders': cancelled})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
""",

    "live/mt5_bridge.py": """import requests

class BridgeClient:
    def __init__(self, base_url):
        self.base_url = base_url

    def account_info(self):
        r = requests.get(f"{self.base_url}/account_info")
        if r.status_code == 200:
            data = r.json()
            class Account:
                pass
            acc = Account()
            acc.login = data.get('login')
            acc.balance = data.get('balance')
            acc.equity = data.get('equity')
            return acc
        return None

    def place_limit_order(self, symbol, order_type, price, volume, comment="BridgeBot"):
        payload = {
            "symbol": symbol,
            "order_type": order_type,
            "price": price,
            "volume": volume,
            "comment": comment
        }
        r = requests.post(f"{self.base_url}/place_limit_order", json=payload)
        if r.status_code == 200:
            result = r.json()
            print(f"✅ Placed {order_type} at {price}, ticket {result.get('ticket')}")
            return result.get('ticket')
        return None

    def get_positions(self, symbol=None):
        params = {'symbol': symbol} if symbol else {}
        r = requests.get(f"{self.base_url}/positions", params=params)
        return r.json() if r.status_code == 200 else []

    def get_open_orders(self, symbol=None):
        params = {'symbol': symbol} if symbol else {}
        r = requests.get(f"{self.base_url}/open_orders", params=params)
        return r.json() if r.status_code == 200 else []

    def close_positions(self, symbol):
        r = requests.post(f"{self.base_url}/close_positions", json={'symbol': symbol})
        return r.json() if r.status_code == 200 else None
""",

    "live/grid_bot.py": """#!/usr/bin/env python3
\"\"\"Simple grid bot – direct MT5 (Windows) or bridge (Mac).\"\"\"
import sys, os, time
from datetime import datetime

SYMBOL = "XAUUSD"
GRID_SPACING = 0.10
NUM_LEVELS = 5
TRADE_QTY = 0.01
POLL_INTERVAL = 1
MAGIC_NUMBER = 123456
BRIDGE_URL = "http://192.168.64.2:5000"

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
    print("✅ Direct MT5 mode")
except ImportError:
    MT5_AVAILABLE = False
    from mt5_bridge import BridgeClient
    bridge = BridgeClient(BRIDGE_URL)
    print("⚠️  Bridge mode")

class TradingAPI:
    def __init__(self):
        if MT5_AVAILABLE:
            if not mt5.initialize():
                raise RuntimeError("MT5 init failed")
        else:
            self.bridge = BridgeClient(BRIDGE_URL)

    def account_info(self):
        if MT5_AVAILABLE:
            return mt5.account_info()
        return self.bridge.account_info()

    def symbol_tick(self):
        if MT5_AVAILABLE:
            tick = mt5.symbol_info_tick(SYMBOL)
            return {'bid': tick.bid, 'ask': tick.ask} if tick else None
        import requests
        r = requests.get(f"{BRIDGE_URL}/symbol_tick", params={'symbol': SYMBOL})
        return r.json() if r.status_code == 200 else None

    def place_limit_order(self, order_type, price, volume):
        if MT5_AVAILABLE:
            mt_type = mt5.ORDER_TYPE_BUY_LIMIT if order_type == 'buy_limit' else mt5.ORDER_TYPE_SELL_LIMIT
            req = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": SYMBOL,
                "volume": volume,
                "type": mt_type,
                "price": price,
                "deviation": 5,
                "magic": MAGIC_NUMBER,
                "comment": "GridBot",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(req)
            return result.order if result.retcode == mt5.TRADE_RETCODE_DONE else None
        return self.bridge.place_limit_order(SYMBOL, order_type, price, volume)

    def get_open_orders(self):
        if MT5_AVAILABLE:
            orders = mt5.orders_get(symbol=SYMBOL, magic=MAGIC_NUMBER)
            return [{'price': o.price_open, 'type': 'buy_limit' if o.type == mt5.ORDER_TYPE_BUY_LIMIT else 'sell_limit'} for o in orders] if orders else []
        return self.bridge.get_open_orders(SYMBOL)

    def get_positions(self):
        if MT5_AVAILABLE:
            positions = mt5.positions_get(symbol=SYMBOL, magic=MAGIC_NUMBER)
            return [{'type': 'buy' if p.type == mt5.POSITION_TYPE_BUY else 'sell', 'volume': p.volume} for p in positions] if positions else []
        return self.bridge.get_positions(SYMBOL)

    def close_all(self):
        if MT5_AVAILABLE:
            for p in mt5.positions_get(symbol=SYMBOL, magic=MAGIC_NUMBER) or []:
                typ = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
                price = mt5.symbol_info_tick(SYMBOL).bid if p.type == mt5.POSITION_TYPE_BUY else mt5.symbol_info_tick(SYMBOL).ask
                mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": p.volume, "type": typ, "position": p.ticket, "price": price, "magic": MAGIC_NUMBER})
            for o in mt5.orders_get(symbol=SYMBOL, magic=MAGIC_NUMBER) or []:
                mt5.order_close(o.ticket)
        else:
            self.bridge.close_positions(SYMBOL)

def main():
    api = TradingAPI()
    tick = api.symbol_tick()
    mid = round((tick['bid'] + tick['ask']) / 2, 2)
    buy_levels = [round(mid - i*GRID_SPACING,2) for i in range(1,NUM_LEVELS+1)]
    sell_levels = [round(mid + i*GRID_SPACING,2) for i in range(1,NUM_LEVELS+1)]
    active = {}
    for p in buy_levels:
        if api.place_limit_order('buy_limit', p, TRADE_QTY): active[p] = 'buy'
    for p in sell_levels:
        if api.place_limit_order('sell_limit', p, TRADE_QTY): active[p] = 'sell'
    print("Grid active. Ctrl+C to stop.")
    while True:
        cur = api.get_open_orders()
        cur_prices = {o['price'] for o in cur}
        filled = set(active.keys()) - cur_prices
        for price in filled:
            side = active.pop(price)
            print(f"Fill: {side} at {price}")
            if side == 'buy':
                new = round(price+GRID_SPACING,2)
                if new in sell_levels and api.place_limit_order('sell_limit', new, TRADE_QTY):
                    active[new] = 'sell'
            else:
                new = round(price-GRID_SPACING,2)
                if new in buy_levels and api.place_limit_order('buy_limit', new, TRADE_QTY):
                    active[new] = 'buy'
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
""",

    "quant_env/config.py": """# Trading parameters
SYMBOL = "XAUUSD"
SYMBOLS = ["XAUUSD"]
LOT_SIZE = 0.01
MAGIC_NUMBER = 123456

GRID_SPACING = 0.10
GRID_SPACING_MULT = 1.0
NUM_LEVELS = 5

TAKE_PROFIT_DOLLARS = 3.0
STOP_LOSS_DOLLARS = 2.0
MAX_POSITION_OZ = 1.0
MAX_DRAWDOWN_PERCENT = 10.0

MODE = "bridge"
BRIDGE_URL = "http://192.168.64.2:5000"

TELEGRAM_TOKEN = ""
TELEGRAM_CHAT_ID = ""
""",

    "quant_env/requirements.txt": """yfinance
pandas
numpy
matplotlib
requests
flask
flask-socketio
eventlet
python-dotenv
plotly
jinja2
scikit-learn
joblib
""",

    "quant_env/main.py": """import time, signal, sys, os
sys.path.append(os.path.dirname(__file__))
from config import Config
from core.connector import Connector
from core.risk_manager import RiskManager
from core.logger import setup_logger
from strategies.grid_strategy import GridStrategy
from analysis.trade_logger import TradeLogger
from utils.notifications import TelegramNotifier
from utils.config_loader import load_config

class App:
    def __init__(self):
        self.config = Config
        self.log = setup_logger()
        self.connector = Connector(self.config)
        self.risk = RiskManager(self.config, self.log)
        self.logger = TradeLogger("quant_env/trades.db")
        self.strategy = GridStrategy(self.connector, self.config, self.log)
        self.strategy.logger = self.logger
        env = load_config()
        self.notifier = None
        if env.get('TELEGRAM_TOKEN'):
            self.notifier = TelegramNotifier(env['TELEGRAM_TOKEN'], env['TELEGRAM_CHAT_ID'])
        self.running = True
        signal.signal(signal.SIGINT, self.shutdown)

    def run(self):
        self.strategy.on_start()
        while self.running:
            tick = self.connector.symbol_tick()
            if tick:
                self.strategy.on_tick(tick)
            acc = self.connector.account_info()
            pos = self.connector.get_positions()
            net = sum(p['volume'] if p['type']=='buy' else -p['volume'] for p in pos)
            if acc:
                self.logger.log_equity(acc.equity, acc.balance, net, len(self.strategy.active_orders))
                action, value = self.risk.check(acc.equity, acc.balance, net)
                if action:
                    msg = f"Risk trigger: {action} {value}"
                    self.log.warning(msg)
                    if self.notifier:
                        self.notifier.send(msg)
                    self.connector.close_all_positions()
                    self.strategy.reset_grid()
            time.sleep(0.5)
        self.strategy.on_stop()
        self.connector.shutdown()
        self.logger.close()

    def shutdown(self, signum, frame):
        self.running = False

if __name__ == "__main__":
    App().run()
""",

    "quant_env/core/connector.py": """import sys, os, requests
sys.path.append(os.path.join(os.path.dirname(__file__), '../../live'))
from mt5_bridge import BridgeClient

class DummyAccount:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

class Connector:
    def __init__(self, config):
        self.config = config
        self.mode = config.MODE
        self.symbol = config.SYMBOL
        self.magic = config.MAGIC_NUMBER
        if self.mode == "direct":
            import MetaTrader5 as mt5
            self.mt5 = mt5
            if not self.mt5.initialize():
                raise RuntimeError("MT5 init failed")
        else:
            self.bridge = BridgeClient(config.BRIDGE_URL)

    def account_info(self):
        if self.mode == "direct":
            acc = self.mt5.account_info()
            return DummyAccount(login=acc.login, balance=acc.balance, equity=acc.equity)
        return self.bridge.account_info()

    def symbol_tick(self):
        if self.mode == "direct":
            tick = self.mt5.symbol_info_tick(self.symbol)
            return {'bid': tick.bid, 'ask': tick.ask} if tick else None
        r = requests.get(f"{self.bridge.base_url}/symbol_tick", params={'symbol': self.symbol})
        return r.json() if r.status_code == 200 else None

    def place_limit_order(self, order_type, price, volume, comment=""):
        if self.mode == "direct":
            mt5 = self.mt5
            mt_type = mt5.ORDER_TYPE_BUY_LIMIT if order_type == 'buy_limit' else mt5.ORDER_TYPE_SELL_LIMIT
            req = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": self.symbol,
                "volume": volume,
                "type": mt_type,
                "price": price,
                "deviation": 5,
                "magic": self.magic,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(req)
            return result.order if result.retcode == mt5.TRADE_RETCODE_DONE else None
        return self.bridge.place_limit_order(self.symbol, order_type, price, volume, comment)

    def close_all_positions(self):
        if self.mode == "direct":
            mt5 = self.mt5
            for p in mt5.positions_get(symbol=self.symbol, magic=self.magic) or []:
                typ = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
                price = mt5.symbol_info_tick(self.symbol).bid if p.type == mt5.POSITION_TYPE_BUY else mt5.symbol_info_tick(self.symbol).ask
                mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": p.volume, "type": typ, "position": p.ticket, "price": price, "magic": self.magic})
            for o in mt5.orders_get(symbol=self.symbol, magic=self.magic) or []:
                mt5.order_close(o.ticket)
        else:
            self.bridge.close_positions(self.symbol)

    def get_open_orders(self):
        if self.mode == "direct":
            orders = self.mt5.orders_get(symbol=self.symbol, magic=self.magic)
            return [{'price': o.price_open, 'type': 'buy_limit' if o.type == self.mt5.ORDER_TYPE_BUY_LIMIT else 'sell_limit'} for o in orders] if orders else []
        return self.bridge.get_open_orders(self.symbol)

    def get_positions(self):
        if self.mode == "direct":
            positions = self.mt5.positions_get(symbol=self.symbol, magic=self.magic)
            return [{'type': 'buy' if p.type == self.mt5.POSITION_TYPE_BUY else 'sell', 'volume': p.volume, 'open_price': p.price_open} for p in positions] if positions else []
        return self.bridge.get_positions(self.symbol)

    def shutdown(self):
        if self.mode == "direct":
            self.mt5.shutdown()
""",

    "quant_env/core/risk_manager.py": """class RiskManager:
    def __init__(self, config, logger):
        self.tp = config.TAKE_PROFIT_DOLLARS
        self.sl = config.STOP_LOSS_DOLLARS
        self.max_pos = config.MAX_POSITION_OZ
        self.max_dd_pct = config.MAX_DRAWDOWN_PERCENT
        self.peak_equity = 0
        self.log = logger

    def check(self, equity, balance, net_position):
        pnl = equity - balance
        if self.tp and pnl >= self.tp:
            return 'take_profit', pnl
        if self.sl and pnl <= -self.sl:
            return 'stop_loss', pnl
        if self.max_pos and abs(net_position) > self.max_pos:
            return 'max_position', net_position
        if equity > self.peak_equity:
            self.peak_equity = equity
        dd = (self.peak_equity - equity) / self.peak_equity * 100 if self.peak_equity > 0 else 0
        if self.max_dd_pct and dd > self.max_dd_pct:
            return 'max_drawdown', dd
        return None, None
""",

    "quant_env/core/logger.py": """import logging, sys

def setup_logger(name="QuantBot", level=logging.INFO):
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(level)
        ch = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter('[%(asctime)s] %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        logger.addHandler(ch)
    return logger
""",

    "quant_env/strategies/base_strategy.py": """class BaseStrategy:
    def __init__(self, connector, config, logger):
        self.connector = connector
        self.config = config
        self.symbol = config.SYMBOL
        self.log = logger

    def on_start(self): pass
    def on_tick(self, tick): return {}
    def on_fill(self, price, side): pass
    def on_stop(self): pass
""",

    "quant_env/strategies/grid_strategy.py": """from .base_strategy import BaseStrategy
import time

class GridStrategy(BaseStrategy):
    def __init__(self, connector, config, logger):
        super().__init__(connector, config, logger)
        self.spacing = config.GRID_SPACING
        self.levels = config.NUM_LEVELS
        self.lot = config.LOT_SIZE
        self.active_orders = {}
        self.buy_levels = []
        self.sell_levels = []
        self.last_status = 0
        self.logger = None  # set externally

    def on_start(self):
        tick = self.connector.symbol_tick()
        if not tick:
            raise RuntimeError("No tick data")
        mid = round((tick['bid'] + tick['ask']) / 2, 2)
        self.buy_levels = [round(mid - i * self.spacing, 2) for i in range(1, self.levels+1)]
        self.sell_levels = [round(mid + i * self.spacing, 2) for i in range(1, self.levels+1)]
        self.log.info(f"Grid levels: {sorted(self.buy_levels + self.sell_levels)}")
        for p in self.buy_levels:
            if self.connector.place_limit_order('buy_limit', p, self.lot):
                self.active_orders[p] = 'buy'
        for p in self.sell_levels:
            if self.connector.place_limit_order('sell_limit', p, self.lot):
                self.active_orders[p] = 'sell'
        self.log.info(f"Placed {len(self.active_orders)} orders")

    def on_tick(self, tick):
        cur = self.connector.get_open_orders()
        cur_prices = {o['price'] for o in cur}
        filled = set(self.active_orders.keys()) - cur_prices
        actions = {'filled': []}
        for price in filled:
            side = self.active_orders.pop(price)
            self.log.info(f"Fill: {side} at {price}")
            self.on_fill(price, side)
            if self.logger:
                self.logger.log_fill(self.symbol, side, price, self.lot)
            actions['filled'].append((price, side))
        if time.time() - self.last_status > 10:
            acc = self.connector.account_info()
            pos = self.connector.get_positions()
            net = sum(p['volume'] if p['type']=='buy' else -p['volume'] for p in pos)
            self.log.info(f"Balance: {acc.balance:.2f} Equity: {acc.equity:.2f} Net: {net:.2f}oz Orders: {len(self.active_orders)}")
            self.last_status = time.time()
        return actions

    def on_fill(self, price, side):
        if side == 'buy':
            new = round(price + self.spacing, 2)
            if new in self.sell_levels:
                if self.connector.place_limit_order('sell_limit', new, self.lot):
                    self.active_orders[new] = 'sell'
        else:
            new = round(price - self.spacing, 2)
            if new in self.buy_levels:
                if self.connector.place_limit_order('buy_limit', new, self.lot):
                    self.active_orders[new] = 'buy'

    def reset_grid(self):
        self.active_orders.clear()
        self.on_start()
""",

    "quant_env/analysis/trade_logger.py": """import sqlite3, os
from datetime import datetime

class TradeLogger:
    def __init__(self, db_path="trades.db"):
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else '.', exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self._create_tables()

    def _create_tables(self):
        self.conn.execute('''CREATE TABLE IF NOT EXISTS fills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, symbol TEXT, side TEXT,
            price REAL, volume REAL, pnl REAL DEFAULT 0)''')
        self.conn.execute('''CREATE TABLE IF NOT EXISTS equity_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, equity REAL, balance REAL,
            net_position REAL, open_orders INTEGER)''')
        self.conn.commit()

    def log_fill(self, symbol, side, price, volume, pnl=0):
        self.conn.execute(
            "INSERT INTO fills (timestamp, symbol, side, price, volume, pnl) VALUES (?,?,?,?,?,?)",
            (datetime.now().isoformat(), symbol, side, price, volume, pnl))
        self.conn.commit()

    def log_equity(self, equity, balance, net_position, open_orders):
        self.conn.execute(
            "INSERT INTO equity_snapshots (timestamp, equity, balance, net_position, open_orders) VALUES (?,?,?,?,?)",
            (datetime.now().isoformat(), equity, balance, net_position, open_orders))
        self.conn.commit()

    def get_fills(self, symbol=None):
        query = "SELECT * FROM fills"
        if symbol: query += f" WHERE symbol='{symbol}'"
        return self.conn.execute(query).fetchall()

    def get_equity_curve(self):
        return self.conn.execute("SELECT timestamp, equity FROM equity_snapshots ORDER BY timestamp").fetchall()

    def close(self):
        self.conn.close()
""",

    "quant_env/analysis/trade_matcher.py": """from collections import deque
import pandas as pd

def match_trades(fills_df):
    buys = fills_df[fills_df['side'] == 'buy'].copy()
    sells = fills_df[fills_df['side'] == 'sell'].copy()
    buys = buys.sort_values('timestamp').reset_index(drop=True)
    sells = sells.sort_values('timestamp').reset_index(drop=True)
    buy_queue = deque()
    trades = []
    for _, buy in buys.iterrows():
        buy_queue.append(buy)
    for _, sell in sells.iterrows():
        remaining_vol = sell.volume
        while remaining_vol > 0 and buy_queue:
            oldest = buy_queue[0]
            if oldest.volume <= remaining_vol:
                pnl = (sell.price - oldest.price) * oldest.volume
                trades.append({'entry_time': oldest.timestamp, 'exit_time': sell.timestamp,
                               'entry_price': oldest.price, 'exit_price': sell.price,
                               'volume': oldest.volume, 'pnl': pnl})
                remaining_vol -= oldest.volume
                buy_queue.popleft()
            else:
                pnl = (sell.price - oldest.price) * remaining_vol
                trades.append({'entry_time': oldest.timestamp, 'exit_time': sell.timestamp,
                               'entry_price': oldest.price, 'exit_price': sell.price,
                               'volume': remaining_vol, 'pnl': pnl})
                oldest.volume -= remaining_vol
                remaining_vol = 0
    return pd.DataFrame(trades)
""",

    "quant_env/analysis/performance.py": """import numpy as np
import pandas as pd
from .trade_matcher import match_trades

def compute_metrics(fills_df, equity_df):
    if fills_df.empty or equity_df.empty:
        return {}
    trades = match_trades(fills_df)
    equity = pd.to_numeric(equity_df['equity'])
    returns = equity.pct_change().dropna()
    total_return = (equity.iloc[-1] / equity.iloc[0] - 1) * 100
    sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() != 0 else 0
    peak = equity.cummax()
    dd = peak - equity
    max_dd_pct = (dd / peak).max() * 100
    wins = trades[trades['pnl'] > 0]
    losses = trades[trades['pnl'] <= 0]
    win_rate = (len(wins) / max(len(trades),1)) * 100
    total_wins = wins['pnl'].sum()
    total_losses = abs(losses['pnl'].sum()) if losses['pnl'].sum() != 0 else 0
    profit_factor = total_wins / total_losses if total_losses != 0 else float('inf')
    return {
        'total_return_pct': round(total_return, 2),
        'total_pnl': round(equity.iloc[-1] - equity.iloc[0], 2),
        'sharpe_ratio': round(sharpe, 2),
        'max_drawdown_pct': round(max_dd_pct, 2),
        'num_trades': len(trades),
        'win_rate_pct': round(win_rate, 2),
        'profit_factor': round(profit_factor, 2),
        'avg_win': round(wins['pnl'].mean(),2) if len(wins) else 0,
        'avg_loss': round(losses['pnl'].mean(),2) if len(losses) else 0,
    }
""",

    "quant_env/analysis/session_analyzer.py": """import pandas as pd
from .trade_matcher import match_trades

SESSIONS = {
    'Sydney': (22,7), 'Tokyo': (0,9), 'London': (7,16), 'New York': (12,21)
}

def classify_session(dt_utc):
    hour = dt_utc.hour
    active = []
    for name, (start,end) in SESSIONS.items():
        if start <= hour < end:
            active.append(name)
        elif start > end and (hour >= start or hour < end):
            active.append(name)
    return active if active else ['Off-hours']

def session_performance(fills_df, equity_df):
    trades = match_trades(fills_df)
    if trades.empty:
        return pd.DataFrame()
    trades['exit_time'] = pd.to_datetime(trades['exit_time'])
    trades['session'] = trades['exit_time'].apply(classify_session)
    exploded = trades.explode('session')
    return exploded.groupby('session').agg(
        num_trades=('pnl','count'),
        total_pnl=('pnl','sum'),
        avg_pnl=('pnl','mean'),
        total_volume=('volume','sum')
    ).reset_index()
""",

    "quant_env/analysis/monte_carlo.py": """import numpy as np
import plotly.graph_objects as go

def run_monte_carlo(trade_returns, num_sim=1000, horizon=252, initial=10000):
    if len(trade_returns)==0:
        return None, {}
    rets = np.array(trade_returns)
    curves = np.zeros((num_sim, horizon))
    for i in range(num_sim):
        sampled = np.random.choice(rets, size=horizon, replace=True)
        curves[i] = initial + np.cumsum(sampled)
    finals = curves[:,-1]
    stats = {
        'prob_profit': (finals > initial).mean()*100,
        'expected_equity': finals.mean(),
        'var_95': np.percentile(finals,5)-initial,
        'median_max_dd': np.median(np.max(np.maximum.accumulate(curves,axis=1)-curves, axis=1))
    }
    fig = go.Figure()
    for i in range(min(100,num_sim)):
        fig.add_trace(go.Scatter(x=np.arange(horizon), y=curves[i], mode='lines', line=dict(color='lightblue', width=0.5), showlegend=False))
    p95 = np.percentile(curves,95,axis=0)
    p5 = np.percentile(curves,5,axis=0)
    median = np.median(curves,axis=0)
    fig.add_trace(go.Scatter(x=np.arange(horizon), y=median, name='Median'))
    fig.add_trace(go.Scatter(x=np.arange(horizon), y=p95, name='95th'))
    fig.add_trace(go.Scatter(x=np.arange(horizon), y=p5, name='5th'))
    return fig, stats
""",

    "quant_env/analysis/report_generator.py": """import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime

def generate_report(equity_df, fills_df, metrics, session_stats, mc_fig=None, output_file="report.html"):
    equity_series = pd.Series(equity_df['equity'].values, index=pd.to_datetime(equity_df['timestamp']))
    peak = equity_series.cummax()
    dd = peak - equity_series
    fig1 = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05)
    fig1.add_trace(go.Scatter(x=equity_series.index, y=equity_series, name='Equity'), row=1, col=1)
    fig1.add_trace(go.Scatter(x=dd.index, y=-dd, fill='tozeroy', name='Drawdown'), row=2, col=1)
    plot_div = fig1.to_html(full_html=False)
    mc_div = mc_fig.to_html(full_html=False) if mc_fig else ""
    html = f'''<html><head><title>Report {datetime.now().date()}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script></head>
    <body class="container"><h1>Quant Grid Bot Report</h1>
    <h3>Metrics</h3>{pd.DataFrame([metrics]).to_html(classes='table')}
    <h3>Equity & Drawdown</h3>{plot_div}
    <h3>Session Stats</h3>{session_stats.to_html(classes='table') if not session_stats.empty else 'N/A'}
    <h3>Monte Carlo</h3>{mc_div}
    </body></html>'''
    with open(output_file, 'w') as f: f.write(html)
""",

    "quant_env/backtest/data_loader.py": """import yfinance as yf
import pandas as pd

def load_yfinance(symbol="GC=F", period="5d", interval="1m"):
    df = yf.download(symbol, period=period, interval=interval, progress=False)
    if df.empty: raise ValueError("No data")
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
    df.index = pd.to_datetime(df.index)
    if df.index.tz: df.index = df.index.tz_convert('UTC')
    else: df.index = df.index.tz_localize('UTC')
    df.rename(columns={'Open':'open','High':'high','Low':'low','Close':'close','Volume':'volume'}, inplace=True)
    return df
""",

    "quant_env/backtest/engine.py": """import pandas as pd
from datetime import datetime

class BacktestResult:
    def __init__(self):
        self.fills = []
        self.equity = []
        self.fills_df = None
        self.equity_df = None

class BacktestEngine:
    def __init__(self, data, strategy_class, initial_cash=10000, slippage=0.1, spread=0.3, **strategy_kwargs):
        self.data = data
        self.strategy_class = strategy_class
        self.cash = initial_cash
        self.inventory = 0.0
        self.result = BacktestResult()
        self.active_orders = {}
        self.slippage = slippage
        self.spread = spread
        self.kwargs = strategy_kwargs

    def run(self):
        from quant_env.strategies.grid_strategy import GridStrategy
        mock_con = MockConnector(self)
        strat = self.strategy_class(mock_con, mock_con.config, mock_con.logger)
        strat.on_start()
        for idx, bar in self.data.iterrows():
            high, low, close = bar['high'], bar['low'], bar['close']
            filled = []
            for price, side in list(self.active_orders.items()):
                if low <= price <= high:
                    filled.append((price, side))
            for price, side in filled:
                del self.active_orders[price]
                fill_price = price + (self.slippage + self.spread/2) if side=='buy' else price - (self.slippage + self.spread/2)
                if side == 'buy':
                    self.cash -= fill_price * strat.lot
                    self.inventory += strat.lot
                else:
                    self.cash += fill_price * strat.lot
                    self.inventory -= strat.lot
                self.result.fills.append({'timestamp': idx, 'side': side, 'price': fill_price, 'volume': strat.lot})
            eq = self.cash + self.inventory * close
            self.result.equity.append((idx, eq))
        self.result.fills_df = pd.DataFrame(self.result.fills)
        self.result.equity_df = pd.DataFrame(self.result.equity, columns=['timestamp','equity'])
        return self.result

class MockConnector:
    def __init__(self, engine):
        self.engine = engine
        self.config = type('obj',(),{'SYMBOL':'BACKTEST','LOT_SIZE':engine.kwargs.get('lot',0.01),
            'GRID_SPACING':engine.kwargs.get('spacing',0.1),'NUM_LEVELS':engine.kwargs.get('levels',5)})
        self.logger = type('obj',(),{'info':print})
    def symbol_tick(self): return None
    def place_limit_order(self, order_type, price, volume):
        side = 'buy' if 'buy' in order_type else 'sell'
        self.engine.active_orders[price] = side
        return True
    def get_open_orders(self): return []
""",

    "quant_env/backtest/optimizer.py": """import itertools
from .engine import BacktestEngine
from quant_env.analysis.performance import compute_metrics
import pandas as pd

def optimize(data, strategy_class, param_grid, capital=10000):
    keys = list(param_grid.keys())
    results = []
    for combo in itertools.product(*param_grid.values()):
        params = dict(zip(keys, combo))
        engine = BacktestEngine(data.copy(), strategy_class, capital, **params)
        res = engine.run()
        metrics = compute_metrics(res.fills_df, res.equity_df)
        metrics.update(params)
        results.append(metrics)
    return pd.DataFrame(results).sort_values('sharpe_ratio', ascending=False)
""",

    "quant_env/backtest/sensitivity.py": """import pandas as pd
from .engine import BacktestEngine
from quant_env.analysis.performance import compute_metrics
import plotly.graph_objects as go

def sensitivity(data, strategy_class, param_name, param_values, fixed_kwargs, metric='sharpe_ratio', capital=10000):
    results = []
    for val in param_values:
        kwargs = {**fixed_kwargs, param_name: val}
        engine = BacktestEngine(data.copy(), strategy_class, capital, **kwargs)
        res = engine.run()
        metrics = compute_metrics(res.fills_df, res.equity_df)
        metrics[param_name] = val
        results.append(metrics)
    df = pd.DataFrame(results)
    fig = go.Figure(go.Scatter(x=df[param_name], y=df[metric], mode='lines+markers'))
    fig.update_layout(title=f'{metric} vs {param_name}')
    return df, fig
""",

    "quant_env/ml/data_builder.py": """import pandas as pd
import numpy as np

def build_features(df, lookback=20, adx_threshold=25):
    def compute_adx(high, low, close, period=14):
        tr = pd.DataFrame({'h-l':high-low, 'h-pc':(high-close.shift(1)).abs(),'l-pc':(low-close.shift(1)).abs()}).max(axis=1)
        atr = tr.ewm(alpha=1/period, adjust=False).mean()
        up = high.diff(); down = -low.diff()
        plus_dm = np.where((up>down)&(up>0), up, 0.0)
        minus_dm = np.where((down>up)&(down>0), down, 0.0)
        plus_di = 100 * pd.Series(plus_dm).ewm(alpha=1/period, adjust=False).mean() / atr
        minus_di = 100 * pd.Series(minus_dm).ewm(alpha=1/period, adjust=False).mean() / atr
        dx = (abs(plus_di-minus_di)/(plus_di+minus_di)*100).fillna(0)
        return dx.ewm(alpha=1/period, adjust=False).mean()
    df['adx'] = compute_adx(df['high'], df['low'], df['close'], 14)
    df['returns'] = df['close'].pct_change()
    df['volatility'] = df['returns'].rolling(lookback).std()
    df['volume_ratio'] = df['volume'] / df['volume'].rolling(lookback).mean()
    df['high_low_ratio'] = (df['high']-df['low'])/df['close']
    df['target'] = (df['adx'].shift(-1) > adx_threshold).astype(int)
    features = ['volatility','volume_ratio','high_low_ratio','returns']
    for lag in range(1,6):
        for f in ['returns','volatility']:
            df[f'{f}_lag{lag}'] = df[f].shift(lag)
            features.append(f'{f}_lag{lag}')
    df.dropna(inplace=True)
    return df[features], df['target']
""",

    "quant_env/ml/regime_model.py": """import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
import joblib

class RegimeClassifier:
    def __init__(self, lookback=20, threshold=25):
        self.lookback = lookback
        self.threshold = threshold
        self.model = None

    def train(self, df):
        from .data_builder import build_features
        X, y = build_features(df, self.lookback, self.threshold)
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
        self.model = RandomForestClassifier(n_estimators=100, max_depth=5)
        self.model.fit(X_train, y_train)
        self.features = X.columns.tolist()
        print(f"Regime model accuracy: {self.model.score(X_test,y_test):.2f}")

    def save(self, path='quant_env/ml/model.pkl'):
        joblib.dump({'model':self.model,'features':self.features,'lookback':self.lookback,'threshold':self.threshold}, path)

    @classmethod
    def load(cls, path='quant_env/ml/model.pkl'):
        data = joblib.load(path)
        obj = cls(data['lookback'], data['threshold'])
        obj.model = data['model']; obj.features = data['features']
        return obj
""",

    "quant_env/optimization/portfolio_optimizer.py": """import numpy as np
from collections import deque

class KellyPortfolio:
    def __init__(self, strategies, window=30, max_total_risk=0.1):
        self.strategies = strategies
        self.trade_logs = {s:deque(maxlen=window) for s in strategies}
        self.max_total_risk = max_total_risk

    def add_trade(self, strategy, pnl):
        self.trade_logs[strategy].append(pnl)

    def compute_allocations(self, total_equity):
        kellys = {}
        for s in self.strategies:
            trades = list(self.trade_logs[s])
            if len(trades)<5: kellys[s]=0; continue
            wins = [t for t in trades if t>0]
            losses = [t for t in trades if t<=0]
            if not losses:
                k = min(0.2, len(wins)/len(trades)*0.5)
            else:
                wr = len(wins)/len(trades)
                r = np.mean(wins)/abs(np.mean(losses)) if abs(np.mean(losses))!=0 else 0
                k = wr - (1-wr)/r if r!=0 else 0
            kellys[s] = max(0, min(k, 0.25))
        total_k = sum(kellys.values())
        if total_k==0: return {s:0 for s in self.strategies}
        return {s: (kellys[s]/total_k)*self.max_total_risk*total_equity for s in self.strategies}
""",

    "quant_env/optimization/genetic_optimizer.py": """import random
import numpy as np
from copy import deepcopy
from quant_env.backtest.engine import BacktestEngine
from quant_env.analysis.performance import compute_metrics

class GeneticOptimizer:
    def __init__(self, data, strategy_class, param_space, pop_size=50, gens=10, mut_rate=0.2, capital=10000):
        self.data = data
        self.strategy_class = strategy_class
        self.param_space = param_space
        self.pop_size = pop_size
        self.generations = gens
        self.mut_rate = mut_rate
        self.capital = capital

    def _random_params(self):
        params = {}
        for p, (low,high,step) in self.param_space.items():
            if isinstance(step, int) or step == int(step):
                params[p] = random.randint(low, high)
            else:
                values = np.arange(low, high+step, step)
                params[p] = random.choice(values)
        return params

    def _fitness(self, params):
        eng = BacktestEngine(self.data.copy(), self.strategy_class, self.capital, **params)
        res = eng.run()
        return compute_metrics(res.fills_df, res.equity_df).get('sharpe_ratio', -999)

    def _crossover(self, p1, p2):
        child = {}
        for k in p1:
            child[k] = p1[k] if random.random()<0.5 else p2[k]
        return child

    def _mutate(self, ind):
        for p, (low,high,step) in self.param_space.items():
            if random.random() < self.mut_rate:
                if isinstance(step, int) or step == int(step):
                    ind[p] = random.randint(low, high)
                else:
                    ind[p] = random.choice(np.arange(low, high+step, step))
        return ind

    def run(self):
        pop = [self._random_params() for _ in range(self.pop_size)]
        best_fit = -np.inf
        best_params = None
        for gen in range(self.generations):
            fits = [self._fitness(ind) for ind in pop]
            max_fit, idx = max((f,i) for i,f in enumerate(fits))
            if max_fit > best_fit:
                best_fit = max_fit; best_params = deepcopy(pop[idx])
            print(f"Gen {gen}: best {max_fit:.3f} params {pop[idx]}")
            new_pop = []
            for _ in range(self.pop_size):
                a,b = random.sample(range(self.pop_size),2)
                p1 = pop[a] if fits[a]>fits[b] else pop[b]
                c,d = random.sample(range(self.pop_size),2)
                p2 = pop[c] if fits[c]>fits[d] else pop[d]
                child = self._crossover(p1,p2) if random.random()<0.7 else deepcopy(p1)
                child = self._mutate(child)
                new_pop.append(child)
            pop = new_pop
        return best_params, best_fit
""",

    "quant_env/dashboard/app.py": """from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO, emit
import eventlet; eventlet.monkey_patch()
import threading, time, sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))
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
socketio = SocketIO(app, async_mode='eventlet')

config = Config
log = setup_logger()
connector = Connector(config)
risk = RiskManager(config, log)
logger = TradeLogger("quant_env/trades.db")
strategy = GridStrategy(connector, config, log)
strategy.logger = logger

def trading_loop():
    strategy.on_start()
    while True:
        tick = connector.symbol_tick()
        if tick:
            strategy.on_tick(tick)
        acc = connector.account_info()
        pos = connector.get_positions()
        net = sum(p['volume'] if p['type']=='buy' else -p['volume'] for p in pos)
        if acc:
            logger.log_equity(acc.equity, acc.balance, net, len(strategy.active_orders))
            pnl = acc.equity - acc.balance
            socketio.emit('update', {'balance':acc.balance,'equity':acc.equity,'pnl':pnl,'net_position':net,'num_orders':len(strategy.active_orders)})
            action, val = risk.check(acc.equity, acc.balance, net)
            if action:
                log.warning(f"Risk: {action} {val}")
                connector.close_all_positions()
                strategy.reset_grid()
        time.sleep(1)

@app.route('/')
def index(): return render_template('dashboard.html')

@app.route('/equity_chart')
def equity_chart():
    rows = logger.get_equity_curve()
    return jsonify([{'x':t,'y':e} for t,e in rows])

@app.route('/session_stats')
def session_stats():
    fills = logger.get_fills()
    if not fills: return jsonify([])
    fills_df = pd.DataFrame(fills, columns=['id','timestamp','symbol','side','price','volume','pnl'])
    equity_df = pd.DataFrame(logger.get_equity_curve(), columns=['timestamp','equity'])
    stats = session_performance(fills_df, equity_df)
    return jsonify(stats.to_dict(orient='records'))

if __name__ == '__main__':
    threading.Thread(target=trading_loop, daemon=True).start()
    socketio.run(app, host='0.0.0.0', port=5050, debug=False)
""",

    "quant_env/dashboard/templates/dashboard.html": """<!DOCTYPE html>
<html>
<head>
    <title>Quant Grid Dashboard</title>
    <script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
    <script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
    <style>
        body { font-family: Arial; margin: 20px; background: #f5f5f5; }
        .metrics { display: flex; gap: 15px; }
        .metric { background: white; padding: 20px; border-radius: 8px; min-width: 150px; }
        .value { font-size: 24px; font-weight: bold; }
        .chart-container { width: 100%; margin-top: 20px; }
    </style>
</head>
<body>
    <h1>⚡ Grid Bot Dashboard</h1>
    <div class="metrics">
        <div class="metric">Balance <div class="value" id="balance">0</div></div>
        <div class="metric">Equity <div class="value" id="equity">0</div></div>
        <div class="metric">P&L <div class="value" id="pnl">0</div></div>
        <div class="metric">Net Pos (oz) <div class="value" id="net">0</div></div>
        <div class="metric">Orders <div class="value" id="orders">0</div></div>
    </div>
    <div class="chart-container" id="equityChart"></div>
    <div id="sessionTable"></div>
    <script>
        const socket = io();
        socket.on('update', (data) => {
            document.getElementById('balance').innerText = '$'+data.balance.toFixed(2);
            document.getElementById('equity').innerText = '$'+data.equity.toFixed(2);
            document.getElementById('pnl').innerText = '$'+data.pnl.toFixed(2);
            document.getElementById('net').innerText = data.net_position.toFixed(2);
            document.getElementById('orders').innerText = data.num_orders;
        });
        function fetchEquity() {
            fetch('/equity_chart').then(r=>r.json()).then(d=>{
                Plotly.newPlot('equityChart', [{x:d.map(p=>p.x), y:d.map(p=>p.y), type:'scatter', mode:'lines', name:'Equity'}], {title:'Equity Curve'});
            });
        }
        function fetchSessions() {
            fetch('/session_stats').then(r=>r.json()).then(d=>{
                let html = '<h3>Session Performance</h3><table border=1>';
                if(d.length>0){ html += '<tr>'+Object.keys(d[0]).map(k=>`<th>${k}</th>`).join('')+'</tr>'; }
                d.forEach(r=>{ html += '<tr>'+Object.values(r).map(v=>`<td>${v}</td>`).join('')+'</tr>'; });
                html += '</table>';
                document.getElementById('sessionTable').innerHTML = html;
            });
        }
        setInterval(fetchEquity, 10000); fetchEquity();
        setInterval(fetchSessions, 15000); fetchSessions();
    </script>
</body>
</html>
""",

    "quant_env/utils/config_loader.py": """import os
from dotenv import load_dotenv

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
load_dotenv(os.path.join(project_root, '.env'))

def get_env(key, default=None):
    return os.getenv(key, default)
""",

    "quant_env/utils/notifications.py": """import requests

class TelegramNotifier:
    def __init__(self, token, chat_id):
        self.token = token; self.chat_id = chat_id
    def send(self, msg):
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try: requests.post(url, json={'chat_id':self.chat_id, 'text':msg}, timeout=5)
        except Exception as e: print(f"Telegram error: {e}")
""",

    "quant_env/utils/health_checker.py": """import pandas as pd
from quant_env.analysis.trade_logger import TradeLogger

def run_health_check(db_path="quant_env/trades.db", expected_daily_return=0.01, telegram=None):
    logger = TradeLogger(db_path)
    fills = logger.get_fills()
    if not fills: return
    fills_df = pd.DataFrame(fills, columns=['id','timestamp','symbol','side','price','volume','pnl'])
    equity_rows = logger.get_equity_curve()
    equity_df = pd.DataFrame(equity_rows, columns=['timestamp','equity'])
    now = pd.Timestamp.now(tz='UTC')
    recent = equity_df[pd.to_datetime(equity_df['timestamp']).dt.tz_convert('UTC') > (now - pd.Timedelta(days=1))]
    if recent.empty: return
    ret = (recent['equity'].iloc[-1] / recent['equity'].iloc[0]) - 1
    peak = recent['equity'].cummax()
    dd = (peak - recent['equity']).max()
    alert = None
    if ret < expected_daily_return*0.5: alert = f"Low daily return {ret:.2%}"
    if dd > recent['equity'].iloc[0]*0.02: alert = f"Intraday drawdown ${dd:.2f}"
    if alert and telegram: telegram.send(alert)
    logger.close()
""",

    "launcher.py": """import argparse, sys, os
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
    generate_report(result.equity_df, result.fills_df, metrics, session, output_file="backtest_report.html")
    print("Backtest report saved.")

def run_optimize():
    from backtest.data_loader import load_yfinance
    from backtest.optimizer import optimize as grid_optimize
    from strategies.grid_strategy import GridStrategy
    data = load_yfinance("GC=F", period="5d", interval="1m")
    param_grid = {'spacing': [0.05,0.1,0.2], 'levels': [3,5,7]}
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
    if not fills_rows: print("No trades."); return
    fills_df = pd.DataFrame(fills_rows, columns=['id','timestamp','symbol','side','price','volume','pnl'])
    equity_rows = logger.get_equity_curve()
    equity_df = pd.DataFrame(equity_rows, columns=['timestamp','equity'])
    metrics = compute_metrics(fills_df, equity_df)
    session = session_performance(fills_df, equity_df)
    generate_report(equity_df, fills_df, metrics, session, output_file="live_report.html")
    logger.close()
    print("Live report saved.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['live','backtest','optimize','report'])
    args = parser.parse_args()
    if args.mode=='live': run_live()
    elif args.mode=='backtest': run_backtest()
    elif args.mode=='optimize': run_optimize()
    elif args.mode=='report': run_report()
""",

    ".env.example": """TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
""",
}

# Create directories and write files
for path, content in FILES.items():
    full_path = os.path.join(PROJECT_ROOT, path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(content.strip() + '\n')
    print(f"Created {full_path}")

print("\n🎉 Quant Grid Bot project generated in:", os.path.abspath(PROJECT_ROOT))
print("Next steps:")
print("1. cd gridbots")
print("2. Install requirements: pip install -r quant_env/requirements.txt")
print("3. Ensure the Windows VM bridge is running (see live/mt5_bridge_server.py)")
print("4. Edit quant_env/config.py (set BRIDGE_URL)")
print("5. Run the bot: python launcher.py live")