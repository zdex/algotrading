"""Live Trading: placeholder until the Phase 2 runner publishes its state."""

import streamlit as st

st.title("Live Trading")
st.info(
    "Not connected yet. The Phase 2 files (`run_phase2.py`, the IBKR connection manager and "
    "broker adapter, order manager, scheduler and alerts) weren't among the uploaded files.",
    icon=":material/construction:",
)

st.markdown("""
**What this page will show once it's wired up**

- Connection panel: IB Gateway host/port (paper, 4002), account (masked), connected since, reconnects.
- Live positions and intraday P&L, refreshing every few seconds.
- Order blotter: working, filled, cancelled and timed-out orders from the order manager.
- Scheduler jobs with next and last run times, and the Slack/email alert history.
- Controls (pause new entries, flatten all) behind a confirmation dialog. None of them can
  bypass the live-account safety block.

**Recommended design:** the UI should never connect to IB Gateway itself, so it can't compete
with the live runner for the connection. Instead `run_phase2.py` writes a small state
snapshot (positions, orders, P&L, heartbeat) to a SQLite or JSON file every few seconds, and
this page only reads it. Control actions would go the other way through a small command file
or table that the runner checks.
""")
