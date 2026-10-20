"""Backtest a plan, ask an LLM to revise the sleeve mix, and repeat until a target or the cap."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from planning.backtest import SLEEVE_PROXIES, run_plan_backtest
from planning.model import Plan, Slice

# First enabled target is the one used to rank iterations when none of them pass.
_PRIMARY = (
    ("min_cagr_pct", "cagr_pct", "min CAGR", True),
    ("max_drawdown_pct", "max_drawdown_pct", "max drawdown", False),
    ("min_sharpe", "sharpe", "min Sharpe", True),
    ("min_total_return_pct", "total_return_pct", "min total return", True),
)
_METRIC_LINES = (
    "final_equity",
    "total_return_pct",
    "cagr_pct",
    "annual_vol_pct",
    "sharpe",
    "max_drawdown_pct",
    "benchmark_return_pct",
    "rebalances",
    "contributed",
)
MAX_ITERATIONS = 8


@dataclass(frozen=True)
class PlanTargets:
    """Pass rules. None means that rule is off. At least one must be set."""

    min_cagr_pct: float | None = None
    max_drawdown_pct: float | None = None
    min_sharpe: float | None = None
    min_total_return_pct: float | None = None

    def enabled(self) -> bool:
        return any(getattr(self, name) is not None for name, *_rest in _PRIMARY)


@dataclass
class IterationRecord:
    number: int
    metrics: dict[str, Any]
    buckets: list[dict[str, Any]]
    rebalance_band_pct: float
    rationale: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    adjustment_error: str = ""


@dataclass
class OptimizeResult:
    iterations: list[IterationRecord]
    best_index: int
    status: str
    plan: Plan
    primary: str


def primary_target_name(targets: PlanTargets) -> str:
    for name, _metric, label, _higher in _PRIMARY:
        if getattr(targets, name) is not None:
            return label
    return ""


def improve_plan(
    plan: Plan,
    prices,
    initial_cash: float,
    monthly_contribution: float,
    targets: PlanTargets,
    max_iterations: int,
    llm: Callable[[str], str],
    on_iteration: Callable[[IterationRecord], None] | None = None,
) -> OptimizeResult:
    """
    Run up to max_iterations backtests.

    Iteration 1 is the plan as given. Later iterations apply an LLM sleeve mix
    when the targets are still missed and iterations remain. The returned plan
    is not written to disk.
    """
    if not targets.enabled():
        raise ValueError("Set at least one target.")
    if max_iterations < 1:
        raise ValueError("Max iterations must be at least 1.")
    max_iterations = min(int(max_iterations), MAX_ITERATIONS)

    working = copy.deepcopy(plan)
    iterations: list[IterationRecord] = []
    best_index = 0
    best_score: tuple[int, float] | None = None
    status = "max_iterations"
    incoming_rationale = ""

    for number in range(1, max_iterations + 1):
        backtest = run_plan_backtest(
            working,
            prices,
            initial_cash,
            monthly_contribution,
        )
        passed, failures = score_backtest(backtest.metrics, targets)
        record = IterationRecord(
            number=number,
            metrics=dict(backtest.metrics),
            buckets=[row.to_dict() for row in working.buckets],
            rebalance_band_pct=float(working.rebalance_band_pct),
            rationale=incoming_rationale,
            passed=passed,
            failures=failures,
        )
        incoming_rationale = ""
        iterations.append(record)
        score = _primary_score(backtest.metrics, targets)
        if best_score is None or score > best_score:
            best_score = score
            best_index = len(iterations) - 1
        if on_iteration is not None:
            on_iteration(record)
        if passed:
            best_index = len(iterations) - 1
            status = "met"
            break
        if number == max_iterations:
            status = "max_iterations"
            break

        try:
            reply = llm(_prompt(working, backtest.metrics, failures, targets))
        except Exception as exc:
            record.adjustment_error = str(exc) or "The model call failed."
            status = "llm_error"
            break
        model_error = _llm_failure(reply)
        if model_error:
            record.adjustment_error = model_error
            status = "llm_error"
            break
        try:
            sleeves, band, rationale = _parse_adjustment(working, reply)
        except ValueError as exc:
            record.adjustment_error = str(exc)
            continue
        working.buckets = sleeves
        working.rebalance_band_pct = band
        incoming_rationale = rationale

    chosen = iterations[best_index]
    return OptimizeResult(
        iterations=iterations,
        best_index=best_index,
        status=status,
        plan=_plan_with_mix(plan, chosen),
        primary=primary_target_name(targets),
    )


def score_backtest(metrics: dict[str, Any], targets: PlanTargets) -> tuple[bool, list[str]]:
    """Return whether every enabled target passes, plus a gap for each miss."""
    failures: list[str] = []
    if targets.min_cagr_pct is not None:
        _at_least(failures, "CAGR", metrics.get("cagr_pct"), targets.min_cagr_pct, "%")
    if targets.max_drawdown_pct is not None:
        _at_most(
            failures,
            "Max drawdown",
            metrics.get("max_drawdown_pct"),
            targets.max_drawdown_pct,
            "%",
        )
    if targets.min_sharpe is not None:
        _at_least(failures, "Sharpe", metrics.get("sharpe"), targets.min_sharpe, "")
    if targets.min_total_return_pct is not None:
        _at_least(
            failures,
            "Total return",
            metrics.get("total_return_pct"),
            targets.min_total_return_pct,
            "%",
        )
    return not failures, failures


def _at_least(failures: list[str], label: str, value: Any, floor: float, unit: str) -> None:
    if value is None:
        failures.append(f"{label} is missing, so it cannot clear {floor:g}{unit}.")
        return
    number = float(value)
    if number < floor:
        gap = floor - number
        suffix = " percentage points" if unit == "%" else ""
        failures.append(
            f"{label} {number:.2f}{unit} is below {floor:.2f}{unit} by {gap:.2f}{suffix}."
        )


def _at_most(failures: list[str], label: str, value: Any, ceiling: float, unit: str) -> None:
    if value is None:
        failures.append(f"{label} is missing, so it cannot stay at or below {ceiling:g}{unit}.")
        return
    number = float(value)
    if number > ceiling:
        gap = number - ceiling
        failures.append(
            f"{label} {number:.2f}{unit} is above {ceiling:.2f}{unit} by {gap:.2f} percentage points."
        )


def _primary_score(metrics: dict[str, Any], targets: PlanTargets) -> tuple[int, float]:
    for name, metric, _label, higher in _PRIMARY:
        if getattr(targets, name) is None:
            continue
        value = metrics.get(metric)
        if value is None:
            return (0, 0.0)
        number = float(value)
        return (1, number if higher else -number)
    return (0, 0.0)


def _plan_with_mix(plan: Plan, record: IterationRecord) -> Plan:
    chosen = copy.deepcopy(plan)
    chosen.buckets = [Slice.from_dict(row) for row in record.buckets]
    chosen.rebalance_band_pct = float(record.rebalance_band_pct)
    return chosen


def _prompt(plan: Plan, metrics: dict[str, Any], failures: list[str], targets: PlanTargets) -> str:
    lines = [
        "Revise this ETF sleeve mix so the next backtest can meet the targets.",
        "Sleeve proxies:",
    ]
    for row in plan.buckets:
        proxy = SLEEVE_PROXIES.get(row.name)
        lines.append(f"- {row.name}: {proxy or 'cash, no ETF'}")
    lines.append("Current sleeves, in percent of the portfolio:")
    for row in plan.buckets:
        lines.append(
            f"- {row.name}: target {row.target:g}, floor {row.floor:g}, ceiling {row.ceiling:g}"
        )
    lines.append(f"Rebalance band: {plan.rebalance_band_pct:g} percentage points.")
    lines.append("Backtest metrics:")
    for key in _METRIC_LINES:
        lines.append(f"- {key}: {metrics.get(key)}")
    lines.append("Enabled targets:")
    if targets.min_cagr_pct is not None:
        lines.append(f"- Min CAGR %: {targets.min_cagr_pct:g}")
    if targets.max_drawdown_pct is not None:
        lines.append(f"- Max drawdown % (pass at or below): {targets.max_drawdown_pct:g}")
    if targets.min_sharpe is not None:
        lines.append(f"- Min Sharpe: {targets.min_sharpe:g}")
    if targets.min_total_return_pct is not None:
        lines.append(f"- Min total return %: {targets.min_total_return_pct:g}")
    lines.append("Targets that failed:")
    for item in failures:
        lines.append(f"- {item}")
    names = ", ".join(row.name for row in plan.buckets)
    lines.append(
        "Return ONLY JSON, with no markdown and no other text, in this shape: "
        '{"buckets":[{"name":"Local equity","target":30,"floor":20,"ceiling":40}],'
        '"rebalance_band_pct":5,"rationale":"short reason"}'
    )
    lines.append(
        f"Use exactly these sleeve names, including Cash when it is listed: {names}. "
        "Every target, floor, and ceiling is a number from 0 to 100, and floor <= target <= ceiling. "
        "Targets must sum to 100. Do not use leverage, shorting, or weights outside 0 to 100. "
        "rebalance_band_pct is optional and must be from 0 to 50 when you include it."
    )
    return "\n".join(lines)


def _llm_failure(text: str) -> str | None:
    stripped = (text or "").strip()
    if not stripped:
        return "The model returned an empty response."
    head = stripped.lower()
    if head.startswith("llm error"):
        return stripped
    if head.startswith("no valid ") or head.startswith("could not reach ollama"):
        return stripped
    if head.startswith("unknown llm provider"):
        return stripped
    return None


def _parse_adjustment(plan: Plan, text: str) -> tuple[list[Slice], float, str]:
    payload = _json_object(text)
    raw_rows = payload.get("buckets")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("The model JSON needs a buckets list.")
    expected = [row.name for row in plan.buckets]
    parsed: dict[str, Slice] = {}
    for item in raw_rows:
        if not isinstance(item, dict):
            raise ValueError("Each bucket must be an object.")
        name = str(item.get("name") or "").strip()
        if name not in expected:
            raise ValueError(f"Unknown sleeve '{name}'. Use {', '.join(expected)}.")
        if name in parsed:
            raise ValueError(f"{name} is listed twice.")
        target = _as_float(item.get("target"), f"{name} target")
        floor = _as_float(item.get("floor"), f"{name} floor")
        ceiling = _as_float(item.get("ceiling"), f"{name} ceiling")
        for label, number in (("target", target), ("floor", floor), ("ceiling", ceiling)):
            if number < 0 or number > 100:
                raise ValueError(f"{name} {label} must be between 0 and 100.")
        if floor > target or target > ceiling:
            raise ValueError(f"{name}: target must sit between floor and ceiling.")
        parsed[name] = Slice(name, round(target, 4), round(floor, 4), round(ceiling, 4))
    missing = [name for name in expected if name not in parsed]
    if missing:
        raise ValueError("Missing sleeves: " + ", ".join(missing) + ".")
    total = sum(parsed[name].target for name in expected)
    if abs(total - 100) > 0.5:
        raise ValueError(f"Targets sum to {total:.2f}, and they must sum to 100.")
    band = float(plan.rebalance_band_pct)
    if "rebalance_band_pct" in payload and payload["rebalance_band_pct"] is not None:
        band = _as_float(payload["rebalance_band_pct"], "rebalance_band_pct")
        if band < 0 or band > 50:
            raise ValueError("Rebalance band must be between 0 and 50.")
        band = round(band, 4)
    rationale = payload.get("rationale") or ""
    if not isinstance(rationale, str):
        rationale = str(rationale)
    return [parsed[name] for name in expected], band, rationale.strip()


def _json_object(text: str) -> dict[str, Any]:
    start = text.find("{")
    if start < 0:
        raise ValueError("The model did not return JSON.")
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    payload = json.loads(text[start:index + 1])
                except json.JSONDecodeError as exc:
                    raise ValueError("The model did not return JSON.") from exc
                if not isinstance(payload, dict):
                    raise ValueError("The model JSON must be an object.")
                return payload
    raise ValueError("The model did not return JSON.")


def _as_float(value: Any, label: str) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{label} must be a number.")
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError as exc:
            raise ValueError(f"{label} must be a number.") from exc
    else:
        raise ValueError(f"{label} must be a number.")
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError(f"{label} must be a finite number.")
    return number
