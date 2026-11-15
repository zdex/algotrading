"""Catalog ownership, scoring, and the local decision audit."""

from datetime import datetime, timedelta, timezone

import pytest

from market_monitor.adapters import DemoEventAdapter, DemoSeriesAdapter
from market_monitor.catalog import AS_OF, EVENTS, collapse_events, primary_events
from market_monitor.series import (
    breadth,
    category_history,
    credit_spreads,
    growth_inflation,
    liquidity_gauge,
    macro_chart_kinds,
    macro_surprise,
    panel_chart_kinds,
    rate_path,
    sector_performance,
    subset_by_geography,
    subset_by_time,
)
from market_monitor.model import Decision
from market_monitor.query import exposure_pct, filter_events, format_dual_time, freshness, resolve_book, risk_feed, scheduled_events
from market_monitor.registry import CATEGORIES, category, ownership_counts
from market_monitor.scoring import priority_band, priority_score
from market_monitor.workflow import WorkflowStore


def test_twenty_categories_and_panel_counts():
    assert [item.id for item in CATEGORIES] == list(range(1, 21))
    counts = ownership_counts()
    assert counts == {
        "macro": 4,
        "markets": 5,
        "corporate": 2,
        "risk": 3,
        "sector": 2,
        "portfolio": 2,
        "catalysts": 2,
        "decisions": 0,
    }
    assert category(18).panel_id == "markets"


def test_every_event_type_is_in_the_catalog_once():
    events = primary_events()
    seen = {(event.category_id, event.event_type) for event in events}
    for spec in CATEGORIES:
        for name in spec.event_types:
            assert (spec.id, name) in seen
    assert all(event.simulated for event in events)
    assert all(event.sources and event.sources[0].retrieved_at for event in events)
    assert all(event.timezone for event in events)


def test_duplicate_wire_collapses_and_keeps_both_sources():
    assert len(EVENTS) == len(primary_events()) + 1
    collapsed = collapse_events(EVENTS)
    cpi = next(event for event in collapsed if event.category_id == 1 and event.event_type == "CPI")
    assert len(cpi.sources) == 2
    assert {source.name for source in cpi.sources} == {
        "Simulated BEA / BLS calendar",
        "Simulated second wire",
    }


def test_calendar_includes_every_category_and_risk_can_reference_other_panels():
    scheduled = scheduled_events(primary_events())
    assert {event.category_id for event in scheduled} == set(range(1, 21))
    feed = risk_feed(primary_events())
    assert any(role == "owned" for _event, role in feed)
    assert any(role == "referenced" and event.primary_panel != "risk" for event, role in feed)


def test_priority_formula_and_missing_exposure():
    score, status = priority_score(5, 5, 5, 5, 5)
    assert status == "complete"
    assert score == pytest.approx(100)
    partial, partial_status = priority_score(5, 5, None, 5, 5)
    assert partial_status == "partial"
    assert partial == pytest.approx(100)
    assert priority_band(80) == "critical review"
    assert priority_band(60) == "high priority"
    assert priority_band(59.9) == "routine"
    holdings, note = resolve_book("none", [], [])
    assert holdings == []
    assert "unknown" in note
    sample = primary_events()[0]
    assert exposure_pct(sample, []) is None


def test_filters_and_timestamps():
    events = primary_events()
    narrowed = filter_events(events, category_id=10, text="EUR/USD")
    assert narrowed
    assert all(event.category_id == 10 for event in narrowed)
    assert filter_events(events, severities=[]) == []
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    assert freshness(events[0].sources[0].retrieved_at, now) == "stale"
    label = format_dual_time("2026-10-16T21:00:00+00:00", "America/New_York", "UTC")
    assert "UTC" in label
    assert "EDT" in label or "ET" in label or "EST" in label or "-04" in label or "16:00" in label or "17:00" in label


def test_decision_history_is_append_only(tmp_path):
    store = WorkflowStore(tmp_path / "workflow.json")
    created = store.create_decision(Decision(
        id="",
        title="Review CPI",
        state="proposed",
        thesis="Wait for the next print.",
        evidence="Simulated surprise.",
        author="analyst",
        event_ids=["MM-01-001"],
    ))
    store.save()
    first = store.decision_by_id(created.id).history[0]
    revised = store.revise_decision(created.id, {"state": "deferred", "result": "No action."}, "analyst", "Snoozed the idea.")
    assert len(revised.history) == 2
    assert revised.history[0].snapshot["title"] == first.snapshot["title"]
    assert revised.history[0].snapshot["state"] == "proposed"
    assert revised.state == "deferred"
    with pytest.raises(ValueError):
        store.revise_decision(created.id, {"history": []}, "analyst", "nope")
    with pytest.raises(ValueError):
        store.dismiss("MM-01-000", "critical")
    store.dismiss("MM-01-000", "info")
    assert store.effective_status("MM-01-000", "new") == "dismissed"


