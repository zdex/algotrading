"""Pick index constituents and queue them for the company analysis agent."""

import pandas as pd
import streamlit as st

from agents.agno.company_analysis_agent import MAX_COMPANIES, CompanyAnalysisAgent
from data.universe import load_company_directory
from ui.components import state

st.title("Companies")
st.caption(
    "S&P 500, NASDAQ-100, and Dow 30. Select up to "
    f"{MAX_COMPANIES} companies and submit them. Filings, news, price action, and social "
    "run together. The price-action agent marks trend and levels, then the selected "
    "model scores each name long, short, or flat."
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

if "sector" not in directory.columns:
    directory = directory.copy()
    directory["sector"] = "Unknown"

if directory["sector"].fillna("Unknown").eq("Unknown").all():
    with st.spinner("Loading sectors…"):
        directory = _load(refresh=False)
    if not directory.empty and not directory["sector"].fillna("Unknown").eq("Unknown").all():
        st.rerun()

snap = pd.Timestamp(directory["fetched_at"].max()).date()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Companies", len(directory), border=True)
c2.metric("S&P 500", int(directory["sp500"].sum()), border=True)
c3.metric("NASDAQ-100", int(directory["nasdaq100"].sum()), border=True)
c4.metric("Dow 30", int(directory["dow30"].sum()), border=True)
st.caption(f"Wikipedia snapshot {snap}. A company in more than one index is listed once.")

filters, sector_col, search_col, refresh_col = st.columns([1.3, 1.6, 1.5, 1])
chosen = filters.multiselect(
    "Index",
    list(INDEX_FILTERS),
    default=list(INDEX_FILTERS),
    placeholder="Choose at least one index",
)
sector_choices = sorted(
    sector for sector in directory["sector"].dropna().astype(str).unique() if sector and sector != "Unknown"
)
chosen_sectors = sector_col.multiselect(
    "Sector",
    sector_choices,
    placeholder="All sectors",
    help="Show companies in these sectors, then use Select shown to add them.",
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

if chosen_sectors:
    view = view[view["sector"].isin(chosen_sectors)]

if query.strip():
    needle = query.strip().upper()
    view = view[
        view["symbol"].str.upper().str.contains(needle, regex=False)
        | view["name"].str.upper().str.contains(needle, regex=False)
    ]

view = view.sort_values(["sector", "name", "symbol"]).reset_index(drop=True)
selected = set(st.session_state.selected_company_symbols)

editor = view[["symbol", "name", "sector", "indexes"]].copy()
editor.insert(0, "select", editor["symbol"].isin(selected))

edited = st.data_editor(
    editor,
    hide_index=True,
    width="stretch",
    height=480,
    num_rows="fixed",
    key=f"company_editor_{st.session_state.company_editor_nonce}_{hash(tuple(editor['symbol']))}",
    disabled=["symbol", "name", "sector", "indexes"],
    column_config={
        "select": st.column_config.CheckboxColumn("Select", default=False),
        "name": "Company",
        "symbol": "Ticker",
        "sector": "Sector",
        "indexes": "Index",
    },
)

visible = set(edited["symbol"])
checked = set(edited.loc[edited["select"].astype(bool), "symbol"])
selected = (selected - visible) | checked
st.session_state.selected_company_symbols = sorted(selected)

st.caption(
    f"{len(selected)} selected · {len(view)} shown"
    + (f" · {', '.join(sorted(selected))}" if selected else "")
)

action_col, sector_btn, cache_col, clear_col = st.columns([1.3, 1.2, 1.3, 1.2])
use_cache = cache_col.checkbox("Use cached research", value=True)
run = action_col.button("Submit for analysis", type="primary", icon=":material/play_arrow:")
if sector_btn.button("Select shown", help=f"Add the companies in the list, up to {MAX_COMPANIES}."):
    extra = [symbol for symbol in view["symbol"] if symbol not in selected]
    room = max(0, MAX_COMPANIES - len(selected))
    take = extra[:room]
    st.session_state.selected_company_symbols = sorted(selected | set(take))
    st.session_state.company_editor_nonce += 1
    if not extra:
        st.session_state["company_select_note"] = "Every company in the list is already selected."
    elif len(extra) > len(take):
        st.session_state["company_select_note"] = (
            f"Added {len(take)} of {len(extra)} shown companies. A run can include {MAX_COMPANIES}."
        )
    else:
        st.session_state["company_select_note"] = f"Added {len(take)} companies from the list."
    st.rerun()
if note := st.session_state.pop("company_select_note", None):
    st.caption(note)
if clear_col.button("Clear selection"):
    st.session_state.selected_company_symbols = []
    st.session_state.company_editor_nonce += 1
    st.session_state.pop("company_analysis", None)
    st.rerun()

if selected:
    picked = directory[directory["symbol"].isin(selected)].sort_values("name")
    with st.expander(f"Selected companies ({len(picked)})", expanded=False):
        st.dataframe(
            picked[["name", "symbol", "sector", "indexes"]],
            hide_index=True,
            width="stretch",
            column_config={
                "name": "Company",
                "symbol": "Ticker",
                "sector": "Sector",
                "indexes": "Index",
            },
        )

def _render_analysis(report: dict) -> None:
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
    ready = [company for company in (report.get("evidence") or []) if company.get("fetched_at")]
    _render_evidence(ready)


def _render_evidence(evidence: list[dict]) -> None:
    if not evidence:
        return
    st.subheader("Research")
    for company in evidence:
        label = f"{company.get('name', '')} ({company.get('symbol', '')})"
        if company.get("cached"):
            label += " · cached"
        with st.expander(label, expanded=True):
            for error in company.get("errors") or []:
                st.warning(error)
            _render_price_action(company.get("price_action"))
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


def _render_price_action(summary: dict | None) -> None:
    st.markdown("**Price action**")
    if not summary:
        st.caption("No bar analysis.")
        return
    if summary.get("error"):
        st.caption(summary["error"])
        return
    facts = pd.DataFrame([{
        "timeframe": summary.get("timeframe"),
        "bars": summary.get("bars"),
        "last_date": summary.get("last_date"),
        "last_close": summary.get("last_close"),
        "trend": summary.get("trend"),
        "support": summary.get("support"),
        "resistance": summary.get("resistance"),
        "breakout": summary.get("breakout"),
        "gap_pct": summary.get("gap_pct"),
        "volume_vs_average": summary.get("volume_vs_average"),
    }])
    st.dataframe(
        facts,
        hide_index=True,
        width="stretch",
        column_config={
            "timeframe": "Timeframe",
            "bars": "Bars",
            "last_date": "Last bar",
            "last_close": st.column_config.NumberColumn("Close", format="%.2f"),
            "trend": "Trend",
            "support": st.column_config.NumberColumn("Support", format="%.2f"),
            "resistance": st.column_config.NumberColumn("Resistance", format="%.2f"),
            "breakout": "Breakout",
            "gap_pct": st.column_config.NumberColumn("Gap %", format="%.2f"),
            "volume_vs_average": st.column_config.NumberColumn("Volume x avg", format="%.2f"),
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
        live = st.empty()
        names = ", ".join(item["symbol"] for item in payload)
        status.caption(f"Queued {len(payload)} companies: {names}")

        def _progress(index: int, total: int, symbol: str) -> None:
            status.caption(f"Researching and scoring {symbol} ({index} of {total}): {names}")

        def _on_update(report) -> None:
            data = report.to_dict()
            st.session_state.company_analysis = data
            with live.container():
                _render_analysis(data)

        with st.spinner("Collecting evidence and scoring signals…"):
            CompanyAnalysisAgent().analyze(
                payload,
                use_cache=use_cache,
                provider=st.session_state.get("llm_provider"),
                model=st.session_state.get("llm_model"),
                progress=_progress,
                on_update=_on_update,
            )
        status.empty()
elif st.session_state.get("company_analysis"):
    _render_analysis(st.session_state.company_analysis)
