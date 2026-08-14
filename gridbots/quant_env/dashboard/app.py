#!/usr/bin/env python3
"""
Flask dashboard for the GridBot trading environment.
Start with:  python3 launcher.py dashboard

Supports MULTI-ACCOUNT trading — each broker account runs its own
GridBot in a background thread, fully isolated.
"""
import json
import os
import subprocess
import sys
import threading
import tempfile
import time
import random
import math
from pathlib import Path

from flask import Flask, render_template, request, jsonify
import requests as http_requests

# ── Ensure we can import from quant_env ──────────────────────────────
# app.py is at  gridbots/quant_env/dashboard/app.py
# project root is gridbots/ (3 levels up)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Config check ─────────────────────────────────────────────────────
CONFIG_PATH = PROJECT_ROOT / "quant_env" / "config.py"
if not CONFIG_PATH.exists():
    print("=" * 60)
    print("  ERROR: config.py not found!")
    print(f"  Expected at: {CONFIG_PATH}")
    print()
    print("  Create it from the example:")
    print(f"    cp {PROJECT_ROOT}/quant_env/config.example.py {CONFIG_PATH}")
    print("=" * 60)
    sys.exit(1)

print(f"  Using config: {CONFIG_PATH}")

from quant_env.config import Config

app = Flask(__name__)


@app.after_request
def _add_cors_headers(response):
    """Allow the Next.js dashboard (any origin, dev-friendly) to call this API."""
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return response


@app.route('/api/<path:_path>', methods=['OPTIONS'])
def _cors_preflight(_path):
    return ('', 204)

# ── Shared state ──────────────────────────────────────────────────────
# manager is a GridBotManager instance that orchestrates all accounts
_manager = None
_manager_lock = threading.Lock()

_BRIDGE_SESSION = None

# ── Strategy results storage ──────────────────────────────────────────
STRATEGY_RESULTS_PATH = PROJECT_ROOT / "quant_env" / "strategy_results.json"


def _get_manager():
    """Lazy-initialize and return the GridBotManager singleton."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                from quant_env.main import GridBotManager
                _manager = GridBotManager()
                # Ensure at least one default account exists
                _manager.account_manager.ensure_default_account()
    return _manager


def _load_strategy_results() -> dict:
    """Load persisted strategy performance results from disk."""
    if STRATEGY_RESULTS_PATH.exists():
        try:
            with open(STRATEGY_RESULTS_PATH, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_strategy_results(results: dict):
    """Persist strategy performance results to disk."""
    try:
        STRATEGY_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(STRATEGY_RESULTS_PATH, 'w') as f:
            json.dump(results, f, indent=2, default=str)
    except Exception as e:
        print(f"[StrategyResults] Could not save: {e}")


def _update_strategy_result(strategy_key: str, operation: str, metrics: dict):
    """Update the stored result for a strategy after a backtest/optimize/etc."""
    results = _load_strategy_results()
    if strategy_key not in results:
        results[strategy_key] = {}
    results[strategy_key][operation] = {
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'metrics': metrics,
    }
    _save_strategy_results(results)


def _get_bridge_url() -> str:
    """Return the broker bridge URL from Config or env, fallback to localhost."""
    return (os.environ.get('BRIDGE_URL')
            or getattr(Config, 'BRIDGE_URL', 'http://127.0.0.1:8080'))


def _try_bridge_status():
    """Fetch live account/status from the MT5 bridge server."""
    global _BRIDGE_SESSION
    if _BRIDGE_SESSION is None:
        _BRIDGE_SESSION = http_requests.Session()
    url = f"{_get_bridge_url()}/account_info"
    try:
        resp = _BRIDGE_SESSION.get(url, timeout=1.5)
        if resp.status_code == 200:
            acct = resp.json()
            pos_url = f"{_get_bridge_url()}/positions"
            try:
                pos_resp = _BRIDGE_SESSION.get(pos_url, timeout=1.0)
                positions = pos_resp.json() if pos_resp.status_code == 200 else []
            except Exception:
                positions = []

            net_pos = 0.0
            dir_str = "Neutral"
            if positions:
                for p in positions:
                    vol = float(p.get("volume", 0))
                    net_pos += vol if p.get("type") == "buy" else -vol
                dir_str = "Long" if net_pos > 0 else "Short"

            from quant_env.config import Config as Cfg
            sym = Cfg.SYMBOL if hasattr(Cfg, 'SYMBOL') else "XAUUSD"
            tick_url = f"{_get_bridge_url()}/symbol_tick?symbol={sym}"
            latest_price = None
            try:
                tr = _BRIDGE_SESSION.get(tick_url, timeout=1.0)
                if tr.status_code == 200:
                    latest_price = tr.json().get("bid")
            except Exception:
                pass

            balance = float(acct.get("balance", 0))
            equity = float(acct.get("equity", 0))
            pnl = equity - balance
            pnl_pct = (pnl / balance * 100) if balance else 0.0

            return {
                "balance": round(balance, 2),
                "equity": round(equity, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "num_orders": len(positions),
                "max_drawdown": 0.0,
                "regime": "unknown",
                "regime_confidence": 0.0,
                "position_direction": dir_str,
                "net_position": round(net_pos, 2),
                "latest_price": latest_price,
            }
    except (http_requests.exceptions.ConnectionError,
            http_requests.exceptions.Timeout):
        pass
    return None


# ── Helper: run analysis / backtest scripts ──────────────────────────

def _run_script(script_name, *args):
    """Run a quant_env script and capture stdout."""
    script = PROJECT_ROOT / "quant_env" / script_name
    if not script.exists():
        script = PROJECT_ROOT / script_name
    cmd = [sys.executable or "python3", str(script), *args]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
    return result.stdout + result.stderr


def _run_launcher_command(cmd_type):
    """Run a launcher.py subcommand."""
    launcher = PROJECT_ROOT / "launcher.py"
    cmd = [sys.executable or "python3", str(launcher), cmd_type]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
    return result.stdout + result.stderr


def _format_result(raw_text: str) -> str:
    """Convert raw CLI output into minimal HTML for the dashboard."""
    lines = raw_text.split("\n")
    html = "<div class='cli-result'>"
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if line.startswith("=" * 3):
            html += f"<div class='cli-section-header'>{stripped.strip('=')}</div>"
        else:
            html += f"<div class='cli-line'>{stripped}</div>"
    html += "</div>"
    return html


# ── Stub helpers for dashboard data ────────────────────────────────────

def _default_account_id():
    """Return the id of the first configured account (the bot logs trades and
    equity to trade_data/trades_<account_id>.db).  Falls back to 'default'."""
    try:
        mgr = _get_manager()
        accounts = mgr.account_manager.list_accounts()
        if accounts:
            return accounts[0].id
    except Exception:
        pass
    return "default"


def _get_recent_trades(account_id=None, limit=50):
    """Return the CURRENT account's recent trades (no historical fallback).

    Rows are NORMALISED to the frontend contract
    (timestamp/symbol/side/price/volume/pnl) regardless of the underlying
    DB schema, so the dashboard never renders blank rows.
    """
    from quant_env.analysis.trade_logger import TradeLogger
    try:
        logger = TradeLogger(account_id=account_id or _default_account_id())
        rows = logger.get_recent(limit)
        logger.close()
        out = []
        for r in rows or []:
            out.append({
                'timestamp': (r.get('timestamp') or r.get('time')
                              or r.get('datetime') or r.get('created_at')),
                'symbol': (r.get('symbol') or r.get('instrument')
                           or r.get('ticker')),
                'side': (r.get('side') or r.get('type')
                         or r.get('direction') or ''),
                'price': (r.get('price') or r.get('entry_price')
                          or r.get('open_price')),
                'volume': (r.get('volume') or r.get('lots')
                           or r.get('qty')),
                'pnl': (r.get('pnl') or r.get('profit')
                        or r.get('realized_pnl')),
            })
        return out
    except Exception:
        return []


def _get_performance_metrics(account_id=None):
    """Return aggregated performance metrics for the CURRENT account."""
    from quant_env.analysis.trade_logger import TradeLogger
    from quant_env.analysis.performance import compute_metrics
    try:
        logger = TradeLogger(account_id=account_id or _default_account_id())
        trades = logger.get_recent(500)
        logger.close()
        if trades:
            import pandas as pd
            fills = pd.DataFrame(trades)
            if 'equity' not in fills.columns:
                equity = pd.DataFrame({'equity': [10000] * len(fills)})
            else:
                equity = pd.DataFrame({'equity': fills['equity']})
            return compute_metrics(fills, equity)
        return None
    except Exception:
        return None


def _get_equity_curve(account_id=None):
    """Return the CURRENT account's equity curve (no historical fallback)."""
    from quant_env.analysis.trade_logger import TradeLogger
    try:
        logger = TradeLogger(account_id=account_id or _default_account_id())
        rows = logger.get_equity_curve()
        logger.close()
        return rows or []
    except Exception:
        return []


# ── Simulation helpers (demo mode when no broker connected) ──────────

_sim_start_time = time.time()

