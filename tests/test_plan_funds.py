"""Plan accounts draw cash from one portfolio total and keep their initial funds."""

import pytest

from planning.funds import (
    FundError,
    FundsStore,
    allocated_total,
    assign_plan_capital,
    set_total_funds,
    top_up_plan,
    top_up_portfolio,
    unallocated_cash,
)
from planning.store import PlanStore


def _open(tmp_path, amount=100_000):
    plans = PlanStore(tmp_path)
    funds = FundsStore(tmp_path)
    book = funds.load()
    set_total_funds(book, amount, plans.list_plans())
    funds.save(book)
    return plans, funds


def test_three_plans_leave_the_rest_in_cash(tmp_path):
    plans, funds = _open(tmp_path)
    book = funds.load()
    created = []
    for name, cash in (("Plan A", 20_000), ("Plan B", 30_000), ("Plan C", 15_000)):
        plan = plans.create(name)
        assign_plan_capital(plan, plans.list_plans(), book, "cash", cash, 0)
        plans.save(plan)
        created.append(plan)

    stored = [plans.load(plan.id) for plan in created]
    assert [plan.capital for plan in stored] == [20_000, 30_000, 15_000]
    assert [plan.initial_funds for plan in stored] == [20_000, 30_000, 15_000]
    assert allocated_total(plans.list_plans()) == 65_000
    assert unallocated_cash(book, plans.list_plans()) == 35_000
    assert funds.load().initial_funds == 100_000


def test_percent_allocation_uses_the_portfolio_total(tmp_path):
    plans, funds = _open(tmp_path)
    book = funds.load()
    plan = plans.create("Aggressive")
    assign_plan_capital(plan, plans.list_plans(), book, "percent", 0, 20)
    plans.save(plan)
    assert plans.load(plan.id).capital == 20_000
    assert plans.load(plan.id).allocation_percent == 20


def test_plans_cannot_take_more_than_the_portfolio(tmp_path):
    plans, funds = _open(tmp_path)
    book = funds.load()
    for name, cash in (("Plan A", 20_000), ("Plan B", 30_000), ("Plan C", 15_000)):
        plan = plans.create(name)
        assign_plan_capital(plan, plans.list_plans(), book, "cash", cash, 0)
        plans.save(plan)
    extra = plans.create("Plan D")
    with pytest.raises(FundError, match="still unallocated"):
        assign_plan_capital(extra, plans.list_plans(), book, "cash", 40_000, 0)
    assert unallocated_cash(book, plans.list_plans()) == 35_000


def test_initial_funds_stay_when_cash_moves_back(tmp_path):
    plans, funds = _open(tmp_path)
    book = funds.load()
    plan = plans.create("Plan A")
    assign_plan_capital(plan, plans.list_plans(), book, "cash", 20_000, 0)
    plans.save(plan)
    assign_plan_capital(plan, plans.list_plans(), book, "cash", 15_000, 0, allow_zero=True)
    plans.save(plan)
    stored = plans.load(plan.id)
    assert stored.capital == 15_000
    assert stored.initial_funds == 20_000
    assert unallocated_cash(book, plans.list_plans()) == 85_000


def test_assigning_more_cash_raises_initial_funds(tmp_path):
    plans, funds = _open(tmp_path)
    book = funds.load()
    plan = plans.create("Plan A")
    assign_plan_capital(plan, plans.list_plans(), book, "cash", 20_000, 0)
    assign_plan_capital(plan, plans.list_plans(), book, "cash", 22_000, 0)
    assert plan.capital == 22_000
    assert plan.initial_funds == 22_000


def test_portfolio_topup_increases_only_the_portfolio_initial(tmp_path):
    plans, funds = _open(tmp_path)
    book = funds.load()
    plan = plans.create("Plan A")
    assign_plan_capital(plan, plans.list_plans(), book, "cash", 20_000, 0)
    plans.save(plan)
    top_up_portfolio(book, 10_000)
    funds.save(book)
    assert funds.load().initial_funds == 110_000
    assert plans.load(plan.id).initial_funds == 20_000
    assert plans.load(plan.id).capital == 20_000
    assert unallocated_cash(funds.load(), plans.list_plans()) == 90_000


def test_plan_topup_increases_portfolio_and_plan_initial_funds(tmp_path):
    plans, funds = _open(tmp_path)
    book = funds.load()
    plan = plans.create("Plan A")
    assign_plan_capital(plan, plans.list_plans(), book, "cash", 20_000, 0)
    top_up_plan(book, plan, 5_000)
    plans.save(plan)
    funds.save(book)
    stored = plans.load(plan.id)
    assert stored.capital == 25_000
    assert stored.initial_funds == 25_000
    assert funds.load().initial_funds == 105_000
    assert unallocated_cash(funds.load(), plans.list_plans()) == 80_000


def test_opening_total_can_be_replaced_before_any_plan_is_funded(tmp_path):
    plans, funds = _open(tmp_path, 150_000)
    book = funds.load()
    set_total_funds(book, 100_000, plans.list_plans())
    assert book.initial_funds == 100_000
    plan = plans.create("Plan A")
    assign_plan_capital(plan, plans.list_plans(), book, "cash", 20_000, 0)
    plans.save(plan)
    with pytest.raises(FundError, match="stay on record"):
        set_total_funds(book, 90_000, plans.list_plans())


def test_funds_file_is_not_a_plan(tmp_path):
    plans, funds = _open(tmp_path)
    assert funds.path.name.startswith("_")
    assert plans.list_plans() == []


def test_saved_plan_without_an_account_loads_with_zero_capital(tmp_path):
    import json

    plans = PlanStore(tmp_path)
    plan = plans.create("Legacy")
    payload_path = plans.path_for(plan.id)
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload.pop("account")
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = plans.load(plan.id)
    assert loaded.capital == 0
    assert loaded.initial_funds == 0
