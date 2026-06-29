import time
import sys
import os
import threading       
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backtest.data_loader import load_yfinance
from analysis.walkforward import walkforward_analysis
from strategies.grid_strategy import GridStrategy

class AdaptiveUpdater:
    """
    Periodically runs walk‑forward on recent data and updates the live strategy.

    Behaviour changes based on whether ML regime adaptation is also active:
        - If ``config.ML_ENABLED`` is True:
            Only updates **risk parameters** (lot size, max position).
            Grid geometry (spacing, levels) is left to the RegimeAdapter.
        - If ``config.ML_ENABLED`` is False:
            Updates **grid geometry** (spacing, levels) and risk params.
    """
    def __init__(self, config, strategy, logger):
        self.config = config
        self.strategy = strategy
        self.log = logger
        self.update_interval_minutes = getattr(config, 'ADAPTIVE_INTERVAL_MINUTES', 120)
        self.sharpe_threshold = getattr(config, 'ADAPTIVE_SHARPE_THRESHOLD', 0.5)
        self.pause_threshold = getattr(config, 'ADAPTIVE_PAUSE_SHARPE', -0.5)
        self.ml_enabled = getattr(config, 'ML_ENABLED', False)

        # Optimise a broader space when ML is off, risk-only when ML is on
        if self.ml_enabled:
            self.param_grid = {'lot': [0.005, 0.01, 0.02]}
        else:
            self.param_grid = {'spacing': [0.1, 0.2, 0.5], 'levels': [3, 5, 7]}

        self.running = False

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.log.info("Adaptive updater started.")

    def stop(self):
        self.running = False
        self.log.info("Adaptive updater stopped.")

    def _run(self):
        while self.running:
            try:
                self.log.info("Running adaptive walk‑forward...")
                data = load_yfinance(self.config.YAHOO_SYMBOL, period="3d", interval="1m")

                wf = walkforward_analysis(
                    data,
                    GridStrategy,
                    self.param_grid,
                    window_size=1440,
                    step_size=1440,
                    initial_capital=10000,
                    lot=self.config.LOT_SIZE,
                )
                if wf.empty:
                    self.log.info("Walk‑forward returned no results. Keeping current parameters.")
                else:
                    best_row = wf.iloc[-1]
                    sharpe = best_row.get('sharpe_ratio', 0.0)

                    self.log.info(
                        f"Adaptive: Sharpe {sharpe:.2f} | "
                        f"params = { {k: best_row.get(k) for k in self.param_grid} }"
                    )

                    if sharpe >= self.sharpe_threshold:
                        if self.ml_enabled:
                            # Only update lot size; grid geometry managed by RegimeAdapter
                            new_lot = float(best_row.get('lot', self.config.LOT_SIZE))
                            self.strategy.lot = new_lot
                            self.log.info(f"Adaptive (ML mode): lot size updated to {new_lot}")
                        else:
                            # Full grid update
                            self.strategy.spacing = float(best_row.get('spacing', self.strategy.spacing))
                            self.strategy.levels = int(best_row.get('levels', self.strategy.levels))
                            self.strategy.reset_grid()
                            self.log.info("Adaptive: grid parameters updated.")
                    elif sharpe <= self.pause_threshold:
                        self.strategy.connector.close_all_positions()
                        self.log.warning("Adaptive: Sharpe too low, pausing grid.")
                    else:
                        self.log.info("Adaptive: Sharpe within neutral range, no changes.")
            except Exception as e:
                self.log.error(f"Adaptive updater error: {e}")

            time.sleep(self.update_interval_minutes * 60)
