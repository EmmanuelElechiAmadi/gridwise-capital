"""
Tests for the InsightForge-for-Quant agent team (intelligence package).

Covers the shared ledger, the confidence/qRICE math, each quant professional
replacement agent, and the full Coordinator research cycle.
"""

import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from intelligence.ledger import (  # noqa: E402
    Opportunity, OpportunityLedger, Insight, Probe, Instrument,
)
from intelligence.agents.analyst import signal_confidence, QuantAnalystAgent  # noqa: E402
from intelligence.agents.prober import MarketProberAgent  # noqa: E402
from intelligence.agents.scout import DataScoutAgent  # noqa: E402
from intelligence.agents.strategist import QuantStrategistAgent  # noqa: E402
from intelligence.agents.news_analyst import NewsResearchAnalystAgent  # noqa: E402
from intelligence.coordinator import CoordinatorAgent  # noqa: E402
from intelligence.llm import LLMClient, LLMNarrator, fact_check_news_verdict  # noqa: E402
from intelligence.scheduler import ResearchScheduler  # noqa: E402
from intelligence.deploy import DeploymentManager  # noqa: E402
from intelligence import llm as llm_mod  # noqa: E402
from intelligence import data as data_mod  # noqa: E402
from intelligence import news as news_mod  # noqa: E402
from intelligence.news import (  # noqa: E402
    Article, sample_news, dedupe_articles, rank_articles, fetch_news,
)
from intelligence.consensus.sources import (  # noqa: E402
    collect_news, compute_news_confirmation,
)


# ── Helpers ───────────────────────────────────────────────────────────

def _make_synthetic_history(length=400, csv_path=None):
    """Build synthetic gold-style OHLCV, optionally written as gold_data.csv."""
    np.random.seed(42)
    close = 2000.0 + np.cumsum(np.random.randn(length) * 0.5)
    high = close + np.abs(np.random.randn(length) * 0.3)
    low = close - np.abs(np.random.randn(length) * 0.3)
    open_ = close + np.random.randn(length) * 0.1
    volume = np.random.randint(100, 10000, length)
    idx = pd.date_range("2025-01-01", periods=length, freq="min")
    df = pd.DataFrame({
        "Open": open_, "High": high, "Low": low,
        "Close": close, "Volume": volume,
    }, index=idx)
    if csv_path:
        df.to_csv(csv_path)
    return df


def _make_project_root(tmp_path):
    """Populate a pytest tmp_path with a synthetic gold_data.csv."""
    _make_synthetic_history(csv_path=str(tmp_path / "gold_data.csv"))
    return str(tmp_path)


# Metrics that clear every hard deployment quality gate (Phase 0).
_GOOD_METRICS = {
    "num_trades": 60,
    "sharpe_ratio": 1.2,
    "total_return_pct": 3.5,
    "max_drawdown_pct": 8.0,
    "oos_consistency": 0.8,
    "monte_carlo": {"mc_prob_profit_pct": 78.0},
}


def _good_opportunity(title="Top Grid", key="grid_strategy", source="q",
                      params=None):
    """An Opportunity whose metrics pass the hard quality gates."""
    return Opportunity(title, key, source, params or {"spacing": 0.1,
                                                      "levels": 3, "lot": 0.01},
                       metrics=dict(_GOOD_METRICS),
                       reach=0.8, impact=0.5, confidence=0.6, effort_hours=6)


# ── Ledger ────────────────────────────────────────────────────────────

class TestLedger:
    def test_roundtrip_serialization(self, tmp_path):
        path = os.path.join(str(tmp_path), "ledger.json")
        ledger = OpportunityLedger(path=path)
        ledger.add_instrument(Instrument("GC=F", "1h", "Yahoo", 1000))
        ledger.add_probe(Probe("grid_strategy", metrics={"num_trades": 3,
                                                         "sharpe_ratio": 0.5}))
        ledger.add_insight(Insight("Grid Alpha", "theme", confidence=0.42))
        ledger.add_opportunity(Opportunity("op", "grid_strategy", "QuantStrategist"))
        ledger.save()
        loaded = OpportunityLedger.load(path)
        assert len(loaded.instruments) == 1
        assert len(loaded.probes) == 1
        assert len(loaded.insights) == 1
        assert len(loaded.opportunities) == 1
        assert loaded.instruments[0].symbol == "GC=F"

    def test_probe_has_trades(self):
        assert Probe("x", metrics={"num_trades": 0}).has_trades is False
        assert Probe("x", metrics={"num_trades": 5}).has_trades is True

    def test_opportunity_qrice_ordering(self):
        high = Opportunity("a", "s", "q", reach=1.0, impact=1.0,
                           confidence=1.0, effort_hours=5)
        low = Opportunity("b", "s", "q", reach=0.1, impact=0.1,
                          confidence=0.1, effort_hours=50)
        assert high.qrice() > low.qrice()
        mid = Opportunity("c", "s", "q", reach=1.0, impact=1.0,
                          confidence=1.0, effort_hours=20)
        assert high.qrice() > mid.qrice()


# ── Math ──────────────────────────────────────────────────────────────

class TestConfidence:
    def test_no_evidence_scores_low(self):
        assert signal_confidence(num_trades=0, sharpe=-1.0,
                                 oos_consistency=0.0) == 0.0

    def test_strong_evidence_scores_high(self):
        strong = signal_confidence(num_trades=100, sharpe=2.5,
                                   oos_consistency=1.0)
        assert strong > 0.8

    def test_overfit_penalty_reduces(self):
        base = signal_confidence(num_trades=50, sharpe=1.5,
                                 oos_consistency=0.8, is_sharpe=2.0,
                                 oos_sharpe=1.5)
        penalized = signal_confidence(num_trades=50, sharpe=1.5,
                                      oos_consistency=0.8, is_sharpe=5.0,
                                      oos_sharpe=0.5)
        assert penalized < base

    def test_returns_clipped_range(self):
        for kwargs in [
            {"num_trades": 10, "sharpe": 0.5, "oos_consistency": 0.5},
            {"num_trades": 500, "sharpe": 10.0, "oos_consistency": 1.0},
            {"num_trades": 0, "sharpe": -5.0, "oos_consistency": 0.0},
        ]:
            assert 0.0 <= signal_confidence(**kwargs) <= 1.0


# ── Agents ────────────────────────────────────────────────────────────

class TestScout:
    def test_discovers_strategies_and_instruments(self, tmp_path):
        project_root = _make_project_root(tmp_path)
        ctx = {"project_root": project_root}
        ledger = OpportunityLedger(path=os.path.join(project_root, "ledger.json"))
        report = DataScoutAgent(ctx).run(ledger)
        assert report["sourced"] >= 3
        assert len(report["strategies"]) >= 1
        assert len(ledger.instruments) >= 3
        assert report["coverage_bars"] == 400   # rows in synthetic csv


class TestProber:
    def test_probes_synthetic_market(self, tmp_path):
        project_root = _make_project_root(tmp_path)
        ctx = {"project_root": project_root, "max_bars": 400, "probe_limit": 1}
        ledger = OpportunityLedger(path=os.path.join(project_root, "ledger.json"))
        report = MarketProberAgent(ctx).run(ledger)
        assert report["data_loaded"] is True
        assert report["bars"] == 400
        assert report["probed"] >= 2            # grid + breakout
        assert len(ledger.probes) >= 2
        for probe in ledger.probes:
            assert probe.strategy_key in ("grid_strategy", "breakout_strategy")
            assert probe.regime in ("bull", "bear", "ranging", "mixed", "unknown")


class TestAnalyst:
    def test_synthesizes_themes(self, tmp_path):
        project_root = _make_project_root(tmp_path)
        ctx = {"project_root": project_root}
        ledger = OpportunityLedger(path=os.path.join(project_root, "ledger.json"))
        ledger.add_probe(Probe("grid_strategy", params={"spacing": 0.1},
                               metrics={"num_trades": 12, "sharpe_ratio": 1.1,
                                        "total_return_pct": 2.5,
                                        "max_drawdown_pct": 4.0},
                               data_bars=400, regime="ranging"))
        report = QuantAnalystAgent(ctx).run(ledger)
        assert len(report["themes"]) >= 1
        for theme in report["themes"]:
            assert 0.0 <= theme["confidence"] <= 1.0
        assert any(i.strategy_keys == ["grid_strategy"] for i in ledger.insights)


class TestStrategist:
    def test_prioritizes_and_drafts_specs(self, tmp_path):
        project_root = _make_project_root(tmp_path)
        ctx = {"project_root": project_root, "top_n": 2}
        ledger = OpportunityLedger(path=os.path.join(project_root, "ledger.json"))
        ledger.add_insight(Insight(
            "Grid Alpha", "theme", confidence=0.6,
            strategy_keys=["grid_strategy"]))
        ledger.add_insight(Insight(
            "Breakout Alpha", "theme", confidence=0.4,
            strategy_keys=["breakout_strategy"]))
        ledger.add_probe(Probe("grid_strategy", params={"spacing": 0.1},
                               metrics={"num_trades": 20, "sharpe_ratio": 1.8,
                                        "total_return_pct": 4.0,
                                        "max_drawdown_pct": 3.0},
                               data_bars=800, regime="bull"))
        ledger.add_probe(Probe("breakout_strategy",
                               metrics={"num_trades": 8, "sharpe_ratio": 0.6,
                                        "total_return_pct": 1.0,
                                        "max_drawdown_pct": 6.0},
                               data_bars=800, regime="mixed"))
        report = QuantStrategistAgent(ctx).run(ledger)
        assert len(report["opportunities"]) == 2
        ranked = report["opportunities"]
        scores = [o["qrice"] for o in ranked]
        assert scores == sorted(scores, reverse=True)
        assert len(report["specs"]) == 2
        assert "risk_gates" in report["specs"][0]
        assert any(o["status"] == "prioritized" for o in ranked)


