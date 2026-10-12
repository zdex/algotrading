"""Paper Trading: sandbox trading dashboard for demo and paper-account workflows."""

from datetime import date

import pandas as pd
import streamlit as st

from ui.components import state

st.title("Paper Trading")
st.caption("Sandbox execution screen for demo paper-account workflows, order monitor, and trade snapshots.")

cache = state.cache_dir()

# demo / placeholder data
positions = pd.DataFrame([
    {"symbol": "AAPL", "qty": 18, "avg_cost": 221.34, "last": 228.10, "pnl": 122.0},
    {"symbol": "MSFT", "qty": 10, "avg_cost": 412.80, "last": 418.55, "pnl": 57.5},
    {"symbol": "NVDA", "qty": 12, "avg_cost": 136.40, "last": 142.90, "pnl": 78.0},
])
orders = pd.DataFrame([
    {"time": pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M:%S"), "symbol": "META", "side": "BUY", "qty": 20, "status": "Queued"},
    {"time": pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M:%S"), "symbol": "AMD", "side": "SELL", "qty": 15, "status": "Filled"},
])

c1, c2, c3, c4 = st.columns(4)
c1.metric("Net liquidation", "$1,243,000", "+$18,400", border=True)
c2.metric("Buying power", "$468,000", "12.4%", border=True)
c3.metric("Open positions", "3", "2 longs / 1 short", border=True)
c4.metric("Today P&L", "+$258.50", "+1.9%", border=True)

st.subheader("Execution controls")
control1, control2, control3 = st.columns(3)
with control1:
    st.selectbox("Broker mode", ["Paper account", "Simulation", "Disconnected"], index=0)
with control2:
    st.selectbox("Order type", ["Market", "Limit", "Stop"], index=0)
with control3:
    st.selectbox("Risk guard", ["Normal", "Tighter", "Pause all new entries"], index=0)

with st.form("paper_trade_form"):
    c1, c2, c3 = st.columns(3)
    symbol = c1.text_input("Symbol", value="AAPL")
    side = c2.selectbox("Side", ["BUY", "SELL"], index=0)
    qty = c3.number_input("Qty", min_value=1, max_value=1000, value=10, step=1)
    price = st.number_input("Limit price", min_value=1.0, value=220.0, step=0.01)
    submit = st.form_submit_button("Send paper order", type="primary")

if submit:
    st.success(f"Paper order queued: {side} {qty} {symbol} @ ${price:.2f}")

st.subheader("Open positions")
if positions.empty:
    st.info("No open positions.")
else:
    st.dataframe(
        positions.assign(pnl=lambda d: d["pnl"].map(lambda x: f"${x:,.2f}")),
        hide_index=True,
        width="stretch",
    )

st.subheader("Order blotter")
if orders.empty:
    st.info("No recent orders.")
else:
    st.dataframe(orders, hide_index=True, width="stretch")

st.subheader("Sandbox settings")
with st.expander("Paper trading configuration", expanded=False):
    col1, col2, col3 = st.columns(3)
    with col1:
        st.date_input("Session date", value=date.today())
    with col2:
        st.number_input("Max daily loss (%)", min_value=0.1, max_value=20.0, value=5.0, step=0.1)
    with col3:
        st.number_input("Max gross exposure (%)", min_value=10.0, max_value=300.0, value=150.0, step=5.0)

    st.text_area(
        "Notes",
        value="Paper mode is for simulation only. Orders are not sent to a live broker and do not represent live capital deployment.",
        height=80,
    )

st.caption(f"Data source: `{cache}`")
