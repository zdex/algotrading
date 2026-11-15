"""Trading Agent: pick companies, run the desk, and watch each worker."""

from __future__ import annotations

from datetime import datetime, time, timedelta

import pandas as pd
import streamlit as st

from agents.agno.schedule import SCHEDULE_CHOICES, DeskSchedule, ScheduledRunner
from agents.agno.trading_desk import (
    DEFAULT_ORDERS,
    MAX_COMPANIES,
    DeskCompany,
    load_orders,
)
from ui.components import state

st.title("Trading Agent")
st.caption(
    "Add companies, set a schedule, then start the desk. LangGraph runs the web, fundamental, social, "
    "and technical agents on that cadence. Each pass scores the companies and the execution agent queues "
    "a paper order when the sources agree. Orders stay on this blotter and are not sent to a broker."
)

_BADGE = {
    "running": ":orange-badge[Running]",
    "done": ":green-badge[Done]",
    "error": ":red-badge[Error]",
    "idle": ":gray-badge[Idle]",
}


def _book() -> list[dict]:
    if "trading_agent_book" not in st.session_state:
        st.session_state.trading_agent_book = []
    return st.session_state.trading_agent_book


def _notice(text: str) -> None:
    st.session_state["trading_agent_notice"] = text


_INDEX_TABS = (
    ("S&P 500", "sp500"),
    ("NASDAQ-100", "nasdaq100"),
    ("Dow 30", "dow30"),
)
_PICK_COLUMNS = [
    "symbol",
    "name",
    "sector",
    "market_cap",
    "price",
    "trailing_pe",
    "dividend_yield",
    "sub_industry",
    "indexes",
]
_COLUMN_CONFIG = {
    "select": st.column_config.CheckboxColumn("Select", default=False),
    "name": "Company",
    "symbol": "Ticker",
    "sector": "Sector",
    "market_cap": st.column_config.NumberColumn("Market cap", format="compact"),
    "price": st.column_config.NumberColumn("Price", format="$%.2f"),
    "trailing_pe": st.column_config.NumberColumn("P/E", format="%.1f"),
    "dividend_yield": st.column_config.NumberColumn("Yield %", format="%.2f"),
    "sub_industry": "Sub-industry",
    "indexes": "Index",
}


def _add_rows(rows: list[dict]) -> None:
    book = _book()
    have = {row["symbol"] for row in book}
    added = 0
    skipped = 0
    for row in rows:
        symbol = str(row.get("symbol", "")).strip().upper()
        if not symbol or symbol in have:
            continue
        if len(book) >= MAX_COMPANIES:
            skipped += 1
            continue
        book.append({
            "symbol": symbol,
            "name": str(row.get("name") or symbol).strip(),
            "sector": str(row.get("sector") or "").strip(),
        })
        have.add(symbol)
        added += 1
    if added and skipped:
        _notice(f"Added {added}. The agent holds {MAX_COMPANIES} companies at a time, so {skipped} were left out.")
    elif added:
        _notice(f"Added {added} {'company' if added == 1 else 'companies'}.")
    elif skipped:
        _notice(f"The agent already has {MAX_COMPANIES} companies. Remove one before adding more.")
    else:
        _notice("Those companies are already on the agent.")


