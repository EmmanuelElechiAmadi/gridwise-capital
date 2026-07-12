"""
RegimeClassifier – predicts directional market regime (BULL / RANGING / BEAR).

Trains a Random Forest on directional-regime labels, exposes class
probabilities for confidence-based decision making, and supports
serialisation with full metadata.
"""

import os
import json
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
import joblib

# Label constants exposed for other modules
REGIME_BEAR = -1
REGIME_RANGING = 0
REGIME_BULL = 1
REGIME_UNKNOWN = -999  # sentinel for "not yet classified"


class RegimeClassifier:
    """
    Direction-aware regime classifier.

    Predicts one of three regimes:
        BEAR (-1)  – market expected to move DOWN
        RANGING (0) – market expected to move sideways / low conviction
        BULL (1)   – market expected to move UP

    Parameters
    ----------
    lookback : int
        Rolling window for feature computation.
    threshold : int
        Kept for backward compatibility (not used in new target logic).
    confidence_threshold : float
        Minimum prediction probability required to return a confident
        prediction. Below this, the classifier returns RANGING as a
        conservative fallback.
    regime_threshold : float
        ATR multiplier used by the label function.
    """

    def __init__(self, lookback=20, threshold=25, confidence_threshold=0.4,
                 regime_threshold=1.0):
        self.lookback = lookback
        self.threshold = threshold
        self.confidence_threshold = confidence_threshold
        self.regime_threshold = regime_threshold
        self.model = None
        self.features = []
        self._feature_importances = None
        self._cv_scores = None
        self._test_accuracy = None
        self._cv_mean = None
        self._cv_std = None

    def train(self, df, n_jobs=-1):
        """
        Train the regime classifier on historical OHLCV data.

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV data with columns: open, high, low, close, volume.
        n_jobs : int
            Number of parallel jobs for training.

        Returns
        -------
        dict
            Training metrics.
        """
        from .data_builder import build_features
        X, y = build_features(
            df,
            lookback=self.lookback,
            target_lookahead=self.lookback,
            regime_threshold=self.regime_threshold,
        )

        if len(X) < 100:
            raise ValueError(
                f"Not enough samples ({len(X)}) to train. Need at least 100."
            )

        # Check that the target has at least 2 classes
        n_classes = y.nunique()
        if n_classes < 2:
            raise ValueError(
                f"Target labels are constant (only {int(y.iloc[0])}). "
                f"Try adjusting regime_threshold or using a longer dataset."
            )

        class_counts = y.value_counts().to_dict()
        print(f"Class distribution: {class_counts}")

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, shuffle=False, stratify=None
        )

        self.model = RandomForestClassifier(
            n_estimators=200,
            max_depth=8,
            min_samples_leaf=20,
            class_weight='balanced_subsample',
            random_state=42,
            n_jobs=n_jobs if n_jobs > 0 else None,
        )
        self.model.fit(X_train, y_train)
        self.features = X.columns.tolist()

        # Feature importances
        self._feature_importances = {
            name: round(imp, 4)
            for name, imp in zip(self.features, self.model.feature_importances_)
        }

        test_acc = self.model.score(X_test, y_test)
        # Per-class accuracy
        y_pred = self.model.predict(X_test)
        per_class_acc = {}
        for cls in sorted(y.unique()):
            mask = y_test == cls
            if mask.sum() > 0:
                per_class_acc[int(cls)] = round((y_pred[mask] == cls).mean(), 4)

        metrics = {
            'test_accuracy': round(test_acc, 4),
            'per_class_accuracy': per_class_acc,
            'n_classes': int(n_classes),
            'class_distribution': {int(k): int(v) for k, v in class_counts.items()},
            'train_samples': len(X_train),
            'test_samples': len(X_test),
            'feature_importances': self._feature_importances,
        }

        self._test_accuracy = metrics['test_accuracy']

        self._print_training_summary(metrics)
        return metrics

    def predict(self, feature_vector: pd.DataFrame) -> int:
        """
        Predict regime for a single feature vector (1 row).

        Returns one of REGIME_BEAR, REGIME_RANGING, REGIME_BULL.
        If confidence is below threshold, returns REGIME_RANGING
        as a conservative fallback.
        """
        if self.model is None:
            return REGIME_UNKNOWN

        # Align columns
        missing = [c for c in self.features if c not in feature_vector.columns]
        if missing:
            raise ValueError(f"Missing features: {missing}")
        X = feature_vector[self.features]

        pred = self.model.predict(X)[0]
        proba = self.model.predict_proba(X)[0]
        confidence = max(proba)

        if confidence < self.confidence_threshold:
            return REGIME_RANGING  # fallback to ranging
        return int(pred)

    def predict_proba(self, feature_vector: pd.DataFrame) -> dict:
        """
        Get full probability distribution over regimes.

        Returns
        -------
        dict
            Mapping from regime label (int) to probability (float),
            e.g. {-1: 0.1, 0: 0.7, 1: 0.2}
        """
        if self.model is None:
            return {REGIME_BEAR: 0.0, REGIME_RANGING: 0.0, REGIME_BULL: 0.0}

        X = feature_vector[self.features]
        proba = self.model.predict_proba(X)[0]
        classes = self.model.classes_
        return {int(cls): float(prob) for cls, prob in zip(classes, proba)}

    def predict_with_confidence(self, feature_vector: pd.DataFrame) -> dict:
        """
        Predict regime with full confidence info.

        Returns
        -------
        dict with keys: regime, regime_name, confidence, probabilities
        """
        probas = self.predict_proba(feature_vector)
        confidence = max(probas.values())
        regime = self.predict(feature_vector)

        names = {REGIME_BEAR: "bear", REGIME_RANGING: "ranging", REGIME_BULL: "bull"}
        return {
            'regime': regime,
            'regime_name': names.get(regime, "unknown"),
            'confidence': round(confidence, 4),
            'probabilities': probas,
            'uncertain': confidence < self.confidence_threshold,
        }

    def save(self, path='quant_env/ml/model.pkl', training_metrics=None):
        """Save model to disk with JSON sidecar."""
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.', exist_ok=True)
        joblib.dump({
            'model': self.model,
            'features': self.features,
            'lookback': self.lookback,
            'threshold': self.threshold,
            'confidence_threshold': self.confidence_threshold,
            'regime_threshold': self.regime_threshold,
            'feature_importances': self._feature_importances,
            'test_accuracy': (training_metrics or {}).get('test_accuracy'),
        }, path)

        json_path = path.replace('.pkl', '_metrics.json')
        sidecar = {
            'lookback': self.lookback,
            'threshold': self.threshold,
            'confidence_threshold': self.confidence_threshold,
            'regime_threshold': self.regime_threshold,
            'features': self.features,
            'feature_importances': {
                k: float(v) for k, v in (self._feature_importances or {}).items()
            },
        }
        if training_metrics:
            sidecar['test_accuracy'] = training_metrics.get('test_accuracy')
            sidecar['per_class_accuracy'] = training_metrics.get('per_class_accuracy')
            sidecar['n_classes'] = training_metrics.get('n_classes')
            sidecar['class_distribution'] = training_metrics.get('class_distribution')
            sidecar['train_samples'] = training_metrics.get('train_samples')
            sidecar['test_samples'] = training_metrics.get('test_samples')
        with open(json_path, 'w') as f:
            json.dump(sidecar, f, indent=2)
        print(f"Model saved to {path}. Metrics saved to {json_path}")

    @classmethod
    def load(cls, path='quant_env/ml/model.pkl'):
        data = joblib.load(path)
        obj = cls(
            lookback=data.get('lookback', 20),
            threshold=data.get('threshold', 25),
            confidence_threshold=data.get('confidence_threshold', 0.4),
            regime_threshold=data.get('regime_threshold', 1.0),
        )
        obj.model = data['model']
        obj.features = data['features']
        obj._feature_importances = data.get('feature_importances', None)
        obj._test_accuracy = data.get('test_accuracy')
        return obj

    def health_check(self) -> dict:
        """Run diagnostics on the loaded model."""
        checks = {}

        checks['model_fitted'] = (
            self.model is not None and hasattr(self.model, 'predict')
        )

        if self._feature_importances:
            nonzero = sum(1 for v in self._feature_importances.values() if v > 0)
            total = len(self._feature_importances)
            checks['nonzero_importances'] = {
                'pass': nonzero > 0,
                'nonzero': nonzero,
                'total': total,
            }
        else:
            checks['nonzero_importances'] = {'pass': False, 'reason': 'no feature importances stored'}

        checks['has_features'] = bool(self.features)

        # Check number of classes
        if self.model is not None and hasattr(self.model, 'classes_'):
            n = len(self.model.classes_)
            checks['n_classes'] = {
                'pass': n >= 2,
                'value': n,
                'message': f'{n} classes' if n >= 2 else f'only {n} class(es)',
            }
        else:
            checks['n_classes'] = {'pass': False, 'reason': 'model not fitted'}

        if self._test_accuracy is not None:
            checks['test_accuracy'] = {
                'pass': self._test_accuracy > 0.35,
                'value': self._test_accuracy,
                'message': f'accuracy={self._test_accuracy:.2%}'
                           if self._test_accuracy > 0.35
                           else 'near random chance for 3-class',
            }
        else:
            checks['test_accuracy'] = {'pass': False, 'reason': 'not stored'}

        healthy = all(
            c['pass'] if isinstance(c, dict) and 'pass' in c else c
            for c in checks.values()
        )
        return {'healthy': healthy, 'checks': checks}

    def _print_training_summary(self, metrics):
        """Pretty-print training metrics."""
        print("=" * 60)
        print("RegimeClassifier (Directional) Training Summary")
        print("=" * 60)
        print(f"  Test accuracy:  {metrics['test_accuracy']:.2%}")
        print(f"  Classes:        {metrics['n_classes']}")
        print(f"  Class dist:     {metrics['class_distribution']}")
        if metrics.get('per_class_accuracy'):
            for cls, acc in metrics['per_class_accuracy'].items():
                label = {-1: 'BEAR', 0: 'RANGING', 1: 'BULL'}.get(cls, cls)
                print(f"    {label:8s} accuracy: {acc:.2%}")
        print(f"  Train samples:  {metrics['train_samples']}")
        print(f"  Test samples:   {metrics['test_samples']}")
        print(f"  Features:       {len(metrics['feature_importances'])}")
        print(f"\n  Top 10 features:")
        sorted_feats = sorted(
            metrics['feature_importances'].items(),
            key=lambda x: x[1], reverse=True
        )[:10]
        for name, imp in sorted_feats:
            print(f"    {name:25s}  {imp:.4f}")
        print("=" * 60)