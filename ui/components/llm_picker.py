"""Sidebar control for choosing the active LLM provider and model."""
from __future__ import annotations

import streamlit as st

from agents.agno import llm as llm_runtime


@st.cache_data(ttl=30, show_spinner=False)
def _ollama_models() -> tuple[str, ...]:
    return tuple(llm_runtime.list_ollama_models())


def render_llm_picker() -> llm_runtime.LLMChoice:
    choices = llm_runtime.available_choices(_ollama_models())
    ids = [choice.id for choice in choices]
    labels = {choice.id: choice.label for choice in choices}
    default_id = f"{llm_runtime.DEFAULT_CHOICE_PROVIDER}:{llm_runtime.DEFAULT_CHOICE_MODEL}"
    if "llm_choice_id" not in st.session_state:
        st.session_state.llm_choice_id = default_id if default_id in ids else ids[0]
    elif st.session_state.llm_choice_id not in ids:
        st.session_state.llm_choice_id = default_id if default_id in ids else ids[0]
    selected_id = st.selectbox(
        "AI model",
        ids,
        format_func=labels.get,
        key="llm_choice_id",
        help="Used by company signals and Analysis Q&A. OpenAI and Gemini need API keys in `.env`; Ollama talks to a local server.",
    )
    choice = llm_runtime.parse_choice_id(selected_id)
    st.session_state.llm_provider = choice.provider
    st.session_state.llm_model = choice.model
    return choice
