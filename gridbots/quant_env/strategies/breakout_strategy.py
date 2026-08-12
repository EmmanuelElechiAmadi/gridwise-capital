"""
BreakoutStrategy — Multi-timeframe breakout trading with partial TP ($3/$5/$10)
and fixed SL ($3).

How it works
------------
1. Builds 5‑minute OHLC candles from incoming ticks.
2. Aggregates 5M → 1H → 4H candles.
3. The 4H range (recent_high / recent_low over N bars) defines the breakout zone.
4. 1H closes that break the 4H range provide confirmation (configurable consecutive
   bars required).
5. On a confirmed 5M close beyond the 4H range + threshold → enter a market
   position.
6. Position is scaled out in three portions at $3, $5, $10 profit (or stopped
   out entirely at $3 loss).

Because the MT5 bridge only supports ``close_all_positions`` (no per‑ticket
partial close), the strategy manages TP portions **in memory**.  When a TP level
is reached the portion is marked as closed; when all portions are closed (or
SL is hit) the bridge is told to close everything.
"""

import time
from collections import deque
from typing import Optional

from .base_strategy import BaseStrategy

# Conditionally import Kronos – it's an optional enhancement.
try:
    from ml.kronos import KronosBreakoutEnhancer

    _HAVE_KRONOS = True
except ImportError:
    _HAVE_KRONOS = False


# ═══════════════════════════════════════════════════════════════════════
# Candle helpers
# ═══════════════════════════════════════════════════════════════════════

class CandleBuilder:
    """Builds a single OHLC candle from tick‑level price updates.

    Each time a new candle period begins (based on *minutes*), the previous
    candle is finalised and returned from ``update()``.
    """

    __slots__ = ('minutes', '_period', 'completed',
                 'open', 'high', 'low', 'close', 'volume', 'start_time',
                 '_current_key')

    def __init__(self, minutes: int, max_candles: int = 100):
        self.minutes = minutes
        self._period = minutes * 60
        self.completed: deque[dict] = deque(maxlen=max_candles)
        self._reset()

    # ── public ────────────────────────────────────────────────────────

    def update(self, price: float, timestamp: float) -> Optional[dict]:
        """Ingest a tick.  Returns a completed candle dict *once* per
        candle boundary, otherwise ``None``."""
        key = int(timestamp) // self._period

        if self._current_key is None:
            # First tick ever
            self._start_candle(price, timestamp, key)
            return None

        if key == self._current_key:
            self._extend_candle(price)
            return None

        # Candle boundary crossed — finalise previous, start new
        done = self._finalise()
        self._start_candle(price, timestamp, key)
        return done

    # ── private ───────────────────────────────────────────────────────

    def _reset(self):
        self.open: Optional[float] = None
        self.high: Optional[float] = None
        self.low: Optional[float] = None
        self.close: Optional[float] = None
        self.volume: int = 0
        self.start_time: Optional[float] = None
        self._current_key: Optional[int] = None

    def _start_candle(self, price: float, ts: float, key: int):
        self.open = self.high = self.low = self.close = price
        self.start_time = ts
        self._current_key = key
        self.volume = 1

    def _extend_candle(self, price: float):
        if price > self.high:
            self.high = price
        if price < self.low:
            self.low = price
        self.close = price
        self.volume += 1

    def _finalise(self) -> Optional[dict]:
        if self.open is None:
            return None
        candle = {
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'start_time': self.start_time,
        }
        self.completed.append(candle)
        return candle


