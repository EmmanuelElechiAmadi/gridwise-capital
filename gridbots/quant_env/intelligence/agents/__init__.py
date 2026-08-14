"""Agent team — each agent replaces a named quant professional role."""

from .base import BaseAgent
from .scout import DataScoutAgent
from .prober import MarketProberAgent
from .analyst import QuantAnalystAgent
from .strategist import QuantStrategistAgent
from .news_analyst import NewsResearchAnalystAgent

TEAM = [DataScoutAgent, MarketProberAgent, QuantAnalystAgent, QuantStrategistAgent,
        NewsResearchAnalystAgent]
