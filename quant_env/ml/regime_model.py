import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
import joblib

class RegimeClassifier:
    def __init__(self, lookback=20, threshold=25):
        self.lookback = lookback
        self.threshold = threshold
        self.model = None

    def train(self, df):
        from .data_builder import build_features
        X, y = build_features(df, self.lookback, self.threshold)
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
        self.model = RandomForestClassifier(n_estimators=100, max_depth=5)
        self.model.fit(X_train, y_train)
        self.features = X.columns.tolist()
        print(f"Regime model accuracy: {self.model.score(X_test,y_test):.2f}")

    def save(self, path='quant_env/ml/model.pkl'):
        joblib.dump({'model':self.model,'features':self.features,'lookback':self.lookback,'threshold':self.threshold}, path)

    @classmethod
    def load(cls, path='quant_env/ml/model.pkl'):
        data = joblib.load(path)
        obj = cls(data['lookback'], data['threshold'])
        obj.model = data['model']; obj.features = data['features']
        return obj
