"""Provider-agnostic LLM helpers for OpenAI, Gemini, and Ollama."""
from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Iterable, Sequence

import requests

from agents.agno.config import env_secret, openai_api_key

DEFAULT_OPENAI_MODELS = (
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4.1-mini",
    "gpt-4.1",
    "o4-mini",
    "o3-mini",
)
DEFAULT_GEMINI_MODELS = (
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
)
DEFAULT_OLLAMA_MODELS = (
    "llama3.1",
    "llama3.1:8b",
    "llama3.2",
    "mistral",
    "qwen2.5",
    "phi4",
)
PROVIDER_LABELS = {
    "openai": "OpenAI",
    "gemini": "Gemini",
    "ollama": "Ollama",
}


@dataclass(frozen=True)
class LLMChoice:
    provider: str
    model: str

    @property
    def id(self) -> str:
        return f"{self.provider}:{self.model}"

    @property
    def label(self) -> str:
        return f"{PROVIDER_LABELS.get(self.provider, self.provider)} · {self.model}"


def ollama_host() -> str:
    return (os.getenv("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")


def list_ollama_models(timeout: float = 0.6) -> list[str]:
    try:
        resp = requests.get(f"{ollama_host()}/api/tags", timeout=timeout)
        resp.raise_for_status()
        names = []
        for item in resp.json().get("models", []):
            name = (item.get("name") or "").strip()
            if name:
                names.append(name.split(":")[0] if name.endswith(":latest") else name)
        return sorted(set(names))
    except Exception:
        return []


def available_choices(ollama_models: Sequence[str] | None = None) -> list[LLMChoice]:
    ollama = list(ollama_models) if ollama_models is not None else list_ollama_models()
    if not ollama:
        ollama = list(DEFAULT_OLLAMA_MODELS)
    else:
        seen = set(ollama)
        ollama = list(ollama) + [m for m in DEFAULT_OLLAMA_MODELS if m not in seen]
    choices: list[LLMChoice] = []
    for model in DEFAULT_OPENAI_MODELS:
        choices.append(LLMChoice("openai", model))
    for model in DEFAULT_GEMINI_MODELS:
        choices.append(LLMChoice("gemini", model))
    for model in ollama:
        choices.append(LLMChoice("ollama", model))
    return choices


def parse_choice_id(choice_id: str | None) -> LLMChoice:
    raw = (choice_id or "").strip()
    if ":" in raw:
        provider, model = raw.split(":", 1)
        provider = provider.strip().lower()
        model = model.strip()
        if provider in PROVIDER_LABELS and model:
            return LLMChoice(provider, model)
    return LLMChoice("openai", DEFAULT_OPENAI_MODELS[0])


def ollama_timeout_seconds() -> float:
    raw = (os.getenv("OLLAMA_TIMEOUT") or "600").strip()
    try:
        return max(30.0, float(raw))
    except ValueError:
        return 600.0


def missing_credentials_message(provider: str) -> str:
    if provider == "openai":
        return "No valid OPENAI_API_KEY found. Add it to the project `.env` and restart Streamlit."
    if provider == "gemini":
        return "No valid GEMINI_API_KEY found. Add it to the project `.env` and restart Streamlit."
    if provider == "ollama":
        return (
            f"Could not reach Ollama at {ollama_host()}. "
            "Start Ollama locally, or set OLLAMA_HOST in `.env`."
        )
    return f"Unknown LLM provider: {provider}"


def generate(prompt: str, *, provider: str, model: str, max_tokens: int = 1024) -> str:
    provider = (provider or "openai").strip().lower()
    model = (model or "").strip()
    if not model:
        return "LLM error: no model selected."
    try:
        if provider == "openai":
            return _generate_openai(prompt, model, max_tokens)
        if provider == "gemini":
            return _generate_gemini(prompt, model, max_tokens)
        if provider == "ollama":
            return _generate_ollama(prompt, model, max_tokens)
        return f"LLM error: unsupported provider '{provider}'."
    except Exception as e:
        return f"LLM error: {e}"


def _generate_openai(prompt: str, model: str, max_tokens: int) -> str:
    api_key = openai_api_key()
    if not api_key:
        return missing_credentials_message("openai")
    try:
        import openai
    except Exception as e:
        return f"LLM error: OpenAI package is not installed ({e})."

    if hasattr(openai, "OpenAI"):
        client = openai.OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.0,
        )
        content = resp.choices[0].message.content
        return (content or "").strip() or "LLM error: empty OpenAI response."

    resp = openai.Completion.create(
        model=model,
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=0.0,
    )
    return resp.choices[0].text.strip()


def _generate_gemini(prompt: str, model: str, max_tokens: int) -> str:
    api_key = env_secret("GEMINI_API_KEY") or env_secret("GOOGLE_API_KEY")
    if not api_key:
        return missing_credentials_message("gemini")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    )
    resp = requests.post(
        url,
        params={"key": api_key},
        json={
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": max_tokens},
        },
        timeout=60,
    )
    payload = resp.json() if resp.content else {}
    if resp.status_code >= 400:
        err = payload.get("error", {}).get("message") or resp.text
        return f"LLM error: {err}"
    candidates = payload.get("candidates") or []
    parts: Iterable[dict] = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts).strip()
    return text or "LLM error: empty Gemini response."


def _generate_ollama(prompt: str, model: str, max_tokens: int) -> str:
    timeout = ollama_timeout_seconds()
    # Keep local replies shorter so CPU inference finishes in a reasonable time.
    predict = min(max_tokens, 512)
    try:
        resp = requests.post(
            f"{ollama_host()}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.0, "num_predict": predict},
            },
            timeout=timeout,
        )
    except requests.Timeout:
        return (
            f"LLM error: Ollama timed out after {int(timeout)}s while running `{model}`. "
            "The model may still be loading, or CPU inference is slow for a large prompt. "
            "Retry once, use a smaller model, or set OLLAMA_TIMEOUT in `.env`."
        )
    except requests.RequestException as e:
        return f"{missing_credentials_message('ollama')} ({e})"
    payload = resp.json() if resp.content else {}
    if resp.status_code >= 400:
        err = payload.get("error") or resp.text
        return f"LLM error: {err}"
    message = payload.get("message") or {}
    text = (message.get("content") or payload.get("response") or "").strip()
    return text or "LLM error: empty Ollama response."
