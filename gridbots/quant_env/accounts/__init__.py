"""
Multi-account brokerage support for the QuantBot trading engine.

Accounts module provides:
- BrokerAccount model (dataclass with all config fields)
- BrokerAccountManager (CRUD, lifecycle, credential storage)
- Persistence via encrypted JSON store
"""

from .models import BrokerAccount, BrokerType, ConnectionStatus
from .manager import BrokerAccountManager
from .store import AccountStore

__all__ = [
    "BrokerAccount",
    "BrokerType",
    "ConnectionStatus",
    "BrokerAccountManager",
    "AccountStore",
]