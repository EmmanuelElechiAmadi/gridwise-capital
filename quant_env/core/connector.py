import sys, os, requests
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
