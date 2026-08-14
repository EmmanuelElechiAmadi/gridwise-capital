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

# ── Kronos predictor / breakout enhancer (Phase: live-engine bugfix) ─────

def _fake_inference_outputs(context=512, pred_len=20, sample_count=5):
    """Mimic real auto_regressive_inference: it decodes the LAST max_context
    tokens (context + forecasts), so the returned blocks are wider than the
    requested horizon until trimmed."""
    return (np.zeros((1, context, 6), dtype=np.float32),
            np.zeros((1, sample_count, context, 6), dtype=np.float32))


class TestKronosPredictorHorizonTrim:
    """Regression for the live 'Shape of passed values is (512, 6), indices
    imply (20, 6)' error: _predict_with_raw must trim the autoregressive
    decode to pred_len before building the forecast frame."""

    def test_predict_with_raw_trims_to_pred_len(self, monkeypatch):
        import ml.kronos.predictor as pred_mod
        from ml.kronos.predictor import KronosPricePredictor

        class _FakeInfer:
            max_context = 512
            device = "cpu"
            tokenizer = object()
            model = object()

        def fake_inference(tokenizer, model, x, x_stamp, y_stamp, max_context,
                           pred_len, **kwargs):
            return _fake_inference_outputs(context=max_context, pred_len=pred_len)

        # predictor.py imports this locally inside _predict_with_raw, so patch
        # the source module (ml.kronos.kronos) — the local import resolves there.
        import ml.kronos.kronos as kronos_mod
        monkeypatch.setattr(kronos_mod, "auto_regressive_inference", fake_inference)

        df = _make_ohlcv(512)  # exactly the case that crashed the live engine
        predictor = KronosPricePredictor()
        predictor._predictor = _FakeInfer()   # bypass _lazy_load / model download
        forecast_df, raw_samples = predictor._predict_with_raw(df)
        assert len(forecast_df) == pred_mod.KRONOS_PRED_LEN
        assert raw_samples.shape == (pred_mod.KRONOS_SAMPLE_COUNT,
                                     pred_mod.KRONOS_PRED_LEN, 6)
        # Forecast frame is indexed by the forecast timestamps (not the context).
        assert len(forecast_df.index) == pred_mod.KRONOS_PRED_LEN

    def test_get_forecast_features_works_with_long_context(self, monkeypatch):
        """The full feature pipeline (used by collect_kronos / enhancer /
        adapter) must survive a > (max_context - pred_len) input window."""
        import ml.kronos.predictor as pred_mod
        from ml.kronos.predictor import KronosPricePredictor

        class _FakeInfer:
            max_context = 512
            device = "cpu"
            tokenizer = object()
            model = object()

        def fake_inference(tokenizer, model, x, x_stamp, y_stamp, max_context,
                           pred_len, **kwargs):
            return _fake_inference_outputs(context=max_context, pred_len=pred_len)

        import ml.kronos.kronos as kronos_mod
        monkeypatch.setattr(kronos_mod, "auto_regressive_inference", fake_inference)

        df = _make_ohlcv(700)
        predictor = KronosPricePredictor()
        predictor._predictor = _FakeInfer()
        features = predictor.get_forecast_features(df)
        assert len(features["forecast_close"]) == pred_mod.KRONOS_PRED_LEN
        assert features["regime_label"] in ("BULL", "BEAR", "RANGING")

    def test_predict_with_raw_drops_dirty_rows(self, monkeypatch):
        """Live feeds can contain NaN/Inf rows (market-closed hours) — they
        must be cleaned before reaching the model, not crash the forecast."""
        import ml.kronos.predictor as pred_mod
        from ml.kronos.predictor import KronosPricePredictor

        class _FakeInfer:
            max_context = 512
            device = "cpu"
            tokenizer = object()
            model = object()

        def fake_inference(tokenizer, model, x, x_stamp, y_stamp, max_context,
                           pred_len, **kwargs):
            return _fake_inference_outputs(context=max_context, pred_len=pred_len)

        import ml.kronos.kronos as kronos_mod
        monkeypatch.setattr(kronos_mod, "auto_regressive_inference", fake_inference)

        df = _make_ohlcv(120)
        # Poison 40 rows with NaN/Inf in the close column (dirty live feed).
        df.loc[df.index[40:80], ["open", "high", "low", "close"]] = np.nan
        df.loc[df.index[90], ["close"]] = np.inf
        predictor = KronosPricePredictor()
        predictor._predictor = _FakeInfer()
        forecast_df, raw = predictor._predict_with_raw(df)
        assert len(forecast_df) == pred_mod.KRONOS_PRED_LEN
        assert raw.shape == (pred_mod.KRONOS_SAMPLE_COUNT,
                             pred_mod.KRONOS_PRED_LEN, 6)