def test_macro_charts_follow_geography_category_and_window():
    everyone = subset_by_geography(growth_inflation(), "country", None)
    assert everyone["country"].nunique() == 6
    japan = subset_by_geography(growth_inflation(), "country", "Japan")
    assert list(japan["country"]) == ["Japan"]
    assert subset_by_geography(growth_inflation(), "country", "Taiwan").empty
    assert macro_chart_kinds(None) == frozenset({"surprise", "quadrant", "rates", "curve", "scorecard"})
    assert macro_chart_kinds(1) == frozenset({"surprise", "quadrant"})
    assert macro_chart_kinds(2) == frozenset({"rates", "curve"})
    assert macro_chart_kinds(5) == frozenset()
    path = subset_by_geography(rate_path(), "country", "United States")
    assert list(path["policy_rate"]) == [4.50, 4.50, 4.25, 4.25, 4.00, 4.00, 3.75, 3.75]
    trimmed = subset_by_time(subset_by_geography(rate_path(), "country", "Japan"), AS_OF - timedelta(days=7), AS_OF)
    assert 1 <= len(trimmed) <= 2
    assert set(trimmed["country"]) == {"Japan"}
    surprise = macro_surprise()
    assert surprise.equals(macro_surprise())
    assert list(surprise["indicator"].unique()) == ["CPI", "Core CPI", "Payrolls", "PMI", "Retail sales", "GDP"]
    assert category_history(1).equals(category_history(1))
    assert not category_history(1)["value"].equals(category_history(2)["value"])


def test_other_panels_follow_category_and_stay_stable():
    assert panel_chart_kinds("markets", None) == frozenset(
        {"ribbon", "map", "liquidity", "breadth", "vol", "commodities", "fx", "crypto"}
    )
    assert panel_chart_kinds("markets", 6) == frozenset({"liquidity"})
    assert panel_chart_kinds("markets", 7) == frozenset({"ribbon", "map", "breadth", "vol"})
    assert panel_chart_kinds("markets", 9) == frozenset({"commodities"})
    assert panel_chart_kinds("markets", 10) == frozenset({"fx"})
    assert panel_chart_kinds("markets", 18) == frozenset({"crypto"})
    assert panel_chart_kinds("markets", 99) == panel_chart_kinds("markets", None)
    assert panel_chart_kinds("corporate", 3) == frozenset({"earnings", "guidance", "calendar"})
    assert panel_chart_kinds("corporate", 14) == frozenset({"governance"})
    assert "spreads" in panel_chart_kinds("risk", None)
    assert "spreads" not in panel_chart_kinds("risk", 4)
    assert panel_chart_kinds("risk", 12) == frozenset({"spreads"})
    assert panel_chart_kinds("risk", 16) == frozenset({"geography", "hazards"})
    assert panel_chart_kinds("sector", 8) == frozenset({"performance", "revisions", "valuation", "constituents"})
    assert panel_chart_kinds("sector", 15) == frozenset({"themes"})
    assert panel_chart_kinds("portfolio", 13) == frozenset({"funds"})
    assert "funds" not in panel_chart_kinds("portfolio", 20)
    assert liquidity_gauge().equals(liquidity_gauge())
    assert breadth().equals(breadth())
    assert credit_spreads().equals(credit_spreads())
    assert sector_performance().equals(sector_performance())
    trimmed = subset_by_time(credit_spreads(), AS_OF - timedelta(days=30), AS_OF)
    assert len(trimmed) < len(credit_spreads())


def test_demo_adapters_do_not_pretend_to_be_live():
    health = DemoEventAdapter().health()
    assert health.status == "simulated"
    assert "not live" in health.delay.lower() or "not live" in health.detail.lower()
    missing = DemoSeriesAdapter(failures={"quotes"}).fetch_series("quotes", "2026-09-01", "2026-10-16")
    assert missing.error
    assert DemoEventAdapter().fetch_events(18)
    assert all(event.category_id == 18 for event in DemoEventAdapter().fetch_events(18))
