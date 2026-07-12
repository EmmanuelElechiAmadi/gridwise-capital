"""
Trade logger — writes fills and equity snapshots to a per-account SQLite DB.

Supports multi-account isolation by storing trades in separate DB files
named ``trades_{account_id}.db``, or in a single DB with an ``account_id``
column (controlled by the ``multi_db`` flag).
"""

import sqlite3
import os
import time
import random
from pathlib import Path
from datetime import datetime
from typing import Optional


# Default directory for trade databases
_DEFAULT_DB_DIR = Path(__file__).resolve().parent.parent / "trade_data"


def _db_path(account_id: str) -> str:
    """Return filesystem path for a given account's trade DB."""
    _DEFAULT_DB_DIR.mkdir(parents=True, exist_ok=True)
    return str(_DEFAULT_DB_DIR / f"trades_{account_id}.db")


class TradeLogger:
    """
    Lightweight trade and equity logging backed by SQLite.

    When ``account_id`` is provided, each account gets its own DB file
    (``trades_{account_id}.db``).  If no account_id is given, falls
    back to the old single-file behaviour (``trades.db``).
    """

    def __init__(self, db_path: Optional[str] = None, account_id: Optional[str] = None):
        if db_path is None:
            db_path = _db_path(account_id) if account_id else "trades.db"

        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else '.', exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self._account_id = account_id or "default"
        self._create_tables()
        self._migrate_schema()

    def _create_tables(self):
        self.conn.execute('''CREATE TABLE IF NOT EXISTS fills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT DEFAULT 'default',
            timestamp TEXT, symbol TEXT, side TEXT,
            price REAL, volume REAL, pnl REAL DEFAULT 0)''')
        self.conn.execute('''CREATE TABLE IF NOT EXISTS equity_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT DEFAULT 'default',
            timestamp TEXT, equity REAL, balance REAL,
            net_position REAL, open_orders INTEGER)''')
        self.conn.commit()

    def _migrate_schema(self):
        """Add missing columns to handle DBs created by older versions."""
        for table, col_def in [
            ("fills", "account_id TEXT DEFAULT 'default'"),
            ("equity_snapshots", "account_id TEXT DEFAULT 'default'"),
        ]:
            try:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
                self.conn.commit()
            except sqlite3.OperationalError:
                pass  # column already exists — this is fine

    def _retry_commit(self, execute_fn):
        for attempt in range(10):
            try:
                execute_fn()
                self.conn.commit()
                return
            except sqlite3.OperationalError as e:
                if "locked" in str(e) or "database is locked" in str(e):
                    time.sleep(random.uniform(0.2, 1.0) * (attempt + 1))
                else:
                    raise
        raise sqlite3.OperationalError("Database still locked after 10 retries")

    def log_fill(self, symbol: str, side: str, price: float, volume: float, pnl: float = 0):
        def insert():
            self.conn.execute(
                "INSERT INTO fills (account_id, timestamp, symbol, side, price, volume, pnl) VALUES (?,?,?,?,?,?,?)",
                (self._account_id, datetime.now().isoformat(), symbol, side, price, volume, pnl))
        self._retry_commit(insert)

    def log_equity(self, equity: float, balance: float, net_position: float, open_orders: int):
        def insert():
            self.conn.execute(
                "INSERT INTO equity_snapshots (account_id, timestamp, equity, balance, net_position, open_orders) VALUES (?,?,?,?,?,?)",
                (self._account_id, datetime.now().isoformat(), equity, balance, net_position, open_orders))
        self._retry_commit(insert)

    def get_fills(self, symbol: Optional[str] = None) -> list:
        query = "SELECT * FROM fills WHERE account_id = ?"
        params = [self._account_id]
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        return self.conn.execute(query, params).fetchall()

    def get_recent(self, limit: int = 50) -> list:
        rows = self.conn.execute(
            "SELECT * FROM fills WHERE account_id = ? ORDER BY id DESC LIMIT ?",
            (self._account_id, limit)
        ).fetchall()
        cols = [d[0] for d in self.conn.execute("PRAGMA table_info(fills)").fetchall()]
        import pandas as pd
        if rows:
            df = pd.DataFrame(rows, columns=cols)
            return df.to_dict(orient='records')
        return []

    def get_equity_curve(self) -> list:
        return self.conn.execute(
            "SELECT timestamp, equity FROM equity_snapshots WHERE account_id = ? ORDER BY timestamp",
            (self._account_id,)
        ).fetchall()

    def close(self):
        self.conn.close()