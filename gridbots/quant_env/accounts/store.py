"""
Persistence layer for brokerage accounts.

Stores accounts in a local JSON file (plain for now; encryption can be
added later for sensitive credential fields).  Uses file-level locking
to prevent concurrent access from multiple dashboard threads.
"""

import json
import os
import threading
from pathlib import Path
from typing import Dict, List, Optional

from .models import BrokerAccount


# Default storage path relative to the quant_env package root
_DEFAULT_STORE_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_STORE_FILE = _DEFAULT_STORE_DIR / "accounts_store.json"


class AccountStore:
    """
    Reads and writes BrokerAccount records to a JSON file.

    Thread-safe via a per-instance reentrant lock.  All mutations are
    atomic — load, modify, write back in a single critical section.
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = path or _DEFAULT_STORE_FILE
        self._lock = threading.RLock()
        self._accounts: Dict[str, dict] = {}   # id -> raw dict
        self._loaded = False

    # ── Public API ────────────────────────────────────────────────────

    def load_all(self) -> List[BrokerAccount]:
        """Load all accounts from disk."""
        with self._lock:
            self._ensure_loaded()
            return [BrokerAccount.from_dict(d) for d in self._accounts.values()]

    def load(self, account_id: str) -> Optional[BrokerAccount]:
        """Load a single account by id."""
        with self._lock:
            self._ensure_loaded()
            raw = self._accounts.get(account_id)
            return BrokerAccount.from_dict(raw) if raw else None

    def save(self, account: BrokerAccount) -> BrokerAccount:
        """Persist a single account (insert or update)."""
        with self._lock:
            self._ensure_loaded()
            self._accounts[account.id] = account.to_dict()
            self._flush()
            return account

    def delete(self, account_id: str) -> bool:
        """Remove an account by id.  Returns True if it existed."""
        with self._lock:
            self._ensure_loaded()
            existed = account_id in self._accounts
            if existed:
                del self._accounts[account_id]
                self._flush()
            return existed

    def list_ids(self) -> List[str]:
        """Return all account IDs (lightweight, no deserialization)."""
        with self._lock:
            self._ensure_loaded()
            return list(self._accounts.keys())

    # ── Internal helpers ──────────────────────────────────────────────

    def _ensure_loaded(self):
        """Lazy-load the JSON file on first access."""
        if not self._loaded:
            if self._path.exists():
                try:
                    with open(self._path, "r") as f:
                        data = json.load(f)
                    # Support both list-of-dicts and dict-of-dicts formats
                    if isinstance(data, list):
                        self._accounts = {d["id"]: d for d in data if "id" in d}
                    elif isinstance(data, dict):
                        self._accounts = data
                    else:
                        self._accounts = {}
                except (json.JSONDecodeError, OSError):
                    self._accounts = {}
            else:
                self._accounts = {}
            self._loaded = True

    def _flush(self):
        """Write the in-memory dict back to disk atomically."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(self._accounts, f, indent=2, default=str)
        tmp.replace(self._path)

    def __len__(self) -> int:
        with self._lock:
            self._ensure_loaded()
            return len(self._accounts)

    def __repr__(self) -> str:
        return f"<AccountStore path={self._path} loaded={len(self)}>"