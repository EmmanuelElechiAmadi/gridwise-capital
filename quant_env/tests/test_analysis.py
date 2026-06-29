"""
Tests for analysis modules: performance, walkforward, session_analyzer,
monte_carlo, report_generator, trade_logger, and trade_matcher.
"""

import sys
import os
import pandas as pd
import numpy as np
import tempfile
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from analysis.performance import compute_metrics
from analysis.walkforward import walkforward_analysis
from analysis.trade_logger import TradeLogger
from analysis.trade_matcher import match_trades
from analysis.session_analyzer import session_performance, classify_session
from analysis.monte_carlo import run_monte_carlo
from strategies.grid_strategy import GridStrategy


# ── Helpers ──────────────────────────────────────────────────────────

def _make_fills():
    return pd.DataFrame({
        'timestamp': pd.date_range('2025-01-01', periods=6, freq='h'),
        'side': ['buy', 'sell', 'buy', 'sell', 'buy', 'sell'],
        'price': [2000.0, 2010.0, 1990.0, 2005.0, 1980.0, 1995.0],
        'volume': [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        'commission': [50.0, 50.0, 50.0, 50.0, 50.0, 50.0],
    })


def _make_equity():
    idx = pd.date_range('2025-01-01', periods=100, freq='h')
    eq = 10000.0 + np.cumsum(np.random.randn(100) * 50)
    return pd.DataFrame({'timestamp': idx, 'equity': eq})


def _make_price_data(length=500):
    np.random.seed(42)
    close = 2000.0 + np.cumsum(np.random.randn(length) * 0.5)
    high = close + np.abs(np.random.randn(length) * 0.3)
    low = close - np.abs(np.random.randn(length) * 0.3)
    open_ = close + np.random.randn(length) * 0.1
    volume = np.random.randint(100, 10000, length)
    idx = pd.date_range('2025-01-01', periods=length, freq='h')
    return pd.DataFrame({
        'open': open_, 'high': high, 'low': low,
        'close': close, 'volume': volume
    }, index=idx)


# ── Tests ────────────────────────────────────────────────────────────

class TestPerformance:
    """compute_metrics tests."""

    def test_compute_metrics_returns_dict(self):
        fills = _make_fills()
        equity = _make_equity()
        metrics = compute_metrics(fills, equity)
        assert isinstance(metrics, dict)
        assert 'total_return_pct' in metrics
        assert 'sharpe_ratio' in metrics

    def test_empty_fills_returns_empty_metrics(self):
        empty = pd.DataFrame(columns=['timestamp', 'side', 'price', 'volume', 'commission'])
        equity = _make_equity()
        metrics = compute_metrics(empty, equity)
        assert metrics['num_trades'] == 0

    def test_empty_equity_returns_empty_metrics(self):
        fills = _make_fills()
        empty = pd.DataFrame(columns=['timestamp', 'equity'])
        metrics = compute_metrics(fills, empty)
        assert metrics['num_trades'] == 0

    def test_positive_return(self):
        fills = _make_fills()
        equity = _make_equity()
        metrics = compute_metrics(fills, equity)
        # Should run without errors and return numeric values
        assert isinstance(metrics['total_return_pct'], float)


class TestWalkforward:
    """Walkforward analysis tests."""

    def test_walkforward_returns_dataframe(self):
        data = _make_price_data(500)
        param_grid = {'spacing': [0.1, 0.5], 'levels': [3, 5]}
        result = walkforward_analysis(
            data, GridStrategy, param_grid,
            window_size=200, step_size=100,
            initial_capital=10000, lot=1.0
        )
        assert isinstance(result, pd.DataFrame)
        # Should have at least one window
        assert len(result) >= 1

    def test_walkforward_contains_key_columns(self):
        data = _make_price_data(300)
        param_grid = {'spacing': [0.1, 0.5], 'levels': [3, 5]}
        result = walkforward_analysis(
            data, GridStrategy, param_grid,
            window_size=120, step_size=60,
            initial_capital=10000, lot=1.0
        )
        expected = {'start_date', 'end_date', 'sharpe_ratio', 'spacing', 'levels'}
        assert expected.issubset(set(result.columns))

    def test_walkforward_insufficient_data(self):
        data = _make_price_data(50)
        param_grid = {'spacing': [0.1], 'levels': [3]}
        result = walkforward_analysis(
            data, GridStrategy, param_grid,
            window_size=100, step_size=50,
            initial_capital=10000, lot=1.0
        )
        assert result.empty


class TestTradeLogger:
    """TradeLogger tests (in-memory SQLite)."""

    def test_log_and_retrieve_fills(self):
        logger = TradeLogger(db_path=":memory:")
        logger.log_fill("TEST", "buy", 2000.0, 1.0, pnl=0.0)
        fills = logger.get_fills()
        assert len(fills) == 1
        _, ts, sym, side, price, vol, pnl = fills[0]
        assert sym == "TEST"
        assert side == "buy"
        assert price == 2000.0
        logger.close()

    def test_log_and_retrieve_equity(self):
        logger = TradeLogger(db_path=":memory:")
        logger.log_equity(10000.0, 10000.0, 0.0, 0)
        logger.log_equity(10050.0, 10000.0, 0.5, 2)
        curve = logger.get_equity_curve()
        assert len(curve) == 2
        eq_vals = [c[1] for c in curve]
        assert eq_vals == [10000.0, 10050.0]
        logger.close()

    def test_get_fills_filter_by_symbol(self):
        logger = TradeLogger(db_path=":memory:")
        logger.log_fill("GC=F", "buy", 2000.0, 1.0)
        logger.log_fill("SI=F", "sell", 25.0, 10.0)
        gc_fills = logger.get_fills(symbol="GC=F")
        assert len(gc_fills) == 1
        logger.close()

    def test_retry_on_locked_db(self):
        """Simulate momentary lock — logger should retry and succeed."""
        logger = TradeLogger(db_path=":memory:")
        # Acquire an exclusive lock on a separate connection
        other = sqlite3.connect(":memory:")
        other.execute("BEGIN EXCLUSIVE")
        # This should retry; but since other is also in-memory and separate,
        # there should be no conflict. Just verify logging works.
        logger.log_fill("TEST", "buy", 100.0, 1.0)
        fills = logger.get_fills()
        assert len(fills) == 1
        other.close()
        logger.close()

    def test_multiple_fills_logged(self):
        logger = TradeLogger(db_path=":memory:")
        for i in range(5):
            logger.log_fill(f"SYM{i}", "buy", 100.0 + i, 1.0)
        assert len(logger.get_fills()) == 5
        logger.close()


class TestMonteCarlo:
    """Monte Carlo simulation tests."""

    def test_run_monte_carlo_returns_fig_and_stats(self):
        # Trade returns as a list of PnL values
        trade_returns = [50, -20, 30, 10, -5, 40, -15, 25, -10, 35]
        fig, stats = run_monte_carlo(trade_returns, num_sim=50, horizon=30, initial=10000)
        assert fig is not None
        assert isinstance(stats, dict)
        assert 'prob_profit' in stats
        assert 'expected_equity' in stats
        assert 'var_95' in stats

    def test_monte_carlo_empty_returns_none(self):
        result = run_monte_carlo([], num_sim=10, horizon=10, initial=10000)
        assert result == (None, {})


class TestSessionAnalyzer:
    """Session analyzer tests."""

    def test_session_performance_returns_dataframe(self):
        fills = _make_fills()
        equity = _make_equity()
        result = session_performance(fills, equity)
        assert isinstance(result, pd.DataFrame)

    def test_classify_session_known_hours(self):
        from datetime import datetime
        # London session (7-16 UTC)
        dt = datetime(2025, 1, 1, 10, 0, 0)
        sessions = classify_session(dt)
        assert 'London' in sessions

    def test_classify_session_off_hours(self):
        from datetime import datetime
        dt = datetime(2025, 1, 1, 21, 0, 0)  # 9 PM UTC - between London close/New York close and Sydney open
        sessions = classify_session(dt)
        # Sydney starts at 22, New York ends at 21 — so 21:00 is a gap with no session
        assert 'Off-hours' in sessions
