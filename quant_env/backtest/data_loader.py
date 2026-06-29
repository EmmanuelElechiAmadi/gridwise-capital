import yfinance as yf
import pandas as pd
import numpy as np
import os
import logging

log = logging.getLogger("QuantBot")


def load_yfinance(symbol="GC=F", period="5d", interval="1m", fallback_csv=None):
    """
    Download data from Yahoo Finance with fallback chain.

    Parameters
    ----------
    symbol : str
        Primary Yahoo Finance symbol (default 'GC=F' for gold futures).
    period : str
        Lookback period (e.g. '5d', '1mo', '3mo').
    interval : str
        Bar interval (e.g. '1m', '1h', '1d').
    fallback_csv : str, optional
        Local CSV file to use if all symbol downloads fail.

    Returns
    -------
    pd.DataFrame
        Columns: open, high, low, close, volume — with no NaN bars removed.

    Raises
    ------
    ValueError
        If no data could be obtained from any source.
    """
    # Try primary symbol
    df = _download(symbol, period, interval)
    if df is not None:
        df = _postprocess(df)
        return df

    # Try gold spot (often still available on weekends)
    log.warning(f"Primary symbol {symbol} failed, trying XAUUSD=F...")
    df = _download("XAUUSD=F", period, interval)
    if df is not None:
        df = _postprocess(df)
        return df

    # Try local CSV if provided
    if fallback_csv and os.path.exists(fallback_csv):
        log.info(f"Loading from fallback CSV: {fallback_csv}")
        df = pd.read_csv(fallback_csv, index_col=0, parse_dates=True)
        df.rename(columns={
            'Open': 'open', 'High': 'high', 'Low': 'low',
            'Close': 'close', 'Volume': 'volume'
        }, inplace=True)
        df = _postprocess(df)
        if not df.empty:
            return df

    raise ValueError(f"No data available for {symbol} or fallback.")


def _download(symbol, period, interval):
    """Download from Yahoo, return raw DataFrame (or None)."""
    try:
        df = yf.download(symbol, period=period, interval=interval, progress=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        return df
    except Exception as e:
        log.warning(f"Download failed for {symbol} ({period}/{interval}): {e}")
        return None


def _postprocess(df):
    """Standardise columns, drop NaN bars, sort index, fill tiny gaps."""
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    df.rename(columns={
        'Open': 'open', 'High': 'high', 'Low': 'low',
        'Close': 'close', 'Volume': 'volume'
    }, inplace=True)

    # Ensure numeric types
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # Drop rows where OHLC is NaN (weekends, holidays)
    df.dropna(subset=['open', 'high', 'low', 'close'], inplace=True)

    # Forward‑fill volume for very short gaps (1–2 bars)
    df['volume'] = df['volume'].fillna(0)

    # Flag suspicious bars where high < low or open/close outside range
    suspicious = (df['high'] < df['low']) | (df['high'] < df['open']) | (df['high'] < df['close'])
    if suspicious.any():
        log.warning(f"Dropping {suspicious.sum()} suspicious bar(s) with high < low or high < open/close.")
        df = df[~suspicious]

    return df