def _generate_demo_status():
    """Generate realistic demo data when no broker/bot is connected."""
    elapsed = time.time() - _sim_start_time
    base_balance = 10000.0
    drift = 50.0 * math.sin(elapsed / 30.0) + 20.0 * math.sin(elapsed / 7.0)
    sim_equity = base_balance + drift
    sim_pnl = sim_equity - base_balance
    sim_pnl_pct = (sim_pnl / base_balance) * 100.0
    regimes = ['ranging', 'trending', 'unknown']
    regime_idx = int((elapsed // 20) % 3)
    regime = regimes[regime_idx]
    conf = 45.0 + 40.0 * (0.5 + 0.5 * math.sin(elapsed / 10.0))
    sim_price = 2350.0 + 5.0 * math.sin(elapsed / 15.0) + random.gauss(0, 0.5)
    return {
        'trading_active': False,
        'has_bot': False,
        'broker_connected': False,
        'balance': base_balance,
        'equity': round(sim_equity, 2),
        'pnl': round(sim_pnl, 2),
        'pnl_pct': round(sim_pnl_pct, 2),
        'num_orders': 0,
        'max_drawdown': round(abs(drift) / base_balance * 100, 2),
        'regime': regime,
        'regime_confidence': round(min(conf, 95.0), 1),
        'position_direction': 'Neutral',
        'net_position': 0.0,
        'latest_price': round(sim_price, 2),
        'grid_spacing': 2.0,
        'grid_levels': 3,
        'active_strategy': None,
    }


# ── Kronos forecast computation (RF-model fallback) ──────────────────
# The dashboard's Kronos widget expects /api/status to include a `kronos`
# dict (regime_label, trend, trend_strength, volatility_forecast,
# price_min/max_forecast, price_range).  The engine only produces this via
# the optional Kronos foundation model, so here we compute a live forecast
# from the trained RandomForest regime model + the latest gold data.  The
# result is cached for 2 minutes so the 5s dashboard poll stays cheap.

_kronos_cache = {'ts': 0.0, 'data': None}

# Live XAU/USD spot cache (gold-api.com — free, no key).  The dashboard
# anchors to SPOT because the bot trades XAUUSD.r; GC=F futures carry a
# basis premium/discount (spot $4,334 vs futures $4,389 on 2026-08-14).
_spot_cache = {'ts': 0.0, 'data': None}


def _fetch_live_spot(max_age=45.0):
    """Live XAU/USD spot from gold-api.com (free, no key, short timeout).

    Returns ``{'price': float, 'ts': float, 'source': str}`` or ``None``.
    Cached ``max_age`` seconds; never raises.
    """
    global _spot_cache
    now = time.time()
    if _spot_cache['data'] is not None and (now - _spot_cache['ts']) < max_age:
        return _spot_cache['data']
    data = None
    try:
        r = http_requests.get('https://api.gold-api.com/price/XAU', timeout=6.0)
        if r.status_code == 200:
            j = r.json()
            price = float(j.get('price') or 0.0)
            if price > 0:
                data = {'price': round(price, 2), 'ts': now,
                        'source': 'XAU/USD spot (gold-api.com)'}
    except Exception as e:
        print(f"[Kronos] spot fetch failed: {e}")
    _spot_cache = {'ts': now, 'data': data}
    return data
_kronos_model = None


def _load_regime_model():
    """Load the trained RegimeClassifier (cached globally)."""
    global _kronos_model
    if _kronos_model is not None:
        return _kronos_model
    try:
        import sys as _sys
        qenv = str(PROJECT_ROOT / "quant_env")
        if qenv not in _sys.path:
            _sys.path.insert(0, qenv)
        from ml.regime_model import RegimeClassifier
        path = os.path.join(qenv, "ml", "model.pkl")
        if os.path.exists(path):
            _kronos_model = RegimeClassifier.load(path)
            print(f"[Kronos] loaded regime model from {path}")
        else:
            _kronos_model = None
    except Exception as e:
        print(f"[Kronos] model load failed: {e}")
        _kronos_model = None
    return _kronos_model


def _load_recent_bars(max_age_hours=6.0):
    """Load recent OHLCV bars for the Kronos/RF forecast.

    Runs inside /api/status (polled every 5 s) and must never block:

      1) local ``gold_data.csv`` snapshot  (instant) — ONLY when FRESH.  A
         stale snapshot (e.g. 3 days old) is what froze the dashboard's
         price and every forecast "since yesterday night".
      2) live Yahoo Finance                 (5 s timeout) — used when the
         local snapshot is stale, so the forecast tracks the market NOW.
      3) broker bridge 1H bars              (3 s timeout) — the instrument
         actually traded (XAUUSD.r).
      4) the stale local snapshot           (last resort — better than none)

    Never raises.
    """
    import pandas as pd
    bars = None
    stale_bars = None

    # 1) Local snapshot (fast, offline-safe) — only when fresh.
    path = PROJECT_ROOT / "gold_data.csv"
    if path.exists():
        try:
            df = pd.read_csv(str(path))
            df['Datetime'] = pd.to_datetime(df['Datetime'], utc=True, errors='coerce')
            df = df.dropna(subset=['Datetime']).set_index('Datetime')
            df.columns = [c.lower() for c in df.columns]
            if all(c in df.columns for c in ('open', 'high', 'low', 'close', 'volume')):
                bars = df.tail(800)
        except Exception as e:
            print(f"[Kronos] local data load failed: {e}")
        if bars is not None:
            try:
                age_h = (pd.Timestamp.now(tz='UTC') - bars.index[-1]).total_seconds() / 3600.0
            except Exception:
                age_h = 0.0
            if age_h <= max_age_hours:
                return bars
            stale_bars = bars
            bars = None

    # 2) Live Yahoo Finance (GC=F gold futures) — try FIRST when the local
    #    snapshot is stale so forecasts track the market, not last week.
    try:
        import yfinance as yf
        df = yf.download("GC=F", period="1mo", interval="1h",
                         progress=False, auto_adjust=False, timeout=5)
        if df is not None and not df.empty:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.rename(columns={'Open': 'open', 'High': 'high', 'Low': 'low',
                                    'Close': 'close', 'Volume': 'volume'})
            keep = [c for c in ('open', 'high', 'low', 'close', 'volume') if c in df.columns]
            if len(keep) >= 5:
                df = df[keep].dropna()
                if len(df) > 40:
                    bars = df.tail(800)
    except Exception as e:
        print(f"[Kronos] live fetch failed (will use local snapshot): {e}")

    if bars is not None:
        return bars

    # 3) Broker's own 1H bars (XAUUSD.r spot) — the instrument actually traded
    try:
        r = http_requests.get(f"{_get_bridge_url()}/bars", timeout=3.0)
        if r.status_code == 200:
            payload = r.json()
            rows = payload.get('bars') or []
            if len(rows) >= 20:
                df = pd.DataFrame(rows)
                df['Datetime'] = pd.to_datetime(df.get('start', pd.Series(dtype='float')), unit='s', utc=True, errors='coerce')
                df = df.set_index('Datetime').sort_index()
                keep = [c for c in ('open', 'high', 'low', 'close', 'volume') if c in df.columns]
                if len(keep) >= 5:
                    bars = df[keep].dropna().tail(800)
    except Exception as e:
        print(f"[Kronos] bridge bars fetch failed: {e}")

    if bars is not None:
        return bars

    # 4) Last resort: the stale local snapshot — better than nothing.
    return stale_bars


_kronos_pred_cache = {'obj': None, 'checked': False, 'loading': False}


def _try_kronos_foundation(df):
    """Attempt the actual Kronos foundation-model forecast.

    Returns a forecast dict (source='kronos_model') or None.  CRITICAL:
    the dashboard/status request path must NEVER block on a HuggingFace
    download, so:

      - unless ``KRONOS_FOUNDATION_DASHBOARD=1`` is set, this is skipped
        entirely (the RF/momentum fallback powers the widget);
      - the model load (when enabled) happens in a BACKGROUND thread — the
        first requests return None immediately and fall back gracefully.
    """
    global _kronos_pred_cache
    if os.getenv("KRONOS_FOUNDATION_DASHBOARD", "0") != "1":
        return None
    if _kronos_pred_cache['loading']:
        return None  # model is loading in the background — don't block
    try:
        if not _kronos_pred_cache['checked']:
            _kronos_pred_cache['loading'] = True

            def _load():
                try:
                    from ml.kronos import KronosPricePredictor
                    _kronos_pred_cache['obj'] = KronosPricePredictor()
                except Exception as e:
                    print(f"[Kronos] foundation import failed: {e}")
                    _kronos_pred_cache['obj'] = None
                finally:
                    _kronos_pred_cache['checked'] = True
                    _kronos_pred_cache['loading'] = False

            threading.Thread(target=_load, daemon=True).start()
            return None

        pred = _kronos_pred_cache['obj']
        if pred is None or not pred.is_available():
            return None
        feats = pred.get_forecast_features(df)
        if not feats or not feats.get('regime_label'):
            return None
        last_price = float(df['close'].iloc[-1]) if len(df) else 0.0
        ts = float(feats.get('trend_strength') or 0.0)
        return {
            'regime_label': str(feats['regime_label']).upper(),
            'volatility_forecast': round(float(feats.get('volatility_forecast') or 0.0), 6),
            'trend': round(float(feats.get('trend') or 0.0), 6),
            'trend_strength': round(min(float(ts), 9.99), 2),
            'price_range': round(float(feats.get('price_range') or 0.0), 2),
            'price_min_forecast': round(float(feats.get('price_min_forecast') or last_price), 2),
            'price_max_forecast': round(float(feats.get('price_max_forecast') or last_price), 2),
            'confidence': round(min(0.9, 0.3 + float(ts) * 0.4), 4),
            'source': 'kronos_model',
            'model': 'Kronos foundation',
            'last_price': round(last_price, 2),
            'computed_at': time.time(),
        }
    except Exception as e:
        print(f"[Kronos] foundation forecast failed: {e}")
    return None


def _compute_kronos_forecast(force=False):
    """Compute a live forecast from Yahoo Finance gold data + RF model.

    Guaranteed to return a forecast dict whenever ANY market bars are
    available (RandomForest when confident, otherwise a live momentum rule).
    Never emits NaN/Inf.  Returns None only if no market data at all exists.
    """
    global _kronos_cache
    now = time.time()
    if (not force and _kronos_cache['data'] is not None
            and (now - _kronos_cache['ts']) < 60):
        return _kronos_cache['data']

    result = None
    last_error = None
    try:
        import numpy as np
        import pandas as pd
        bars = _load_recent_bars()
        if bars is None or len(bars) < 20:
            last_error = "No market data (live fetch + local snapshot unavailable)"
        else:
            closes = pd.to_numeric(bars['close'], errors='coerce').dropna()
            last_price = float(closes.iloc[-1])
            rets = closes.pct_change().dropna()
            vol_bar = float(rets.tail(250).std()) if len(rets) > 1 else 0.0
            if vol_bar is None or not np.isfinite(vol_bar) or vol_bar <= 0:
                vol_bar = 1e-6
            try:
                delta_s = bars.index.to_series().diff().dt.total_seconds().median()
            except Exception:
                delta_s = 3600.0
            if not np.isfinite(delta_s) or delta_s <= 0:
                delta_s = 3600.0
            bar_frac_year = delta_s / (365.25 * 86400.0)
            annual_factor = (1.0 / bar_frac_year) ** 0.5 if bar_frac_year > 0 else 1.0
            vol_annualized = vol_bar * annual_factor

            n = min(20, len(closes) - 1)
            window = closes.tail(n)
            trend = float(window.iloc[-1]) / float(window.iloc[0]) - 1.0 if len(window) > 1 else 0.0
            if not np.isfinite(trend):
                trend = 0.0
            exp_vol = vol_bar * (n ** 0.5)
            trend_strength = abs(trend) / exp_vol if exp_vol > 0 else 0.0
            if not np.isfinite(trend_strength):
                trend_strength = 0.0
            hvol = vol_bar * (20 ** 0.5)
            low = last_price * (1 - hvol)
            high = last_price * (1 + hvol)

            # Kronos foundation model (best effort) — highest priority
            kronos_fc = _try_kronos_foundation(bars)

            # RF model (best effort, only used when confident)
            rf_label, rf_conf = None, 0.0
            try:
                model = _load_regime_model()
                if model is not None and len(bars) > model.lookback + 15:
                    from ml.data_builder import build_features
                    X, _ = build_features(bars, lookback=model.lookback,
                                          regime_threshold=model.regime_threshold)
                    if X is not None and not X.empty:
                        pred = model.predict_with_confidence(X.iloc[-1:])
                        rf_label = pred.get('regime_name')
                        rf_conf = float(pred.get('confidence') or 0.0)
            except Exception as e:
                last_error = f"RF model unavailable: {e}"

            if rf_label and rf_conf >= 0.45:
                regime_label = rf_label.upper()
                confidence = rf_conf
                source, model_name = 'rf_regime_model', 'RandomForest'
            else:
                regime_label = ('BULL' if trend >= 0 else 'BEAR') if trend_strength >= 0.8 else 'RANGING'
                confidence = min(0.9, 0.3 + trend_strength * 0.4)
                source, model_name = 'live_momentum', 'Momentum'

            result = {
                'regime_label': regime_label,
                'volatility_forecast': round(vol_annualized, 6),
                'trend': round(trend, 6),
                'trend_strength': round(min(trend_strength, 9.99), 2),
                'price_range': round(high - low, 2),
                'price_min_forecast': round(low, 2),
                'price_max_forecast': round(high, 2),
                'confidence': round(confidence, 4),
                'source': source,
                'model': model_name,
                'last_price': round(last_price, 2),
                'computed_at': now,
                'last_error': last_error,
            }
            if kronos_fc is not None:
                result = kronos_fc
    except Exception as e:
        print(f"[Kronos] forecast computation failed: {e}")
        result = None

    # ── Anchor to LIVE XAU/USD spot (the traded instrument) ────────────
    # GC=F futures carry a basis premium vs spot (e.g. +$56 on 2026-08-14).
    # The bot trades XAUUSD.r spot, so the forecast levels and the breakout
    # must be spot-denominated — shift the futures-derived levels by the basis.
    if result is not None:
        try:
            spot = _fetch_live_spot()
            if spot and result.get('last_price'):
                basis = result['last_price'] - spot['price']
                futures_last = result['last_price']
                result['last_price'] = spot['price']
                if result.get('price_min_forecast'):
                    result['price_min_forecast'] = round(
                        result['price_min_forecast'] - basis, 2)
                if result.get('price_max_forecast'):
                    result['price_max_forecast'] = round(
                        result['price_max_forecast'] - basis, 2)
                result['spot_price'] = spot['price']
                result['futures_last'] = round(futures_last, 2)
                result['basis'] = round(basis, 2)
                result['price_source'] = spot['source']
        except Exception as e:
            print(f"[Kronos] spot anchoring failed: {e}")

    _kronos_cache = {'ts': now, 'data': result}
    return result


_bridge_health_cache = {'ts': 0.0, 'data': None}


def _try_bridge_health():
    """Return the bridge /status payload (mode, files) with a short cache."""
    global _bridge_health_cache
    now = time.time()
    if _bridge_health_cache['data'] is not None and (now - _bridge_health_cache['ts']) < 10:
        return _bridge_health_cache['data']
    data = None
    try:
        r = http_requests.get(f"{_get_bridge_url()}/status", timeout=2.0)
        if r.status_code == 200:
            data = r.json()
    except Exception:
        data = None
    _bridge_health_cache = {'ts': now, 'data': data}
    return data


def _attach_bridge_status(status_dict):
    """Add a `bridge` summary to a status dict so the UI can show live vs demo."""
    h = _try_bridge_health()
    if h:
        status_dict['bridge'] = {
            'mode': h.get('mode', 'unknown'),
            'connected': bool(h.get('ea_running')),
            'ea_running': bool(h.get('ea_running')),
            'files_dir': h.get('mt5_files_dir'),
            'hint': h.get('hint', ''),
        }
    else:
        status_dict['bridge'] = {'mode': 'offline', 'connected': False, 'ea_running': False, 'files_dir': None}
    return status_dict


def _compute_breakout_forecast(kronos):
    """Derive a simple breakout estimate from the regime forecast."""
    if not kronos or not kronos.get('last_price'):
        return None
    last_price = float(kronos['last_price'])
    regime = kronos.get('regime_label', 'RANGING')
    conf = float(kronos.get('confidence', 0.0))
    risk = max(float(kronos.get('price_range', 0.0)) / 4.0, 0.01)

    if regime == 'BULL' and conf >= 0.45:
        direction, status = 'BULLISH', 'active_bull'
    elif regime == 'BEAR' and conf >= 0.45:
        direction, status = 'BEARISH', 'active_bear'
    elif regime == 'BULL':
        direction, status = 'BULLISH', 'idle'
    elif regime == 'BEAR':
        direction, status = 'BEARISH', 'idle'
    else:
        direction, status = 'NEUTRAL', 'idle'

    if status == 'active_bear':
        stop_loss = round(last_price + risk, 2)
        take_profit = round(last_price - risk * 2.0, 2)
    else:
        stop_loss = round(last_price - risk, 2)
        take_profit = round(last_price + risk * 2.0, 2)

    rr = (abs(take_profit - last_price) / risk) if risk > 0 else 0.0
    return {
        'status': status,
        'direction': direction,
        'entry_price': round(last_price, 2),
        'stop_loss': stop_loss,
        'take_profit': take_profit,
        'r_multiple': round(rr, 2),
        'confidence': conf,
        'source': kronos.get('source', 'rf_regime_model'),
    }


def _compute_live_drawdown():
    """Max drawdown % from the current account's live equity snapshots.

    Works even before any trades are filled — the equity curve itself
    captures floating P&L swings.  Cached for 30s.
    """
    global _dd_cache
    now = time.time()
    if _dd_cache['value'] is not None and (now - _dd_cache['ts']) < 30:
        return _dd_cache['value']
    rows = _get_equity_curve(None)
    eqs = []
    for r in rows:
        try:
            eqs.append(float(r[1]))
        except (TypeError, ValueError, IndexError):
            continue
    dd = None
    if len(eqs) >= 2:
        peak = eqs[0]
        max_dd = 0.0
        for e in eqs:
            if e > peak:
                peak = e
            if peak > 0:
                d = (peak - e) / peak * 100.0
                if d > max_dd:
                    max_dd = d
        dd = round(max_dd, 2)
    _dd_cache = {'ts': now, 'value': dd}
    return dd


_dd_cache = {'ts': 0.0, 'value': None}


def _attach_forecast_data(status_dict):
    """Add kronos / kronos_breakout / current_price + real regime to a status dict."""
    # Use a truthy check: the bot's status may carry kronos={} (empty), which
    # means "no forecast" — recompute a real one in that case.
    if status_dict.get('kronos'):
        k = status_dict.get('kronos')
    else:
        k = _compute_kronos_forecast()
        status_dict['kronos'] = k
        status_dict['kronos_breakout'] = _compute_breakout_forecast(k)
    # When the bot's own adapter supplied the forecast it is futures-based
    # (GC=F) — anchor it to LIVE XAU/USD spot too, so levels match the traded
    # instrument and the Price tile never freezes on a dead bridge tick.
    if k and k.get('last_price') and not k.get('spot_price'):
        try:
            spot = _fetch_live_spot()
            if spot:
                basis = k['last_price'] - spot['price']
                futures_last = k['last_price']
                k['last_price'] = spot['price']
                if k.get('price_min_forecast'):
                    k['price_min_forecast'] = round(k['price_min_forecast'] - basis, 2)
                if k.get('price_max_forecast'):
                    k['price_max_forecast'] = round(k['price_max_forecast'] - basis, 2)
                k['spot_price'] = spot['price']
                k['futures_last'] = round(futures_last, 2)
                k['basis'] = round(basis, 2)
                k['price_source'] = spot['source']
        except Exception:
            pass
    # Recompute the breakout from the spot-anchored forecast so Entry/SL/TP
    # are denominated in the traded instrument, not the futures basis.
    if k and k.get('spot_price'):
        status_dict['kronos_breakout'] = _compute_breakout_forecast(k)
    if k and k.get('spot_price'):
        # The bridge tick freezes the moment MT5 stops streaming, leaving a
        # stale quote on the dashboard.  Prefer the LIVE XAU/USD spot the
        # forecast was anchored to — it is authoritative and at most 45s old.
        status_dict['current_price'] = k['spot_price']
        status_dict['price_source'] = k.get('price_source')
        if k.get('basis') is not None:
            status_dict['futures_basis'] = k['basis']
    elif status_dict.get('current_price') is None:
        status_dict['current_price'] = (
            status_dict.get('latest_price')
            or (k.get('last_price') if k else None)
        )
    # Surface the real detected regime instead of 'unknown' placeholders
    cur = (status_dict.get('regime') or '').lower()
    if cur in ('', 'unknown', 'ml_disabled', 'trending') and k and k.get('regime_label'):
        status_dict['regime'] = k['regime_label'].lower()
        status_dict['regime_confidence'] = round((k.get('confidence') or 0.0) * 100, 1)
    # Derive a directional model signal for the Position widget
    if k and k.get('regime_label'):
        label = k['regime_label'].upper()
        if label == 'BULL':
            status_dict['signal_bias'] = 'Long'
        elif label == 'BEAR':
            status_dict['signal_bias'] = 'Short'
        else:
            status_dict['signal_bias'] = 'Neutral'
    # Real max drawdown from the live equity curve (works before any fills)
    if not status_dict.get('max_drawdown'):
        dd = _compute_live_drawdown()
        if dd is not None:
            status_dict['max_drawdown'] = dd
    # Surface the MT5 bridge mode (live vs demo) so failures are visible
    return _attach_bridge_status(status_dict)


def _forecast_regime_label():
    """Return the RF forecast regime (lowercase) or 'unknown'."""
    k = _compute_kronos_forecast()
    if k and k.get('regime_label'):
        return k['regime_label'].lower()
    return 'unknown'





# ── Routes ────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('dashboard.html')


@app.route('/api/equity_chart')
@app.route('/equity_chart')
def equity_chart():
    account_id = request.args.get('account_id')
    data = _get_equity_curve(account_id)
    # Downsample to ~500 points and format for the Chart.js linear x-axis.
    # Each row is a (timestamp, equity) tuple.
    step = max(1, len(data) // 500)
    out = []
    for i, row in enumerate(data[::step]):
        try:
            eq = float(row[1])
        except (TypeError, ValueError, IndexError):
            continue
        out.append({'x': i, 'y': eq})
    return jsonify(out)


@app.route('/api/performance')
@app.route('/performance')
def performance():
    account_id = request.args.get('account_id')
    metrics = _get_performance_metrics(account_id)
    if metrics is None:
        return jsonify({'status': 'no_trades'})
    return jsonify({
        'status': 'ok',
        'win_rate_pct': metrics.get('win_rate_pct', 0),
        'profit_factor': metrics.get('profit_factor', 0),
        'sharpe_ratio': metrics.get('sharpe_ratio', 0),
        'num_trades': metrics.get('num_trades', 0),
        'total_return_pct': metrics.get('total_return_pct', 0),
        'avg_win': metrics.get('avg_win', 0),
        'avg_loss': metrics.get('avg_loss', 0),
        'max_drawdown_pct': metrics.get('max_drawdown_pct', 0),
    })


@app.route('/api/recent_trades')
@app.route('/recent_trades')
def recent_trades():
    account_id = request.args.get('account_id')
    trades = _get_recent_trades(account_id, 50)
    return jsonify(trades)


@app.route('/export_trades')
def export_trades():
    account_id = request.args.get('account_id')
    trades = _get_recent_trades(account_id, 500)
    csv_rows = ["timestamp,symbol,side,price,volume,pnl"]
    for t in trades:
        csv_rows.append(
            f"{t.get('timestamp','')},{t.get('symbol','')},{t.get('side','')},"
            f"{t.get('price',0)},{t.get('volume',0)},{t.get('pnl',0)}"
        )
    csv_content = "\n".join(csv_rows)
    return csv_content, 200, {'Content-Type': 'text/csv', 'Content-Disposition': 'attachment; filename=trades.csv'}


# ═══════════════════════════════════════════════════════════════════════
#  ACCOUNT API ROUTES
# ═══════════════════════════════════════════════════════════════════════

@app.route('/api/accounts', methods=['GET'])
def api_list_accounts():
    """List all brokerage accounts with their status."""
    mgr = _get_manager()
    accounts = mgr.account_manager.list_accounts()
    statuses = {s['account_id']: s for s in mgr.all_statuses()}
    result = []
    for acct in accounts:
        info = statuses.get(acct.id, {})
        result.append({
            'id': acct.id,
            'label': acct.label,
            'user_id': acct.user_id,
            'broker_type': acct.broker_type.value,
            'connection_status': acct.status.value,
            'enabled': acct.enabled,
            'created_at': acct.created_at.isoformat(),
            'updated_at': acct.updated_at.isoformat(),
            'last_error': acct.last_error,
            # Live data from the bot if running
            'balance': info.get('balance', 0.0),
            'equity': info.get('equity', 0.0),
            'total_pnl': info.get('total_pnl', 0.0),
            'active_orders': info.get('active_orders', 0),
            'open_positions': info.get('open_positions', 0),
            'paused': info.get('paused', True),
            'regime': info.get('regime', 'unknown'),
            'position_direction': info.get('position_direction', 'Neutral'),
        })
    return jsonify({'accounts': result})


@app.route('/api/accounts/<account_id>', methods=['GET'])
def api_get_account(account_id):
    """Get details for a single account."""
    mgr = _get_manager()
    acct = mgr.account_manager.get_account(account_id)
    if acct is None:
        return jsonify({'status': 'error', 'message': 'Account not found'}), 404
    statuses = {s['account_id']: s for s in mgr.all_statuses()}
    info = statuses.get(account_id, {})
    return jsonify({
        'id': acct.id,
        'label': acct.label,
        'user_id': acct.user_id,
        'broker_type': acct.broker_type.value,
        'connection_status': acct.status.value,
        'enabled': acct.enabled,
        'connection_config': {k: v for k, v in acct.connection_config.items()
                              if k != 'password'},
        'trading_config': acct.trading_config,
        'risk_config': acct.risk_config,
        'created_at': acct.created_at.isoformat(),
        'updated_at': acct.updated_at.isoformat(),
        'last_error': acct.last_error,
        'balance': info.get('balance', 0.0),
        'equity': info.get('equity', 0.0),
        'total_pnl': info.get('total_pnl', 0.0),
    })


@app.route('/api/accounts', methods=['POST'])
def api_create_account():
    """Create a new brokerage account."""
    data = request.get_json() or {}
    label = data.get('label', '')
    broker_type = data.get('broker_type', 'mt5_bridge')
    connection_config = data.get('connection_config', {})
    trading_config = data.get('trading_config', {})
    risk_config = data.get('risk_config', {})

    if not label:
        return jsonify({'status': 'error', 'message': 'Label is required'}), 400

    from quant_env.accounts.models import BrokerType
    try:
        bt = BrokerType(broker_type)
    except ValueError:
        return jsonify({'status': 'error', 'message': f'Invalid broker_type: {broker_type}'}), 400

    mgr = _get_manager()
    acct = mgr.account_manager.create_account(
        label=label,
        broker_type=bt,
        connection_config=connection_config,
        trading_config=trading_config,
        risk_config=risk_config,
    )
    return jsonify({'status': 'ok', 'account': {'id': acct.id, 'label': acct.label}}), 201


@app.route('/api/accounts/<account_id>', methods=['PUT'])
def api_update_account(account_id):
    """Update an existing account."""
    data = request.get_json() or {}
    mgr = _get_manager()
    acct = mgr.account_manager.update_account(account_id, data)
    if acct is None:
        return jsonify({'status': 'error', 'message': 'Account not found'}), 404
    return jsonify({'status': 'ok', 'account': {'id': acct.id, 'label': acct.label}})


@app.route('/api/accounts/<account_id>', methods=['DELETE'])
def api_delete_account(account_id):
    """Delete an account and stop its bot if running."""
    mgr = _get_manager()
    mgr.stop_bot(account_id)
    deleted = mgr.account_manager.delete_account(account_id)
    if not deleted:
        return jsonify({'status': 'error', 'message': 'Account not found'}), 404
    return jsonify({'status': 'ok', 'message': 'Account deleted'})


@app.route('/api/accounts/<account_id>/test', methods=['POST'])
def api_test_account_connection(account_id):
    """Test connection to the broker for this account."""
    mgr = _get_manager()
    ok = mgr.account_manager.test_connection(account_id)
    acct = mgr.account_manager.get_account(account_id)
    return jsonify({
        'status': 'ok' if ok else 'error',
        'connected': ok,
        'connection_status': acct.status.value if acct else 'unknown',
        'last_error': acct.last_error if acct else None,
    })


# ═══════════════════════════════════════════════════════════════════════
#  BOT CONTROL API ROUTES
# ═══════════════════════════════════════════════════════════════════════

def _build_account_status(acct, bridge_data=None, bot_status=None):
    """
    Build a unified BotStatus dict for a single account.
    
    Merges data from:
      - The BrokerAccount itself (identity, connection status)
      - A running bot's status dict (if available)
      - Live bridge data from _try_bridge_status (if no bot running)
    
    Returns a dict matching the BotStatus interface the frontend expects.
    """
    result = {
        'account_id': acct.id,
        'label': acct.label,
        'broker_type': acct.broker_type.value,
        'connection_status': acct.status.value,
        'balance': 0.0,
        'equity': 0.0,
        'total_pnl': 0.0,
        'pnl': 0.0,
        'pnl_pct': 0.0,
        'active_orders': 0,
        'open_positions': 0,
        'net_position': 0.0,
        'num_orders': 0,
        'paused': True,
        'trading_active': False,
        'has_bot': False,
        'broker_connected': False,
        'regime': 'unknown',
        'regime_confidence': 0.0,
        'position_direction': 'Neutral',
        'latest_price': None,
        'grid_spacing': acct.trading_config.get('grid_spacing'),
        'grid_levels': acct.trading_config.get('num_levels'),
        'max_drawdown': 0.0,
        'max_drawdown_pct': 0.0,
    }

    # Priority 1: running bot status (most accurate)
    if bot_status:
        result.update(bot_status)
        result['has_bot'] = True
        result['trading_active'] = bool(bot_status.get('trading_active', True))
        result['broker_connected'] = bot_status.get('broker_connected', False)
        # Normalise pnl fields
        if 'total_pnl' in bot_status and 'pnl' not in bot_status:
            result['pnl'] = bot_status['total_pnl']
        if 'pnl' in bot_status and 'total_pnl' not in bot_status:
            result['total_pnl'] = bot_status['pnl']
        return result

    # Priority 2: live bridge data (no bot running, but bridge is reachable)
    if bridge_data:
        result.update(bridge_data)
        result['has_bot'] = False
        result['trading_active'] = False
        result['paused'] = True
        result['broker_connected'] = True
        result['total_pnl'] = bridge_data.get('pnl', 0.0)
        # connection_status becomes 'connected' since bridge responded
        result['connection_status'] = 'connected'
        return result

    # Priority 3: account record only — bridge is unreachable
    result['connection_status'] = acct.status.value if acct.status else 'disconnected'
    result['broker_connected'] = False
    result['last_error'] = acct.last_error
    return result


@app.route('/api/logs')
def api_logs():
    """Return the most recent lines from the bot's rotating log file(s) —
    powers the dashboard Event Log with the bot's real activity."""
    n = min(int(request.args.get('limit', 80)), 500)
    lines = []
    log_dir = PROJECT_ROOT / "logs"
    if log_dir.exists():
        files = sorted(log_dir.glob("quantbot_*.log"),
                       key=lambda p: os.path.getmtime(str(p)), reverse=True)
        if files:
            try:
                with open(str(files[0]), 'r', errors='replace') as f:
                    tail = f.readlines()[-n:]
                    lines = [ln.rstrip('\n') for ln in tail]
            except Exception:
                lines = []
    return jsonify({'status': 'ok', 'lines': lines})


@app.route('/api/status')
def api_status():
    """
    JSON status — returns all accounts and aggregate dashboard data.
    Called every 5 s by pollStatus() in dashboard.html.
    Always wraps individual results in { accounts: [ … ] } for the frontend.
    NEVER 500s: any exception falls back to a demo/idle account so the UI
    shows an explicit "not connected" state instead of frozen placeholders.
    """
    try:
        mgr = _get_manager()
        account_id = request.args.get('account_id')

        # ── Aggregate: return all accounts FROM RUNNING BOTS ───────────────
        # GridBotManager stores the thread in _threads and links it to the bot
        # (bot._thread).  Only report bot status when at least one is alive.
        has_active_bots = bool(mgr._threads) and any(
            t.is_alive() for t in mgr._threads.values()
        )
        statuses = mgr.all_statuses() if has_active_bots else []

        if statuses:
            for _s in statuses:
                _attach_forecast_data(_s)
            total_balance = sum(s.get('balance', 0.0) for s in statuses)
            total_equity = sum(s.get('equity', 0.0) for s in statuses)
            total_pnl = sum(s.get('total_pnl', 0.0) for s in statuses)
            return jsonify({
                'accounts': statuses,
                'total_balance': round(total_balance, 2),
                'total_equity': round(total_equity, 2),
                'total_pnl': round(total_pnl, 2),
                'total_pnl_pct': round((total_pnl / total_balance * 100) if total_balance else 0.0, 2),
                'num_accounts': len(statuses),
            })

        # No running bots — try reading live data from the bridge directly
        bridge_data = _try_bridge_status()
        if bridge_data:
            # All accounts from the store with bridge data merged in
            accounts = mgr.account_manager.list_accounts()
            acc_list = []
            if accounts:
                for acct in accounts:
                    acc_list.append(_build_account_status(acct, bridge_data=bridge_data))
            else:
                # No accounts configured — show bridge data as a single demo account
                demo = _generate_demo_status()
                demo.update(bridge_data)
                demo['broker_connected'] = True
                demo['connection_status'] = 'connected'
                acc_list.append(demo)

            for _s in acc_list:
                _attach_forecast_data(_s)
            total_balance = sum(s.get('balance', 0.0) for s in acc_list)
            total_equity = sum(s.get('equity', 0.0) for s in acc_list)
            total_pnl = sum(s.get('pnl', 0.0) for s in acc_list)
            return jsonify({
                'accounts': acc_list,
                'total_balance': round(total_balance, 2),
                'total_equity': round(total_equity, 2),
                'total_pnl': round(total_pnl, 2),
                'total_pnl_pct': round((total_pnl / total_balance * 100) if total_balance else 0.0, 2),
                'num_accounts': len(acc_list),
            })

        # Bridge is unreachable and no bots running.
        # If configured accounts exist, show demo data so the dashboard
        # has realistic placeholder values rather than all zeros.
        # Mark broker_connected=False so the UI can show a "not connected" indicator.
        demo = _generate_demo_status()
        accounts = mgr.account_manager.list_accounts()
        if accounts:
            # Use the first account's label/ID for context
            demo['account_id'] = accounts[0].id
            demo['label'] = accounts[0].label
            demo['connection_status'] = 'disconnected'
            demo['broker_connected'] = False
            demo['regime'] = 'unknown'
            demo['regime_confidence'] = 0.0
            demo['position_direction'] = 'Neutral'
            # Reset trading-specific fields since no bot/bridge is active
            demo['num_orders'] = 0
            demo['active_orders'] = 0
            demo['open_positions'] = 0
            demo['net_position'] = 0.0
            demo['grid_spacing'] = accounts[0].trading_config.get('grid_spacing')
            demo['grid_levels'] = accounts[0].trading_config.get('num_levels')
            demo['trading_active'] = False
            demo['has_bot'] = False
            demo['last_error'] = 'bridge_unreachable: no MT5 session connected'
        else:
            # No accounts at all — pure demo mode
            demo['connection_status'] = 'demo'
        _attach_forecast_data(demo)
        return jsonify({'accounts': [demo]})
    except Exception as e:
        print(f"[api_status] error: {e}")
        demo = _generate_demo_status()
        demo['connection_status'] = 'error'
        demo['broker_connected'] = False
        demo['last_error'] = str(e)
        return jsonify({'status': 'error', 'error': str(e), 'accounts': [demo]})


@app.route('/api/bot/start', methods=['POST'])
def api_bot_start():
    """Start trading for a specific account (or all accounts)."""
    try:
        data = request.get_json(silent=True) or {}
        account_id = data.get('account_id')

        mgr = _get_manager()

        if account_id:
            mgr.start_bot(account_id)
            mgr.resume_bot(account_id)
            return jsonify({'status': 'started', 'account_id': account_id, 'message': 'Started'})
        else:
            # Start all accounts
            accounts = mgr.account_manager.list_accounts()
            for acct in accounts:
                mgr.start_bot(acct.id)
                mgr.resume_bot(acct.id)
            return jsonify({'status': 'started', 'num_accounts': len(accounts), 'message': f'Started {len(accounts)} account(s)'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/bot/stop', methods=['POST'])
def api_bot_stop():
    """Stop trading for a specific account (or all accounts)."""
    try:
        data = request.get_json(silent=True) or {}
        account_id = data.get('account_id')

        mgr = _get_manager()
        if account_id:
            bot = mgr.get_bot(account_id)
            if bot:
                bot.pause()
                bot.cancel_pending_orders()
                return jsonify({'status': 'stopped', 'account_id': account_id, 'message': 'Paused; pending orders cancelled'})
            return jsonify({'status': 'stopped', 'account_id': account_id, 'message': 'No running bot'})
        else:
            n = 0
            for bot in list(mgr._bots.values()):
                bot.pause()
                bot.cancel_pending_orders()
                n += 1
            return jsonify({'status': 'stopped', 'message': f'Paused {n} bot(s); pending orders cancelled'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/bot/close_all', methods=['POST'])
def api_bot_close_all():
    """Close all positions for a specific account (or all accounts)."""
    try:
        data = request.get_json(silent=True) or {}
        account_id = data.get('account_id')

        mgr = _get_manager()
        if account_id:
            bot = mgr.get_bot(account_id)
            if bot:
                bot.close_all_positions()
                return jsonify({'status': 'closed', 'account_id': account_id, 'message': 'Close-all sent'})
            return jsonify({'status': 'closed', 'account_id': account_id, 'message': 'No running bot'})
        else:
            n = 0
            for bot in list(mgr._bots.values()):
                bot.close_all_positions()
                n += 1
            return jsonify({'status': 'closed', 'message': f'Close-all sent for {n} bot(s)'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/bot/reset_grid', methods=['POST'])
def api_bot_reset_grid():
    """Reset the grid for a specific account (or all accounts)."""
    try:
        data = request.get_json(silent=True) or {}
        account_id = data.get('account_id')

        mgr = _get_manager()
        if account_id:
            bot = mgr.get_bot(account_id)
            if bot:
                bot.reset_grid()
                return jsonify({'status': 'reset', 'account_id': account_id, 'message': 'Grid reset'})
            return jsonify({'status': 'reset', 'account_id': account_id, 'message': 'No running bot'})
        else:
            n = 0
            for bot in list(mgr._bots.values()):
                bot.reset_grid()
                n += 1
            return jsonify({'status': 'reset', 'message': f'Reset {n} bot(s)'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/bot/refresh_regime', methods=['POST'])
def api_bot_refresh_regime():
    """Force regime refresh for a specific account (or all accounts)."""
    try:
        data = request.get_json(silent=True) or {}
        account_id = data.get('account_id')

        mgr = _get_manager()
        accounts = mgr.account_manager.list_accounts()

        if account_id:
            # Refresh for a specific account
            bot = mgr.get_bot(account_id)
            if bot:
                regime = bot.detect_regime()
                if regime in (None, '', 'unknown', 'ml_disabled'):
                    regime = _forecast_regime_label()
            else:
                regime = _forecast_regime_label()
            return jsonify({'status': 'refreshed', 'regime': regime, 'account_id': account_id})
        else:
            # Refresh for all accounts
            results = {}
            for acct in accounts:
                bot = mgr.get_bot(acct.id)
                if bot:
                    try:
                        r = bot.detect_regime()
                        results[acct.id] = r if r not in (None, '', 'unknown', 'ml_disabled') else _forecast_regime_label()
                    except Exception:
                        results[acct.id] = _forecast_regime_label()
                else:
                    results[acct.id] = _forecast_regime_label()
            if not results:
                return jsonify({'status': 'refreshed', 'regime': _forecast_regime_label(), 'message': 'No active bots running. Showing model forecast regime.'})
            first_regime = next(iter(results.values()), _forecast_regime_label())
            return jsonify({'status': 'refreshed', 'regime': first_regime, 'accounts': results})
    except Exception as e:
        return jsonify({'status': 'error', 'regime': 'unknown', 'message': str(e)})


# ── Strategy API routes ───────────────────────────────────────────────

@app.route('/api/strategies')
def api_strategies():
    """Return list of all discovered strategies with metadata."""
    try:
        from quant_env.strategies.registry import list_strategies
        strategies = list_strategies()
        return jsonify({
            'status': 'ok',
            'strategies': strategies,
            'active': None,    # per-account active strategy TBD
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e), 'strategies': []})


@app.route('/api/strategies/reload', methods=['POST'])
def api_strategies_reload():
    """Force re-scan of the strategies folder."""
    try:
        from quant_env.strategies.registry import reload, list_strategies
        reload()
        strategies = list_strategies()
        return jsonify({
            'status': 'ok',
            'message': f'Reloaded {len(strategies)} strategies.',
            'strategies': strategies,
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/api/strategy/select', methods=['POST'])
def api_strategy_select():
    """Set the active strategy for a specific account."""
    data = request.get_json() or {}
    key = data.get('strategy')
    account_id = data.get('account_id')
    if not key:
        return jsonify({'status': 'error', 'message': 'No strategy key provided.'})

    mgr = _get_manager()
    acct = mgr.account_manager.get_account(account_id) if account_id else None
    if acct is not None:
        # Persist selection
        mgr.account_manager.update_account(account_id, {'trading_config': {'strategy': key}})
        # Apply immediately if the bot is already running
        if mgr.get_bot(account_id):
            mgr.restart_bot(account_id)
            return jsonify({
                'status': 'ok',
                'message': f'Strategy "{key}" applied to account {account_id} (bot restarted).',
                'strategy': key,
            })
        return jsonify({
            'status': 'ok',
            'message': f'Strategy "{key}" saved for account {account_id} — start the bot to apply.',
            'strategy': key,
        })
    # No account — just acknowledge
    return jsonify({'status': 'ok', 'message': f'Strategy "{key}" noted for account {account_id or "default"}.', 'strategy': key})


@app.route('/api/strategy/performance')
def api_strategy_performance():
    """Return stored performance results for all strategies."""
    results = _load_strategy_results()
    return jsonify({'status': 'ok', 'results': results})


# ── Operation routes (background tasks) ──────────────────────────────

def _run_backtest_for_strategy(strategy_key: str, params: dict) -> dict:
    """
    Run a backtest for the given strategy key with the provided params.
    Returns a dict with 'metrics' and 'result_html'.
    """
    try:
        from quant_env.strategies.registry import get_class
        from quant_env.backtest.data_loader import load_yfinance
        from quant_env.backtest.engine import BacktestEngine
        from quant_env.analysis.performance import compute_metrics

        strategy_cls = get_class(strategy_key)
        if strategy_cls is None:
            return {'error': f'Strategy "{strategy_key}" not found.'}

        symbol   = params.get('symbol', 'GC=F')
        period   = params.get('period', '1mo')
        interval = params.get('interval', '1h')
        capital  = float(params.get('capital', 10000))

        # Build strategy kwargs from remaining params (exclude meta params)
        meta_keys = {'symbol', 'period', 'interval', 'capital', 'strategy'}
        strategy_kwargs = {k: v for k, v in params.items() if k not in meta_keys}
        # Convert numeric strings
        for k, v in strategy_kwargs.items():
            try:
                strategy_kwargs[k] = float(v)
            except (ValueError, TypeError):
                pass

        data = load_yfinance(symbol, period=period, interval=interval)
        engine = BacktestEngine(data, strategy_cls, capital, **strategy_kwargs)
        result = engine.run()
        metrics = compute_metrics(result.fills_df, result.equity_df)

        # Persist results
        _update_strategy_result(strategy_key, 'backtest', metrics)

        lines = [
            f"Strategy: {getattr(strategy_cls, 'STRATEGY_NAME', strategy_key)}",
            f"Symbol: {symbol}  Period: {period}  Interval: {interval}",
            f"Capital: ${capital:,.0f}",
            "=" * 40,
            f"Total Return:   {metrics.get('total_return_pct', 0):.2f}%",
            f"Sharpe Ratio:   {metrics.get('sharpe_ratio', 0):.2f}",
            f"Max Drawdown:   {metrics.get('max_drawdown_pct', 0):.2f}%",
            f"Win Rate:       {metrics.get('win_rate_pct', 0):.2f}%",
            f"Profit Factor:  {metrics.get('profit_factor', 0):.2f}",
            f"Total Trades:   {metrics.get('num_trades', 0)}",
            f"Avg Win:        ${metrics.get('avg_win', 0):.2f}",
            f"Avg Loss:       ${metrics.get('avg_loss', 0):.2f}",
        ]
        return {
            'metrics': metrics,
            'result_html': _format_result('\n'.join(lines)),
        }
    except Exception as e:
        import traceback
        return {'error': str(e), 'result_html': _format_result(f'ERROR: {e}\n{traceback.format_exc()}')}


@app.route('/api/operation/backtest', methods=['POST'])
def op_backtest():
    data = request.get_json() or {}
    strategy_key = data.get('strategy') or 'grid_strategy'

    try:
        from quant_env.strategies.registry import get_class
        cls = get_class(strategy_key)
        if cls is not None:
            result = _run_backtest_for_strategy(strategy_key, data)
            if 'error' in result and 'result_html' not in result:
                return jsonify({'status': 'error', 'result_html': _format_result(result['error'])})
            return jsonify({'status': 'done', **result})
    except Exception:
        pass

    output = _run_launcher_command('backtest')
    return jsonify({'status': 'done', 'result_html': _format_result(output)})


@app.route('/api/operation/optimize', methods=['POST'])
def op_optimize():
    data = request.get_json() or {}
    strategy_key = data.get('strategy') or 'grid_strategy'

    try:
        from quant_env.strategies.registry import get_class, list_strategies
        from quant_env.backtest.data_loader import load_yfinance
        from quant_env.backtest.engine import BacktestEngine
        from quant_env.analysis.performance import compute_metrics
        import pandas as pd
        import itertools

        strategy_cls = get_class(strategy_key)
        if strategy_cls is not None:
            symbol   = data.get('symbol', 'GC=F')
            period   = data.get('period', '1mo')
            interval = data.get('interval', '1h')
            capital  = float(data.get('capital', 10000))

            # Build param_grid from the strategy's own PARAMS dict
            # Look up the strategy metadata to get parameter definitions
            all_strategies = list_strategies()
            meta = next((s for s in all_strategies if s['key'] == strategy_key), {})
            params_def = meta.get('params', {})

            # Build param_grid: each param can be swept over 3 values
            param_grid = {}
            for pname, pdef in params_def.items():
                default = pdef.get('default', 1)
                # Use request values if provided, otherwise generate 3 values around default
                req_vals = data.get(f'{pname}s') or data.get(pname)
                if req_vals is not None:
                    if isinstance(req_vals, str):
                        req_vals = [float(v) for v in req_vals.split(',') if v.strip()]
                    elif not isinstance(req_vals, list):
                        req_vals = [float(req_vals)]
                    param_grid[pname] = req_vals
                else:
                    # Auto-generate 3 values: default * 0.5, default, default * 1.5
                    base = float(default)
                    if isinstance(default, int) or pdef.get('type') == 'number' and pdef.get('step', 1) >= 1:
                        vals = [int(base * 0.5) or 1, int(base), int(base * 1.5)]
                    else:
                        vals = [round(base * 0.5, 4), base, round(base * 1.5, 4)]
                    param_grid[pname] = vals

            if not param_grid:
                return jsonify({'status': 'error', 'message': 'No sweepable parameters defined for this strategy.'})

            hist_data = load_yfinance(symbol, period=period, interval=interval)
            keys = list(param_grid.keys())
            results = []
            for combo in itertools.product(*param_grid.values()):
                params = dict(zip(keys, combo))
                # Convert numeric types appropriately
                engine_params = {}
                for k, v in params.items():
                    pdef = params_def.get(k, {})
                    if pdef.get('type') == 'number' and pdef.get('step', 1) >= 1:
                        engine_params[k] = int(v) if not isinstance(v, int) else v
                    else:
                        engine_params[k] = float(v)
                try:
                    engine = BacktestEngine(
                        hist_data.copy(), strategy_cls, capital, **engine_params
                    )
                    res = engine.run()
                    m = compute_metrics(res.fills_df, res.equity_df)
                    m.update(engine_params)
                    results.append(m)
                except Exception:
                    pass

            if results:
                df = pd.DataFrame(results).sort_values('sharpe_ratio', ascending=False)
                best = df.iloc[0].to_dict()
                _update_strategy_result(strategy_key, 'optimize', best)

                lines = [f"Optimization — {getattr(strategy_cls, 'STRATEGY_NAME', strategy_key)}", "=" * 40]
                for _, r in df.iterrows():
                    param_str = '  '.join(f"{k}={r[k]}" for k in keys)
                    lines.append(f"  {param_str}  sharpe={r['sharpe_ratio']:.2f}  return={r['total_return_pct']:.2f}%  dd={r['max_drawdown_pct']:.2f}%")
                lines.append("=" * 40)
                best_param_str = '  '.join(f"{k}={best[k]}" for k in keys)
                lines.append(f"Best: {best_param_str}  sharpe={best['sharpe_ratio']:.2f}")
                return jsonify({'status': 'done', 'result_html': _format_result('\n'.join(lines)), 'best': best})
    except Exception as e:
        pass

    output = _run_launcher_command('optimize')
    return jsonify({'status': 'done', 'result_html': _format_result(output)})


@app.route('/api/operation/report', methods=['POST'])
def op_report():
    output = _run_launcher_command('report')
    return jsonify({
        'status': 'done',
        'result_html': _format_result(output),
    })


@app.route('/api/operation/walkforward', methods=['POST'])
def op_walkforward():
    data = request.get_json() or {}
    strategy_key = data.get('strategy') or 'grid_strategy'

    try:
        from quant_env.strategies.registry import get_class, list_strategies
        from quant_env.backtest.data_loader import load_yfinance
        from quant_env.analysis.walkforward import walkforward_analysis

        strategy_cls = get_class(strategy_key)
        if strategy_cls is not None:
            symbol   = data.get('symbol', 'GC=F')
            period   = data.get('period', '3mo')
            interval = data.get('interval', '1h')
            capital  = float(data.get('capital', 10000))
            window   = int(data.get('window', 500))
            step     = int(data.get('step', 500))

            # Build param_grid from the strategy's own PARAMS dict
            all_strategies = list_strategies()
            meta = next((s for s in all_strategies if s['key'] == strategy_key), {})
            params_def = meta.get('params', {})

            param_grid = {}
            for pname, pdef in params_def.items():
                default = pdef.get('default', 1)
                req_vals = data.get(f'{pname}s') or data.get(pname)
                if req_vals is not None:
                    if isinstance(req_vals, str):
                        req_vals = [float(v) for v in req_vals.split(',') if v.strip()]
                    elif not isinstance(req_vals, list):
                        req_vals = [float(req_vals)]
                    param_grid[pname] = req_vals
                else:
                    # Auto-generate 2 values: default, default * 1.5
                    base = float(default)
                    if isinstance(default, int) or pdef.get('type') == 'number' and pdef.get('step', 1) >= 1:
                        vals = [int(base), int(base * 1.5)]
                    else:
                        vals = [base, round(base * 1.5, 4)]
                    param_grid[pname] = vals

            if not param_grid:
                return jsonify({'status': 'error', 'message': 'No sweepable parameters defined for this strategy.'})

            hist_data = load_yfinance(symbol, period=period, interval=interval)
            wf_df = walkforward_analysis(
                hist_data, strategy_cls, param_grid,
                window_size=window, step_size=step,
                initial_capital=capital
            )
            summary = wf_df.to_dict(orient='records') if not wf_df.empty else []
            if summary:
                _update_strategy_result(strategy_key, 'walkforward', {'windows': len(summary)})

            lines = [f"Walk-Forward — {getattr(strategy_cls, 'STRATEGY_NAME', strategy_key)}", "=" * 40]
            for row in summary:
                lines.append(str(row))
            return jsonify({'status': 'done', 'result_html': _format_result('\n'.join(lines))})
    except Exception as e:
        pass

    output = _run_launcher_command('walkforward')
    return jsonify({'status': 'done', 'result_html': _format_result(output)})


@app.route('/api/operation/train_ml', methods=['POST'])
def op_train_ml():
    data = request.get_json() or {}
    strategy_key = data.get('strategy')

    output = _run_launcher_command('train_ml')

    if strategy_key:
        _update_strategy_result(strategy_key, 'train_ml', {
            'trained_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'output_summary': output[:500],
        })

    return jsonify({
        'status': 'done',
        'result_html': _format_result(output),
    })


@app.route('/api/operation/benchmark_all', methods=['POST'])
def op_benchmark_all():
    """Run backtest for ALL discovered strategies and return comparison."""
    data = request.get_json() or {}
    symbol   = data.get('symbol', 'GC=F')
    period   = data.get('period', '1mo')
    interval = data.get('interval', '1h')
    capital  = float(data.get('capital', 10000))

    try:
        from quant_env.strategies.registry import list_strategies
        strategies = list_strategies()
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

    comparison = []
    for s in strategies:
        key = s['key']
        params = {'symbol': symbol, 'period': period, 'interval': interval, 'capital': capital}
        for pname, pdef in s.get('params', {}).items():
            params[pname] = pdef.get('default', 1.0)

        result = _run_backtest_for_strategy(key, params)
        metrics = result.get('metrics', {})
        comparison.append({
            'key': key,
            'name': s['name'],
            'total_return_pct': metrics.get('total_return_pct', 0),
            'sharpe_ratio': metrics.get('sharpe_ratio', 0),
            'win_rate_pct': metrics.get('win_rate_pct', 0),
            'profit_factor': metrics.get('profit_factor', 0),
            'max_drawdown_pct': metrics.get('max_drawdown_pct', 0),
            'num_trades': metrics.get('num_trades', 0),
            'error': result.get('error'),
        })

    return jsonify({'status': 'done', 'comparison': comparison})


# ═══════════════════════════════════════════════════════════════════════
#  ANALYTICS API — structured JSON for the Next.js Intelligence page
#  Serves the real artifacts produced by the engine:
#    strategy_results.json · optimization_results.csv · walkforward_*.csv
#    ml/model_metrics.json · gold_data.csv · live trade DBs
# ═══════════════════════════════════════════════════════════════════════

import csv as _csv


def _read_csv_rows(path, limit=20000):
    """Read a CSV into a list of dicts (string values preserved)."""
    if not os.path.exists(str(path)):
        return []
    try:
        with open(str(path), newline='', encoding='utf-8') as f:
            rows = list(_csv.DictReader(f))
        return rows[:limit]
    except Exception as e:
        print(f"[Analytics] CSV read failed {path}: {e}")
        return []


def _num(value, default=0.0):
    """Best-effort numeric cast (handles None / empty / weird strings)."""
    try:
        if value is None:
            return default
        s = str(value).strip()
        if not s:
            return default
        return float(s)
    except (ValueError, TypeError):
        return default


def _load_live_engine_data():
    """
    Load the legacy engine trade DB (the one with real fills) plus the
    per-account DBs, deduplicated.  Returns { fills, equity, trades, metrics }.
    Realized PnL is computed on the fly with the FIFO trade matcher because
    fills are logged without a pnl value.
    """
    import pandas as pd
    import sqlite3
    from quant_env.analysis.trade_matcher import match_trades
    from quant_env.analysis.performance import compute_metrics

    candidates = [
        PROJECT_ROOT / "quant_env" / "trades.db",   # legacy single-file DB
        PROJECT_ROOT / "trades.db",                 # root-level copy
    ]
    fill_rows = []
    seen = set()
    for db_path in candidates:
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(str(db_path), timeout=5.0)
            rows = conn.execute(
                "SELECT timestamp, symbol, side, price, volume, pnl FROM fills ORDER BY timestamp"
            ).fetchall()
            conn.close()
            for ts, sym, side, price, vol, pnl in rows:
                key = (ts, sym, side, float(price or 0), float(vol or 0))
                if key in seen:
                    continue
                seen.add(key)
                fill_rows.append({
                    "timestamp": ts, "symbol": sym, "side": side,
                    "price": float(price or 0), "volume": float(vol or 0),
                    "pnl": float(pnl or 0),
                })
        except Exception as e:
            print(f"[Analytics] Could not read {db_path}: {e}")

    equity_rows = []
    for db_path in candidates:
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(str(db_path), timeout=5.0)
            rows = conn.execute(
                "SELECT timestamp, equity, balance FROM equity_snapshots ORDER BY timestamp"
            ).fetchall()
            conn.close()
            for ts, eq, bal in rows:
                equity_rows.append({"timestamp": ts, "equity": float(eq or 0), "balance": float(bal or 0)})
            if equity_rows:
                break  # first DB that has equity wins
        except Exception:
            continue

    result = {"fills": fill_rows, "equity": equity_rows, "trades": [], "metrics": None}
    if fill_rows:
        try:
            fills_df = pd.DataFrame(fill_rows)
            trades_df = match_trades(fills_df)
            if not trades_df.empty:
                result["trades"] = trades_df.to_dict(orient="records")
                eq_series = [e["equity"] for e in equity_rows] if equity_rows else []
                if len(eq_series) > 1:
                    import numpy as np
                    eq_idx = pd.date_range("2026-05-11", periods=len(eq_series), freq="h")
                    eq_df = pd.DataFrame({"timestamp": eq_idx, "equity": eq_series})
                else:
                    eq_df = pd.DataFrame({"timestamp": [], "equity": []})
                result["metrics"] = compute_metrics(fills_df, eq_df)
        except Exception as e:
            print(f"[Analytics] PnL matching failed: {e}")
    return result



@app.route('/api/analytics/overview')
def api_analytics_overview():
    """Top-level dashboard: strategy results, ML summary, live stats, flags."""
    strategy_results = _load_strategy_results()
    live = _load_live_engine_data()

    strategies = {}
    for key, ops in strategy_results.items():
        strategies[key] = {
            "name": key.replace("_", " ").title(),
            "backtest": (ops.get("backtest") or {}).get("metrics"),
            "optimize": (ops.get("optimize") or {}).get("metrics"),
            "walkforward": (ops.get("walkforward") or {}).get("metrics"),
            "train_ml": (ops.get("train_ml") or {}).get("metrics"),
        }

    return jsonify({
        "status": "ok",
        "strategies": strategies,
        "live": {
            "fill_count": len(live["fills"]),
            "trade_count": len(live["trades"]),
            "equity_points": len(live["equity"]),
            "first_fill": live["fills"][0]["timestamp"] if live["fills"] else None,
            "last_fill": live["fills"][-1]["timestamp"] if live["fills"] else None,
            "metrics": live["metrics"],
            "side_split": {
                "buy": sum(1 for f in live["fills"] if f["side"] == "buy"),
                "sell": sum(1 for f in live["fills"] if f["side"] == "sell"),
            },
        },
        "config": {
            "symbol": getattr(Config, "SYMBOL", "XAUUSD.r"),
            "yahoo_symbol": getattr(Config, "YAHOO_SYMBOL", "GC=F"),
            "ml_enabled": getattr(Config, "ML_ENABLED", False),
            "kronos_enabled": getattr(Config, "KRONOS_ENABLED", False),
            "kronos_blend_enabled": getattr(Config, "KRONOS_BLEND_ENABLED", False),
            "kronos_risk_metrics": getattr(Config, "KRONOS_RISK_METRICS_ENABLED", False),
            "kronos_symbols": getattr(Config, "KRONOS_SYMBOLS", ""),
            "kronos_model": getattr(Config, "KRONOS_MODEL", "NeoQuasar/Kronos-small"),
            "adaptive_enabled": getattr(Config, "ADAPTIVE_ENABLED", False),
        },
    })


@app.route('/api/analytics/optimization')
def api_analytics_optimization():
    """Grid-search optimization results + derived best params."""
    rows = _read_csv_rows(PROJECT_ROOT / "optimization_results.csv")
    parsed = []
    for r in rows:
        parsed.append({
            "spacing": _num(r.get("spacing")),
            "levels": _num(r.get("levels")),
            "total_return_pct": _num(r.get("total_return_pct")),
            "total_pnl": _num(r.get("total_pnl")),
            "sharpe_ratio": _num(r.get("sharpe_ratio")),
            "max_drawdown_pct": _num(r.get("max_drawdown_pct")),
            "num_trades": _num(r.get("num_trades")),
            "win_rate_pct": _num(r.get("win_rate_pct")),
            "profit_factor": _num(r.get("profit_factor")),
        })
    best = None
    if parsed:
        best = max(parsed, key=lambda p: p["sharpe_ratio"])
    return jsonify({"status": "ok", "rows": parsed, "best": best})


@app.route('/api/analytics/walkforward')
def api_analytics_walkforward():
    """Walk-forward analysis: per-window OOS results (both result files)."""
    primary = _read_csv_rows(PROJECT_ROOT / "walkforward_report.csv")
    secondary = _read_csv_rows(PROJECT_ROOT / "walkforward_results.csv")
    return jsonify({"status": "ok", "windows": primary, "raw": secondary})



@app.route('/api/analytics/ml')
def api_analytics_ml():
    """ML model metrics + feature importances."""
    path = PROJECT_ROOT / "quant_env" / "ml" / "model_metrics.json"
    model_metrics = {}
    if path.exists():
        try:
            with open(str(path)) as f:
                model_metrics = json.load(f)
        except Exception:
            pass
    return jsonify({
        "status": "ok",
        "model": model_metrics,
        "trained": model_metrics is not None and bool(model_metrics),
    })


@app.route('/api/analytics/equity')
def api_analytics_equity():
    """Price series (gold_data.csv, sampled) + live equity curve."""
    gold_rows = _read_csv_rows(PROJECT_ROOT / "gold_data.csv", limit=200000)
    sampled = []
    step = max(1, len(gold_rows) // 480)  # ~480 points max for the chart
    for i in range(0, len(gold_rows), step):
        r = gold_rows[i]
        sampled.append({
            "t": r.get("Datetime", ""),
            "close": _num(r.get("Close")),
            "high": _num(r.get("High")),
            "low": _num(r.get("Low")),
        })
    live = _load_live_engine_data()
    equity = []
    step_e = max(1, len(live["equity"]) // 480)
    for i in range(0, len(live["equity"]), step_e):
        equity.append(live["equity"][i])
    return jsonify({
        "status": "ok",
        "price": sampled,
        "live_equity": equity,
        "fills": live["fills"][-200:],
    })


@app.route('/api/analytics/live')
def api_analytics_live():
    """Realized PnL trades (FIFO) + fill activity series."""
    live = _load_live_engine_data()
    return jsonify({
        "status": "ok",
        "trades": live["trades"],
        "fills": live["fills"],
        "metrics": live["metrics"],
    })


# ── InsightForge for Quant — autonomous research team ─────────────────
# These endpoints expose the multi-agent quantitative research loop
# (DataScout -> MarketProber -> QuantAnalyst -> QuantStrategist) as a
# dashboard API. Every agent is a named replacement for a human quant
# professional; see gridbots/quant_env/intelligence/ for the framework.


def _run_intelligence_cycle():
    """Run one agent-team cycle with a light probe budget (fast enough for HTTP)."""
    from quant_env.intelligence.coordinator import CoordinatorAgent
    brief, _ = CoordinatorAgent({
        "max_bars": 600,
        "probe_limit": 2,
        "top_n": 3,
        "llm_enabled": getattr(Config, "RESEARCH_LLM_ENABLED", False),
        "news_enabled": getattr(Config, "RESEARCH_NEWS_ENABLED", True),
        "news_max_articles": int(getattr(Config, "RESEARCH_NEWS_MAX_ARTICLES", "20")),
        "news_use_sample": getattr(Config, "RESEARCH_NEWS_USE_SAMPLE", False),
    }).run_cycle()
    return brief


@app.route('/api/intelligence/brief')
def api_intelligence_brief():
    """Trigger + return the latest autonomous research brief."""
    try:
        brief = _run_intelligence_cycle()
        return jsonify({"status": "ok", "brief": brief})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/intelligence/ledger')
def api_intelligence_ledger():
    """Return the persisted opportunity ledger (instruments/probes/themes/opportunities)."""
    try:
        from quant_env.intelligence.ledger import OpportunityLedger
        ledger = OpportunityLedger.load()
        return jsonify({"status": "ok", "ledger": ledger.to_dict()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/intelligence/deployments')
def api_intelligence_deployments():
    """List all strategy deployments (proposed / approved / rejected)."""
    try:
        from quant_env.intelligence.deploy import DeploymentManager
        return jsonify({"status": "ok", "deployments": DeploymentManager().list()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/intelligence/last_brief')
def api_intelligence_last_brief():
    """Return the persisted research brief (last completed cycle) without re-running."""
    try:
        from quant_env.intelligence.ledger import OUTPUT_DIR
        import json as _json
        path = os.path.join(OUTPUT_DIR, "research_brief.json")
        if not os.path.exists(path):
            return jsonify({"status": "empty"})
        with open(path) as f:
            brief = _json.load(f)
        return jsonify({"status": "ok", "brief": brief})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/intelligence/news')
def api_intelligence_news():
    """Latest News Desk analysis from the last consensus MarketView.

    Returns the curated-corpus stats, the Claude Sonnet direction verdict, the
    Kronos + RF confirmation and the persisted news narrative — or
    ``status: "empty"`` when no cycle has produced one yet.
    """
    try:
        from quant_env.intelligence.ledger import OpportunityLedger, OUTPUT_DIR
        import json as _json
        ledger = OpportunityLedger.load()
        views = list(ledger.market_views or [])
        latest = views[-1] if views else None
        na = (latest or {}).get("news_analysis")
        if not na:
            return jsonify({"status": "empty"})
        news_narrative = None
        brief_path = os.path.join(OUTPUT_DIR, "research_brief.json")
        if os.path.exists(brief_path):
            try:
                with open(brief_path) as f:
                    news_narrative = _json.load(f).get("news_narrative")
            except Exception:
                pass
        return jsonify({
            "status": "ok",
            "news_analysis": na,
            "news_narrative": news_narrative,
            "market_view_generated_at": latest.get("generated_at"),
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/intelligence/scheduler', methods=['GET', 'POST'])
def api_intelligence_scheduler():
    """Research-loop status + control.

    GET  — status (running, cycles, next cycle estimate, config).
    POST — {"action": "start"|"stop"} controls the ResearchScheduler
           singleton from the dashboard.
    """
    try:
        from quant_env.intelligence.scheduler import ResearchScheduler
        s = ResearchScheduler._instance
        last = getattr(s, "last_brief", None) or {}

        if request.method == 'POST':
            data = request.get_json(silent=True) or {}
            action = data.get("action")
            if action not in ("start", "stop"):
                return jsonify({"status": "error",
                                "error": f"unknown action: {action}"}), 400
            if s is None:
                # Lazily create the singleton with engine Config defaults.
                from quant_env.intelligence.scheduler import ResearchScheduler as RS
                s = RS.get_instance(Config, None)
            if action == "start":
                s.start()
            else:
                s.stop()
            return jsonify({"status": "ok", "action": action,
                            "running": bool(s.running)})

        running = bool(s and s.running)
        now = time.time()
        last_run_at = None
        next_cycle_at = None
        if running and s is not None:
            # Scheduler stores _loop_started_at (set in _run) — else estimate.
            started = getattr(s, "_loop_started_at", None)
            last_run_at = started
            if started:
                next_cycle_at = started + s.interval_minutes * 60

        return jsonify({
            "status": "ok",
            "running": running,
            "interval_minutes": int(getattr(s, "interval_minutes", 0)) if s else 0,
            "cycles_run": int(getattr(s, "cycles_run", 0)) if s else 0,
            "last_brief_cycle_id": last.get("cycle_id") if isinstance(last, dict) else None,
            "last_run_at": last_run_at,
            "next_cycle_at": next_cycle_at,
            "enabled": bool(getattr(Config, "RESEARCH_ENABLED", False)),
            "auto_approve_cycles": int(getattr(Config, "RESEARCH_AUTO_APPROVE_CYCLES", "0")),
            "symbols": getattr(Config, "RESEARCH_SYMBOLS", "GC=F"),
            "news_enabled": bool(getattr(Config, "RESEARCH_NEWS_ENABLED", False)),
            "news_max_articles": int(getattr(Config, "RESEARCH_NEWS_MAX_ARTICLES", "20")),
            "news_use_sample": bool(getattr(Config, "RESEARCH_NEWS_USE_SAMPLE", False)),
            "news_model": getattr(Config, "LLM_NEWS_MODEL", "claude-sonnet-5"),
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/intelligence/execution')
def api_intelligence_execution():
    """Execution-guard status: kill-switch config, live consensus strength,
    drawdown snapshot and hot-applied deployments — everything the terminal
    knows about execution, exposed to the dashboard."""
    try:
        from quant_env.intelligence.ledger import OpportunityLedger
        from quant_env.intelligence.execution import live_apply
        from quant_env.intelligence.execution.advisor import (
            MIN_CONSENSUS_STRENGTH, MAX_RISK_PER_TRADE)
        from quant_env.intelligence.deploy import (
            DEPLOY_MIN_TRADES, DEPLOY_MIN_SHARPE, DEPLOY_MIN_OOS_CONSISTENCY,
            DEPLOY_MIN_MC_PROB_PROFIT, DEPLOY_MIN_Q_RICE, DEPLOY_MAX_DRAWDOWN_PCT)

        ledger = OpportunityLedger.load()
        views = list(ledger.market_views or [])
        latest = views[-1] if views else None
        consensus_strength = (latest or {}).get("consensus_strength", 0.0)
        direction = (latest or {}).get("direction", "RANGING")

        # Drawdown snapshot: best effort from the live account (engine App).
        drawdown_pct = 0.0
        try:
            mgr = _get_manager()
            for acct in mgr.account_manager.list_accounts():
                bot = mgr.get_bot(acct.id)
                if bot is not None:
                    app = getattr(bot, "_app", None)
                    dd = getattr(app, "_last_drawdown_pct", None) if app else None
                    if dd is not None:
                        drawdown_pct = max(drawdown_pct, float(dd))
        except Exception:
            pass

        kill = {
            "max_drawdown_pct": live_apply.EXEC_KILL_MAX_DRAWDOWN_PCT,
            "consensus_collapse_armed": live_apply.EXEC_KILL_CONSENSUS_COLLAPSE,
            "consensus_floor": live_apply.EXEC_KILL_CONSENSUS_FLOOR,
            "regime_flip_armed": live_apply.EXEC_KILL_REGIME_FLIP,
        }
        # Evaluate the kill-switches against the current state.
        from quant_env.intelligence.execution.live_apply import evaluate_kill_switches
        flatten, reasons = evaluate_kill_switches(
            market_view=latest, current_drawdown_pct=drawdown_pct)

        return jsonify({
            "status": "ok",
            "kill": kill,
            "current": {
                "consensus_strength": consensus_strength,
                "direction": direction,
                "drawdown_pct": round(drawdown_pct, 2),
                "kill_triggered": bool(flatten),
                "kill_reasons": reasons,
                "advisor_min_consensus_strength": MIN_CONSENSUS_STRENGTH,
                "advisor_max_risk_per_trade": MAX_RISK_PER_TRADE,
            },
            "gates": {
                "min_trades": DEPLOY_MIN_TRADES,
                "min_sharpe": DEPLOY_MIN_SHARPE,
                "min_oos_consistency": DEPLOY_MIN_OOS_CONSISTENCY,
                "min_mc_prob_profit": DEPLOY_MIN_MC_PROB_PROFIT,
                "min_qrice": DEPLOY_MIN_Q_RICE,
                "max_drawdown": DEPLOY_MAX_DRAWDOWN_PCT,
            },
            "hot_applied": live_apply.list_hot_applied(),
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


# ── Consensus / execution endpoints (Phase 1 + 3) ─────────────────────
@app.route('/api/intelligence/market_view')
def api_intelligence_market_view():
    """Return the latest consensus MarketView + its attribution chain.

    When no cycle has persisted a view yet, a fresh consensus is fused on
    demand from every currently-available source (Kronos / RF / trend filter /
    backtest probes) so the dashboard is live from the first paint.
    """
    try:
        from quant_env.intelligence.ledger import OpportunityLedger
        from quant_env.intelligence.consensus import ConsensusEngine
        from quant_env.intelligence.consensus.sources import collect_all_signals

        ledger = OpportunityLedger.load()
        views = list(ledger.market_views or [])
        latest = views[-1] if views else None
        if latest is None:
            symbol = getattr(Config, "RESEARCH_SYMBOLS", "GC=F").split(",")[0].strip() or "GC=F"
            signals = collect_all_signals(
                ctx={"max_bars": 600},
                ledger=ledger,
                project_root=_get_project_root(),
                symbol=symbol)
            latest = ConsensusEngine().fuse(
                signals, symbol=symbol, cycle_id="dashboard-live").to_dict()
            views = [latest]
        return jsonify({
            "status": "ok",
            "market_view": latest,
            "history": views[-20:],
            "count": len(views),
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/intelligence/kill_drill')
def api_intelligence_kill_drill():
    """Kill-switch DRILL — replay the recent consensus history through the
    kill conditions and report what WOULD have happened (no broker touch)."""
    try:
        from quant_env.intelligence.ledger import OpportunityLedger
        from quant_env.intelligence.execution.live_apply import run_kill_drill

        from quant_env.intelligence.consensus import ConsensusEngine
        from quant_env.intelligence.consensus.sources import collect_all_signals

        ledger = OpportunityLedger.load()
        views = list(ledger.market_views or [])
        if not views:
            # Drill the LIVE consensus when no cycle has persisted a view yet.
            symbol = getattr(Config, "RESEARCH_SYMBOLS", "GC=F").split(",")[0].strip() or "GC=F"
            signals = collect_all_signals(ctx={"max_bars": 600}, ledger=ledger,
                                          project_root=_get_project_root(),
                                          symbol=symbol)
            fresh = ConsensusEngine().fuse(signals, symbol=symbol,
                                           cycle_id="dashboard-live")
            views = [fresh.to_dict()]
        try:
            horizon = int(request.args.get("horizon", 12))
        except (TypeError, ValueError):
            horizon = 12
        # Drawdown snapshot: best effort from the live account (engine App).
        drawdown_pct = 0.0
        try:
            mgr = _get_manager()
            for acct in mgr.account_manager.list_accounts():
                bot = mgr.get_bot(acct.id)
                if bot is not None:
                    app = getattr(bot, "_app", None)
                    dd = getattr(app, "_last_drawdown_pct", None) if app else None
                    if dd is not None:
                        drawdown_pct = max(drawdown_pct, float(dd))
        except Exception:
            pass
        # What-if scenario sliders (advanced drill): override kill thresholds
        # for this simulation WITHOUT touching the live guard's config.
        overrides = {}
        for key, qp in (("max_drawdown_pct", "drawdown_pct"),
                        ("consensus_floor", "consensus_floor")):
            raw = request.args.get(qp)
            if raw:
                try:
                    overrides[key] = float(raw)
                except (TypeError, ValueError):
                    pass
        for key, qp in (("consensus_collapse_armed", "collapse_armed"),
                        ("regime_flip_armed", "flip_armed")):
            raw = request.args.get(qp)
            if raw is not None and str(raw).lower() in ("0", "1", "true", "false"):
                overrides[key] = str(raw).lower() in ("1", "true")
        drill = run_kill_drill(views, current_drawdown_pct=drawdown_pct,
                               horizon=horizon, overrides=overrides or None)
        # Advanced: the what-if threshold sensitivity grid (drill matrix).
        if request.args.get("matrix", "0") == "1":
            from quant_env.intelligence.execution.live_apply import run_kill_drill_matrix
            try:
                dd_range = [float(x) for x in
                            str(request.args.get("dd_range", "5,10,15,20")).split(",") if x]
                fl_range = [float(x) for x in
                            str(request.args.get("floor_range", "0.05,0.15,0.3,0.5")).split(",") if x]
                matrix = run_kill_drill_matrix(views, dd_grid=dd_range or (5, 10, 15, 20),
                                               floor_grid=fl_range or (0.05, 0.15, 0.3, 0.5),
                                               current_drawdown_pct=drawdown_pct,
                                               horizon=horizon)
                return jsonify({"status": "ok", "drill": drill, "matrix": matrix})
            except Exception:
                return jsonify({"status": "ok", "drill": drill})
        return jsonify({"status": "ok", "drill": drill})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/intelligence/consensus_history')
def api_intelligence_consensus_history():
    """Belief curve + per-source track record over persisted consensus views.

    Every persisted MarketView is labeled with the realized outcome that
    FOLLOWED it (forward return from the cached symbol history), so the desk
    can see — source by source — who called it right and who called it wrong.
    "Calibration beats accuracy": we score the direction of each vote against
    the realized direction, not the strength.

    Views whose forward window is not yet observable are returned unscored
    ("pending") — the scorecard grows honestly as time passes and cycles run.
    """
    try:
        from quant_env.intelligence.ledger import OpportunityLedger
        from quant_env.intelligence.data import load_cached_history
        import pandas as pd

        from quant_env.intelligence.consensus import ConsensusEngine
        from quant_env.intelligence.consensus.sources import collect_all_signals

        ledger = OpportunityLedger.load()
        views = list(ledger.market_views or [])
        symbol = getattr(Config, "RESEARCH_SYMBOLS", "GC=F").split(",")[0].strip() or "GC=F"
        # Always show the CURRENT belief as the newest (pending) point — the
        # belief curve is never empty, and persisted cycles add scored history.
        try:
            signals = collect_all_signals(ctx={"max_bars": 600}, ledger=ledger,
                                          project_root=_get_project_root(),
                                          symbol=symbol)
            live = ConsensusEngine().fuse(
                signals, symbol=symbol, cycle_id="dashboard-live").to_dict()
            live["current_live"] = True
            views = views + [live]
        except Exception:
            pass
        df = load_cached_history(_get_project_root(), symbol)
        if df is not None and getattr(df.index, "tz", None) is not None:
            df.index = df.index.tz_convert("UTC").tz_localize(None)

        from quant_env.intelligence.research_stats import score_consensus_history
        out, scorecard, scored = score_consensus_history(views, df)
        return jsonify({
            "status": "ok",
            "views": out[-30:],
            "count": len(out),
            "scored": scored,
            "scorecard": scorecard,
            "note": ("Track records grow with every persisted research cycle; "
                      "unscored views are pending forward data."),
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/intelligence/risk_cone')
def api_intelligence_risk_cone():
    """Forward Monte-Carlo "possibility cone" from the current equity point:
    5/50/95 percentile paths + P(ruin) + P(profit), bootstrapped from realized
    trade PnL (falls back to the committed analytics snapshot)."""
    try:
        from quant_env.analysis.monte_carlo import possibility_cone
        import numpy as np

        live = _load_live_engine_data()
        trades = live.get("trades") or []
        pnls = [float(t.get("pnl", 0.0) or 0.0) for t in trades]
        equity = live.get("equity") or []
        initial = float(equity[-1]["equity"]) if equity else 10000.0
        if not pnls and equity:
            eqs = [float(e["equity"]) for e in equity]
            pnls = [b - a for a, b in zip(eqs, eqs[1:])]
        if not pnls:
            snap_path = PROJECT_ROOT / "analytics_snapshot.json"
            if snap_path.exists():
                try:
                    snap = json.load(open(snap_path))
                    eqs = [float(e["equity"]) for e in (snap.get("equity_tail") or [])]
                    if len(eqs) > 1:
                        pnls = [b - a for a, b in zip(eqs, eqs[1:])]
                        initial = float(eqs[-1])
                except Exception:
                    pass
        try:
            horizon = min(max(20, int(request.args.get("horizon", 120))), 500)
        except (TypeError, ValueError):
            horizon = 120
        try:
            initial_arg = float(request.args.get("initial", initial))
            if initial_arg > 0:
                initial = initial_arg
        except (TypeError, ValueError):
            pass
        if not pnls:
            return jsonify({"status": "ok", "cone": None,
                            "error": "no realized trade or equity returns available"})
        _, stats = possibility_cone(pnls, num_sim=1000, horizon=horizon,
                                    initial=initial, seed=7)
        return jsonify({"status": "ok", "cone": stats})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/intelligence/advise', methods=['GET', 'POST'])
def api_intelligence_advise():
    """Trade recommendation from the advisor (consensus + gates + Kronos).

    Optionally accepts a POST body: {"price": ..., "equity": ...,
    "deployment_id": ...} to size lots.  With no market view present the
    advisor returns a HOLD with an explanation.
    """
    try:
        from quant_env.intelligence.consensus import ConsensusEngine
        from quant_env.intelligence.consensus.sources import collect_all_signals
        from quant_env.intelligence.ledger import OpportunityLedger
        from quant_env.intelligence.execution import TradeExecutionAdvisor

        ledger = OpportunityLedger.load()
        ctx = {
            "max_bars": 600,
            "probe_limit": 2,
        }
        signals = collect_all_signals(
            ctx=ctx, ledger=ledger,
            project_root=_get_project_root(),
            symbol=getattr(Config, "RESEARCH_SYMBOLS", "GC=F").split(",")[0])
        view = ConsensusEngine().fuse(
            signals, symbol=getattr(Config, "RESEARCH_SYMBOLS", "GC=F").split(",")[0],
            cycle_id="dashboard-advise")

        body = request.get_json(silent=True) or {}
        deployment = None
        if body.get("deployment_id"):
            from quant_env.intelligence.deploy import DeploymentManager
            for r in DeploymentManager().list():
                if r["id"] == body.get("deployment_id"):
                    deployment = r
                    break
        try:
            equity = float(body.get("equity") or 10000.0)
        except (TypeError, ValueError):
            equity = 10000.0
        advisor = TradeExecutionAdvisor({
            "equity": equity,
        })
        rec = advisor.advise(
            market_view=view,
            deployment=deployment,
            price=body.get("price"),
            symbol=getattr(Config, "RESEARCH_SYMBOLS", "GC=F").split(",")[0])
        return jsonify({"status": "ok", "market_view": view.to_dict(),
                        "recommendation": rec.to_dict()})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route('/api/intelligence/shadow', methods=['GET', 'POST'])
def api_intelligence_shadow():
    """Shadow forward-testing.

    GET  — return the history of shadow forward-test reports.
    POST — run a new shadow forward-test for an approved deployment on a
           held-out recent window.
    """
    try:
        from quant_env.intelligence.execution import ShadowForwardTester

        if request.method == 'GET':
            tester = ShadowForwardTester()
            return jsonify({"status": "ok", "reports": list(reversed(tester.reports))})

        from quant_env.intelligence.deploy import DeploymentManager
        from quant_env.intelligence.data import load_cached_history

        body = request.get_json(silent=True) or {}
        deployment_id = body.get("deployment_id")
        if not deployment_id:
            return jsonify({"status": "error",
                            "error": "deployment_id is required"}), 400
        dep = next((r for r in DeploymentManager().list()
                    if r["id"] == deployment_id), None)
        if dep is None:
            return jsonify({"status": "error",
                            "error": "deployment not found"}), 404

        symbol = body.get("symbol") or getattr(Config, "RESEARCH_SYMBOLS", "GC=F")
        # RESEARCH_SYMBOLS may be a comma-separated corpus — use the first.
        symbol = str(symbol).split(",")[0].strip() or "GC=F"
        history = load_cached_history(_get_project_root(), symbol)
        if history is None:
            return jsonify({"status": "error",
                            "error": f"no cached history for {symbol}"}), 400

        tester = ShadowForwardTester()
        report = tester.test(dep, history,
                             forward_window=int(body.get("window", 200)))
        return jsonify({"status": "ok", "report": report})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


def _get_project_root():
    """gridbots/ — parent of the quant_env package."""
    import os as _os
    return _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))


@app.route('/api/intelligence/deploy', methods=['POST'])
def api_intelligence_deploy():
    """
    Human-gated deployment actions.

    body: {"action": "propose"|"approve"|"force_approve"|"reject"|"void",
           "deployment_id": "...",
           "opportunity_id": "..." (optional propose target),
           "reason": "..." (optional void reason)}

    - ``approve`` is blocked by the hard quality gates.
    - ``force_approve`` bypasses them (auditable: approved_by="human:FORCE").
    - ``void`` retires a deployment forever (never applied by the engine).
    """
    try:
        from quant_env.intelligence.deploy import DeploymentManager
        from quant_env.intelligence.ledger import OpportunityLedger
        data = request.get_json(silent=True) or {}
        action = data.get("action")
        dm = DeploymentManager()

        if action == "approve":
            rec = dm.approve(data.get("deployment_id"))
            if rec is None:
                return jsonify({"status": "error",
                                "error": "Deployment not found."}), 404
            if rec["status"] == "blocked_by_gates":
                return jsonify({
                    "status": "blocked",
                    "deployment": rec,
                    "message": "Deployment BLOCKED by quality gates: "
                               + ", ".join(rec.get("quality", {}).get("failed", [])),
                }), 200
            return jsonify({"status": "ok", "deployment": rec,
                            "message": "Deployment approved — applied on next bot start."})
        if action == "force_approve":
            rec = dm.approve(data.get("deployment_id"), force=True)
            if rec is None:
                return jsonify({"status": "error",
                                "error": "Deployment not found."}), 404
            return jsonify({"status": "ok", "deployment": rec,
                            "message": "Deployment FORCE-approved (auditable override)."})
        if action == "reject":
            rec = dm.reject(data.get("deployment_id"))
            return jsonify({"status": "ok" if rec else "error",
                            "deployment": rec or None})
        if action == "void":
            rec = dm.void(data.get("deployment_id"), reason=data.get("reason", ""))
            return jsonify({"status": "ok" if rec else "error",
                            "deployment": rec or None})
        if action == "propose":
            # Propose the top opportunity (or the best for a given strategy)
            # from the persisted ledger.
            ledger = OpportunityLedger.load()
            target = data.get("strategy_key")
            if target:
                candidates = [o for o in ledger.opportunities
                              if o.strategy_key == target]
            else:
                candidates = ledger.top_opportunities(1)
            if not candidates:
                return jsonify({"status": "error",
                                "error": f"no opportunities to deploy for {target or 'top'}"}), 400
            best = max(candidates, key=lambda o: o.qrice())
            best.status = "proposed"
            ledger.save()
            rec = dm.propose(best, note="proposed from dashboard; awaiting human approval")
            return jsonify({"status": "ok", "deployment": rec})
        return jsonify({"status": "error", "error": f"unknown action: {action}"}), 400
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


# ── Entry point ────────────────────────────────────────────────────────
# ── Entry point ────────────────────────────────────────────────────────

def find_available_port(start=5050, max_attempts=100):
    """Find the next available port starting from `start`."""
    import socket
    for port in range(start, start + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('0.0.0.0', port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No available port found in range {start}-{start + max_attempts - 1}")


if __name__ == '__main__':
    port = find_available_port(5050)
    bridge_url = _get_bridge_url()
    print("=" * 50)
    print(f"  Dashboard:  http://localhost:{port}")
    print(f"  Bridge URL: {bridge_url}")
    print("  Bot starts paused — click 'Start' in the sidebar.")
    mgr = _get_manager()
    accounts = mgr.account_manager.list_accounts()
    print(f"  Accounts: {len(accounts)} configured")
    for acct in accounts:
        bot = mgr.get_bot(acct.id)
        status = "✅ connected" if (bot and bot.connected) else "⏹️ paused"
        print(f"    - {acct.label} ({acct.id[:8]}...) {status}")
    if not accounts:
        bridge_test = _try_bridge_status()
        if bridge_test:
            print(f"  ✅ Broker connected — balance: {bridge_test['balance']}")
        else:
            print("  ⚠️  Bridge not responding — demo data shown")

    # ── Auto-start trading when the MT5 bridge is live (EA running) ──
    # Set AUTO_START_BOT=false in .env to disable.
    bridge_health = _try_bridge_health()
    auto_start = os.environ.get('AUTO_START_BOT', 'true').lower() != 'false'
    if auto_start and bridge_health and bridge_health.get('mode') == 'live' and accounts:
        for acct in accounts:
            if acct.enabled:
                mgr.start_bot(acct.id)
                mgr.resume_bot(acct.id)
                print(f"  ▶ Auto-started bot for {acct.label} ({acct.id[:8]}...)")
    elif accounts and bridge_health:
        print(f"  ⚠️  Bridge mode={bridge_health.get('mode')} — bot NOT auto-started. "
              f"Attach mt5_bridge_ea.mq5, enable Algo Trading, then click ▶ Start.")
    print("=" * 50)
    try:
        import waitress
        waitress.serve(app, host='0.0.0.0', port=port)
    except ImportError:
        app.run(host='0.0.0.0', port=port, debug=False, threaded=False)