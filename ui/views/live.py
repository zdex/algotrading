"""Live Trading: real IBKR paper-account connection and order management."""

from __future__ import annotations

from datetime import date

import streamlit as st

from execution.adapters.ibkr_paper import IBKRPaperConfig, IBKRPaperTrader
from ui.components import ibkr_state

ibkr_state.session_defaults()

st.title("Live Trading")
st.caption("Connected to Interactive Brokers paper account via the IBKR API.")

if "ibkr_trader" not in st.session_state:
    st.session_state.ibkr_trader = IBKRPaperTrader()

trader: IBKRPaperTrader = st.session_state.ibkr_trader

with st.sidebar:
    st.subheader("IB Gateway")
    host = st.text_input("Host", key="ibkr_host", value=st.session_state.ibkr_host)
    port = st.number_input("Port", min_value=1, max_value=65535, value=int(st.session_state.ibkr_port), step=1)
    client_id = st.number_input("Client ID", min_value=1, max_value=100, value=int(st.session_state.ibkr_client_id), step=1)
    if st.button("Connect to IBKR"):
        trader.config = IBKRPaperConfig(host=host, port=int(port), client_id=int(client_id))
        connected = trader.connect()
        if connected:
            st.session_state.ibkr_connected = True
            st.success(f"Connected to IBKR paper account: {trader.account_id}")
        else:
            st.session_state.ibkr_connected = False
            st.error(f"Connection failed: {trader.connection_error or 'Unknown error'}")
    if st.button("Disconnect"):
        trader.disconnect()
        st.session_state.ibkr_connected = False
        st.success("Disconnected from IBKR")

connected = getattr(st.session_state, "ibkr_connected", trader.connected)

if not connected:
    st.info(
        "IBKR is not connected yet. Start IB Gateway or TWS in paper mode, then connect using the sidebar.",
        icon=":material/info:",
    )
    st.markdown(
        """
        Prerequisites:
        - IB Gateway or TWS running locally
        - Paper trading enabled in the IB account
        - Gateway port usually `7497` for paper trading
        """
    )
    st.stop()

summary = trader.get_account_summary()
positions = trader.get_positions()
orders = trader.get_open_orders()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Account", trader.account_id or "—", "IBKR", border=True)
c2.metric("Buying power", summary.get("BuyingPower", "—"), "available", border=True)
c3.metric("Net liquidation", summary.get("NetLiquidation", "—"), "value", border=True)
c4.metric("Status", "Connected", "live", border=True)

st.subheader("Submit order")
with st.form("ibkr_order_form"):
    col1, col2, col3 = st.columns(3)
    symbol = col1.text_input("Symbol", value="AAPL")
    side = col2.selectbox("Side", ["BUY", "SELL"], index=0)
    qty = col3.number_input("Qty", min_value=1, max_value=1000, value=10, step=1)
    limit_price = st.number_input("Limit price (optional)", min_value=0.0, value=0.0, step=0.01, help="Leave at 0 for market order.")
    submit = st.form_submit_button("Send order", type="primary")

if submit:
    try:
        result = trader.place_order(symbol, side, int(qty), None if limit_price == 0 else float(limit_price))
        st.success(f"Order submitted: {result}")
    except Exception as exc:
        st.error(f"Order failed: {exc}")

st.subheader("Open positions")
if not positions:
    st.info("No open positions in the connected paper account.")
else:
    st.dataframe(positions, hide_index=True, width="stretch")

st.subheader("Open orders")
if not orders:
    st.info("No open orders.")
else:
    st.dataframe(orders, hide_index=True, width="stretch")

st.subheader("Account summary")
if summary:
    st.dataframe(
        [{"tag": k, "value": v} for k, v in summary.items()],
        hide_index=True,
        width="stretch",
    )
else:
    st.info("No account summary returned yet.")

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