def _render_index_tab(directory: pd.DataFrame, index_column: str) -> None:
    if index_column not in directory.columns:
        st.info("This index is not in the company list yet. Open Companies and refresh the list, then come back.")
        return
    members = directory[directory[index_column].astype(bool)].copy()
    sectors = sorted(
        sector
        for sector in members["sector"].dropna().astype(str).unique()
        if sector and sector != "Unknown"
    )
    if not sectors:
        st.caption("Sectors are not loaded for this index. Open Companies and refresh the list, then come back.")
        return
    sector_col, search_col = st.columns([1.2, 1.4])
    sector = sector_col.selectbox(
        "Sector",
        sectors,
        index=None,
        placeholder="Choose a sector",
        key=f"trading-agent-sector-{index_column}",
    )
    query = search_col.text_input(
        "Search name or ticker",
        placeholder="Apple or AAPL",
        key=f"trading-agent-search-{index_column}",
    )
    if not sector:
        st.caption(f"{len(members)} companies in this index. Choose a sector to list them.")
        return
    view = members[members["sector"] == sector]
    if query.strip():
        needle = query.strip().upper()
        view = view[
            view["symbol"].astype(str).str.upper().str.contains(needle, regex=False)
            | view["name"].astype(str).str.upper().str.contains(needle, regex=False)
        ]
    view = view.sort_values(["name", "symbol"]).reset_index(drop=True)
    if view.empty:
        st.caption(f"No companies in {sector} match.")
        return
    columns = [column for column in _PICK_COLUMNS if column in view.columns]
    editor = view[columns].copy()
    editor.insert(0, "select", False)
    edited = st.data_editor(
        editor,
        hide_index=True,
        width="stretch",
        height=420,
        num_rows="fixed",
        key=f"trading-agent-editor-{index_column}-{sector}-{hash(tuple(editor['symbol']))}",
        disabled=columns,
        column_config={name: _COLUMN_CONFIG[name] for name in editor.columns if name in _COLUMN_CONFIG},
    )
    checked = edited.loc[edited["select"].astype(bool)]
    on_book = {row["symbol"] for row in _book()}
    already = sum(symbol in on_book for symbol in view["symbol"])
    shown = len(view)
    shown_label = "company" if shown == 1 else "companies"
    st.caption(
        f"{shown} {shown_label} in {sector}. {len(checked)} checked"
        + (f" · {already} already on this agent." if already else ".")
    )
    add_col, shown_col = st.columns(2)
    if add_col.button(
        "Add selected",
        type="primary",
        icon=":material/add:",
        disabled=checked.empty,
        key=f"trading-agent-add-{index_column}",
        width="stretch",
    ):
        _add_rows(checked.to_dict(orient="records"))
        st.rerun()
    if shown_col.button(
        "Select shown",
        key=f"trading-agent-shown-{index_column}",
        help=f"Add the companies in this list, up to {MAX_COMPANIES}.",
        width="stretch",
    ):
        _add_rows(view[columns].to_dict(orient="records"))
        st.rerun()


def _paint(payload: dict) -> None:
    roster = payload.get("roster") or []
    running = [row["agent"] for row in roster if row.get("status") == "running"]
    st.subheader("Workers")
    st.markdown(", ".join(running) if running else "None")
    st.subheader("Agents")
    if not roster:
        st.caption("Start the agent to see the workers.")
    for row in roster:
        badge = _BADGE.get(row.get("status"), row.get("status", ""))
        st.markdown(f"{badge} **{row['agent']}** · {row.get('detail') or 'Waiting'}")
    st.subheader("Agent output")
    log = payload.get("log") or []
    if not log:
        st.caption("Output appears here as each agent finishes.")
    for line in log:
        st.markdown(f"**{line['agent']}** · `{line['symbol']}`")
        st.text(line.get("text") or "")
    decisions = payload.get("decisions") or []
    if decisions:
        st.subheader("Decisions")
        st.dataframe(
            pd.DataFrame([
                {"symbol": row["symbol"], "action": row["action"], "qty": row["qty"], "reason": row["reason"]}
                for row in decisions
            ]),
            hide_index=True,
            width="stretch",
        )
    orders = payload.get("orders") or []
    if orders:
        st.subheader("Orders from this run")
        st.dataframe(pd.DataFrame(orders), hide_index=True, width="stretch")


