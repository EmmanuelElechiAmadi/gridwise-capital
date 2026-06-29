"""
BacktestEngine — realistic grid strategy simulator.

Features
--------
- Commission per lot (configurable)
- Volatility‑proportional slippage
- Spread applied on fills
- Partial fill probability
- Max loss drawdown stop
- Trend filter (optional)
- Final liquidation of remaining inventory
"""

import pandas as pd
import numpy as np
from copy import deepcopy


class BacktestResult:
    """Container for backtest outputs."""
    def __init__(self):
        self.fills = []
        self.equity = []
        self.fills_df = None
        self.equity_df = None


class BacktestEngine:
    """Simulate a grid strategy over historical OHLCV data with realistic costs."""

    # Default cost parameters — can be overridden via kwargs
    DEFAULT_COMMISSION_PER_LOT = 50.0       # USD round-turn for gold futures
    DEFAULT_SLIPPAGE_FACTOR = 0.1           # fraction of ATR used as slippage
    DEFAULT_FILL_PROBABILITY = 0.85         # limit order fill probability
    DEFAULT_ATR_PERIOD = 14                 # ATR lookback

    def __init__(self, data, strategy_class, initial_cash=10000,
                 regime_adapter=None, **strategy_kwargs):
        self.data = data.copy() if data is not None else data
        self.strategy_class = strategy_class
        self.initial_cash = float(initial_cash)
        self.cash = float(initial_cash)
        self.inventory = 0.0
        self.result = BacktestResult()
        self.active_orders = {}          # price -> side
        self.order_ages = {}             # price -> bar index (for timeouts)
        self.regime_adapter = regime_adapter  # may be None

        # Cost parameters
        self.commission_per_lot = float(
            strategy_kwargs.pop('commission_per_lot', self.DEFAULT_COMMISSION_PER_LOT))
        self.slippage_factor = float(
            strategy_kwargs.pop('slippage_factor', self.DEFAULT_SLIPPAGE_FACTOR))
        self.fill_prob = float(
            strategy_kwargs.pop('fill_probability', self.DEFAULT_FILL_PROBABILITY))
        self.max_loss_pct = None
        if 'max_loss_pct' in strategy_kwargs:
            self.max_loss_pct = float(strategy_kwargs.pop('max_loss_pct'))

        # Trend filter
        self.trend_filter_fn = strategy_kwargs.pop('trend_filter_fn', None)

        # Remaining kwargs go to the strategy (spacing, levels, lot, etc.)
        self.strategy_kwargs = strategy_kwargs

        # Pre‑compute ATR for slippage estimates
        self._atr = None
        self._bar_index = 0

    # ── Public API ──────────────────────────────────────────────────

    def run(self):
        """Execute the backtest.  Returns a BacktestResult."""
        if self.data is None or self.data.empty:
            raise ValueError("No data provided to BacktestEngine.")

        self._validate_data()
        self._precompute_atr()

        # Set up MockConnector + strategy
        mock_con = MockConnector(self)
        first_bar = self.data.iloc[0]
        close_price = float(first_bar['close'])
        mock_con.set_tick(close_price)

        strat = self.strategy_class(mock_con, mock_con.config, mock_con.logger)
        strat.on_start()

        # Copy orders placed during on_start into the engine
        self.active_orders = deepcopy(mock_con.engine.active_orders)
        for p in self.active_orders:
            self.order_ages[p] = self._bar_index

        stopped_early = False

        for idx, bar in self.data.iterrows():
            self._bar_index += 1
            high, low, close = float(bar['high']), float(bar['low']), float(bar['close'])

            # ── 1. Risk guard: max drawdown ──
            if self._check_max_loss(close):
                stopped_early = True
                break

            # ── 2. Trend filter: skip bar if trending ──
            if self._trend_filter_skip(idx):
                eq = self.cash + self.inventory * close
                self.result.equity.append((idx, eq))
                continue

            # ── 3. Order matching ──
            self._match_orders(high, low, close, idx)

            # ── 4. Log equity ──
            eq = self.cash + self.inventory * close
            self.result.equity.append((idx, eq))

        # ── 5. Liquidate remaining inventory ──
        if not stopped_early and self.inventory != 0:
            self._liquidate_inventory(self.data.iloc[-1])

        # ── 6. Build result DataFrames ──
        self._build_result_dfs()
        return self.result

    # ── Internal helpers ────────────────────────────────────────────

    def _validate_data(self):
        required = {'open', 'high', 'low', 'close', 'volume'}
        missing = required - set(self.data.columns.str.lower())
        if missing:
            raise ValueError(f"Data missing columns: {missing}")
        if len(self.data) < 50:
            raise ValueError(f"Too few bars ({len(self.data)}); need at least 50.")

    def _precompute_atr(self):
        """Simple ATR for slippage estimation."""
        high = self.data['high'].values.astype(float)
        low = self.data['low'].values.astype(float)
        close = self.data['close'].values.astype(float)
        tr = np.maximum(high[1:] - low[1:],
                        np.abs(high[1:] - close[:-1]),
                        np.abs(low[1:] - close[:-1]))
        atr = np.full(len(self.data), np.nan)
        atr[self.DEFAULT_ATR_PERIOD] = tr[:self.DEFAULT_ATR_PERIOD].mean()
        for i in range(self.DEFAULT_ATR_PERIOD + 1, len(self.data)):
            atr[i] = (atr[i - 1] * (self.DEFAULT_ATR_PERIOD - 1) + tr[i - 1]) / self.DEFAULT_ATR_PERIOD
        self._atr = pd.Series(atr, index=self.data.index)

    def _check_max_loss(self, close):
        if self.max_loss_pct is None:
            return False
        equity = self.cash + self.inventory * close
        if equity < self.initial_cash * (1.0 - self.max_loss_pct / 100.0):
            if self.inventory != 0:
                side = 'sell' if self.inventory > 0 else 'buy'
                fill_price = self._apply_costs(close, side)
                volume = abs(self.inventory)
                self._execute_fill(side, fill_price, volume, self.data.index[-1])
            self.result.equity.append((self.data.index[-1], self.cash))
            return True
        return False

    def _trend_filter_skip(self, idx):
        if self.trend_filter_fn is None:
            return False
        iloc = self.data.index.get_loc(idx)
        if iloc >= 10:
            recent = self.data.iloc[iloc - 10:iloc]
            return self.trend_filter_fn(recent)
        # Apply filter from bar 0 using whatever data is available
        recent = self.data.iloc[:iloc] if iloc > 0 else self.data.iloc[:1]
        return self.trend_filter_fn(recent)

    def _match_orders(self, high, low, close, idx):
        """Match active limit orders against the bar's price range."""
        filled = []
        for price, side in list(self.active_orders.items()):
            price_f = float(price)
            if low <= price_f <= high:
                # Partial fill probability
                if np.random.random() < self.fill_prob:
                    filled.append((price, side))

        for price, side in filled:
            del self.active_orders[price]
            self.order_ages.pop(price, None)

            fill_price = self._apply_costs(price, side)
            volume = self.strategy_kwargs.get('lot', 0.01)
            self._execute_fill(side, fill_price, volume, idx)

    def _apply_costs(self, base_price, side):
        """Apply spread + slippage to fill price."""
        # Slippage proportional to ATR
        atr_val = self._atr.iloc[min(self._bar_index, len(self._atr) - 1)]
        if np.isnan(atr_val):
            atr_val = base_price * 0.001  # fallback: 0.1% of price
        slippage = atr_val * self.slippage_factor

        # Spread: half in each direction
        spread = atr_val * 0.02  # typical gold futures spread ~ 2% of ATR

        if side == 'buy':
            return base_price + slippage + spread / 2
        else:
            return base_price - slippage - spread / 2

    def _execute_fill(self, side, fill_price, volume, idx):
        """Record a fill and update cash/inventory."""
        commission = volume * self.commission_per_lot
        if side == 'buy':
            self.cash -= fill_price * volume + commission
            self.inventory += volume
        else:
            self.cash += fill_price * volume - commission
            self.inventory -= volume

        self.result.fills.append({
            'timestamp': idx,
            'side': side,
            'price': round(fill_price, 2),
            'volume': volume,
            'commission': round(commission, 2),
        })

    def _liquidate_inventory(self, final_bar):
        final_close = float(final_bar['close'])
        side = 'sell' if self.inventory > 0 else 'buy'
        fill_price = self._apply_costs(final_close, side)
        volume = abs(self.inventory)
        self._execute_fill(side, fill_price, volume, self.data.index[-1])
        self.result.equity.append((self.data.index[-1], self.cash))

    def _build_result_dfs(self):
        if self.result.fills:
            self.result.fills_df = pd.DataFrame(self.result.fills)
        else:
            self.result.fills_df = pd.DataFrame(columns=[
                'timestamp', 'side', 'price', 'volume', 'commission'])
        self.result.equity_df = pd.DataFrame(
            self.result.equity, columns=['timestamp', 'equity'])


