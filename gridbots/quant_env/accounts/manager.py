"""
BrokerAccountManager — CRUD and lifecycle for all brokerage accounts.

Provides the high-level API that the dashboard and other components
use to create, read, update, delete, and test broker accounts.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Dict, List, Optional

from .models import BrokerAccount, BrokerType, ConnectionStatus
from .store import AccountStore

logger = logging.getLogger(__name__)


class BrokerAccountManager:
    """
    Central manager for brokerage accounts.

    Wraps AccountStore with business logic:
    - CRUD operations
    - Connection testing (ping the broker)
    - Status tracking
    - Backwards-compat: creates a default account if none exist
    """

    def __init__(self, store: Optional[AccountStore] = None):
        self._store = store or AccountStore()
        self._lock = threading.RLock()
        self._status_cache: Dict[str, ConnectionStatus] = {}

    # ── CRUD ──────────────────────────────────────────────────────────

    def list_accounts(self) -> List[BrokerAccount]:
        """Return all accounts, ordered by creation time."""
        accounts = self._store.load_all()
        for acct in accounts:
            # Restore cached runtime status if available
            if acct.id in self._status_cache:
                acct.status = self._status_cache[acct.id]
        return sorted(accounts, key=lambda a: a.created_at)

    def get_account(self, account_id: str) -> Optional[BrokerAccount]:
        """Get a single account by id."""
        acct = self._store.load(account_id)
        if acct and acct.id in self._status_cache:
            acct.status = self._status_cache[acct.id]
        return acct

    def create_account(
        self,
        label: str,
        broker_type: BrokerType,
        connection_config: dict,
        trading_config: Optional[dict] = None,
        risk_config: Optional[dict] = None,
        user_id: str = "default",
    ) -> BrokerAccount:
        """Create a new brokerage account and persist it."""
        account = BrokerAccount(
            label=label,
            user_id=user_id,
            broker_type=broker_type,
            connection_config=connection_config,
            trading_config=trading_config or {},
            risk_config=risk_config or {},
            status=ConnectionStatus.NOT_CONFIGURED,
        )
        # Fill in missing defaults
        self._apply_defaults(account)
        self._store.save(account)
        logger.info(f"Created account {account.id} ({account.label})")
        return account

    def update_account(
        self,
        account_id: str,
        updates: dict,
    ) -> Optional[BrokerAccount]:
        """Update fields on an existing account.  Returns None if not found."""
        acct = self._store.load(account_id)
        if acct is None:
            return None

        # Apply partial updates to sub-dicts
        if "connection_config" in updates:
            acct.connection_config.update(updates["connection_config"])
        if "trading_config" in updates:
            acct.trading_config.update(updates["trading_config"])
        if "risk_config" in updates:
            acct.risk_config.update(updates["risk_config"])

        # Scalar fields
        for scalar in ("label", "enabled", "broker_type", "user_id"):
            if scalar in updates:
                if scalar == "broker_type":
                    setattr(acct, scalar, BrokerType(updates[scalar]))
                else:
                    setattr(acct, scalar, updates[scalar])

        acct.updated_at = datetime.utcnow()
        self._store.save(acct)
        logger.info(f"Updated account {account_id}")
        return acct

    def delete_account(self, account_id: str) -> bool:
        """Delete an account.  Returns True if it existed."""
        with self._lock:
            self._status_cache.pop(account_id, None)
            result = self._store.delete(account_id)
            if result:
                logger.info(f"Deleted account {account_id}")
            return result

    def set_status(self, account_id: str, status: ConnectionStatus, error: Optional[str] = None):
        """Update the cached runtime status of an account."""
        with self._lock:
            self._status_cache[account_id] = status
        if error:
            acct = self._store.load(account_id)
            if acct:
                acct.last_error = error
                self._store.save(acct)

    # ── Connection testing ────────────────────────────────────────────

    def test_connection(self, account_id: str) -> bool:
        """
        Attempt to connect to the broker and verify credentials.
        Updates the account's runtime status on success/failure.
        """
        acct = self._store.load(account_id)
        if acct is None:
            return False

        self.set_status(account_id, ConnectionStatus.CONNECTING)
        try:
            ok = self._ping_broker(acct)
            self.set_status(
                account_id,
                ConnectionStatus.CONNECTED if ok else ConnectionStatus.ERROR,
                error=None if ok else "Connection returned no data",
            )
            return ok
        except Exception as e:
            self.set_status(account_id, ConnectionStatus.ERROR, error=str(e))
            logger.warning(f"Connection test failed for {account_id}: {e}")
            return False

    def _ping_broker(self, account: BrokerAccount) -> bool:
        """
        Low-level connection probe against the local MT5 bridge server.
        Import connector lazily to avoid circular imports at module level.
        """
        if account.broker_type == BrokerType.DUMMY:
            return True

        # MT5_BRIDGE is the only real broker connection type.
        import requests
        url = account.connection_config.get("bridge_url", "http://127.0.0.1:8080")
        try:
            resp = requests.get(f"{url}/account_info", timeout=3.0)
            return resp.status_code == 200
        except requests.RequestException as e:
            logger.warning(
                f"Bridge unreachable at {url}. Make sure MT5 is running with "
                f"mt5_bridge_ea.mq5 attached and mt5_bridge_server.py is running. ({e})"
            )
            return False

    # ── Helpers ───────────────────────────────────────────────────────

    def _apply_defaults(self, account: BrokerAccount):
        """Fill in sensible defaults for empty config dicts."""
        if account.broker_type == BrokerType.MT5_BRIDGE:
            account.connection_config.setdefault("bridge_url", "http://127.0.0.1:8080")


    def ensure_default_account(self) -> BrokerAccount:
        """
        If no accounts exist, create a default one from the current
        hard-coded Config values.  This provides backwards compatibility
        for single-account setups.
        """
        accounts = self._store.load_all()
        if accounts:
            return accounts[0]

        from quant_env.config import Config
        default = BrokerAccount(
            label="Default (MT5 Bridge)",
            broker_type=BrokerType.MT5_BRIDGE,
            connection_config={"bridge_url": Config.BRIDGE_URL},
            trading_config={
                "symbol": Config.SYMBOL,
                "lot_size": Config.LOT_SIZE,
                "magic_number": Config.MAGIC_NUMBER,
                "grid_spacing": Config.GRID_SPACING,
                "grid_spacing_mult": Config.GRID_SPACING_MULT,
                "num_levels": Config.NUM_LEVELS,
            },
            risk_config={
                "take_profit_dollars": Config.TAKE_PROFIT_DOLLARS,
                "stop_loss_dollars": Config.STOP_LOSS_DOLLARS,
                "max_position_oz": Config.MAX_POSITION_OZ,
                "max_drawdown_percent": Config.MAX_DRAWDOWN_PERCENT,
            },
            status=ConnectionStatus.NOT_CONFIGURED,
        )
        self._store.save(default)
        logger.info(f"Created default account {default.id}")
        return default