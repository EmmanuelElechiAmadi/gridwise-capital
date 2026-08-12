"""
InsightForge for Quant — an autonomous multi-agent quantitative research team.

This package operationalises the InsightForge research framework
(continuous discovery via a persistent agent team) inside the Seek Quant
engine. Every agent is an explicit *replacement for a named quant
professional role*:

    Recruiter   -> Quant Data Scout        (sources instruments & data feeds)
    Interviewer -> Market Prober           (interviews the market via backtests)
    Analyst     -> Quant Research Analyst  (synthesizes alpha themes)
    Strategist  -> Quant Strategist        (prioritizes + specs strategies)
    Coordinator -> Chief Quant Officer     (orchestrates the research loop)

The agents share a persistent ``OpportunityLedger`` (the "opportunity
solution tree") and a cycle produces a ``research_brief.json`` for humans.
"""

import os
import sys

# ── Ensure quant_env root is importable so this package can reuse the
# ── existing engine modules (backtest.*, analysis.*, strategies.*, ml.*)
# ── exactly the same way the rest of the repo does. ────────────────────
_QUANT_ENV_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _QUANT_ENV_ROOT not in sys.path:
    sys.path.insert(0, _QUANT_ENV_ROOT)

__version__ = "3.0.0"
