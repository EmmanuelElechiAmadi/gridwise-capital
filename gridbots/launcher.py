import argparse
import subprocess
import sys
import os
import shutil

# Make sure we can import from the quant_env folder
sys.path.append(os.path.join(os.path.dirname(__file__), 'quant_env'))

from config import Config
from utils.emailer import Emailer

def get_emailer():
    """Return an Emailer instance if email is enabled and configured."""
    if Config.EMAIL_ENABLED:
        try:
            return Emailer(
                Config.EMAIL_SMTP_SERVER,
                Config.EMAIL_PORT,
                Config.EMAIL_USERNAME,
                Config.EMAIL_PASSWORD,
            )
        except Exception as e:
            print(f"Email not available: {e}")
    return None


def run_live():
    from main import App
    from adaptive.updater import AdaptiveUpdater
    from accounts.manager import BrokerAccountManager

    # The engine is multi-account: run the first configured account, or
    # create a default one from Config (backwards-compatible single-account).
    mgr = BrokerAccountManager()
    account = mgr.ensure_default_account()

    app = App(account)
    # Apply any human-approved research deployment (logged by App).
    if app.config.ADAPTIVE_ENABLED:
        updater = AdaptiveUpdater(app.config, app.strategy, app.log)
        updater.start()
    app.run()


def run_backtest():
    from backtest.data_loader import load_yfinance
    from backtest.engine import BacktestEngine
    from strategies.grid_strategy import GridStrategy
    from analysis.performance import compute_metrics
    from analysis.session_analyzer import session_performance
    from analysis.report_generator import generate_report

    data = load_yfinance("GC=F", period="5d", interval="1m")
    engine = BacktestEngine(data, GridStrategy, 10000, spacing=0.1, levels=5, lot=1.0)
    result = engine.run()
    metrics = compute_metrics(result.fills_df, result.equity_df)
    session = session_performance(result.fills_df, result.equity_df)
    report_file = "backtest_report.html"
    generate_report(result.equity_df, result.fills_df, metrics, session, output_file=report_file)
    print(f"Backtest report saved: {report_file}")

    # ---- Email ----
    emailer = get_emailer()
    if emailer:
        emailer.send(
            to=Config.EMAIL_TO,
            subject="Quant Grid Bot – Backtest Report",
            body="<h3>Backtest completed. Report attached.</h3>",
            attachments=[report_file],
        )
def run_optimize():
    from backtest.data_loader import load_yfinance
    from backtest.engine import BacktestEngine
    from analysis.performance import compute_metrics
    from strategies.grid_strategy import GridStrategy
    import pandas as pd

    data = load_yfinance("GC=F", period="5d", interval="1m")
    spacings = [0.05, 0.1, 0.2]
    levels = [3, 5, 7]
    results = []

    for sp in spacings:
        for lv in levels:
            engine = BacktestEngine(data.copy(), GridStrategy, 10000,
                                    spacing=sp, levels=lv, lot=1.0)
            res = engine.run()
            metrics = compute_metrics(res.fills_df, res.equity_df)
            metrics['spacing'] = sp
            metrics['levels'] = lv
            results.append(metrics)

    df = pd.DataFrame(results).sort_values('sharpe_ratio', ascending=False)
    print(df)
    csv_file = "optimization_results.csv"
    df.to_csv(csv_file, index=False)

    # ---- Email ----
    emailer = get_emailer()
    if emailer:
        emailer.send(
            to=Config.EMAIL_TO,
            subject="Quant Grid Bot – Optimization Results",
            body="<h3>Optimization run completed. Results attached.</h3>",
            attachments=[csv_file],
        )
def run_report():
    from analysis.trade_logger import TradeLogger
    from analysis.performance import compute_metrics
    from analysis.session_analyzer import session_performance
    from analysis.report_generator import generate_report
    import pandas as pd

    db_path = "quant_env/trades.db"
    logger = TradeLogger(db_path)
    fills_rows = logger.get_fills()
    if not fills_rows:
        print("No trades yet – live report empty.")
        logger.close()
        return

    fills_df = pd.DataFrame(fills_rows, columns=['id','account_id','timestamp','symbol','side','price','volume','pnl'])
    equity_rows = logger.get_equity_curve()
    equity_df = pd.DataFrame(equity_rows, columns=['timestamp','equity'])
    metrics = compute_metrics(fills_df, equity_df)
    session = session_performance(fills_df, equity_df)
    report_file = "live_report.html"
    generate_report(equity_df, fills_df, metrics, session, output_file=report_file)
    logger.close()
    print(f"Live report saved: {report_file}")

    emailer = get_emailer()
    if emailer:
        # Also attach a backup of the trade database
        backup_db = "trades_backup.db"
        shutil.copy(db_path, backup_db)
        emailer.send(
            to=Config.EMAIL_TO,
            subject="Quant Grid Bot – Live Performance Report",
            body="<h3>Live performance report attached.</h3>",
            attachments=[report_file, backup_db],
        )