class TestKronosSpotAnchoring:
    """Live signal paths must be spot-denominated (XAU/USD), not futures."""

    def test_is_gold_symbol_only_matches_gold(self):
        from ml.kronos.spot import is_gold_symbol
        assert is_gold_symbol("GC=F") is True
        assert is_gold_symbol("XAUUSD.r") is True
        assert is_gold_symbol("XAUUSD=F") is True
        assert is_gold_symbol("SI=F") is False
        assert is_gold_symbol("CL=F") is False

    def test_reanchor_to_spot_shifts_ohlcv(self):
        from ml.kronos.spot import reanchor_to_spot
        df = _make_ohlcv(50)
        df["close"].iloc[-1] = 4391.5
        out = reanchor_to_spot(df, spot_price=4333.33)
        # Last close == the spot reference after the shift.
        assert round(float(out["close"].iloc[-1]), 2) == 4333.33
        # The shift is a uniform basis offset (all levels move together).
        basis = 4391.5 - 4333.33
        assert abs(float(out["high"].iloc[-1]) - (float(df["high"].iloc[-1]) - basis)) < 1e-6

    def test_reanchor_fails_safe_without_spot(self, monkeypatch):
        from ml.kronos import spot as spot_mod
        from ml.kronos.spot import reanchor_to_spot
        monkeypatch.setattr(spot_mod, "fetch_live_spot", lambda *a, **k: None)
        df = _make_ohlcv(30)
        assert reanchor_to_spot(df) is df  # untouched when spot unavailable


class TestKronosBreakoutEnhancerFallback:
    """Broker symbols (XAUUSD.r) don't exist on Yahoo — the enhancer must fall
    back through YAHOO_SYMBOL / gold aliases / cached gold history."""

    def test_fetch_data_walks_fallback_chain(self, monkeypatch):
        import sys as _sys
        from ml.kronos.breakout_enhancer import KronosBreakoutEnhancer

        class _Cfg:
            SYMBOL = "XAUUSD.r"
            YAHOO_SYMBOL = "GC=F"

        class _Log:
            def info(self, *a): pass
            def warning(self, *a): pass
            def error(self, *a): pass

        calls = []

        class _EmptyTicker:
            def __init__(self, sym):
                calls.append(sym)
            def history(self, **kw):
                return pd.DataFrame()

        class _FakeYF:
            Ticker = _EmptyTicker

        monkeypatch.setitem(_sys.modules, "yfinance", _FakeYF())
        # Neutralise the spot re-anchor (it would otherwise do a live network
        # fetch and shift the frame) — this test only exercises the chain.
        from ml.kronos import spot as spot_mod
        monkeypatch.setattr(spot_mod, "fetch_live_spot", lambda *a, **k: None)

        cached = _make_ohlcv(300)
        enhancer = KronosBreakoutEnhancer(_Cfg(), _Log())
        monkeypatch.setattr(enhancer, "_load_cached_gold", lambda: cached)
        df = enhancer._fetch_data()
        assert df is cached
        # YAHOO_SYMBOL first, then gold aliases, before the CSV fallback.
        assert calls == ["XAUUSD.r", "GC=F", "XAUUSD", "XAUUSD=F"]

    def test_load_cached_gold_returns_clean_ohlcv(self, tmp_path):
        from ml.kronos.breakout_enhancer import KronosBreakoutEnhancer

        csv_path = str(tmp_path / "gold_data.csv")
        _make_ohlcv(200).to_csv(csv_path)

        class _Cfg:
            SYMBOL = "XAUUSD.r"

        class _Log:
            def info(self, *a): pass
            def warning(self, *a): pass
            def error(self, *a): pass

        enhancer = KronosBreakoutEnhancer(_Cfg(), _Log())
        df = enhancer._load_cached_gold(candidates=[csv_path])
        assert df is not None and len(df) == 200
        assert {"open", "high", "low", "close", "volume"} <= set(df.columns)
