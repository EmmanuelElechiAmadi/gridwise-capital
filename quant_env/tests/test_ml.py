"""
Tests for ML modules: regime_model, regime_adapter, and data_builder.
"""

import sys
import os
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ml.regime_model import RegimeClassifier
from ml.regime_adapter import RegimeAdapter
from ml.data_builder import build_features


# ── Helpers ──────────────────────────────────────────────────────────

def _make_ohlcv(length=3000):
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

class TestRegimeClassifier:
    """RegimeClassifier unit tests."""

    def test_train_returns_metrics(self):
        data = _make_ohlcv(500)
        classifier = RegimeClassifier(lookback=20, threshold=25)
        metrics = classifier.train(data)
        assert isinstance(metrics, dict)
        assert 'test_accuracy' in metrics
        assert 'cv_mean' in metrics
        assert 'feature_importances' in metrics

    def test_train_raises_on_insufficient_data(self):
        data = _make_ohlcv(10)
        classifier = RegimeClassifier(lookback=5, threshold=25)
        try:
            classifier.train(data)
            assert False, "Expected ValueError"
        except ValueError:
            pass

    def test_save_load(self, tmp_path):
        data = _make_ohlcv(500)
        classifier = RegimeClassifier(lookback=20, threshold=25)
        classifier.train(data)
        model_path = str(tmp_path / "model.pkl")
        classifier.save(model_path)
        loaded = RegimeClassifier.load(model_path)
        assert loaded.lookback == classifier.lookback
        assert loaded.threshold == classifier.threshold
        assert loaded.model is not None


class TestDataBuilder:
    """Feature builder tests."""

    def test_build_features_returns_dataframe(self):
        data = _make_ohlcv(200)
        X, y = build_features(data)
        assert isinstance(X, pd.DataFrame)
        assert not X.empty
        assert isinstance(y, pd.Series)

    def test_build_features_handles_minimal_data(self):
        data = _make_ohlcv(10)
        X, y = build_features(data)
        # Should not crash; may return empty
        assert isinstance(X, pd.DataFrame)


class TestRegimeAdapter:
    """RegimeAdapter integration tests."""

    def test_start_stop(self):
        config = type('obj', (), {
            'ML_ENABLED': False,
            'YAHOO_SYMBOL': 'GC=F',
            'ML_RETRAIN_INTERVAL': 60,
        })
        adapter = RegimeAdapter(config)
        adapter.start()
        # ML disabled so _running stays False (no thread started)
        assert not adapter._running
        adapter.stop()
        assert not adapter._running

    def test_regime_is_unknown_initially(self):
        config = type('obj', (), {
            'ML_ENABLED': True,
            'YAHOO_SYMBOL': 'GC=F',
            'ML_RETRAIN_INTERVAL': 60,
            'GRID_SPACING': 0.5,
            'NUM_LEVELS': 3,
        })
        adapter = RegimeAdapter(config)
        assert adapter.regime == RegimeAdapter.UNKNOWN

    def test_grid_params_default(self):
        config = type('obj', (), {
            'ML_ENABLED': True,
            'YAHOO_SYMBOL': 'GC=F',
            'ML_RETRAIN_INTERVAL': 60,
            'GRID_SPACING': 0.5,
            'NUM_LEVELS': 3,
        })
        adapter = RegimeAdapter(config)
        assert adapter.spacing > 0
        assert adapter.levels > 0