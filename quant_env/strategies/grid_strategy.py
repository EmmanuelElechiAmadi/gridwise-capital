from .base_strategy import BaseStrategy
from data_feeds.economic_news import get_forexfactory_events, is_high_impact_near
from analysis.trend_filter import is_trending
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

        # Optional regime adapter – if set, grid auto-adjusts to regime
        self.regime_adapter = None

    def on_start(self):
            
        self.log.info("Waiting for market data...")
        while True:
            tick = self.connector.symbol_tick()
            if tick and tick.get('bid') and tick.get('ask'):
                break
            self.log.info("Tick not available yet, retrying in 30s...")
            time.sleep(30)

        mid = round((tick['bid'] + tick['ask']) / 2, 2)
        self.buy_levels = [round(mid - i * self.spacing, 2) for i in range(1, self.levels+1)]
        self.sell_levels = [round(mid + i * self.spacing, 2) for i in range(1, self.levels+1)]
        self.log.info(f"Grid levels: {sorted(self.buy_levels + self.sell_levels)}")
        for p in self.buy_levels:
            if self.connector.place_limit_order('buy_limit', p, self.lot):
                self.active_orders[p] = 'buy'
        for p in self.sell_levels:
            if self.connector.place_limit_order('sell_limit', p, self.lot):
                self.active_orders[p] = 'sell'
        self.log.info(f"Placed {len(self.active_orders)} orders")
     
   

    
    
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
                self.log.info("News filter: high‑impact event nearby, pausing new orders.")
        # ----------------------------------

        cur = self.connector.get_open_orders()
        cur_prices = {o['price'] for o in cur}
        filled = set(self.active_orders.keys()) - cur_prices
        actions = {'filled': []}
        for price in filled:
            side = self.active_orders.pop(price)
            self.log.info(f"Fill: {side} at {price}")
            self.on_fill(price, side)
            if self.logger:
                self.logger.log_fill(self.symbol, side, price, self.lot)
            actions['filled'].append((price, side))

        # Place new orders only if allowed
        if allow_new_orders:
            # (the existing code that replaces filled orders)
            # … but we actually do that in on_fill already.
            pass

        if time.time() - self.last_status > 10:
            acc = self.connector.account_info()
            pos = self.connector.get_positions()
            net = sum(p['volume'] if p['type']=='buy' else -p['volume'] for p in pos)
            self.log.info(f"Balance: {acc.balance:.2f} Equity: {acc.equity:.2f} Net: {net:.2f}oz Orders: {len(self.active_orders)}")
            self.last_status = time.time()
        return actions    

    def on_fill(self, price, side):
        # Only place opposite order if news filter allows new orders
        allow_new = True
        if getattr(self.config, 'NEWS_FILTER_ENABLED', False):
            events = get_forexfactory_events(self.config.NEWS_FILTER_HOURS_AHEAD)
            if is_high_impact_near(events,
                                   self.config.NEWS_FILTER_MINUTES_BEFORE,
                                   self.config.NEWS_FILTER_MINUTES_AFTER):
                allow_new = False

        if side == 'buy':
            new = round(price + self.spacing, 2)
            if new in self.sell_levels:
                if allow_new:
                    if self.connector.place_limit_order('sell_limit', new, self.lot):
                        self.active_orders[new] = 'sell'
        else:
            new = round(price - self.spacing, 2)
            if new in self.buy_levels:
                if allow_new:
                    if self.connector.place_limit_order('buy_limit', new, self.lot):
                        self.active_orders[new] = 'buy'