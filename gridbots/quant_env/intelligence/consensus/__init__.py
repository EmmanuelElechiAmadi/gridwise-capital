"""Consensus package — evidence unification for the agent team.

Every intelligence source (Kronos forecast, RF regime model, backtest/walk-
forward probes, LLM structured verdict) casts a typed vote; the ConsensusEngine
fuses them into a single MarketView with attribution — the "why" behind the
common conclusion on market direction.
"""

from .signals import Signal, clip01
from .market_view import MarketView
from .engine import ConsensusEngine, DEFAULT_SOURCE_WEIGHTS
from . import sources

__all__ = [
    "Signal",
    "MarketView",
    "ConsensusEngine",
    "DEFAULT_SOURCE_WEIGHTS",
    "sources",
]