class CandleAggregator:
    """Aggregates lower‑timeframe candles into higher‑timeframe candles.

    e.g. 12 × 5m → 1h,  4 × 1h → 4h
    """

    __slots__ = ('lower_min', 'higher_min', 'candles_per',
                 '_buffer', 'completed')

    def __init__(self, lower_minutes: int, higher_minutes: int,
                 max_candles: int = 50):
        self.lower_min = lower_minutes
        self.higher_min = higher_minutes
        self.candles_per = higher_minutes // lower_minutes
        self._buffer: list[dict] = []
        self.completed: deque[dict] = deque(maxlen=max_candles)

    def add(self, candle: dict) -> Optional[dict]:
        """Feed a lower‑tf candle.  Returns a newly completed higher‑tf
        candle if one was produced, otherwise ``None``."""
        self._buffer.append(candle)
        if len(self._buffer) < self.candles_per:
            return None

        high = max(c['high'] for c in self._buffer)
        low = min(c['low'] for c in self._buffer)
        higher = {
            'open': self._buffer[0]['open'],
            'high': high,
            'low': low,
            'close': self._buffer[-1]['close'],
            'start_time': self._buffer[0]['start_time'],
        }
        self.completed.append(higher)
        self._buffer = []
        return higher

    def recent(self, n: int) -> list[dict]:
        """Return the *n* most recent completed candles (or fewer if not
        enough exist)."""
        all_ = list(self.completed)
        return all_[-n:] if n < len(all_) else all_


# ═══════════════════════════════════════════════════════════════════════
# Strategy
# ═══════════════════════════════════════════════════════════════════════

