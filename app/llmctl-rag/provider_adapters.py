from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import numpy as np
from openai import OpenAI


SUPPORTED_PROVIDERS = {"openai", "gemini"}
DEFAULT_PROVIDER = "openai"


def normalize_provider(value: str | None, default: str = DEFAULT_PROVIDER) -> str:
    candidate = (value or "").strip().lower()
    if candidate in SUPPORTED_PROVIDERS:
        return candidate
    return default


def get_embedding_provider(config) -> str:
    return normalize_provider(getattr(config, "embed_provider", None), DEFAULT_PROVIDER)


def get_chat_provider(config) -> str:
    return normalize_provider(getattr(config, "chat_provider", None), DEFAULT_PROVIDER)


def get_embedding_model(config) -> str:
    provider = get_embedding_provider(config)
    if provider == "gemini":
        return getattr(config, "gemini_embedding_model", "")
    return getattr(config, "openai_embedding_model", "")


def get_chat_model(config) -> str:
    provider = get_chat_provider(config)
    if provider == "gemini":
        return getattr(config, "gemini_chat_model", "")
    return getattr(config, "openai_chat_model", "")


def _provider_api_key(config, provider: str) -> str:
    if provider == "gemini":
        return (
            (getattr(config, "gemini_api_key", None) or "").strip()
            or (getattr(config, "google_api_key", None) or "").strip()
        )
    return (getattr(config, "openai_api_key", None) or "").strip()


def has_embedding_api_key(config) -> bool:
    provider = get_embedding_provider(config)
    return bool(_provider_api_key(config, provider))


def has_chat_api_key(config) -> bool:
    provider = get_chat_provider(config)
    return bool(_provider_api_key(config, provider))


def missing_api_key_message(provider: str, usage: str) -> str:
    if provider == "gemini":
        return (
            f"{usage} requires GEMINI_API_KEY (or GOOGLE_API_KEY) when "
            "provider is set to gemini."
        )
    return f"{usage} requires OPENAI_API_KEY when provider is set to openai."


def _require_api_key(config, provider: str, usage: str) -> str:
    api_key = _provider_api_key(config, provider)
    if api_key:
        return api_key
    raise RuntimeError(missing_api_key_message(provider, usage))


def _load_openai_embedding_function():
    try:
        from chromadb.utils.embedding_functions.openai_embedding_function import (
            OpenAIEmbeddingFunction,
        )
    except Exception:
        from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
    return OpenAIEmbeddingFunction


def _gemini_embedding_model_name(model: str) -> str:
    value = (model or "").strip()
    if value.startswith("models/"):
        return value
    if not value:
        value = "gemini-embedding-001"
    return f"models/{value}"


def _gemini_batch_embed_endpoint(model_name: str) -> str:
    model_path = quote(model_name.strip(), safe="/")
    return (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"{model_path}:batchEmbedContents"
    )


def _extract_embedding_values(item: Any) -> list[float]:
    values: Any = []
    if isinstance(item, dict):
        values = item.get("values") or []
        if not values:
            values = ((item.get("embedding") or {}).get("values") or [])
    if not isinstance(values, list):
        values = []
    return [float(value) for value in values]


def _embed_gemini_texts(
    api_key: str,
    model_name: str,
    texts: list[str],
    *,
    batch_size: int = 64,
) -> list[list[float]]:
    if not texts:
        return []

    endpoint = _gemini_batch_embed_endpoint(model_name)
    vectors: list[list[float]] = []
    chunk_size = max(1, int(batch_size))

    for index in range(0, len(texts), chunk_size):
        batch = texts[index : index + chunk_size]
        payload = {
            "requests": [
                {
                    "model": model_name,
                    "content": {"parts": [{"text": text}]},
                }
                for text in batch
            ]
        }
        request = Request(
            endpoint,
            method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
        )
        try:
            with urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            message = detail.strip() or str(exc)
            raise RuntimeError(f"Gemini embedding request failed: {message}") from exc

        embedded = data.get("embeddings") or []
        if len(embedded) != len(batch):
            raise RuntimeError(
                "Gemini embedding response did not match request size."
            )
        for item in embedded:
            vector = _extract_embedding_values(item)
            if not vector:
                raise RuntimeError("Gemini embedding response was missing vector values.")
            vectors.append(vector)

    if len(vectors) != len(texts):
        raise RuntimeError("Gemini embedding output size mismatch.")
    return vectors


