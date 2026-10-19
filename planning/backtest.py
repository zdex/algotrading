"""Backtest a plan as a sleeve mix of ETFs, rebalanced when a sleeve leaves its band."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from backtester.metrics import drawdown_series, performance_report
from planning.model import Plan

# US-listed stand-ins. Local equity is the US market because the company list is US indexes.
SLEEVE_PROXIES = {
    "Local equity": "SPY",
    "Developed global equity": "VEA",
    "Emerging equity": "VWO",
    "Fixed income": "AGG",
    "Gold": "GLD",
    "Cash": None,
}
BENCHMARK = "SPY"


@dataclass
class PlanBacktest:
    equity: pd.Series
    weights: pd.DataFrame
    rebalance_dates: list[pd.Timestamp]
    metrics: dict
    benchmark: pd.Series
    proxies: dict[str, str]
    notes: list[str] = field(default_factory=list)
    contributed: float = 0.0


def proxy_symbols(plan: Plan) -> list[str]:
    symbols = {BENCHMARK}
    for row in plan.buckets:
        proxy = SLEEVE_PROXIES.get(row.name)
        if proxy:
            symbols.add(proxy)
    return sorted(symbols)


def _traded_targets(plan: Plan) -> tuple[dict[str, float], dict[str, str | None], list[str], bool]:
    """Sleeve name -> weight, sleeve -> proxy, notes, and whether targets were scaled."""
    notes: list[str] = []
    raw: dict[str, float] = {}
    for row in plan.buckets:
        if row.target <= 0:
            continue
        raw[row.name] = row.target / 100.0

    scaled = False
    total = sum(raw.values())
    if total > 1.001:
        raw = {name: weight / total for name, weight in raw.items()}
        scaled = True
        notes.append("Sleeve targets were above 100%, so they were scaled to 100% for the backtest.")

    proxies: dict[str, str | None] = {}
    traded: dict[str, float] = {}
    dropped = 0.0
    for name, weight in raw.items():
        if name not in SLEEVE_PROXIES:
            dropped += weight
            notes.append(f"{name} has no price history in this backtest, so its target stays in cash.")
            continue
        proxies[name] = SLEEVE_PROXIES[name]
        traded[name] = weight

    residual = 1.0 - sum(traded.values()) - dropped
    extra_cash = dropped + max(0.0, residual)
    if extra_cash > 0.001:
        if "Cash" in traded:
            traded["Cash"] += extra_cash
        else:
            traded["Cash"] = extra_cash
            proxies["Cash"] = None
            if residual > 0.001 and dropped == 0:
                notes.append("Target weights below 100% are held as cash.")
    return traded, proxies, notes, scaled


def _portfolio_value(shares: dict[str, float], prices: pd.Series, cash: float) -> tuple[float, dict[str, float]]:
    values: dict[str, float] = {}
    total = cash
    for proxy, qty in shares.items():
        value = qty * float(prices[proxy])
        values[proxy] = value
        total += value
    return total, values


def _sleeve_weights(
    proxies: dict[str, str | None],
    values: dict[str, float],
    cash: float,
    total: float,
) -> dict[str, float]:
    if total <= 0:
        return {name: 0.0 for name in proxies}
    weights = {}
    for name, proxy in proxies.items():
        amount = cash if proxy is None else values.get(proxy, 0.0)
        weights[name] = amount / total
    return weights


def _rebalance(
    total: float,
    prices: pd.Series,
    proxies: dict[str, str | None],
    targets: dict[str, float],
) -> tuple[dict[str, float], float]:
    shares: dict[str, float] = {}
    cash = 0.0
    for name, target in targets.items():
        dollars = total * target
        proxy = proxies[name]
        if proxy is None:
            cash += dollars
        else:
            shares[proxy] = shares.get(proxy, 0.0) + dollars / float(prices[proxy])
    return shares, cash


def _deploy_contribution(
    amount: float,
    shares: dict[str, float],
    cash: float,
    prices: pd.Series,
    proxies: dict[str, str | None],
    targets: dict[str, float],
) -> tuple[dict[str, float], float]:
    """Put new money into sleeves that are below target, in proportion to the dollar gap."""
    if amount <= 0:
        return shares, cash
    total, values = _portfolio_value(shares, prices, cash + amount)
    gaps: dict[str, float] = {}
    for name, target in targets.items():
        proxy = proxies[name]
        current = cash if proxy is None else values.get(proxy, 0.0)
        gap = target * total - current
        if gap > 1e-6:
            gaps[name] = gap
    if not gaps:
        return shares, cash + amount
    gap_sum = sum(gaps.values())
    for name, gap in gaps.items():
        dollars = amount * gap / gap_sum
        proxy = proxies[name]
        if proxy is None:
            cash += dollars
        else:
            shares[proxy] = shares.get(proxy, 0.0) + dollars / float(prices[proxy])
    return shares, cash


def _off_target(
    weights: dict[str, float],
    targets: dict[str, float],
    plan: Plan,
    band: float,
    scaled: bool,
) -> bool:
    floors = {row.name: row for row in plan.buckets}
    for name, target in targets.items():
        weight = weights.get(name, 0.0)
        if abs(weight - target) * 100 > band:
            return True
        row = floors.get(name)
        if row is None or scaled:
            continue
        percent = weight * 100
        if percent < row.floor or percent > row.ceiling:
            return True
    return False


def run_plan_backtest(
    plan: Plan,
    prices: pd.DataFrame,
    initial_cash: float,
    monthly_contribution: float = 0.0,
) -> PlanBacktest:
    """
    Daily close backtest.

    Each sleeve is one ETF. New money on the first session of a month goes to
    sleeves below target. At month-end the book is reset to target when a sleeve
    is outside the rebalance band or its floor and ceiling.
    """
    if initial_cash <= 0:
        raise ValueError("Starting cash must be positive.")
    targets, proxies, notes, scaled = _traded_targets(plan)
    needed = sorted({proxy for proxy in proxies.values() if proxy})
    missing = [symbol for symbol in needed if symbol not in prices.columns]
    if missing:
        raise ValueError("Missing prices for " + ", ".join(missing) + ".")

    frame = prices.sort_index()
    if needed:
        frame = frame[needed].dropna(how="any")
    if frame.empty or len(frame) < 2:
        raise ValueError("Not enough price history in that date range.")

    shares: dict[str, float] = {}
    cash = 0.0
    contributed = 0.0
    rebalances: list[pd.Timestamp] = []
    equity_rows: list[float] = []
    weight_rows: list[dict[str, float]] = []
    dates = list(frame.index)

    for i, day in enumerate(dates):
        row = frame.loc[day]
        if i == 0:
            shares, cash = _rebalance(initial_cash, row, proxies, targets)
        else:
            if monthly_contribution > 0 and day.month != dates[i - 1].month:
                shares, cash = _deploy_contribution(
                    monthly_contribution, shares, cash, row, proxies, targets,
                )
                contributed += monthly_contribution
            total, _ = _portfolio_value(shares, row, cash)
            month_end = i == len(dates) - 1 or dates[i + 1].month != day.month
            weights_now = _sleeve_weights(proxies, _portfolio_value(shares, row, cash)[1], cash, total)
            if month_end and _off_target(weights_now, targets, plan, plan.rebalance_band_pct, scaled):
                shares, cash = _rebalance(total, row, proxies, targets)
                rebalances.append(pd.Timestamp(day))

        total, values = _portfolio_value(shares, row, cash)
        equity_rows.append(total)
        weight_rows.append(_sleeve_weights(proxies, values, cash, total))

    equity = pd.Series(equity_rows, index=frame.index, name="equity")
    weights = pd.DataFrame(weight_rows, index=frame.index).reindex(columns=list(targets))
    benchmark = pd.Series(dtype=float)
    if BENCHMARK in prices.columns:
        benchmark = prices[BENCHMARK].reindex(equity.index).ffill().dropna()
    metrics = performance_report(equity, [], benchmark if not benchmark.empty else None)
    metrics["rebalances"] = len(rebalances)
    metrics["contributed"] = round(contributed, 2)
    return PlanBacktest(
        equity=equity,
        weights=weights,
        rebalance_dates=rebalances,
        metrics=metrics,
        benchmark=benchmark,
        proxies={name: proxy for name, proxy in proxies.items() if proxy},
        notes=notes,
        contributed=contributed,
    )
