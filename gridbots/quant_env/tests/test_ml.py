"""
Tests for ML modules: regime_model, regime_adapter, and data_builder.
"""

import sys
import os
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ml.regime_model import RegimeClassifier, REGIME_BEAR, REGIME_RANGING, REGIME_BULL
from ml.regime_adapter import RegimeAdapter
from ml.data_builder import build_features, label_directional_regime, compute_atr


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
        assert 'per_class_accuracy' in metrics
        assert 'feature_importances' in metrics
        assert 'n_classes' in metrics
        assert metrics['n_classes'] >= 2

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
        assert loaded.features == classifier.features

    def test_predict_returns_known_regime(self):
        data = _make_ohlcv(500)
        classifier = RegimeClassifier(lookback=20, threshold=25)
        classifier.train(data)

        # Build feature vector for prediction
        X, _ = build_features(data, lookback=20, regime_threshold=1.0)
        latest = X.iloc[-1:]

        result = classifier.predict_with_confidence(latest)
        assert 'regime' in result
        assert 'confidence' in result
        assert 'regime_name' in result
        assert 'probabilities' in result
        assert result['regime'] in (REGIME_BEAR, REGIME_RANGING, REGIME_BULL)
        assert 0.0 <= result['confidence'] <= 1.0

    def test_health_check(self):
        data = _make_ohlcv(500)
        classifier = RegimeClassifier(lookback=20, threshold=25)
        health_before = classifier.health_check()
        assert not health_before['healthy']  # not trained yet

        classifier.train(data)
        health_after = classifier.health_check()
        # Should be healthy after training (or at least have model_fitted)
        assert health_after['checks']['model_fitted'] is True
        assert health_after['checks']['has_features'] is True

    def test_predict_proba_format(self):
        data = _make_ohlcv(500)
        classifier = RegimeClassifier(lookback=20, threshold=25)
        classifier.train(data)
        X, _ = build_features(data, lookback=20, regime_threshold=1.0)
        probas = classifier.predict_proba(X.iloc[-1:])
        assert isinstance(probas, dict)
        assert all(k in (REGIME_BEAR, REGIME_RANGING, REGIME_BULL) for k in probas)
        assert abs(sum(probas.values()) - 1.0) < 0.01


class TestDataBuilder:
    """Feature builder tests."""

    def test_build_features_returns_dataframe(self):
        data = _make_ohlcv(1000)
        X, y = build_features(data)
        assert isinstance(X, pd.DataFrame)
        assert not X.empty
        assert isinstance(y, pd.Series)
        # Target should have varied labels
        assert y.nunique() >= 2

    def test_build_features_handles_minimal_data(self):
        data = _make_ohlcv(10)
        X, y = build_features(data)
        # Should not crash; may return empty
        assert isinstance(X, pd.DataFrame)

    def test_label_directional_regime(self):
        close = pd.Series([100, 101, 102, 103, 104, 105, 106, 107, 108, 109])
        atr = pd.Series([1.0] * 10)
        labels = label_directional_regime(close, atr, lookahead=3, threshold=1.0)
        assert len(labels) == 10
        assert set(labels.unique()).issubset({-1, 0, 1})

    def test_compute_atr(self):
        high = pd.Series([102, 104, 103, 105, 106])
        low = pd.Series([98, 99, 100, 101, 102])
        close = pd.Series([100, 102, 101, 103, 104])
        atr = compute_atr(high, low, close, period=3)
        assert len(atr) == 5
        assert atr.iloc[-1] > 0


class TestRegimeAdapter:
    """RegimeAdapter integration tests."""

    def test_start_stop(self):
        config = type('obj', (), {
            'ML_ENABLED': False,
            'YAHOO_SYMBOL': 'GC=F',
            'ML_REFRESH_MINUTES': 60,
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
            'ML_REFRESH_MINUTES': 60,
            'GRID_SPACING': 0.5,
            'NUM_LEVELS': 3,
        })
        adapter = RegimeAdapter(config)
        assert adapter.regime == RegimeAdapter.UNKNOWN

    def test_grid_params_default(self):
        config = type('obj', (), {
            'ML_ENABLED': True,
            'YAHOO_SYMBOL': 'GC=F',
            'ML_REFRESH_MINUTES': 60,
            'GRID_SPACING': 0.5,
            'NUM_LEVELS': 3,
        })
        adapter = RegimeAdapter(config)
        assert adapter.spacing > 0
        assert adapter.levels > 0

    def test_regime_name_mapping(self):
        config = type('obj', (), {
            'ML_ENABLED': False,
            'YAHOO_SYMBOL': 'GC=F',
        })
        adapter = RegimeAdapter(config)
        assert adapter.regime_name == "unknown"