"""Trading Agent: pick companies, run the desk, and watch each worker."""

from __future__ import annotations

from datetime import datetime, time, timedelta

import pandas as pd
import streamlit as st

from agents.agno.schedule import SCHEDULE_CHOICES, DeskSchedule, ScheduledRunner
from agents.agno.trading_desk import (
    DEFAULT_ORDERS,
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
    for row in rows:
        symbol = str(row.get("symbol", "")).strip().upper()
        if not symbol or symbol in have:
            continue
        book.append({
            "symbol": symbol,
            "name": str(row.get("name") or symbol).strip(),
            "sector": str(row.get("sector") or "").strip(),
        })
        have.add(symbol)
        added += 1
    if added:
        _notice(f"Added {added} {'company' if added == 1 else 'companies'}.")
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
    list_key = f"{index_column}-{sector}-{hash(tuple(editor['symbol']))}"
    select_all = st.checkbox(
        "Select all",
        key=f"trading-agent-select-all-{list_key}",
        help="Check every company in this list.",
    )
    editor.insert(0, "select", bool(select_all))
    edited = st.data_editor(
        editor,
        hide_index=True,
        width="stretch",
        height=420,
        num_rows="fixed",
        key=f"trading-agent-editor-{list_key}-{int(bool(select_all))}",
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
        help="Add every company in this list.",
        width="stretch",
    ):
        _add_rows(view[columns].to_dict(orient="records"))
        st.rerun()


def _grouped(rows: list[dict], key: str) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(str(row.get(key) or ""), []).append(row)
    return grouped


def _paint(payload: dict, companies: list, key_prefix: str) -> None:
    roster = payload.get("roster") or []
    running = [row["agent"] for row in roster if row.get("status") == "running"]
    st.markdown("**Running now**")
    st.caption(", ".join(running) if running else "None")
    logs = _grouped(payload.get("log") or [], "symbol")
    decisions = {row["symbol"]: row for row in payload.get("decisions") or []}
    orders = _grouped(payload.get("orders") or [], "symbol")
    ordered: list[tuple[str, str]] = []
    seen: set[str] = set()
    for company in companies:
        ordered.append((company.symbol, company.name))
        seen.add(company.symbol)
    for symbol in list(logs) + list(decisions) + list(orders):
        if symbol and symbol not in seen:
            ordered.append((symbol, symbol))
            seen.add(symbol)
    if not ordered:
        st.caption("Output appears here as each company finishes.")
        return
    for symbol, name in ordered:
        decision = decisions.get(symbol)
        title = f"{symbol} · {name}"
        if decision:
            title = f"{title} · {decision['action']} {decision['qty'] or ''}".strip()
        with st.expander(title, expanded=False, key=f"{key_prefix}-company-{symbol}", on_change="rerun"):
            company_log = logs.get(symbol) or []
            if not company_log and decision is None and not orders.get(symbol):
                st.caption("Waiting for this company.")
            for line in company_log:
                st.markdown(f"**{line['agent']}**")
                st.text(line.get("text") or "")
            if decision:
                st.markdown(f"**Decision** · {decision['action']} {decision['qty'] or ''}".strip())
                st.text(decision.get("reason") or "")
            company_orders = orders.get(symbol) or []
            if company_orders:
                st.markdown("**Orders**")
                st.dataframe(pd.DataFrame(company_orders), hide_index=True, width="stretch")


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
    count = len(info["symbols"])
    count_label = "company" if count == 1 else "companies"
    label = info["label"]
    with st.expander(
        f"**{label}** · {state_label} · {count} {count_label}",
        expanded=bool(info["in_run"]),
        key=f"trading-agent-open-{label}",
        on_change="rerun",
    ):
        if info["active"]:
            if st.button("Stop", icon=":material/stop:", key=f"trading-agent-stop-{label}"):
                runner.stop()
                st.rerun()
        elif st.button("Dismiss", key=f"trading-agent-dismiss-{label}"):
            st.session_state.trading_agent_runners = [item for item in _runners() if item is not runner]
            st.rerun()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Agent", state_label)
        c2.metric("Schedule", info["schedule"])
        c3.metric("Next run", _clock(info["next_run_at"]))
        c4.metric("Completed runs", info["run_count"])
        st.caption(f"Last finished {_clock(info['last_finished'])}.")
        if info["error"]:
            st.error(info["error"])
        if info["latest"]:
            _paint(info["latest"], runner.companies, f"trading-agent-{label}")
        elif info["active"]:
            st.caption("Waiting for the first pass.")
            for company in runner.companies:
                with st.expander(
                    f"{company.symbol} · {company.name}",
                    expanded=False,
                    key=f"trading-agent-{label}-company-{company.symbol}",
                    on_change="rerun",
                ):
                    st.caption("Waiting for this company.")


def _render_roster(runners: list[ScheduledRunner]) -> None:
    if not runners:
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
count_label = "company" if len(book) == 1 else "companies"
st.caption(f"{len(book)} {count_label}. The desk runs this list when you start the agent.")
if book:
    for row in book:
        symbol = row["symbol"]
        with st.expander(
            f"**{symbol}** · {row.get('name') or symbol}",
            expanded=False,
            key=f"trading-agent-book-{symbol}",
            on_change="rerun",
        ):
            st.write(row.get("sector") or "No sector")
            if st.button("Remove", key=f"trading-agent-remove-one-{symbol}"):
                st.session_state.trading_agent_book = [item for item in book if item["symbol"] != symbol]
                st.rerun()
else:
    st.caption("No companies yet.")

st.subheader("Schedule")
runners = _runners()
active = any(runner.active for runner in runners)
choice_labels = [label for label, _cadence, _minutes in SCHEDULE_CHOICES]
choice = st.selectbox("Run", choice_labels, index=1)
_label, cadence, every_minutes = next(row for row in SCHEDULE_CHOICES if row[0] == choice)
daily_at = None
if cadence in {"daily", "monthly", "quarterly"}:
    daily_at = st.time_input("Time", value=time(9, 30), key="trading-agent-clock")
    if cadence == "monthly":
        st.caption("Day 1 of each month, at this time.")
    elif cadence == "quarterly":
        st.caption("Day 1 of January, April, July, and October, at this time.")
if active:
    st.caption("Agents already running keep the companies and schedule they started with.")

def _make_desk(orders_path):
    """Build a desk from the current module.

    A Streamlit process keeps the first import. If that copy still refuses
    more than five companies, reload the module once and use the new class.
    """
    import importlib

    import agents.agno.trading_desk as trading_desk

    run = trading_desk.TradingDesk.run
    stale = any(
        isinstance(item, str) and "companies at a time" in item
        for item in run.__code__.co_consts
    )
    if stale:
        trading_desk = importlib.reload(trading_desk)
    return trading_desk.TradingDesk(orders_path=orders_path)


start_label = "Start new agent" if active else "Start agent"
if st.button(
    start_label,
    type="primary",
    icon=":material/play_arrow:",
    disabled=not book,
):
    schedule = DeskSchedule(every_minutes=every_minutes, daily_at=daily_at, cadence=cadence)
    companies = [DeskCompany(row["symbol"], row["name"], row.get("sector", "")) for row in book]
    started = ScheduledRunner(
        companies,
        schedule,
        orders_path=DEFAULT_ORDERS,
        desk_factory=lambda: _make_desk(DEFAULT_ORDERS),
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
