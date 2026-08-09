"""
Portfolio optimization module.

Classes
-------
KellyPortfolio
    Standard Kelly-based allocation across strategies using historical PnL.

KronosPortfolioOptimizer
    Extends KellyPortfolio to incorporate Kronos per-symbol forecasts
    (volatility, trend, regime) for dynamic risk-weighted allocation.

Usage::
    optimizer = KronosPortfolioOptimizer(strategies=["GC=F","SI=F"])
    optimizer.update_kronos_inputs({
        "GC=F": {"volatility": 0.02, "trend": 0.01, "regime": "BULL", "confidence": 0.8},
        "SI=F": {"volatility": 0.03, "trend": -0.005, "regime": "BEAR", "confidence": 0.6},
    })
    allocs = optimizer.compute_allocations(total_equity=100000)
"""

import numpy as np
from collections import deque
from typing import Dict, List, Optional


class KellyPortfolio:
    """
    Standard Kelly-based portfolio allocation using historical trade PnL.

    Parameters
    ----------
    strategies : list of str
        Strategy/symbol names.
    window : int
        Rolling window for PnL history.
    max_total_risk : float
        Maximum fraction of equity to risk across all strategies (0..1).
    """

    def __init__(self, strategies, window=30, max_total_risk=0.1):
        self.strategies = strategies
        self.trade_logs = {s: deque(maxlen=window) for s in strategies}
        self.max_total_risk = max_total_risk

    def add_trade(self, strategy, pnl):
        self.trade_logs[strategy].append(pnl)

    def compute_allocations(self, total_equity):
        kellys = {}
        for s in self.strategies:
            trades = list(self.trade_logs[s])
            if len(trades) < 5:
                kellys[s] = 0
                continue
            wins = [t for t in trades if t > 0]
            losses = [t for t in trades if t <= 0]
            if not losses:
                k = min(0.2, len(wins) / len(trades) * 0.5)
            else:
                wr = len(wins) / len(trades)
                r = (
                    np.mean(wins) / abs(np.mean(losses))
                    if abs(np.mean(losses)) != 0
                    else 0
                )
                k = wr - (1 - wr) / r if r != 0 else 0
            kellys[s] = max(0, min(k, 0.25))
        total_k = sum(kellys.values())
        if total_k == 0:
            return {s: 0 for s in self.strategies}
        return {
            s: (kellys[s] / total_k) * self.max_total_risk * total_equity
            for s in self.strategies
        }


