#!/usr/bin/env python3
"""Simple grid bot – direct MT5 (Windows) or bridge (Mac)."""
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