def run_walkforward():
    from backtest.data_loader import load_yfinance
    from strategies.grid_strategy import GridStrategy
    from analysis.walkforward import walkforward_analysis

    data = load_yfinance("GC=F", period="1mo", interval="1h")
    if data is None or data.empty:
        print("ERROR: No data available for walkforward analysis.")
        return
    param_grid = {'spacing': [0.1, 0.2], 'levels': [3, 5]}
    wf_df = walkforward_analysis(data, GridStrategy, param_grid,
                                 window_size=500, step_size=500,
                                 initial_capital=10000, lot=1.0)
    if wf_df.empty:
        print("NOT ENOUGH DATA: walkforward requires at least {} bars but only {} available.".format(
            500 + 500, len(data)))
        return
    print(wf_df)
    wf_df.to_csv('walkforward_results.csv', index=False)


def run_bridge():
    """Launch the MT5 bridge server (reads EA JSON files, exposes REST API)."""
    import threading, time
    bridge_path = os.path.join(os.path.dirname(__file__), 'live', 'mt5_bridge_server.py')
    env = os.environ.copy()
    # Load .env file so MT5_FILES_DIR is available to the bridge process
    env_file = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, val = line.partition('=')
                    env.setdefault(key.strip(), val.strip())
    proc = subprocess.Popen(
        [sys.executable, bridge_path],
        cwd=os.path.dirname(__file__),
        env=env,
    )
    return proc


def run_dashboard():
    """Launch the MT5 bridge server + web dashboard together."""
    import time

    # Load .env so BRIDGE_URL / MT5_FILES_DIR are in our environment
    env_file = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, val = line.partition('=')
                    os.environ.setdefault(key.strip(), val.strip())

    # Start bridge server in background
    bridge_proc = run_bridge()
    print("🌉 MT5 Bridge server starting on port 8080…")
    time.sleep(2)  # give it a moment to bind

    dashboard_path = os.path.join(os.path.dirname(__file__), 'quant_env', 'dashboard', 'app.py')
    try:
        # Use subprocess so __file__ resolves correctly inside app.py
        subprocess.run([sys.executable, dashboard_path], cwd=os.path.dirname(__file__))
    finally:
        bridge_proc.terminate()
        bridge_proc.wait()
        print("🛑 MT5 Bridge server stopped.")


def run_train_ml():
    """
    Train the regime classification ML model using historical YFinance data.
    Saves model.pkl to quant_env/ml/ for use by RegimeAdapter in live mode.
    """
    from ml.regime_model import RegimeClassifier
    from backtest.data_loader import load_yfinance

    print("Downloading training data (GC=F, 3mo, 1h)...")
    data = load_yfinance("GC=F", period="3mo", interval="1h")
    if data is None or data.empty:
        print("ERROR: No data downloaded. Check internet / symbol.")
        sys.exit(1)

    print(f"Loaded {len(data)} bars. Training regime classifier...")
    clf = RegimeClassifier(lookback=20, threshold=25)
    clf.train(data)

    model_dir = os.path.join(os.path.dirname(__file__), 'quant_env', 'ml')
    os.makedirs(model_dir, exist_ok=True)
    model_path = os.path.join(model_dir, 'model.pkl')
    clf.save(model_path)
    print(f"Model saved to {model_path}")
    print("Done. Set ML_ENABLED=True in config to use RegimeAdapter in live mode.")


