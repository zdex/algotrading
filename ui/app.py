"""
Streamlit UI for the algo trading system.

    streamlit run ui/app.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from ui.components import state  # noqa: E402
from ui.components import theme  # noqa: E402,F401  (registers the Plotly template)

st.set_page_config(page_title="Algo Trading", page_icon=":material/monitoring:", layout="wide")

views = ROOT / "ui" / "views"
pages = {
    "Overview": [
        st.Page(views / "home.py", title="Command Center", icon=":material/dashboard:", default=True),
        st.Page(views / "portfolio.py", title="Portfolio", icon=":material/account_balance_wallet:"),
    ],
    "Research": [
        st.Page(views / "backtest_lab.py", title="Backtest Lab", icon=":material/science:"),
        st.Page(views / "results.py", title="Backtest Results", icon=":material/query_stats:"),
        st.Page(views / "strategy_explorer.py", title="Strategy Explorer", icon=":material/candlestick_chart:"),
        st.Page(views / "risk.py", title="Risk", icon=":material/shield:"),
        st.Page(views / "phase1.py", title="Phase 1 Validation", icon=":material/fact_check:"),
    ],
    "Trading": [
        st.Page(views / "paper.py", title="Paper Trading", icon=":material/trending_up:"),
        st.Page(views / "live.py", title="Live Trading", icon=":material/sensors:"),
    ],
    "Data": [
        st.Page(views / "universe_data.py", title="Universe & Data", icon=":material/database:"),
    ],
}
nav = st.navigation(pages)

with st.sidebar:
    st.markdown(":blue-badge[:material/description: PAPER]  :gray-badge[Sandbox mode]")
    options = ["Real data", "Sample data"]
    state.cache_dir()   # initialises the default choice
    st.radio(
        "Price data", options, key="cache_choice", horizontal=True,
        help="Sample data is synthetic (tools/make_sample_data.py) for trying the UI offline.",
    )
    st.caption(f"Cache: `{Path(state.cache_dir()).relative_to(ROOT)}`")

nav.run()
