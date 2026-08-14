"""news — trading-news corpus for the News Research Analyst (News Desk).

The News Desk is the one intelligence source that is NOT derived from price
bars: it reads what the world is saying about the traded instruments, lets
Claude Sonnet draft a market-direction conclusion grounded in the verbatim
headline corpus, and then lets Kronos + the RF regime model *verify* (or
contradict) that conclusion inside the consensus engine.

Design rules (same fail-safe ethos as ``consensus/sources.py``):

  * Every fetcher returns ``[]`` on ANY failure — the consensus never blocks
    on news; it just reflects the brains that are present.
  * ``fetch_news`` reads public RSS endpoints (feedparser over a timed
    ``requests`` GET) or the NewsAPI.org REST endpoint (``NEWS_API_KEY``).
  * ``sample_news`` returns a small deterministic OFFLINE corpus so the desk
    can be exercised end-to-end without network access. It is clearly
    labelled "sample corpus" and is never confused with live headlines.
  * Articles are deduped on a normalized title and ranked by relevance to the
    researched symbols (keyword overlap) and recency.
"""

import os
import random
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone

# ── Outlet registry (trading-focused public feeds) ──────────────────────
# ``tier``: "wire" = primary financial wire / major outlet, "desk" = specialist
# trading desk. Tiers only nudge relevance ranking.
DEFAULT_OUTLETS = [
    {"name": "MarketWatch", "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories", "tier": "wire"},
    {"name": "CNBC Markets", "url": "https://www.cnbc.com/id/10000664/device/rss/rss.html", "tier": "wire"},
    {"name": "Yahoo Finance", "url": "https://finance.yahoo.com/news/rssindex", "tier": "wire"},
    {"name": "ForexLive", "url": "https://www.forexlive.com/feed/", "tier": "desk"},
    {"name": "FXStreet News", "url": "https://www.fxstreet.com/rss/news", "tier": "desk"},
]

# Symbol -> news search keywords used for relevance ranking and NewsAPI queries.
_SYMBOL_KEYWORDS = {
    "GC=F": ("gold", "precious metal", "bullion"),
    "XAUUSD.r": ("gold", "precious metal", "bullion"),
    "XAUUSD": ("gold", "precious metal", "bullion"),
    "SI=F": ("silver", "precious metal"),
    "XAG": ("silver", "precious metal"),
    "CL=F": ("crude", "oil", "opec"),
    "WTI": ("crude", "oil", "opec"),
    "BRENT": ("crude", "oil", "opec"),
}

# Generic macro keywords that matter for precious/energy metals.
_MACRO_KEYWORDS = (
    "fed", "federal reserve", "inflation", "rate cut", "rate hike", "treasury",
    "yield", "dollar", "dxy", "safe haven", "geopolitics", "recession",
    "central bank", "etf", "commodities", "copper", "pm", "fomc", "nonfarm",
)


def _normalize(text: str) -> str:
    """Lowercase + squeeze whitespace + strip punctuation for title matching."""
    t = re.sub(r"[^a-z0-9\s]", "", str(text or "").lower())
    return re.sub(r"\s+", " ", t).strip()


@dataclass
class Article:
    """One fetched trading headline with provenance (source + timestamp)."""

    source: str
    title: str
    url: str = ""
    published_at: str = ""
    summary: str = ""
    tier: str = "desk"

    def to_dict(self) -> dict:
        return asdict(self)


# ── Outlet configuration ────────────────────────────────────────────────
def load_outlets(outlets=None):
    """Resolve the outlet list: explicit > NEWS_OUTLETS JSON env > defaults."""
    if outlets:
        return list(outlets)
    raw = os.getenv("NEWS_OUTLETS", "").strip()
    if raw:
        try:
            import json
            data = json.loads(raw)
            if isinstance(data, list) and data:
                return data
        except Exception:
            pass
    return list(DEFAULT_OUTLETS)


# Browser-like UA — several feed hosts reject non-browser clients.
_BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _parse_feed(content):
    """Parse RSS 2.0 / Atom XML into a list of field dicts.

    Pure stdlib (``xml.etree``) — there is deliberately NO feedparser
    dependency, so the News Desk works on any install.
    """
    import xml.etree.ElementTree as ET
    root = ET.fromstring(content)
    items = []
    for el in root.iter():
        tag = el.tag.split("}")[-1]  # strip XML namespace
        if tag not in ("item", "entry"):
            continue
        fields = {}
        for child in el:
            ctag = child.tag.split("}")[-1]
            if ctag in ("title", "link", "pubDate", "published", "updated",
                        "description", "summary"):
                text = (child.text or "").strip()
                if ctag == "link" and not text:
                    text = child.get("href") or ""
                if text and ctag not in fields:
                    fields[ctag] = text
        if fields.get("title"):
            items.append(fields)
    return items