# ── Coordinator ───────────────────────────────────────────────────────

class TestCoordinator:
    def test_full_cycle_produces_brief(self, tmp_path):
        # No gold_data.csv -> prober uses the fast artifact fallback path.
        project_root = str(tmp_path)
        ctx = {
            "project_root": project_root,
            "max_bars": 300,
            "probe_limit": 1,
            "top_n": 2,
            "ledger_path": os.path.join(project_root, "ledger.json"),
        }
        coordinator = CoordinatorAgent(ctx)
        brief, ledger = coordinator.run_cycle()

        assert brief["framework"] == "InsightForge for Quant v2.0"
        keys = {m["key"] for m in brief["team"]}
        assert keys == {"scout", "prober", "analyst", "strategist", "news"}
        for member in brief["team"]:
            assert member["replaces"]          # every agent names the human role
            assert member["role"]              # every agent names the quant title
        assert brief["probe_count"] >= 2
        assert brief["instrument_count"] >= 3
        assert "top_opportunities" in brief
        assert os.path.exists(os.path.join(project_root, "ledger.json"))

    def test_brief_json_serializable(self, tmp_path):
        project_root = str(tmp_path)
        ctx = {"project_root": project_root, "max_bars": 300,
               "probe_limit": 1, "top_n": 1,
               "ledger_path": os.path.join(project_root, "ledger.json")}
        coordinator = CoordinatorAgent(ctx)
        brief, _ = coordinator.run_cycle()
        dumped = json.dumps(brief, default=str)   # must not raise
        assert "cycle_id" in json.loads(dumped)


# ── LLM narrative layer ───────────────────────────────────────────────

class _FakeLLMClient:
    """Canned client used to test the narrative layer without a network."""

    available = True
    provider = "openai"
    fast_model = "fake-fast-model"
    capable_model = "fake-capable-model"
    news_model = "fake-news-model"

    def __init__(self, text="FAKE-NARRATIVE"):
        self._text = text
        self.calls = []

    def status(self):
        return {"provider": self.provider, "available": self.available,
                "fast_model": self.fast_model, "capable_model": self.capable_model,
                "news_model": self.news_model}

    def complete(self, system, user, model=None, max_tokens=None, temperature=0.4):
        self.calls.append((system, user, model))
        return self._text


