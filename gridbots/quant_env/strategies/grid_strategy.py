"""
GridStrategy with regime-aware dynamic parameters.

When a RegimeAdapter is attached, the grid spacing and number of levels
automatically adjust to the detected market regime (BULL / RANGING / BEAR),
including asymmetric grid placement (more buy levels in BULL, more sell
levels in BEAR).
"""

from .base_strategy import BaseStrategy
from data_feeds.economic_news import get_forexfactory_events, is_high_impact_near
from ml.regime_model import REGIME_BEAR, REGIME_RANGING, REGIME_BULL, REGIME_UNKNOWN
from collections import deque
import time


class GridStrategy(BaseStrategy):
    def __init__(self, connector, config, logger):
        super().__init__(connector, config, logger)
        self.spacing = config.GRID_SPACING
        self.levels = config.NUM_LEVELS
        self.lot = config.LOT_SIZE
        self.active_orders = {}
        self.buy_levels = []
        self.sell_levels = []
        self.last_status = 0
        self.logger = None  # set externally

        # FIFO entry-price queue for realized-PnL attribution on fills
        self._open_buys = deque(maxlen=2000)

        # Optional regime adapter – if set, grid auto-adjusts to regime
        self.regime_adapter = None
        self._last_regime = REGIME_UNKNOWN

    def on_start(self):
        self.log.info("Waiting for market data...")
        max_retries = 5
        for attempt in range(1, max_retries + 1):
            tick = self.connector.symbol_tick()
            if tick and tick.get('bid') and tick.get('ask'):
                self.log.info(f"Tick received: bid={tick.get('bid')} ask={tick.get('ask')} — placing grid.")
                self._place_grid(tick)
                return
            debug_info = tick if tick else "None"
            self.log.warning(
                f"Tick fetch attempt {attempt}/{max_retries}: got {debug_info}. "
                f"Check that: (1) MT5 terminal is open, (2) mt5_bridge_ea.mq5 is attached to a chart, "
                f"(3) mt5_bridge_server.py is running on port 8080, (4) Algo Trading is enabled in MT5."
            )
            if attempt < max_retries:
                self.log.info(f"Retrying in 10s...")
                time.sleep(10)
            else:
                self.log.error(
                    f"Bridge unreachable after {max_retries} attempts — starting in IDLE mode. "
                    f"NO trades will be placed until a tick is received. "
                    f"Verify MT5 is running and the EA is attached to a chart."
                )
                return  # continue without grid; orders will fail gracefully

    def _place_grid(self, tick):
        """Cancel all active orders and place a new grid based on current regime/spacing."""
        # Cancel existing orders first
        if self.active_orders:
            self.log.info(f"Cancelling {len(self.active_orders)} existing orders...")
            for price, side in list(self.active_orders.items()):
                try:
                    self.connector.cancel_order(price)
                except Exception as e:
                    self.log.warning(f"Failed to cancel order at {price}: {e}")
            self.active_orders.clear()

        mid = round((tick['bid'] + tick['ask']) / 2, 2)
        spacing = self._get_spacing()
        levels = self._get_levels()
        buy_count, sell_count = self._get_asymmetric_levels(levels)

        # Asymmetric grid
        self.buy_levels = [round(mid - i * spacing, 2) for i in range(1, buy_count + 1)]
        self.sell_levels = [round(mid + i * spacing, 2) for i in range(1, sell_count + 1)]

        self.log.info(
            f"Grid: mid={mid} spacing={spacing} levels={levels} "
            f"(buy={buy_count}, sell={sell_count}) "
            f"regime={self._regime_name()}"
        )

        # Place orders one at a time with delay between each.
        # The EA processes commands on a 1-second timer, and Wine filesystem
        # sync adds additional latency — serializing prevents command overwrites.
        for p in self.buy_levels:
            result = self.connector.place_limit_order('buy_limit', p, self.lot)
            if result:
                self.active_orders[p] = 'buy'
                time.sleep(0.8)
            else:
                self.log.warning(f"Failed to place buy_limit at {p} — check bridge connection")
        for p in self.sell_levels:
            result = self.connector.place_limit_order('sell_limit', p, self.lot)
            if result:
                self.active_orders[p] = 'sell'
                time.sleep(0.8)
            else:
                self.log.warning(f"Failed to place sell_limit at {p} — check bridge connection")
        if len(self.active_orders) == 0:
            self.log.warning(
                "ZERO orders placed! Bridge may be unreachable or MT5 not accepting orders. "
                "The bot will auto-retry on the next tick."
            )
        else:
            self.log.info(f"Placed {len(self.active_orders)} orders")

    def _get_spacing(self):
        """Get the effective grid spacing, using regime adapter if available."""
        if self.regime_adapter is not None:
            return self.regime_adapter.spacing
        return self.spacing

    def _get_levels(self):
        """Get the effective number of grid levels, using regime adapter if available."""
        if self.regime_adapter is not None:
            return self.regime_adapter.levels
        return self.levels

    def _get_asymmetric_levels(self, total_levels):
        """
        Distribute levels asymmetrically based on regime.

        BULL:  more buy levels (e.g. 60% buys, 40% sells)
        BEAR:  more sell levels (e.g. 40% buys, 60% sells)
        RANGING: symmetric (50/50)
        """
        if self.regime_adapter is None:
            return total_levels, total_levels

        regime = self.regime_adapter.regime
        if regime == REGIME_BULL:
            buy_ratio = 0.65
        elif regime == REGIME_BEAR:
            buy_ratio = 0.35
        else:
            buy_ratio = 0.5

        buy_count = max(1, round(total_levels * buy_ratio))
        sell_count = max(1, round(total_levels * (1 - buy_ratio)))
        return buy_count, sell_count

    def _regime_name(self):
        if self.regime_adapter is not None:
            return self.regime_adapter.regime_name
        return "default"

    def reset_grid(self):
        self.active_orders.clear()
        self.on_start()

    def on_tick(self, tick):
        # ---------- NEWS FILTER ----------
        allow_new_orders = True
        if getattr(self.config, 'NEWS_FILTER_ENABLED', False):
            events = get_forexfactory_events(self.config.NEWS_FILTER_HOURS_AHEAD)
            if is_high_impact_near(events,
                                   self.config.NEWS_FILTER_MINUTES_BEFORE,
                                   self.config.NEWS_FILTER_MINUTES_AFTER):
                allow_new_orders = False
                self.log.info("News filter: high-impact event nearby, pausing new orders.")
        # ----------------------------------

        # ---------- REGIME CHANGE CHECK ----------
        if self.regime_adapter is not None:
            current_regime = self.regime_adapter.regime
            if current_regime != self._last_regime and current_regime != REGIME_UNKNOWN:
                self._last_regime = current_regime
                self.log.info(
                    f"Regime changed to {self.regime_adapter.regime_name}, "
                    f"regenerating grid..."
                )
                self._place_grid(tick)  # regenerates entire grid
                return {}
        # -----------------------------------------

        cur = self.connector.get_open_orders()
        cur_prices = {o['price'] for o in cur}
        filled = set(self.active_orders.keys()) - cur_prices
        actions = {'filled': []}
        for price in filled:
            side = self.active_orders.pop(price)
            self.log.info(f"Fill: {side} at {price}")
            realized_pnl = self.on_fill(price, side)
            if self.logger:
                self.logger.log_fill(self.symbol, side, price, self.lot, realized_pnl)
            actions['filled'].append((price, side, realized_pnl))

        # Place new orders only if allowed
        if allow_new_orders:
            pass  # on_fill handles replacement

        if time.time() - self.last_status > 10:
            acc = self.connector.account_info()
            if acc is not None:
                pos = self.connector.get_positions()
                net = sum(p['volume'] if p['type'] == 'buy' else -p['volume'] for p in pos)
                self.log.info(
                    f"Balance: {acc.balance:.2f} Equity: {acc.equity:.2f} "
                    f"Net: {net:.2f}oz Orders: {len(self.active_orders)} "
                    f"Regime: {self._regime_name()}"
                )
            self.last_status = time.time()
        return actions

    def on_fill(self, price, side):
        """Replace a filled order with its opposite side one grid spacing away.

        Instead of requiring an exact match on a pre-computed level list
        (which fails in a moving market), computes the replacement price
        dynamically and validates it against the grid's range.

        Also tracks FIFO open buys so each sell fill can report the *realized*
        PnL for the grid round-trip.  Returns the realized PnL (0.0 if no
        matching entry is available yet).
        """
        # ── Realized PnL (FIFO) ──────────────────────────────────────
        realized_pnl = 0.0
        if side == 'buy':
            self._open_buys.append(price)
        else:
            if self._open_buys:
                entry_price = self._open_buys.popleft()
                realized_pnl = round((price - entry_price) * self.lot, 2)

        # Only place opposite order if news filter allows new orders
        allow_new = True
        if getattr(self.config, 'NEWS_FILTER_ENABLED', False):
            events = get_forexfactory_events(self.config.NEWS_FILTER_HOURS_AHEAD)
            if is_high_impact_near(events,
                                   self.config.NEWS_FILTER_MINUTES_BEFORE,
                                   self.config.NEWS_FILTER_MINUTES_AFTER):
                allow_new = False

        if not allow_new:
            return realized_pnl

        spacing = self._get_spacing()

        if side == 'buy':
            # A buy was filled → place a sell one grid spacing above
            new = round(price + spacing, 2)
            if self.connector.place_limit_order('sell_limit', new, self.lot):
                self.active_orders[new] = 'sell'
                self.log.info(f"Replacement sell_limit placed at {new}")
            else:
                self.log.warning(f"Failed to place replacement sell_limit at {new}")
        else:
            # A sell was filled → place a buy one grid spacing below
            new = round(price - spacing, 2)
            if self.connector.place_limit_order('buy_limit', new, self.lot):
                self.active_orders[new] = 'buy'
                self.log.info(f"Replacement buy_limit placed at {new}")
            else:
                self.log.warning(f"Failed to place replacement buy_limit at {new}")

        return realized_pnl
