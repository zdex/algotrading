"""Shared Market Monitor chrome: banner, filters, event detail, and actions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from market_monitor.catalog import AS_OF, AS_OF_ISO, EVENTS_BY_ID, primary_events, reaction_seed
from market_monitor.model import Decision, Event
from market_monitor.query import (
    event_priority,
    filter_events,
    format_dual_time,
    freshness,
    resolve_book,
)
from market_monitor.registry import CATEGORIES, category
from market_monitor.series import reaction_path
from market_monitor.workflow import WorkflowStore
from ui.components import widgets

_SEVERITY_TONE = {
    "critical": "critical",
    "high": "warning",
    "medium": "warning",
    "low": "neutral",
    "info": "neutral",
}


def store() -> WorkflowStore:
    if "mm_store" not in st.session_state:
        st.session_state.mm_store = WorkflowStore().load()
    return st.session_state.mm_store


def catalog() -> list[Event]:
    return primary_events()


def paper_positions() -> list[dict]:
    try:
        from execution.portfolio_service import PortfolioBackend

        snap = PortfolioBackend().get_paper_snapshot()
        return list(snap.positions or [])
    except Exception:
        return []


def book(workflow: WorkflowStore) -> tuple[list, str]:
    prefs = workflow.preferences()
    return resolve_book(prefs.get("book", "demo"), paper_positions(), workflow.data.get("manual_holdings") or [])


def render_banner(workflow: WorkflowStore) -> None:
    if workflow.load_error:
        st.error(workflow.load_error)
        if st.button("Reset the local workflow file", icon=":material/restart_alt:"):
            workflow.reset()
            st.rerun()
    now = datetime.now(timezone.utc)
    state = freshness(AS_OF_ISO, now)
    tone = "critical" if state == "stale" else "warning" if state == "aging" else "good"
    prefs = workflow.preferences()
    holdings, book_note = book(workflow)
    st.markdown("  ".join([
        widgets.pill("Data", "SIMULATED", "warning"),
        widgets.pill("As of", AS_OF.strftime("%Y-%m-%d %H:%M UTC"), tone),
        widgets.pill("Freshness", state, tone),
        widgets.pill("Book", prefs.get("book", "demo"), "neutral"),
        widgets.pill("Holdings", str(len(holdings)) if holdings else "unavailable", "good" if holdings else "warning"),
    ]))
    st.caption(
        "Demo batch. Figures are not live quotes and an alert is not an instruction to trade. "
        f"{book_note}"
    )


def render_topbar(workflow: WorkflowStore) -> None:
    prefs = workflow.preferences()
    search, book_col, zone_col, bell = st.columns([3, 1.4, 1.6, 1.2])
    with search:
        st.text_input(
            "Search events",
            key="mm_query",
            placeholder="Title, ticker, or source",
            label_visibility="collapsed",
        )
    with book_col:
        choice = st.selectbox(
            "Book",
            ["demo", "paper", "manual", "none"],
            index=["demo", "paper", "manual", "none"].index(prefs.get("book", "demo")),
            format_func=lambda item: {
                "demo": "Demo book",
                "paper": "Paper book",
                "manual": "Manual book",
                "none": "No holdings",
            }[item],
            key="mm_book",
        )
        if choice != prefs.get("book"):
            workflow.update_preferences(book=choice)
            workflow.save()
            st.rerun()
    with zone_col:
        zone = st.selectbox(
            "Timezone",
            ["America/New_York", "America/Chicago", "America/Los_Angeles", "Europe/London", "Asia/Kolkata", "UTC"],
            index=["America/New_York", "America/Chicago", "America/Los_Angeles", "Europe/London", "Asia/Kolkata", "UTC"].index(
                prefs.get("timezone", "America/New_York")
            ) if prefs.get("timezone", "America/New_York") in {
                "America/New_York", "America/Chicago", "America/Los_Angeles", "Europe/London", "Asia/Kolkata", "UTC"
            } else 0,
            key="mm_zone",
        )
        if zone != prefs.get("timezone"):
            workflow.update_preferences(timezone=zone)
            workflow.save()
    with bell:
        alerts = _open_alerts(workflow)
        with st.popover(f"Alerts {len(alerts)}"):
            if not alerts:
                st.caption("No open critical items. High-severity items stay on Risk Alerts.")
            for event, status in alerts[:8]:
                st.markdown(f"**{event.severity}** · {event.title}")
                st.caption(f"{status} · {event.id}")
    st.caption(f"Last demo batch {AS_OF_ISO}. Display zone {prefs.get('timezone')}.")


def _open_alerts(workflow: WorkflowStore) -> list[tuple[Event, str]]:
    rows = []
    for event in catalog():
        if event.severity != "critical":
            continue
        status = workflow.effective_status(event.id, event.status)
        if status in {"resolved", "snoozed", "dismissed"}:
            continue
        rows.append((event, status))
    rows.sort(key=lambda item: item[0].severity)
    return rows


def render_filters(scope: str, events: list[Event]) -> dict:
    geos = sorted({geo for event in events for geo in event.geography})
    sectors = sorted({sector for event in events for sector in event.sectors})
    assets = sorted({asset for event in events for asset in event.asset_classes})
    sources = sorted({source.name for event in events for source in event.sources})
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        geography = st.selectbox("Geography", ["Any"] + geos, key=f"{scope}-geo")
    with c2:
        sector = st.selectbox("Sector", ["Any"] + sectors, key=f"{scope}-sector")
    with c3:
        asset = st.selectbox("Asset class", ["Any"] + assets, key=f"{scope}-asset")
    with c4:
        window = st.selectbox("Window vs demo as-of", ["Any time", "7 days", "30 days", "90 days"], key=f"{scope}-window")
    c5, c6, c7 = st.columns([2, 2, 1])
    with c5:
        severities = st.pills(
            "Severity",
            ["critical", "high", "medium", "low", "info"],
            selection_mode="multi",
            default=["critical", "high", "medium", "low", "info"],
            key=f"{scope}-sev",
        )
    with c6:
        source = st.selectbox("Source", ["Any"] + sources, key=f"{scope}-source")
    with c7:
        quiet = st.checkbox("Show resolved and snoozed", key=f"{scope}-quiet")
    time_from = None
    if window != "Any time":
        days = int(window.split()[0])
        time_from = AS_OF - timedelta(days=days)
    return {
        "geography": None if geography == "Any" else geography,
        "sector": None if sector == "Any" else sector,
        "asset": None if asset == "Any" else asset,
        "severities": list(severities or []),
        "source": None if source == "Any" else source,
        "time_from": time_from,
        "time_to": AS_OF,
        "text": st.session_state.get("mm_query") or "",
        "include_quiet": quiet,
    }


def apply_filters(events: list[Event], filters: dict, workflow: WorkflowStore) -> tuple[list[tuple[Event, str]], int]:
    matched = filter_events(
        events,
        geography=filters.get("geography"),
        sector=filters.get("sector"),
        asset=filters.get("asset"),
        severities=filters.get("severities"),
        source=filters.get("source"),
        text=filters.get("text"),
        time_from=filters.get("time_from"),
        time_to=filters.get("time_to"),
        instruments=filters.get("instruments"),
        category_id=filters.get("category_id"),
        panel=filters.get("panel"),
    )
    visible: list[tuple[Event, str]] = []
    hidden = 0
    for event in matched:
        status = workflow.effective_status(event.id, event.status)
        if status in {"dismissed", "snoozed", "resolved"} and not filters.get("include_quiet"):
            hidden += 1
            continue
        visible.append((event, status))
    return visible, hidden


def event_frame(rows: list[tuple[Event, str]], workflow: WorkflowStore) -> pd.DataFrame:
    holdings, _note = book(workflow)
    prefs = workflow.preferences()
    zone = prefs.get("timezone", "America/New_York")
    records = []
    for event, status in rows:
        score = event_priority(event, holdings, prefs.get("thresholds"))
        exposure = "unknown" if score["exposure_pct"] is None else f"{score['exposure_pct']:.1f}%"
        records.append({
            "id": event.id,
            "severity": event.severity,
            "priority": score["band"] if score["status"] == "complete" else f"{score['band']} ({score['status']})",
            "score": score["score"],
            "title": event.title,
            "type": event.event_type,
            "status": status,
            "verification": event.verification,
            "when": format_dual_time(event.scheduled_at or event.observed_at, event.timezone, zone),
            "exposure": exposure,
            "source": event.sources[0].name if event.sources else "—",
        })
    return pd.DataFrame(records)


def render_feed(scope: str, rows: list[tuple[Event, str]], workflow: WorkflowStore, hidden: int) -> None:
    st.subheader("Event feed")
    if hidden:
        st.caption(f"{hidden} resolved, snoozed, or dismissed items are hidden. Turn on “Show resolved and snoozed” to see them.")
    if not rows:
        st.info("No events match these filters.")
        return
    frame = event_frame(rows, workflow)
    height = 280 if workflow.preferences().get("density") == "compact" else 420
    st.dataframe(frame.drop(columns=["id"]), hide_index=True, height=height, width="stretch")
    labels = {event.id: f"{event.severity} · {event.title}" for event, _status in rows}
    selected = st.selectbox("Open an event", list(labels), format_func=lambda item: labels[item], key=f"{scope}-pick")
    st.download_button(
        "Export this feed",
        data=frame.to_csv(index=False).encode(),
        file_name=f"market-monitor-{scope}.csv",
        mime="text/csv",
        key=f"{scope}-csv",
    )
    if selected:
        with st.expander("Event detail", expanded=True):
            render_detail(EVENTS_BY_ID[selected], workflow, inline=True)


def render_detail(event: Event, workflow: WorkflowStore, *, inline: bool) -> None:
    holdings, note = book(workflow)
    prefs = workflow.preferences()
    score = event_priority(event, holdings, prefs.get("thresholds"))
    spec = category(event.category_id)
    st.markdown(f"### {event.title}")
    st.markdown("  ".join([
        widgets.pill("Severity", event.severity, _SEVERITY_TONE.get(event.severity, "neutral")),
        widgets.pill("Verification", event.verification, "good" if event.verification == "verified" else "warning"),
        widgets.pill("Priority", f"{score['score'] if score['score'] is not None else '—'} {score['band']}", "neutral"),
        widgets.pill("Simulated", "yes", "warning"),
    ]))
    exposure = "unknown" if score["exposure_pct"] is None else f"{score['exposure_pct']:.1f}% of the selected book"
    if score["status"] == "partial":
        st.caption("Priority is partial because portfolio exposure is unknown. Missing exposure was not treated as zero.")
    cols = st.columns(5)
    cols[0].metric("Actual", _num(event.actual, event.unit), help="Observed fact when the item has been released.")
    cols[1].metric("Consensus", _num(event.consensus, event.unit), help="Consensus expectation, not an outcome.")
    cols[2].metric("Prior", _num(event.previous, event.unit))
    cols[3].metric("Surprise", _num(event.surprise, event.unit))
    cols[4].metric("Exposure", exposure)
    zone = prefs.get("timezone", "America/New_York")
    st.caption(
        f"Category {spec.id:02d} · {spec.name} · {event.cadence} · "
        f"Event time {format_dual_time(event.scheduled_at or event.observed_at, event.timezone, zone)} · "
        f"As of {event.sources[0].retrieved_at if event.sources else '—'} · {event.delay_label}"
    )
    facts, timeline, reaction, exposure_tab, scenarios, sources, decisions = st.tabs(
        ["Facts", "Timeline", "Market reaction", "Exposure", "Scenarios", "Sources", "Decisions"]
    )
    with facts:
        st.markdown("**Observed fact**")
        st.write(event.observed_fact)
        st.markdown("**Consensus expectation**")
        st.write(event.consensus_text)
        if event.revised_prior is not None:
            st.caption(f"Revised prior {event.revised_prior:.2f} {event.unit or ''}. Historical percentile {event.historical_percentile}.")
        elif event.historical_percentile is not None:
            st.caption(f"Historical percentile in the demo set: {event.historical_percentile}.")
        st.markdown("**Analyst interpretation**")
        st.write(event.interpretation)
        st.caption(f"Asset impact note: {event.impact_note}")
    with timeline:
        st.dataframe(
            pd.DataFrame([{"time": row.at, "kind": row.kind, "label": row.label} for row in event.timeline]),
            hide_index=True, width="stretch",
        )
    with reaction:
        st.caption(event.market_reaction)
        import plotly.graph_objects as go

        path = reaction_path(reaction_seed(event.id))
        fig = go.Figure(go.Scatter(x=path["time"], y=path["index"], mode="lines", name="Simulated"))
        fig.update_layout(title="Simulated reaction index (100 = batch start)", height=280)
        st.plotly_chart(fig, width="stretch")
    with exposure_tab:
        st.write(note)
        if not holdings:
            st.warning("Holdings are unavailable, so this event is not mapped to a position.")
        else:
            hits = [row for row in holdings if row.symbol in event.instruments]
            if not hits:
                st.info("None of the selected holdings are on this event. Exposure stays unknown.")
            else:
                st.dataframe(pd.DataFrame([row.__dict__ for row in hits]), hide_index=True, width="stretch")
        st.caption("Instruments: " + (", ".join(event.instruments) or "—"))
    with scenarios:
        st.caption("Scenario analysis. These are review cases, not predicted returns.")
        for item in event.scenarios:
            st.markdown(f"**{item.label.title()}**")
            st.write(item.rationale)
    with sources:
        st.dataframe(
            pd.DataFrame([{"name": row.name, "url": row.url, "retrieved": row.retrieved_at} for row in event.sources]),
            hide_index=True, width="stretch",
        )
        if event.related_event_ids:
            st.caption("Related ids: " + ", ".join(event.related_event_ids))
    with decisions:
        linked = [row for row in workflow.decisions() if event.id in row.event_ids]
        if not linked:
            st.caption("No decision is linked yet.")
        for row in linked:
            st.markdown(f"**{row.title}** · {row.state}")
            st.caption(row.thesis)
    if inline:
        _actions(event, workflow)


def _actions(event: Event, workflow: WorkflowStore) -> None:
    st.markdown("**Actions**")
    status = workflow.effective_status(event.id, event.status)
    st.caption(f"Workflow status: {status}. Critical and high alerts cannot be dismissed.")
    a, b, c, d = st.columns(4)
    with a:
        if st.button("Acknowledge", key=f"ack-{event.id}"):
            workflow.acknowledge(event.id, "analyst")
            workflow.save()
            st.rerun()
    with b:
        assignee = st.text_input("Assign to", key=f"asg-{event.id}", placeholder="Name")
        if st.button("Assign", key=f"asg-btn-{event.id}") and assignee.strip():
            workflow.assign(event.id, assignee.strip())
            workflow.save()
            st.rerun()
    with c:
        until = st.date_input("Snooze until", key=f"snz-{event.id}")
        if st.button("Snooze", key=f"snz-btn-{event.id}"):
            workflow.snooze(event.id, datetime.combine(until, datetime.min.time(), tzinfo=timezone.utc).isoformat())
            workflow.save()
            st.rerun()
    with d:
        if event.severity in {"critical", "high"}:
            st.caption("Dismiss is unavailable at this severity.")
        elif st.button("Dismiss", key=f"dis-{event.id}"):
            workflow.dismiss(event.id, event.severity)
            workflow.save()
            st.rerun()
    note = st.text_input("Resolution note", key=f"res-{event.id}")
    if st.button("Resolve", key=f"res-btn-{event.id}"):
        workflow.resolve(event.id, note or "Resolved in review.")
        workflow.save()
        st.rerun()
    for symbol in event.instruments:
        if st.button(f"Watch {symbol}", key=f"watch-{event.id}-{symbol}"):
            workflow.add_watch(symbol)
            workflow.save()
            st.rerun()
    with st.form(f"decision-{event.id}"):
        st.markdown("**Add to decision log**")
        title = st.text_input("Decision", value=f"Review {event.event_type}")
        thesis = st.text_area("Thesis", value=event.interpretation)
        state = st.selectbox("State", ["proposed", "executed", "rejected", "deferred"])
        sizing = st.text_input("Sizing note", value="Research only. No order.")
        author = st.text_input("Author", value="analyst")
        follow = st.text_input("Follow-up date", value=(AS_OF + timedelta(days=14)).date().isoformat())
        if st.form_submit_button("Save decision"):
            workflow.create_decision(Decision(
                id="",
                title=title,
                state=state,
                thesis=thesis,
                evidence=event.summary,
                positions=list(event.instruments),
                sizing=sizing,
                risk_budget="Within existing review. No new risk budget.",
                author=author,
                approver="",
                follow_up=follow,
                result="",
                event_ids=[event.id],
            ))
            workflow.save()
            st.rerun()


def _num(value: float | None, unit: str | None) -> str:
    if value is None:
        return "—"
    suffix = f" {unit}" if unit else ""
    return f"{value:.2f}{suffix}"


def category_choices() -> list[str]:
    return [f"{item.id:02d} {item.name}" for item in CATEGORIES]


def parse_category_choice(label: str | None) -> int | None:
    if not label or label.startswith("All"):
        return None
    return int(label[:2])


def save_view_control(scope: str, workflow: WorkflowStore, filters: dict) -> None:
    name = st.text_input("Save this view as", key=f"{scope}-view-name", placeholder="View name")
    if st.button("Save view", key=f"{scope}-view-btn") and name.strip():
        payload = {key: value.isoformat() if isinstance(value, datetime) else value for key, value in filters.items()}
        workflow.save_view(name.strip(), payload)
        workflow.save()
        st.success(f"Saved “{name.strip()}”.")
