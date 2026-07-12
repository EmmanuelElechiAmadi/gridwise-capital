import yfinance as yf
import pandas as pd
import numpy as np
import os
import logging

log = logging.getLogger("QuantBot")

# Default fallback: look for gold_data.csv next to the project root
_DEFAULT_FALLBACK = os.path.join(os.path.dirname(__file__), "..", "..", "gold_data.csv")


def load_yfinance(symbol="GC=F", period="5d", interval="1m", fallback_csv=_DEFAULT_FALLBACK):
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
        Defaults to ``<project_root>/gold_data.csv``.

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
    if df is not None and not df.empty:
        df = _postprocess(df)
        return df

    # Try gold spot (often still available on weekends)
    log.warning(f"Primary symbol {symbol} failed, trying XAUUSD=F...")
    df = _download("XAUUSD=F", period, interval)
    if df is not None and not df.empty:
        df = _postprocess(df)
        return df

    # Try local CSV fallback
    if fallback_csv and os.path.exists(fallback_csv):
        log.info(f"Loading from fallback CSV: {fallback_csv}")
        try:
            df = pd.read_csv(fallback_csv, index_col=0, parse_dates=True)
            # Map the csv column names (Datetime, Open, High, Low, Close, Volume)
            # to the standard lowercase names expected by the rest of the engine
            rename_map = {
                'Open': 'open', 'High': 'high', 'Low': 'low',
                'Close': 'close', 'Volume': 'volume',
            }
            df.rename(columns=rename_map, inplace=True)
            df = _postprocess(df)
            if not df.empty:
                return df
            else:
                log.warning(f"Fallback CSV {fallback_csv} was empty after processing.")
        except Exception as e:
            log.warning(f"Could not load fallback CSV {fallback_csv}: {e}")
    elif fallback_csv:
        log.warning(f"Fallback CSV not found: {fallback_csv}")

    raise ValueError(f"No data available for {symbol} or fallback.")


def _download(symbol, period, interval):
    """Download from Yahoo, return raw DataFrame (or None)."""
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)
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

    # Only rename columns that exist (avoids errors if already lowercase)
    rename_map = {
        'Open': 'open', 'High': 'high', 'Low': 'low',
        'Close': 'close', 'Volume': 'volume'
    }
    cols_to_rename = {k: v for k, v in rename_map.items() if k in df.columns}
    if cols_to_rename:
        df.rename(columns=cols_to_rename, inplace=True)

    # Ensure numeric types
    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # Drop rows where OHLC is NaN (weekends, holidays)
    existing_ohlc = [c for c in ['open', 'high', 'low', 'close'] if c in df.columns]
    if existing_ohlc:
        df.dropna(subset=existing_ohlc, inplace=True)

    # Forward‑fill volume for very short gaps (1–2 bars)
    if 'volume' in df.columns:
        df['volume'] = df['volume'].fillna(0)

    # Flag suspicious bars where high < low or open/close outside range
    if 'high' in df.columns and 'low' in df.columns:
        suspicious = (df['high'] < df['low'])
        if 'open' in df.columns:
            suspicious |= (df['high'] < df['open'])
        if 'close' in df.columns:
            suspicious |= (df['high'] < df['close'])
        if suspicious.any():
            log.warning(
                f"Dropping {suspicious.sum()} suspicious bar(s) "
                f"with high < low or high < open/close."
            )
            df = df[~suspicious]

    return df