class KronosPortfolioOptimizer(KellyPortfolio):
    """
    Portfolio optimizer that blends Kelly-based allocation with
    Kronos per-symbol forecasts for dynamic risk-weighting.

    The Kronos forecasts (volatility, trend, regime confidence) are used
    to tilt allocations away from high-volatility / bearish symbols and
    toward low-volatility / bullish symbols.

    Parameters
    ----------
    strategies : list of str
        Strategy/symbol names.
    window : int
        Rolling window for PnL history.
    max_total_risk : float
        Maximum fraction of equity to risk (0..1).
    kronos_weight : float
        Blend weight for Kronos forecast (0 = pure Kelly, 1 = pure Kronos).
    """

    def __init__(
        self,
        strategies: List[str] = None,
        window: int = 30,
        max_total_risk: float = 0.1,
        kronos_weight: float = 0.4,
        # Alternative constructor: adapter-based (used by main.py)
        adapter=None,
        symbols=None,
        config=None,
        logger=None,
    ):
        """
        Parameters
        ----------
        strategies : list of str, optional
            Strategy/symbol names. If not given, extracted from 'symbols'.
        window : int
            Rolling window for PnL history.
        max_total_risk : float
            Maximum fraction of equity to risk (0..1).
        kronos_weight : float
            Blend weight for Kronos forecast (0 = pure Kelly, 1 = pure Kronos).
        adapter : KronosRegimeAdapter, optional
            Used to auto-populate strategies from the adapter's symbol list
            and to enable automatic forecast updates.
        symbols : list of str, optional
            Symbol names (alternative to strategies).
        config : object, optional
            QuantEnv config (reads KRONOS_PORTFOLIO_WEIGHT, PORTFOLIO_MAX_RISK).
        logger : object, optional
            Logger instance.
        """
        # Resolve strategy list
        if strategies:
            pass  # use as-is
        elif symbols:
            strategies = symbols
        else:
            strategies = getattr(config, "KRONOS_SYMBOLS", []) if config else []
            if isinstance(strategies, str):
                strategies = [s.strip() for s in strategies.split(",") if s.strip()]
        strategies = list(strategies) if strategies else []

        # Read config overrides
        if config is not None:
            kronos_weight = float(
                getattr(config, "KRONOS_PORTFOLIO_WEIGHT", kronos_weight)
            )
            max_total_risk = float(
                getattr(config, "PORTFOLIO_MAX_RISK", max_total_risk)
            )

        super().__init__(strategies, window=window, max_total_risk=max_total_risk)
        self._kronos_inputs: Dict[str, dict] = {}
        self._kronos_weight = kronos_weight
        self._adapter = adapter
        self._auto_update = adapter is not None
        self._logger = logger

    def update_from_adapter(self, adapter=None):
        """
        Auto-update Kronos inputs from the adapter's per-symbol forecasts.

        Parameters
        ----------
        adapter : KronosRegimeAdapter, optional
            If not given, uses the adapter passed at construction time.
        """
        ad = adapter or self._adapter
        if ad is None:
            return
        if hasattr(ad, "get_portfolio_inputs"):
            self.update_kronos_inputs(ad.get_portfolio_inputs())

    def update_kronos_inputs(self, inputs: Dict[str, dict]):
        """
        Update the per-symbol Kronos forecast inputs.

        Parameters
        ----------
        inputs : dict of {symbol: dict}
            Each value dict should have keys:
                'volatility'  : float (forecast volatility)
                'trend'       : float (forecast trend)
                'regime'      : str   ('BULL'/'BEAR'/'RANGING')
                'confidence'  : float (trend strength)
        """
        self._kronos_inputs = inputs

    def compute_allocations(self, total_equity: float) -> Dict[str, float]:
        """
        Compute allocations blending Kelly PnL-based allocation with
        Kronos forecast-based risk weighting.

        Returns
        -------
        dict of {strategy_name: allocation_in_currency}
        """
        # Base Kelly allocations
        kelly_allocs = super().compute_allocations(total_equity)

        if not self._kronos_inputs or self._kronos_weight <= 0:
            return kelly_allocs

        # Compute Kronos risk scores for each strategy
        kronos_scores = {}
        for s in self.strategies:
            ki = self._kronos_inputs.get(s, {})
            if not ki:
                kronos_scores[s] = 0.5
                continue

            vol = ki.get("volatility", 0.01)
            trend = ki.get("trend", 0.0)
            regime = ki.get("regime", "RANGING")
            confidence = ki.get("confidence", 0.0)

            # Score: higher is better (more allocation)
            # - Lower volatility -> higher score
            # - Bullish + confidence -> higher score
            # - Bearish -> lower score
            vol_score = 1.0 / (1.0 + vol * 100)  # 0..1; vol=0.01 -> 0.5, vol=0.05 -> 0.17

            if regime == "BULL":
                regime_score = 0.5 + confidence * 0.5  # 0.5..1.0
            elif regime == "BEAR":
                regime_score = 0.5 - confidence * 0.5  # 0.0..0.5
            else:
                regime_score = 0.5

            # Trend contribution: normalize to 0..1
            trend_score = 0.5 + np.clip(trend * 5, -0.5, 0.5)

            kronos_scores[s] = (vol_score * 0.3 + regime_score * 0.4 + trend_score * 0.3)

        # Normalize Kronos scores to sum to 1
        total_k_score = sum(kronos_scores.values())
        if total_k_score > 0:
            for s in kronos_scores:
                kronos_scores[s] /= total_k_score

        # Blend Kelly allocations with Kronos scores
        kw = self._kronos_weight
        blended = {}
        kelly_total = max(1.0, sum(kelly_allocs.values()))
        for s in self.strategies:
            kelly_frac = kelly_allocs.get(s, 0) / kelly_total
            kronos_frac = kronos_scores.get(s, 0)
            blended_frac = (1.0 - kw) * kelly_frac + kw * kronos_frac
            blended[s] = blended_frac * self.max_total_risk * total_equity

        return blended
