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
    Periodically runs walk‑forward on recent data and updates the live strategy
    if the best out‑of‑sample Sharpe is above a threshold.
    """
    def __init__(self, config, strategy, logger):
        self.config = config
        self.strategy = strategy
        self.log = logger
        self.update_interval_minutes = getattr(config, 'ADAPTIVE_INTERVAL_MINUTES', 120)  # default 2 hours
        self.sharpe_threshold = getattr(config, 'ADAPTIVE_SHARPE_THRESHOLD', 0.5)
        self.pause_threshold = getattr(config, 'ADAPTIVE_PAUSE_SHARPE', -0.5)  # pause if Sharpe below this
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
                # Download recent 1‑minute data (last 3 days gives ~4320 bars)
                data = load_yfinance(self.config.YAHOO_SYMBOL, period="3d", interval="1m")
                # Walk‑forward: last 1 day in‑sample, 1 day out‑of‑sample
                wf = walkforward_analysis(
                    data,
                    GridStrategy,
                    self.param_grid,
                    window_size=1440,      # 1 day (1440 minutes)
                    step_size=1440,
                    initial_capital=10000,
                    lot=self.config.LOT_SIZE
                )
                if wf.empty:
                    self.log.info("Walk‑forward returned no results. Keeping current parameters.")
                else:
                    # Use the best row from the most recent window
                    best_row = wf.iloc[-1]   # last out‑of‑sample
                    sharpe = best_row['sharpe_ratio']
                    spacing = best_row['spacing']
                    levels = int(best_row['levels'])

                    self.log.info(f"Adaptive: best params = spacing {spacing}, levels {levels}, Sharpe {sharpe:.2f}")

                    if sharpe >= self.sharpe_threshold:
                        # Update live strategy
                        self.strategy.spacing = spacing
                        self.strategy.levels = levels
                        self.strategy.reset_grid()
                        self.log.info("Adaptive: parameters updated.")
                    elif sharpe <= self.pause_threshold:
                        # Pause grid
                        self.strategy.connector.close_all_positions()
                        self.log.warning("Adaptive: Sharpe too low, pausing grid.")
                    else:
                        self.log.info("Adaptive: Sharpe within neutral range, no changes.")
            except Exception as e:
                self.log.error(f"Adaptive updater error: {e}")

            # Sleep for the configured interval
            time.sleep(self.update_interval_minutes * 60)