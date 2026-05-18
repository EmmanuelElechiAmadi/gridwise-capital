class RiskManager:
    def __init__(self, config, logger):
        self.tp = config.TAKE_PROFIT_DOLLARS
        self.sl = config.STOP_LOSS_DOLLARS
        self.max_pos = config.MAX_POSITION_OZ
        self.max_dd_pct = config.MAX_DRAWDOWN_PERCENT
        self.peak_equity = 0
        self.log = logger

    def check(self, equity, balance, net_position):
        pnl = equity - balance
        if self.tp and pnl >= self.tp:
            return 'take_profit', pnl
        if self.sl and pnl <= -self.sl:
            return 'stop_loss', pnl
        if self.max_pos and abs(net_position) > self.max_pos:
            return 'max_position', net_position
        if equity > self.peak_equity:
            self.peak_equity = equity
        dd = (self.peak_equity - equity) / self.peak_equity * 100 if self.peak_equity > 0 else 0
        if self.max_dd_pct and dd > self.max_dd_pct:
            return 'max_drawdown', dd
        return None, None
