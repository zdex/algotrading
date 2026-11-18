"""Portfolio cash and plan accounts.

A plan is an account. Its capital is cash taken from the portfolio's total
funds, as a dollar amount or as a percent of those funds. The sum of every
plan's capital stays within the portfolio total. Cash that no plan has taken
stays unallocated.

Initial funds are the reference balance. They rise when more cash is assigned
or topped up, and they stay put when cash moves back to the unallocated pool.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from planning.model import Plan
from planning.store import DEFAULT_DIR


class FundError(ValueError):
    """The assignment does not fit the cash that is still available."""


def money(value: float | str | Decimal) -> float:
    quantized = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(quantized)


def _cents(value: float) -> int:
    return int(Decimal(str(money(value))).scaleb(2))


@dataclass
class PortfolioFunds:
    initial_funds: float = 0
    currency: str = "USD"
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "initial_funds": self.initial_funds,
            "currency": self.currency,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "PortfolioFunds":
        return cls(
            initial_funds=float(raw.get("initial_funds") or 0),
            currency=str(raw.get("currency") or "USD"),
            updated_at=str(raw.get("updated_at") or ""),
        )


class FundsStore:
    def __init__(self, directory: str | Path | None = None):
        self.directory = Path(directory) if directory else DEFAULT_DIR
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "_funds.json"

    def load(self) -> PortfolioFunds:
        if not self.path.exists():
            return PortfolioFunds()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return PortfolioFunds()
        if not isinstance(payload, dict):
            return PortfolioFunds()
        return PortfolioFunds.from_dict(payload)

    def save(self, funds: PortfolioFunds) -> PortfolioFunds:
        funds.initial_funds = money(funds.initial_funds)
        funds.updated_at = datetime.now().replace(microsecond=0).isoformat()
        self.path.write_text(json.dumps(funds.to_dict(), indent=2), encoding="utf-8")
        return funds


def allocated_total(plans: list[Plan]) -> float:
    return money(sum(plan.capital for plan in plans))


def unallocated_cash(funds: PortfolioFunds, plans: list[Plan]) -> float:
    return money(funds.initial_funds - allocated_total(plans))


def set_total_funds(funds: PortfolioFunds, amount: float, plans: list[Plan]) -> None:
    """Set the opening balance. After a plan holds cash, add a top-up instead."""
    amount = money(amount)
    if amount <= 0:
        raise FundError("Total funds must be greater than zero.")
    used = allocated_total(plans)
    if _cents(amount) < _cents(used):
        raise FundError(
            f"Plans already hold {used:,.2f}. The portfolio total has to cover that."
        )
    if _cents(used) > 0 and _cents(amount) < _cents(funds.initial_funds):
        raise FundError("Initial funds stay on record. Top up the portfolio to add cash.")
    funds.initial_funds = amount


def top_up_portfolio(funds: PortfolioFunds, amount: float) -> None:
    amount = money(amount)
    if amount <= 0:
        raise FundError("A top-up has to be more than zero.")
    funds.initial_funds = money(funds.initial_funds + amount)


def capital_for(
    mode: str,
    cash: float,
    percent: float,
    portfolio_initial: float,
    *,
    allow_zero: bool = False,
) -> tuple[float, float]:
    """Return (capital, percent) for a cash amount or a percent of portfolio funds."""
    normalized = mode.strip().lower()
    if normalized not in {"percent", "cash"}:
        raise FundError("Allocate by cash or by percent.")
    if _cents(portfolio_initial) <= 0:
        zero_request = (normalized == "percent" and money(percent) == 0) or (
            normalized == "cash" and money(cash) == 0
        )
        if allow_zero and zero_request:
            return 0.0, 0.0
        raise FundError("Set the portfolio's total funds before allocating a plan.")
    if normalized == "percent":
        percent = money(percent)
        if percent < 0 or percent > 100:
            raise FundError("Enter a percent from 0 to 100.")
        if percent == 0 and not allow_zero:
            raise FundError("Enter a percent greater than zero.")
        capital = money(Decimal(str(portfolio_initial)) * Decimal(str(percent)) / Decimal(100))
        return capital, percent
    cash = money(cash)
    if cash < 0:
        raise FundError("Cash allocation cannot be negative.")
    if cash == 0 and not allow_zero:
        raise FundError("Enter a cash amount greater than zero.")
    stored_percent = money(Decimal(str(cash)) / Decimal(str(portfolio_initial)) * Decimal(100))
    return cash, stored_percent


def ensure_fits(plans: list[Plan], plan_id: str, new_capital: float, portfolio_initial: float) -> None:
    others = money(sum(plan.capital for plan in plans if plan.id != plan_id))
    if _cents(others) + _cents(new_capital) > _cents(portfolio_initial):
        left = money(portfolio_initial - others)
        raise FundError(
            f"This would put {money(others + new_capital):,.2f} across plans. "
            f"The portfolio has {portfolio_initial:,.2f}, with {max(left, 0):,.2f} still unallocated."
        )


def assign_plan_capital(
    plan: Plan,
    plans: list[Plan],
    funds: PortfolioFunds,
    mode: str,
    cash: float,
    percent: float,
    *,
    allow_zero: bool = False,
) -> None:
    """Point the plan account at cash taken from the portfolio. Initial funds never fall."""
    if plan.currency and funds.currency and plan.currency.upper() != funds.currency.upper():
        raise FundError("This plan's currency has to match the portfolio funds.")
    capital, stored_percent = capital_for(
        mode, cash, percent, funds.initial_funds, allow_zero=allow_zero,
    )
    ensure_fits(plans, plan.id, capital, funds.initial_funds)
    if _cents(capital) > _cents(plan.initial_funds):
        plan.initial_funds = capital
    plan.capital = capital
    plan.allocation_mode = "percent" if mode.strip().lower() == "percent" else "cash"
    plan.allocation_percent = stored_percent


def top_up_plan(funds: PortfolioFunds, plan: Plan, amount: float) -> None:
    """New cash into one plan. The portfolio total and both initial balances rise."""
    amount = money(amount)
    if amount <= 0:
        raise FundError("A top-up has to be more than zero.")
    if plan.currency and funds.currency and plan.currency.upper() != funds.currency.upper():
        raise FundError("This plan's currency has to match the portfolio funds.")
    funds.initial_funds = money(funds.initial_funds + amount)
    plan.capital = money(plan.capital + amount)
    plan.initial_funds = money(plan.initial_funds + amount)
    plan.allocation_percent = money(
        Decimal(str(plan.capital)) / Decimal(str(funds.initial_funds)) * Decimal(100)
    )