class BreakoutStrategy(BaseStrategy):
    """Breakout from 4H range, confirmed by 1H, entered on 5M.

    Parameters (set via config or dashboard)
    ----------------------------------------
    LOOKBACK_4H_BARS        : int   – candles for 4H range (default 5)
    BREAKOUT_THRESHOLD_PCT  : float – % above high / below low to trigger
    CONFIRMATION_BARS_1H    : int   – consecutive 1H closes confirming
    LOT_SIZE                : float – position size
    MAX_POSITIONS           : int   – max concurrent positions
    TP_DOLLARS              : str   – comma‑separated TP levels (default "3,5,10")
    SL_DOLLARS              : float – stop‑loss in dollars   (default 3)
    """

    STRATEGY_NAME = "Breakout Strategy"
    STRATEGY_DESC = (
        "Trades breakouts from recent high/low ranges. "
        "Uses 4H candles for range, 1H for confirmation, 5M for entry. "
        "Partial TP at $3/$5/$10, SL at $3. "
        "Optional Kronos ML enhancement for trade filtering and dynamic TP/SL."
    )

    PARAMS = {
        'lookback_4h_bars': {
            'label': '4H Lookback (bars)',
            'type': 'number',
            'default': 5,
            'step': 1,
            'min': 2,
        },
        'breakout_threshold_pct': {
            'label': 'Breakout Threshold (%)',
            'type': 'number',
            'default': 0.05,
            'step': 0.01,
            'min': 0.01,
        },
        'confirmation_bars_1h': {
            'label': '1H Confirmation (bars)',
            'type': 'number',
            'default': 2,
            'step': 1,
            'min': 1,
        },
        'lot': {
            'label': 'Lot Size',
            'type': 'number',
            'default': 0.01,
            'step': 0.01,
            'min': 0.01,
        },
        'max_positions': {
            'label': 'Max Positions',
            'type': 'number',
            'default': 1,
            'step': 1,
            'min': 1,
        },
        'tp_dollars': {
            'label': 'TP Levels ($)',
            'type': 'text',
            'default': '3,5,10',
            'hint': 'Comma‑separated dollar amounts',
        },
        'sl_dollars': {
            'label': 'Stop Loss ($)',
            'type': 'number',
            'default': 3,
            'step': 0.5,
            'min': 0.5,
        },
        'kronos_enabled': {
            'label': 'Kronos ML Enhancement',
            'type': 'boolean',
            'default': False,
        },
    }

    # ── lifecycle ─────────────────────────────────────────────────────

    def on_start(self):
        """Called when the bot starts. Seeds the multi-timeframe candle
        history from recent price data so breakouts can be evaluated
        immediately instead of waiting ~20h for the 4H range to form from
        live ticks.  Skipped in backtests / dummy connectors."""
        if not hasattr(self.connector, 'bridge') and not hasattr(self.connector, 'base_url'):
            return
        try:
            self._seed_from_history()
        except Exception as exc:
            self.log.warning(f"Breakout history seed failed: {exc}")

        # Start the Kronos enhancer's background forecast refresh so trade
        # filtering / dynamic TP-SL actually run (not just the flag).
        if self._kronos:
            try:
                self._kronos.start()
                self.log.info("KronosBreakoutEnhancer background refresh started.")
            except Exception as exc:
                self.log.warning(f"Kronos enhancer start failed: {exc}")

    def _seed_from_history(self):
        """Pre-build 1H/4H candles from recent hourly gold price history.

        Uses live Yahoo Finance GC=F hourly bars (best effort), falling back
        to the local gold_data.csv snapshot resampled to hourly.  Once seeded,
        the 4H range is available on the first live tick.
        """
        import os
        import pandas as pd

        df = None
        try:
            import yfinance as yf
            df = yf.download("GC=F", period="1mo", interval="1h",
                             progress=False, auto_adjust=False, timeout=10)
            if df is not None and not df.empty and isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
        except Exception:
            df = None

        if df is None or df.empty:
            # Local snapshot fallback (1-min bars -> resample to 1h)
            path = os.path.join(os.path.dirname(__file__), '..', '..', 'gold_data.csv')
            if os.path.exists(path):
                try:
                    d = pd.read_csv(path)
                    d['Datetime'] = pd.to_datetime(d['Datetime'], utc=True, errors='coerce')
                    d = d.dropna(subset=['Datetime']).set_index('Datetime')
                    d.columns = [c.lower() for c in d.columns]
                    d = d.resample('1h').agg({
                        'open': 'first', 'high': 'max',
                        'low': 'min', 'close': 'last', 'volume': 'sum',
                    }).dropna()
                    df = d
                except Exception:
                    df = None

        if df is None or df.empty:
            return
        df.columns = [str(c).lower() for c in df.columns]
        if not {'open', 'high', 'low', 'close'}.issubset(set(df.columns)):
            return

        now = time.time()
        n = len(df)
        hours = []
        for i in range(n):
            hours.append({
                'open': float(df['open'].iloc[i]),
                'high': float(df['high'].iloc[i]),
                'low': float(df['low'].iloc[i]),
                'close': float(df['close'].iloc[i]),
                'start_time': now - (n - i) * 3600,
            })

        # Reset and seed the aggregators
        self._agg_1h.completed.clear()
        self._agg_4h.completed.clear()
        self._agg_4h._buffer = []
        for c in hours:
            self._agg_1h.completed.append(c)
            self._agg_4h.add(c)

        candles = self._agg_4h.recent(self.lookback_4h)
        if len(candles) >= 2:
            self._recent_high = max(c['high'] for c in candles)
            self._recent_low = min(c['low'] for c in candles)
            self.log.info(
                f"📊 Breakout seeded: {len(hours)} hourly bars -> "
                f"{len(self._agg_4h.completed)} 4H candles; "
                f"range high={self._recent_high:.2f} low={self._recent_low:.2f}"
            )


    def __init__(self, connector, config, logger):
        super().__init__(connector, config, logger)

        # ---- config ----
        self.lookback_4h = getattr(config, 'LOOKBACK_4H_BARS', 5)
        self.breakout_threshold = getattr(
            config, 'BREAKOUT_THRESHOLD_PCT', 0.05) / 100.0
        self.confirmation_bars = getattr(config, 'CONFIRMATION_BARS_1H', 2)
        self.lot = getattr(config, 'LOT_SIZE', 0.01)
        self.max_positions = getattr(config, 'MAX_POSITIONS', 1)

        # TP / SL in dollars
        tp_str = getattr(config, 'TP_DOLLARS', '3,5,10')
        try:
            self.tp_dollars = sorted(float(x.strip())
                                     for x in tp_str.split(',') if x.strip())
        except (ValueError, TypeError, AttributeError):
            self.tp_dollars = [3.0, 5.0, 10.0]
        self.sl_dollars = float(getattr(config, 'SL_DOLLARS', 3.0))

        # ---- candle chain ----
        self._c5 = CandleBuilder(5)
        self._agg_1h = CandleAggregator(5, 60)    # 12 × 5m → 1h
        self._agg_4h = CandleAggregator(60, 240)   # 4 × 1h → 4h

        # ---- breakout state ----
        self._recent_high: Optional[float] = None
        self._recent_low: Optional[float] = None
        self._bullish_confirmed = False
        self._bearish_confirmed = False
        self._conf_count = 0
        self._conf_side: Optional[str] = None  # 'bullish' | 'bearish' | None

        # ---- position state ----
        self.position: Optional[dict] = None
        self.logger: object = None  # set externally by the runner

        # ---- Kronos ML enhancement ----
        self._kronos_enabled = getattr(config, 'KRONOS_BREAKOUT_ENABLED', False)
        if not self._kronos_enabled:
            # Allow per‑strategy override via the 'kronos_enabled' PARAM value
            self._kronos_enabled = getattr(config, 'kronos_enabled', False)
        self._kronos: Optional[KronosBreakoutEnhancer] = None
        if _HAVE_KRONOS and self._kronos_enabled:
            try:
                self._kronos = KronosBreakoutEnhancer(config, logger=self.log)
                self.log.info("KronosBreakoutEnhancer initialised for BreakoutStrategy.")
            except Exception as exc:
                self.log.warning(f"Failed to initialise KronosBreakoutEnhancer: {exc}")
                self._kronos = None

        self._last_status = 0.0
        self._trade_count = 0

    # ── bar handler (used by backtest engine) ──────────────────────────

    def on_bar(self, bar: dict):
        """Called by the backtest engine for each OHLC bar (usually 1h).

        Since backtest data arrives as complete OHLC bars rather than
        ticks, we bypass the tick→5M→1H chain and treat each bar as a
        1H candle directly.  This feeds into the 4H aggregator so the
        breakout logic still works.
        """
        ts = self._ts_from_bar(bar)
        if ts is None:
            return

        # Build a proper 1H candle from the bar's OHLC
        c1 = {
            'open': float(bar['open']),
            'high': float(bar['high']),
            'low': float(bar['low']),
            'close': float(bar['close']),
            'start_time': ts,
        }

        # Feed into 4H aggregator (4 × 1h = 4h)
        c4 = self._agg_4h.add(c1)
        if c4 is not None:
            self._on_4h_candle(c4)

        # Run 1H confirmation check
        self._on_1h_candle(c1)

        # Entry check: if confirmed, enter at this bar's close
        self._try_entry_from_bar(c1)

        # TP / SL check: use bar high for buy TP / sell SL, bar low for
        # buy SL / sell TP (worst-case directional check per bar)
        if self.position is not None:
            self._check_tp_sl_on_bar(c1)

    @staticmethod
    def _ts_from_bar(bar: dict) -> Optional[float]:
        ts = bar.get('timestamp')
        if ts is None:
            return None
        if hasattr(ts, 'timestamp'):
            return ts.timestamp()
        try:
            return float(ts)
        except (ValueError, TypeError):
            return None

    def on_start(self):
        self.log.info(
            "BreakoutStrategy ready — building 5M candles from ticks, "
            "aggregating to 1H / 4H."
        )
        if self._kronos:
            self._kronos.start()
        self._reset_state()

    def on_stop(self):
        self._close_position("STOP")
        if self._kronos:
            self._kronos.stop()

    def on_fill(self, price, side):
        if self.logger:
            self.logger.log_fill(self.symbol, side, price, self.lot)

    # ── tick handler ──────────────────────────────────────────────────

    def on_tick(self, tick):
        now = time.time()
        price = self._mid(tick)

        # 1. Update candles and process completions
        self._process_ticks(price, now)

        # 2. Manage open position
        if self.position is not None:
            self._check_tp_sl(price)

        # 3. Periodic status
        if now - self._last_status > 30:
            self._log_status(now)

        return {}

    # ── candle processing chain ───────────────────────────────────────

    def _process_ticks(self, price: float, ts: float):
        """Feed price into the 5m candle; if a candle completes, cascade
        up to 1h → 4h and fire callbacks in dependency order."""
        c5 = self._c5.update(price, ts)
        if c5 is None:
            return

        # 5M completed → feed into 1H aggregator
        c1 = self._agg_1h.add(c5)
        if c1 is not None:
            # 1H completed → feed into 4H aggregator
            c4 = self._agg_4h.add(c1)
            if c4 is not None:
                self._on_4h_candle(c4)
            self._on_1h_candle(c1)
        self._on_5m_candle(c5)

    def _on_4h_candle(self, candle: dict):
        """Recalculate the breakout range from recent 4H candles."""
        candles = self._agg_4h.recent(self.lookback_4h)
        if len(candles) < 2:
            return
        self._recent_high = max(c['high'] for c in candles)
        self._recent_low = min(c['low'] for c in candles)
        self.log.info(
            f"📊 4H range updated: high={self._recent_high:.2f} "
            f"low={self._recent_low:.2f}"
        )

    def _on_1h_candle(self, candle: dict):
        """Check whether the 1H close confirms a breakout of the 4H range."""
        if self._recent_high is None or self._recent_low is None:
            return

        close = candle['close']

        if close > self._recent_high:
            self._update_confirmation('bullish')
        elif close < self._recent_low:
            self._update_confirmation('bearish')
        else:
            self._reset_confirmation()

        self._bullish_confirmed = (
            self._conf_side == 'bullish'
            and self._conf_count >= self.confirmation_bars
        )
        self._bearish_confirmed = (
            self._conf_side == 'bearish'
            and self._conf_count >= self.confirmation_bars
        )

    def _on_5m_candle(self, candle: dict):
        """Trigger entry if price breaks the 4H range on a confirmed 5M
        close.  Kronos filters/adjusts the trade when enabled."""
        if self.position is not None:
            return
        if self._recent_high is None or self._recent_low is None:
            return

        # Kronos-adjusted threshold
        threshold = self.breakout_threshold
        if self._kronos:
            threshold = self._kronos.adjust_breakout_threshold(threshold)

        close = candle['close']
        threshold_buy = self._recent_high * (1 + threshold)
        threshold_sell = self._recent_low * (1 - threshold)

        if self._bullish_confirmed and close >= threshold_buy:
            if self._kronos and not self._kronos.should_filter('buy'):
                return
            self._enter_position('buy', close)
        elif self._bearish_confirmed and close <= threshold_sell:
            if self._kronos and not self._kronos.should_filter('sell'):
                return
            self._enter_position('sell', close)

    # ── confirmation helpers ──────────────────────────────────────────

    def _update_confirmation(self, side: str):
        if self._conf_side == side:
            self._conf_count += 1
        else:
            self._conf_side = side
            self._conf_count = 1

    def _reset_confirmation(self):
        self._conf_side = None
        self._conf_count = 0
        self._bullish_confirmed = False
        self._bearish_confirmed = False

    # ── position management ───────────────────────────────────────────

    def _enter_position(self, side: str, price: float):
        if self.position is not None:
            return
        if self._trade_count >= self.max_positions:
            return

        # Kronos-adjusted TP/SL
        tp_dollars = list(self.tp_dollars)
        sl_dollars = self.sl_dollars
        if self._kronos:
            tp_dollars, sl_dollars = self._kronos.adjust_tp_sl(tp_dollars, sl_dollars)

        direction = 1 if side == 'buy' else -1
        tp_levels = [round(price + direction * tp, 2)
                     for tp in tp_dollars]
        sl_price = round(price - direction * sl_dollars, 2)

        self.position = {
            'entry_price': price,
            'side': side,
            'lot': self.lot,
            'remaining_lot': self.lot,
            'tp_levels': tp_levels,
            'tp_hit': [False] * len(tp_levels),
            'sl_price': sl_price,
        }

        # Place a market‑style order through the connector.
        # The bridge receives order_type 'buy' / 'sell'; the EA should treat
        # these as market orders.  If the bridge doesn't support market
        # orders, a limit order at the current price is a close substitute.
        order_type = 'buy' if side == 'buy' else 'sell'
        self.connector.place_limit_order(order_type, price, self.lot,
                                         comment='BreakoutEntry')

        self._trade_count += 1
        self.log.info(
            f"🚀 ENTRY {side.upper()} @ {price:.2f}  "
            f"SL={sl_price:.2f}  TPs={tp_levels}"
        )

    def _check_tp_sl(self, current_price: float):
        pos = self.position
        if pos is None:
            return

        # ── SL check ──
        hit_sl = False
        if pos['side'] == 'buy' and current_price <= pos['sl_price']:
            hit_sl = True
        elif pos['side'] == 'sell' and current_price >= pos['sl_price']:
            hit_sl = True

        if hit_sl:
            self.log.info(
                f"🛑 SL hit @ {current_price:.2f} "
                f"(limit {pos['sl_price']:.2f})"
            )
            self._close_position("SL")
            return

        # ── TP checks (partial scale‑out) ──
        for i, (tp_level, hit) in enumerate(zip(pos['tp_levels'],
                                                  pos['tp_hit'])):
            if hit:
                continue
            triggered = False
            if pos['side'] == 'buy' and current_price >= tp_level:
                triggered = True
            elif pos['side'] == 'sell' and current_price <= tp_level:
                triggered = True

            if triggered:
                pos['tp_hit'][i] = True
                portion = self.lot / len(pos['tp_levels'])
                pos['remaining_lot'] -= portion
                self.log.info(
                    f"🎯 TP{i + 1} (${self.tp_dollars[i]:g}) hit "
                    f"@ {tp_level:.2f}"
                )
                if self.logger:
                    self.logger.log_fill(self.symbol, pos['side'],
                                         tp_level, portion)

                # If all shares have been closed we can clean up.
                if pos['remaining_lot'] <= 0.0001:
                    self._close_position("ALL_TP")
                return  # only one TP per tick

    def _close_position(self, reason: str):
        if self.position is None:
            return

        pos = self.position
        self.log.info(
            f"🔒 CLOSE {pos['side'].upper()} — {reason}  "
            f"(entry={pos['entry_price']:.2f})"
        )

        # Tell the MT5 bridge to close everything on this symbol.
        self.connector.close_all_positions()

        # Log the final fill if there's remaining size.
        remaining = max(pos['remaining_lot'], 0.0)
        if remaining > 0.0001 and self.logger:
            self.logger.log_fill(self.symbol, 'close',
                                 self._mid({'bid': 0, 'ask': 0}),
                                 remaining)

        self.position = None

    # ── TP/SL from bar (backtest path) ───────────────────────────────

    def _check_tp_sl_on_bar(self, bar: dict):
        """Evaluate TP/SL using the full bar range.

        For a buy position:
          - SL hit if bar low ≤ sl_price
          - TP hit if bar high ≥ tp_level
        For a sell position:
          - SL hit if bar high ≥ sl_price
          - TP hit if bar low ≤ tp_level
        """
        pos = self.position
        if pos is None:
            return

        low = bar['low']
        high = bar['high']

        # ── SL check ──
        hit_sl = False
        if pos['side'] == 'buy' and low <= pos['sl_price']:
            hit_sl = True
        elif pos['side'] == 'sell' and high >= pos['sl_price']:
            hit_sl = True

        if hit_sl:
            self.log.info(
                f"🛑 SL hit on bar (low={low:.2f} high={high:.2f}) "
                f"limit={pos['sl_price']:.2f}"
            )
            self._close_position("SL")
            return

        # ── TP checks ──
        for i, (tp_level, hit) in enumerate(zip(pos['tp_levels'],
                                                  pos['tp_hit'])):
            if hit:
                continue
            triggered = False
            if pos['side'] == 'buy' and high >= tp_level:
                triggered = True
            elif pos['side'] == 'sell' and low <= tp_level:
                triggered = True

            if triggered:
                pos['tp_hit'][i] = True
                portion = self.lot / len(pos['tp_levels'])
                pos['remaining_lot'] -= portion
                self.log.info(
                    f"🎯 TP{i + 1} (${self.tp_dollars[i]:g}) hit on bar "
                    f"@ {tp_level:.2f}"
                )
                if self.logger:
                    self.logger.log_fill(self.symbol, pos['side'],
                                         tp_level, portion)

                if pos['remaining_lot'] <= 0.0001:
                    self._close_position("ALL_TP")
                return  # one TP level per bar

    # ── entry from bar (backtest path) ────────────────────────────────

    def _try_entry_from_bar(self, bar: dict):
        """Attempt entry directly on a 1H bar close.

        This is the backtest path — since we only see OHLC bars, not 5M
        ticks, we check whether the bar's close confirms the breakout and
        meets the threshold, then enter at the close price.
        Kronos filters/adjusts the trade when enabled.
        """
        if self.position is not None:
            return
        if self._recent_high is None or self._recent_low is None:
            return

        # Kronos-adjusted threshold
        threshold = self.breakout_threshold
        if self._kronos:
            threshold = self._kronos.adjust_breakout_threshold(threshold)

        close = bar['close']
        threshold_buy = self._recent_high * (1 + threshold)
        threshold_sell = self._recent_low * (1 - threshold)

        if self._bullish_confirmed and close >= threshold_buy:
            if self._kronos and not self._kronos.should_filter('buy'):
                return
            self._enter_position('buy', close)
        elif self._bearish_confirmed and close <= threshold_sell:
            if self._kronos and not self._kronos.should_filter('sell'):
                return
            self._enter_position('sell', close)

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _mid(tick: dict) -> float:
        bid = tick.get('bid', 0) or 0
        ask = tick.get('ask', 0) or 0
        return (bid + ask) / 2.0

    def _log_status(self, now: float):
        acc = self.connector.account_info()
        balance = acc.balance if acc else 0
        equity = acc.equity if acc else 0
        pos_str = f" pos={self.position['side'][:1].upper()}" if self.position else ""
        kronos_str = f"  {self._kronos.status_str()}" if self._kronos else ""
        self.log.info(
            f"Balance={balance:.2f} Equity={equity:.2f}{pos_str}  "
            f"4H range=[{self._recent_low or 0:.2f}–{self._recent_high or 0:.2f}]  "
            f"5M candles={len(self._c5.completed)}{kronos_str}"
        )
        self._last_status = now

    def get_kronos_breakout_status(self) -> dict:
        """Return a snapshot of the Kronos breakout enhancer state for the dashboard.

        Returns a dict with direction, confidence, volatility mode, and which
        adjustment features are active.  Returns an empty dict if Kronos is
        disabled or the enhancer is not initialised.
        """
        if self._kronos is None or not self._kronos.enabled:
            return {}

        try:
            summary = self._kronos.get_forecast_summary()
            return {
                'enabled': summary.get('enabled', False),
                'direction': summary.get('direction', 'NEUTRAL'),
                'confidence': summary.get('confidence', 0.0),
                'volatility_mode': summary.get('volatility_mode', 'MEDIUM'),
                'volatility': summary.get('volatility', 0.0),
                'trend': summary.get('trend', 0.0),
                'trend_strength': summary.get('trend_strength', 0.0),
                'last_refresh': summary.get('last_refresh', 0.0),
                'threshold_adjustment': self._kronos._vol_adjust_threshold,
                'tp_sl_adjustment': self._kronos._dynamic_tp_sl,
                'filter_active': self._kronos._filter_direction,
                'status_str': self._kronos.status_str(),
            }
        except Exception:
            return {}

    def _reset_state(self):
        self.position = None
        self._c5 = CandleBuilder(5)
        self._agg_1h = CandleAggregator(5, 60)
        self._agg_4h = CandleAggregator(60, 240)
        self._recent_high = None
        self._recent_low = None
        self._reset_confirmation()
        self._trade_count = 0
        if self._kronos:
            # Refresh the forecast immediately on reset
            self._kronos.refresh()
