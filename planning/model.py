"""Investment plan: target mix, holding tags, and drift against a portfolio."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


BUCKETS = (
    "Local equity",
    "Developed global equity",
    "Emerging equity",
    "Fixed income",
    "Gold",
    "Cash",
)
EQUITY_BUCKETS = {
    "Local equity",
    "Developed global equity",
    "Emerging equity",
}
SECTORS = (
    "Technology",
    "Financials",
    "Health Care",
    "Consumer Discretionary",
    "Consumer Staples",
    "Industrials",
    "Energy",
    "Materials",
    "Utilities",
    "Real Estate",
    "Communication Services",
)
HORIZONS = ("1–3 years", "3–7 years", "7–15 years", "15+ years")
STATUSES = ("draft", "active")
UNSET = "—"


@dataclass
class Slice:
    name: str
    target: float
    floor: float
    ceiling: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "target": self.target,
            "floor": self.floor,
            "ceiling": self.ceiling,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Slice":
        return cls(
            name=str(raw.get("name", "")).strip(),
            target=float(raw.get("target", 0) or 0),
            floor=float(raw.get("floor", 0) or 0),
            ceiling=float(raw.get("ceiling", 0) or 0),
        )


def _band(target: float, down: float = 5, up: float = 7) -> tuple[float, float]:
    return max(0.0, target - down), min(100.0, target + up)


def default_buckets() -> list[Slice]:
    targets = {
        "Local equity": 30,
        "Developed global equity": 35,
        "Emerging equity": 10,
        "Fixed income": 10,
        "Gold": 5,
        "Cash": 10,
    }
    return [Slice(name, float(target), *_band(target)) for name, target in targets.items()]


def default_sectors() -> list[Slice]:
    targets = {
        "Technology": 18,
        "Financials": 14,
        "Health Care": 12,
        "Consumer Discretionary": 10,
        "Industrials": 10,
        "Communication Services": 8,
        "Consumer Staples": 8,
        "Energy": 6,
        "Materials": 5,
        "Utilities": 5,
        "Real Estate": 4,
    }
    return [Slice(name, float(target), *_band(target)) for name, target in targets.items()]


@dataclass
class Plan:
    id: str
    name: str
    purpose: str = "Long-term growth"
    horizon: str = "7–15 years"
    status: str = "draft"
    currency: str = "USD"
    buckets: list[Slice] = field(default_factory=default_buckets)
    sectors: list[Slice] = field(default_factory=default_sectors)
    max_single_name_pct: float = 8
    max_sector_pct: float = 25
    rebalance_band_pct: float = 5
    review_date: str = ""
    monthly_contribution: float = 0
    notes: str = ""
    classifications: dict[str, dict[str, str]] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "purpose": self.purpose,
            "horizon": self.horizon,
            "status": self.status,
            "currency": self.currency,
            "buckets": [row.to_dict() for row in self.buckets],
            "sectors": [row.to_dict() for row in self.sectors],
            "rules": {
                "max_single_name_pct": self.max_single_name_pct,
                "max_sector_pct": self.max_sector_pct,
                "rebalance_band_pct": self.rebalance_band_pct,
                "review_date": self.review_date,
                "monthly_contribution": self.monthly_contribution,
                "notes": self.notes,
            },
            "classifications": self.classifications,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Plan":
        rules = raw.get("rules") or {}
        tags = raw.get("classifications") or {}
        clean_tags: dict[str, dict[str, str]] = {}
        if isinstance(tags, dict):
            for symbol, tag in tags.items():
                if not isinstance(tag, dict):
                    continue
                clean_tags[str(symbol).upper()] = {
                    "bucket": str(tag.get("bucket") or ""),
                    "sector": str(tag.get("sector") or ""),
                }
        return cls(
            id=str(raw.get("id") or ""),
            name=str(raw.get("name") or "Untitled plan"),
            purpose=str(raw.get("purpose") or ""),
            horizon=str(raw.get("horizon") or HORIZONS[2]),
            status=str(raw.get("status") or "draft"),
            currency=str(raw.get("currency") or "USD"),
            buckets=[Slice.from_dict(row) for row in raw.get("buckets") or []],
            sectors=[Slice.from_dict(row) for row in raw.get("sectors") or []],
            max_single_name_pct=float(rules.get("max_single_name_pct", 8) or 0),
            max_sector_pct=float(rules.get("max_sector_pct", 25) or 0),
            rebalance_band_pct=float(rules.get("rebalance_band_pct", 5) or 0),
            review_date=str(rules.get("review_date") or ""),
            monthly_contribution=float(rules.get("monthly_contribution") or 0),
            notes=str(rules.get("notes") or ""),
            classifications=clean_tags,
            created_at=str(raw.get("created_at") or ""),
            updated_at=str(raw.get("updated_at") or ""),
        )


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "plan"


def new_plan(name: str, plan_id: str) -> Plan:
    now = datetime.now().replace(microsecond=0).isoformat()
    return Plan(id=plan_id, name=name.strip(), created_at=now, updated_at=now)


def parse_money(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", value.replace(",", ""))
    if cleaned in {"", "-", ".", "-."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def slice_errors(rows: list[Slice], label: str) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not row.name:
            errors.append(f"{label}: every row needs a name.")
            continue
        key = row.name.casefold()
        if key in seen:
            errors.append(f"{label}: '{row.name}' is listed twice.")
        seen.add(key)
        if row.floor < 0 or row.ceiling > 100 or row.target < 0 or row.target > 100:
            errors.append(f"{row.name}: percentages must be between 0 and 100.")
        if row.floor > row.target or row.target > row.ceiling:
            errors.append(f"{row.name}: target must sit between floor and ceiling.")
    return errors


def _status(actual: float | None, row: Slice, band: float) -> str:
    if actual is None:
        return "unknown"
    if actual < row.floor:
        return "below floor"
    if actual > row.ceiling:
        return "above ceiling"
    if abs(actual - row.target) <= band:
        return "in band"
    if actual < row.target:
        return "underweight"
    return "overweight"


def _pct(value: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return value / total * 100


def portfolio_nav(summary: dict[str, Any], holdings_value: float) -> tuple[float | None, float | None]:
    """Return (nav, cash). Cash is nav minus holdings when nav is known and larger."""
    nav = None
    for key in ("NetLiquidation", "Net liquidation", "net_liquidation"):
        if key in summary:
            nav = parse_money(summary[key])
            if nav is not None:
                break
    if nav is None or nav <= 0:
        return None, None
    cash = max(0.0, nav - holdings_value)
    return nav, cash


def allocation_drift(
    plan: Plan,
    positions: list[dict[str, Any]],
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare tagged holdings with the plan. Weights are percent of NAV when NAV is known."""
    summary = summary or {}
    values: dict[str, float] = {}
    for row in positions:
        symbol = str(row.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        market_value = row.get("market_value")
        if market_value is None:
            qty = float(row.get("qty") or 0)
            price = float(row.get("market_price") or 0)
            market_value = qty * price
        values[symbol] = values.get(symbol, 0.0) + float(market_value or 0)

    holdings_value = sum(values.values())
    nav, cash = portfolio_nav(summary, holdings_value)
    basis = nav if nav is not None else holdings_value
    basis_label = "nav" if nav is not None else "holdings"

    bucket_value = {row.name: 0.0 for row in plan.buckets}
    sector_value: dict[str, float] = {row.name: 0.0 for row in plan.sectors}
    equity_value = 0.0
    unclassified: list[str] = []

    for symbol, amount in values.items():
        tag = plan.classifications.get(symbol) or {}
        bucket = (tag.get("bucket") or "").strip()
        sector = (tag.get("sector") or "").strip()
        if not bucket:
            unclassified.append(symbol)
            continue
        bucket_value[bucket] = bucket_value.get(bucket, 0.0) + amount
        if bucket in EQUITY_BUCKETS:
            equity_value += amount
            if sector:
                sector_value[sector] = sector_value.get(sector, 0.0) + amount

    if "Cash" in bucket_value and cash is not None:
        bucket_value["Cash"] += cash

    band = plan.rebalance_band_pct
    rows = []
    for slice_row in plan.buckets:
        amount = bucket_value.get(slice_row.name, 0.0)
        actual = None if basis <= 0 or (slice_row.name == "Cash" and cash is None and amount == 0) else _pct(amount, basis)
        if slice_row.name == "Cash" and cash is None and amount == 0:
            actual = None
        gap = None if actual is None else actual - slice_row.target
        rows.append({
            "name": slice_row.name,
            "target": slice_row.target,
            "floor": slice_row.floor,
            "ceiling": slice_row.ceiling,
            "actual": actual,
            "gap": gap,
            "status": _status(actual, slice_row, band),
        })

    extra_buckets = [name for name in bucket_value if name not in {row.name for row in plan.buckets} and bucket_value[name] > 0]
    for name in extra_buckets:
        actual = _pct(bucket_value[name], basis) if basis > 0 else 0.0
        rows.append({
            "name": name,
            "target": 0.0,
            "floor": 0.0,
            "ceiling": 0.0,
            "actual": actual,
            "gap": actual,
            "status": "unplanned",
        })

    sector_rows = []
    equity_basis = equity_value
    known_sectors = {row.name for row in plan.sectors}
    for slice_row in plan.sectors:
        amount = sector_value.get(slice_row.name, 0.0)
        actual = None if equity_basis <= 0 else _pct(amount, equity_basis)
        gap = None if actual is None else actual - slice_row.target
        sector_rows.append({
            "name": slice_row.name,
            "target": slice_row.target,
            "floor": slice_row.floor,
            "ceiling": slice_row.ceiling,
            "actual": actual,
            "gap": gap,
            "status": _status(actual, slice_row, band),
            "portfolio_pct": None if basis <= 0 else _pct(amount, basis),
        })
    for name, amount in sector_value.items():
        if name in known_sectors or amount <= 0:
            continue
        actual = _pct(amount, equity_basis) if equity_basis > 0 else 0.0
        sector_rows.append({
            "name": name,
            "target": 0.0,
            "floor": 0.0,
            "ceiling": 0.0,
            "actual": actual,
            "gap": actual,
            "status": "unplanned",
            "portfolio_pct": None if basis <= 0 else _pct(amount, basis),
        })

    names = []
    for symbol, amount in sorted(values.items()):
        weight = _pct(amount, basis) if basis > 0 else 0.0
        names.append({
            "symbol": symbol,
            "market_value": amount,
            "weight": weight,
            "over_cap": weight > plan.max_single_name_pct,
        })

    fill_next = [
        row["name"]
        for row in sorted(
            (row for row in rows if row["gap"] is not None and row["gap"] < -band),
            key=lambda row: row["gap"],
        )
    ]

    return {
        "nav": nav,
        "cash": cash,
        "holdings_value": holdings_value,
        "basis": basis_label,
        "rows": rows,
        "sectors": sector_rows,
        "names": names,
        "unclassified": sorted(unclassified),
        "fill_next": fill_next,
        "equity_value": equity_value,
    }