class TestLLMLayer:
    def test_client_unavailable_without_key(self, monkeypatch):
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        client = LLMClient({})
        assert client.available is False
        assert client.complete("s", "u") is None

    def test_provider_aware_defaults(self, monkeypatch):
        # Simulate an Anthropic key in the environment (as in gridbots/.env).
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("LLM_API_KEY", "sk-ant-test")
        monkeypatch.delenv("LLM_FAST_MODEL", raising=False)
        monkeypatch.delenv("LLM_CAPABLE_MODEL", raising=False)
        client = LLMClient({})
        assert client.available is True
        assert client.provider == "anthropic"
        assert client.fast_model == "claude-haiku-4-5"       # fast/summarization tier
        assert client.capable_model == "claude-opus-5"       # deep-synthesis tier
        assert client.fast_chain[0] == "claude-haiku-4-5"
        assert "claude-opus-4-8" in client.capable_chain     # graceful fallback
        assert "claude-sonnet-5" in client.capable_chain     # graceful fallback

    def test_complete_falls_back_through_chain(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("LLM_API_KEY", "sk-ant-test")
        client = LLMClient({})
        attempts = []

        def fake_post(payload, headers):
            attempts.append(payload["model"])
            if payload["model"] == "claude-haiku-4-5":
                raise RuntimeError("model not found")       # primary fails
            return {"content": [{"type": "text", "text": "OK-FALLBACK"}]}

        client._post = fake_post
        out = client.complete("s", "u", model=client.fast_model)
        assert out == "OK-FALLBACK"
        assert attempts == ["claude-haiku-4-5", "claude-haiku-4-5-20251001"]

    def test_auto_pick_models(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("LLM_API_KEY", "sk-ant-test")
        client = LLMClient({})
        models = ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-4-8",
                  "claude-opus-5", "claude-3-5-haiku-latest"]
        assert client._pick_auto_model(models, "capable") == "claude-opus-5"
        assert client._pick_auto_model(models, "fast") == "claude-haiku-4-5"
        ordered = client._auto_models(models, "capable")
        assert ordered == ["claude-opus-5", "claude-opus-4-8",
                           "claude-sonnet-5", "claude-haiku-4-5",
                           "claude-3-5-haiku-latest"]

    def test_complete_auto_discovers_on_failure(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("LLM_API_KEY", "sk-ant-test")
        # Clear model overrides so the configured capable model is the code
        # default (claude-opus-5) and the whole chain genuinely fails first
        # (the real gridbots/.env sets claude-opus-4-6, which would succeed
        # in the chain before auto-discovery ever runs).
        monkeypatch.delenv("LLM_CAPABLE_MODEL", raising=False)
        monkeypatch.delenv("LLM_FAST_MODEL", raising=False)
        client = LLMClient({})
        assert client.capable_model == "claude-opus-5"
        # The configured chain (opus-5/4-8/sonnet-5/3-5) all fail; the
        # discovered opus-4-6 succeeds via auto-discovery.
        def fake_once(s, u, m, mt, t):
            if m == "claude-opus-4-6":
                client._last_model = m      # real _complete_once records this
                return "AUTO-OK"
            return None

        client._complete_once = fake_once
        client.refresh_models = lambda: ["claude-opus-4-6", "claude-sonnet-5"]
        out = client.complete("s", "u", model=client.capable_model)
        assert out == "AUTO-OK"
        assert client._auto_cache.get("capable") == ["claude-opus-4-6", "claude-sonnet-5"]
        assert client._last_model == "claude-opus-4-6"   # the model that answered

    def test_narrator_deterministic_fallback(self, monkeypatch):
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        narrator = LLMNarrator({})   # no key, llm disabled
        assert narrator.active is False
        summary = narrator.executive_summary({"cycle_id": "abc", "probe_count": 3,
                                              "instrument_count": 2, "themes": [],
                                              "top_opportunities": []})
        assert summary.startswith("Cycle abc ran 3 probes")

    def test_narrator_uses_llm_when_active(self):
        fake = _FakeLLMClient(text="THE-LM-NARRATIVE")
        narrator = LLMNarrator({"llm_enabled": True}, client=fake)
        assert narrator.active is True
        out = narrator.executive_summary({"cycle_id": "abc", "probe_count": 1,
                                          "instrument_count": 1, "themes": [],
                                          "top_opportunities": []})
        assert out == "THE-LM-NARRATIVE"
        theme = narrator.narrate_theme({"title": "T", "theme": "fb", "confidence": 0.5})
        assert theme == "THE-LM-NARRATIVE"
        opp = narrator.narrate_opportunity({"strategy_key": "grid_strategy", "qrice": 0.1},
                                           {"title": "spec title"})
        assert opp == "THE-LM-NARRATIVE"
        # The capable model must be used for deep synthesis, fast for summaries.
        models = [c[2] for c in fake.calls]
        assert fake.fast_model in models
        assert fake.capable_model in models


class TestNarrativeInCoordinator:
    def test_brief_has_narrative_and_layer(self, tmp_path):
        project_root = str(tmp_path)
        ctx = {"project_root": project_root, "max_bars": 300,
               "probe_limit": 1, "top_n": 1,
               "ledger_path": os.path.join(project_root, "ledger.json")}
        coordinator = CoordinatorAgent(ctx)
        brief, _ = coordinator.run_cycle()
        assert "narrative" in brief
        assert brief["narrative"]
        layer = brief["narrative_layer"]
        assert layer["enabled"] is False
        assert "available" in layer

    def test_brief_contains_consensus_market_view(self, tmp_path):
        project_root = _make_project_root(tmp_path)
        ctx = {"project_root": project_root, "max_bars": 300,
               "probe_limit": 1, "top_n": 1,
               "ledger_path": os.path.join(project_root, "ledger.json")}
        coordinator = CoordinatorAgent(ctx)
        brief, ledger = coordinator.run_cycle()
        mv = brief.get("market_view")
        assert mv is not None
        assert mv["direction"] in ("BULL", "BEAR", "RANGING")
        assert isinstance(mv["agreement_index"], (int, float))
        # The market view is persisted in the ledger too.
        assert len(ledger.market_views) >= 1
        # Attribution chain exists for the sources that voted.
        assert isinstance(mv.get("contributions"), list)

    def test_brief_uses_llm_when_injected(self, tmp_path):
        fake = _FakeLLMClient(text="CQO-COMMENTARY")
        narrator = LLMNarrator({"llm_enabled": True}, client=fake)
        project_root = str(tmp_path)
        ctx = {"project_root": project_root, "max_bars": 300,
               "probe_limit": 1, "top_n": 1,
               "ledger_path": os.path.join(project_root, "ledger.json")}
        coordinator = CoordinatorAgent(ctx, narrator=narrator)
        brief, _ = coordinator.run_cycle()
        assert brief["narrative"] == "CQO-COMMENTARY"
        for theme in brief.get("themes", []):
            assert "narrative" in theme


# ── Continuous loop scheduler ─────────────────────────────────────────

class TestScheduler:
    def test_run_cycle_now_produces_brief(self, tmp_path):
        project_root = str(tmp_path)
        scheduler = ResearchScheduler(ctx={"max_bars": 300, "probe_limit": 1,
                                           "top_n": 1,
                                           "ledger_path": os.path.join(project_root, "l.json")})
        brief = scheduler.run_cycle_now()
        assert brief is not None
        assert "cycle_id" in brief
        assert scheduler.cycles_run == 1

    def test_start_stop_lifecycle(self, tmp_path):
        scheduler = ResearchScheduler(ctx={"max_bars": 300, "probe_limit": 1,
                                           "top_n": 1,
                                           "ledger_path": os.path.join(str(tmp_path), "l.json")})
        scheduler.start()
        assert scheduler.running is True
        scheduler.stop()
        assert scheduler.running is False

    def test_singleton_guard(self, tmp_path):
        first = ResearchScheduler.get_instance(ctx={"max_bars": 300})
        second = ResearchScheduler.get_instance(ctx={"max_bars": 300})
        assert first is second
        # Reset for isolation from other tests in this run.
        ResearchScheduler._instance = None


# ── Deeper per-agent capabilities ─────────────────────────────────────

class TestScoutHealth:
    def test_reports_data_health(self, tmp_path):
        project_root = _make_project_root(tmp_path)   # fresh gold_data.csv
        ctx = {"project_root": project_root}
        ledger = OpportunityLedger(path=os.path.join(project_root, "ledger.json"))
        report = DataScoutAgent(ctx).run(ledger)
        health = report["data_health"]
        assert "readiness_score" in health
        assert 0.0 <= health["readiness_score"] <= 100.0
        assert health["sources_checked"] >= 1
        # A just-written csv must not be stale.
        assert "gold_price_history" not in health["stale_sources"]


class TestProberOOS:
    def test_oos_followup_probe(self, tmp_path):
        # 900 bars with max_bars 400 -> disjoint IS/OOS windows available.
        _make_synthetic_history(length=900, csv_path=str(tmp_path / "gold_data.csv"))
        project_root = str(tmp_path)
        ctx = {"project_root": project_root, "max_bars": 400, "probe_limit": 1,
               "validate_oos": True}
        ledger = OpportunityLedger(path=os.path.join(project_root, "ledger.json"))
        prober = MarketProberAgent(ctx)
        data = prober._load_data()
        assert data is not None and len(data) == 400
        from strategies.grid_strategy import GridStrategy
        probe = prober._run_oos_probe("grid_strategy", GridStrategy,
                                      {"spacing": 0.1, "levels": 3, "lot": 0.01})
        assert probe is not None
        assert probe.oos is True
        assert "out-of-sample" in probe.note


class TestAnalystDeeper:
    def test_ml_theme(self):
        agent = QuantAnalystAgent({})
        ml = {"accuracy": 0.62, "top_features": ["volatility", "rsi"]}
        theme = agent._ml_theme(ml)
        assert theme is not None
        assert theme.title == "Regime Model Insight"
        assert "volatility" in theme.theme
        assert theme.risk_flags == []

        weak = agent._ml_theme({"accuracy": 0.4, "top_features": ["volatility"]})
        assert "ml-accuracy-below-60" in weak.risk_flags
        assert agent._ml_theme({}) is None

    def test_oos_degradation_flag(self, tmp_path):
        project_root = _make_project_root(tmp_path)
        ctx = {"project_root": project_root}
        ledger = OpportunityLedger(path=os.path.join(project_root, "ledger.json"))
        ledger.add_probe(Probe("grid_strategy", params={"spacing": 0.1},
                               metrics={"num_trades": 20, "sharpe_ratio": 1.8,
                                        "total_return_pct": 4.0,
                                        "max_drawdown_pct": 3.0},
                               data_bars=800, regime="bull"))
        ledger.add_probe(Probe("grid_strategy", params={"spacing": 0.1},
                               metrics={"num_trades": 10, "sharpe_ratio": -0.6,
                                        "total_return_pct": -2.0,
                                        "max_drawdown_pct": 8.0},
                               oos=True, data_bars=800, regime="bear",
                               note="out-of-sample validation"))
        report = QuantAnalystAgent(ctx).run(ledger)
        grid_theme = next(t for t in report["themes"]
                          if "grid_strategy" in (t.get("strategy_keys") or []))
        assert "oos-degradation" in grid_theme["risk_flags"]


class TestStrategistDeeper:
    def test_spec_has_allocation_and_mc(self, tmp_path):
        project_root = _make_project_root(tmp_path)
        ctx = {"project_root": project_root, "top_n": 1}
        ledger = OpportunityLedger(path=os.path.join(project_root, "ledger.json"))
        ledger.add_insight(Insight("Grid Alpha", "theme", confidence=0.8,
                                   strategy_keys=["grid_strategy"]))
        ledger.add_probe(Probe("grid_strategy", params={"spacing": 0.1},
                               metrics={"num_trades": 20, "sharpe_ratio": 1.8,
                                        "total_return_pct": 4.0,
                                        "max_drawdown_pct": 3.0,
                                        "monte_carlo": {"mc_prob_profit_pct": 92.0,
                                                        "mc_var_95_pct": -3.1,
                                                        "mc_median_max_dd_pct": 5.5}},
                               data_bars=800, regime="bull"))
        report = QuantStrategistAgent(ctx).run(ledger)
        spec = report["specs"][0]
        assert spec["suggested_allocation_pct"] > 0
        assert spec["suggested_allocation_pct"] <= 20.0
        assert "monte_carlo" in spec and "MC:" in spec["monte_carlo"]
        assert "diversification_note" in spec
        assert any("portfolio cap" in g for g in spec["risk_gates"])


# ── Human-gated deployment (wire top opportunity back into the engine) ─

class TestDeployment:
    def test_propose_approve_apply(self, tmp_path):
        path = os.path.join(str(tmp_path), "deployments.json")
        dm = DeploymentManager(path=path)
        opp = _good_opportunity()
        rec = dm.propose(opp, note="test")
        assert rec["status"] == "proposed"
        assert dm.pending()[0]["id"] == rec["id"]
        # Not applied until a human approves.
        assert dm.approved_for("grid_strategy") is None

        approved = dm.approve(rec["id"], approved_by="qa")
        assert approved["status"] == "approved"
        assert dm.approved_for("grid_strategy")["id"] == rec["id"]

        class FakeStrategy:
            pass

        s = FakeStrategy()
        s.spacing = 1.0
        s.levels = 1
        applied = DeploymentManager.apply_to_strategy(s, approved)
        assert "spacing" in applied and "levels" in applied
        assert s.spacing == 0.1 and s.levels == 3

        dm.reject(rec["id"])
        assert dm.list()[-1]["status"] == "rejected"

    def test_auto_approve_after_n_cycles(self, tmp_path):
        dm = DeploymentManager(path=os.path.join(str(tmp_path), "deployments.json"))
        opp = _good_opportunity()
        r1 = dm.consider_auto_approve(opp, required_cycles=3)
        assert r1["status"] == "proposed" and r1["consistent_cycles"] == 1
        r2 = dm.consider_auto_approve(opp, required_cycles=3)
        assert r2["status"] == "proposed" and r2["consistent_cycles"] == 2
        r3 = dm.consider_auto_approve(opp, required_cycles=3)
        assert r3["status"] == "approved"
        assert r3["approved_by"].startswith("auto:")
        # A single record was bumped, not re-proposed.
        assert len(dm.list()) == 1

    def test_auto_approve_resets_on_change(self, tmp_path):
        dm = DeploymentManager(path=os.path.join(str(tmp_path), "deployments.json"))
        opp_a = _good_opportunity(params={"spacing": 0.1, "levels": 3, "lot": 0.01})
        opp_b = _good_opportunity(params={"spacing": 0.2, "levels": 5, "lot": 0.01})
        dm.consider_auto_approve(opp_a, required_cycles=3)
        dm.consider_auto_approve(opp_b, required_cycles=3)
        records = dm.list()
        assert records[-1]["consistent_cycles"] == 1      # fresh start for B
        assert records[0]["status"] == "superseded"        # A no longer active

    def test_apply_breakout_params(self, tmp_path):
        dm = DeploymentManager(path=os.path.join(str(tmp_path), "deployments.json"))
        deployment = {
            "id": "brk", "strategy_key": "breakout_strategy",
            "params": {"lookback_4h_bars": 8, "breakout_threshold_pct": 0.05,
                       "confirmation_bars_1h": 2, "lot": 0.02,
                       "tp_dollars": "3,5,10", "sl_dollars": 2.5,
                       "kronos_enabled": False},
        }

        class FakeBreakout:
            lookback_4h = 5
            breakout_threshold = 0.0005
            confirmation_bars = 2
            lot = 0.01
            tp_dollars = [3.0, 5.0, 10.0]
            sl_dollars = 3.0
            _kronos_enabled = False

        s = FakeBreakout()
        applied = DeploymentManager.apply_to_strategy(s, deployment)
        assert "lookback_4h_bars" in applied
        assert "breakout_threshold_pct" in applied
        assert "tp_dollars" in applied
        assert s.lookback_4h == 8
        assert abs(s.breakout_threshold - 0.0005) < 1e-9   # pct stored /100
        assert s.tp_dollars == [3.0, 5.0, 10.0]            # string -> float list
        assert s.sl_dollars == 2.5
        # kronos_enabled: false is a research-scope no-op — it must not
        # force-disable a config-driven Kronos switch.
        assert s._kronos_enabled is False

    def test_apply_breakout_kronos_flag(self, tmp_path):
        # kronos_enabled=True must flip the flag AND attempt to attach the
        # enhancer — not just set a dead boolean (fails safely without torch).
        deployment = {
            "id": "brk2", "strategy_key": "breakout_strategy",
            "params": {"kronos_enabled": True, "lot": 0.02},
        }

        class FakeBreakout:
            lot = 0.01
            _kronos_enabled = False
            _kronos = None
            config = None
            log = None

        s = FakeBreakout()
        applied = DeploymentManager.apply_to_strategy(s, deployment)
        assert "kronos_enabled" in applied
        assert s._kronos_enabled is True
        assert "lot" in applied and s.lot == 0.02
        # In this test env the enhancer may not import (no torch) — that's fine:
        # the flag is set and _kronos is left None rather than raising.
        assert hasattr(s, "_kronos")

    def test_apply_breakout_kronos_false_keeps_config(self, tmp_path):
        # A deployment saying kronos_enabled:false must leave a config-driven
        # True untouched (deployment can opt in, not force off).
        deployment = {
            "id": "brk3", "strategy_key": "breakout_strategy",
            "params": {"kronos_enabled": False, "lot": 0.02},
        }

        class FakeBreakoutConfigOn:
            lot = 0.01
            _kronos_enabled = True       # enabled via KRONOS_BREAKOUT_ENABLED
            _kronos = object()           # enhancer attached at construction

        s = FakeBreakoutConfigOn()
        applied = DeploymentManager.apply_to_strategy(s, deployment)
        assert "kronos_enabled" not in applied          # no-op
        assert s._kronos_enabled is True                # config switch preserved
        assert s._kronos is not None                    # enhancer preserved
        assert s.lot == 0.02

    def test_persistence(self, tmp_path):
        path = os.path.join(str(tmp_path), "deployments.json")
        dm = DeploymentManager(path=path)
        dm.propose(_good_opportunity(), note="x")
        reloaded = DeploymentManager(path=path)
        assert len(reloaded.list()) == 1


class TestDeploymentQualityGates:
    """Phase 0 — a human cannot approve a study with no statistical edge."""

    def test_bad_metrics_are_blocked(self, tmp_path):
        path = os.path.join(str(tmp_path), "deployments.json")
        dm = DeploymentManager(path=path)
        bad = Opportunity("Bad", "grid_strategy", "q",
                          params={"spacing": 0.1},
                          metrics={"num_trades": 5, "sharpe_ratio": -0.5,
                                   "max_drawdown_pct": 2.5})
        rec = dm.propose(bad, note="legacy-style approval")
        assert rec["status"] == "blocked_by_gates"
        assert "min_trades" in rec["quality"]["failed"]
        assert "min_sharpe" in rec["quality"]["failed"]
        # Approve without force -> stays blocked.
        ret = dm.approve(rec["id"], approved_by="human")
        assert ret["status"] == "blocked_by_gates"
        assert dm.approved_for("grid_strategy") is None
        # Force-approve -> auditable override.
        forced = dm.approve(rec["id"], approved_by="human", force=True)
        assert forced["status"] == "approved"
        assert forced["approved_by"].endswith(":FORCE")
        assert dm.approved_for("grid_strategy")["id"] == rec["id"]

    def test_legacy_approved_bad_record_held(self, tmp_path):
        path = os.path.join(str(tmp_path), "deployments.json")
        dm = DeploymentManager(path=path)
        bad = Opportunity("LegacyBad", "grid_strategy", "q",
                          params={"spacing": 0.1},
                          metrics={"num_trades": 5, "sharpe_ratio": -0.5})
        # Write a pre-gate "approved" record directly (as the shipped data had).
        rec = dm.propose(bad, note="pre-gate")
        rec["status"] = "approved"
        rec["approved_by"] = "human"
        dm.save()
        # approved_for() must NOT return it — it fails the gates now.
        assert dm.approved_for("grid_strategy") is None

    def test_auto_approve_never_bypasses_gates(self, tmp_path):
        path = os.path.join(str(tmp_path), "deployments.json")
        dm = DeploymentManager(path=path)
        bad = Opportunity("Bad", "grid_strategy", "q",
                          params={"spacing": 0.1},
                          metrics={"num_trades": 5, "sharpe_ratio": -0.5})
        for _ in range(5):
            rec = dm.consider_auto_approve(bad, required_cycles=2)
        assert rec["status"] == "blocked_by_gates"
        assert dm.approved_for("grid_strategy") is None

    def test_pbo_gate_is_optional_but_enforced_when_measured(self, tmp_path):
        from intelligence.deploy import evaluate_quality, DEPLOY_MAX_PBO
        # No PBO metric on the record -> gate not enforced, not blocking.
        rec = {"qrice": 0.05, "metrics": {"num_trades": 50,
                                             "sharpe_ratio": 1.2,
                                             "max_drawdown_pct": 8.0}}
        q = evaluate_quality(rec)
        pbo_gate = next(g for g in q["gates"] if g["gate"] == "max_pbo")
        assert pbo_gate["enforced"] is False
        assert pbo_gate["passed"] is True
        assert "pbo" in q["missing_metrics"]
        assert "max_pbo" not in q["failed"]
        # With a PBO metric above the threshold -> enforced and blocking.
        rec2 = {"qrice": 0.05, "metrics": {"num_trades": 50,
                                              "sharpe_ratio": 1.2,
                                              "max_drawdown_pct": 8.0,
                                              "pbo": DEPLOY_MAX_PBO + 0.2}}
        q2 = evaluate_quality(rec2)
        pbo2 = next(g for g in q2["gates"] if g["gate"] == "max_pbo")
        assert pbo2["enforced"] is True
        assert pbo2["passed"] is False
        assert "max_pbo" in q2["failed"]
        # A passing PBO clears the gate.
        rec3 = {"qrice": 0.05, "metrics": {"num_trades": 50,
                                              "sharpe_ratio": 1.2,
                                              "max_drawdown_pct": 8.0,
                                              "pbo": 0.1}}
        q3 = evaluate_quality(rec3)
        pbo3 = next(g for g in q3["gates"] if g["gate"] == "max_pbo")
        assert pbo3["passed"] is True and pbo3["enforced"] is True
        assert "max_pbo" not in q3["failed"]


class TestCoordinatorAutoDeploy:
    def test_auto_propose_top(self, tmp_path):
        project_root = str(tmp_path)
        deploy_path = os.path.join(project_root, "deployments.json")
        ctx = {"project_root": project_root, "max_bars": 300, "probe_limit": 1,
               "top_n": 1, "ledger_path": os.path.join(project_root, "ledger.json"),
               "auto_deploy_top": True, "deploy_path": deploy_path}
        coordinator = CoordinatorAgent(ctx)
        brief, _ = coordinator.run_cycle()
        assert brief.get("deployment") is not None
        # Synthetic-data backtests may or may not clear the quality gates —
        # the important contract is the wiring (proposed OR held by gates).
        assert brief["deployment"]["status"] in ("proposed", "blocked_by_gates")
        assert brief["deployment"]["strategy_key"] == \
            brief["top_opportunities"][0]["strategy_key"]
        dm = DeploymentManager(path=deploy_path)
        assert len(dm.pending()) + len(dm.blocked()) == 1
        # The brief opportunity itself is marked as proposed.
        assert brief["top_opportunities"][0]["status"] in ("proposed", "blocked_by_gates")


# ── Multi-symbol corpus ───────────────────────────────────────────────

class TestDataHelpers:
    def test_scan_and_load(self, tmp_path):
        _make_synthetic_history(length=400, csv_path=str(tmp_path / "gold_data.csv"))
        _make_synthetic_history(length=300, csv_path=str(tmp_path / "SIF.csv"))
        root = str(tmp_path)
        cov = data_mod.scan_cached_symbols(root)
        assert cov.get("GC=F") == 400
        assert cov.get("SI=F") == 300
        df = data_mod.load_cached_history(root, "SI=F", max_bars=100)
        assert df is not None and len(df) == 100
        assert data_mod.load_cached_history(root, "CL=F") is None

    def test_ensure_fresh_corpus_refreshes_stale_and_skips_fresh(self, tmp_path, monkeypatch):
        # A stale gold_data.csv gets re-downloaded; a fresh one is skipped.
        csv = tmp_path / "gold_data.csv"
        _make_synthetic_history(length=50, csv_path=str(csv))
        old = time.time() - 48 * 3600  # 48h old -> stale
        os.utime(csv, (old, old))
        root = str(tmp_path)

        fake_df = _make_synthetic_history(length=200)
        captured = []

        class _FakeYF:
            def download(self, sym, **kwargs):
                captured.append(sym)
                return fake_df

        monkeypatch.setitem(sys.modules, "yfinance", _FakeYF())
        res = data_mod.ensure_fresh_corpus(root, max_age_hours=6.0)
        assert "GC=F" in captured
        assert res["refreshed"]
        assert data_mod.load_cached_history(root, "GC=F") is not None

        # Second call: corpus is now fresh -> skipped, no download.
        captured.clear()
        res2 = data_mod.ensure_fresh_corpus(root, max_age_hours=6.0)
        assert "GC=F" in str(res2["skipped"]) and not captured

    def test_ensure_fresh_corpus_fails_safe_offline(self, tmp_path, monkeypatch):
        root = str(tmp_path)

        def boom(*a, **k):
            raise RuntimeError("offline")

        monkeypatch.setattr("yfinance.download", boom)
        res = data_mod.ensure_fresh_corpus(root, max_age_hours=6.0)
        assert isinstance(res, dict) and "skipped" in res


class TestProberMultiSymbol:
    def test_loads_and_tags_symbols(self, tmp_path):
        _make_synthetic_history(length=500, csv_path=str(tmp_path / "gold_data.csv"))
        _make_synthetic_history(length=400, csv_path=str(tmp_path / "SIF.csv"))
        project_root = str(tmp_path)
        ctx = {"project_root": project_root, "max_bars": 200, "probe_limit": 1}
        prober = MarketProberAgent(ctx)
        gold = prober._load_data_for("GC=F")
        silver = prober._load_data_for("SI=F")
        assert gold is not None and len(gold) == 200
        assert silver is not None and len(silver) == 200
        from strategies.grid_strategy import GridStrategy
        probe = prober._run_backtest("grid_strategy", GridStrategy, silver,
                                     {"spacing": 0.1, "levels": 3}, symbol="SI=F")
        assert probe.symbol == "SI=F"

    def test_run_probes_multi_symbol(self, tmp_path):
        _make_synthetic_history(length=400, csv_path=str(tmp_path / "gold_data.csv"))
        _make_synthetic_history(length=300, csv_path=str(tmp_path / "SIF.csv"))
        project_root = str(tmp_path)
        ctx = {"project_root": project_root, "max_bars": 150, "probe_limit": 1,
               "validate_oos": False, "symbols": "GC=F,SI=F"}
        ledger = OpportunityLedger(path=os.path.join(project_root, "ledger.json"))
        report = MarketProberAgent(ctx).run(ledger)
        assert "GC=F" in report["symbols"]
        assert "SI=F" in report["symbols"]
        assert any(p.symbol == "SI=F" for p in ledger.probes)


class TestScoutMultiSymbol:
    def test_reports_cached_symbols(self, tmp_path):
        _make_synthetic_history(length=400, csv_path=str(tmp_path / "gold_data.csv"))
        _make_synthetic_history(length=300, csv_path=str(tmp_path / "SIF.csv"))
        project_root = str(tmp_path)
        ctx = {"project_root": project_root}
        ledger = OpportunityLedger(path=os.path.join(project_root, "ledger.json"))
        report = DataScoutAgent(ctx).run(ledger)
        assert "SI=F" in report["cached_symbols"]
        silver = next(i for i in report["instruments"] if i["symbol"] == "SI=F")
        assert silver["coverage_bars"] == 300


# ── Prompt tuning ─────────────────────────────────────────────────────

class TestPromptsCalibrated:
    def test_prompts_contain_calibration(self):
        p = llm_mod._PROMPTS
        assert "never invent statistics" in p["executive_summary"]
        assert "human approval" in p["executive_summary"]
        assert "not yet investable" in p["theme"]
        assert "human approval" in p["opportunity"]
        # Summaries should be the most deterministic narration.
        assert llm_mod._PROMPT_TEMPERATURES["executive_summary"] < \
            llm_mod._PROMPT_TEMPERATURES["theme"]


# ── Correlation-aware theming ──────────────────────────────────────────

class TestCorrelationTheming:
    def _write_correlated_corpus(self, tmp_path):
        """GC=F and SI=F closes that move nearly in lockstep."""
        np.random.seed(7)
        n = 500
        idx = pd.date_range("2025-01-01", periods=n, freq="min")
        g = 2000 + np.cumsum(np.random.randn(n) * 0.5)
        s = g * 1.0 + np.random.randn(n) * 0.05
        for fname, close in (("gold_data.csv", g), ("SIF.csv", s)):
            df = pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1,
                               "Close": close, "Volume": 1000}, index=idx)
            df.to_csv(str(tmp_path / fname))
        return str(tmp_path)

    def test_correlation_theme(self, tmp_path):
        root = self._write_correlated_corpus(tmp_path)
        agent = QuantAnalystAgent({"project_root": root, "symbols": "GC=F,SI=F"})
        corr = agent._load_correlations()
        assert len(corr["pairs"]) == 1
        theme = agent._correlation_theme(corr)
        assert theme is not None
        assert theme.title == "Cross-Symbol Correlation Insight"
        assert theme.confidence > 0.7                    # near-identical returns
        assert "high-correlation-cluster" in theme.risk_flags

    def test_correlation_theme_in_run(self, tmp_path):
        root = self._write_correlated_corpus(tmp_path)
        ctx = {"project_root": root, "symbols": "GC=F,SI=F"}
        ledger = OpportunityLedger(path=os.path.join(root, "ledger.json"))
        report = QuantAnalystAgent(ctx).run(ledger)
        assert any(t["title"] == "Cross-Symbol Correlation Insight"
                   for t in report["themes"])


