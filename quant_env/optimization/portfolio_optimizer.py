import numpy as np
from collections import deque

class KellyPortfolio:
    def __init__(self, strategies, window=30, max_total_risk=0.1):
        self.strategies = strategies
        self.trade_logs = {s:deque(maxlen=window) for s in strategies}
        self.max_total_risk = max_total_risk

    def add_trade(self, strategy, pnl):
        self.trade_logs[strategy].append(pnl)

    def compute_allocations(self, total_equity):
        kellys = {}
        for s in self.strategies:
            trades = list(self.trade_logs[s])
            if len(trades)<5: kellys[s]=0; continue
            wins = [t for t in trades if t>0]
            losses = [t for t in trades if t<=0]
            if not losses:
                k = min(0.2, len(wins)/len(trades)*0.5)
            else:
                wr = len(wins)/len(trades)
                r = np.mean(wins)/abs(np.mean(losses)) if abs(np.mean(losses))!=0 else 0
                k = wr - (1-wr)/r if r!=0 else 0
            kellys[s] = max(0, min(k, 0.25))
        total_k = sum(kellys.values())
        if total_k==0: return {s:0 for s in self.strategies}
        return {s: (kellys[s]/total_k)*self.max_total_risk*total_equity for s in self.strategies}
