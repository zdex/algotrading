"""
Streamlit page for uploading documents and querying the RAG index.

Usage: `streamlit run ui/agent_upload.py`

This simple page:
 - accepts file uploads and saves them to `data/agents/uploads/`
 - reads their text (basic fallback to binary->utf-8)
 - calls `agents.agno.examples.rag_qdrant.index_texts` to index
 - provides a query box that calls `agents.agno.examples.rag_qdrant.query`

Note: Qdrant should be running locally (or set QDRANT_URL). Install requirements first.
"""
import json
import os
import sys
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.agno.examples import rag_qdrant
from agents.agno.workflow import run_agent_workflow
from agents.agno.portfolio_agent import PortfolioAgent
from core.portfolio import Portfolio

UPLOAD_DIR = Path("data/agents/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _safe_decode(raw: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


def _read_text_from_csv(raw: bytes) -> str:
    try:
        import csv
        from io import StringIO

        text = raw.decode("utf-8", errors="replace")
        rows = list(csv.reader(StringIO(text)))
        return "\n".join(", ".join(r) for r in rows if r)
    except Exception:
        return _safe_decode(raw)


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
        return _read_text_from_csv(raw)
    if suffix == ".pdf":
        return _read_pdf_text(raw)
    if suffix == ".docx":
        return _read_docx_text(raw)

    try:
        return _safe_decode(raw)
    except Exception:
        return str(raw)


def build_portfolio_context(portfolio_snapshot: Optional[Dict[str, Any]] = None) -> str:
    """Create a plain-language portfolio summary that can be merged into a query context."""
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

    positions = portfolio_snapshot.get("positions", [])
    if positions:
        lines.append("Open positions:")
        for pos in positions:
            symbol = pos.get("symbol", "UNKNOWN")
            qty = pos.get("qty", 0)
            avg = pos.get("avg_price", 0)
            mkt = pos.get("market_value", 0)
            lines.append(f"- {symbol}: qty={qty}, avg_price={avg}, market_value=${mkt:,.2f}")

    trades = portfolio_snapshot.get("trades", [])
    if trades:
        lines.append("Recent trades:")
        for trade in trades:
            symbol = trade.get("symbol", "UNKNOWN")
            direction = trade.get("direction", "UNKNOWN")
            pnl = trade.get("net_pnl", 0)
            lines.append(f"- {symbol}: {direction}, net_pnl=${pnl:,.2f}")

    return "\n".join(lines)


def build_live_portfolio_context() -> str:
    """Use a real Portfolio model when available; otherwise use the demo summary."""
    portfolio = Portfolio(initial_cash=100_000.0)
    agent = PortfolioAgent(portfolio)
    return agent.build_context()


UPLOAD_DIR = Path("data/agents/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def main():
    st.title("AI Analyst + Portfolio RAG")
    st.caption("Upload filings, research notes, earnings reports, or other documents and ask portfolio-aware questions.")

    with st.sidebar:
        st.subheader("Portfolio context")
        include_context = st.checkbox("Include portfolio summary in answer context", value=True)
        st.write("Sample portfolio context is included when no live portfolio is connected.")

    uploaded_files = st.file_uploader("Upload documents", type=["txt", "md", "csv", "json", "pdf", "docx"], accept_multiple_files=True)

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

            res = rag_qdrant.index_texts(texts, metadatas=metadata)
            st.success(f"Indexed {res.get('count', 0)} documents")

    st.subheader("Ask a question")
    query = st.text_area("Question", value="Summarize the latest company update and explain how it affects my portfolio.")
    if st.button("Ask the agent") and query:
        context_text = ""
        if include_context:
            context_text = build_live_portfolio_context()

        with st.spinner("Retrieving relevant documents..."):
            out = rag_qdrant.query(query, top_k=5)

        if out.get("error"):
            st.error(out["error"])
            return

        context_docs = "\n\n".join(d.get("text", "") for d in out.get("docs", []))
        workflow_output = run_agent_workflow(query, context_docs + "\n\n" + context_text)

        st.subheader("Retrieved context")
        if out.get("docs"):
            for doc in out["docs"]:
                st.write(f"- {doc.get('source', '(unknown)')} (score={doc.get('score', 0):.3f})")
                st.write(doc.get("text", "")[:1200])
        else:
            st.info("No matching documents were found in the index yet. Upload documents first.")

        if context_text:
            st.subheader("Portfolio context")
            st.write(context_text)

        st.subheader("Agent workflow")
        st.json(workflow_output)

        if out.get("answer"):
            st.subheader("Answer")
            st.write(out["answer"])
        else:
            st.info("No OpenAI key configured, so no synthesized LLM answer is available yet.")


if __name__ == "__main__":
    main()
