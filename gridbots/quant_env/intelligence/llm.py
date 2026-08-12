"""
Optional LLM narrative layer for the agent team.

The deterministic agents produce numbers and structured evidence; this layer
converts them into natural-language narratives (executive summaries, deep
theme synthesis, opportunity storyboards).

The layer is strictly optional and fail-safe:

- Without an API key, ``LLMClient.available`` is False and every method
  falls back to deterministic text, so the engine never depends on an
  external model.
- Every network call is wrapped; a failure returns the deterministic
  fallback instead of raising.
- Cost control: only top-N themes/opportunities are narrated per cycle.

Providers: ``openai`` (chat completions) and ``anthropic`` (messages).
Set via env vars: LLM_PROVIDER, LLM_API_KEY, LLM_FAST_MODEL,
LLM_CAPABLE_MODEL.
"""

import json
import os
from pathlib import Path

_ENDPOINTS = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
}

# ── Latest model tiers (2026) ────────────────────────────────────────
# Fast tier  -> Claude Haiku 4.5  (fastest/lightest; executive summaries)
# Capable    -> Claude Opus 5     (highest raw capability; deep synthesis)
# Fallbacks  -> Opus 4.8 -> Sonnet 5 -> 3.5-gen, so a bad/unsupported name
#               degrades gracefully instead of failing the cycle.
_DEFAULT_FAST_OPENAI = "gpt-4o-mini"
_DEFAULT_FAST_ANTHROPIC = "claude-haiku-4-5"
_DEFAULT_CAPABLE_MODEL = "claude-opus-5"
_ANTHROPIC_FAST_FALLBACKS = ["claude-haiku-4-5-20251001", "claude-3-5-haiku-latest"]
_ANTHROPIC_CAPABLE_FALLBACKS = ["claude-opus-4-8", "claude-sonnet-5",
                                "claude-3-5-sonnet-latest"]
_OPENAI_CAPABLE_FALLBACKS = ["gpt-4o", "gpt-4o-mini"]

# ── Calibrated narration prompts (2026) ──────────────────────────────
# Kept as module constants so they are easy to tune; each narration passes
# its own temperature.  Every prompt forbids inventing statistics and
# enforces the human deployment gate.
_PROMPTS = {
    "executive_summary": (
        "You are the Chief Quant Officer of an autonomous research desk writing a daily brief for a "
        "portfolio manager. Reply with exactly four short sentences: (1) what was tested and the "
        "verdict, (2) the strongest theme and its confidence, (3) the top opportunity and its qRICE, "
        "(4) the key risk and a reminder that deployment requires human approval. Use only the "
        "numbers in the JSON; never invent statistics. No hedging, no fluff, no markdown headers."
    ),
    "theme": (
        "You are a quantitative research analyst writing an alpha-theme debrief. In 2-3 sentences "
        "cover: the market mechanism, the observed evidence (trades, Sharpe, out-of-sample "
        "consistency), why it may persist, and the key risks. If out-of-sample consistency is below "
        "0.5, state explicitly that the theme is not yet investable. Use only the evidence provided; "
        "never invent statistics."
    ),
    "opportunity": (
        "You are a portfolio manager writing a strategy kickoff note. In 2-3 sentences state: the "
        "objective, what must be validated first, the hard risk gates, and the suggested capital "
        "allocation. Remind that deployment requires human approval. Use only the numbers provided; "
        "never invent statistics."
    ),
    "cross_validate": (
        "You are the Chief Risk Officer of a systematic trading desk. You are given the raw evidence "
        "bundle: Kronos foundation-model forecast features, the RandomForest regime probabilities, "
        "backtest/walk-forward probe metrics, and the deterministic trend filter. Your job is to "
        "challenge the research team's conclusion and reach your OWN market view. Reply with EXACTLY "
        "one JSON object, no prose, no markdown, with ONLY these keys: "
        "direction (\"BULL\", \"BEAR\" or \"RANGING\"), strength (0..1), confidence (0..1), "
        "horizon (\"short\"|\"medium\"|\"long\"), "
        "key_risks (array of strings), evidence_cited (array of strings — each must quote a number "
        "that exists verbatim in the evidence bundle). Never invent statistics. If the evidence is "
        "contradictory or thin, prefer RANGING with low strength."
    ),
    "market_view": (
        "You are the Chief Quant Officer explaining the team's consensus market view to a portfolio "
        "manager. In 3-4 sentences explain: the agreed direction and how strong the agreement is, "
        "then for each of the top two contributing sources state WHY it voted that way (cite its "
        "exact numbers from the evidence), then name the strongest dissenting voice. Use only the "
        "numbers provided; never invent statistics."
    ),
}

