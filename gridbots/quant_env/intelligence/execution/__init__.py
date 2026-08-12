"""Execution package — turning research + consensus into safe trades.

Advisor    — combines market view + strategy evidence + Kronos into a
             concrete trade recommendation with a full reason chain.
shadow     — forward-testing a deployment in simulation before it goes live.
live_apply — hot-applies approved params to a running strategy and enforces
             kill-switches (regime flip / consensus collapse / drawdown).
"""

from .advisor import TradeExecutionAdvisor, TradeRecommendation
from .shadow import ShadowForwardTester
from . import live_apply

__all__ = [
    "TradeExecutionAdvisor",
    "TradeRecommendation",
    "ShadowForwardTester",
    "live_apply",
]