def _clock(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def _runners() -> list[ScheduledRunner]:
    if "trading_agent_runners" not in st.session_state:
        previous = st.session_state.get("trading_agent_runner")
        st.session_state.trading_agent_runners = [previous] if previous is not None else []
    return st.session_state.trading_agent_runners


def _next_agent_label() -> str:
    number = int(st.session_state.get("trading_agent_seq", 0)) + 1
    st.session_state.trading_agent_seq = number
    return f"Agent {number}"


def _render_one(runner: ScheduledRunner) -> None:
    info = runner.view()
    state_label = "Running now" if info["in_run"] else ("Scheduled" if info["active"] else "Stopped")
    with st.container(border=True):
        title, action = st.columns([4, 1])
        title.subheader(info["label"])
        if info["active"]:
            if action.button("Stop", icon=":material/stop:", key=f"trading-agent-stop-{info['label']}", width="stretch"):
                runner.stop()
                st.rerun()
        elif action.button("Dismiss", key=f"trading-agent-dismiss-{info['label']}", width="stretch"):
            st.session_state.trading_agent_runners = [item for item in _runners() if item is not runner]
            st.rerun()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Agent", state_label)
        c2.metric("Schedule", info["schedule"])
        c3.metric("Next run", _clock(info["next_run_at"]))
        c4.metric("Completed runs", info["run_count"])
        symbols = ", ".join(info["symbols"]) or "none"
        st.caption(f"Companies on this schedule: {symbols}. Last finished {_clock(info['last_finished'])}.")
        if info["error"]:
            st.error(info["error"])
        if info["latest"]:
            _paint(info["latest"])
        elif info["active"]:
            st.caption("Waiting for the first pass.")


def _render_roster(runners: list[ScheduledRunner]) -> None:
    if not runners:
        st.caption("Start the agent to see the workers.")
        return
    for runner in runners:
        _render_one(runner)


def _watch(runners: list[ScheduledRunner]) -> None:
    if any(runner.active for runner in runners):
        @st.fragment(run_every=timedelta(seconds=2))
        def _tick() -> None:
            _render_roster(list(st.session_state.get("trading_agent_runners") or []))

        _tick()
        return
    _render_roster(runners)


book = _book()
if notice := st.session_state.pop("trading_agent_notice", None):
    st.info(notice)

directory = state.company_directory(state.cache_dir())
has_directory = not directory.empty and {"symbol", "name", "sector"}.issubset(directory.columns)

st.subheader("Add companies")
st.caption("S&P 500, NASDAQ-100, and Dow 30. Choose a sector to list that sector’s companies, then select the ones for this agent.")
if has_directory:
    tabs = st.tabs(
        [label for label, _column in _INDEX_TABS],
        key="trading_agent_index_tab",
        on_change="rerun",
    )
    for tab, (_label, column) in zip(tabs, _INDEX_TABS):
        with tab:
            if tab.open:
                _render_index_tab(directory, column)
else:
    st.info("The company list is not loaded. Open Companies and refresh the list, then come back.")

st.subheader("Companies on this agent")
st.caption(f"{len(book)} of {MAX_COMPANIES}. The desk runs this list when you start the agent.")
if book:
    st.dataframe(pd.DataFrame(book), hide_index=True, width="stretch")
    remove = st.multiselect("Remove", [row["symbol"] for row in book], key="trading-agent-remove")
    if st.button("Remove selected", disabled=not remove):
        st.session_state.trading_agent_book = [row for row in book if row["symbol"] not in set(remove)]
        st.rerun()
else:
    st.caption("No companies yet.")

st.subheader("Schedule")
runners = _runners()
active = any(runner.active for runner in runners)
choice_labels = [label for label, _minutes in SCHEDULE_CHOICES]
choice = st.selectbox("Run", choice_labels, index=1)
every_minutes = dict(SCHEDULE_CHOICES)[choice]
daily_at = None
if every_minutes is None:
    daily_at = st.time_input("Time", value=time(9, 30))
if active:
    st.caption("Agents already running keep the companies and schedule they started with.")

start_label = "Start new agent" if active else "Start agent"
if st.button(
    start_label,
    type="primary",
    icon=":material/play_arrow:",
    disabled=not book,
):
    schedule = DeskSchedule(every_minutes=every_minutes, daily_at=daily_at)
    companies = [DeskCompany(row["symbol"], row["name"], row.get("sector", "")) for row in book]
    started = ScheduledRunner(
        companies,
        schedule,
        orders_path=DEFAULT_ORDERS,
        label=_next_agent_label(),
    )
    started.start(immediate=True)
    _runners().append(started)
    st.rerun()

_watch(runners)

blotter = load_orders(DEFAULT_ORDERS)
st.subheader("Paper blotter")
st.caption("Queued by the execution agent on this computer. Nothing here is sent to a broker.")
if blotter:
    st.dataframe(pd.DataFrame(blotter), hide_index=True, width="stretch")
else:
    st.caption("No paper orders yet.")
