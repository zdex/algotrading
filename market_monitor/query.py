"""Filters, calendars, exposure, and alert matching. No Streamlit here."""

from __future__ import annotations

from datetime import datetime, timezone

from market_monitor.catalog import DEMO_HOLDINGS
from market_monitor.model import Event, Holding
from market_monitor.scoring import SEVERITY_RANK, exposure_bucket, priority_band, priority_score


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def freshness(retrieved_at: str, now: datetime) -> str:
    parsed = parse_time(retrieved_at)
    if parsed is None:
        return "unknown"
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    age_days = (now - parsed).total_seconds() / 86400
    if age_days > 3:
        return "stale"
    if age_days > 1:
        return "aging"
    return "fresh"


def format_dual_time(iso: str | None, event_tz: str, display_tz: str) -> str:
    parsed = parse_time(iso)
    if parsed is None:
        return "—"
    from zoneinfo import ZoneInfo

    local = parsed.astimezone(ZoneInfo(event_tz))
    shown = parsed.astimezone(ZoneInfo(display_tz))
    if event_tz == display_tz:
        return shown.strftime("%Y-%m-%d %H:%M %Z")
    return f"{shown.strftime('%Y-%m-%d %H:%M %Z')} · {local.strftime('%H:%M %Z')} event zone"


def exposure_pct(event: Event, holdings: list[Holding] | tuple[Holding, ...]) -> float | None:
    if not holdings:
        return None
    matched = [
        row.weight_pct
        for row in holdings
        if row.symbol in event.instruments and row.symbol != "CASH"
    ]
    if not matched:
        return None
    return round(sum(matched), 2)


def holdings_from_positions(positions: list[dict], source: str) -> list[Holding]:
    rows = []
    values = []
    for position in positions:
        symbol = str(position.get("symbol") or "").upper()
        if not symbol:
            continue
        value = position.get("market_value")
        try:
            value_f = float(value) if value is not None else 0.0
        except (TypeError, ValueError):
            value_f = 0.0
        values.append(value_f)
        rows.append((symbol, value_f, position))
    total = sum(value for value in values if value > 0)
    holdings: list[Holding] = []
    for symbol, value, position in rows:
        weight = (value / total * 100) if total else None
        holdings.append(Holding(
            symbol=symbol,
            name=str(position.get("name") or symbol),
            sector=str(position.get("sector") or "Unknown"),
            country=str(position.get("country") or "Unknown"),
            asset_class=str(position.get("asset_class") or "Equity"),
            weight_pct=round(weight, 2) if weight is not None else 0.0,
            market_value=value,
            source=source,
        ))
    return holdings


def resolve_book(choice: str, paper_positions: list[dict] | None, manual: list[dict] | None) -> tuple[list[Holding], str]:
    if choice == "none":
        return [], "Holdings are unavailable. Exposure is unknown, not zero."
    if choice == "paper":
        holdings = holdings_from_positions(paper_positions or [], "paper")
        if not holdings:
            return [], "The paper book has no positions. Exposure is unknown, not zero."
        return holdings, "Weights use the paper book market values. Sector labels are unknown unless the file has them."
    if choice == "manual":
        holdings = holdings_from_positions(manual or [], "manual")
        if not holdings:
            return [], "No manual holdings yet. Exposure is unknown, not zero."
        return holdings, "Manual holdings entered on Portfolio Health. Simulated prices are not attached."
    return list(DEMO_HOLDINGS), "Demo book, $1,000,000 simulated NAV. Not your account."


def event_priority(event: Event, holdings: list[Holding] | tuple[Holding, ...], thresholds: dict | None = None) -> dict:
    weight = exposure_pct(event, holdings)
    bucket = exposure_bucket(weight)
    score, status = priority_score(event.impact, event.probability, bucket, event.urgency, event.reliability)
    return {
        "exposure_pct": weight,
        "score": None if score is None else round(score, 1),
        "status": status,
        "band": priority_band(score, thresholds),
    }


def filter_events(
    events: list[Event],
    *,
    panel: str | None = None,
    category_id: int | None = None,
    geography: str | None = None,
    sector: str | None = None,
    asset: str | None = None,
    severities: list[str] | None = None,
    source: str | None = None,
    text: str | None = None,
    time_from: datetime | None = None,
    time_to: datetime | None = None,
    instruments: list[str] | None = None,
) -> list[Event]:
    query = (text or "").strip().lower()
    selected = set(severities or [])
    wanted = {item.upper() for item in instruments or []}
    matched: list[Event] = []
    for event in events:
        if panel and event.primary_panel != panel:
            continue
        if category_id and event.category_id != category_id:
            continue
        if geography and geography not in event.geography:
            continue
        if sector and sector not in event.sectors:
            continue
        if asset and asset not in event.asset_classes:
            continue
        if severities is not None and event.severity not in selected:
            continue
        if source and not any(source.lower() in item.name.lower() for item in event.sources):
            continue
        if wanted and not wanted.intersection(event.instruments):
            continue
        observed = parse_time(event.observed_at)
        if time_from and observed and observed < time_from:
            continue
        if time_to and observed and observed > time_to:
            continue
        if query:
            blob = " ".join([
                event.title, event.summary, event.event_type, " ".join(event.instruments),
                " ".join(source.name for source in event.sources),
            ]).lower()
            if query not in blob:
                continue
        matched.append(event)
    return matched


def scheduled_events(events: list[Event]) -> list[Event]:
    rows = [event for event in events if event.scheduled_at]
    rows.sort(key=lambda event: event.scheduled_at or "")
    return rows


def risk_feed(events: list[Event]) -> list[tuple[Event, str]]:
    rows: list[tuple[Event, str]] = []
    for event in events:
        if event.primary_panel == "risk":
            rows.append((event, "owned"))
        elif event.severity in ("critical", "high"):
            rows.append((event, "referenced"))
    return rows


def countdown_days(event: Event, now: datetime) -> int | None:
    scheduled = parse_time(event.scheduled_at)
    if scheduled is None:
        return None
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return int((scheduled.date() - now.date()).days)


def rule_matches(event: Event, rule: dict, holdings: list[Holding], now: datetime) -> bool:
    if not rule.get("enabled", True):
        return False
    if rule.get("category_id") and event.category_id != int(rule["category_id"]):
        return False
    geography = rule.get("geography")
    if geography and geography not in event.geography:
        return False
    ticker = (rule.get("ticker") or "").upper()
    if ticker and ticker not in event.instruments:
        return False
    minimum = rule.get("min_severity")
    if minimum and SEVERITY_RANK[event.severity] < SEVERITY_RANK[minimum]:
        return False
    if rule.get("min_surprise") is not None:
        if event.surprise is None or abs(event.surprise) < float(rule["min_surprise"]):
            return False
    if rule.get("min_exposure") is not None:
        weight = exposure_pct(event, holdings)
        if weight is None or weight < float(rule["min_exposure"]):
            return False
    if rule.get("max_days_to_catalyst") is not None:
        days = countdown_days(event, now)
        if days is None or days < 0 or days > int(rule["max_days_to_catalyst"]):
            return False
    return True
