"""Sleeve-mix backtest: contributions, band rebalance, and flat prices."""

import pandas as pd

from planning.backtest import run_plan_backtest
from planning.model import Plan, Slice


def _prices(spy, vea=None) -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-02", periods=len(spy))
    frame = pd.DataFrame({"SPY": spy}, index=dates)
    if vea is not None:
        frame["VEA"] = vea
    return frame


def _plan(buckets, band=5) -> Plan:
    plan = Plan(id="t", name="Test", buckets=buckets, rebalance_band_pct=band)
    return plan


def test_flat_prices_keep_starting_cash():
    dates = pd.bdate_range("2020-01-02", "2020-03-31")
    prices = _prices([100.0] * len(dates))
    plan = _plan([Slice("Local equity", 50, 40, 60), Slice("Cash", 50, 40, 60)])
    result = run_plan_backtest(plan, prices, initial_cash=1000)
    assert result.equity.iloc[0] == 1000
    assert result.equity.iloc[-1] == 1000
    assert result.rebalance_dates == []
    assert abs(result.weights["Local equity"].iloc[-1] - 0.5) < 1e-9


def test_contribution_is_split_across_underweight_sleeves():
    dates = pd.bdate_range("2020-01-02", "2020-03-31")
    prices = _prices([100.0] * len(dates))
    plan = _plan([Slice("Local equity", 50, 40, 60), Slice("Cash", 50, 40, 60)])
    result = run_plan_backtest(plan, prices, initial_cash=1000, monthly_contribution=100)
    assert result.contributed == 200
    assert abs(result.equity.iloc[-1] - 1200) < 1e-6
    assert abs(result.weights["Local equity"].iloc[-1] - 0.5) < 1e-6


def test_month_end_rebalance_when_a_sleeve_leaves_the_band():
    dates = pd.bdate_range("2020-01-02", "2020-03-31")
    spy = [100.0] * len(dates)
    spy[1:] = [300.0] * (len(dates) - 1)
    vea = [100.0] * len(dates)
    plan = _plan([
        Slice("Local equity", 50, 40, 60),
        Slice("Developed global equity", 50, 40, 60),
    ])
    result = run_plan_backtest(plan, _prices(spy, vea), initial_cash=1000, monthly_contribution=0)
    assert result.rebalance_dates
    assert abs(result.equity.iloc[-1] - 2000) < 1e-6
    assert abs(result.weights["Local equity"].iloc[-1] - 0.5) < 1e-6


def test_small_drift_does_not_rebalance():
    dates = pd.bdate_range("2020-01-02", "2020-02-28")
    spy = [110.0] * len(dates)
    spy[0] = 100.0
    vea = [100.0] * len(dates)
    plan = _plan([
        Slice("Local equity", 50, 0, 100),
        Slice("Developed global equity", 50, 0, 100),
    ], band=5)
    result = run_plan_backtest(plan, _prices(spy, vea), initial_cash=1000)
    assert result.rebalance_dates == []
    assert result.equity.iloc[-1] > result.equity.iloc[0]


def test_targets_above_100_are_scaled():
    dates = pd.bdate_range("2020-01-02", "2020-01-31")
    prices = pd.DataFrame({"SPY": 100.0, "VEA": 100.0}, index=dates)
    plan = _plan([
        Slice("Local equity", 60, 0, 100),
        Slice("Developed global equity", 60, 0, 100),
    ])
    result = run_plan_backtest(plan, prices, initial_cash=1000)
    assert any("scaled" in note for note in result.notes)
    assert abs(result.weights["Local equity"].iloc[-1] - 0.5) < 1e-9
