"""NewsResearchAnalystAgent — the News Desk of the quant team.

Primary responsibility: source the day's trading news from multiple outlets,
curate it (dedupe, rank by relevance to the researched instruments) and hand
the corpus to the CQO, who runs Claude Sonnet over it to draft a market-
direction conclusion. Kronos + the RF regime model then verify (or contradict)
that conclusion inside the consensus engine.

InsightForge mapping:
    Recruiter (participant pool) -> Data Scout (instruments & data)
    NEW — News Desk              -> Macro / News Research Analyst (market narrative)
    Interviewer                  -> Market Prober
    ...

Fail-safe contract (identical to every other agent):
    * Offline / no feed / no API key -> ``status: "no_news"``, never raises.
    * The LLM verdict is produced by the COORDINATOR (single LLM gateway),
      not by this agent — this agent stays deterministic (source + curate).
"""

import os

from .base import BaseAgent

_QUANT_ENV_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class NewsResearchAnalystAgent(BaseAgent):
    KEY = "news"
    ROLE = "News Research Analyst"
    REPLACES = "Macro / News Research Analyst (Market Direction)"
    PRIMARY_RESPONSIBILITY = (
        "Researches trading news across multiple outlets, curates a relevant "
        "corpus, and feeds the CQO's Claude Sonnet synthesis — which Kronos and "
        "the RF regime model then verify inside the consensus engine."
    )
    INTEGRATIONS = [
        "RSS outlets (MarketWatch / CNBC / Kitco / ForexLive / FXStreet)",
        "NewsAPI.org (NEWS_API_KEY)",
        "Claude Sonnet direction synthesis (coordinator)",
        "Kronos + RandomForest regime model (verification)",
    ]

    def __init__(self, ctx=None):
        super().__init__(ctx)
        # Opt-in at the agent level: production paths (scheduler / dashboard
        # cycle / runner --news) enable it explicitly, so unit tests and bare
        # CoordinatorAgent() calls never touch the network.
        self.enabled = bool(self.ctx.get("news_enabled", False))
        self.max_articles = max(1, int(self.ctx.get("news_max_articles", 20)))
        self.use_sample = bool(self.ctx.get("news_use_sample", False))
        raw_symbols = str(self.ctx.get("symbols") or os.getenv("RESEARCH_SYMBOLS", "GC=F"))
        self.symbols = [s.strip() for s in raw_symbols.split(",") if s.strip()] or ["GC=F"]
        # Injectable fetcher (tests / alternate backends). Defaults to RSS.
        self._fetcher = self.ctx.get("news_fetcher")

    # ── Run ───────────────────────────────────────────────────────────
    def run(self, ledger):
        from ..news import dedupe_articles, fetch_news, rank_articles, sample_news

        if not self.enabled:
            return self._report(status="disabled", article_count=0, outlets=[],
                                articles=[])

        fetcher = self._fetcher or fetch_news
        raw = []
        try:
            raw = fetcher(symbols=self.symbols, max_items=self.max_articles)
        except Exception as e:
            self.log(f"news fetch failed: {e}")

        articles = dedupe_articles(raw or [])
        if not articles and self.use_sample:
            # Air-gapped / demo mode: a clearly-labelled offline corpus.
            articles = sample_news(symbols=self.symbols, max_items=self.max_articles)
            self.log("Using the deterministic OFFLINE sample corpus "
                     "(NEWS_USE_SAMPLE=true) — not live headlines.")

        ranked = rank_articles(articles, self.symbols, self.max_articles)
        status = "fetched" if ranked else "no_news"
        outlets = sorted({a.source for a in ranked if a.source})
        self.log(f"Fetched {len(ranked)} trading headlines across "
                 f"{len(outlets)} outlets ({status})")

        return self._report(
            status=status,
            article_count=len(ranked),
            outlets=outlets,
            symbols=self.symbols,
            articles=[a.to_dict() for a in ranked],
        )
