"""
Streamlit UI for the algo trading system.

    streamlit run ui/app.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.agno.config import load_env  # noqa: E402

load_env()

import streamlit as st  # noqa: E402

from ui.components import state  # noqa: E402
from ui.components import theme  # noqa: E402,F401  (registers the Plotly template)
from ui.components.llm_picker import render_llm_picker  # noqa: E402

st.set_page_config(page_title="Algo Trading", page_icon=":material/monitoring:", layout="wide")

views = ROOT / "ui" / "views"
pages = {
    "Overview": [
        st.Page(views / "home.py", title="Command Center", icon=":material/dashboard:", default=True),
        st.Page(views / "portfolio.py", title="Portfolio", icon=":material/account_balance_wallet:"),
        st.Page(views / "planning.py", title="Planning", icon=":material/pie_chart:"),
    ],
    "Research": [
        st.Page(views / "companies.py", title="Companies", icon=":material/business:"),
        st.Page(views / "analysis.py", title="Analysis", icon=":material/insights:"),
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
# Hidden so we can put the AI model dropdown above the Overview section.
nav = st.navigation(pages, position="hidden")

with st.sidebar:
    render_llm_picker()
    st.divider()
    for section, section_pages in pages.items():
        st.caption(section)
        for page in section_pages:
            st.page_link(page)
    st.divider()
    st.markdown(":blue-badge[:material/description: PAPER]  :gray-badge[Sandbox mode]")
    options = ["Real data", "Sample data"]
    state.cache_dir()   # initialises the default choice
    st.radio(
        "Price data", options, key="cache_choice", horizontal=True,
        help="Sample data is synthetic (tools/make_sample_data.py) for trying the UI offline.",
    )
    st.caption(f"Cache: `{Path(state.cache_dir()).relative_to(ROOT)}`")

nav.run()
