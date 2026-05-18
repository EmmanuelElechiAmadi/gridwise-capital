import time, signal, sys, os
sys.path.append(os.path.dirname(__file__))
from config import Config
from core.connector import Connector
from core.risk_manager import RiskManager
from core.logger import setup_logger
from strategies.grid_strategy import GridStrategy
from analysis.trade_logger import TradeLogger
from utils.notifications import TelegramNotifier
from utils.config_loader import load_config

class App:
    def __init__(self):
        self.config = Config
        self.log = setup_logger()
        self.connector = Connector(self.config)
        self.risk = RiskManager(self.config, self.log)
        self.logger = TradeLogger("quant_env/trades.db")
        self.strategy = GridStrategy(self.connector, self.config, self.log)
        self.strategy.logger = self.logger
        env = load_config()
        self.notifier = None
        if env.get('TELEGRAM_TOKEN'):
            self.notifier = TelegramNotifier(env['TELEGRAM_TOKEN'], env['TELEGRAM_CHAT_ID'])
        self.running = True
        signal.signal(signal.SIGINT, self.shutdown)

    def run(self):
        self.strategy.on_start()
        while self.running:
            tick = self.connector.symbol_tick()
            if tick:
                self.strategy.on_tick(tick)
            acc = self.connector.account_info()
            pos = self.connector.get_positions()
            net = sum(p['volume'] if p['type']=='buy' else -p['volume'] for p in pos)
            if acc:
                self.logger.log_equity(acc.equity, acc.balance, net, len(self.strategy.active_orders))
                action, value = self.risk.check(acc.equity, acc.balance, net)
                if action:
                    msg = f"Risk trigger: {action} {value}"
                    self.log.warning(msg)
                    if self.notifier:
                        self.notifier.send(msg)
                    self.connector.close_all_positions()
                    self.strategy.reset_grid()
            time.sleep(0.5)
        self.strategy.on_stop()
        self.connector.shutdown()
        self.logger.close()

    def shutdown(self, signum, frame):
        self.running = False

if __name__ == "__main__":
    App().run()