class GeminiEmbeddingFunction:
    def __init__(self, *, api_key: str, model_name: str) -> None:
        self._api_key = api_key
        self._model_name = _gemini_embedding_model_name(model_name)

    @staticmethod
    def _coerce_text_list(
        values: Any = None,
        *,
        input: Any = None,  # noqa: A002
        texts: Any = None,
    ) -> list[str]:
        candidate = values
        if candidate is None:
            candidate = input
        if candidate is None:
            candidate = texts
        if candidate is None:
            return []
        if isinstance(candidate, str):
            return [candidate]
        try:
            return [str(item or "") for item in candidate]
        except TypeError:
            return [str(candidate)]

    def __call__(self, input: list[str]) -> list[np.ndarray]:  # noqa: A002
        return self.embed_documents(input)

    def _embed(self, values: Any = None, **kwargs) -> list[np.ndarray]:
        normalized = self._coerce_text_list(values, **kwargs)
        vectors = _embed_gemini_texts(
            api_key=self._api_key,
            model_name=self._model_name,
            texts=normalized,
        )
        return [np.asarray(vector, dtype=np.float32) for vector in vectors]

    def embed_documents(self, texts: Any = None) -> list[np.ndarray]:
        return self._embed(texts=texts)

    def embed_query(self, input: Any) -> list[np.ndarray]:  # noqa: A002
        return self._embed(input=input)

    @staticmethod
    def name() -> str:
        return "llmctl_gemini_embedding_function"


def build_embedding_function(config):
    provider = get_embedding_provider(config)
    if provider == "gemini":
        api_key = _require_api_key(config, provider, "Embedding")
        return GeminiEmbeddingFunction(
            api_key=api_key,
            model_name=get_embedding_model(config),
        )

    api_key = _require_api_key(config, provider, "Embedding")
    OpenAIEmbeddingFunction = _load_openai_embedding_function()
    return OpenAIEmbeddingFunction(
        api_key=api_key,
        model_name=get_embedding_model(config),
    )


def call_chat_completion(config, messages: list[dict[str, str]]) -> str:
    provider = get_chat_provider(config)
    model = get_chat_model(config)
    temperature = float(getattr(config, "chat_temperature", 0.2))
    api_key = _require_api_key(config, provider, "Chat")

    if provider == "gemini":
        return _call_gemini_chat(
            api_key=api_key,
            model=model,
            messages=messages,
            temperature=temperature,
        )

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
    )
    choice = response.choices[0] if response.choices else None
    content = choice.message.content if choice and choice.message else None
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and item.get("text"):
                    text_parts.append(str(item["text"]))
                continue
            text_value = getattr(item, "text", None)
            if text_value:
                text_parts.append(str(text_value))
        return "\n".join(part.strip() for part in text_parts if part and part.strip()).strip()
    return ""


def _gemini_model_path(model: str) -> str:
    value = (model or "").strip()
    if value.startswith("models/"):
        value = value.split("/", 1)[1]
    if not value:
        value = "gemini-2.5-flash"
    return value


def _messages_to_prompt(messages: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for message in messages:
        role = (message.get("role") or "user").strip().lower()
        text = (message.get("content") or "").strip()
        if not text:
            continue
        if role == "system":
            lines.append(f"SYSTEM: {text}")
        elif role == "assistant":
            lines.append(f"ASSISTANT: {text}")
        else:
            lines.append(f"USER: {text}")
    if not lines:
        return "USER:"
    lines.append("ASSISTANT:")
    return "\n\n".join(lines)


def _call_gemini_chat(
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
) -> str:
    model_path = _gemini_model_path(model)
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{quote(model_path, safe='')}:generateContent"
    )
    payload: dict[str, Any] = {
        "contents": [
            {
                "parts": [
                    {"text": _messages_to_prompt(messages)},
                ]
            }
        ],
        "generationConfig": {"temperature": temperature},
    }
    request = Request(
        endpoint,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        message = detail.strip() or str(exc)
        raise RuntimeError(f"Gemini request failed: {message}") from exc

    candidates = data.get("candidates") or []
    for candidate in candidates:
        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        text_parts = []
        for part in parts:
            text = (part or {}).get("text")
            if text:
                text_parts.append(str(text))
        joined = "".join(text_parts).strip()
        if joined:
            return joined
    return ""
