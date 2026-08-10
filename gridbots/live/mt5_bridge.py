import requests

# All HTTP calls to the local MT5 bridge use a short timeout so the
# dashboard does not hang when the bridge server is not running.
_BRIDGE_TIMEOUT = 3.0   # seconds


class BridgeClient:
    def __init__(self, base_url):
        self.base_url = base_url

    def health(self):
        """Return bridge /status payload (mode, files) or None."""
        try:
            r = requests.get(f"{self.base_url}/status", timeout=3.0)
            return r.json() if r.status_code == 200 else None
        except requests.RequestException:
            return None

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
            # Order placement through Wine/EA needs longer timeout to account
            # for MT5's execution + filesystem sync delay.
            r = requests.post(f"{self.base_url}/place_limit_order", json=payload, timeout=20.0)
            if r.status_code == 200:
                result = r.json()
                print(f"✅ Placed {order_type} at {price}, ticket {result.get('ticket')}")
                return result.get('ticket')
            else:
                print(f"❌ {order_type} {symbol} @ {price} failed: HTTP {r.status_code} — {r.text[:300]}")
                return None
        except requests.RequestException as e:
            print(f"❌ {order_type} {symbol} @ {price}: bridge unreachable ({e})")
            return None

    def symbol_tick(self, symbol):
        """Fetch the latest tick for a symbol with a useful error message."""
        try:
            r = requests.get(f"{self.base_url}/symbol_tick", params={'symbol': symbol}, timeout=5.0)
            if r.status_code == 200:
                return r.json()
            return None
        except requests.RequestException:
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

    def cancel_order(self, symbol, price_or_ticket):
        """Cancel a pending order by price level or ticket number."""
        try:
            payload = {
                "symbol": symbol,
                "price_or_ticket": price_or_ticket
            }
            r = requests.post(f"{self.base_url}/cancel_order", json=payload, timeout=_BRIDGE_TIMEOUT)
            return r.json() if r.status_code == 200 else None
        except requests.RequestException:
            return None

    def close_positions(self, symbol):
        try:
            r = requests.post(f"{self.base_url}/close_positions", json={'symbol': symbol}, timeout=_BRIDGE_TIMEOUT)
            return r.json() if r.status_code == 200 else None
        except requests.RequestException:
            return None
