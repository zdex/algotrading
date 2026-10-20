"""Improvement loop: stop rules, invalid model output, and a mix that can hit a target."""

import json

import pandas as pd

from planning.model import Plan, Slice
from planning.optimize import PlanTargets, improve_plan


def _prices(spy, vea=None) -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-02", periods=len(spy))
    frame = pd.DataFrame({"SPY": spy}, index=dates)
    if vea is not None:
        frame["VEA"] = vea
    return frame


def _plan(buckets, band=5) -> Plan:
    return Plan(id="t", name="Test", buckets=buckets, rebalance_band_pct=band)


def _mix(local, developed, cash, band=5, rationale="shift") -> str:
    return json.dumps({
        "buckets": [
            {"name": "Local equity", "target": local, "floor": 0, "ceiling": 100},
            {"name": "Developed global equity", "target": developed, "floor": 0, "ceiling": 100},
            {"name": "Cash", "target": cash, "floor": 0, "ceiling": 100},
        ],
        "rebalance_band_pct": band,
        "rationale": rationale,
    })


def _sleeves(local, developed, cash=0) -> list[Slice]:
    return [
        Slice("Local equity", local, 0, 100),
        Slice("Developed global equity", developed, 0, 100),
        Slice("Cash", cash, 0, 100),
    ]


def test_stops_when_target_already_met_without_calling_the_model():
    dates = pd.bdate_range("2020-01-02", "2020-06-30")
    prices = _prices([100.0] * len(dates))
    plan = _plan([Slice("Local equity", 60, 0, 100), Slice("Cash", 40, 0, 100)])
    calls = {"n": 0}

    def llm(prompt):
        calls["n"] += 1
        return "{}"

    result = improve_plan(
        plan,
        prices,
        initial_cash=1000,
        monthly_contribution=0,
        targets=PlanTargets(min_cagr_pct=-1, max_drawdown_pct=5),
        max_iterations=3,
        llm=llm,
    )
    assert result.status == "met"
    assert calls["n"] == 0
    assert len(result.iterations) == 1
    assert result.best_index == 0
    assert result.iterations[0].passed
    assert result.plan.buckets[0].target == 60


def test_stops_at_max_iterations_and_keeps_the_best():
    count = 260
    spy = [100 + 10 * i / (count - 1) for i in range(count)]
    vea = [100 + 80 * i / (count - 1) for i in range(count)]
    plan = _plan(_sleeves(100, 0, 0))
    calls = {"n": 0}

    def llm(prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            assert "SPY" in prompt
            assert "CAGR" in prompt
            return _mix(0, 100, 0, rationale="own the stronger market")
        return _mix(50, 50, 0, rationale="split the difference")

    result = improve_plan(
        plan,
        _prices(spy, vea),
        initial_cash=10_000,
        monthly_contribution=0,
        targets=PlanTargets(min_cagr_pct=500),
        max_iterations=3,
        llm=llm,
    )
    assert result.status == "max_iterations"
    assert calls["n"] == 2
    assert len(result.iterations) == 3
    assert result.best_index == 1
    assert result.primary == "min CAGR"
    assert result.plan.buckets[1].target == 100
    assert result.iterations[1].rationale == "own the stronger market"
    assert result.iterations[2].buckets[0]["target"] == 50
    assert result.iterations[1].metrics["cagr_pct"] > result.iterations[0].metrics["cagr_pct"]
    assert result.iterations[1].metrics["cagr_pct"] > result.iterations[2].metrics["cagr_pct"]
    assert plan.buckets[0].target == 100


def test_invalid_llm_json_does_not_crash():
    dates = pd.bdate_range("2020-01-02", "2020-04-30")
    prices = _prices([100.0] * len(dates))
    plan = _plan(_sleeves(100, 0, 0))

    def llm(prompt):
        return "I would raise equities, but here is no JSON."

    result = improve_plan(
        plan,
        prices,
        initial_cash=1000,
        monthly_contribution=0,
        targets=PlanTargets(min_cagr_pct=50),
        max_iterations=2,
        llm=llm,
    )
    assert result.status == "max_iterations"
    assert len(result.iterations) == 2
    assert result.iterations[0].passed is False
    assert "JSON" in result.iterations[0].adjustment_error
    assert result.iterations[1].buckets[0]["target"] == 100
    assert result.plan.buckets[0].target == 100


def test_weight_shift_can_meet_a_trivial_target():
    count = 260
    spy = [100 + 100 * i / (count - 1) for i in range(count)]
    vea = [100.0] * count
    plan = _plan(_sleeves(0, 100, 0), band=5)
    calls = {"n": 0}

    def llm(prompt):
        calls["n"] += 1
        assert "VEA" in prompt
        assert "below" in prompt
        return _mix(100, 0, 0, band=7, rationale="move into the rising market")

    result = improve_plan(
        plan,
        _prices(spy, vea),
        initial_cash=10_000,
        monthly_contribution=0,
        targets=PlanTargets(min_cagr_pct=10),
        max_iterations=4,
        llm=llm,
    )
    assert result.status == "met"
    assert calls["n"] == 1
    assert len(result.iterations) == 2
    assert result.iterations[0].passed is False
    assert result.iterations[1].passed
    assert result.best_index == 1
    assert result.plan.buckets[0].target == 100
    assert result.plan.rebalance_band_pct == 7
    assert plan.buckets[0].target == 0
    assert plan.rebalance_band_pct == 5


def test_llm_error_keeps_the_completed_backtest():
    dates = pd.bdate_range("2020-01-02", "2020-03-31")
    prices = _prices([100.0] * len(dates))
    plan = _plan(_sleeves(100, 0, 0))

    def llm(prompt):
        raise RuntimeError("connection refused")

    result = improve_plan(
        plan,
        prices,
        initial_cash=1000,
        monthly_contribution=0,
        targets=PlanTargets(min_cagr_pct=25),
        max_iterations=3,
        llm=llm,
    )
    assert result.status == "llm_error"
    assert len(result.iterations) == 1
    assert result.iterations[0].metrics.get("cagr_pct") is not None
    assert "connection refused" in result.iterations[0].adjustment_error
    assert result.best_index == 0


def test_drawdown_ceiling_stops_without_the_model_when_already_inside():
    dates = pd.bdate_range("2020-01-02", periods=40)
    spy = [100.0] + [40.0] * (len(dates) - 1)
    plan = _plan([Slice("Local equity", 100, 0, 100)])
    calls = {"n": 0}

    def llm(prompt):
        calls["n"] += 1
        return "{}"

    loose = improve_plan(
        plan,
        _prices(spy),
        initial_cash=1000,
        monthly_contribution=0,
        targets=PlanTargets(max_drawdown_pct=80),
        max_iterations=3,
        llm=llm,
    )
    tight = improve_plan(
        plan,
        _prices(spy),
        initial_cash=1000,
        monthly_contribution=0,
        targets=PlanTargets(max_drawdown_pct=10),
        max_iterations=1,
        llm=llm,
    )
    assert loose.status == "met"
    assert loose.iterations[0].passed
    assert tight.status == "max_iterations"
    assert tight.iterations[0].passed is False
    assert "10" in tight.iterations[0].failures[0]
    assert calls["n"] == 0