# ── Auto-approve integration ──────────────────────────────────────────

class TestCoordinatorAutoApprove:
    def test_first_cycle_proposes_with_consistency(self, tmp_path):
        project_root = str(tmp_path)
        deploy_path = os.path.join(project_root, "deployments.json")
        ctx = {"project_root": project_root, "max_bars": 300, "probe_limit": 1,
               "top_n": 1, "ledger_path": os.path.join(project_root, "ledger.json"),
               "auto_deploy_top": True, "auto_approve_cycles": 3,
               "deploy_path": deploy_path}
        coordinator = CoordinatorAgent(ctx)
        brief, _ = coordinator.run_cycle()
        dep = brief.get("deployment")
        assert dep is not None
        # Synthetic backtests may not clear the quality gates; the contract is
        # that the cycle wired the auto-approval path (1st of >=2 consistent).
        assert dep["status"] in ("proposed", "blocked_by_gates")
        assert dep.get("consistent_cycles", 1) >= 1
        dm = DeploymentManager(path=deploy_path)
        assert len(dm.pending()) + len(dm.blocked()) == 1


# ── Consensus engine (Phase 1) ─────────────────────────────────────────

class TestConsensus:
    def test_no_signals_is_ranging_with_insufficient_evidence(self):
        from intelligence.consensus import ConsensusEngine
        view = ConsensusEngine().fuse([])
        assert view.direction == "RANGING"
        assert view.consensus_strength == 0.0
        assert any("insufficient evidence" in str(d.get("message"))
                   for d in view.disagreements)

    def test_strong_bull_consensus(self):
        from intelligence.consensus import ConsensusEngine
        from intelligence.consensus.signals import Signal
        signals = [
            Signal("kronos", "BULL", strength=1.0, confidence=0.9),
            Signal("rf_regime", "BULL", strength=0.8, confidence=0.8),
            Signal("backtest", "BULL", strength=0.6, confidence=0.7),
        ]
        view = ConsensusEngine().fuse(signals)
        assert view.direction == "BULL"
        assert view.agreement_index == 1.0
        assert view.consensus_strength > 0.5
        assert view.disagreements == []
        # Attribution chain includes each source with its contribution.
        assert {c["source"] for c in view.contributions} == \
            {"kronos", "rf_regime", "backtest"}

    def test_disagreement_is_listed(self):
        from intelligence.consensus import ConsensusEngine
        from intelligence.consensus.signals import Signal
        signals = [
            Signal("kronos", "BULL", strength=1.0, confidence=0.9),
            Signal("backtest", "BEAR", strength=0.9, confidence=0.9),
        ]
        view = ConsensusEngine().fuse(signals)
        # The BEAR voice must be visible as a dissent when it doesn't win.
        dissent = {d["source"] for d in view.disagreements}
        assert "backtest" in dissent or view.direction == "BEAR"

    def test_ledger_roundtrip_market_views(self, tmp_path):
        from intelligence.consensus import ConsensusEngine
        from intelligence.consensus.signals import Signal
        from intelligence.ledger import OpportunityLedger
        path = os.path.join(str(tmp_path), "ledger.json")
        ledger = OpportunityLedger(path=path)
        view = ConsensusEngine().fuse([Signal("kronos", "BULL", 0.5, 0.5)])
        ledger.add_market_view(view)
        ledger.save()
        loaded = OpportunityLedger.load(path)
        assert len(loaded.market_views) == 1
        assert loaded.market_views[0]["direction"] == "BULL"

    def test_signal_adapters(self):
        from intelligence.consensus.signals import Signal
        # Kronos adapter uses regime_label + trend_strength + vol.
        k = Signal.from_kronos({"regime_label": "BULL", "trend_strength": 1.2,
                                "volatility_forecast": 0.02})
        assert k is not None and k.direction == "BULL"
        assert 0.0 < k.strength <= 1.0
        # Backtest adapter crushes tiny samples and honors OOS.
        thin = Signal.from_backtest("grid_strategy",
                                    {"num_trades": 2, "sharpe_ratio": 3.0})
        thick = Signal.from_backtest("grid_strategy",
                                     {"num_trades": 80, "sharpe_ratio": 1.5,
                                      "oos_consistency": 0.8,
                                      "monte_carlo": {"mc_prob_profit_pct": 70}})
        assert thin.strength < thick.strength
        # Trend filter + llm adapters.
        assert Signal.from_trend_filter("bull", 0.6).direction == "BULL"
        llm = Signal.from_llm_verdict({"direction": "BEAR", "confidence": 0.7})
        assert llm is not None and llm.direction == "BEAR"

    def test_llm_fact_check(self):
        from intelligence import llm as llm_mod
        bundle = {"kronos": {"trend_strength": 1.2, "vol": 0.02}}
        good = llm_mod.fact_check_verdict(
            {"direction": "BULL", "evidence_cited": ["trend_strength 1.2"]}, bundle)
        assert good["passed"] is True
        bad = llm_mod.fact_check_verdict(
            {"direction": "BULL", "evidence_cited": ["trend_strength 9.9"]}, bundle)
        assert bad["passed"] is False
        assert len(bad["failed_citations"]) == 1

    def test_source_correlation_penalty_effective_n(self):
        """v4 #18 — correlated brains cannot double-count in agreement."""
        from intelligence.consensus import ConsensusEngine
        from intelligence.consensus.signals import Signal
        # backtest + trend_filter are correlated (both derived from the same
        # bars); kronos is an independent brain.
        signals = [
            Signal("kronos", "BULL", strength=0.8, confidence=0.8),
            Signal("backtest", "BULL", strength=0.8, confidence=0.8),
            Signal("trend_filter", "BULL", strength=0.8, confidence=0.8),
        ]
        view = ConsensusEngine().fuse(signals)
        # All three agree, so the (uncorrected) agreement is 1.0 — but the
        # independence-corrected agreement and effective sample size reflect
        # the redundancy: effective_n < 3 and diversity_penalty < 1.
        assert view.raw_agreement_index == 1.0
        assert view.effective_n is not None and view.effective_n < 3.0
        assert 0.0 < view.diversity_penalty < 1.0
        assert view.max_vif >= 1.0
        # Per-source VIFs are recorded on the attribution chain.
        for c in view.contributions:
            assert c["vif"] >= 1.0
            assert c["independent_weight"] <= c["base_weight"]

    def test_correlation_penalty_does_not_change_nominal_votes(self):
        """The correction affects agreement/strength, not the direction."""
        from intelligence.consensus import ConsensusEngine
        from intelligence.consensus.signals import Signal
        signals = [
            Signal("kronos", "BULL", strength=1.0, confidence=0.9),
            Signal("rf_regime", "BULL", strength=0.8, confidence=0.8),
            Signal("backtest", "BULL", strength=0.6, confidence=0.7),
        ]
        adj = ConsensusEngine(diversity_adjust=True).fuse(signals)
        raw = ConsensusEngine(diversity_adjust=False).fuse(signals)
        assert adj.direction == raw.direction == "BULL"
        assert adj.raw_agreement_index == raw.agreement_index == 1.0
        # Corrected agreement never exceeds the nominal one.
        assert adj.agreement_index <= raw.agreement_index + 1e-9
        assert adj.consensus_strength <= raw.consensus_strength + 1e-9

    def test_correlation_penalty_differentiates_correlated_vs_independent(self):
        from intelligence.consensus import ConsensusEngine
        from intelligence.consensus.signals import Signal
        # Panel A: independent brains (kronos + llm).
        a = ConsensusEngine().fuse([
            Signal("kronos", "BULL", 0.8, 0.8),
            Signal("llm", "BULL", 0.8, 0.8),
        ])
        # Panel B: the same two votes, but one is a redundant bar-derived vote.
        b = ConsensusEngine().fuse([
            Signal("backtest", "BULL", 0.8, 0.8),
            Signal("trend_filter", "BULL", 0.8, 0.8),
        ])
        assert a.diversity_penalty > b.diversity_penalty
        assert a.effective_n > b.effective_n

    def test_market_view_roundtrips_v4_fields(self, tmp_path):
        from intelligence.consensus import ConsensusEngine
        from intelligence.consensus.signals import Signal
        from intelligence.ledger import OpportunityLedger
        path = os.path.join(str(tmp_path), "ledger.json")
        ledger = OpportunityLedger(path=path)
        view = ConsensusEngine().fuse([Signal("kronos", "BULL", 0.5, 0.5)])
        ledger.add_market_view(view)
        ledger.save()
        loaded = OpportunityLedger.load(path)
        mv = loaded.market_views[0]
        assert "effective_n" in mv and "max_vif" in mv
        assert "diversity_penalty" in mv and "raw_agreement_index" in mv


