"""Simulated event catalog. Every category event type has one primary record.

A second CPI wire copy shares a dedupe key so repeated reports can be collapsed
without dropping source provenance. Nothing in this module is a live quote.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from market_monitor.model import Event, Holding, Scenario, Source, TimelineEntry
from market_monitor.registry import CATEGORIES, category
from market_monitor.scoring import exposure_bucket

AS_OF = datetime(2026, 10, 16, 21, 0, tzinfo=timezone.utc)
AS_OF_ISO = AS_OF.isoformat()

DEMO_HOLDINGS: tuple[Holding, ...] = (
    Holding("AAPL", "Apple", "Information Technology", "United States", "Equity", 12, 120_000, "demo"),
    Holding("MSFT", "Microsoft", "Information Technology", "United States", "Equity", 11, 110_000, "demo"),
    Holding("NVDA", "NVIDIA", "Information Technology", "United States", "Equity", 10, 100_000, "demo"),
    Holding("JPM", "JPMorgan Chase", "Financials", "United States", "Equity", 8, 80_000, "demo"),
    Holding("XOM", "Exxon Mobil", "Energy", "United States", "Equity", 7, 70_000, "demo"),
    Holding("UNH", "UnitedHealth", "Health Care", "United States", "Equity", 7, 70_000, "demo"),
    Holding("CAT", "Caterpillar", "Industrials", "United States", "Equity", 6, 60_000, "demo"),
    Holding("TLT", "20+ Year Treasury ETF", "Rates", "United States", "Fund", 12, 120_000, "demo"),
    Holding("GLD", "SPDR Gold Shares", "Commodities", "Global", "Commodity", 6, 60_000, "demo"),
    Holding("EEM", "iShares MSCI Emerging Markets", "Multi", "Emerging markets", "Fund", 8, 80_000, "demo"),
    Holding("IBIT", "iShares Bitcoin Trust", "Alternatives", "Global", "Alternative", 4, 40_000, "demo"),
    Holding("EURUSD", "Euro / US dollar", "FX", "Euro area", "FX", 3, 30_000, "demo"),
    Holding("CASH", "Cash", "Cash", "United States", "Cash", 6, 60_000, "demo"),
)

_COMPANIES = (
    ("AAPL", "Apple", "Information Technology"),
    ("MSFT", "Microsoft", "Information Technology"),
    ("NVDA", "NVIDIA", "Information Technology"),
    ("JPM", "JPMorgan Chase", "Financials"),
    ("XOM", "Exxon Mobil", "Energy"),
    ("UNH", "UnitedHealth", "Health Care"),
    ("CAT", "Caterpillar", "Industrials"),
)

_SOURCES = {
    1: ("Simulated BEA / BLS calendar", "demo://bea-bls"),
    2: ("Simulated central-bank calendar", "demo://central-banks"),
    3: ("Simulated company filings", "demo://edgar"),
    4: ("Simulated wire summary", "demo://geo-wire"),
    5: ("Simulated legislative calendar", "demo://fiscal"),
    6: ("Simulated financial-conditions batch", "demo://liquidity"),
    7: ("Simulated equity-analytics batch", "demo://technicals"),
    8: ("Simulated sector brief", "demo://sectors"),
    9: ("Simulated EIA / commodity batch", "demo://eia"),
    10: ("Simulated FX batch", "demo://fx"),
    11: ("Simulated regional brief", "demo://regions"),
    12: ("Simulated credit batch", "demo://credit"),
    13: ("Simulated fund-document batch", "demo://funds"),
    14: ("Simulated governance brief", "demo://governance"),
    15: ("Simulated thematic brief", "demo://themes"),
    16: ("Simulated hazard brief", "demo://hazards"),
    17: ("Simulated political calendar", "demo://elections"),
    18: ("Simulated alternatives batch", "demo://alts"),
    19: ("Simulated exchange calendar", "demo://calendar"),
    20: ("Simulated portfolio risk batch", "demo://portfolio-risk"),
}

_NUMERIC = {1, 2, 3, 6, 7, 8, 9, 10, 12, 13, 18, 20}
_UNITS = {
    1: "%", 2: "%", 3: "USD", 6: "index", 7: "index", 8: "%",
    9: "USD", 10: "rate", 12: "bps", 13: "%", 18: "USD", 20: "%",
}
_BASES = {
    1: 2.4, 2: 4.50, 3: 1.80, 6: 100.0, 7: 52.0, 8: 1.4,
    9: 78.0, 10: 104.0, 12: 115.0, 13: 0.12, 18: 100.0, 20: 8.0,
}
_ASSET = {
    1: ("Equities", "Rates", "FX", "Commodities"),
    2: ("Rates", "FX"),
    3: ("Equities",),
    4: ("Commodities", "FX", "Equities"),
    5: ("Equities", "Rates"),
    6: ("Rates", "Equities"),
    7: ("Equities",),
    8: ("Equities",),
    9: ("Commodities",),
    10: ("FX",),
    11: ("Equities", "FX", "Rates"),
    12: ("Rates", "Credit"),
    13: ("Funds",),
    14: ("Equities",),
    15: ("Equities",),
    16: ("Equities", "Commodities"),
    17: ("Equities", "FX", "Rates"),
    18: ("Alternatives",),
    19: ("Equities", "Funds"),
    20: ("Multi-asset",),
}
_DEFAULT_GEO = {
    1: ("United States",),
    2: ("United States",),
    3: ("United States",),
    4: ("Global",),
    5: ("United States",),
    6: ("United States",),
    7: ("United States",),
    8: ("United States",),
    9: ("Global",),
    10: ("Global",),
    11: ("Global",),
    12: ("United States",),
    13: ("United States",),
    14: ("United States",),
    15: ("Global",),
    16: ("United States",),
    17: ("United States",),
    18: ("Global",),
    19: ("United States",),
    20: ("United States",),
}
_DEFAULT_SECTOR = {
    1: ("Broad market",),
    2: ("Rates",),
    3: ("Broad market",),
    4: ("Energy", "Defense"),
    5: ("Broad market",),
    6: ("Financials",),
    7: ("Broad market",),
    8: ("Broad market",),
    9: ("Energy", "Materials"),
    10: ("FX",),
    11: ("Broad market",),
    12: ("Credit",),
    13: ("Funds",),
    14: ("Broad market",),
    15: ("Information Technology",),
    16: ("Insurance", "Energy"),
    17: ("Broad market",),
    18: ("Alternatives",),
    19: ("Broad market",),
    20: ("Multi-asset",),
}
_DEFAULT_INSTRUMENTS = {
    1: ("TLT", "XOM"),
    2: ("TLT", "JPM"),
    3: ("AAPL",),
    4: ("XOM", "GLD", "EEM"),
    5: ("JPM", "XOM"),
    6: ("TLT", "JPM"),
    7: ("AAPL", "MSFT", "NVDA"),
    8: ("MSFT", "NVDA"),
    9: ("XOM", "GLD"),
    10: ("EURUSD",),
    11: ("EEM",),
    12: ("TLT",),
    13: ("EEM", "IBIT", "TLT"),
    14: ("AAPL",),
    15: ("NVDA", "MSFT"),
    16: ("CAT", "XOM"),
    17: ("EEM",),
    18: ("IBIT",),
    19: ("AAPL", "MSFT"),
    20: ("AAPL", "MSFT", "NVDA", "JPM", "TLT"),
}
_TZ = {
    "United States": "America/New_York",
    "Euro area": "Europe/Berlin",
    "United Kingdom": "Europe/London",
    "Japan": "Asia/Tokyo",
    "India": "Asia/Kolkata",
    "China": "Asia/Shanghai",
    "Taiwan": "Asia/Taipei",
    "Global": "America/New_York",
    "Emerging markets": "America/New_York",
    "Middle East": "Asia/Dubai",
    "Russia": "Europe/Moscow",
    "Ukraine": "Europe/Kyiv",
    "Latin America": "America/Sao_Paulo",
    "Africa": "Africa/Johannesburg",
    "Southeast Asia": "Asia/Singapore",
}

_GEO_RULES = (
    ("ecb", ("Euro area",)),
    ("euro", ("Euro area",)),
    ("eur/", ("Euro area",)),
    ("boe", ("United Kingdom",)),
    ("gbp", ("United Kingdom",)),
    ("boj", ("Japan",)),
    ("yen", ("Japan",)),
    ("japan", ("Japan",)),
    ("rbi", ("India",)),
    ("india", ("India",)),
    ("inr", ("India",)),
    ("pboc", ("China",)),
    ("china", ("China",)),
    ("cny", ("China",)),
    ("taiwan", ("Taiwan",)),
    ("middle east", ("Middle East",)),
    ("russia", ("Russia", "Ukraine")),
    ("ukraine", ("Ukraine",)),
    ("latin america", ("Latin America",)),
    ("africa", ("Africa",)),
    ("southeast asia", ("Southeast Asia",)),
    ("emerging", ("Emerging markets",)),
    ("europe", ("Euro area",)),
    ("global", ("Global",)),
)
_SECTOR_RULES = (
    ("semiconductor", ("Information Technology",)),
    ("cloud", ("Information Technology",)),
    ("gpu", ("Information Technology",)),
    ("software", ("Information Technology",)),
    (" ai", ("Information Technology",)),
    ("financial", ("Financials",)),
    ("bank", ("Financials",)),
    ("deposit", ("Financials",)),
    ("health", ("Health Care",)),
    ("fda", ("Health Care",)),
    ("biotech", ("Health Care",)),
    ("energy", ("Energy",)),
    ("oil", ("Energy",)),
    ("opec", ("Energy",)),
    ("gas", ("Energy",)),
    ("staples", ("Consumer Staples",)),
    ("discretionary", ("Consumer Discretionary",)),
    ("retail", ("Consumer Discretionary",)),
    ("industrial", ("Industrials",)),
    ("transport", ("Industrials",)),
    ("freight", ("Industrials",)),
    ("real estate", ("Real Estate",)),
    ("utilities", ("Utilities",)),
    ("power demand", ("Utilities",)),
    ("material", ("Materials",)),
    ("copper", ("Materials",)),
    ("steel", ("Materials",)),
    ("communication", ("Communication Services",)),
    ("defense", ("Industrials",)),
    ("renewable", ("Utilities",)),
    ("gold", ("Commodities",)),
    ("bitcoin", ("Alternatives",)),
    ("ether", ("Alternatives",)),
    ("crypto", ("Alternatives",)),
    ("private", ("Alternatives",)),
)
_INSTRUMENT_RULES = (
    ("cpi", ("TLT", "XOM")),
    ("pce", ("TLT",)),
    ("ppi", ("XOM", "CAT")),
    ("payroll", ("JPM", "CAT")),
    ("unemployment", ("JPM",)),
    ("wage", ("JPM",)),
    ("jobless", ("JPM",)),
    ("housing", ("CAT",)),
    ("gdp", ("CAT", "MSFT")),
    ("fomc", ("TLT", "JPM", "NVDA")),
    ("dot plot", ("TLT", "NVDA")),
    ("yield", ("TLT",)),
    ("treasury", ("TLT",)),
    ("fed ", ("TLT", "JPM")),
    ("gold", ("GLD", "TLT")),
    ("oil", ("XOM",)),
    ("opec", ("XOM",)),
    ("bitcoin", ("IBIT",)),
    ("ether", ("IBIT",)),
    ("crypto", ("IBIT",)),
    ("stablecoin", ("IBIT",)),
    ("eur/usd", ("EURUSD",)),
    ("dxy", ("EURUSD", "TLT")),
    ("emerging", ("EEM",)),
    ("china", ("EEM", "NVDA")),
    ("india", ("EEM",)),
    ("semiconductor", ("NVDA",)),
    ("gpu", ("NVDA",)),
    (" ai", ("NVDA", "MSFT")),
    ("cloud", ("MSFT",)),
    ("health", ("UNH",)),
    ("fda", ("UNH",)),
    ("financial", ("JPM",)),
    ("bank", ("JPM",)),
    ("industrial", ("CAT",)),
    ("hurricane", ("CAT", "XOM")),
    ("wildfire", ("CAT",)),
    ("drought", ("CAT", "XOM")),
)


def demo_nav() -> float:
    return float(sum(row.market_value for row in DEMO_HOLDINGS))


def _pick_geo(event_type: str, category_id: int) -> tuple[str, ...]:
    lowered = event_type.lower()
    for needle, geo in _GEO_RULES:
        if needle in lowered:
            return geo
    return _DEFAULT_GEO[category_id]


def _pick_sectors(event_type: str, category_id: int, company_sector: str | None) -> tuple[str, ...]:
    if company_sector:
        return (company_sector,)
    lowered = f" {event_type.lower()}"
    for needle, sectors in _SECTOR_RULES:
        if needle in lowered:
            return sectors
    return _DEFAULT_SECTOR[category_id]


def _pick_instruments(event_type: str, category_id: int, company: str | None) -> tuple[str, ...]:
    if company:
        return (company,)
    lowered = f" {event_type.lower()}"
    for needle, symbols in _INSTRUMENT_RULES:
        if needle in lowered:
            return symbols
    return _DEFAULT_INSTRUMENTS[category_id]


def _exposure(symbols: tuple[str, ...]) -> float | None:
    weights = [row.weight_pct for row in DEMO_HOLDINGS if row.symbol in symbols and row.symbol != "CASH"]
    if not weights:
        return None
    return round(sum(weights), 2)


def _scores(category_id: int, index: int, exposure_pct: float | None) -> tuple[int, int, int | None, int, int, str, str]:
    impact = 1 + ((category_id * 3 + index) % 5)
    probability = 1 + ((category_id + index * 2) % 5)
    urgency = 1 + ((category_id * 5 + index * 3) % 5)
    reliability = 3 + (index % 3)
    if index % 29 == 0:
        impact, urgency = 5, 5
    if index % 11 == 0:
        verification = "unconfirmed"
    elif index % 7 == 0:
        verification = "developing"
    else:
        verification = "verified"
    rank = impact + urgency
    if impact >= 5 and urgency >= 5:
        severity = "critical"
    elif rank >= 8:
        severity = "high"
    elif rank >= 6:
        severity = "medium"
    elif rank >= 4:
        severity = "low"
    else:
        severity = "info"
    return impact, probability, exposure_bucket(exposure_pct), urgency, reliability, verification, severity


def _when(category_id: int, index: int, scheduled: bool) -> tuple[datetime, datetime | None]:
    if scheduled:
        # First type in every category sits on the forward calendar.
        if index == 0:
            scheduled_at = datetime(2026, 11, 2, 13, 30, tzinfo=timezone.utc) + timedelta(days=category_id)
        else:
            day = datetime(2026, 9, 1, 13, 30, tzinfo=timezone.utc) + timedelta(days=(category_id * 5 + index * 3) % 110)
            scheduled_at = day
        observed = min(scheduled_at, AS_OF) - timedelta(hours=6)
        if scheduled_at > AS_OF:
            observed = AS_OF - timedelta(hours=category_id)
        return observed, scheduled_at
    observed = AS_OF - timedelta(days=(index % 28) + 1, hours=category_id)
    return observed, None


def _numbers(category_id: int, index: int, released: bool) -> tuple[float | None, float | None, float | None, float | None, float | None, int | None]:
    if category_id not in _NUMERIC:
        return None, None, None, None, None, None
    base = _BASES[category_id]
    consensus = round(base + ((index % 5) - 2) * (0.15 if base < 20 else 0.4), 2)
    previous = round(consensus - (0.10 if base < 20 else 0.25), 2)
    revised = round(previous - 0.05, 2) if category_id == 1 else None
    percentile = 15 + ((category_id * 13 + index * 7) % 80)
    if not released:
        return None, consensus, previous, revised, None, percentile
    actual = round(consensus + (((index % 5) - 2) * (0.08 if base < 20 else 0.2)), 2)
    surprise = round(actual - consensus, 2)
    return actual, consensus, previous, revised, surprise, percentile


def _company_for(category_id: int, index: int) -> tuple[str, str, str] | None:
    if category_id not in (3, 14):
        return None
    return _COMPANIES[index % len(_COMPANIES)]


def _should_schedule(category_id: int, index: int, event_type: str) -> bool:
    if index == 0 or category_id in (1, 2, 17, 19):
        return True
    lowered = event_type.lower()
    return any(word in lowered for word in ("auction", "expiry", "election", "earnings", "fomc", "release"))


def _build_event(category_id: int, index: int, event_type: str, *, duplicate: bool = False) -> Event:
    spec = category(category_id)
    company = _company_for(category_id, index)
    company_symbol = company[0] if company else None
    company_name = company[1] if company else None
    geography = _pick_geo(event_type, category_id)
    sectors = _pick_sectors(event_type, category_id, company[2] if company else None)
    instruments = _pick_instruments(event_type, category_id, company_symbol)
    exposure = _exposure(instruments)
    impact, probability, exposure_input, urgency, reliability, verification, severity = _scores(
        category_id, index, exposure
    )
    scheduled = _should_schedule(category_id, index, event_type)
    observed_at, scheduled_at = _when(category_id, index, scheduled)
    released = scheduled_at is None or scheduled_at <= AS_OF
    actual, consensus, previous, revised, surprise, percentile = _numbers(category_id, index, released)
    source_name, source_url = _SOURCES[category_id]
    if duplicate:
        source_name = "Simulated second wire"
        source_url = "demo://wire-repeat"
        observed_at = observed_at + timedelta(minutes=40)
    tz_name = _TZ.get(geography[0], "America/New_York")
    period = observed_at.strftime("%b %Y")
    prefix = f"{company_name}: " if company_name else f"{geography[0]}: "
    title = f"{prefix}{event_type}"
    if not released and scheduled_at is not None:
        summary = (
            f"Scheduled item on the simulated calendar. {event_type} has not been released "
            f"in this batch. Consensus is an expectation, not an outcome."
        )
    elif actual is not None and surprise is not None:
        direction = "above" if surprise > 0 else "below" if surprise < 0 else "in line with"
        summary = (
            f"Observed fact in the simulated batch: {event_type} printed {actual:.2f}"
            f"{(' ' + _UNITS[category_id]) if category_id in _UNITS else ''}, {direction} consensus."
        )
    else:
        summary = (
            f"Observed fact in the simulated batch: {event_type} was logged for {geography[0]}. "
            "No numeric print is attached."
        )
    interpretation = (
        f"Analyst interpretation (simulated): {event_type} is relevant for {spec.impacts} "
        "This note is not a forecast and not an instruction to trade."
    )
    scenarios = (
        Scenario("bull", f"Simulated bull case: the {event_type.lower()} outcome is absorbed without a funding squeeze."),
        Scenario("base", f"Simulated base case: {event_type.lower()} stays a one-period item and is rechecked at the next print."),
        Scenario("bear", f"Simulated bear case: {event_type.lower()} coincides with tighter liquidity or a wider risk premium."),
    )
    status = ("new", "reviewing", "acknowledged", "resolved")[index % 4]
    reaction = "Simulated path only. Delayed demo points, not a tradable quote."
    event_id = f"MM-{category_id:02d}-{index:03d}" + ("-DUP" if duplicate else "")
    dedupe = f"{category_id}|{event_type}|{(scheduled_at or observed_at).date().isoformat()}"
    timeline = (
        TimelineEntry(observed_at.isoformat(), "Item entered the simulated batch", "observed_fact"),
        TimelineEntry(AS_OF_ISO, "Consensus snapshot frozen for this demo", "consensus"),
        TimelineEntry(AS_OF_ISO, "Scenario set written for review", "scenario"),
        TimelineEntry(AS_OF_ISO, "Interpretation drafted and labeled as opinion", "interpretation"),
    )
    return Event(
        id=event_id,
        category_id=category_id,
        primary_panel=spec.panel_id,
        event_type=event_type,
        title=title,
        summary=summary,
        observed_at=observed_at.isoformat(),
        published_at=observed_at.isoformat() if verification == "verified" else None,
        scheduled_at=scheduled_at.isoformat() if scheduled_at else None,
        timezone=tz_name,
        geography=geography,
        sectors=sectors,
        asset_classes=_ASSET[category_id],
        instruments=instruments,
        sources=(Source(source_name, source_url, AS_OF_ISO),),
        verification=verification,
        severity=severity,
        actual=actual,
        consensus=consensus,
        previous=previous,
        revised_prior=revised,
        unit=_UNITS.get(category_id),
        surprise=surprise,
        historical_percentile=percentile,
        portfolio_exposure_pct=exposure,
        impact_score=impact * 20,
        interpretation=interpretation,
        scenarios=scenarios,
        status=status,
        related_event_ids=(),
        period=period,
        cadence=spec.cadence,
        impact_note=spec.impacts,
        timeline=timeline,
        market_reaction=reaction,
        dedupe_key=dedupe,
        impact=impact,
        probability=probability,
        exposure_input=exposure_input,
        urgency=urgency,
        reliability=reliability,
    )


def _with_related(events: list[Event]) -> list[Event]:
    by_cat: dict[int, list[str]] = {}
    for event in events:
        by_cat.setdefault(event.category_id, []).append(event.id)
    linked: list[Event] = []
    for event in events:
        peers = [item for item in by_cat[event.category_id] if item != event.id][:2]
        linked.append(_replace_related(event, tuple(peers)))
    return linked


def _replace_related(event: Event, related: tuple[str, ...]) -> Event:
    return Event(**{**event.__dict__, "related_event_ids": related})


def build_catalog() -> tuple[Event, ...]:
    events: list[Event] = []
    for spec in CATEGORIES:
        for index, event_type in enumerate(spec.event_types):
            events.append(_build_event(spec.id, index, event_type))
    cpi = next(event for event in events if event.category_id == 1 and event.event_type == "CPI")
    events.append(_build_event(1, 1, "CPI", duplicate=True))
    # The duplicate builder uses index 1's schedule. Force the CPI dedupe key.
    duplicate = events[-1]
    events[-1] = Event(**{**duplicate.__dict__, "dedupe_key": cpi.dedupe_key, "title": cpi.title})
    return tuple(events)


EVENTS: tuple[Event, ...] = build_catalog()
EVENTS_BY_ID: dict[str, Event] = {event.id: event for event in EVENTS}


def collapse_events(events: tuple[Event, ...] | list[Event] = EVENTS) -> list[Event]:
    """Keep the earliest report for each dedupe key and merge later sources."""
    grouped: dict[str, list[Event]] = {}
    for event in events:
        grouped.setdefault(event.dedupe_key, []).append(event)
    collapsed: list[Event] = []
    for group in grouped.values():
        group = sorted(group, key=lambda item: item.published_at or item.observed_at)
        primary = group[0]
        if len(group) == 1:
            collapsed.append(primary)
            continue
        sources = tuple(source for item in group for source in item.sources)
        collapsed.append(Event(**{**primary.__dict__, "sources": sources}))
    collapsed.sort(key=lambda item: (item.category_id, item.id))
    return collapsed


def reaction_seed(event_id: str) -> int:
    return int(hashlib.sha256(event_id.encode()).hexdigest()[:8], 16)


def primary_events() -> list[Event]:
    return _with_related(collapse_events(EVENTS))
