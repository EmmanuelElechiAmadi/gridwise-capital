"""
Broker connector — talks to the local MetaTrader 5 terminal via the
HTTP bridge server (mt5_bridge_server.py + mt5_bridge_ea.mq5).

This platform is single-broker by design: your MT5 terminal running on
this same MacBook, talking to the bridge over localhost.  A DummyConnector
is kept purely as an internal offline fallback (used only if the bridge
truly cannot be reached and you explicitly want to preview the dashboard
without a broker), it is never exposed as a user-facing "broker choice".
"""

from __future__ import annotations

import sys
import os
import requests
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from quant_env.accounts.models import BrokerAccount


class DummyAccount:
    """Minimal account info object returned by account_info()."""
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


# ── Connector factory ─────────────────────────────────────────────────

def create_connector(account: "BrokerAccount") -> "Connector":
    """
    Create the Connector for the given account.

    The only real connector is MT5BridgeConnector.  DUMMY is only used
    when explicitly configured (e.g. for local UI preview / testing).
    """
    from quant_env.accounts.models import BrokerType

    if account.broker_type == BrokerType.DUMMY:
        return DummyConnector(account)
    # MT5_BRIDGE (and any legacy/unknown value) -> the one real connector
    return MT5BridgeConnector(account)


# ── Base Connector ────────────────────────────────────────────────────

class Connector:
    """
    Abstract base for the broker connector.

    Subclasses must implement: account_info, symbol_tick, place_limit_order,
    close_all_positions, get_open_orders, get_positions, shutdown.
    """

    def __init__(self, account: "BrokerAccount"):
        self.account = account
        self.magic = account.trading_config.get("magic_number", 123456)
        self.symbol = account.trading_config.get("symbol", "XAUUSD.r")

    def account_info(self):
        raise NotImplementedError

    def symbol_tick(self):
        raise NotImplementedError

    def place_limit_order(self, order_type, price, volume, comment=""):
        raise NotImplementedError

    def cancel_order(self, price_or_ticket):
        """
        Cancel an existing pending order identified by price or ticket.
        Subclasses must implement this or return True (no-op) if cancellation
        is not supported.
        """
        raise NotImplementedError

    def close_all_positions(self):
        raise NotImplementedError

    def get_open_orders(self):
        raise NotImplementedError

    def get_positions(self):
        raise NotImplementedError

    def is_connected(self) -> bool:
        """Lightweight connectivity check. Override in subclasses."""
        try:
            return self.account_info() is not None
        except Exception:
            return False

    def shutdown(self):
        pass


# ── MT5 via local HTTP bridge (the only supported broker connection) ──

class MT5BridgeConnector(Connector):
    """
    Connects to MetaTrader 5 running locally on this MacBook via the HTTP
    bridge server (mt5_bridge_server.py). The bridge, in turn, talks to
    the mt5_bridge_ea.mq5 Expert Advisor attached to a chart inside your
    MT5 terminal.

    Requirements for a working connection:
      1. MetaTrader 5 terminal is open and logged into your broker account.
      2. mt5_bridge_ea.mq5 is compiled & attached to a chart, with
         "Algo Trading" enabled in MT5.
      3. mt5_bridge_server.py is running locally (default http://127.0.0.1:8080).
    """

    def __init__(self, account: "BrokerAccount"):
        super().__init__(account)
        cfg = account.connection_config
        self.base_url = cfg.get("bridge_url", "http://127.0.0.1:8080")
        # Import BridgeClient lazily
        sys.path.append(os.path.join(os.path.dirname(__file__), '../../live'))
        from mt5_bridge import BridgeClient
        self.bridge = BridgeClient(self.base_url)

    def account_info(self):
        return self.bridge.account_info()

    def symbol_tick(self):
        try:
            r = requests.get(f"{self.base_url}/symbol_tick", params={'symbol': self.symbol}, timeout=3.0)
            return r.json() if r.status_code == 200 else None
        except requests.RequestException:
            return None

    def place_limit_order(self, order_type, price, volume, comment=""):
        return self.bridge.place_limit_order(self.symbol, order_type, price, volume, comment)

    def cancel_order(self, price_or_ticket):
        """Cancel a pending order via the bridge server."""
        return self.bridge.cancel_order(self.symbol, price_or_ticket)

    def close_all_positions(self):
        self.bridge.close_positions(self.symbol)

    def get_open_orders(self):
        return self.bridge.get_open_orders(self.symbol)

    def get_positions(self):
        return self.bridge.get_positions(self.symbol)

    def is_connected(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/account_info", timeout=2.0)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def shutdown(self):
        pass  # bridge client is stateless


# ── Dummy / simulation connector (offline fallback only) ──────────────

class DummyConnector(Connector):
    """Simulated connector that returns placeholder data when the MT5
    bridge is not configured / not reachable. Not a real broker."""

    def __init__(self, account: "BrokerAccount"):
        super().__init__(account)
        self._balance = 10000.0
        self._equity = 10000.0

    def account_info(self):
        return DummyAccount(login="dummy", balance=self._balance, equity=self._equity)

    def symbol_tick(self):
        import random, math
        fake_price = 2350.0 + 5.0 * math.sin(getattr(self, '_tick', 0) / 15.0) + random.gauss(0, 0.5)
        self._tick = getattr(self, '_tick', 0) + 1
        return {'bid': fake_price, 'ask': fake_price + 0.2}

    def place_limit_order(self, order_type, price, volume, comment=""):
        return "dummy_ticket_123"

    def cancel_order(self, price_or_ticket):
        """Dummy cancel — no-op for simulation mode."""
        return True

    def close_all_positions(self):
        pass

    def get_open_orders(self):
        return []

    def get_positions(self):
        return []

    def is_connected(self) -> bool:
        return True

    def shutdown(self):
        pass
