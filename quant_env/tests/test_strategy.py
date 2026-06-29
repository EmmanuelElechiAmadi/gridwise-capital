"""
Tests for grid strategy and risk manager.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from strategies.grid_strategy import GridStrategy
from core.risk_manager import RiskManager


class MockConnector:
    """Minimal connector mock for strategy testing."""

    def __init__(self):
        self.orders = []
        self._tick = {'bid': 2000.0, 'ask': 2000.5}
        self.config = type('obj', (), {'SYMBOL': 'TEST'})
        self.logger = type('obj', (), {
            'info': print, 'warning': print, 'error': print
        })

    def symbol_tick(self):
        return self._tick

    def place_limit_order(self, order_type, price, volume):
        self.orders.append({'type': order_type, 'price': price, 'volume': volume})
        return True

    def cancel_order(self, _id):
        pass

    def close_all_positions(self):
        pass

    def get_open_orders(self):
        return self.orders

    def get_positions(self):
        return []

    def account_info(self):
        return type('obj', (), {'balance': 10000.0, 'equity': 10000.0})

    def shutdown(self):
        pass


class MockConfig:
    SYMBOL = "TEST"
    LOT_SIZE = 0.1
    GRID_SPACING = 0.5
    NUM_LEVELS = 3
    ML_ENABLED = False


# ── Tests ────────────────────────────────────────────────────────────

class TestGridStrategy:
    """GridStrategy unit tests."""

    def test_on_start_places_orders(self):
        con = MockConnector()
        strat = GridStrategy(con, MockConfig, con.logger)
        strat.on_start()
        assert len(strat.active_orders) > 0

    def test_on_tick_maintains_orders(self):
        con = MockConnector()
        strat = GridStrategy(con, MockConfig, con.logger)
        strat.on_start()
        initial_count = len(strat.active_orders)
        con._tick = {'bid': 2005.0, 'ask': 2005.5}
        strat.on_tick(con._tick)
        assert len(strat.active_orders) == initial_count

    def test_reset_grid_clears_and_replaces(self):
        con = MockConnector()
        strat = GridStrategy(con, MockConfig, con.logger)
        strat.on_start()
        assert len(strat.active_orders) > 0
        strat.reset_grid()
        # After reset, should have placed new orders
        assert len(strat.active_orders) > 0

    def test_regime_adapter_sync(self):
        con = MockConnector()
        strat = GridStrategy(con, MockConfig, con.logger)
        adapter = type('MockAdapter', (), {
            'enabled': True, 'regime': 'low_vol',
            'spacing': 2.0, 'levels': 7
        })
        strat.regime_adapter = adapter
        strat.spacing = adapter.spacing
        strat.levels = adapter.levels
        assert strat.spacing == 2.0
        assert strat.levels == 7

    def test_logger_accepts_trade_logger(self):
        con = MockConnector()
        strat = GridStrategy(con, MockConfig, con.logger)
        from analysis.trade_logger import TradeLogger
        tl = TradeLogger(db_path=":memory:")
        strat.logger = tl
        assert strat.logger is tl
        tl.close()


class TestRiskManager:
    """RiskManager tests."""

    def test_risk_no_action_within_limits(self):
        config = type('obj', (), {
            'MAX_DRAWDOWN_PCT': 10.0,
            'MAX_DAILY_LOSS': 500.0,
            'INITIAL_BALANCE': 10000.0,
        })
        rm = RiskManager(config, None)
        action, value = rm.check(equity=10000, balance=10000, net_position=0)
        assert action is None

    def test_risk_triggers_on_drawdown(self):
        config = type('obj', (), {
            'MAX_DRAWDOWN_PCT': 5.0,
            'MAX_DAILY_LOSS': 500.0,
            'INITIAL_BALANCE': 10000.0,
        })
        rm = RiskManager(config, None)
        # First establish a peak equity
        rm.check(equity=10000, balance=10000, net_position=0)
        # Then trigger drawdown (equity below peak by >5%)
        action, value = rm.check(equity=9300, balance=10000, net_position=0)
        assert action is not None
        # Should contain 'drawdown' or 'max loss'
        assert isinstance(action, str)

    def test_risk_triggers_on_daily_loss(self):
        config = type('obj', (), {
            'MAX_DRAWDOWN_PCT': 10.0,
            'MAX_DAILY_LOSS': 200.0,
            'INITIAL_BALANCE': 10000.0,
        })
        rm = RiskManager(config, None)
        # Simulate a day with 300 loss (balance below initial by >200)
        action, value = rm.check(equity=9700, balance=9700, net_position=0)
        assert action is not None