class MockConnector:
    """Mock connector used by BacktestEngine to talk to a GridStrategy."""

    def __init__(self, engine):
        self.engine = engine
        self.config = type('obj', (), {
            'SYMBOL': 'BACKTEST',
            'LOT_SIZE': engine.strategy_kwargs.get('lot', 0.01),
            'GRID_SPACING': engine.strategy_kwargs.get('spacing', 0.1),
            'NUM_LEVELS': engine.strategy_kwargs.get('levels', 5),
        })
        self.logger = type('obj', (), {'info': print, 'warning': print, 'error': print})
        self._tick = {'bid': 0.0, 'ask': 0.0}

    def set_tick(self, price):
        self._tick = {'bid': price, 'ask': price}

    def symbol_tick(self):
        return self._tick

    def place_limit_order(self, order_type, price, volume):
        side = 'buy' if 'buy' in order_type else 'sell'
        self.engine.active_orders[float(price)] = side
        self.engine.order_ages[float(price)] = self.engine._bar_index
        return True

    def get_open_orders(self):
        """Return the engine's active orders so the strategy can detect fills."""
        return [
            {'price': float(p), 'type': 'buy_limit' if s == 'buy' else 'sell_limit'}
            for p, s in self.engine.active_orders.items()
        ]

    def account_info(self):
        return type('obj', (), {'balance': self.engine.cash, 'equity': self.engine.cash})

    def get_positions(self):
        return []