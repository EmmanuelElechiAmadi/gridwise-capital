import sqlite3, os, time, random
from datetime import datetime

class TradeLogger:
    def __init__(self, db_path="trades.db"):
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else '.', exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self._create_tables()

    def _create_tables(self):
        self.conn.execute('''CREATE TABLE IF NOT EXISTS fills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, symbol TEXT, side TEXT,
            price REAL, volume REAL, pnl REAL DEFAULT 0)''')
        self.conn.execute('''CREATE TABLE IF NOT EXISTS equity_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, equity REAL, balance REAL,
            net_position REAL, open_orders INTEGER)''')
        self.conn.commit()

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

    def log_fill(self, symbol, side, price, volume, pnl=0):
        def insert():
            self.conn.execute(
                "INSERT INTO fills (timestamp, symbol, side, price, volume, pnl) VALUES (?,?,?,?,?,?)",
                (datetime.now().isoformat(), symbol, side, price, volume, pnl))
        self._retry_commit(insert)

    def log_equity(self, equity, balance, net_position, open_orders):
        def insert():
            self.conn.execute(
                "INSERT INTO equity_snapshots (timestamp, equity, balance, net_position, open_orders) VALUES (?,?,?,?,?)",
                (datetime.now().isoformat(), equity, balance, net_position, open_orders))
        self._retry_commit(insert)

    def get_fills(self, symbol=None):
        query = "SELECT * FROM fills"
        if symbol: query += f" WHERE symbol='{symbol}'"
        return self.conn.execute(query).fetchall()

    def get_equity_curve(self):
        return self.conn.execute("SELECT timestamp, equity FROM equity_snapshots ORDER BY timestamp").fetchall()

    def close(self):
        self.conn.close()