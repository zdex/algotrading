"""
Minimal Qdrant + embeddings + simple RAG example.

Usage:
 - Index a list of texts: call `index_texts(texts, metadatas)`
 - Query: call `query(q, top_k=3)` which returns nearest docs and (optionally) an LLM answer.

Notes:
 - Uses `sentence-transformers` for embeddings and `qdrant-client` for storage.
 - If `OPENAI_API_KEY` is set, `query()` will call OpenAI to synthesize an answer from retrieved docs.
"""
from pathlib import Path
import os
from typing import List, Dict, Any, Optional

from agents.agno.config import openai_api_key

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
import numpy as np

# Simple in-memory fallback store when Qdrant is not available during development.
_IN_MEMORY_STORE: dict = {"points": [], "dim": None}

try:
    import openai
except Exception:
    openai = None


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


def _generate_answer(prompt: str, q: str) -> Optional[str]:
    """Generate a final answer using the configured OpenAI client.

    Supports both the modern `openai>=1.0` client (`OpenAI().chat.completions.create`)
    and legacy `openai<1.0` (`Completion.create`) so the app keeps working across
    environments without requiring a full dependency pin.
    """
    if not openai:
        return None

    api_key = openai_api_key()
    if not api_key:
        return None

    try:
        if hasattr(openai, "OpenAI"):
            client = openai.OpenAI(api_key=api_key)
            model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=256,
                temperature=0.0,
            )
            content = resp.choices[0].message.content
            return content.strip() if content else None

        # Backward-compatible fallback for old OpenAI SDKs.
        resp = openai.Completion.create(
            model=os.getenv("OPENAI_MODEL", "text-davinci-003"),
            prompt=prompt,
            max_tokens=256,
            temperature=0.0,
        )
        return resp.choices[0].text.strip()
    except Exception as e:
        return f"LLM error: {e}"


def query(q: str, top_k: int = 3) -> Dict[str, Any]:
    model = _emb_model()
    emb = model.encode([q])[0]
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

    answer = None
    if openai and openai_api_key():
        # simple prompt: provide context and ask model to answer
        ctx = "\n\n".join([d.get("text", "") for d in docs])
        prompt = f"You are an assistant. Use the context to answer the question.\nContext:\n{ctx}\n---\nQuestion: {q}\nAnswer:"
        answer = _generate_answer(prompt, q)

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
