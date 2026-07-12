#!/usr/bin/env python3
"""
Refresh gold_data.csv from Yahoo Finance when the network is working.

Usage:
    cd gridbots && python refresh_data.py

This script connects to Yahoo Finance and downloads the latest 5 days
of 1-minute gold futures data, saving it to gold_data.csv so backtests
and the live system have fresh local data to fall back on.
"""

import os
import sys
import logging

# Make sure we can import from quant_env
sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("RefreshData")

from quant_env.backtest.data_loader import _download, _postprocess


def main():
    csv_path = os.path.join(os.path.dirname(__file__), "gold_data.csv")

    log.info("Downloading GC=F 5d 1m from Yahoo Finance ...")
    df = _download("GC=F", period="5d", interval="1m")

    if df is None or df.empty:
        log.warning("GC=F download failed, trying XAUUSD=F ...")
        df = _download("XAUUSD=F", period="5d", interval="1m")

    if df is None or df.empty:
        log.error("Could not download data from Yahoo Finance. Check your network.")
        sys.exit(1)

    df = _postprocess(df)

    # Save with the column format that load_yfinance expects
    out = df[['open', 'high', 'low', 'close', 'volume']].copy()
    # Capitalise columns to match CSV convention
    out.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
    out.index.name = 'Datetime'

    out.to_csv(csv_path)
    log.info(f"Saved {len(out)} rows to {csv_path}")


if __name__ == "__main__":
    main()