"""
backtester/metrics.py
---------------------
Post-run performance analytics.

The list-based functions assume ONE equity point per trading day
(periods_per_year=252). Feed them a daily curve, not one point per bar:
with ~400 symbols a per-bar curve has ~400 points per day, which makes
cagr() treat 3 years as ~1,200 years and breaks Sharpe.

`performance_report()` works on a date-indexed daily pandas Series and
computes everything from real dates.
"""

import math
from typing import List, Optional

import pandas as pd


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


# ── Date-aware analytics (pandas) ─────────────────────────────

def drawdown_series(equity: pd.Series) -> pd.Series:
    """Drawdown at each date as a negative fraction (e.g. -0.12 = 12% below peak)."""
    return equity / equity.cummax() - 1


def monthly_returns(equity: pd.Series) -> pd.DataFrame:
    """Year × month table of returns (fractions)."""
    monthly = equity.resample("ME").last().pct_change()
    first = equity.resample("ME").last().iloc[0] / equity.iloc[0] - 1
    monthly.iloc[0] = first
    table = monthly.to_frame("ret")
    table["year"] = table.index.year
    table["month"] = table.index.month
    return table.pivot(index="year", columns="month", values="ret")


def performance_report(
    equity:        pd.Series,
    pnl_per_trade: List[float],
    benchmark:     Optional[pd.Series] = None,
    risk_free_rate: float = 0.0,
) -> dict:
    """
    Full metrics from a date-indexed DAILY equity curve.

    benchmark: optional daily close series (e.g. SPY) for alpha/beta.
    """
    equity = equity.dropna()
    if len(equity) < 2:
        return {}
    rets  = equity.pct_change().dropna()
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-9)
    total = equity.iloc[-1] / equity.iloc[0] - 1
    cagr_ = (1 + total) ** (1 / years) - 1 if total > -1 else -1.0
    vol   = rets.std() * math.sqrt(252)
    rf_d  = risk_free_rate / 252
    sharpe = (rets.mean() - rf_d) / rets.std() * math.sqrt(252) if rets.std() > 0 else None
    downside = rets[rets < 0].std()
    sortino = (rets.mean() - rf_d) / downside * math.sqrt(252) if downside and downside > 0 else None
    mdd = -drawdown_series(equity).min()

    wins   = [p for p in pnl_per_trade if p > 0]
    losses = [p for p in pnl_per_trade if p < 0]

    report = {
        "start":            str(equity.index[0].date()),
        "end":              str(equity.index[-1].date()),
        "final_equity":     round(float(equity.iloc[-1]), 2),
        "total_return_pct": round(total * 100, 2),
        "cagr_pct":         round(cagr_ * 100, 2),
        "annual_vol_pct":   round(vol * 100, 2),
        "sharpe":           round(sharpe, 3) if sharpe is not None else None,
        "sortino":          round(sortino, 3) if sortino is not None else None,
        "max_drawdown_pct": round(mdd * 100, 2),
        "calmar":           round(cagr_ / mdd, 3) if mdd > 0 else None,
        "num_trades":       len(pnl_per_trade),
        "win_rate_pct":     round(len(wins) / len(pnl_per_trade) * 100, 2) if pnl_per_trade else None,
        "profit_factor":    round(sum(wins) / abs(sum(losses)), 3) if losses else None,
        "avg_win":          round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss":         round(sum(losses) / len(losses), 2) if losses else None,
    }

    report = _plain(report)
    if benchmark is not None and len(benchmark.dropna()) > 2:
        b = benchmark.reindex(equity.index).ffill().pct_change()
        joined = pd.concat([rets, b], axis=1, keys=["s", "b"]).dropna()
        if len(joined) > 2 and joined["b"].var() > 0:
            beta  = joined.cov().loc["s", "b"] / joined["b"].var()
            alpha = (joined["s"].mean() - beta * joined["b"].mean()) * 252
            active = joined["s"] - joined["b"]
            ir = active.mean() / active.std() * math.sqrt(252) if active.std() > 0 else None
            bench_total = benchmark.reindex(equity.index).ffill().dropna()
            report.update({
                "benchmark_return_pct": round((bench_total.iloc[-1] / bench_total.iloc[0] - 1) * 100, 2),
                "beta":              round(float(beta), 3),
                "alpha_annual_pct":  round(float(alpha) * 100, 2),
                "information_ratio": round(float(ir), 3) if ir is not None else None,
                "correlation":       round(float(joined.corr().loc["s", "b"]), 3),
            })
    return _plain(report)


def _plain(d: dict) -> dict:
    """numpy scalars → Python floats/ints so results serialise cleanly to JSON."""
    return {k: (v.item() if hasattr(v, "item") else v) for k, v in d.items()}