# ── Trade advisor + shadow + kill-switch (Phase 3) ─────────────────────

class TestExecutionAdvisor:
    def test_hold_when_consensus_weak(self):
        from intelligence.execution import TradeExecutionAdvisor
        from intelligence.consensus import MarketView
        mv = MarketView(direction="BULL", direction_value=0.1,
                        strength=0.1, agreement_index=0.5,
                        consensus_strength=0.05)
        rec = TradeExecutionAdvisor().advise(mv, price=2000.0)
        assert rec.action == "hold"
        assert rec.side is None
        assert any("consensus" in s["detail"] for s in rec.reason_chain)

    def test_trade_when_consensus_strong(self):
        from intelligence.execution import TradeExecutionAdvisor
        from intelligence.consensus import MarketView
        mv = MarketView(direction="BULL", direction_value=0.6,
                        strength=0.6, agreement_index=0.9,
                        consensus_strength=0.54)
        rec = TradeExecutionAdvisor().advise(mv, price=2000.0)
        assert rec.action == "trade"
        assert rec.side == "buy"
        assert rec.suggested_lot > 0
        assert any("decision" in s["step"] for s in rec.reason_chain)

    def test_bad_deployment_blocks_trade(self):
        from intelligence.execution import TradeExecutionAdvisor
        from intelligence.consensus import MarketView
        bad_dep = {
            "strategy_key": "grid_strategy",
            "metrics": {"num_trades": 5, "sharpe_ratio": -0.5},
            "qrice": 0.02,
        }
        mv = MarketView(direction="BULL", direction_value=0.6,
                        strength=0.6, agreement_index=0.9,
                        consensus_strength=0.54)
        rec = TradeExecutionAdvisor().advise(mv, deployment=bad_dep, price=2000.0)
        assert rec.action == "hold"
        assert any(not g["passed"] for g in rec.gates)


