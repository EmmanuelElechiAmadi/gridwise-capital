import requests

# All HTTP calls to the local MT5 bridge use a short timeout so the
# dashboard does not hang when the bridge server is not running.
_BRIDGE_TIMEOUT = 3.0   # seconds


class BridgeClient:
    def __init__(self, base_url):
        self.base_url = base_url

    def account_info(self):
        try:
            r = requests.get(f"{self.base_url}/account_info", timeout=_BRIDGE_TIMEOUT)
            if r.status_code == 200:
                data = r.json()
                class Account:
                    pass
                acc = Account()
                acc.login = data.get('login')
                acc.balance = data.get('balance')
                acc.equity = data.get('equity')
                return acc
        except requests.RequestException:
            pass
        return None

    def place_limit_order(self, symbol, order_type, price, volume, comment="BridgeBot"):
        try:
            payload = {
                "symbol": symbol,
                "order_type": order_type,
                "price": price,
                "volume": volume,
                "comment": comment
            }
            r = requests.post(f"{self.base_url}/place_limit_order", json=payload, timeout=_BRIDGE_TIMEOUT)
            if r.status_code == 200:
                result = r.json()
                print(f"✅ Placed {order_type} at {price}, ticket {result.get('ticket')}")
                return result.get('ticket')
        except requests.RequestException:
            pass
        return None

    def get_positions(self, symbol=None):
        try:
            params = {'symbol': symbol} if symbol else {}
            r = requests.get(f"{self.base_url}/positions", params=params, timeout=5.0)
            return r.json() if r.status_code == 200 else []
        except requests.RequestException:
            return []

    def get_open_orders(self, symbol=None):
        try:
            params = {'symbol': symbol} if symbol else {}
            r = requests.get(f"{self.base_url}/open_orders", params=params, timeout=5.0)
            return r.json() if r.status_code == 200 else []
        except requests.RequestException:
            return []

    def close_positions(self, symbol):
        try:
            r = requests.post(f"{self.base_url}/close_positions", json={'symbol': symbol}, timeout=_BRIDGE_TIMEOUT)
            return r.json() if r.status_code == 200 else None
        except requests.RequestException:
            return None