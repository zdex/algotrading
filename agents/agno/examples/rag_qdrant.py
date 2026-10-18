"""
Minimal Qdrant + embeddings + simple RAG example.

Usage:
 - Index a list of texts: call `index_texts(texts, metadatas)`
 - Query: call `query(q, top_k=3)` which returns nearest docs and (optionally) an LLM answer.

Notes:
 - Uses `sentence-transformers` for embeddings and `qdrant-client` for storage.
 - `query()` synthesizes an answer with the selected OpenAI, Gemini, or Ollama model.
"""
import os
from typing import List, Dict, Any, Optional

from agents.agno.llm import generate as generate_llm, parse_choice_id

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
import numpy as np

# Simple in-memory fallback store when Qdrant is not available during development.
_IN_MEMORY_STORE: dict = {"points": [], "dim": None}


INDEX_NAME = "algotrading_docs"
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def _emb_model():
    return SentenceTransformer(EMBED_MODEL)


def _qdrant_client():
    # Default: local Qdrant running on 6333
    url = os.getenv("QDRANT_URL", "http://localhost:6333")
    api_key = os.getenv("QDRANT_API_KEY", None)
    # qdrant-client accepts host and api_key
    return QdrantClient(url=url, api_key=api_key)


def ensure_collection(client: QdrantClient, dim: int):
    try:
        client.get_collection(INDEX_NAME)
    except Exception:
        client.recreate_collection(
            collection_name=INDEX_NAME,
            vectors_config=qmodels.VectorParams(size=dim, distance=qmodels.Distance.COSINE),
        )


def index_texts(texts: List[str], metadatas: Optional[List[Dict[str, Any]]] = None):
    model = _emb_model()
    embeddings = model.encode(texts, show_progress_bar=False)
    # Try Qdrant first; on failure, fall back to an in-memory store.
    try:
        client = _qdrant_client()
        ensure_collection(client, dim=len(embeddings[0]))

        points = []
        for i, (emb, txt) in enumerate(zip(embeddings, texts)):
            payload = {"text": txt}
            if metadatas and i < len(metadatas):
                payload.update(metadatas[i])
            points.append(qmodels.PointStruct(id=str(i), vector=emb.tolist(), payload=payload))

        client.upsert(collection_name=INDEX_NAME, points=points)
        return {"status": "indexed", "count": len(points)}
    except Exception:
        # fallback: store vectors and payloads in memory for the running session
        if _IN_MEMORY_STORE["dim"] is None:
            _IN_MEMORY_STORE["dim"] = len(embeddings[0])

        start_id = len(_IN_MEMORY_STORE["points"])
        for i, (emb, txt) in enumerate(zip(embeddings, texts)):
            payload = {"text": txt}
            if metadatas and i < len(metadatas):
                payload.update(metadatas[i])
            _IN_MEMORY_STORE["points"].append({
                "id": str(start_id + i),
                "vector": np.array(emb, dtype=float),
                "payload": payload,
            })

        return {"status": "fallback_indexed", "count": len(texts)}


def _context_char_limit(provider: Optional[str]) -> int:
    # Local models choke on huge PDF dumps; keep prompts smaller for Ollama.
    if (provider or "").strip().lower() == "ollama":
        return int(os.getenv("OLLAMA_CONTEXT_CHARS", "8000"))
    return int(os.getenv("LLM_CONTEXT_CHARS", "24000"))


def _generate_answer(prompt: str, provider: Optional[str] = None, model: Optional[str] = None) -> str:
    """Generate a final answer with the selected OpenAI, Gemini, or Ollama model."""
    if provider and model:
        choice = parse_choice_id(f"{provider}:{model}")
    else:
        fallback = os.getenv("LLM_CHOICE") or f"openai:{os.getenv('OPENAI_MODEL', 'gpt-4o-mini')}"
        choice = parse_choice_id(fallback)
    max_tokens = 512 if choice.provider == "ollama" else 1024
    return generate_llm(
        prompt,
        provider=choice.provider,
        model=choice.model,
        max_tokens=max_tokens,
    )


def query(q: str, top_k: int = 3, provider: Optional[str] = None, model: Optional[str] = None) -> Dict[str, Any]:
    llm_model = model
    embedder = _emb_model()
    emb = embedder.encode([q])[0]
    # First try Qdrant; if unavailable, use the in-memory store.
    try:
        client = _qdrant_client()
        hits = client.search(collection_name=INDEX_NAME, query_vector=emb.tolist(), limit=top_k)

        docs = []
        for h in hits:
            docs.append({"id": h.id, "score": h.score, **(h.payload or {})})
    except Exception:
        # in-memory linear search using cosine similarity
        docs = []
        if not _IN_MEMORY_STORE["points"]:
            return {"query": q, "docs": [], "answer": None}

        qv = np.array(emb, dtype=float)
        # normalize
        qv_norm = qv / (np.linalg.norm(qv) + 1e-12)
        vectors = np.vstack([p["vector"] for p in _IN_MEMORY_STORE["points"]])
        vec_norms = vectors / (np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-12)
        sims = vec_norms.dot(qv_norm)
        top_idx = np.argsort(-sims)[:top_k]
        for idx in top_idx:
            p = _IN_MEMORY_STORE["points"][int(idx)]
            docs.append({"id": p["id"], "score": float(sims[int(idx)]), **p["payload"]})

    ctx = "\n\n".join([d.get("text", "") for d in docs])
    limit = _context_char_limit(provider)
    if len(ctx) > limit:
        ctx = ctx[:limit] + "\n\n[Context truncated for model speed.]"
    prompt = (
        "You are an assistant. Use the context to answer the question.\n"
        f"Context:\n{ctx}\n---\nQuestion: {q}\nAnswer:"
    )
    answer = _generate_answer(prompt, provider=provider, model=llm_model)

    return {"query": q, "docs": docs, "answer": answer}


if __name__ == "__main__":
    # quick demo
    texts = [
        "Company ABC reported revenue of $1B in Q2 and EPS of $0.50.",
        "Company XYZ announced a new product and saw positive sentiment on social media.",
        "Earnings call highlighted margin expansion and cost savings for Company ABC.",
    ]
    print(index_texts(texts))
    print(query("What did Company ABC report in Q2?", top_k=2))