class TestShadowForwardTester:
    def test_insufficient_data(self, tmp_path):
        from intelligence.execution import ShadowForwardTester
        import pandas as pd
        tester = ShadowForwardTester(path=os.path.join(str(tmp_path), "sh.json"))
        dep = {"id": "x", "strategy_key": "grid_strategy",
               "params": {"spacing": 0.1, "levels": 3}}
        report = tester.test(dep, pd.DataFrame(), forward_window=50)
        assert report["status"] == "insufficient_data"


class TestKillSwitches:
    def test_drawdown_trigger(self):
        from intelligence.execution.live_apply import evaluate_kill_switches
        flatten, reasons = evaluate_kill_switches(current_drawdown_pct=16.0)
        assert flatten is True
        assert any("drawdown" in r for r in reasons)

    def test_consensus_collapse_trigger(self):
        from intelligence.execution.live_apply import evaluate_kill_switches
        from intelligence.consensus import MarketView
        mv = MarketView(direction="BULL", strength=0.2, agreement_index=0.3,
                        consensus_strength=0.06)
        flatten, reasons = evaluate_kill_switches(market_view=mv)
        assert flatten is True
        assert any("consensus" in r for r in reasons)

    def test_regime_flip_trigger(self):
        from intelligence.execution.live_apply import evaluate_kill_switches
        from intelligence.consensus import MarketView
        mv = MarketView(direction="BEAR", strength=0.5, agreement_index=0.8,
                        consensus_strength=0.4)
        flatten, reasons = evaluate_kill_switches(market_view=mv,
                                                  deployed_direction="BULL")
        assert flatten is True
        assert any("flip" in r for r in reasons)

    def test_no_trigger_when_healthy(self):
        from intelligence.execution.live_apply import evaluate_kill_switches
        from intelligence.consensus import MarketView
        mv = MarketView(direction="BULL", strength=0.5, agreement_index=0.8,
                        consensus_strength=0.4)
        flatten, reasons = evaluate_kill_switches(
            market_view=mv, current_drawdown_pct=3.0,
            deployed_direction="BULL")
        assert flatten is False
        assert reasons == []

    def test_kill_drill_replays_history_without_broker(self):
        from intelligence.execution.live_apply import run_kill_drill
        from intelligence.consensus import MarketView
        # Three healthy snapshots then one consensus collapse.
        views = [
            MarketView(direction="BULL", strength=0.5, agreement_index=0.8,
                       consensus_strength=0.4).to_dict(),
            MarketView(direction="BULL", strength=0.5, agreement_index=0.8,
                       consensus_strength=0.4).to_dict(),
            MarketView(direction="BULL", strength=0.5, agreement_index=0.8,
                       consensus_strength=0.4).to_dict(),
            MarketView(direction="BULL", strength=0.1, agreement_index=0.2,
                       consensus_strength=0.05).to_dict(),
        ]
        drill = run_kill_drill(views, horizon=12)
        assert drill["drill"] is True
        assert drill["simulated_steps"] == 4
        assert drill["fired_steps"] == 1
        assert drill["first_fired_index"] == 3
        assert drill["reason_histogram"]
        assert drill["config"]["max_drawdown_pct"] > 0
        # Every step carries the direction + strength the guard would see.
        assert all("direction" in s and "kill_triggered" in s
                   for s in drill["steps"])

    def test_kill_drill_empty_history(self):
        from intelligence.execution.live_apply import run_kill_drill
        drill = run_kill_drill([], horizon=5)
        assert drill["simulated_steps"] == 0
        assert drill["fired_steps"] == 0
        assert drill["fired_fraction"] == 0.0

    def test_kill_drill_drawdown_condition(self):
        from intelligence.execution.live_apply import run_kill_drill
        from intelligence.consensus import MarketView
        healthy = MarketView(direction="BULL", strength=0.5,
                             agreement_index=0.8,
                             consensus_strength=0.4).to_dict()
        drill = run_kill_drill([healthy], current_drawdown_pct=30.0)
        assert drill["fired_steps"] == 1
        assert any("drawdown" in r for r in drill["steps"][0]["reasons"])

    def test_kill_drill_matrix_sensitivity(self):
        """v4 advanced: the what-if grid shows fired counts per threshold pair."""
        from intelligence.execution.live_apply import run_kill_drill_matrix
        from intelligence.consensus import MarketView
        views = [
            MarketView(direction="BULL", strength=0.5, agreement_index=0.8,
                       consensus_strength=0.4).to_dict(),
            MarketView(direction="BULL", strength=0.1, agreement_index=0.2,
                       consensus_strength=0.04).to_dict(),   # weak -> collapse
        ]
        m = run_kill_drill_matrix(views, dd_grid=(5, 20),
                                  floor_grid=(0.05, 0.5), horizon=12)
        assert m["drill_matrix"] is True
        assert len(m["rows"]) == 2 and len(m["rows"][0]["cells"]) == 2
        # Stricter floor (0.5) fires at least as often as a lax floor (0.05).
        strict = m["rows"][0]["cells"][1]["fired"]
        lax = m["rows"][0]["cells"][0]["fired"]
        assert strict >= lax
        # The weak view trips the consensus-collapse kill under both floors.
        assert m["rows"][0]["cells"][0]["fired"] >= 1

    def test_kill_drill_matrix_empty_history(self):
        from intelligence.execution.live_apply import run_kill_drill_matrix
        m = run_kill_drill_matrix([], horizon=6)
        assert m["horizon"] == 0
        assert all(cell["fired"] == 0
                   for row in m["rows"] for cell in row["cells"])

    def test_kill_drill_scenario_overrides(self):
        """v4 advanced: what-if thresholds without touching the live guard."""
        from intelligence.execution.live_apply import run_kill_drill, evaluate_kill_switches
        from intelligence.consensus import MarketView
        # A 5% drawdown with the default 15% threshold is safe...
        flatten, reasons = evaluate_kill_switches(current_drawdown_pct=5.0)
        assert flatten is False
        # ...but under a stricter scenario it fires.
        flatten2, reasons2 = evaluate_kill_switches(
            current_drawdown_pct=5.0,
            overrides={"max_drawdown_pct": 4.0})
        assert flatten2 is True
        assert any("drawdown" in r for r in reasons2)
        # A consensus floor override makes a borderline view kill.
        mv = MarketView(direction="BULL", strength=0.4, agreement_index=0.5,
                        consensus_strength=0.2).to_dict()
        loose = run_kill_drill([mv], overrides={"consensus_floor": 0.05})
        strict = run_kill_drill([mv], overrides={"consensus_floor": 0.5})
        assert loose["fired_steps"] == 0
        assert strict["fired_steps"] == 1
        # The drill reports the *effective* (overridden) config.
        assert strict["config"]["consensus_floor"] == 0.5
        assert strict["config"]["max_drawdown_pct"] == 15.0