# ── Fetchers (fail-safe) ────────────────────────────────────────────────
def fetch_news(symbols=None, max_items=20, outlets=None, timeout=8.0):
    """Fetch trading news from the outlet registry (RSS/Atom via stdlib).

    Falls back to Yahoo Finance news when the RSS outlets return nothing
    (many hosts block datacenter/scripted networks).  Fail-safe: returns
    ``[]`` on any failure. ``symbols`` only guides relevance ranking.
    """
    import requests

    outlet_list = load_outlets(outlets)
    symbols = symbols or ["GC=F"]
    articles = []
    for outlet in outlet_list:
        if len(articles) >= max_items * 4:  # fetch headroom for ranking
            break
        try:
            r = requests.get(outlet["url"], timeout=timeout,
                             headers={"User-Agent": _BROWSER_UA})
            if r.status_code != 200:
                continue
            for entry in _parse_feed(r.content):
                title = entry.get("title", "")
                if not title:
                    continue
                published = (entry.get("pubDate") or entry.get("published")
                             or entry.get("updated") or "")
                summary = re.sub(r"<[^>]+>", "",
                                 entry.get("description") or entry.get("summary") or "")
                summary = re.sub(r"\s+", " ", summary).strip()[:400]
                articles.append(Article(
                    source=outlet["name"], title=title,
                    url=entry.get("link", ""), published_at=published,
                    summary=summary, tier=outlet.get("tier", "desk")))
        except Exception:
            continue
    ranked = rank_articles(dedupe_articles(articles), symbols, max_items)
    if not ranked:
        # RSS blocked/dark — Yahoo Finance news is usually reachable and is
        # directly symbol-relevant (e.g. "Gold prices must overcome...").
        ranked = fetch_yfinance_news(symbols=symbols, max_items=max_items)
    return ranked


