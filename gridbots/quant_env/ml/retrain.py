"""
One-shot retraining script for the directional regime classifier.

Fetches multiple years of hourly data for the target instrument (default:
GC=F gold futures, the same symbol used live), trains a new RegimeClassifier,
runs health checks, and saves the model + sidecar metrics JSON.

Usage:
    cd quant_env && python -m ml.retrain

Environment variables (optional):
    SYMBOL      - Yahoo Finance symbol (default: GC=F)
    PERIOD      - yfinance period string (default: "2y")
    INTERVAL    - yfinance interval string (default: "1h")
    MODEL_PATH  - output path for model.pkl
"""

import sys
import os
import logging
import yfinance as yf
import pandas as pd
import numpy as np

# Ensure we can import from parent
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ml.regime_model import RegimeClassifier
from ml.data_builder import build_features

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("retrain")

# ── Config ─────────────────────────────────────────────────────────────
SYMBOL = os.getenv("SYMBOL", "GC=F")           # Gold futures (matches YAHOO_SYMBOL default)
PERIOD = os.getenv("PERIOD", "2y")              # 2 years of hourly data
INTERVAL = os.getenv("INTERVAL", "1h")
LOOKBACK = 20
REGIME_THRESHOLD = 1.0                          # ATR multiplier for trending classification
CONFIDENCE_THRESHOLD = 0.4

# Output path
MODEL_DIR = os.path.join(os.path.dirname(__file__))
MODEL_PATH = os.getenv("MODEL_PATH", os.path.join(MODEL_DIR, "model.pkl"))


# ── Fetch Data ─────────────────────────────────────────────────────────
def fetch_data():
    log.info(f"Downloading {SYMBOL} ({PERIOD}, {INTERVAL})...")
    df = yf.download(SYMBOL, period=PERIOD, interval=INTERVAL, progress=False)
    if df.empty:
        log.error("No data fetched.")
        sys.exit(1)

    # Flatten MultiIndex columns (yfinance format)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)

    df.rename(columns={
        'Open': 'open', 'High': 'high', 'Low': 'low',
        'Close': 'close', 'Volume': 'volume'
    }, inplace=True)

    log.info(f"Fetched {len(df)} bars ({df.index[0].date()} → {df.index[-1].date()})")
    return df


# ── Train ──────────────────────────────────────────────────────────────
def main():
    df = fetch_data()

    # Quick sanity: check class balance with a preview of the target
    X_preview, y_preview = build_features(
        df,
        lookback=LOOKBACK,
        target_lookahead=LOOKBACK,
        regime_threshold=REGIME_THRESHOLD,
    )
    if X_preview.empty:
        log.error("Not enough data to build features after preprocessing.")
        sys.exit(1)

    class_dist = y_preview.value_counts(normalize=True).sort_index()
    log.info(f"Class distribution (pre-training preview of {len(y_preview)} samples):")
    label_map = {-1: 'BEAR', 0: 'RANGING', 1: 'BULL'}
    for cls in sorted(class_dist.index):
        label = label_map.get(cls, cls)
        log.info(f"  {label:8s} ({cls:2d}): {class_dist[cls]:.1%}")

    if len(class_dist) < 2:
        log.error(
            f"Only {len(class_dist)} class(es) present. "
            f"Try adjusting REGIME_THRESHOLD (currently {REGIME_THRESHOLD}) "
            f"or using a longer/より varied dataset."
        )
        sys.exit(1)

    classifier = RegimeClassifier(
        lookback=LOOKBACK,
        threshold=25,                              # kept for backward compat
        confidence_threshold=CONFIDENCE_THRESHOLD,
        regime_threshold=REGIME_THRESHOLD,
    )

    log.info("Training directional regime classifier...")
    metrics = classifier.train(df)

    # Health check
    log.info("Running health check...")
    health = classifier.health_check()
    log.info(f"Health check: {'PASS' if health['healthy'] else 'FAIL'}")
    for check_name, result in health['checks'].items():
        if isinstance(result, dict):
            status = "✓" if result.get('pass') else "✗"
            detail = result.get('message') or result.get('reason') or ''
            log.info(f"  {status} {check_name}: {detail}")
        else:
            log.info(f"  {'✓' if result else '✗'} {check_name}")

    # Save
    classifier.save(MODEL_PATH, training_metrics=metrics)
    log.info(f"Retraining complete. Model saved to {MODEL_PATH}")


if __name__ == "__main__":
    main()