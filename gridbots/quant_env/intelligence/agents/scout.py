"""
DataScoutAgent — the *Recruiter* replacement.

Recruiter (InsightForge)          -> Quant Data Scout
Human role replaced               -> Data Acquisition Analyst / Market Data Researcher

Primary responsibility: source, validate and log the "participant pool" —
instruments, timeframes, data feeds and alternative data — with coverage and
provenance metadata, exactly as the Recruiter recruits diverse participants
with consent metadata.
"""

import os
import time

from .base import BaseAgent
from ..ledger import Instrument

_QUANT_ENV_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_PROJECT_ROOT = os.path.dirname(_QUANT_ENV_ROOT)

# Candidate participants: instrument universe × timeframes (extensible).
INSTRUMENT_UNIVERSE = [
    {"symbol": "XAUUSD.r", "timeframe": "1m",  "source": "MT5 bridge (raw ticks)"},
    {"symbol": "GC=F",     "timeframe": "1h",  "source": "Yahoo Finance"},
    {"symbol": "SI=F",     "timeframe": "1h",  "source": "Yahoo Finance"},
    {"symbol": "CL=F",     "timeframe": "1h",  "source": "Yahoo Finance"},
]


class DataScoutAgent(BaseAgent):
    KEY = "scout"
    ROLE = "Quant Data Scout"
    REPLACES = "Data Acquisition Analyst / Market Data Researcher"
    PRIMARY_RESPONSIBILITY = (
        "Sources, validates and logs the participant pool: instruments, "
        "timeframes, data feeds and alternative data, with coverage and "
        "provenance metadata."
    )
    INTEGRATIONS = ["Yahoo Finance (GC=F)", "MT5 Bridge (XAUUSD.r)", "ForexFactory calendar"]

    def __init__(self, ctx=None):
        super().__init__(ctx)
        self.project_root = self.ctx.get("project_root") or _DEFAULT_PROJECT_ROOT

    # ── Run ───────────────────────────────────────────────────────────
    def run(self, ledger):
        from strategies.registry import list_strategies
        from ..data import scan_cached_symbols

        strategies = list_strategies() or []
        data_sources = self._scan_data_sources()
        coverage = self._coverage_bars()
        coverage_map = scan_cached_symbols(self.project_root)

        sourced = 0
        for item in INSTRUMENT_UNIVERSE:
            cov = coverage_map.get(item["symbol"], 0)
            if item["symbol"] in ("GC=F", "XAUUSD.r") and not cov:
                cov = coverage  # gold via the legacy gold_data.csv
            instrument = Instrument(
                symbol=item["symbol"], timeframe=item["timeframe"],
                source=item["source"],
                coverage_bars=cov,
                note=f"cached history: {cov} bars" if cov else "no cached history",
            )
            ledger.add_instrument(instrument)
            sourced += 1

        data_health = self._data_health(data_sources, coverage)

        self.log(f"Discovered {len(strategies)} strategies in registry; "
                 f"cached symbols: {sorted(k for k, v in coverage_map.items() if v)}")
        self.log(f"Detected {len(data_sources)} data source artifacts "
                 f"(readiness {data_health['readiness_score']:.0f}/100)")

        return self._report(
            strategies=[{k: meta[k] for k in ("key", "name", "description") if k in meta}
                        for meta in strategies],
            data_sources=data_sources,
            instruments=[i.to_dict() for i in ledger.instruments],
            coverage_bars=coverage,
            cached_symbols=sorted(k for k, v in coverage_map.items() if v),
            sourced=sourced,
            data_health=data_health,
        )

    # ── Internals ─────────────────────────────────────────────────────
    def _data_health(self, data_sources, coverage):
        """Compute a readiness score + flag stale artifacts."""
        stale_names = [s["name"] for s in data_sources if s.get("stale")]
        score = 0.0
        if data_sources:
            fresh = sum(1 for s in data_sources if not s.get("stale"))
            score += 40.0 * (fresh / len(data_sources))
        if coverage >= 1000:
            score += 30.0
        elif coverage >= 100:
            score += 15.0
        # ML artifacts present & fresh -> regime awareness ready
        has_ml = any(s["name"] == "ml_model_metrics" and not s.get("stale")
                     for s in data_sources)
        if has_ml:
            score += 30.0
        return {
            "readiness_score": round(score, 1),
            "stale_sources": stale_names,
            "sources_checked": len(data_sources),
        }

    def _scan_data_sources(self):
        """Probe the engine's artifact directory for available data sources."""
        candidates = [
            ("gold_price_history", os.path.join(self.project_root, "gold_data.csv")),
            ("optimization_grid", os.path.join(self.project_root, "optimization_results.csv")),
            ("walkforward_report", os.path.join(self.project_root, "walkforward_report.csv")),
            ("strategy_results", os.path.join(_QUANT_ENV_ROOT, "strategy_results.json")),
            ("ml_model_metrics", os.path.join(_QUANT_ENV_ROOT, "ml", "model_metrics.json")),
            ("trades_db", os.path.join(_QUANT_ENV_ROOT, "trades.db")),
        ]
        found = []
        for name, path in candidates:
            if os.path.exists(path):
                size = os.path.getsize(path)
                age_days = round((time.time() - os.path.getmtime(path)) / 86400.0, 1)
                found.append({
                    "name": name, "path": path, "bytes": size,
                    "age_days": age_days,
                    "stale": age_days > self.ctx.get("stale_artifact_days", 7.0),
                })
        return found

    def _coverage_bars(self):
        path = os.path.join(self.project_root, "gold_data.csv")
        if not os.path.exists(path):
            return 0
        try:
            with open(path) as f:
                return sum(1 for _ in f) - 1  # minus header
        except Exception:
            return 0