def fetch_yfinance_news(symbols=None, max_items=15, timeout=8.0):
    """Gold-relevant headlines from Yahoo Finance (works where RSS is blocked).

    Uses the same Yahoo endpoint as the rest of the repo (yfinance), so it
    shares the machine's existing network reachability.  Fail-safe: ``[]``.
    """
    try:
        import yfinance as yf
    except Exception:
        return []
    symbols = symbols or ["GC=F"]
    articles = []
    for sym in symbols[:2]:
        try:
            for item in (yf.Ticker(sym).news or [])[: max_items * 3]:
                content = item.get("content", {}) or {}
                title = (content.get("title") or item.get("title") or "").strip()
                if not title:
                    continue
                ts = (item.get("providerPublishTime")
                      or content.get("providerPublishTime")
                      or content.get("pubDate"))
                published = ""
                if ts:
                    try:
                        from datetime import datetime, timezone
                        published = datetime.fromtimestamp(
                            int(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    except (TypeError, ValueError):
                        published = ""
                summary = (content.get("summary") or content.get("description") or "")[:400]
                cj = content.get("canonicalUrl", {}) or {}
                url = cj.get("url") or item.get("link") or ""
                articles.append(Article(
                    source="Yahoo Finance", title=title, url=str(url),
                    published_at=published, summary=summary, tier="wire"))
        except Exception:
            continue
    return rank_articles(dedupe_articles(articles), symbols, max_items)


def fetch_news_api(symbols=None, max_items=20, api_key=None, timeout=8.0):
    """Fetch trading news via NewsAPI.org (requires NEWS_API_KEY).

    Uses the ``everything`` endpoint with an OR-joined symbol keyword query.
    Fail-safe: ``[]`` without a key or on any error.
    """
    api_key = api_key or os.getenv("NEWS_API_KEY", "").strip()
    if not api_key:
        return []
    symbols = symbols or ["GC=F"]
    terms = _search_terms(symbols)
    if not terms:
        return []
    try:
        import requests
        r = requests.get("https://newsapi.org/v2/everything", timeout=timeout,
                         params={"q": " OR ".join(terms), "language": "en",
                                 "sortBy": "publishedAt", "pageSize": max_items * 3,
                                 "apiKey": api_key})
        data = r.json()
        articles = []
        for a in (data.get("articles") or []):
            title = (a.get("title") or "").strip()
            if not title:
                continue
            articles.append(Article(
                source=(a.get("source") or {}).get("name") or "NewsAPI",
                title=title, url=a.get("url") or "",
                published_at=a.get("publishedAt") or "",
                summary=(a.get("description") or "")[:400],
                tier="wire"))
    
        return rank_articles(dedupe_articles(articles), symbols, max_items)
    except Exception:
        return []
# ── Deterministic offline corpus ────────────────────────────────────────
_SAMPLE_HEADLINES = [
    ("Kitco Gold News", "Gold steadies near $2,350 as traders await US inflation data",
     "Bullion holds a tight range into the CPI release; analysts flag consolidation "
     "before the next directional leg."),
    ("Reuters", "Fed minutes signal rates to stay higher for longer; dollar firms",
     "Minutes from the latest FOMC show officials reluctant to cut early; the firmer "
     "dollar pressures dollar-denominated metals."),
    ("MarketWatch", "Safe-haven demand lifts gold as Middle East tensions escalate",
     "Geopolitical risk premium returns to bullion, pushing prices to a two-week high "
     "as equities wobble."),
    ("CNBC Markets", "Gold retreats as Treasury yields climb to a two-week high",
     "Rising real yields outweigh haven flows, sending bullion off its highs into the "
     "session close."),
    ("Kitco Gold News", "Silver rallies 3% on industrial demand outlook and short covering",
     "Silver outperforms gold as industrial demand expectations and a short squeeze "
     "drive prices sharply higher."),
    ("Reuters", "Crude climbs on OPEC+ supply cuts, gold shrugs off firm dollar",
     "Energy leads the complex higher while bullion holds flat, decoupling from the "
     "dollar for the session."),
    ("MarketWatch", "Central bank buying keeps gold underpinned, strategists say",
     "Persistent official-sector accumulation provides a structural bid beneath the "
     "metal, analysts note."),
    ("Yahoo Finance", "Dollar index heads for weekly gain, capping metals rally",
     "A resurgent dollar caps upside in precious metals after a strong run; bulls "
     "watch the 50-day moving average."),
    ("Reuters", "Copper hits record as energy-transition demand accelerates",
     "Copper extends its advance to an all-time high on grid and EV demand, lending a "
     "risk-on tone to the metals complex."),
    ("ForexLive", "US jobs data beats expectations; odds of a Fed cut slip",
     "Strong payrolls push back rate-cut bets, a headwind for gold; traders reprice "
     "the next two meetings."),
    ("Kitco Gold News", "Gold miners rally; analysts flag stretched valuations",
     "Equity proxies for gold climb but caution rises as valuations outpace spot "
     "performance."),
    ("FXStreet News", "Palladium slides on weak auto demand, gold holds its range",
     "Palladium remains the laggard of the complex; gold's tight range persists into "
     "the policy window."),
    ("Kitco Gold News", "Silver supply deficit narrows; prices consolidate",
     "A narrower projected deficit takes some momentum out of silver after its "
     "outperformance."),
    ("Reuters", "Gold ETF outflows weigh on bullion despite inflation-hedge appeal",
     "Paper-metal outflows partially offset physical demand strength, keeping the "
     "metal range-bound."),
]


def sample_news(symbols=None, max_items=12, seed=42):
    """Deterministic OFFLINE headline corpus (demos / tests / air-gapped runs).

    The returned articles carry ``source="Sample corpus"`` so no consumer can
    mistake them for live news. Fail-safe never applies — this never fails.
    """
    rng = random.Random(seed)
    symbols = symbols or ["GC=F"]
    chosen = rng.sample(_SAMPLE_HEADLINES, min(len(_SAMPLE_HEADLINES), max_items or 12))
    now = datetime.now(timezone.utc)
    articles = []
    for i, (source, title, summary) in enumerate(chosen):
        published = (now - timedelta(minutes=15 * (i + 1))).strftime("%Y-%m-%dT%H:%M:%SZ")
        articles.append(Article(
            source="Sample corpus", title=title, published_at=published,
            summary=summary, tier="wire"))
    return rank_articles(articles, symbols, len(articles))


# ── Corpus hygiene ──────────────────────────────────────────────────────
def dedupe_articles(articles):
    """Drop near-duplicate titles (normalized) while keeping the first seen."""
    seen, out = set(), []
    for a in articles:
        key = _normalize(a.title)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


def _search_terms(symbols):
    """Map researched symbols onto news keyword terms (deduped)."""
    terms = []
    for s in symbols or []:
        for kw in _SYMBOL_KEYWORDS.get(str(s).upper(), ()):
            if kw not in terms:
                terms.append(kw)
    return terms


def _relevance_score(article, symbols):
    """Keyword-overlap relevance in [0, 1]: symbol hit >> macro hit >> none."""
    text = f"{article.title} {article.summary}".lower()
    hits = [kw for kw in _search_terms(symbols) if kw in text]
    if hits:
        base = 1.0
    else:
        macro = sum(1 for kw in _MACRO_KEYWORDS if kw in text)
        base = min(0.5, 0.05 * macro)
    tier = 1.0 if getattr(article, "tier", "desk") == "wire" else 0.9
    return round(base * tier, 3)


def _published_ts(article):
    """Best-effort parse of published_at -> epoch seconds (0 on failure)."""
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z",
                "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            dt = datetime.strptime(article.published_at, fmt)
            return dt.timestamp()
        except (TypeError, ValueError):
            continue
    return 0.0


def rank_articles(articles, symbols=None, max_items=20):
    """Rank by (relevance desc, recency desc) and return the top ``max_items``.

    Never raises: bad input simply yields ``[]``.
    """
    if not articles:
        return []
    symbols = symbols or ["GC=F"]
    try:
        ranked = sorted(articles, key=lambda a: (_relevance_score(a, symbols),
                                                 _published_ts(a)), reverse=True)
    except Exception:
        ranked = list(articles)
    return ranked[: max(1, int(max_items or 20))]
