from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[2]


def _is_placeholder_key(value: str) -> bool:
    key = (value or "").strip().lower()
    if not key:
        return True
    return (
        key.startswith("sk-your-")
        or "your-api-key" in key
        or key in {"changeme", "replace-me", "none", "null"}
    )


def _parse_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, raw = stripped.partition("=")
        name = name.strip()
        value = raw.strip().strip("'").strip('"')
        if name:
            values[name] = value
    return values


def load_env() -> None:
    """Load project `.env`, replacing missing or placeholder values."""
    for name, value in _parse_dotenv(ROOT / ".env").items():
        current = os.environ.get(name, "")
        if name not in os.environ or _is_placeholder_key(current):
            os.environ[name] = value


def env_secret(name: str) -> str | None:
    key = (os.getenv(name) or "").strip()
    if _is_placeholder_key(key):
        return None
    return key


def openai_api_key() -> str | None:
    return env_secret("OPENAI_API_KEY")


load_env()


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
