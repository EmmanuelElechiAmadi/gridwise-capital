import time
import signal
import sys
import os
import threading

sys.path.append(os.path.dirname(__file__))

from config import Config
from core.connector import Connector
from core.risk_manager import RiskManager
from core.logger import setup_logger
from strategies.grid_strategy import GridStrategy
from analysis.trade_logger import TradeLogger
from utils.notifications import TelegramNotifier
from utils.config_loader import load_config
from ml.regime_adapter import RegimeAdapter
from adaptive.updater import AdaptiveUpdater


class App:
    """
    Main trading application.

    Manages lifecycle of connector, strategy, ML regime adapter, adaptive
    walk‑forward updater, and graceful shutdown.
    """

    def __init__(self):
        self.config = Config
        self.log = setup_logger(
            log_file=os.path.join(os.path.dirname(__file__), '../logs/quantbot.log')
        )
        self.connector = Connector(self.config)
        self.risk = RiskManager(self.config, self.log)
        self.logger = TradeLogger("quant_env/trades.db")
        self.strategy = GridStrategy(self.connector, self.config, self.log)
        self.strategy.logger = self.logger

        env = load_config()
        self.notifier = None
        if env.get('TELEGRAM_TOKEN'):
            self.notifier = TelegramNotifier(
                env['TELEGRAM_TOKEN'], env['TELEGRAM_CHAT_ID']
            )

        self.running = True

        # Register SIGINT (Ctrl-C) and SIGTERM
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        # ── ML regime adapter ──────────────────────────────────────
        self.regime_adapter = RegimeAdapter(self.config)
        if self.config.ML_ENABLED:
            self.strategy.regime_adapter = self.regime_adapter

        # ── Adaptive walk‑forward updater ───────────────────────────
        self.adaptive_updater = AdaptiveUpdater(
            self.config, self.strategy, self.log
        )

    # ── Lifecycle ──────────────────────────────────────────────────

    def run(self):
        """Main trading loop."""
        self.log.info("Starting QuantBot – press Ctrl-C to stop.")
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

    # ── Internal tick / account processing ─────────────────────────

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
            msg = f"Risk trigger: {action} {value}"
            self.log.warning(msg)
            if self.notifier:
                self.notifier.send(msg)
            self.connector.close_all_positions()
            self.strategy.reset_grid()

    # ── Signal handling ────────────────────────────────────────────

    def _handle_signal(self, signum, frame):
        sig_name = signal.Signals(signum).name
        self.log.warning(f"Received {sig_name} – shutting down gracefully...")
        self.running = False

    def _shutdown_cleanly(self):
        """Orderly shutdown of all components."""
        self.log.info("Shutting down QuantBot...")
        try:
            self.regime_adapter.stop()
        except Exception as e:
            self.log.warning(f"regime_adapter.stop() error: {e}")
        try:
            self.adaptive_updater.stop()
        except Exception as e:
            self.log.warning(f"adaptive_updater.stop() error: {e}")
        try:
            self.strategy.on_stop()
        except Exception as e:
            self.log.warning(f"strategy.on_stop() error: {e}")
        try:
            self.connector.shutdown()
        except Exception as e:
            self.log.warning(f"connector.shutdown() error: {e}")
        try:
            self.logger.close()
        except Exception as e:
            self.log.warning(f"logger.close() error: {e}")
        self.log.info("QuantBot shut down.")


# ── GridBot — dashboard-friendly wrapper around App ──────────────────

class GridBot:
    """
    Wraps App with the pause/resume/get_status API that the web dashboard
    expects.  The dashboard imports this class via::

        from quant_env.main import GridBot
    """

    def __init__(self):
        self._app = App()
        self._paused = True                     # start paused
        self._thread = None
        self._lock = threading.Lock()
        self.connected = False                  # updated on first account info

        # Check MT5 bridge connectivity at construction time
        try:
            acc = self._app.connector.account_info()
            self.connected = acc is not None
        except Exception:
            self.connected = False

    # ── Lifecycle ──────────────────────────────────────────────────────

    def run(self):
        """Called by dashboard in a background thread.  Loops until paused."""
        self._app.log.info("GridBot: background thread started (paused).")
        self._app.regime_adapter.start()
        self._app.adaptive_updater.start()
        self._app.strategy.on_start()

        try:
            while True:
                if not self._paused:
                    self._app._sync_regime_params()
                    self._app._process_tick()
                    self._app._process_account()
                    # Update connected flag
                    acc = self._app.connector.account_info()
                    self.connected = acc is not None
                time.sleep(0.5)
        except Exception as exc:
            self._app.log.error(f"GridBot: thread crashed: {exc}")
        finally:
            self._app._shutdown_cleanly()

    def pause(self):
        """Pause trading (orders stay on the books)."""
        self._paused = True
        self._app.log.info("GridBot: paused.")

    def resume(self):
        """Resume paused trading."""
        self._paused = False
        self._app.log.info("GridBot: resumed.")

    # ── Dashboard API methods ──────────────────────────────────────────

    def get_status(self) -> dict:
        """Return a snapshot dict consumed by the dashboard socket."""
        acc = self._app.connector.account_info()
        tick = self._app.connector.symbol_tick()
        pos = self._app.connector.get_positions()

        balance = float(acc.balance) if acc else 0.0
        equity = float(acc.equity) if acc else 0.0
        price = float(tick.bid) if tick else 0.0
        net_pos = sum(
            p['volume'] if p['type'] == 'buy' else -p['volume']
            for p in pos
        ) if pos else 0.0
        num_pos = len(pos) if pos else 0

        regime = self._app.regime_adapter.regime_name if self._app.regime_adapter.enabled else "ml_disabled"
        regime_conf = self._app.regime_adapter.confidence
        spacing = self._app.regime_adapter.spacing
        levels = self._app.regime_adapter.levels

        return {
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
            'position_direction': 'Long' if net_pos > 0 else 'Short' if net_pos < 0 else 'Neutral',
            'max_drawdown_pct': 0.0,       # not tracked real-time in simple mode
            'grid_spacing': spacing,
            'grid_levels': levels,
        }

    def detect_regime(self) -> str:
        """Force an immediate regime classification and return the name."""
        if not self._app.regime_adapter.enabled:
            return "ml_disabled"
        try:
            self._app.regime_adapter.refresh_now()
            return self._app.regime_adapter.regime_name
        except Exception as exc:
            self._app.log.warning(f"GridBot.detect_regime() error: {exc}")
            return "error"

    def close_all_positions(self):
        """Close all open positions and cancel pending orders."""
        self._app.connector.close_all_positions()
        self._app.strategy.reset_grid()

    def reset_grid(self):
        """Recreate the grid based on the latest price."""
        self._app.strategy.reset_grid()


if __name__ == "__main__":
    App().run()
