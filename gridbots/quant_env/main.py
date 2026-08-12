"""
Multi-account trading engine.

Each account (broker connection) gets its own App instance (connector,
strategy, risk manager).  GridBotManager orchestrates all running bots.
"""

import time
import signal
import sys
import os
import threading
from typing import Dict, List, Optional

sys.path.append(os.path.dirname(__file__))

from config import Config
from core.connector import create_connector
from core.risk_manager import RiskManager
from core.logger import setup_logger
from strategies.grid_strategy import GridStrategy
from analysis.trade_logger import TradeLogger
from utils.notifications import TelegramNotifier
from utils.config_loader import load_config
from ml.regime_adapter import RegimeAdapter
from ml.kronos import (
    KronosRegimeAdapter,
    KronosRiskMetrics,
    MetaRegimeAdapter,
    IncrementalInferenceEngine,
)
from optimization.portfolio_optimizer import KronosPortfolioOptimizer
from adaptive.updater import AdaptiveUpdater
from intelligence.scheduler import ResearchScheduler

from accounts.models import BrokerAccount, ConnectionStatus
from accounts.manager import BrokerAccountManager


# ═══════════════════════════════════════════════════════════════════════
#  Single-account App
# ═══════════════════════════════════════════════════════════════════════

class App:
    """
    Main trading application for ONE broker account.

    Manages lifecycle of connector, strategy, ML regime adapter, adaptive
    walk‑forward updater, and graceful shutdown.
    """

    def __init__(self, account: BrokerAccount):
        self.account = account
        self.config = Config
        self.log = setup_logger(
            log_file=os.path.join(os.path.dirname(__file__),
                                  f'../logs/quantbot_{account.id}.log')
        )
        self.connector = create_connector(account)
        self.risk = RiskManager(self.config, self.log)
        self.logger = TradeLogger(account_id=account.id)
        # Create the strategy selected for this account (default: grid_strategy)
        from strategies.registry import get_class as _get_strategy_class
        _strategy_key = account.trading_config.get('strategy', 'grid_strategy')
        _strategy_cls = _get_strategy_class(_strategy_key) or GridStrategy
        self.strategy = _strategy_cls(self.connector, self.config, self.log)
        self.strategy.logger = self.logger

        # Human-gated deployment: apply approved research-team params to the
        # live strategy (only records a human explicitly approved via the
        # dashboard or `launcher.py research --approve <id>`).
        self._last_drawdown_pct = 0.0
        self._peak_equity = 0.0
        self._kill_triggered = False
        self._deployed_direction = None
        try:
            from intelligence.deploy import DeploymentManager
            dep = DeploymentManager().approved_for(_strategy_key)
            if dep:
                applied = DeploymentManager.apply_to_strategy(self.strategy, dep)
                self.log.info(
                    f"Applied approved research deployment {dep['id']} to "
                    f"{_strategy_key} (params: {', '.join(applied) or 'none'})")
        except Exception as e:
            self.log.warning(f"Research deployment apply failed: {e}")

        env = load_config()
        self.notifier = None
        if env.get('TELEGRAM_TOKEN'):
            self.notifier = TelegramNotifier(
                env['TELEGRAM_TOKEN'], env['TELEGRAM_CHAT_ID']
            )

        self.running = True

        # ── ML regime adapter (RF-based, Kronos forecast, or Meta blend) ──
        kronos_enabled = getattr(self.config, "KRONOS_ENABLED", False)
        blend_enabled = getattr(self.config, "KRONOS_BLEND_ENABLED", False)

        try:
            if kronos_enabled and blend_enabled:
                # Meta-adapter blends Kronos + RF by confidence
                kronos_adapter = KronosRegimeAdapter(self.config, self.log)
                rf_adapter = RegimeAdapter(self.config)
                # Use IncrementalInferenceEngine to avoid re-encoding full context on every refresh
                if getattr(self.config, "KRONOS_INCREMENTAL_ENABLED", True):
                    kronos_predictor = kronos_adapter._predictor or getattr(kronos_adapter, '_init_predictor', lambda: None)
                    if kronos_adapter._predictor is not None and kronos_adapter._predictor.is_available():
                        k_engine = IncrementalInferenceEngine(kronos_adapter._predictor, cache_size=128)
                        kronos_adapter._incremental_engine = k_engine
                        self.log.info("IncrementalInferenceEngine attached to Kronos adapter")
                self.regime_adapter = MetaRegimeAdapter(
                    self.config, kronos_adapter, rf_adapter, self.log
                )
                self.log.info("Using MetaRegimeAdapter (Kronos + RF blended by confidence)")
            elif kronos_enabled:
                self.regime_adapter = KronosRegimeAdapter(self.config, self.log)
                # Attach IncrementalInferenceEngine to avoid re-encoding full context on every refresh
                if getattr(self.config, "KRONOS_INCREMENTAL_ENABLED", True):
                    kronos_adapter = self.regime_adapter
                    kronos_adapter._init_predictor()
                    if kronos_adapter._predictor is not None and kronos_adapter._predictor.is_available():
                        k_engine = IncrementalInferenceEngine(kronos_adapter._predictor, cache_size=128)
                        kronos_adapter._incremental_engine = k_engine
                        self.log.info("IncrementalInferenceEngine attached to Kronos adapter")
                self.log.info("Using Kronos foundation model for regime adaptation")
            else:
                self.regime_adapter = RegimeAdapter(self.config)
        except Exception as e:
            self.log.warning(
                f"Kronos adapter init failed ({e}) — falling back to RF RegimeAdapter"
            )
            self.regime_adapter = RegimeAdapter(self.config)
        if (getattr(self.config, "ML_ENABLED", False) or kronos_enabled):
            self.strategy.regime_adapter = self.regime_adapter

        # ── Kronos Risk Metrics (VaR/CVaR) ──────────────────────────────
        self.kronos_risk = None
        self._kronos_predictor = None  # hold ref for risk metric extraction
        if getattr(self.config, "KRONOS_RISK_METRICS_ENABLED", False) and kronos_enabled:
            kronos_adapt = self.regime_adapter
            if blend_enabled and hasattr(self.regime_adapter, '_kronos_adapter'):
                kronos_adapt = self.regime_adapter._kronos_adapter
            # Store a reference to the underlying predictor for raw sample extraction
            predictor_ref = getattr(kronos_adapt, '_predictor', None)
            if predictor_ref is not None and predictor_ref.is_available():
                self._kronos_predictor = predictor_ref
                self.kronos_risk = KronosRiskMetrics(config=self.config)
                self.log.info("KronosRiskMetrics initialized for VaR/CVaR position sizing")
                # Apply initial risk adjustment to lot size
            else:
                self.log.warning("KronosRiskMetrics: Kronos predictor not available")

        # ── Portfolio Optimizer (multi-symbol) ──────────────────────────
        self.portfolio_optimizer = None
        kronos_symbols = getattr(self.config, "KRONOS_SYMBOLS", None)
        if kronos_symbols and kronos_enabled:
            try:
                symbols = [s.strip() for s in kronos_symbols.split(",") if s.strip()]
                if len(symbols) > 0:
                    # Create a KronosRegimeAdapter or reuse existing for multi-symbol
                    kronos_adapt = self.regime_adapter
                    if blend_enabled and hasattr(self.regime_adapter, '_kronos_adapter'):
                        kronos_adapt = self.regime_adapter._kronos_adapter
                    self.portfolio_optimizer = KronosPortfolioOptimizer(
                        adapter=kronos_adapt,
                        symbols=symbols,
                        config=self.config,
                        logger=self.log,
                    )
                    self.log.info(f"KronosPortfolioOptimizer initialized for {symbols}")
            except Exception as exc:
                self.log.warning(f"Failed to init KronosPortfolioOptimizer: {exc}")

        # ── Portfolio allocation tracker (blended from optimizer) ───────
        self._last_portfolio_allocs: Dict[str, float] = {}

        # ── Adaptive walk‑forward updater ──────────────────────────────
        self.adaptive_updater = AdaptiveUpdater(
            self.config, self.strategy, self.log
        )

        # ── Autonomous research loop (InsightForge for Quant) ─────────
        # Singleton-guarded: only one research thread runs per process.
        self.research_scheduler = None
        if getattr(self.config, "RESEARCH_ENABLED", False):
            try:
                self.research_scheduler = ResearchScheduler.get_instance(
                    self.config, self.log
                )
                self.log.info("Autonomous research loop enabled (ResearchScheduler).")
            except Exception as e:
                self.log.warning(f"ResearchScheduler init failed: {e}")

    # ── Lifecycle ──────────────────────────────────────────────────────

    def run(self):
        """Main trading loop."""
        self.log.info(f"Starting QuantBot for account {self.account.id} – press Ctrl-C to stop.")
        self.regime_adapter.start()
        self.adaptive_updater.start()
        if self.research_scheduler is not None:
            self.research_scheduler.start()
        self.strategy.on_start()

        try:
            while self.running:
                self._sync_regime_params()
                self._process_tick()
                self._process_account()
                self._execution_guard()      # consensus kill-switch + hot-apply
                time.sleep(0.5)
        finally:
            self._shutdown_cleanly()

    # ── Internal tick / account processing ─────────────────────────────

    def _sync_regime_params(self):
        """Pull grid parameters from RegimeAdapter if ML is active."""
        if (self.regime_adapter.enabled and
                self.regime_adapter.regime != RegimeAdapter.UNKNOWN):
            # Only grid strategies expose spacing/levels
            if hasattr(self.strategy, 'spacing') and hasattr(self.strategy, 'levels'):
                self.strategy.spacing = self.regime_adapter.spacing
                self.strategy.levels = self.regime_adapter.levels

        # ── Portfolio optimizer: sync per-symbol Kronos forecasts (Item 6) ──
        if self.portfolio_optimizer is not None:
            try:
                self.portfolio_optimizer.update_from_adapter()
            except Exception as exc:
                self.log.warning(f"Portfolio optimizer update failed: {exc}")

        # ── Kronos Risk Metrics: extract VaR/CVaR and apply position sizing (Item 10) ──
        if self.kronos_risk is not None and self.kronos_risk.enabled:
            try:
                self._apply_kronos_risk_sizing()
            except Exception as exc:
                self.log.warning(f"Kronos risk sizing failed: {exc}")

    # ── Execution guard (Phase 3): consensus kill-switch + hot-apply ───
    _GUARD_EVERY = 60          # check every ~30s of the 0.5s loop
    _guard_counter = 0
    _hot_applied_sigs = set()

    def _execution_guard(self):
        """Periodically enforce kill-switches and hot-apply approved params."""
        self._guard_counter += 1
        if self._guard_counter < self._GUARD_EVERY:
            return
        self._guard_counter = 0

        # 1) Load the latest consensus MarketView (if any).
        market_view = None
        try:
            from intelligence.ledger import OpportunityLedger
            views = list(OpportunityLedger.load().market_views or [])
            market_view = views[-1] if views else None
        except Exception:
            pass

        # 2) Kill-switch: drawdown / consensus collapse / regime flip.
        try:
            from intelligence.execution.live_apply import evaluate_kill_switches
            dd = float(getattr(self, "_last_drawdown_pct", 0.0) or 0.0)
            deployed_dir = getattr(self, "_deployed_direction", None)
            flatten, reasons = evaluate_kill_switches(
                market_view=market_view, current_drawdown_pct=dd,
                deployed_direction=deployed_dir)
            if flatten and not getattr(self, "_kill_triggered", False):
                self.log.warning(
                    "🛑 KILL-SWITCH triggered: " + " | ".join(reasons))
                self._kill_triggered = True
                self.strategy.on_stop()                 # cancel pending
                self.connector.close_all_positions()    # flatten live
        except Exception as e:
            self.log.warning(f"Kill-switch check failed: {e}")

        # 3) Hot-apply newly approved deployments (no restart needed).
        try:
            from intelligence.deploy import DeploymentManager
            from intelligence.execution.live_apply import apply_hot
            for dep in DeploymentManager().list():
                if dep.get("status") != "approved":
                    continue
                sig = (dep.get("id"), dep.get("params_signature"))
                if sig in self._hot_applied_sigs:
                    continue
                applied = apply_hot(self.strategy, dep)
                self._hot_applied_sigs.add(sig)
                self.log.info(
                    f"Hot-applied deployment {dep['id']} "
                    f"({', '.join(applied.get('applied', [])) or 'no params'})")
        except Exception as e:
            self.log.warning(f"Hot-apply failed: {e}")

    def _active_orders_count(self) -> int:
        """Number of pending grid orders (grid strategies only; 0 otherwise)."""
        if hasattr(self.strategy, 'active_orders'):
            try:
                return len(self.strategy.active_orders)
            except Exception:
                return 0
        return 0

    def _process_tick(self):
        tick = self.connector.symbol_tick()
        if tick:
            self.strategy.on_tick(tick)
            # Auto-retry is grid-specific — only re-place for strategies that
            # expose active_orders (GridStrategy).  Breakout manages its own
            # entries and must NOT be restarted here.
            if hasattr(self.strategy, 'active_orders'):
                if not self.strategy.active_orders:
                    positions = self.connector.get_positions() or []
                    if not positions:
                        self.log.warning(
                            "Grid has 0 active orders and 0 open positions — "
                            "re-placing grid on next tick..."
                        )
                        self.strategy.on_start()

    def _process_account(self):
        acc = self.connector.account_info()
        if not acc:
            return
        pos = self.connector.get_positions()
        net = sum(
            p['volume'] if p['type'] == 'buy' else -p['volume']
            for p in pos
        )
        self.logger.log_equity(
            acc.equity, acc.balance, net, self._active_orders_count()
        )
        # Track drawdown from peak equity (feeds the execution kill-switch).
        self._peak_equity = max(
            getattr(self, "_peak_equity", 0.0) or 0.0, float(acc.equity or 0.0))
        if getattr(self, "_peak_equity", 0.0) > 0:
            self._last_drawdown_pct = max(
                0.0, (self._peak_equity - float(acc.equity or 0.0))
                / self._peak_equity * 100.0)
        action, value = self.risk.check(acc.equity, acc.balance, net)
        if action:
            msg = f"Risk trigger [{self.account.id}]: {action} {value}"
            self.log.warning(msg)
            if self.notifier:
                self.notifier.send(msg)
            self.connector.close_all_positions()
            if hasattr(self.strategy, 'reset_grid'):
                self.strategy.reset_grid()

    # ── Kronos Risk Sizing (Item 10) ───────────────────────────────────

    def _apply_kronos_risk_sizing(self):
        """
        Extract VaR/CVaR from Kronos forecast samples and adjust the
        strategy's lot size accordingly.

        Called periodically from _sync_regime_params.

        Workflow:
          1. Get the raw forecast samples from the Kronos predictor
          2. Compute VaR and CVaR from the sample distribution
          3. Compute position size adjustment factor (0.1..1.0)
          4. Apply to strategy.lot

        If samples are unavailable, leaves lot size unchanged.
        """
        if self._kronos_predictor is None:
            return

        # Get raw forecast samples from the predictor's last run
        raw_samples = getattr(self._kronos_predictor, '_last_raw_samples', None)
        if raw_samples is None:
            # Try to extract from the adapter's forecast_features
            feat = getattr(self.regime_adapter, 'forecast_features', {})
            raw_samples = feat.get('raw_samples', None)

        if raw_samples is None or not hasattr(raw_samples, 'ndim') or raw_samples.ndim != 3:
            self.log.warning("KronosRiskMetrics: no raw samples available for VaR computation")
            return

        try:
            var, cvar = self.kronos_risk.compute_var_cvar(raw_samples)
            adjustment = self.kronos_risk.position_size_adjustment(var, cvar)

            # Apply adjustment to strategy's base lot size
            base_lot = getattr(self.config, 'LOT_SIZE', 0.1)
            adjusted_lot = round(base_lot * adjustment, 4)
            adjusted_lot = max(0.001, adjusted_lot)  # enforce minimum

            old_lot = getattr(self.strategy, 'lot', None)
            if old_lot is None:
                return
            if abs(old_lot - adjusted_lot) / max(old_lot, 1e-8) > 0.05:
                self.strategy.lot = adjusted_lot
                self.log.info(
                    f"KronosRiskMetrics: VaR={var:.4f} CVaR={cvar:.4f} "
                    f"adjustment={adjustment:.2f} lot={old_lot}→{adjusted_lot}"
                )
        except Exception as e:
            self.log.warning(f"KronosRiskMetrics: VaR/CVaR computation failed: {e}")

    # ── Signal handling ────────────────────────────────────────────────

    def _handle_signal(self, signum, frame):
        self.log.warning(f"Received signal – shutting down gracefully...")
        self.running = False

    def _shutdown_cleanly(self):
        """Orderly shutdown of all components."""
        self.log.info(f"Shutting down QuantBot for account {self.account.id}...")
        for comp in (self.regime_adapter, self.adaptive_updater,
                     self.research_scheduler,
                     self.strategy, self.connector, self.logger):
            try:
                if hasattr(comp, 'stop'):
                    comp.stop()
                elif hasattr(comp, 'close'):
                    comp.close()
                elif hasattr(comp, 'shutdown'):
                    comp.shutdown()
                elif hasattr(comp, 'on_stop'):
                    comp.on_stop()
            except Exception as e:
                self.log.warning(f"{type(comp).__name__} shutdown error: {e}")
        self.log.info(f"QuantBot for account {self.account.id} shut down.")


