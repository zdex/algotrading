"""Pick index constituents and queue them for the company analysis agent."""

import pandas as pd
import streamlit as st

from agents.agno.company_analysis_agent import MAX_COMPANIES, CompanyAnalysisAgent
from data.universe import load_company_directory
from ui.components import state

st.title("Companies")
st.caption(
    "S&P 500, NASDAQ-100, and Dow 30. Select up to "
    f"{MAX_COMPANIES} companies and submit them. The analysis agent collects SEC filings, "
    "recent news, and X posts, then the selected model scores each name long, short, or flat."
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

action_col, cache_col, clear_col = st.columns([1.2, 1.4, 3])
use_cache = cache_col.checkbox("Use cached research", value=True)
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
    elif len(selected) > MAX_COMPANIES:
        st.warning(f"Select at most {MAX_COMPANIES} companies for one research run.")
    else:
        picked = directory[directory["symbol"].isin(selected)].sort_values("name")
        payload = [
            {"symbol": row.symbol, "name": row.name, "indexes": row.indexes}
            for row in picked.itertuples(index=False)
        ]
        status = st.empty()

        def _progress(index: int, total: int, symbol: str) -> None:
            status.caption(f"Researching and scoring {symbol} ({index} of {total})")

        with st.spinner("Collecting evidence and scoring signals…"):
            report = CompanyAnalysisAgent().analyze(
                payload,
                use_cache=use_cache,
                provider=st.session_state.get("llm_provider"),
                model=st.session_state.get("llm_model"),
                progress=_progress,
            )
        status.empty()
        st.session_state.company_analysis = report.to_dict()


def _render_evidence(evidence: list[dict]) -> None:
    if not evidence:
        return
    st.subheader("Research")
    for company in evidence:
        label = f"{company.get('name', '')} ({company.get('symbol', '')})"
        if company.get("cached"):
            label += " · cached"
        with st.expander(label, expanded=len(evidence) == 1):
            for error in company.get("errors") or []:
                st.warning(error)
            st.markdown("**Filings**")
            _records(
                company.get("filings") or [],
                ["form", "period_end", "filed_at", "source", "url"],
                {"form": "Form", "period_end": "Period end", "filed_at": "Filed", "source": "Source", "url": "Document"},
            )
            st.markdown("**News**")
            _records(
                company.get("news") or [],
                ["published_at", "source", "title", "url"],
                {"published_at": "Published", "source": "Source", "title": "Headline", "url": "Link"},
            )
            st.markdown("**Social**")
            _records(
                company.get("social") or [],
                ["posted_at", "author", "sentiment", "score", "text", "url"],
                {
                    "posted_at": "Posted",
                    "author": "Author",
                    "sentiment": "Sentiment",
                    "score": "Score",
                    "text": "Post",
                    "url": "Link",
                },
            )


def _records(rows: list[dict], columns: list[str], labels: dict[str, str]) -> None:
    if not rows:
        st.caption("Nothing collected.")
        return
    frame = pd.DataFrame(rows)
    keep = [column for column in columns if column in frame.columns]
    config = {}
    for column in keep:
        if column == "url":
            config[column] = st.column_config.LinkColumn(labels[column], display_text="Open")
        elif column == "score":
            config[column] = st.column_config.NumberColumn(labels[column], format="%.2f")
        else:
            config[column] = labels[column]
    st.dataframe(frame[keep], hide_index=True, width="stretch", column_config=config)


report = st.session_state.get("company_analysis")
if report:
    st.subheader("Analysis")
    icon = ":material/check_circle:" if report.get("llm_called") else ":material/pending:"
    st.info(report["note"], icon=icon)
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

    _render_evidence(report.get("evidence") or [])