def run_research(interval_minutes=None, once=False, llm=False, deploy=False,
                 approve=None, symbols=None, auto_approve=None, deploy_strategy=None,
                 force_approve=None, void=None, advise=False, shadow=None):
    """
    Run the InsightForge-for-Quant agent team.

    - Default: run one full research cycle and print the brief.
    - ``interval_minutes``: keep running the cycle on a schedule.
    - ``llm``: enable the optional LLM narrative layer (needs LLM_API_KEY).
    - ``deploy``: propose the top opportunity for human-gated deployment.
    - ``auto_approve``: auto-approve after N consistent cycles (opt-in).
    - ``approve``: approve a pending deployment by id (human gate; blocked by
      quality gates unless the human uses --force-approve).
    - ``force_approve``: FORCE-approve a deployment by id (auditable override).
    - ``void``: void a deployment by id (never applied by the engine).
    - ``advise``: print the TradeExecutionAdvisor recommendation.
    - ``shadow``: forward-test an approved deployment by id.
    - ``deploy_strategy``: propose the best opportunity for a specific strategy.
    - ``symbols``: comma-separated corpus, e.g. "GC=F,SI=F,CL=F".
    """
    sys.path.append(os.path.join(os.path.dirname(__file__), 'quant_env'))
    import json
    from intelligence.ledger import OUTPUT_DIR

    # ── FORCE approve (bypasses quality gates, auditable) ──────────────
    if force_approve:
        from intelligence.deploy import DeploymentManager
        rec = DeploymentManager().approve(force_approve, force=True)
        if rec:
            print(f"✅ FORCE-approved deployment {rec['id']} for "
                  f"{rec['strategy_key']} (approved_by={rec['approved_by']})")
        else:
            print(f"❌ No deployment with id '{force_approve}'.")
        return

    # ── Void a deployment ──────────────────────────────────────────────
    if void:
        from intelligence.deploy import DeploymentManager
        rec = DeploymentManager().void(void, reason="voided via CLI")
        if rec:
            print(f"🗑️  Voided deployment {rec['id']} — never applied by the engine.")
        else:
            print(f"❌ No deployment with id '{void}'.")
        return

    # ── Trade advisor recommendation (no research run needed) ─────────
    if advise:
        from intelligence.consensus import ConsensusEngine
        from intelligence.consensus.sources import collect_all_signals
        from intelligence.ledger import OpportunityLedger
        from intelligence.execution import TradeExecutionAdvisor
        ledger = OpportunityLedger.load()
        ctx = {"max_bars": 600, "probe_limit": 2}
        symbols_str = symbols or getattr(Config, "RESEARCH_SYMBOLS", "GC=F")
        sym = symbols_str.split(",")[0]
        signals = collect_all_signals(ctx=ctx, ledger=ledger,
                                      project_root=os.path.dirname(os.path.dirname(
                                          os.path.abspath(__file__))),
                                      symbol=sym)
        view = ConsensusEngine().fuse(signals, symbol=sym, cycle_id="cli-advise")
        rec = TradeExecutionAdvisor().advise(view, price=None, symbol=sym)
        print("MARKET VIEW (consensus)")
        print(f"  direction={view.direction}  value={view.direction_value:+.2f}  "
              f"agreement={view.agreement_index:.0%}  "
              f"strength={view.consensus_strength:.0%}")
        print("  per-source contributions:")
        for c in view.contributions:
            print(f"    - {c['source']}: {c['direction']} contrib={c['contribution']:+.3f}")
        print("RECOMMENDATION")
        print(f"  action={rec.action}  side={rec.side}  confidence={rec.confidence:.0%}  "
              f"risk={rec.risk_fraction:.1%}  lot={rec.suggested_lot}")
        print("  reason chain:")
        for step in rec.reason_chain:
            print(f"    • {step['detail']}")
        return

    # ── Shadow forward-test a deployment ───────────────────────────────
    if shadow:
        from intelligence.deploy import DeploymentManager
        from intelligence.execution import ShadowForwardTester
        from intelligence.data import load_cached_history
        dep = next((r for r in DeploymentManager().list()
                    if r["id"] == shadow), None)
        if dep is None:
            print(f"❌ No deployment with id '{shadow}'.")
            return
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sym = symbols.split(",")[0] if symbols else \
            getattr(Config, "RESEARCH_SYMBOLS", "GC=F").split(",")[0]
        history = load_cached_history(project_root, sym)
        if history is None:
            print(f"❌ No cached history for {sym} — refresh data first.")
            return
        report = ShadowForwardTester().test(dep, history)
        print(f"SHADOW FORWARD TEST for deployment {shadow}")
        print(f"  status={report['status']}  window_bars={report.get('window_bars')}")
        for g in report.get("gates", []):
            print(f"    - {g['gate']}: {'PASS' if g['passed'] else 'FAIL'} "
                  f"(value={g['value']}, threshold={g['threshold']})")
        print(f"  reason: {report.get('reason')}")
        return

    # ── Propose a specific strategy's best opportunity (no research run) ─
    if deploy_strategy:
        from intelligence.ledger import OpportunityLedger
        from intelligence.deploy import DeploymentManager
        ledger = OpportunityLedger.load()
        candidates = [o for o in ledger.opportunities
                      if o.strategy_key == deploy_strategy]
        if not candidates:
            print(f"❌ No opportunities for strategy '{deploy_strategy}' in the ledger.")
            return
        best = max(candidates, key=lambda o: o.qrice())
        best.status = "proposed"
        ledger.save()
        rec = DeploymentManager().propose(best, note=f"proposed via --deploy-strategy {deploy_strategy}")
        print(f"✅ Proposed deployment {rec['id']} for {deploy_strategy} "
              f"(qRICE {rec['qrice']:.3f}) — approve with: "
              f"python3 launcher.py research --approve {rec['id']}")
        return

    # ── Human-gated approval (no research run needed) ─────────────────
    if approve:
        from intelligence.deploy import DeploymentManager
        dm = DeploymentManager()
        rec = dm.approve(approve)
        if rec:
            if rec["status"] == "blocked_by_gates":
                print(f"🚫 Deployment {rec['id']} BLOCKED by quality gates:")
                for g in (rec.get("quality") or {}).get("gates", []):
                    print(f"   - {g['gate']}: value={g['value']} "
                          f"threshold={g['threshold']} "
                          f"{'✅' if g['passed'] else '❌'}")
                print("   Force-approve with: python3 launcher.py research "
                      f"--force-approve {rec['id']}  (auditable override)")
            else:
                print(f"✅ Approved deployment {rec['id']} for {rec['strategy_key']}")
                print(f"   params: {rec['params']}")
                print("   Applied to the engine on the next bot start.")
        else:
            pending = dm.pending()
            print(f"❌ No deployment with id '{approve}'. Pending deployments:")
            for p in pending:
                print(f"   - {p['id']}  {p['strategy_key']}  (proposed {p['proposed_at']})")
        return

    from intelligence.coordinator import CoordinatorAgent
    from intelligence.scheduler import ResearchScheduler

    llm_on = llm or getattr(Config, "RESEARCH_LLM_ENABLED", False)
    symbols_str = symbols or getattr(Config, "RESEARCH_SYMBOLS", "GC=F")
    auto_cycles = int(auto_approve or getattr(Config, "RESEARCH_AUTO_APPROVE_CYCLES", "0"))
    deploy_on = deploy or auto_cycles > 0

    if interval_minutes:
        # Continuous mode: run in-process via the singleton scheduler.
        scheduler = ResearchScheduler.get_instance(
            Config, interval_minutes=interval_minutes,
            ctx={"llm_enabled": llm_on, "symbols": symbols_str,
                 "auto_deploy_top": deploy_on,
                 "auto_approve_cycles": auto_cycles})
        print(f"🤖 Autonomous research loop starting (cycle every {interval_minutes} min, "
              f"symbols={symbols_str}, auto-approve={auto_cycles or 'off'}). Ctrl-C to stop.")
        scheduler.start()
        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            scheduler.stop()
            print("\n🛑 Research loop stopped.")
        return

    # Single cycle
    ctx = {"llm_enabled": llm_on, "symbols": symbols_str,
           "auto_deploy_top": deploy_on, "auto_approve_cycles": auto_cycles}
    coordinator = CoordinatorAgent(ctx)
    brief, ledger = coordinator.run_cycle()
    brief_path = os.path.join(OUTPUT_DIR, "research_brief.json")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(brief_path, "w") as f:
        json.dump(brief, f, indent=2, default=str)
    print("=" * 72)
    print("  INSIGHTFORGE FOR QUANT — research cycle complete")
    print("=" * 72)
    print(f"  cycle     : {brief['cycle_id']}")
    print(f"  probes    : {brief['probe_count']}")
    print(f"  themes    : {len(brief.get('themes', []))}")
    print(f"  narrative : {brief.get('narrative', '')[:220]}…")
    layer = brief.get("narrative_layer") or {}
    print(f"  llm layer : enabled={layer.get('enabled')} "
          f"provider={layer.get('provider')} available={layer.get('available')} "
          f"fast={layer.get('fast_model')} capable={layer.get('capable_model')} "
          f"answered_by={layer.get('last_model')}")
    print("  top opportunities:")
    for o in brief.get("top_opportunities", []):
        print(f"    - {o['strategy_key']}  qRICE={o['qrice']:.3f}  [{o['status']}]")
    mv = brief.get("market_view")
    if mv:
        print("  market view:")
        print(f"    direction={mv.get('direction')}  "
              f"value={mv.get('direction_value', 0):+.2f}  "
              f"agreement={mv.get('agreement_index', 0):.0%}  "
              f"strength={mv.get('consensus_strength', 0):.0%}")
        for c in mv.get("contributions", []):
            print(f"      - {c.get('source')}: {c.get('direction')} "
                  f"contrib={c.get('contribution', 0):+.3f}")
        if mv.get("disagreements"):
            for d in mv.get("disagreements", []):
                print(f"      ✗ dissent: {d.get('source')} ({d.get('direction')})")
    if brief.get("market_view_narrative"):
        print(f"  why: {brief.get('market_view_narrative')[:220]}…")
    deployment = brief.get("deployment")
    if deployment:
        status = deployment.get("status")
        action = ("auto-approved after consistent cycles"
                  if status == "approved"
                  else f"approve with: python3 launcher.py research --approve {deployment['id']}")
        print(f"  deployment: {deployment['id']}  {deployment['strategy_key']}  "
              f"[{status}]  ({deployment.get('consistent_cycles', 1)} cycles)  -> {action}")
    print(f"  ledger    : {ledger.path}")
    print(f"  brief     : {brief_path}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Quant Grid Bot Launcher (with Email & ML)")
    parser.add_argument('mode', choices=['live', 'backtest', 'optimize', 'report', 'walkforward', 'train_ml', 'dashboard', 'research'], help="Mode to run: live trading, backtest, optimization, report generation, walk-forward analysis, train ML regime classifier, launch web dashboard, or run the autonomous research team")
    parser.add_argument('--interval', type=int, default=None, help="Research mode: minutes between cycles (continuous loop)")
    parser.add_argument('--once', action='store_true', help="Research mode: run a single cycle (default)")
    parser.add_argument('--llm', action='store_true', help="Research mode: enable the LLM narrative layer")
    parser.add_argument('--deploy', action='store_true', help="Research mode: propose the top opportunity for human-gated deployment")
    parser.add_argument('--auto-approve', type=int, default=None, help="Research mode: auto-approve a deployment after N consistent cycles (0 = human gate only)")
    parser.add_argument('--deploy-strategy', default=None, help="Research mode: propose the best opportunity for a specific strategy (e.g. breakout_strategy)")
    parser.add_argument('--approve', default=None, help="Research mode: approve a pending deployment by id (human gate)")
    parser.add_argument('--force-approve', default=None, help="Research mode: FORCE-approve a deployment by id, bypassing quality gates (auditable)")
    parser.add_argument('--void', default=None, help="Research mode: void a deployment by id (never applied by the engine)")
    parser.add_argument('--advise', action='store_true', help="Research mode: print the TradeExecutionAdvisor recommendation for the current consensus")
    parser.add_argument('--shadow', default=None, help="Research mode: forward-test an approved deployment by id on a held-out recent window")
    parser.add_argument('--symbols', default=None, help="Research mode: comma-separated corpus, e.g. GC=F,SI=F,CL=F")
    args = parser.parse_args()

    if args.mode == 'live':
        run_live()
    elif args.mode == 'backtest':
        run_backtest()
    elif args.mode == 'optimize':
        run_optimize()
    elif args.mode == 'report':
        run_report()
    elif args.mode == 'walkforward':
        run_walkforward()
    elif args.mode == 'train_ml':
        run_train_ml()
    elif args.mode == 'dashboard':
        run_dashboard()
    elif args.mode == 'research':
        run_research(interval_minutes=args.interval, once=args.once, llm=args.llm,
                     deploy=args.deploy, approve=args.approve, symbols=args.symbols,
                     auto_approve=args.auto_approve, deploy_strategy=args.deploy_strategy,
                     force_approve=args.force_approve, void=args.void,
                     advise=args.advise, shadow=args.shadow)
