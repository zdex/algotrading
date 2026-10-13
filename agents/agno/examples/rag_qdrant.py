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

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

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


def query(q: str, top_k: int = 3) -> Dict[str, Any]:
    model = _emb_model()
    emb = model.encode([q])[0]
    client = _qdrant_client()
    try:
        hits = client.search(collection_name=INDEX_NAME, query_vector=emb.tolist(), limit=top_k)
    except Exception as e:
        return {"error": str(e)}

    docs = []
    for h in hits:
        docs.append({"id": h.id, "score": h.score, **(h.payload or {})})

    answer = None
    if openai and os.getenv("OPENAI_API_KEY"):
        # simple prompt: provide context and ask model to answer
        ctx = "\n\n".join([d.get("text", "") for d in docs])
        prompt = f"You are an assistant. Use the context to answer the question.\nContext:\n{ctx}\n---\nQuestion: {q}\nAnswer:"
        try:
            resp = openai.Completion.create(
                model="text-davinci-003",
                prompt=prompt,
                max_tokens=256,
                temperature=0.0,
            )
            answer = resp.choices[0].text.strip()
        except Exception as e:
            answer = f"LLM error: {e}"

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
