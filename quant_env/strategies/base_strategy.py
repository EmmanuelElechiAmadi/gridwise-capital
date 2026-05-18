class BaseStrategy:
    def __init__(self, connector, config, logger):
        self.connector = connector
        self.config = config
        self.symbol = config.SYMBOL
        self.log = logger

    def on_start(self): pass
    def on_tick(self, tick): return {}
    def on_fill(self, price, side): pass
    def on_stop(self): pass
