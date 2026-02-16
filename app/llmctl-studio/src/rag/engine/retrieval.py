from __future__ import annotations

from typing import Any

from rag.providers.adapters import build_embedding_function


def get_collections(config, sources) -> list[dict[str, Any]]:
    import chromadb

    client = chromadb.HttpClient(host=config.chroma_host, port=config.chroma_port)
    embedding_fn = build_embedding_function(config)
    collections: list[dict[str, Any]] = []
    for source in sources:
        collection_name = getattr(source, "collection", None)
        if not collection_name:
            continue
        collection = client.get_or_create_collection(
            name=collection_name,
            embedding_function=embedding_fn,
        )
        collections.append({"source": source, "collection": collection})
    return collections


def query_collections(
    message: str,
    collections: list[dict[str, Any]],
    top_k: int,
) -> tuple[list[str], list[dict[str, Any]]]:
    merged: list[tuple[float, str, dict[str, Any]]] = []
    for entry in collections:
        source = entry.get("source")
        collection = entry.get("collection")
        if not collection:
            continue
        results = collection.query(query_texts=[message], n_results=top_k)
        documents = (results.get("documents") or [[]])[0] or []
        metadatas = (results.get("metadatas") or [[]])[0] or []
        distances = (results.get("distances") or [[]])[0] or []
        for doc, meta, distance in zip(documents, metadatas, distances):
            if not doc:
                continue
            meta = meta or {}
            if source:
                meta.setdefault("source_id", getattr(source, "id", None))
                meta.setdefault("source_name", getattr(source, "name", None))
                meta.setdefault("source_kind", getattr(source, "kind", None))
            score = float(distance) if distance is not None else float("inf")
            merged.append((score, doc, meta))

    merged.sort(key=lambda item: item[0])
    trimmed = merged[:top_k]
    documents = [item[1] for item in trimmed]
    metadatas = [item[2] for item in trimmed]
    return documents, metadatas


def build_query_text(message: str, history: Any, max_history: int) -> str:
    trimmed = trim_history(history, max_history)
    recent_users = [item["content"] for item in trimmed if item["role"] == "user"]
    parts = recent_users[-2:] + [message]
    combined = "\n".join([part for part in parts if part]).strip()
    if not combined:
        return message
    max_chars = 800
    if len(combined) > max_chars:
        combined = combined[-max_chars:]
    return combined


def trim_history(history: Any, max_items: int) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    if not isinstance(history, list):
        return cleaned
    for item in history:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"}:
            continue
        if not isinstance(content, str):
            continue
        text = content.strip()
        if not text:
            continue
        cleaned.append({"role": role, "content": text})
    return cleaned[-max_items:]


def build_context(
    documents: list[str],
    metadatas: list[dict[str, Any]],
    max_chars: int,
    snippet_chars: int,
) -> tuple[str, list[dict[str, Any]]]:
    blocks: list[str] = []
    sources: list[dict[str, Any]] = []
    remaining = max_chars

    for idx, (doc, meta) in enumerate(zip(documents, metadatas), start=1):
        if not doc:
            continue
        meta = meta or {}
        label = format_label(meta)
        snippet = truncate(doc.strip(), snippet_chars)
        sources.append(
            {
                "id": idx,
                "label": label,
                "path": meta.get("path"),
                "start_line": meta.get("start_line"),
                "end_line": meta.get("end_line"),
                "snippet": snippet,
            }
        )

        block_text = f"[{idx}] {label}\n{doc.strip()}"
        if len(block_text) > remaining:
            block_text = block_text[:remaining].rstrip()
        blocks.append(block_text)
        remaining -= len(block_text)
        if remaining <= 0:
            break

    return "\n\n".join(blocks), sources


def format_label(meta: dict[str, Any]) -> str:
    source_name = meta.get("source_name")
    path = meta.get("path", "unknown")
    start_line = meta.get("start_line")
    end_line = meta.get("end_line")
    prefix = f"{source_name} • " if source_name else ""
    if start_line is not None and end_line is not None:
        return f"{prefix}{path}:{start_line}-{end_line}"
    if start_line is not None:
        return f"{prefix}{path}:{start_line}"
    return f"{prefix}{path}"


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
