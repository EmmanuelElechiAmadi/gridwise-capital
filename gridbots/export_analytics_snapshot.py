#!/usr/bin/env python3
"""
Export a JSON snapshot of all engine analytics artifacts so the
Intelligence webapp has real data even when the live Flask backend is
offline and the (gitignored) CSV / DB artifacts are not present in a
fresh clone.

Usage:
    cd gridbots && python3 export_analytics_snapshot.py

Writes: analytics_snapshot.json (committed to git).
"""
import csv
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read_csv(path: Path, limit: int = 20000):
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))[:limit]


def load_engine_fills():
    """Read fills + equity from the legacy engine DB (real historical data)."""
    db = ROOT / "quant_env" / "trades.db"
    if not db.exists():
        return [], []
    conn = sqlite3.connect(str(db), timeout=5.0)
    fills = conn.execute(
        "SELECT timestamp, symbol, side, price, volume, pnl FROM fills ORDER BY timestamp"
    ).fetchall()
    equity = conn.execute(
        "SELECT timestamp, equity, balance FROM equity_snapshots ORDER BY timestamp"
    ).fetchall()
    conn.close()
    fills_out = [
        {"timestamp": t, "symbol": s, "side": si, "price": float(p or 0),
         "volume": float(v or 0), "pnl": float(pn or 0)}
        for t, s, si, p, v, pn in fills
    ]
    equity_out = [
        {"timestamp": t, "equity": float(e or 0), "balance": float(b or 0)}
        for t, e, b in equity
    ]
    return fills_out, equity_out


def main():
    fills, equity = load_engine_fills()

    # Match trades FIFO for realized PnL
    trades = []
    if fills:
        buys = [f for f in fills if f["side"] == "buy"]
        sells = [f for f in fills if f["side"] == "sell"]
        buy_q = list(buys)
        for sell in sells:
            vol = float(sell["volume"])
            price = float(sell["price"])
            while vol > 1e-9 and buy_q:
                b = buy_q[0]
                b_vol = float(b["volume"])
                matched = min(b_vol, vol)
                trades.append({
                    "entry_time": b["timestamp"],
                    "exit_time": sell["timestamp"],
                    "entry_price": float(b["price"]),
                    "exit_price": price,
                    "volume": matched,
                    "pnl": round((price - float(b["price"])) * matched, 4),
                })
                vol -= matched
                b["volume"] = b_vol - matched
                if b["volume"] <= 1e-9:
                    buy_q.pop(0)

    snapshot = {
        "exported_at": __import__("datetime").datetime.utcnow().isoformat(),
        "overview": {
            "fills": {
                "count": len(fills),
                "first": fills[0]["timestamp"] if fills else None,
                "last": fills[-1]["timestamp"] if fills else None,
                "buy": sum(1 for f in fills if f["side"] == "buy"),
                "sell": sum(1 for f in fills if f["side"] == "sell"),
            },
            "trades": {"count": len(trades)},
            "equity_points": len(equity),
        },
        "optimization": read_csv(ROOT / "optimization_results.csv"),
        "walkforward": read_csv(ROOT / "walkforward_report.csv"),
        "walkforward_raw": read_csv(ROOT / "walkforward_results.csv"),
        "model_metrics": json.loads(
            (ROOT / "quant_env" / "ml" / "model_metrics.json").read_text()
        ) if (ROOT / "quant_env" / "ml" / "model_metrics.json").exists() else {},
        "fills_tail": fills[-200:],
        "equity_tail": equity[-480:],
        "trades_tail": trades[-100:],
    }

    out = ROOT / "analytics_snapshot.json"
    out.write_text(json.dumps(snapshot, indent=2, default=str))
    print(f"Wrote {out}  ({os.path.getsize(out):,} bytes)")
    print(f"  fills={len(fills)} trades={len(trades)} equity={len(equity)}")


if __name__ == "__main__":
    sys.exit(main())
