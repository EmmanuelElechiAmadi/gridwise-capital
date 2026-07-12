import numpy as np
import pandas as pd
from .trade_matcher import match_trades

def compute_metrics(fills_df, equity_df):
    if fills_df.empty or equity_df.empty:
        return _empty_metrics()
    trades = match_trades(fills_df)
    if trades.empty:
        return _empty_metrics()
    equity = pd.to_numeric(equity_df['equity'])
    returns = equity.pct_change().dropna()
    total_return = (equity.iloc[-1] / equity.iloc[0] - 1) * 100
    sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() != 0 else 0
    peak = equity.cummax()
    dd = peak - equity
    max_dd_pct = (dd / peak).max() * 100
    wins = trades[trades['pnl'] > 0]
    losses = trades[trades['pnl'] <= 0]
    win_count = len(wins)
    loss_count = len(losses)
    total_trades = len(trades)
    win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0.0
    total_wins = wins['pnl'].sum()
    total_losses = abs(losses['pnl'].sum())
    profit_factor = total_wins / total_losses if total_losses > 0 else 0.0
    return {
        'total_return_pct': round(total_return, 2),
        'total_pnl': round(equity.iloc[-1] - equity.iloc[0], 2),
        'sharpe_ratio': round(sharpe, 2),
        'max_drawdown_pct': round(max_dd_pct, 2),
        'num_trades': total_trades,
        'win_rate_pct': round(win_rate, 2),
        'profit_factor': round(profit_factor, 2),
        'avg_win': round(wins['pnl'].mean(),2) if win_count else 0.0,
        'avg_loss': round(losses['pnl'].mean(),2) if loss_count else 0.0,
    }

def _empty_metrics():
    return {
        'total_return_pct': 0.0,
        'total_pnl': 0.0,
        'sharpe_ratio': -999,          # so optimizer avoids this
        'max_drawdown_pct': 0.0,
        'num_trades': 0,
        'win_rate_pct': 0.0,
        'profit_factor': 0.0,
        'avg_win': 0.0,
        'avg_loss': 0.0,
    }
