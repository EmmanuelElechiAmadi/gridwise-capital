import yfinance as yf
import pandas as pd
import os

def load_yfinance(symbol="GC=F", period="5d", interval="1m", fallback_csv=None):
    """
    Download data from Yahoo Finance. If it fails, try a fallback symbol,
    then a local CSV file.
    """
    # Try primary symbol
    df = _download(symbol, period, interval)
    if df is not None:
        return df

    # Try gold spot (often still available on weekends)
    print(f"Primary symbol {symbol} failed, trying XAUUSD=F...")
    df = _download("XAUUSD=F", period, interval)
    if df is not None:
        return df

    # Try local CSV if provided
    if fallback_csv and os.path.exists(fallback_csv):
        print(f"Loading from fallback CSV: {fallback_csv}")
        df = pd.read_csv(fallback_csv, index_col=0, parse_dates=True)
        df.rename(columns={'Open':'open','High':'high','Low':'low','Close':'close','Volume':'volume'}, inplace=True)
        if not df.empty:
            return df

    raise ValueError(f"No data available for {symbol} or fallback.")

def _download(symbol, period, interval):
    try:
        df = yf.download(symbol, period=period, interval=interval, progress=False)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df.index = pd.to_datetime(df.index)
        df.rename(columns={'Open':'open','High':'high','Low':'low','Close':'close','Volume':'volume'}, inplace=True)
        return df
    except Exception:
        return None