# ═══════════════════════════════════════════════════════════════════════
#  Single-account GridBot (dashboard-friendly wrapper)
# ═══════════════════════════════════════════════════════════════════════

class GridBot:
    """
    Wraps App with the pause/resume/get_status API that the web dashboard
    expects.  Tied to a single BrokerAccount.
    """

    def __init__(self, account: BrokerAccount):
        self.account_id = account.id
        self._app = App(account)
        self._paused = True        # start paused
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._stop = False
        self.connected = False
        self.last_error: Optional[str] = None

        # Check connectivity at construction time
        try:
            acc = self._app.connector.account_info()
            self.connected = acc is not None
        except Exception:
            self.connected = False

    # ── Lifecycle ──────────────────────────────────────────────────────

    def run(self):
        """Called in a background thread.  Loops until stopped."""
        self._app.log.info(f"GridBot [{self.account_id}]: background thread started (paused).")
        try:
            self._app.regime_adapter.start()
            self._app.adaptive_updater.start()
            if self._app.research_scheduler is not None:
                self._app.research_scheduler.start()
            self._app.strategy.on_start()

            while not self._stop:
                if not self._paused:
                    self._app._sync_regime_params()
                    self._app._process_tick()
                    self._app._process_account()
                    self._app._execution_guard()   # kill-switch + hot-apply
                    acc = self._app.connector.account_info()
                    self.connected = acc is not None
                time.sleep(0.5)
        except Exception as exc:
            import traceback
            self.last_error = str(exc)
            self._app.log.error(
                f"GridBot [{self.account_id}]: thread crashed: {exc}\n{traceback.format_exc()}"
            )
        finally:
            self._app._shutdown_cleanly()

    def pause(self):
        self._paused = True
        self._app.log.info(f"GridBot [{self.account_id}]: paused.")

    def cancel_pending_orders(self):
        """Cancel this bot's pending limit orders (best-effort)."""
        try:
            if hasattr(self._app.strategy, 'active_orders') and self._app.strategy.active_orders:
                for p in list(self._app.strategy.active_orders.keys()):
                    try:
                        self._app.connector.cancel_order(p)
                    except Exception:
                        pass
                self._app.strategy.active_orders.clear()
        except Exception:
            pass

    def close_all_positions(self):
        """Close all open positions via the broker connector."""
        try:
            self._app.connector.close_all_positions()
            self._app.log.info(f"GridBot [{self.account_id}]: close_all_positions sent.")
        except Exception as e:
            self._app.log.warning(f"GridBot [{self.account_id}]: close_all failed: {e}")

    def reset_grid(self):
        """Reset the strategy: re-place the grid, or restart breakout warm-up."""
        try:
            if hasattr(self._app.strategy, 'reset_grid'):
                self._app.strategy.reset_grid()
            else:
                self._app.strategy.on_start()
            self._app.log.info(f"GridBot [{self.account_id}]: strategy reset.")
        except Exception as e:
            self._app.log.warning(f"GridBot [{self.account_id}]: reset failed: {e}")

    def resume(self):
        self._paused = False
        self._app.log.info(f"GridBot [{self.account_id}]: resumed.")

    def stop(self):
        """Fully stop the background thread and cancel its pending grid orders
        (so they don't keep executing under a different strategy)."""
        self._stop = True
        self._paused = True
        # Cancel pending grid orders best-effort so they don't linger
        try:
            if hasattr(self._app.strategy, 'active_orders') and self._app.strategy.active_orders:
                prices = list(self._app.strategy.active_orders.keys())
                for p in prices:
                    try:
                        self._app.connector.cancel_order(p)
                    except Exception:
                        pass
                self._app.strategy.active_orders.clear()
        except Exception:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    # ── Dashboard API ──────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return a snapshot dict consumed by the dashboard."""
        acc = self._app.connector.account_info()
        tick = self._app.connector.symbol_tick()
        pos = self._app.connector.get_positions()

        balance = float(acc.balance) if acc else 0.0
        equity = float(acc.equity) if acc else 0.0
        price = float(tick.get('bid', 0)) if tick else 0.0
        net_pos = sum(
            p['volume'] if p['type'] == 'buy' else -p['volume']
            for p in (pos or [])
        )
        num_pos = len(pos) if pos else 0

        regime = (self._app.regime_adapter.regime_name
                  if self._app.regime_adapter.enabled else "ml_disabled")
        regime_conf = self._app.regime_adapter.confidence
        spacing = getattr(self._app.regime_adapter, 'spacing', None)
        levels = getattr(self._app.regime_adapter, 'levels', None)

        # ── Kronos forecast data (if enabled and available) ─────────────
        kronos_forecast = {}
        if getattr(self._app.config, "KRONOS_ENABLED", False):
            try:
                feat = getattr(self._app.regime_adapter, 'forecast_features', {})
                if feat:
                    kronos_forecast = {
                        'trend': feat.get('trend', 0.0),
                        'trend_strength': feat.get('trend_strength', 0.0),
                        'volatility_forecast': feat.get('volatility_forecast', 0.0),
                        'price_range': feat.get('price_range', 0.0),
                        'price_min_forecast': feat.get('price_min_forecast', 0.0),
                        'price_max_forecast': feat.get('price_max_forecast', 0.0),
                        'regime_label': feat.get('regime_label', 'RANGING'),
                    }
            except Exception:
                pass

        # ── Breakout-specific Kronos enhancer data (if strategy supports it) ──
        kronos_breakout = {}
        try:
            strategy = self._app.strategy
            if hasattr(strategy, 'get_kronos_breakout_status'):
                kronos_breakout = strategy.get_kronos_breakout_status()
        except Exception:
            pass

        return {
            'account_id': self.account_id,
            'active_orders': self._app._active_orders_count(),
            'open_positions': num_pos,
            'net_position': net_pos,
            'total_pnl': equity - balance,
            'pnl_pct': ((equity - balance) / balance * 100) if balance else 0.0,
            'current_price': price,
            'latest_price': price,
            'balance': balance,
            'equity': equity,
            'regime': regime,
            'regime_confidence': regime_conf,
            'position_direction': ('Long' if net_pos > 0
                                   else 'Short' if net_pos < 0
                                   else 'Neutral'),
            'max_drawdown_pct': 0.0,
            'grid_spacing': spacing,
            'grid_levels': levels,
            'paused': self._paused,
            'has_bot': True,
            'trading_active': not self._paused,
            'num_orders': self._app._active_orders_count(),
            'last_error': self.last_error,
            'kronos': kronos_forecast,
            'kronos_breakout': kronos_breakout,
        }

    def detect_regime(self) -> str:
        if not self._app.regime_adapter.enabled:
            return "ml_disabled"
        try:
            self._app.regime_adapter.refresh_now()
            return self._app.regime_adapter.regime_name
        except Exception as exc:
            self._app.log.warning(f"GridBot [{self.account_id}].detect_regime() error: {exc}")
            return "error"

    def close_all_positions(self):
        self._app.connector.close_all_positions()
        self._app.strategy.reset_grid()

    def reset_grid(self):
        self._app.strategy.reset_grid()


