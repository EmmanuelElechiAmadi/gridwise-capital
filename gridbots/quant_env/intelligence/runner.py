"""
runner — CLI entry point for the InsightForge quant research cycle.

Usage:
    cd gridbots
    python -m quant_env.intelligence.runner                # full cycle
    python -m quant_env.intelligence.runner --max-bars 800 --probe-limit 2
    python -m quant_env.intelligence.runner --json brief.json
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intelligence.coordinator import CoordinatorAgent  # noqa: E402
from intelligence.ledger import OUTPUT_DIR  # noqa: E402

DEFAULT_BRIEF = os.path.join(OUTPUT_DIR, "research_brief.json")


def _render(brief) -> str:
    lines = [
        "=" * 72,
        "  INSIGHTFORGE FOR QUANT — autonomous research cycle complete",
        "=" * 72,
        f"  cycle      : {brief['cycle_id']}",
        f"  generated  : {brief['generated_at']}",
        "",
        "  AGENT TEAM (quant professional replacements)",
    ]
    for member in brief["team"]:
        findings = member["findings"]
        probes = findings.get("probes")
        themes = findings.get("themes")
        lines.append(f"    • {member['role']}")
        lines.append(f"        replaces: {member['replaces']}")
        if isinstance(probes, list):
            lines.append(f"        probes run: {len(probes)}")
        if isinstance(themes, list):
            lines.append(f"        alpha themes: {len(themes)}")

    lines.append("")
    lines.append("  TOP OPPORTUNITIES (qRICE)")
    for i, opp in enumerate(brief.get("top_opportunities", []), 1):
        lines.append(
            f"    {i}. {opp['strategy_key']}  qRICE={opp['qrice']:.3f}  "
            f"conf={opp['confidence']:.2f}  impact={opp['impact']:.2f}  "
            f"effort={opp['effort_hours']:.0f}h  [{opp['status']}]"
        )

    themes = brief.get("themes", [])
    if themes:
        lines.append("")
        lines.append("  ALPHA THEMES")
        for t in themes:
            lines.append(f"    - {t['title']}  conf={t['confidence']:.2f}")
            if t["risk_flags"]:
                lines.append(f"        flags: {', '.join(t['risk_flags'])}")

    market_view = brief.get("market_view")
    if market_view:
        lines.append("")
        lines.append("  MARKET VIEW (consensus)")
        lines.append(
            f"    direction   : {market_view.get('direction')}  "
            f"value={market_view.get('direction_value', 0):+.2f}")
        lines.append(
            f"    agreement   : {market_view.get('agreement_index', 0):.0%}  "
            f"strength={market_view.get('consensus_strength', 0):.0%}")
        lines.append("    sources:")
        for c in market_view.get("contributions", []):
            lines.append(
                f"      - {c.get('source')}: {c.get('direction')} "
                f"contrib={c.get('contribution', 0):+.3f} "
                f"(strength {c.get('strength', 0):.0%}, conf {c.get('confidence', 0):.0%})")
        if market_view.get("disagreements"):
            lines.append("    dissenting voices:")
            for d in market_view.get("disagreements", []):
                lines.append(f"      - {d.get('source')} ({d.get('direction')})")

    news_analysis = brief.get("news_analysis")
    if news_analysis:
        lines.append("")
        lines.append("  NEWS DESK (Phase 5 — trading headlines → Sonnet verdict → Kronos/RF check)")
        verdict = news_analysis.get("news_verdict") or {}
        conf = news_analysis.get("confirmation") or {}
        lines.append(f"    status      : {news_analysis.get('status')}  "
                     f"headlines={news_analysis.get('article_count', 0)}  "
                     f"outlets={', '.join(news_analysis.get('outlets', []) or []) or '—'}")
        lines.append(f"    news verdict: {verdict.get('direction', '—')}  "
                     f"strength={float(verdict.get('strength', 0) or 0):.0%}  "
                     f"confidence={float(verdict.get('confidence', 0) or 0):.0%}")
        if verdict.get("key_themes"):
            lines.append(f"    key themes  : {', '.join(verdict.get('key_themes', []))}")
        if conf.get("available"):
            status = "CONFIRMED" if conf.get("agrees") else "DIVERGES"
            lines.append(f"    Kronos+RF   : {conf.get('model_direction')} "
                         f"({conf.get('model_value', 0):+.2f}) — news {status}")
        if verdict.get("evidence_cited"):
            lines.append("    grounded on :")
            for c in verdict.get("evidence_cited", []):
                lines.append(f"      - {c}")

    news_narrative = brief.get("news_narrative")
    if news_narrative:
        lines.append("")
        lines.append("  NEWS DESK NARRATIVE")
        lines.append(f"    {news_narrative}")
    mv_narrative = brief.get("market_view_narrative")
    if mv_narrative:
        lines.append("")
        lines.append("  WHY (market view narrative)")
        lines.append(f"    {mv_narrative}")

    narrative = brief.get("narrative")
    if narrative:
        lines.append("")
        lines.append("  CQO NARRATIVE")
        lines.append(f"    {narrative}")

    layer = brief.get("narrative_layer") or {}
    if layer:
        lines.append("")
        lines.append(f"  NARRATIVE LAYER: enabled={layer.get('enabled')} "
                     f"provider={layer.get('provider') or 'none'} "
                     f"available={layer.get('available')}")

    lines.append("")
    lines.append("=" * 72)
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="insightforge",
        description="Run the InsightForge-for-Quant autonomous research cycle.")
    parser.add_argument("--max-bars", type=int, default=1500,
                        help="max bars of cached history to probe")
    parser.add_argument("--probe-limit", type=int, default=4,
                        help="max parameter variants probed per strategy")
    parser.add_argument("--top-n", type=int, default=3,
                        help="how many opportunities to prioritize")
    parser.add_argument("--ledger", default=None,
                        help="path to the opportunity ledger JSON")
    parser.add_argument("--json", default=DEFAULT_BRIEF,
                        help="where to write the research brief JSON")
    parser.add_argument("--llm", action="store_true",
                        help="enable the optional LLM narrative layer "
                             "(requires LLM_API_KEY / LLM_PROVIDER env vars)")
    parser.add_argument("--news", action="store_true",
                        help="enable the News Desk (fetches trading headlines "
                             "from public RSS outlets)")
    parser.add_argument("--symbols", default="GC=F",
                        help="comma-separated symbol corpus to probe, e.g. GC=F,SI=F,CL=F")
    parser.add_argument("--deploy-top", action="store_true",
                        help="propose the top opportunity for human-gated deployment")
    parser.add_argument("--news-use-sample", action="store_true",
                        help="use the deterministic OFFLINE news corpus "
                             "(air-gapped demos; clearly labelled sample)")
    parser.add_argument("--news-max-articles", type=int, default=20,
                        help="max curated headlines handed to Claude Sonnet")
    parser.add_argument("--models", action="store_true",
                        help="list the LLM models this key can access, then exit")
    parser.add_argument("--quiet", action="store_true",
                        help="skip printing the human summary")
    args = parser.parse_args(argv)

    if args.models:
        from intelligence.llm import LLMClient
        client = LLMClient({"llm_enabled": True})
        print(f"provider        : {client.provider}  available={client.available}")
        print(f"configured fast : {client.fast_model}  chain={client.fast_chain}")
        print(f"configured capab: {client.capable_model}  chain={client.capable_chain}")
        models = client.refresh_models(force=True) or []
        print("accessible models:")
        for m in models:
            print(f"  - {m}")
        print(f"auto fast      : {client._pick_auto_model(models, 'fast')}")
        print(f"auto capable   : {client._pick_auto_model(models, 'capable')}")
        return 0

    ctx = {
        "max_bars": args.max_bars,
        "probe_limit": args.probe_limit,
        "top_n": args.top_n,
        "ledger_path": args.ledger,
        "llm_enabled": args.llm,
        "symbols": args.symbols,
        "auto_deploy_top": args.deploy_top,
        "news_enabled": args.news,
        "news_use_sample": args.news_use_sample,
        "news_max_articles": max(1, args.news_max_articles),
    }
    coordinator = CoordinatorAgent(ctx)
    brief, ledger = coordinator.run_cycle()

    os.makedirs(os.path.dirname(args.json), exist_ok=True)
    with open(args.json, "w") as f:
        json.dump(brief, f, indent=2, default=str)

    if not args.quiet:
        print(_render(brief))
        print(f"\n  Ledger saved: {ledger.path}")
        print(f"  Brief saved:  {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