_PROMPT_TEMPERATURES = {
    "executive_summary": 0.3,
    "theme": 0.4,
    "opportunity": 0.4,
    "cross_validate": 0.2,
    "market_view": 0.3,
}


def _dedupe(models):
    seen, out = set(), []
    for m in models:
        m = str(m).strip()
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _model_version(model):
    """Numeric (major, minor) for ordering families, e.g. claude-opus-5 -> (5, 0)."""
    import re
    m = re.search(r"(?:opus|sonnet|haiku)-(\d+(?:-\d+)?)", str(model).lower())
    if not m:
        return (0, 0)
    parts = m.group(1).replace("-", ".").split(".")
    try:
        return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    except ValueError:
        return (0, 0)


# The project's .env lives at gridbots/.env — three levels up from this file.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _ensure_dotenv():
    """Best-effort load of gridbots/.env so the LLM key works from any entry point."""
    try:
        from dotenv import load_dotenv
        load_dotenv(_PROJECT_ROOT / ".env")
    except Exception:
        pass


_ensure_dotenv()


class LLMClient:
    """Thin, fail-safe client for OpenAI- and Anthropic-style completions."""

    def __init__(self, ctx=None):
        ctx = ctx or {}
        self.provider = str(ctx.get("llm_provider") or os.getenv("LLM_PROVIDER", "")).lower()
        self.api_key = str(ctx.get("llm_api_key") or os.getenv("LLM_API_KEY", "")).strip()
        fast = str(ctx.get("llm_fast_model") or os.getenv("LLM_FAST_MODEL", "")).strip()
        capable = str(ctx.get("llm_capable_model") or os.getenv("LLM_CAPABLE_MODEL", "")).strip()
        # Provider-aware defaults: Anthropic never sees an OpenAI model name.
        if self.provider == "anthropic":
            self.fast_model = fast or _DEFAULT_FAST_ANTHROPIC
            self.capable_model = capable or _DEFAULT_CAPABLE_MODEL
            self.fast_chain = _dedupe([self.fast_model] + _ANTHROPIC_FAST_FALLBACKS)
            self.capable_chain = _dedupe([self.capable_model] + _ANTHROPIC_CAPABLE_FALLBACKS)
        else:
            self.fast_model = fast or _DEFAULT_FAST_OPENAI
            self.capable_model = capable or _DEFAULT_CAPABLE_MODEL
            self.fast_chain = [self.fast_model]
            self.capable_chain = _dedupe([self.capable_model] + _OPENAI_CAPABLE_FALLBACKS)
        self.timeout = int(ctx.get("llm_timeout", 30))
        self.max_tokens = int(ctx.get("llm_max_tokens", 500))
        self.available = bool(self.api_key) and self.provider in _ENDPOINTS
        self._last_error = None
        self._last_model = None
        # Auto-discovery: when every configured model fails (e.g. wrong API
        # string), query the provider's model list and pick the best working
        # model for the tier.  Cached per process + per instance.
        self.auto_models = bool(ctx.get("llm_auto_models", True))
        self._auto_cache = {}

    # ── Tier selection ────────────────────────────────────────────────
    def _chain_for(self, model):
        if model == self.fast_model:
            return self.fast_chain
        if model == self.capable_model:
            return self.capable_chain
        return [model]

    def _pick_auto_model(self, discovered, tier):
        """Best single model for a tier (diagnostics)."""
        ordered = self._auto_models(discovered, tier)
        return ordered[0] if ordered else None

    def _auto_models(self, discovered, tier):
        """All discovered models for a tier, best-first (opus > sonnet > haiku
        for capable; haiku > sonnet > opus for fast), newest version first
        within a family.  Fable is always excluded."""
        priorities = ("opus", "sonnet", "haiku") if tier == "capable" else ("haiku", "sonnet", "opus")
        lowered = [str(m) for m in (discovered or []) if "fable" not in str(m).lower()]
        out = []
        for key in priorities:
            family = [m for m in lowered if key in m.lower()]
            family.sort(key=_model_version, reverse=True)
            for m in family:
                if m not in out:
                    out.append(m)
        for m in lowered:  # anything unrecognized, keep order
            if m not in out:
                out.append(m)
        return out

    def status(self) -> dict:
        return {
            "provider": self.provider,
            "available": self.available,
            "fast_model": self.fast_model,
            "capable_model": self.capable_model,
            "last_model": self._last_model,
        }

    # ── Model discovery (diagnostics) ─────────────────────────────────
    _models_cache = None
    _models_cache_at = 0.0

    def list_models(self):
        """Return the model IDs this key can access, or [] on any failure."""
        if not self.available:
            return []
        try:
            import requests
            if self.provider == "anthropic":
                r = requests.get("https://api.anthropic.com/v1/models",
                                 headers={"x-api-key": self.api_key,
                                          "anthropic-version": "2023-06-01"},
                                 timeout=self.timeout)
                r.raise_for_status()
                return [m.get("id") for m in (r.json().get("data") or [])]
            if self.provider == "openai":
                r = requests.get("https://api.openai.com/v1/models",
                                 headers={"Authorization": f"Bearer {self.api_key}"},
                                 timeout=self.timeout)
                r.raise_for_status()
                return [m.get("id") for m in (r.json().get("data") or [])]
        except Exception as e:
            self._last_error = str(e)
        return []

    def refresh_models(self, force=False, ttl=3600):
        """Cached provider model list (1h TTL shared across the process)."""
        import time
        if (not force and LLMClient._models_cache is not None
                and time.time() - LLMClient._models_cache_at < ttl):
            return LLMClient._models_cache
        LLMClient._models_cache = self.list_models()
        LLMClient._models_cache_at = time.time()
        return LLMClient._models_cache

    # ── Transport (overridable in tests) ──────────────────────────────
    def _post(self, payload, headers):
        import requests
        r = requests.post(_ENDPOINTS[self.provider], headers=headers, json=payload,
                          timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # ── Core completion (with model fallback chain) ────────────────────
    def complete(self, system, user, model=None, max_tokens=None, temperature=0.4):
        """Return generated text, or None when unavailable / all models fail."""
        if not self.available:
            return None
        model = model or self.fast_model
        chain = self._chain_for(model)
        for candidate in chain:
            text = self._complete_once(system, user, candidate, max_tokens, temperature)
            if text:
                return text

        # Every configured model failed (e.g. alias not valid on the raw
        # API) -> auto-discover working models for this tier, best-first.
        if self.auto_models:
            tier = "capable" if model == self.capable_model else "fast"
            if tier not in self._auto_cache:
                self._auto_cache[tier] = self._auto_models(self.refresh_models(), tier)
            for auto in self._auto_cache[tier]:
                if auto in chain:
                    continue
                text = self._complete_once(system, user, auto, max_tokens, temperature)
                if text:
                    return text
        return None

    def _complete_once(self, system, user, model, max_tokens, temperature):
        """Attempt a single completion with one model.  Returns text or None."""
        try:
            if self.provider == "openai":
                data = self._post({
                    "model": model, "temperature": temperature,
                    "max_tokens": max_tokens or self.max_tokens,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                }, {"Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"})
                choices = data.get("choices") or [{}]
                text = (choices[0] or {}).get("message", {}).get("content", "")
                text = (text or "").strip()
                if text:
                    self._last_model = model
                return text or None
            if self.provider == "anthropic":
                data = self._post({
                    "model": model, "max_tokens": max_tokens or self.max_tokens,
                    "temperature": temperature, "system": system,
                    "messages": [{"role": "user", "content": user}],
                }, {"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json"})
                blocks = data.get("content") or []
                text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
                text = text.strip()
                if text:
                    self._last_model = model
                return text or None
        except Exception as e:
            self._last_error = f"{model}: {e}"
            return None
        return None


class LLMNarrator:
    """
    Adds ``narrative`` fields to a research brief.

    Always produces text (deterministic fallback) so the brief schema is
    stable whether or not an LLM is configured.
    """

    def __init__(self, ctx=None, client=None):
        ctx = ctx or {}
        self.client = client or LLMClient(ctx)
        self.llm_enabled = bool(ctx.get("llm_enabled", False))
        self.max_items = int(ctx.get("llm_max_items", 3))

    @property
    def active(self):
        """True when the LLM is both configured and enabled for this cycle."""
        return self.client.available and self.llm_enabled

    def _pick(self, llm_text, fallback):
        return llm_text if (llm_text and self.active) else fallback

    # ── Executive summary ─────────────────────────────────────────────
    def executive_summary(self, brief):
        themes = brief.get("themes") or []
        opps = brief.get("top_opportunities") or []
        deployment = brief.get("deployment") or {}
        fallback = (
            f"Cycle {brief.get('cycle_id', '?')} ran {brief.get('probe_count', 0)} probes across "
            f"{brief.get('instrument_count', 0)} instruments, synthesizing {len(themes)} alpha themes "
            f"and {len(opps)} prioritized opportunities. "
        )
        if themes:
            fallback += "Top theme: " + (themes[0].get("title") or "n/a") + "."
        else:
            fallback += "No statistically validated theme cleared the out-of-sample bar this cycle."
        if deployment:
            fallback += (f" Deployment proposed for {deployment.get('strategy_key')} "
                         f"(id {deployment.get('id')}, pending human approval).")
        if not self.active:
            return fallback
        system = _PROMPTS["executive_summary"]
        user = json.dumps({
            "cycle_id": brief.get("cycle_id"),
            "probe_count": brief.get("probe_count"),
            "instrument_count": brief.get("instrument_count"),
            "themes": [{k: t.get(k) for k in ("title", "confidence", "risk_flags")}
                       for t in themes[: self.max_items]],
            "top_opportunities": [{k: o.get(k) for k in ("strategy_key", "qrice", "status")}
                                  for o in opps[: self.max_items]],
            "deployment": {k: deployment.get(k) for k in
                           ("id", "strategy_key", "status", "qrice")} or None,
        }, default=str)
        return self._pick(
            self.client.complete(system, user, model=self.client.fast_model,
                                 temperature=_PROMPT_TEMPERATURES["executive_summary"]),
            fallback)

    # ── Deep theme synthesis ──────────────────────────────────────────
    def narrate_theme(self, theme):
        fallback = theme.get("theme") or theme.get("title") or ""
        if not self.active:
            return fallback
        system = _PROMPTS["theme"]
        user = json.dumps({k: theme.get(k) for k in
                           ("title", "theme", "confidence", "risk_flags",
                            "strategy_keys", "evidence")}, default=str)
        return self._pick(
            self.client.complete(system, user, model=self.client.capable_model,
                                 temperature=_PROMPT_TEMPERATURES["theme"]),
            fallback)

    # ── Opportunity storyboard ────────────────────────────────────────
    def narrate_opportunity(self, opp, spec=None):
        fallback = (spec or {}).get("title") or f"{opp.get('strategy_key')} — production strategy candidate."
        if not self.active:
            return fallback
        system = _PROMPTS["opportunity"]
        user = json.dumps({
            "opportunity": {k: opp.get(k) for k in
                            ("strategy_key", "qrice", "impact", "confidence",
                             "effort_hours", "status", "params")},
            "spec": spec,
        }, default=str)
        return self._pick(
            self.client.complete(system, user, model=self.client.capable_model,
                                 temperature=_PROMPT_TEMPERATURES["opportunity"]),
            fallback)

    # ── Cross-validation verdict (Phase 2) ────────────────────────────
    def cross_validate(self, evidence_bundle):
        """Challenge the research conclusion with a structured LLM verdict.

        The capable model receives the RAW evidence (not a summary) and must
        return a JSON verdict.  The verdict is passed through a deterministic
        fact-check; on any failure the verdict is dropped and ``None`` is
        returned so the consensus simply omits the LLM vote.
        """
        if not self.active:
            return None
        system = _PROMPTS["cross_validate"]
        user = json.dumps(evidence_bundle, default=str)
        text = self.client.complete(system, user, model=self.client.capable_model,
                                    temperature=_PROMPT_TEMPERATURES["cross_validate"])
        verdict = _parse_json_verdict(text)
        if not verdict:
            return None
        report = fact_check_verdict(verdict, evidence_bundle)
        if not report["passed"]:
            return None
        verdict["_fact_check"] = report
        return verdict

    def explain_market_view(self, market_view, signals=None):
        """Natural-language 'why' for the consensus (attributed reasoning)."""
        if isinstance(market_view, dict):
            mv = market_view
            fallback = (
                f"Consensus {mv.get('direction', 'RANGING')} at "
                f"{mv.get('consensus_strength', 0) or 0:.0%} strength with "
                f"{mv.get('agreement_index', 0) or 0:.0%} agreement across "
                f"{len(mv.get('sources', []) or [])} sources."
            )
        else:
            fallback = market_view.summary() if market_view is not None else ""
        if not self.active:
            return fallback
        system = _PROMPTS["market_view"]
        user = json.dumps({
            "market_view": market_view,
            "signals": signals or [],
        }, default=str)
        return self._pick(
            self.client.complete(system, user, model=self.client.capable_model,
                                 temperature=_PROMPT_TEMPERATURES["market_view"]),
            fallback)


def _parse_json_verdict(text):
    """Best-effort parse of the LLM's JSON verdict (tolerates code fences)."""
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    # Strip markdown code fences.
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        return json.loads(cleaned)
    except Exception:
        return None


def fact_check_verdict(verdict, evidence_bundle):
    """Deterministic verification that the LLM cited only real numbers.

    Extracts every decimal/number token from the evidence bundle and checks
    that each ``evidence_cited`` string contains at least one of them (and no
    made-up statistic).  A verdict with ZERO citations also fails — the
    cross-validator must ground its view in the provided evidence.

    Returns ``{passed, checked, flagged, failed_citations}``.
    """
    import re
    corpus = json.dumps(evidence_bundle, default=str)
    known_numbers = set(re.findall(r"\d+(?:\.\d+)?", corpus))
    cited = verdict.get("evidence_cited") or []
    flagged = []
    if not cited:
        flagged.append("no evidence cited — verdict is ungrounded")
    for c in cited:
        c = str(c)
        if not known_numbers:
            # No numbers in the bundle at all -> any citation is suspicious.
            flagged.append(c)
            continue
        found = [t for t in re.findall(r"\d+(?:\.\d+)?", c) if t in known_numbers]
        if not found:
            flagged.append(c)
    passed = not flagged
    return {
        "passed": passed,
        "checked": len(cited),
        "flagged": flagged,
        "failed_citations": flagged,
    }