# ═══════════════════════════════════════════════════════════════════════
#  GridBotManager — orchestrates all accounts
# ═══════════════════════════════════════════════════════════════════════

class GridBotManager:
    """
    Manages multiple GridBot instances, one per BrokerAccount.

    Provides the high-level API used by the dashboard: start, stop,
    status, create/update/delete accounts.
    """

    def __init__(self, account_manager: Optional[BrokerAccountManager] = None):
        self._acct_mgr = account_manager or BrokerAccountManager()
        self._bots: Dict[str, GridBot] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._lock = threading.RLock()

    # ── Account management ─────────────────────────────────────────────

    @property
    def account_manager(self) -> BrokerAccountManager:
        return self._acct_mgr

    # ── Bot lifecycle ──────────────────────────────────────────────────

    def start_bot(self, account_id: str) -> bool:
        """Start a background thread for the given account."""
        with self._lock:
            if account_id in self._threads and self._threads[account_id].is_alive():
                return True   # already running

            account = self._acct_mgr.get_account(account_id)
            if account is None:
                return False

            bot = GridBot(account)
            t = threading.Thread(target=bot.run, daemon=True, name=f"gridbot-{account_id[:8]}")
            bot._thread = t            # link thread to the bot (used by /api/status)
            bot._stop = False
            t.start()
            self._bots[account_id] = bot
            self._threads[account_id] = t
            return True

    def restart_bot(self, account_id: str) -> bool:
        """Fully stop and re-create the bot (used to apply a new strategy)."""
        with self._lock:
            bot = self._bots.get(account_id)
            if bot:
                bot.stop()
            self._bots.pop(account_id, None)
            self._threads.pop(account_id, None)
        started = self.start_bot(account_id)
        if started:
            self.resume_bot(account_id)
        return started

    def stop_bot(self, account_id: str):
        """Pause the bot for the given account."""
        with self._lock:
            bot = self._bots.get(account_id)
            if bot:
                bot.pause()

    def resume_bot(self, account_id: str):
        """Resume trading for the given account."""
        with self._lock:
            bot = self._bots.get(account_id)
            if bot:
                bot.resume()

    def get_bot(self, account_id: str) -> Optional[GridBot]:
        return self._bots.get(account_id)

    def all_statuses(self) -> List[dict]:
        """Return status for all running bots + account metadata."""
        with self._lock:
            accounts = self._acct_mgr.list_accounts()
            results = []
            for acct in accounts:
                bot = self._bots.get(acct.id)
                if bot:
                    try:
                        results.append(bot.get_status())
                    except Exception:
                        results.append(self._account_to_brief(acct))
                else:
                    results.append(self._account_to_brief(acct))
            return results

    def _account_to_brief(self, acct: BrokerAccount) -> dict:
        return {
            'account_id': acct.id,
            'label': acct.label,
            'broker_type': acct.broker_type.value,
            'status': acct.status.value,
            'enabled': acct.enabled,
            'balance': 0.0,
            'equity': 0.0,
            'total_pnl': 0.0,
            'paused': True,
            'active_orders': 0,
            'open_positions': 0,
            'regime': 'unknown',
            'position_direction': 'Neutral',
        }

    def stop_all(self):
        """Pause all running bots."""
        with self._lock:
            for bot in self._bots.values():
                bot.pause()


# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    acct_mgr = BrokerAccountManager()
    default = acct_mgr.ensure_default_account()
    manager = GridBotManager(acct_mgr)
    manager.start_bot(default.id)
    bot = manager.get_bot(default.id)
    if bot:
        bot.resume()
    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        manager.stop_all()