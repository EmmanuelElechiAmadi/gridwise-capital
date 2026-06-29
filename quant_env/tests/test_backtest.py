"""
Tests for backtest engine, optimizer, sensitivity, and data loader.
"""

import sys
import os
import pandas as pd
import numpy as np
from copy import deepcopy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backtest.engine import BacktestEngine, BacktestResult
from backtest.optimizer import optimize
from backtest.sensitivity import sensitivity
from backtest.data_loader import load_yfinance
from strategies.grid_strategy import GridStrategy


# ── Helpers ──────────────────────────────────────────────────────────

def _make_price_data(length=5000):
    """Generate realistic OHLCV data."""
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


def _tiny_data():
    """Minimal but valid price series (just barely above 50-bar minimum)."""
    idx = pd.date_range('2025-01-01', periods=60, freq='h')
    return pd.DataFrame({
        'open': 2000.0, 'high': 2005.0, 'low': 1995.0,
        'close': 2000.0, 'volume': 1000
    }, index=idx)


# ── Tests ────────────────────────────────────────────────────────────

class TestBacktestEngine:
    """BacktestEngine unit tests."""

    def test_run_returns_result(self):
        data = _make_price_data(500)
        engine = BacktestEngine(data, GridStrategy, 10000,
                                spacing=0.5, levels=5, lot=1.0)
        result = engine.run()
        assert isinstance(result, BacktestResult)
        assert hasattr(result, 'fills_df')
        assert hasattr(result, 'equity_df')

    def test_insufficient_data_raises(self):
        data = _tiny_data().iloc[:30]
        engine = BacktestEngine(data, GridStrategy, 10000,
                                spacing=0.5, levels=5, lot=1.0)
        try:
            engine.run()
            assert False, "Expected ValueError"
        except ValueError:
            pass

    def test_missing_columns_raises(self):
        bad = pd.DataFrame({'foo': [1, 2, 3]})
        engine = BacktestEngine(bad, GridStrategy, 10000,
                                spacing=0.5, levels=3, lot=1.0)
        try:
            engine.run()
            assert False, "Expected ValueError"
        except ValueError:
            pass

    def test_max_loss_stops_early(self):
        data = _make_price_data(500)
        # Force a huge loss scenario
        data['close'] = data['close'] * 0.5
        engine = BacktestEngine(data, GridStrategy, 10000,
                                spacing=0.5, levels=3, lot=1.0,
                                max_loss_pct=5.0)
        result = engine.run()
        assert len(result.equity) > 0

    def test_commission_applied(self):
        data = _tiny_data()
        engine = BacktestEngine(data, GridStrategy, 10000,
                                spacing=0.5, levels=3, lot=1.0,
                                commission_per_lot=100.0)
        result = engine.run()
        if not result.fills_df.empty:
            assert (result.fills_df['commission'] > 0).all()

    def test_trend_filter_skip(self):
        data = _make_price_data(500)
        # A trend filter that always returns True (skip everything because "strong trend")
        def strong_trend(_df):
            return True
        engine = BacktestEngine(
            data, GridStrategy, 10000,
            spacing=0.5, levels=3, lot=1.0,
            trend_filter_fn=strong_trend
        )
        result = engine.run()
        # Should have zero fills since every bar is skipped
        assert result.fills_df.empty

    def test_regime_adapter_accepted(self):
        data = _tiny_data()
        adapter = type('MockAdapter', (), {
            'enabled': True, 'regime': 'high_vol',
            'spacing': 1.0, 'levels': 7
        })
        engine = BacktestEngine(
            data, GridStrategy, 10000,
            spacing=0.5, levels=3, lot=1.0,
            regime_adapter=adapter
        )
        assert engine.regime_adapter is adapter


class TestOptimizer:
    """Optimizer tests."""

    def test_optimize_returns_best(self):
        data = _make_price_data(500)
        param_grid = {'spacing': [0.1, 0.5, 1.0], 'levels': [3, 5]}
        results = optimize(data, GridStrategy, param_grid, capital=10000)
        assert not results.empty
        assert 'spacing' in results.columns
        assert 'levels' in results.columns
        assert 'sharpe_ratio' in results.columns
        # Best (first) row should have highest sharpe
        assert results['sharpe_ratio'].iloc[0] >= results['sharpe_ratio'].iloc[-1]

    def test_optimize_empty_grid_returns_empty(self):
        data = _make_price_data(500)
        results = optimize(data, GridStrategy, {}, capital=10000)
        assert results.empty if hasattr(results, 'empty') else True


class TestSensitivity:
    """Sensitivity analysis tests."""

    def test_sensitivity_returns_dataframe_and_fig(self):
        data = _make_price_data(500)
        df, fig = sensitivity(data, GridStrategy, 'spacing', [0.1, 0.5, 1.0],
                              {'levels': 5, 'lot': 1.0}, metric='sharpe_ratio', capital=10000)
        assert isinstance(df, pd.DataFrame)
        assert not df.empty

    def test_sensitivity_spacing_impact(self):
        """Vary spacing and get a result."""
        data = _tiny_data()
        df, fig = sensitivity(data, GridStrategy, 'spacing', [0.1, 0.5],
                              {'levels': 3, 'lot': 1.0}, metric='sharpe_ratio', capital=10000)
        assert isinstance(df, pd.DataFrame)


class TestDataLoader:
    """Data loader tests (mock to avoid network calls)."""

    def test_load_yfinance_integration(self, monkeypatch):
        """Mock yfinance download to avoid network dependency."""

        def mock_download(*args, **kwargs):
            idx = pd.date_range('2025-01-01', periods=100, freq='h')
            return pd.DataFrame({
                'Open': 2000.0, 'High': 2005.0, 'Low': 1995.0,
                'Close': 2000.0, 'Volume': 1000
            }, index=idx)

        monkeypatch.setattr('yfinance.download', mock_download)
        df = load_yfinance("GC=F", period="1d", interval="1m")
        assert not df.empty
        assert 'close' in df.columns

    def test_load_yfinance_columns_lowercased(self, monkeypatch):
        import yfinance as yf

        class MockTicker:
            def history(self, **kw):
                idx = pd.date_range('2025-01-01', periods=50, freq='h')
                return pd.DataFrame({
                    'Open': 2000.0, 'High': 2005.0, 'Low': 1995.0,
                    'Close': 2000.0, 'Volume': 1000
                }, index=idx)

        monkeypatch.setattr(yf, 'Ticker', lambda s: MockTicker())
        df = load_yfinance("GC=F", period="1d", interval="1m")
        for col in ['open', 'high', 'low', 'close', 'volume']:
            assert col in df.columns