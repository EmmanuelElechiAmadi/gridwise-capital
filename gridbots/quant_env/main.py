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
from adaptive.updater import AdaptiveUpdater

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
        self.strategy = GridStrategy(self.connector, self.config, self.log)
        self.strategy.logger = self.logger

        env = load_config()
        self.notifier = None
        if env.get('TELEGRAM_TOKEN'):
            self.notifier = TelegramNotifier(
                env['TELEGRAM_TOKEN'], env['TELEGRAM_CHAT_ID']
            )

        self.running = True

        # ── ML regime adapter ──────────────────────────────────────────
        self.regime_adapter = RegimeAdapter(self.config)
        if self.config.ML_ENABLED:
            self.strategy.regime_adapter = self.regime_adapter

        # ── Adaptive walk‑forward updater ──────────────────────────────
        self.adaptive_updater = AdaptiveUpdater(
            self.config, self.strategy, self.log
        )

    # ── Lifecycle ──────────────────────────────────────────────────────

    def run(self):
        """Main trading loop."""
        self.log.info(f"Starting QuantBot for account {self.account.id} – press Ctrl-C to stop.")
        self.regime_adapter.start()
        self.adaptive_updater.start()
        self.strategy.on_start()

        try:
            while self.running:
                self._sync_regime_params()
                self._process_tick()
                self._process_account()
                time.sleep(0.5)
        finally:
            self._shutdown_cleanly()

    # ── Internal tick / account processing ─────────────────────────────

    def _sync_regime_params(self):
        """Pull grid parameters from RegimeAdapter if ML is active."""
        if (self.regime_adapter.enabled and
                self.regime_adapter.regime != RegimeAdapter.UNKNOWN):
            self.strategy.spacing = self.regime_adapter.spacing
            self.strategy.levels = self.regime_adapter.levels

    def _process_tick(self):
        tick = self.connector.symbol_tick()
        if tick:
            self.strategy.on_tick(tick)

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
            acc.equity, acc.balance, net, len(self.strategy.active_orders)
        )
        action, value = self.risk.check(acc.equity, acc.balance, net)
        if action:
            msg = f"Risk trigger [{self.account.id}]: {action} {value}"
            self.log.warning(msg)
            if self.notifier:
                self.notifier.send(msg)
            self.connector.close_all_positions()
            self.strategy.reset_grid()

    # ── Signal handling ────────────────────────────────────────────────

    def _handle_signal(self, signum, frame):
        self.log.warning(f"Received signal – shutting down gracefully...")
        self.running = False

    def _shutdown_cleanly(self):
        """Orderly shutdown of all components."""
        self.log.info(f"Shutting down QuantBot for account {self.account.id}...")
        for comp in (self.regime_adapter, self.adaptive_updater,
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
        self.connected = False

        # Check connectivity at construction time
        try:
            acc = self._app.connector.account_info()
            self.connected = acc is not None
        except Exception:
            self.connected = False

    # ── Lifecycle ──────────────────────────────────────────────────────

    def run(self):
        """Called in a background thread.  Loops until paused."""
        self._app.log.info(f"GridBot [{self.account_id}]: background thread started (paused).")
        self._app.regime_adapter.start()
        self._app.adaptive_updater.start()
        self._app.strategy.on_start()

        try:
            while True:
                if not self._paused:
                    self._app._sync_regime_params()
                    self._app._process_tick()
                    self._app._process_account()
                    acc = self._app.connector.account_info()
                    self.connected = acc is not None
                time.sleep(0.5)
        except Exception as exc:
            self._app.log.error(f"GridBot [{self.account_id}]: thread crashed: {exc}")
        finally:
            self._app._shutdown_cleanly()

    def pause(self):
        self._paused = True
        self._app.log.info(f"GridBot [{self.account_id}]: paused.")

    def resume(self):
        self._paused = False
        self._app.log.info(f"GridBot [{self.account_id}]: resumed.")

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
        spacing = self._app.regime_adapter.spacing
        levels = self._app.regime_adapter.levels

        return {
            'account_id': self.account_id,
            'active_orders': len(self._app.strategy.active_orders),
            'open_positions': num_pos,
            'net_position': net_pos,
            'total_pnl': equity - balance,
            'pnl_pct': ((equity - balance) / balance * 100) if balance else 0.0,
            'current_price': price,
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
            t.start()
            self._bots[account_id] = bot
            self._threads[account_id] = t
            return True

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