class TestLiveApplyPersistence:
    def test_apply_hot_persists_and_lists(self, tmp_path, monkeypatch):
        from intelligence.execution import live_apply
        # Redirect persistence to a temp file for isolation.
        live_apply.HOT_APPLIED_PATH = os.path.join(str(tmp_path), "hot_applied.json")

        class FakeStrategy:
            spacing = 1.0
            levels = 1

        dep = {
            "id": "hot1",
            "strategy_key": "grid_strategy",
            "params": {"spacing": 0.1, "levels": 5},
        }
        s = FakeStrategy()
        out = live_apply.apply_hot(s, dep)
        assert out["hot"] is True
        assert "spacing" in out["applied"]
        assert s.spacing == 0.1 and s.levels == 5   # params applied to the running instance

        records = live_apply.list_hot_applied()
        assert len(records) == 1
        assert records[0]["deployment_id"] == "hot1"
        assert records[0]["applied"] == ["spacing", "levels"]

    def test_kill_switch_config_exposed(self):
        from intelligence.execution import live_apply
        assert live_apply.EXEC_KILL_MAX_DRAWDOWN_PCT > 0
        assert isinstance(live_apply.EXEC_KILL_CONSENSUS_COLLAPSE, bool)
        assert isinstance(live_apply.EXEC_KILL_REGIME_FLIP, bool)




# ── News Desk (Phase 5) ─────────────────────────────────────────────────

def _fake_articles(n=4, seed=1):
    """Deterministic injected news corpus (no network)."""
    return sample_news(["GC=F"], n, seed=seed)


def _news_verdict_json(cited_title):
    return json.dumps({
        "direction": "BULL", "strength": 0.7, "confidence": 0.6,
        "horizon": "short", "rationale": "haven flows dominate the corpus",
        "key_themes": ["safe haven"], "risks": ["dollar strength"],
        "evidence_cited": [cited_title],
    })


