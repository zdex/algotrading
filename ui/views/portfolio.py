"""Portfolio: view live (actual) and paper portfolio side by side with a toggle."""

from __future__ import annotations

import pandas as pd
import streamlit as st
try:
    from streamlit_autorefresh import st_autorefresh
except Exception:
    def st_autorefresh(*args, **kwargs):
        """Fallback no-op when `streamlit_autorefresh` is not installed.

        This prevents the Streamlit app from crashing; auto-refresh will be disabled.
        """
        return None

from execution.portfolio_service import PortfolioBackend
from ui.components import state

backend = PortfolioBackend()

st.title("Portfolio")
st.caption("Switch between your live IBKR portfolio and the paper-trading portfolio with a single toggle.")

# Toggle: show live (actual) portfolio when True, paper when False
actual = st.toggle(
    "Actual portfolio",
    value=False,
    help="Turn on to show the live IBKR portfolio. Turn off to show the paper-trading portfolio.",
)

mode_label = "Actual portfolio (IBKR)" if actual else "Paper trading portfolio"
st.subheader(mode_label)

# Auto-refresh only when viewing the live portfolio
if actual:
    # refresh every 5 seconds
    st_autorefresh(interval=5_000, key="portfolio_autorefresh")

snapshot = backend.get_snapshot(actual, st.session_state.get("ibkr_trader"))

if actual:
    # Refresh now button
    colr1, colr2 = st.columns([1, 4])
    with colr1:
        if st.button("Refresh now"):
            # force a refresh (this will fetch & persist)
            snapshot = backend.get_snapshot(True, st.session_state.get("ibkr_trader"))
    meta = backend.get_persisted_meta()
    status = "No persisted snapshot" if not meta.get("exists") else (
        f"Last refresh: {meta.get('ts')} ({meta.get('age_seconds')}s ago)"
    )
    colr2.markdown(f"**{status}**")

    if not snapshot.connected:
        # If trader disconnected but we have a persisted snapshot, show it as read-only
        persisted = backend.get_persisted_live_snapshot()
        if persisted.connected:
            st.warning("Live connection lost — showing last persisted snapshot.")
            df = backend.normalise_positions(persisted.positions)
            summary = persisted.summary
        else:
            st.info(snapshot.message or "No live IBKR account is connected right now.", icon=":material/info:")
            st.stop()
    else:
        df = backend.normalise_positions(snapshot.positions)
        summary = snapshot.summary

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Net liquidation", summary.get("NetLiquidation", "—"), "IBKR", border=True)
    c2.metric("Buying power", summary.get("BuyingPower", "—"), "available", border=True)
    c3.metric("Open positions", len(df), "positions", border=True)
    c4.metric("Unrealized P&L", f"${df['pnl'].sum():,.2f}" if not df.empty else "$0.00", "live", border=True)

    st.dataframe(df[["symbol", "qty", "avg_cost", "market_price", "market_value", "pnl"]], hide_index=True, width="stretch")
else:
    snapshot = backend.get_paper_snapshot()
    df = backend.normalise_positions(snapshot.positions)
    summary = snapshot.summary

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Net liquidation", summary.get("Net liquidation", "—"), "+$18,400", border=True)
    c2.metric("Buying power", summary.get("Buying power", "—"), "12.4%", border=True)
    c3.metric("Open positions", summary.get("Open positions", len(df)), "3", border=True)
    c4.metric("Today P&L", summary.get("Today P&L", "—"), "+1.9%", border=True)

    st.dataframe(df[["symbol", "qty", "avg_cost", "market_price", "market_value", "pnl"]], hide_index=True, width="stretch")

st.caption(f"Data source: {state.cache_dir()}")
