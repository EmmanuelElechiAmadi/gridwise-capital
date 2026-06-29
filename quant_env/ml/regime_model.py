import os
import json
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split, cross_val_score
import joblib

class RegimeClassifier:
    def __init__(self, lookback=20, threshold=25):
        self.lookback = lookback
        self.threshold = threshold
        self.model = None
        self.features = []
        self._feature_importances = None
        self._cv_scores = None

    def train(self, df, n_jobs=-1):
        """
        Train the regime classifier on historical OHLCV data.

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV data with columns: open, high, low, close, volume.
        n_jobs : int
            Number of parallel jobs for cross-validation.

        Returns
        -------
        dict
            Training metrics including accuracy, cross-val scores, and feature importance.
        """
        from .data_builder import build_features
        X, y = build_features(df, self.lookback, self.threshold)

        if len(X) < 50:
            raise ValueError(f"Not enough samples ({len(X)}) to train. Need at least 50.")

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, shuffle=False  # Don't shuffle time series
        )

        self.model = RandomForestClassifier(
            n_estimators=100,
            max_depth=5,
            min_samples_leaf=10,       # prevent overfitting on noisy bars
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

        # Cross-validation (5-fold, time-series aware: use shuffled CV since data is already sorted)
        self._cv_scores = cross_val_score(
            self.model, X, y, cv=5, scoring='accuracy'
        )

        test_acc = self.model.score(X_test, y_test)
        metrics = {
            'test_accuracy': round(test_acc, 4),
            'cv_mean': round(self._cv_scores.mean(), 4),
            'cv_std': round(self._cv_scores.std(), 4),
            'cv_scores': [round(s, 4) for s in self._cv_scores],
            'train_samples': len(X_train),
            'test_samples': len(X_test),
            'feature_importances': self._feature_importances,
        }

        self._print_training_summary(metrics)
        return metrics

    def save(self, path='quant_env/ml/model.pkl'):
        """Save model to disk. Also writes a JSON sidecar with metrics."""
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.', exist_ok=True)
        joblib.dump({
            'model': self.model,
            'features': self.features,
            'lookback': self.lookback,
            'threshold': self.threshold,
            'feature_importances': self._feature_importances,
        }, path)

        # Sidecar JSON with training metrics for easy inspection
        json_path = path.replace('.pkl', '_metrics.json')
        with open(json_path, 'w') as f:
            json.dump({
                'lookback': self.lookback,
                'threshold': self.threshold,
                'features': self.features,
                'feature_importances': self._feature_importances,
            }, f, indent=2)
        print(f"Model saved to {path}. Metrics saved to {json_path}")

    @classmethod
    def load(cls, path='quant_env/ml/model.pkl'):
        data = joblib.load(path)
        obj = cls(data['lookback'], data['threshold'])
        obj.model = data['model']
        obj.features = data['features']
        obj._feature_importances = data.get('feature_importances', None)
        return obj

    # ── Private helpers ────────────────────────────────────────────

    def _print_training_summary(self, metrics):
        """Pretty-print training metrics."""
        print("=" * 50)
        print("RegimeClassifier Training Summary")
        print("=" * 50)
        print(f"  Test accuracy:  {metrics['test_accuracy']:.2%}")
        print(f"  CV accuracy:    {metrics['cv_mean']:.2%} ± {metrics['cv_std']:.2%}")
        print(f"  CV scores:      {', '.join(f'{s:.2%}' for s in metrics['cv_scores'])}")
        print(f"  Train samples:  {metrics['train_samples']}")
        print(f"  Test samples:   {metrics['test_samples']}")
        print(f"  Features:       {len(metrics['feature_importances'])}")
        print(f"\n  Top 5 features:")
        sorted_feats = sorted(
            metrics['feature_importances'].items(),
            key=lambda x: x[1], reverse=True
        )[:5]
        for name, imp in sorted_feats:
            print(f"    {name:20s}  {imp:.4f}")
        print("=" * 50)
