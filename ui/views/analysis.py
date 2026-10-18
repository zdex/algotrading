"""Analysis page embedded into the main application.

This page replaces the standalone `ui/agent_upload.py` script and is launched as part of
`ui/app.py` via the Streamlit navigation system.
"""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.agno.examples import rag_qdrant
from agents.agno.workflow import run_agent_workflow
from agents.agno.portfolio_agent import PortfolioAgent
from agents.agno.analysis_agents import AnalystPipeline
from core.portfolio import Portfolio

UPLOAD_DIR = ROOT / "data" / "agents" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _safe_decode(raw: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


def _read_pdf_text(raw: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(raw))
        pages = []
        for page in reader.pages:
            txt = page.extract_text() or ""
            if txt:
                pages.append(txt)
        return "\n\n".join(pages)
    except Exception:
        return _safe_decode(raw)


def _read_docx_text(raw: bytes) -> str:
    try:
        from docx import Document

        doc = Document(BytesIO(raw))
        return "\n".join(paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip())
    except Exception:
        return _safe_decode(raw)


def extract_text_from_upload(file_obj, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    raw = file_obj.read()

    if suffix in {".txt", ".md", ".json", ".yaml", ".yml"}:
        return _safe_decode(raw)
    if suffix == ".csv":
        return _safe_decode(raw)
    if suffix == ".pdf":
        return _read_pdf_text(raw)
    if suffix == ".docx":
        return _read_docx_text(raw)
    return _safe_decode(raw)


def build_portfolio_context(portfolio_snapshot: Optional[Dict[str, Any]] = None) -> str:
    if portfolio_snapshot is None:
        portfolio_snapshot = {
            "cash": 25000.0,
            "equity": 156000.0,
            "positions": [
                {"symbol": "AAPL", "qty": 120, "avg_price": 178.5, "market_value": 21400.0},
                {"symbol": "MSFT", "qty": 75, "avg_price": 332.0, "market_value": 24900.0},
                {"symbol": "NVDA", "qty": 80, "avg_price": 840.0, "market_value": 67200.0},
            ],
            "trades": [
                {"symbol": "AAPL", "direction": "LONG", "net_pnl": 1520.0},
                {"symbol": "MSFT", "direction": "SHORT", "net_pnl": 980.0},
            ],
        }

    lines = [
        "Portfolio context:",
        f"Cash: ${portfolio_snapshot.get('cash', 0):,.2f}",
        f"Equity: ${portfolio_snapshot.get('equity', 0):,.2f}",
    ]
    for pos in portfolio_snapshot.get("positions", []):
        lines.append(
            f"- {pos.get('symbol', 'UNKNOWN')}: qty={pos.get('qty', 0)}, "
            f"avg_price={pos.get('avg_price', 0)}, market_value=${pos.get('market_value', 0):,.2f}"
        )
    for trade in portfolio_snapshot.get("trades", []):
        lines.append(
            f"- {trade.get('symbol', 'UNKNOWN')}: {trade.get('direction', 'UNKNOWN')}, "
            f"net_pnl=${trade.get('net_pnl', 0):,.2f}"
        )
    return "\n".join(lines)


def build_live_portfolio_context() -> str:
    portfolio = Portfolio(initial_cash=100_000.0)
    agent = PortfolioAgent(portfolio)
    return agent.build_context()


st.title("Analysis")
st.caption("Fundamental, technical, sentiment, and document-based research for the trading workflow.")

with st.sidebar:
    st.subheader("Analysis modules")
    st.checkbox("Fundamental analysis", value=True)
    st.checkbox("Technical analysis", value=True)
    st.checkbox("Sentiment analysis", value=True)
    st.checkbox("Company news / social / web", value=True)
    st.checkbox("Upload & Q&A", value=True)

st.subheader("Document upload and Q&A")
uploaded_files = st.file_uploader(
    "Upload documents",
    type=["txt", "md", "csv", "json", "pdf", "docx"],
    accept_multiple_files=True,
)

if uploaded_files:
    with st.spinner("Saving and indexing uploaded documents..."):
        texts = []
        metadata = []
        for uploaded in uploaded_files:
            filename = uploaded.name
            text = extract_text_from_upload(uploaded, filename)
            save_path = UPLOAD_DIR / filename
            with open(save_path, "wb") as fh:
                fh.write(uploaded.getvalue())
            texts.append(text)
            metadata.append({"source": str(save_path), "filename": filename})

        try:
            res = rag_qdrant.index_texts(texts, metadatas=metadata)
            st.success(f"Indexed {res.get('count', 0)} documents.")
        except Exception as e:
            # If Qdrant (or other services) are unavailable, show a clear error
            st.error(f"Indexing failed: {e}")
            res = {"status": "error", "count": 0, "error": str(e)}

st.subheader("Ask the analyst")
query = st.text_area(
    "Question",
    value="Summarize the latest company update and explain how it affects my portfolio and risk exposure.",
)

if st.button("Ask the agent") and query:
    with st.spinner("Retrieving relevant docs and building context..."):
        portfolio_context = build_live_portfolio_context()
        retrieval = rag_qdrant.query(query, top_k=5)
        context_text = (
            (retrieval.get("docs", []) and "\n\n".join(d.get("text", "") for d in retrieval.get("docs", [])))
            + "\n\n" + portfolio_context
        )
        workflow = run_agent_workflow(query, context_text)
        analysis = AnalystPipeline().analyze(context_text)

    if retrieval.get("error"):
        st.error(retrieval["error"])
    else:
        st.subheader("Retrieved context")
        for doc in retrieval.get("docs", []):
            st.write(f"- {doc.get('source', '(unknown)')} (score={doc.get('score', 0):.3f})")
            st.write(doc.get("text", "")[:1200])

        st.subheader("Portfolio context")
        st.write(portfolio_context)

        st.subheader("Analysis summary")
        st.metric("Overall bias", analysis["overall_bias"].title())
        st.metric("Overall score", f"{analysis['overall_score']:.3f}")

        for module_name, module in analysis["modules"].items():
            st.write(f"**{module_name.title()}**: {module['summary']}")
            st.write("Key points:")
            for point in module.get("key_points", []):
                st.write(f"- {point}")

        st.subheader("Agent workflow")
        st.json(workflow)

        if retrieval.get("answer"):
            st.subheader("Answer")
            st.write(retrieval["answer"])
        else:
            st.info(
                "No valid OPENAI_API_KEY found. Put a real key in the project `.env` "
                "(not `sk-your-api-key-here`) and restart Streamlit."
            )

# Module cards
st.subheader("Analysis capability map")
col1, col2, col3 = st.columns(3)
with col1:
    st.markdown("### Fundamental")
    st.write("- company analysis\n- results analysis\n- company news analysis")
with col2:
    st.markdown("### Technical & Sentiment")
    st.write("- price action and signal review\n- sentiment scoring\n- message and news tone analysis")
with col3:
    st.markdown("### Research & Agents")
    st.write("- uploaded document Q&A\n- portfolio-aware insights\n- historical trade context")
