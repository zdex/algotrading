"""Paths, sidebar settings and cached data loaders shared by every page."""

import os
from pathlib import Path

import pandas as pd
import streamlit as st

from backtester import results_store
from data.feed import DataFeed
from data.universe import UNIVERSE_FILE

ROOT = Path(__file__).resolve().parents[2]
REAL_CACHE = ROOT / "data" / "cache"
SAMPLE_CACHE = ROOT / "data" / "sample_cache"
RESULTS_DIR = ROOT / "results"


def _has_parquet(path: Path) -> bool:
    return path.is_dir() and any(f.suffix == ".parquet" for f in path.iterdir())


def cache_dir() -> str:
    """The data cache picked in the sidebar (real cache unless only sample data exists)."""
    if "cache_choice" not in st.session_state:
        st.session_state.cache_choice = (
            "Real data" if _has_parquet(REAL_CACHE) or not _has_parquet(SAMPLE_CACHE) else "Sample data"
        )
    return str(SAMPLE_CACHE if st.session_state.cache_choice == "Sample data" else REAL_CACHE)


def results_dir() -> str:
    return str(RESULTS_DIR)


@st.cache_data(ttl=30, show_spinner=False)
def list_runs(results_path: str) -> pd.DataFrame:
    return results_store.list_runs(results_path)


@st.cache_data(show_spinner="Loading run…")
def load_run(results_path: str, run_id: str):
    return results_store.load_result(run_id, results_path)


@st.cache_data(ttl=60, show_spinner=False)
def coverage(cache_path: str) -> pd.DataFrame:
    if not os.path.isdir(cache_path):
        return pd.DataFrame()
    return DataFeed(cache_dir=cache_path).coverage_report()


@st.cache_data(ttl=300, show_spinner=False)
def universe_table(cache_path: str) -> pd.DataFrame:
    path = os.path.join(cache_path, UNIVERSE_FILE)
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path, parse_dates=["fetched_at"])


@st.cache_data(show_spinner=False)
def ohlcv(cache_path: str, symbol: str) -> pd.DataFrame | None:
    return DataFeed(cache_dir=cache_path).load_ohlcv(symbol)


@st.cache_data(show_spinner=False)
def closes(cache_path: str, symbols: tuple[str, ...], start=None, end=None) -> pd.DataFrame:
    return DataFeed(cache_dir=cache_path).load_prices(list(symbols), start=start, end=end)


def run_picker(label: str = "Backtest run", key: str = "run_id") -> str | None:
    """Select box of saved runs (newest first). Remembers the choice across pages."""
    runs = list_runs(results_dir())
    if runs.empty:
        return None
    ids = runs["run_id"].tolist()
    labels = {
        r.run_id: f"{r.run_id}  ·  {r.period}  ·  Sharpe {r.sharpe if r.sharpe is not None else '—'}"
        for r in runs.itertuples()
    }
    current = st.session_state.get("selected_run")
    index = ids.index(current) if current in ids else 0
    choice = st.selectbox(label, ids, index=index, format_func=labels.get, key=key)
    st.session_state.selected_run = choice
    return choice


def no_runs_message() -> None:
    st.info(
        "No saved backtests yet. Run one from **Backtest Lab**, or from a terminal: "
        "`python run_backtest_large.py`.",
        icon=":material/info:",
    )
