AGNO (phidata) pipeline scaffold for algotrading

What this scaffold contains

- `config.py` — basic configuration dataclass for vector DB, models and storage.
- `pipeline.py` — high-level Python skeleton with steps: ingest, process, embed_index, run_agent.

How to proceed

1. Install AGNO / phidata and other deps in your environment (example):

```powershell
pip install phidata qdrant-client sentence-transformers
```

2. Replace the task bodies in `pipeline.py` with phidata Task/Operator implementations and
   wire them into a phidata DAG/workflow.

3. Add connectors for your vector DB (Qdrant/Weaviate) and embedding/LLM providers.

4. Integrate the agent run with your Streamlit UI by exposing a background task or HTTP endpoint
   that executes `run_agent()` or triggers the AGNO workflow.

Suggested next steps I can do for you

- Convert these placeholders into runnable phidata tasks and a sample DAG.
- Add Qdrant + OpenAI embedding example and a small RAG retriever.
- Add a Streamlit upload endpoint that stores user files to `data/agents/uploads`.

Tell me which of the next steps you want me to implement first.
