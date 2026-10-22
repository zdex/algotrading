"""Market Monitor pages. Each sidebar subsection calls one function here."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from market_monitor.adapters import ENDPOINTS, source_board
from market_monitor.catalog import AS_OF, demo_nav
from market_monitor.model import Event
from market_monitor.query import countdown_days, risk_feed, rule_matches, scheduled_events
from market_monitor.registry import PANELS, categories_for, category, panel
from market_monitor.series import category_history, sector_performance
from ui.components import theme as t
from ui.market_monitor import panels
from ui.market_monitor import widgets as w


def _chrome():
    workflow = w.store()
    w.render_banner(workflow)
    w.render_topbar(workflow)
    return workflow


def _landing(spec, rows: list[tuple[Event, str]], workflow) -> None:
    st.subheader(f"{spec.id:02d} · {spec.name}")
    st.write(spec.summary)
    st.caption(f"Cadence: {spec.cadence}")
    st.caption(f"Asset impact: {spec.impacts}")
    st.caption("Fields: " + ", ".join(spec.fields))
    events = [event for event, _status in rows]
    released = [event for event in events if event.actual is not None]
    upcoming = [event for event in events if event.scheduled_at]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Event types", len(spec.event_types))
    c2.metric("In this filter", len(events))
    c3.metric("With a print", len(released))
    c4.metric("Scheduled", len(upcoming))
    covered = {event.event_type for event in events}
    type_rows = []
    for name in spec.event_types:
        match = next((event for event in events if event.event_type == name), None)
        type_rows.append({
            "event type": name,
            "catalog": "represented",
            "in filter": "yes" if match else "filtered out",
            "severity": match.severity if match else "—",
            "id": match.id if match else "—",
        })
    st.dataframe(pd.DataFrame(type_rows), hide_index=True, height=240, width="stretch")
    history = category_history(spec.id)
    fig = go.Figure(go.Scatter(x=history["date"], y=history["value"], mode="lines"))
    fig.update_layout(title=f"Simulated history for category {spec.id:02d}", height=280)
    st.plotly_chart(fig, width="stretch")
    rules = [rule for rule in workflow.data["rules"] if not rule.get("category_id") or int(rule["category_id"]) == spec.id]
    st.markdown("**Alert rules that can hit this category**")
    if rules:
        st.dataframe(pd.DataFrame(rules), hide_index=True, width="stretch")
    else:
        st.caption("No saved rule targets this category. Add one in Settings.")
    watched = [symbol for symbol in workflow.data["watchlist"] if any(symbol in event.instruments for event in events)]
    st.caption("Watchlist symbols in this category: " + (", ".join(watched) if watched else "none."))


def render_panel(panel_id: str) -> None:
    workflow = _chrome()
    spec = panel(panel_id)
    st.title(spec.title)
    st.caption(spec.summary)
    owned = categories_for(panel_id)
    if not owned:
        st.info("This workflow has no exclusive category. Link a decision from any event.")
        return
    choice = st.pills(
        "Category",
        ["All categories"] + [f"{item.id:02d} {item.name}" for item in owned],
        default="All categories",
        key=f"{panel_id}-cat",
    )
    events = w.catalog()
    if panel_id == "risk":
        mode = st.radio(
            "Queue",
            ["Owned and referenced", "Owned only"],
            horizontal=True,
            key="risk-mode",
            help="High and critical events owned by other panels stay visible here as references.",
        )
        if mode == "Owned only":
            pool = [event for event in events if event.primary_panel == "risk"]
        else:
            pool = [event for event, _role in risk_feed(events)]
    elif panel_id == "catalysts":
        pool = scheduled_events(events)
        st.caption("This calendar aggregates scheduled items from every category, not only elections and market mechanics.")
    else:
        pool = [event for event in events if event.primary_panel == panel_id]
    filters = w.render_filters(panel_id, pool)
    category_id = w.parse_category_choice(choice)
    filters["category_id"] = category_id
    rows, hidden = w.apply_filters(pool, filters, workflow)
    if panel_id == "macro":
        country = st.selectbox(
            "Country lens",
            ["All"] + sorted({geo for event in pool for geo in event.geography}),
            key="macro-country",
        )
        if country != "All":
            rows = [(event, status) for event, status in rows if country in event.geography]
        macro_charts = panels.macro_charts
        macro_charts()
    elif panel_id == "markets":
        panels.markets_charts()
    elif panel_id == "corporate":
        panels.corporate_charts([event for event, _status in rows])
        gov = [(event, status) for event, status in rows if event.category_id == 14]
        st.subheader("Governance alert feed")
        if gov:
            st.dataframe(w.event_frame(gov, workflow).drop(columns=["id"]), hide_index=True, width="stretch")
        else:
            st.caption("No governance events in the current filter.")
    elif panel_id == "risk":
        panels.risk_charts()
        _risk_context(rows, workflow)
    elif panel_id == "sector":
        panels.sector_charts()
    elif panel_id == "portfolio":
        holdings, _note = w.book(workflow)
        panels.portfolio_charts(holdings, workflow.preferences().get("book", "demo"))
        _manual_holdings(workflow)
    elif panel_id == "catalysts":
        _catalyst_views(rows, workflow)
    if category_id:
        scoped = rows if category_id else rows
        _landing(category(category_id), scoped, workflow)
    w.save_view_control(panel_id, workflow, filters)
    w.render_feed(panel_id, rows, workflow, hidden)


def _risk_context(rows, workflow) -> None:
    holdings, note = w.book(workflow)
    st.subheader("Geography")
    if rows:
        counts = pd.Series([geo for event, _status in rows for geo in event.geography]).value_counts()
        fig = go.Figure(go.Bar(x=counts.index.tolist(), y=counts.values.tolist(), marker_color=t.SERIES[3]))
        fig.update_layout(title="Events by geography", height=300)
        st.plotly_chart(fig, width="stretch")
    st.write(note)
    st.subheader("Affected holdings")
    if not holdings:
        st.warning("Holdings are unavailable, so affected positions cannot be listed.")
    else:
        hit_rows = []
        for event, status in rows:
            overlap = [row.symbol for row in holdings if row.symbol in event.instruments]
            if overlap:
                hit_rows.append({"event": event.title, "severity": event.severity, "status": status, "holdings": ", ".join(overlap)})
        if hit_rows:
            st.dataframe(pd.DataFrame(hit_rows), hide_index=True, width="stretch")
        else:
            st.info("No holding symbol is on the events in this filter. Exposure stays unknown.")
    st.subheader("Geopolitical timeline")
    geo = [(event, status) for event, status in rows if event.category_id == 4]
    if geo:
        st.dataframe(w.event_frame(geo, workflow).drop(columns=["id"]), hide_index=True, width="stretch")
    else:
        st.caption("No geopolitical events in this filter.")
    st.subheader("Natural hazard alerts")
    hazards = [(event, status) for event, status in rows if event.category_id == 16]
    if hazards:
        st.dataframe(w.event_frame(hazards, workflow).drop(columns=["id"]), hide_index=True, width="stretch")
    else:
        st.caption("No hazard events in this filter.")


def _catalyst_views(rows, workflow) -> None:
    mode = st.radio("Calendar layout", ["List", "Week", "Month"], horizontal=True, key="cal-layout")
    now = datetime.now(timezone.utc)
    records = []
    for event, status in rows:
        days = countdown_days(event, now)
        records.append({
            "date": (event.scheduled_at or "")[:10],
            "countdown_days": days,
            "importance": event.severity,
            "title": event.title,
            "panel": event.primary_panel,
            "timezone": event.timezone,
            "status": status,
        })
    frame = pd.DataFrame(records)
    if frame.empty:
        st.info("No scheduled events in this filter.")
        return
    if mode == "Week":
        st.caption("Grouped by calendar week of the scheduled timestamp.")
        frame["week"] = pd.to_datetime(frame["date"]).dt.strftime("%G-W%V")
        st.dataframe(frame.sort_values("date"), hide_index=True, width="stretch")
    elif mode == "Month":
        frame["month"] = frame["date"].str.slice(0, 7)
        st.dataframe(frame.groupby("month").size().rename("events").reset_index(), hide_index=True, width="stretch")
        st.dataframe(frame.sort_values("date"), hide_index=True, width="stretch")
    else:
        st.dataframe(frame.sort_values("date"), hide_index=True, width="stretch")
    st.caption("Countdown uses your clock against the simulated schedule. The event timezone is shown beside the display timezone in the feed.")


def _manual_holdings(workflow) -> None:
    st.subheader("Manual holdings")
    st.caption("Symbols and market values you type here are used only when the book selector is Manual. No price is fetched.")
    current = pd.DataFrame(workflow.data.get("manual_holdings") or [], columns=["symbol", "market_value"])
    edited = st.data_editor(current, num_rows="dynamic", key="mm-manual", width="stretch")
    if st.button("Save manual holdings", key="mm-manual-save"):
        rows = []
        for record in edited.to_dict(orient="records"):
            symbol = str(record.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            try:
                value = float(record.get("market_value") or 0)
            except (TypeError, ValueError):
                value = 0
            rows.append({"symbol": symbol, "market_value": value})
        workflow.set_manual_holdings(rows)
        workflow.update_preferences(book="manual")
        workflow.save()
        st.rerun()


def render_overview() -> None:
    workflow = _chrome()
    st.title("Market Monitor")
    st.caption("Home for the eight panels. Search here, then open a panel for the category landing pages.")
    holdings, note = w.book(workflow)
    value = sum(row.market_value for row in holdings) if holdings else None
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Book value", f"${value:,.0f}" if value else "—", help=note)
    alerts = [event for event in w.catalog() if event.severity in {"critical", "high"}]
    c2.metric("High or critical", len(alerts))
    upcoming = scheduled_events(w.catalog())
    c3.metric("Scheduled items", len(upcoming))
    c4.metric("Decisions", len(workflow.decisions()))
    if workflow.preferences().get("book") == "demo":
        st.caption(f"Demo NAV ${demo_nav():,.0f}. The day-change column is not shown because this batch has no live mark.")
    query = (st.session_state.get("mm_query") or "").strip()
    if query:
        hits, _hidden = w.apply_filters(w.catalog(), {"text": query, "severities": ["critical", "high", "medium", "low", "info"]}, workflow)
        st.subheader(f"Search · {len(hits)} events")
        if hits:
            st.dataframe(w.event_frame(hits[:12], workflow).drop(columns=["id"]), hide_index=True, width="stretch")
        st.caption("The same query is applied on Event Explorer.")
    left, right = st.columns(2)
    with left:
        st.subheader("Top risk alerts")
        feed = [(event, "referenced" if event.primary_panel != "risk" else "owned") for event, _role in risk_feed(w.catalog())]
        top = sorted(feed, key=lambda item: item[0].severity)[:8]
        if top:
            st.dataframe(
                pd.DataFrame([{"role": role, "severity": event.severity, "title": event.title, "panel": event.primary_panel} for event, role in top]),
                hide_index=True, width="stretch",
            )
        else:
            st.caption("No risk items.")
    with right:
        st.subheader("Upcoming catalysts")
        now = datetime.now(timezone.utc)
        future = []
        for event in upcoming:
            days = countdown_days(event, now)
            if days is not None and days >= 0:
                future.append({"in days": days, "date": event.scheduled_at[:10], "title": event.title, "panel": event.primary_panel})
        future = sorted(future, key=lambda row: row["in days"])[:8]
        if future:
            st.dataframe(pd.DataFrame(future), hide_index=True, width="stretch")
        else:
            st.caption("No future dates left on the simulated calendar.")
    frame = sector_performance()
    fig = go.Figure(go.Bar(
        x=frame["sector"], y=frame["1M"],
        marker_color=[t.GOOD if value >= 0 else t.CRITICAL for value in frame["1M"]],
    ))
    fig.update_layout(title="Sector heatmap proxy, simulated 1-month move", height=340, yaxis_title="%")
    st.plotly_chart(fig, width="stretch")
    st.caption("Simulated series.")
    st.subheader("Recent decisions")
    decisions = workflow.decisions()
    if not decisions:
        st.caption("No decisions yet. Open an event and add one.")
    else:
        st.dataframe(pd.DataFrame([
            {"when": row.created_at, "state": row.state, "title": row.title, "events": ", ".join(row.event_ids)}
            for row in decisions[-8:]
        ]), hide_index=True, width="stretch")


def render_explorer() -> None:
    workflow = _chrome()
    st.title("Event Explorer")
    st.caption("Every category in one filterable catalog. Simulated records stay labeled.")
    events = w.catalog()
    filters = w.render_filters("explorer", events)
    panel_choice = st.selectbox(
        "Panel",
        ["Any"] + [item.title for item in PANELS if item.id != "decisions"],
        key="explorer-panel",
    )
    if panel_choice != "Any":
        filters["panel"] = next(item.id for item in PANELS if item.title == panel_choice)
    category_choice = st.selectbox("Category", ["All categories"] + w.category_choices(), key="explorer-cat")
    filters["category_id"] = w.parse_category_choice(category_choice)
    rows, hidden = w.apply_filters(events, filters, workflow)
    st.caption(f"{len(rows)} events shown.")
    w.save_view_control("explorer", workflow, filters)
    w.render_feed("explorer", rows, workflow, hidden)


def render_watchlists() -> None:
    workflow = _chrome()
    st.title("Watchlists")
    st.caption("Symbols you flag on an event, plus anything you add here.")
    symbol = st.text_input("Add symbol", key="mm-watch-add")
    if st.button("Add", key="mm-watch-btn") and symbol.strip():
        workflow.add_watch(symbol)
        workflow.save()
        st.rerun()
    current = workflow.data["watchlist"]
    if not current:
        st.info("The watchlist is empty.")
        return
    drop = st.selectbox("Remove", current)
    if st.button("Remove", key="mm-watch-drop"):
        workflow.remove_watch(drop)
        workflow.save()
        st.rerun()
    rows, hidden = w.apply_filters(
        w.catalog(),
        {"instruments": current, "severities": ["critical", "high", "medium", "low", "info"]},
        workflow,
    )
    w.render_feed("watch", rows, workflow, hidden)


def render_sources() -> None:
    workflow = _chrome()
    st.title("Data Sources")
    st.caption("Adapters report health, as-of, and delay. None of these are licensed live feeds.")
    rows = []
    for health in source_board():
        rows.append({
            "source": health.name,
            "status": health.status,
            "as of": health.as_of,
            "delay": health.delay,
            "detail": health.detail,
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.subheader("API contract")
    st.caption("These routes are the backend contract. They are not mounted in this app yet.")
    st.dataframe(pd.DataFrame([{"method": item.method, "path": item.path, "purpose": item.purpose} for item in ENDPOINTS]), hide_index=True, width="stretch")
    st.subheader("Saved views")
    views = workflow.data.get("views") or []
    if views:
        st.dataframe(pd.DataFrame(views), hide_index=True, width="stretch")
    else:
        st.caption("No saved views yet.")


def render_settings() -> None:
    workflow = _chrome()
    st.title("Settings")
    st.caption("Thresholds and alert rules are local. They do not place orders.")
    prefs = workflow.preferences()
    density = st.radio("Density", ["comfortable", "compact"], horizontal=True, index=0 if prefs.get("density") != "compact" else 1)
    critical = st.number_input("Critical review at or above", value=float(prefs["thresholds"]["critical"]), min_value=0.0, max_value=100.0)
    high = st.number_input("High priority at or above", value=float(prefs["thresholds"]["high"]), min_value=0.0, max_value=100.0)
    if st.button("Save preferences"):
        workflow.update_preferences(density=density, thresholds={"critical": critical, "high": high})
        workflow.save()
        st.rerun()
    st.subheader("Alert rules")
    st.dataframe(pd.DataFrame(workflow.data["rules"]), hide_index=True, width="stretch")
    with st.form("mm-rule"):
        name = st.text_input("Rule name")
        category_id = st.number_input("Category id (0 = any)", min_value=0, max_value=20, value=0)
        geography = st.text_input("Geography contains")
        ticker = st.text_input("Ticker")
        severity = st.selectbox("Minimum severity", ["info", "low", "medium", "high", "critical"])
        surprise = st.number_input("Minimum absolute surprise (0 ignores)", value=0.0)
        exposure = st.number_input("Minimum exposure % (0 ignores)", value=0.0)
        days = st.number_input("Max days to catalyst (0 ignores)", value=0)
        if st.form_submit_button("Add rule"):
            workflow.add_rule({
                "name": name or "Untitled rule",
                "category_id": int(category_id) or None,
                "geography": geography,
                "ticker": ticker,
                "min_severity": severity,
                "min_surprise": surprise or None,
                "min_exposure": exposure or None,
                "max_days_to_catalyst": int(days) or None,
                "enabled": True,
            })
            workflow.save()
            st.rerun()
    now = datetime.now(timezone.utc)
    holdings, _note = w.book(workflow)
    hits = []
    for rule in workflow.data["rules"]:
        for event in w.catalog():
            if rule_matches(event, rule, holdings, now):
                hits.append({"rule": rule["name"], "event": event.id, "title": event.title})
                if len(hits) >= 30:
                    break
    st.subheader("Rule hits in the demo catalog")
    if hits:
        st.dataframe(pd.DataFrame(hits), hide_index=True, width="stretch")
    else:
        st.caption("No current hits.")
    st.subheader("Reset")
    st.caption("Clears decisions, watches, snoozes, and saved views on this computer.")
    if st.checkbox("I want to clear the local Market Monitor workflow"):
        if st.button("Reset workflow"):
            workflow.reset()
            st.rerun()


def render_decisions() -> None:
    workflow = _chrome()
    st.title("Decision Log")
    st.caption(
        "Cross-panel journal. Category 18 (alternatives and crypto) is owned by Markets. "
        "Nothing saved here is sent to a broker."
    )
    rows = workflow.decisions()
    if not rows:
        st.info("No decisions yet. Open an event in any panel and use Add to decision log.")
    else:
        st.dataframe(pd.DataFrame([{
            "id": row.id,
            "created": row.created_at,
            "state": row.state,
            "title": row.title,
            "author": row.author,
            "approver": row.approver,
            "follow_up": row.follow_up,
            "positions": ", ".join(row.positions),
            "events": ", ".join(row.event_ids),
            "result": row.result,
        } for row in rows]), hide_index=True, width="stretch")
        st.download_button(
            "Export decisions",
            data=pd.DataFrame([row.to_dict() for row in rows]).to_csv(index=False).encode(),
            file_name="market-monitor-decisions.csv",
            mime="text/csv",
        )
        picked = st.selectbox("Decision", [row.id for row in rows], format_func=lambda item: next(row.title for row in rows if row.id == item))
        current = next(row for row in rows if row.id == picked)
        st.markdown(f"**Thesis.** {current.thesis}")
        st.markdown(f"**Evidence.** {current.evidence}")
        st.caption(f"Sizing: {current.sizing} · Risk budget: {current.risk_budget}")
        with st.form("mm-revise"):
            state = st.selectbox("State", ["proposed", "executed", "rejected", "deferred"], index=["proposed", "executed", "rejected", "deferred"].index(current.state) if current.state in {"proposed", "executed", "rejected", "deferred"} else 0)
            result = st.text_area("Outcome review", value=current.result)
            approver = st.text_input("Approver", value=current.approver)
            note = st.text_input("Audit note", value="Updated in review.")
            if st.form_submit_button("Save revision"):
                workflow.revise_decision(current.id, {"state": state, "result": result, "approver": approver}, current.author or "analyst", note)
                workflow.save()
                st.rerun()
        st.subheader("Audit history")
        history = pd.DataFrame([
            {"at": row.at, "author": row.author, "action": row.action, "note": row.note}
            for row in current.history
        ])
        st.dataframe(history, hide_index=True, width="stretch")
        st.caption("Earlier audit rows stay on the record when you save a revision.")
