"""
Data models for brokerage accounts.

Defines the BrokerAccount dataclass, broker type enum, and connection
status enum used throughout the multi-account system.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


class BrokerType(str, enum.Enum):
    """
    Supported brokerage connection type.

    This platform is single-broker: MetaTrader 5, connected via the local
    HTTP bridge server (mt5_bridge_server.py) which reads/writes JSON files
    produced by the mt5_bridge_ea.mq5 Expert Advisor running inside your
    MT5 terminal.  DUMMY is kept only as an internal offline/demo fallback
    when the bridge is unreachable — it is not a user-facing broker choice.
    """

    MT5_BRIDGE = "mt5_bridge"      # MetaTrader 5 via HTTP bridge server (the only real broker)
    DUMMY = "dummy"                # Simulated / demo data (internal fallback only)



class ConnectionStatus(str, enum.Enum):
    """Current connection state of a broker account."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    NOT_CONFIGURED = "not_configured"


@dataclass
class BrokerAccount:
    """
    Represents a single brokerage account linked to the platform.

    Each account holds its own connection credentials, trading parameters,
    risk settings, and runtime state.  Accounts are fully isolated from
    each other — each gets its own Connector, strategy instance, and
    trade log.
    """

    # ── Identity ─────────────────────────────────────────────────────
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    label: str = "My Account"
    user_id: str = "default"                # for future multi-user support
    broker_type: BrokerType = BrokerType.MT5_BRIDGE
    enabled: bool = True

    # ── Connection config ────────────────────────────────────────────
    # The exact fields depend on broker_type.  Stored as a dict so new
    # broker types don't require schema changes.
    connection_config: dict = field(default_factory=dict)
    #   For MT5_BRIDGE (the only supported broker connection):
    #       bridge_url: str = "http://127.0.0.1:8080"


    # ── Trading config ───────────────────────────────────────────────
    trading_config: dict = field(default_factory=lambda: {
        "symbol": "XAUUSD.r",
        "lot_size": 0.01,
        "magic_number": 123456,
        "grid_spacing": 2.0,
        "grid_spacing_mult": 1.0,
        "num_levels": 3,
    })

    # ── Risk config ──────────────────────────────────────────────────
    risk_config: dict = field(default_factory=lambda: {
        "take_profit_dollars": 2.0,
        "stop_loss_dollars": 0.0,
        "max_position_oz": 1.0,
        "max_drawdown_percent": 0.0,
    })

    # ── Runtime state (not persisted) ────────────────────────────────
    status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    last_error: Optional[str] = None
    last_sync_at: Optional[datetime] = None

    # ── Metadata ─────────────────────────────────────────────────────
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict (excludes runtime state)."""
        return {
            "id": self.id,
            "label": self.label,
            "user_id": self.user_id,
            "broker_type": self.broker_type.value,
            "enabled": self.enabled,
            "connection_config": self.connection_config,
            "trading_config": self.trading_config,
            "risk_config": self.risk_config,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> BrokerAccount:
        """Deserialize from a dict (e.g. loaded from JSON store)."""
        return cls(
            id=data.get("id", uuid.uuid4().hex[:12]),
            label=data.get("label", "My Account"),
            user_id=data.get("user_id", "default"),
            broker_type=BrokerType(data.get("broker_type", "mt5_bridge")),
            enabled=data.get("enabled", True),
            connection_config=data.get("connection_config", {}),
            trading_config=data.get("trading_config", {}),
            risk_config=data.get("risk_config", {}),
            created_at=datetime.fromisoformat(data["created_at"])
                if "created_at" in data else datetime.utcnow(),
            updated_at=datetime.fromisoformat(data["updated_at"])
                if "updated_at" in data else datetime.utcnow(),
        )

    def __repr__(self) -> str:
        bt = self.broker_type.value if isinstance(self.broker_type, BrokerType) else str(self.broker_type)
        st = self.status.value if isinstance(self.status, ConnectionStatus) else str(self.status)
        return (
            f"<BrokerAccount id={self.id!r} label={self.label!r} "
            f"type={bt!r} status={st}>"
        )
