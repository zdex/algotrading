"""Pick index constituents and queue them for the company analysis agent."""

import pandas as pd
import streamlit as st

from agents.agno.company_analysis_agent import CompanyAnalysisAgent
from data.universe import load_company_directory
from ui.components import state

st.title("Companies")
st.caption(
    "S&P 500, NASDAQ-100, and Dow 30. Select names and submit them to the analysis agent. "
    "This phase records the basket and returns a placeholder signal. It does not call a model."
)

INDEX_FILTERS = {
    "S&P 500": "sp500",
    "NASDAQ-100": "nasdaq100",
    "Dow 30": "dow30",
}


def _load(refresh: bool = False) -> pd.DataFrame:
    table = load_company_directory(state.cache_dir(), refresh=refresh)
    state.company_directory.clear()
    return table


if "selected_company_symbols" not in st.session_state:
    st.session_state.selected_company_symbols = []
if "company_editor_nonce" not in st.session_state:
    st.session_state.company_editor_nonce = 0

directory = state.company_directory(state.cache_dir())

if directory.empty:
    with st.spinner("Fetching S&P 500, NASDAQ-100, and Dow 30…"):
        directory = _load(refresh=True)
    if directory.empty:
        st.error("Could not load the company list. Check your connection and try again.")
        if st.button("Retry", icon=":material/refresh:"):
            st.rerun()
        st.stop()
    st.rerun()

snap = pd.Timestamp(directory["fetched_at"].max()).date()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Companies", len(directory), border=True)
c2.metric("S&P 500", int(directory["sp500"].sum()), border=True)
c3.metric("NASDAQ-100", int(directory["nasdaq100"].sum()), border=True)
c4.metric("Dow 30", int(directory["dow30"].sum()), border=True)
st.caption(f"Wikipedia snapshot {snap}. A company in more than one index is listed once.")

filters, search_col, refresh_col = st.columns([2, 2, 1])
chosen = filters.multiselect(
    "Index",
    list(INDEX_FILTERS),
    default=list(INDEX_FILTERS),
    placeholder="Choose at least one index",
)
query = search_col.text_input("Search name or ticker", placeholder="Apple or AAPL")
if refresh_col.button("Refresh list", icon=":material/refresh:", width="stretch"):
    previous = pd.Timestamp(directory["fetched_at"].max())
    with st.spinner("Refreshing constituents…"):
        refreshed = _load(refresh=True)
    if refreshed.empty or pd.Timestamp(refreshed["fetched_at"].max()) == previous:
        st.error("Refresh failed. Showing the saved list.")
    else:
        st.rerun()

view = directory
if chosen:
    mask = pd.Series(False, index=view.index)
    for label in chosen:
        mask |= view[INDEX_FILTERS[label]].astype(bool)
    view = view[mask]
else:
    view = view.iloc[0:0]

if query.strip():
    needle = query.strip().upper()
    view = view[
        view["symbol"].str.upper().str.contains(needle, regex=False)
        | view["name"].str.upper().str.contains(needle, regex=False)
    ]

view = view.sort_values(["name", "symbol"]).reset_index(drop=True)
selected = set(st.session_state.selected_company_symbols)

editor = view[["symbol", "name", "indexes"]].copy()
editor.insert(0, "select", editor["symbol"].isin(selected))

edited = st.data_editor(
    editor,
    hide_index=True,
    width="stretch",
    height=480,
    num_rows="fixed",
    key=f"company_editor_{st.session_state.company_editor_nonce}_{hash(tuple(editor['symbol']))}",
    disabled=["symbol", "name", "indexes"],
    column_config={
        "select": st.column_config.CheckboxColumn("Select", default=False),
        "name": "Company",
        "symbol": "Ticker",
        "indexes": "Index",
    },
)

visible = set(edited["symbol"])
checked = set(edited.loc[edited["select"].astype(bool), "symbol"])
selected = (selected - visible) | checked
st.session_state.selected_company_symbols = sorted(selected)

st.caption(f"{len(selected)} selected · {len(view)} shown")

action_col, clear_col = st.columns([1, 4])
run = action_col.button("Submit for analysis", type="primary", icon=":material/play_arrow:")
if clear_col.button("Clear selection"):
    st.session_state.selected_company_symbols = []
    st.session_state.company_editor_nonce += 1
    st.session_state.pop("company_analysis", None)
    st.rerun()

if selected:
    picked = directory[directory["symbol"].isin(selected)].sort_values("name")
    with st.expander(f"Selected companies ({len(picked)})", expanded=False):
        st.dataframe(
            picked[["name", "symbol", "indexes"]],
            hide_index=True,
            width="stretch",
            column_config={"name": "Company", "symbol": "Ticker", "indexes": "Index"},
        )

if run:
    if not selected:
        st.warning("Select at least one company.")
    else:
        picked = directory[directory["symbol"].isin(selected)].sort_values("name")
        payload = [
            {"symbol": row.symbol, "name": row.name, "indexes": row.indexes}
            for row in picked.itertuples(index=False)
        ]
        with st.spinner("Running the analysis agent…"):
            report = CompanyAnalysisAgent().analyze(payload)
        st.session_state.company_analysis = report.to_dict()

report = st.session_state.get("company_analysis")
if report:
    st.subheader("Analysis")
    st.info(report["note"], icon=":material/pending:")
    m1, m2, m3 = st.columns(3)
    m1.metric("Companies", report["company_count"], border=True)
    m2.metric("Status", report["status"], border=True)
    m3.metric("LLM called", "No" if not report["llm_called"] else "Yes", border=True)
    signals = pd.DataFrame(report["signals"])
    if not signals.empty:
        signals["indexes"] = signals["indexes"].apply(
            lambda value: ", ".join(value) if isinstance(value, list) else value
        )
        st.dataframe(
            signals[["name", "symbol", "indexes", "signal", "confidence", "status", "rationale"]],
            hide_index=True,
            width="stretch",
            column_config={
                "name": "Company",
                "symbol": "Ticker",
                "indexes": "Index",
                "signal": "Signal",
                "confidence": st.column_config.NumberColumn("Confidence", format="%.2f"),
                "status": "Status",
                "rationale": "Rationale",
            },
        )
