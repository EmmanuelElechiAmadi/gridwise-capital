#!/usr/bin/env python3
"""
Refresh the multi-symbol research corpus from Yahoo Finance.

Downloads each symbol's recent hourly history into the cached CSVs the
agent team probes (see intelligence/data.py for the filename convention):

    GC=F  ->  gold_data.csv
    SI=F  ->  SIF.csv
    CL=F  ->  CLF.csv

Usage:
    cd gridbots && python refresh_multi_symbol.py
    cd gridbots && python refresh_multi_symbol.py --symbols GC=F,SI=F --period 3mo
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "quant_env"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("RefreshMultiSymbol")

from quant_env.backtest.data_loader import _download, _postprocess  # noqa: E402

DEFAULT_SYMBOLS = {"GC=F": "gold_data.csv", "SI=F": "SIF.csv", "CL=F": "CLF.csv"}


def main():
    parser = argparse.ArgumentParser(description="Refresh multi-symbol cached OHLCV corpus")
    parser.add_argument("--symbols", default=None,
                        help="comma-separated symbols, e.g. GC=F,SI=F,CL=F")
    parser.add_argument("--period", default="1mo", help="Yahoo period (1mo/3mo/6mo)")
    parser.add_argument("--interval", default="1h", help="Yahoo interval (1h/4h/1d)")
    args = parser.parse_args()

    symbols = DEFAULT_SYMBOLS
    if args.symbols:
        requested = [s.strip() for s in args.symbols.split(",") if s.strip()]
        symbols = {s: DEFAULT_SYMBOLS.get(s, f"{s.replace('=', '').replace('/', '_')}.csv")
                   for s in requested}

    root = os.path.dirname(__file__)
    ok = 0
    for symbol, fname in symbols.items():
        log.info(f"Downloading {symbol} ({args.period} {args.interval}) …")
        df = _download(symbol, period=args.period, interval=args.interval)
        if df is None or df.empty:
            log.warning(f"{symbol} download failed — skipping")
            continue
        df = _postprocess(df)
        out = df[["open", "high", "low", "close", "volume"]].copy()
        out.columns = ["Open", "High", "Low", "Close", "Volume"]
        out.index.name = "Datetime"
        path = os.path.join(root, fname)
        out.to_csv(path)
        log.info(f"Saved {len(out)} rows to {path}")
        ok += 1

    log.info(f"Done — {ok}/{len(symbols)} symbols refreshed. "
             "Run `python3 launcher.py research --symbols GC=F,SI=F,CL=F` to probe the corpus.")


if __name__ == "__main__":
    main()
