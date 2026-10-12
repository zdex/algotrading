"""Cached session state helpers for IBKR paper-trading UI."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]


def ibkr_cache_dir() -> str:
    return str(ROOT / "data" / "ibkr")


def ensure_ibkr_dirs() -> None:
    os.makedirs(ibkr_cache_dir(), exist_ok=True)


def session_defaults() -> None:
    if "ibkr_host" not in st.session_state:
        st.session_state.ibkr_host = "127.0.0.1"
    if "ibkr_port" not in st.session_state:
        st.session_state.ibkr_port = 7497
    if "ibkr_client_id" not in st.session_state:
        st.session_state.ibkr_client_id = 1
