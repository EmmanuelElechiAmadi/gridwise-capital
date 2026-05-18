import requests

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