class TestNewsCorpus:
    def test_sample_news_is_deterministic_and_relevant(self):
        a = _fake_articles(6, seed=7)
        b = _fake_articles(6, seed=7)
        assert len(a) == len(b) == 6
        assert [x.title for x in a] == [x.title for x in b]
        # Relevance ranking puts symbol-relevant gold headlines first.
        assert any("gold" in x.title.lower() for x in a[:2])

    def test_dedupe_drops_normalized_duplicates(self):
        a = _fake_articles(3)
        dup = Article(source="Wire", title=a[0].title.upper() + "!")
        out = dedupe_articles(list(a) + [dup])
        assert len(out) == 3

    def test_rank_orders_by_relevance_then_recency(self):
        items = [
            Article(source="Wire", title="Gold rallies on safe-haven demand",
                    published_at="2025-01-01T00:00:00Z", tier="wire"),
            Article(source="Desk", title="Markets quiet ahead of holiday",
                    published_at="2025-01-02T00:00:00Z", tier="desk"),
        ]
        ranked = rank_articles(items, ["GC=F"], 10)
        assert ranked[0].title.startswith("Gold")

    def test_fetch_fails_safe_without_network(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("no network")

        monkeypatch.setattr("requests.get", boom)
        monkeypatch.setattr("yfinance.Ticker", lambda *a, **k: boom)
        assert fetch_news(["GC=F"], 5) == []
        assert news_mod.fetch_news_api(["GC=F"], 5) == []

    def test_fetch_news_api_requires_key(self, monkeypatch):
        monkeypatch.delenv("NEWS_API_KEY", raising=False)
        assert news_mod.fetch_news_api(["GC=F"], 5) == []

    def test_parse_feed_stdlib_rss(self):
        rss = ("<rss version='2.0'><channel><item>"
               "<title>Gold steadies ahead of CPI</title>"
               "<link>https://example.com/gold-cpi</link>"
               "<pubDate>Fri, 14 Aug 2026 10:00:00 GMT</pubDate>"
               "<description>Bullion holds range.</description>"
               "</item></channel></rss>")
        items = news_mod._parse_feed(rss)
        assert len(items) == 1
        assert items[0]["title"] == "Gold steadies ahead of CPI"
        assert items[0]["link"] == "https://example.com/gold-cpi"

    def test_parse_feed_stdlib_atom(self):
        atom = ("<feed xmlns='http://www.w3.org/2005/Atom'><entry>"
                "<title>Silver rallies on demand</title>"
                "<link href='https://example.com/silver'/>"
                "<updated>2026-08-14T10:00:00Z</updated>"
                "</entry></feed>")
        items = news_mod._parse_feed(atom)
        assert len(items) == 1
        assert items[0]["title"] == "Silver rallies on demand"
        assert items[0]["link"] == "https://example.com/silver"

    def test_fetch_news_parses_rss_with_stdlib(self, monkeypatch):
        rss = ("<rss version='2.0'><channel><item>"
               "<title>Gold hits record high on haven demand</title>"
               "<link>https://example.com/gold</link>"
               "<pubDate>Fri, 14 Aug 2026 10:00:00 GMT</pubDate>"
               "<description>Safe-haven flows.</description>"
               "</item></channel></rss>")

        class _Resp:
            status_code = 200
            content = rss.encode()

        monkeypatch.setattr("requests.get", lambda *a, **k: _Resp())
        monkeypatch.setattr("yfinance.Ticker", lambda *a, **k: None)  # avoid fallback
        arts = fetch_news(["GC=F"], max_items=5, timeout=5)
        assert arts and any("record high" in a.title for a in arts)


class TestNewsResearchAgent:
    def test_disabled_reports_disabled(self):
        agent = NewsResearchAnalystAgent({"news_enabled": False})
        report = agent.run(None)
        assert report["status"] == "disabled"

    def test_default_off_never_touches_network(self):
        agent = NewsResearchAnalystAgent({})
        report = agent.run(None)
        assert report["status"] == "disabled"

    def test_offline_fetcher_reports_no_news(self):
        agent = NewsResearchAnalystAgent({
            "news_enabled": True,
            "news_fetcher": lambda symbols=None, max_items=20: []})
        report = agent.run(None)
        assert report["status"] == "no_news"
        assert report["article_count"] == 0

    def test_injected_fetcher_curates_corpus(self):
        agent = NewsResearchAnalystAgent({
            "news_enabled": True,
            "news_fetcher": lambda symbols=None, max_items=20: _fake_articles(5)})
        report = agent.run(None)
        assert report["status"] == "fetched"
        assert report["article_count"] == 5
        assert report["outlets"] and report["articles"][0]["title"]

    def test_sample_corpus_fallback_is_labeled(self):
        agent = NewsResearchAnalystAgent({
            "news_enabled": True, "news_use_sample": True,
            "news_fetcher": lambda symbols=None, max_items=20: []})
        report = agent.run(None)
        assert report["status"] == "fetched"
        assert report["articles"][0]["source"] == "Sample corpus"



class TestNewsSignal:
    def test_from_news_maps_verdict(self):
        from intelligence.consensus.signals import Signal
        verdict = {"direction": "BEAR", "strength": 0.8, "confidence": 0.7,
                   "horizon": "short", "evidence_cited": ["h1"],
                   "key_themes": ["dollar"]}
        s = Signal.from_news(verdict)
        assert s.source == "news" and s.direction == "BEAR"
        assert s.horizon == "short"
        assert s.evidence["articles_cited"] == ["h1"]

    def test_from_news_rejects_none(self):
        from intelligence.consensus.signals import Signal
        assert Signal.from_news(None) is None

    def test_from_news_clamps_strength(self):
        from intelligence.consensus.signals import Signal
        s = Signal.from_news({"direction": "BULL", "strength": 5.0,
                              "confidence": -1.0, "evidence_cited": ["h"]})
        assert s.strength == 1.0 and s.confidence == 0.0


class TestNewsFactCheck:
    def test_grounded_verdict_passes(self):
        arts = _fake_articles(4)
        items = [a.to_dict() for a in arts]
        verdict = {"direction": "BULL", "strength": 0.8, "confidence": 0.6,
                   "evidence_cited": [arts[0].title]}
        rep = fact_check_news_verdict(verdict, items)
        assert rep["passed"] is True
        assert rep["checked"] == 1

    def test_hallucinated_headline_is_flagged(self):
        arts = _fake_articles(4)
        items = [a.to_dict() for a in arts]
        verdict = {"direction": "BULL", "strength": 0.8, "confidence": 0.6,
                   "evidence_cited": ["BREAKING: Martians buy all the gold"]}
        rep = fact_check_news_verdict(verdict, items)
        assert rep["passed"] is False
        assert rep["flagged"]

    def test_empty_citations_fail(self):
        arts = _fake_articles(4)
        items = [a.to_dict() for a in arts]
        verdict = {"direction": "BULL", "strength": 0.8, "confidence": 0.6}
        assert fact_check_news_verdict(verdict, items)["passed"] is False

    def test_bad_direction_flagged_and_values_clamped(self):
        arts = _fake_articles(4)
        items = [a.to_dict() for a in arts]
        verdict = {"direction": "LUNAR", "strength": 9.0, "confidence": -1.0,
                   "evidence_cited": [arts[0].title]}
        rep = fact_check_news_verdict(verdict, items)
        assert rep["passed"] is False
        assert verdict["strength"] == 1.0 and verdict["confidence"] == 0.0


class TestNewsLLM:
    def test_analyze_news_inactive_returns_none(self, monkeypatch):
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        narrator = LLMNarrator({})
        assert narrator.analyze_news(_fake_articles(3)) is None

    def test_analyze_news_uses_news_model_and_grounds(self):
        cited = _fake_articles(2)[0].title
        fake = _FakeLLMClient(text=_news_verdict_json(cited))
        narrator = LLMNarrator({"llm_enabled": True}, client=fake)
        verdict = narrator.analyze_news(_fake_articles(2))
        assert verdict and verdict["direction"] == "BULL"
        assert verdict["_fact_check"]["passed"] is True
        assert fake.news_model in [c[2] for c in fake.calls]

    def test_analyze_news_drops_hallucinated_verdict(self):
        fake = _FakeLLMClient(text=_news_verdict_json("This headline never existed"))
        narrator = LLMNarrator({"llm_enabled": True}, client=fake)
        assert narrator.analyze_news(_fake_articles(2)) is None

    def test_explain_news_deterministic_fallback(self, monkeypatch):
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        narrator = LLMNarrator({})
        na = {"status": "fetched", "article_count": 5, "outlets": ["Kitco"],
              "news_verdict": {"direction": "BULL", "strength": 0.6},
              "confirmation": {"available": True, "agrees": True,
                               "model_direction": "BULL"}}
        text = narrator.explain_news(na)
        assert "CONFIRMED" in text

    def test_explain_news_active_uses_news_model(self):
        fake = _FakeLLMClient(text="NEWS-BRIEF")
        narrator = LLMNarrator({"llm_enabled": True}, client=fake)
        out = narrator.explain_news({"status": "fetched"})
        assert out == "NEWS-BRIEF"
        assert fake.news_model in [c[2] for c in fake.calls]

class TestNewsConfirmation:
    def test_confirms_when_models_agree(self):
        from intelligence.consensus.signals import Signal
        news = Signal.from_news({"direction": "BULL", "strength": 0.6,
                                 "confidence": 0.6, "evidence_cited": ["h"]})
        kronos = Signal("kronos", "BULL", 0.8, 0.8)
        rf = Signal("rf_regime", "BULL", 0.7, 0.7)
        conf = compute_news_confirmation(news, [kronos, rf])
        assert conf["available"] and conf["agrees"] is True
        assert conf["model_direction"] == "BULL"

    def test_diverges_when_models_disagree(self):
        from intelligence.consensus.signals import Signal
        news = Signal.from_news({"direction": "BEAR", "strength": 0.6,
                                 "confidence": 0.6, "evidence_cited": ["h"]})
        kronos = Signal("kronos", "BULL", 0.8, 0.8)
        rf = Signal("rf_regime", "BULL", 0.7, 0.7)
        conf = compute_news_confirmation(news, [kronos, rf])
        assert conf["available"] and conf["agrees"] is False
        assert "DIVERGES" in conf["semantics"]

    def test_unavailable_without_models(self):
        from intelligence.consensus.signals import Signal
        news = Signal.from_news({"direction": "BULL", "strength": 0.6,
                                 "confidence": 0.6, "evidence_cited": ["h"]})
        conf = compute_news_confirmation(news, [])
        assert conf["available"] is False

    def test_collect_news_requires_grounded_verdict(self):
        assert collect_news({}) is None
        assert collect_news({"news_verdict": None}) is None


class TestNewsConsensus:
    def test_news_is_low_weight_and_cannot_flip_strong_panel(self):
        from intelligence.consensus import ConsensusEngine
        from intelligence.consensus.signals import Signal
        engine = ConsensusEngine()
        assert engine.source_weights["news"] < engine.source_weights["kronos"]
        news = Signal.from_news({"direction": "BULL", "strength": 0.9,
                                 "confidence": 0.9, "evidence_cited": ["h"]})
        panel = [Signal("kronos", "BEAR", 1.0, 1.0), Signal("rf_regime", "BEAR", 1.0, 1.0)]
        view = engine.fuse(panel + [news])
        assert view.direction == "BEAR"
        assert "news" in view.sources

    def test_news_raises_effective_n(self):
        from intelligence.consensus import ConsensusEngine
        from intelligence.consensus.signals import Signal
        base = [Signal("kronos", "BULL", 0.8, 0.8), Signal("rf_regime", "BULL", 0.8, 0.8)]
        news = Signal.from_news({"direction": "BULL", "strength": 0.8,
                                 "confidence": 0.8, "evidence_cited": ["h"]})
        without = ConsensusEngine().fuse(base)
        with_news = ConsensusEngine().fuse(base + [news])
        assert with_news.effective_n > without.effective_n

    def test_market_view_roundtrips_news_analysis(self, tmp_path):
        from intelligence.consensus import MarketView
        from intelligence.ledger import OpportunityLedger
        path = os.path.join(str(tmp_path), "ledger.json")
        ledger = OpportunityLedger(path=path)
        mv = MarketView(direction="BULL")
        mv.news_analysis = {"status": "fetched", "article_count": 3,
                            "news_verdict": {"direction": "BULL"},
                            "confirmation": {"available": True, "agrees": True}}
        ledger.add_market_view(mv)
        ledger.save()
        loaded = OpportunityLedger.load(path)
        assert loaded.market_views[0]["news_analysis"]["article_count"] == 3


class TestNewsInCoordinator:
    def test_cycle_includes_news_desk(self, tmp_path):
        project_root = _make_project_root(tmp_path)
        articles = _fake_articles(4)
        fake = _FakeLLMClient(text=_news_verdict_json(articles[0].title))
        narrator = LLMNarrator({"llm_enabled": True}, client=fake)
        ctx = {"project_root": project_root, "max_bars": 300, "probe_limit": 1,
               "top_n": 1, "ledger_path": os.path.join(str(tmp_path), "ledger.json"),
               "news_enabled": True,
               "news_fetcher": lambda symbols=None, max_items=20: articles}
        coord = CoordinatorAgent(ctx, narrator=narrator)
        brief, ledger = coord.run_cycle()
        na = brief["news_analysis"]
        assert na["status"] == "fetched"
        assert na["article_count"] == 4
        assert na["news_verdict"]["direction"] == "BULL"
        mv = brief["market_view"]
        assert any(c["source"] == "news" for c in mv["contributions"])
        assert "news_narrative" in brief
        # Persisted view carries the News Desk block too.
        assert ledger.market_views[-1].get("news_analysis")

    def test_cycle_without_news_is_silent(self, tmp_path):
        project_root = _make_project_root(tmp_path)
        ctx = {"project_root": project_root, "max_bars": 300, "probe_limit": 1,
               "top_n": 1, "ledger_path": os.path.join(str(tmp_path), "ledger.json")}
        coord = CoordinatorAgent(ctx)
        brief, _ = coord.run_cycle()
        assert brief.get("news_analysis") is None
        assert all(c.get("source") != "news"
                   for c in (brief.get("market_view") or {}).get("contributions", []))

    def test_run_news_desk_fast_path(self, tmp_path):
        # The dashboard "⚡ Fetch News Now" path — no probes/backtests.
        from intelligence.ledger import OpportunityLedger
        path = os.path.join(str(tmp_path), "ledger.json")
        ledger = OpportunityLedger(path=path)
        articles = _fake_articles(4)
        fake = _FakeLLMClient(text=_news_verdict_json(articles[0].title))
        narrator = LLMNarrator({"llm_enabled": True}, client=fake)
        ctx = {"ledger_path": path, "news_enabled": True,
               "news_fetcher": lambda symbols=None, max_items=20: articles}
        coord = CoordinatorAgent(ctx, narrator=narrator)
        report, na = coord.run_news_desk()
        assert na and na["status"] == "fetched"
        assert na["article_count"] == 4
        assert na["news_verdict"]["direction"] == "BULL"
        # Persisted onto the (bare) market view so /api/intelligence/news serves it.
        loaded = OpportunityLedger.load(path)
        assert loaded.market_views and loaded.market_views[-1]["news_analysis"]

