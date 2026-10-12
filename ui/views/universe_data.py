"""Universe & Data: index constituents, sectors, cache coverage, downloads."""

from datetime import date

import pandas as pd
import streamlit as st

from data.feed import DataFeed
from data.universe import load_universe
from ui.components import charts, state

st.title("Universe & Data")

cache = state.cache_dir()
sample = cache.endswith("sample_cache")
uni = state.universe_table(cache)
cov = state.coverage(cache)

tab_uni, tab_cache = st.tabs(["Universe", "Price cache"])

with tab_uni:
    if uni.empty:
        st.info("No universe snapshot yet. Fetch one below.", icon=":material/info:")
    else:
        snap = pd.Timestamp(uni["fetched_at"].max()).date()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Symbols", len(uni), border=True)
        c2.metric("S&P 500", int(uni["sp500"].sum()), border=True)
        c3.metric("NASDAQ-100", int(uni["nasdaq100"].sum()), border=True)
        c4.metric("Snapshot", str(snap), border=True)
        st.caption("These are today's constituents. Backtests over past years miss companies that "
                   "left the indexes (survivorship bias).")

        c1, c2 = st.columns([3, 2])
        with c1:
            sectors = st.multiselect("Sector", sorted(uni["sector"].dropna().unique()))
            q = st.text_input("Search symbol")
            view = uni if not sectors else uni[uni["sector"].isin(sectors)]
            if q:
                view = view[view["symbol"].str.contains(q.strip().upper())]
            if not cov.empty:
                view = view.merge(cov[["symbol", "last_date"]], on="symbol", how="left")
            st.dataframe(view.drop(columns=["fetched_at"]), hide_index=True, width="stretch", height=420,
                         column_config={"last_date": st.column_config.DateColumn("Cached to")})
        with c2:
            counts = uni["sector"].fillna("Unknown").value_counts()
            st.plotly_chart(charts.counts_bar(counts, "Symbols per sector"), width="stretch")

    if not sample:
        if st.button("Refresh universe from Wikipedia", icon=":material/refresh:"):
            with st.spinner("Fetching constituents and sectors…"):
                table = load_universe(cache, refresh=True)
            state.universe_table.clear()
            if table.empty:
                st.error("Fetch failed. Check your internet connection and that lxml/html5lib are installed.")
            else:
                st.success(f"Saved {len(table)} symbols.")
                st.rerun()

with tab_cache:
    if cov.empty:
        st.info("The price cache is empty.", icon=":material/info:")
    else:
        cov = cov.copy()
        cov["last_date"] = pd.to_datetime(cov["last_date"])
        newest = cov["last_date"].max()
        cov["stale_days"] = (newest - cov["last_date"]).dt.days
        c1, c2, c3 = st.columns(3)
        c1.metric("Cached symbols", int(cov["cached"].sum()), border=True)
        c2.metric("Latest date", str(newest.date()) if pd.notna(newest) else "—", border=True)
        c3.metric("Behind latest by > 5 days", int((cov["stale_days"] > 5).sum()), border=True)
        only_stale = st.toggle("Only show symbols behind the latest date")
        view = cov[cov["stale_days"] > 5] if only_stale else cov
        st.dataframe(view, hide_index=True, width="stretch", height=420, column_config={
            "first_date": st.column_config.DateColumn("First"),
            "last_date": st.column_config.DateColumn("Last"),
            "file_updated": st.column_config.DatetimeColumn("File updated", format="YYYY-MM-DD HH:mm"),
            "stale_days": st.column_config.NumberColumn("Days behind"),
        })

    if sample:
        st.caption("Sample data is synthetic. Regenerate it with `python tools/make_sample_data.py`.")
    else:
        st.subheader("Download / update prices")
        with st.form("download"):
            c1, c2, c3 = st.columns(3)
            start = c1.date_input("From", value=date(2019, 1, 1))
            end = c2.date_input("To (exclusive)", value=date.today())
            force = c3.toggle("Re-download everything")
            go = st.form_submit_button("Download", icon=":material/download:")
        if go:
            if uni.empty:
                st.error("Fetch the universe first.")
            else:
                symbols = uni["symbol"].tolist() + ["SPY", "QQQ"]
                with st.spinner(f"Downloading {len(symbols)} symbols… this takes a few minutes the first time"):
                    stats = DataFeed(cache_dir=cache).download(symbols, start=str(start), end=str(end), force=force)
                state.coverage.clear()
                st.success(f"Downloaded {stats['downloaded']}, already cached {stats['cached']}, "
                           f"failed {stats['failed']}.")
