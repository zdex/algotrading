from dataclasses import dataclass
from pathlib import Path


@dataclass
class AGNOConfig:
    # Vector DB / embeddings / LLM settings
    vector_db: str = "qdrant"  # qdrant | weaviate | pinecone
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    llm_model: str = "gpt-4o"  # replace with your provider/model

    # Local paths
    storage_path: Path = Path("data/agents")

    # AGNO / phidata settings (placeholder)
    schedule: str = "@daily"


config = AGNOConfig()
