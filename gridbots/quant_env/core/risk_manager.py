class RiskManager:
    def __init__(self, config, logger):
        self.tp = getattr(config, 'TAKE_PROFIT_DOLLARS', None)
        self.sl = getattr(config, 'STOP_LOSS_DOLLARS', None)
        self.max_pos = getattr(config, 'MAX_POSITION_OZ', None)
        # Support both MAX_DRAWDOWN_PERCENT and MAX_DRAWDOWN_PCT
        self.max_dd_pct = getattr(config, 'MAX_DRAWDOWN_PERCENT',
                         getattr(config, 'MAX_DRAWDOWN_PCT', None))
        self.max_daily_loss = getattr(config, 'MAX_DAILY_LOSS', None)
        self.initial_balance = getattr(config, 'INITIAL_BALANCE', None)
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
        # Daily loss check
        if self.max_daily_loss is not None and self.initial_balance is not None:
            daily_loss = self.initial_balance - balance
            if daily_loss > self.max_daily_loss:
                return 'max_daily_loss', daily_loss
        if equity > self.peak_equity:
            self.peak_equity = equity
        dd = (self.peak_equity - equity) / self.peak_equity * 100 if self.peak_equity > 0 else 0
        if self.max_dd_pct and dd > self.max_dd_pct:
            return 'max_drawdown', dd
        return None, None
