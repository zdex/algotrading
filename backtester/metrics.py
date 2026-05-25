"""
backtester/metrics.py
---------------------
Post-run performance analytics.
Pass in the equity curve as a list or pandas Series.
"""

import math
from typing import List, Optional


def sharpe_ratio(
    returns: List[float],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> Optional[float]:
    """Annualised Sharpe ratio from a list of period returns."""
    if len(returns) < 2:
        return None
    n       = len(returns)
    mean    = sum(returns) / n
    excess  = [r - risk_free_rate / periods_per_year for r in returns]
    var     = sum((r - mean) ** 2 for r in excess) / (n - 1)
    std     = math.sqrt(var)
    if std == 0:
        return None
    return (mean - risk_free_rate / periods_per_year) / std * math.sqrt(periods_per_year)


def max_drawdown(equity_curve: List[float]) -> float:
    """Maximum peak-to-trough drawdown as a positive decimal (e.g. 0.23 = 23%)."""
    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        if dd > max_dd:
            max_dd = dd
    return max_dd


def cagr(equity_curve: List[float], periods_per_year: int = 252) -> Optional[float]:
    """Compound Annual Growth Rate."""
    if len(equity_curve) < 2 or equity_curve[0] == 0:
        return None
    total_return = equity_curve[-1] / equity_curve[0]
    years = len(equity_curve) / periods_per_year
    return total_return ** (1 / years) - 1


def win_rate(pnl_per_trade: List[float]) -> Optional[float]:
    if not pnl_per_trade:
        return None
    wins = sum(1 for p in pnl_per_trade if p > 0)
    return wins / len(pnl_per_trade)


def profit_factor(pnl_per_trade: List[float]) -> Optional[float]:
    gross_profit = sum(p for p in pnl_per_trade if p > 0)
    gross_loss   = abs(sum(p for p in pnl_per_trade if p < 0))
    if gross_loss == 0:
        return None
    return gross_profit / gross_loss


def summary_report(
    equity_curve:   List[float],
    pnl_per_trade:  List[float],
    periods_per_year: int = 252,
) -> dict:
    returns = [
        (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
        for i in range(1, len(equity_curve))
    ]
    return {
        "total_return_pct": round((equity_curve[-1] / equity_curve[0] - 1) * 100, 2),
        "cagr_pct":         round((cagr(equity_curve, periods_per_year) or 0) * 100, 2),
        "sharpe":           round(sharpe_ratio(returns, periods_per_year=periods_per_year) or 0, 3),
        "max_drawdown_pct": round(max_drawdown(equity_curve) * 100, 2),
        "num_trades":       len(pnl_per_trade),
        "win_rate_pct":     round((win_rate(pnl_per_trade) or 0) * 100, 2),
        "profit_factor":    round(profit_factor(pnl_per_trade) or 0, 3),
    }
