from __future__ import annotations

import argparse
import sys

import chromadb

from config import load_config
from provider_adapters import (
    build_embedding_function,
    get_embedding_provider,
    has_embedding_api_key,
    missing_api_key_message,
)
from sources_store import list_sources


def query(collection, question: str, n_results: int):
    return collection.query(query_texts=[question], n_results=n_results)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query the repo collection in ChromaDB")
    parser.add_argument("question", help="Question to search for")
    parser.add_argument("--top-k", type=int, default=5, help="Number of results")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    config = load_config()
    embed_provider = get_embedding_provider(config)
    if not has_embedding_api_key(config):
        print(missing_api_key_message(embed_provider, "Query"), file=sys.stderr)
        return 1

    client = chromadb.HttpClient(host=config.chroma_host, port=config.chroma_port)
    embedding_fn = build_embedding_function(config)
    sources = list_sources()
    collections = []
    if sources:
        for source in sources:
            try:
                collection = client.get_or_create_collection(
                    name=source.collection, embedding_function=embedding_fn
                )
            except Exception:
                continue
            collections.append((source, collection))
    else:
        try:
            collection = client.get_collection(
                name=config.collection, embedding_function=embedding_fn
            )
        except Exception as exc:
            print(
                f"Failed to load collection '{config.collection}': {exc}",
                file=sys.stderr,
            )
            return 1
        collections.append((None, collection))

    merged = []
    for source, collection in collections:
        results = query(collection, args.question, args.top_k)
        documents = results.get("documents", [[]])[0] or []
        metadatas = results.get("metadatas", [[]])[0] or []
        distances = results.get("distances", [[]])[0] or []
        for doc, meta, distance in zip(documents, metadatas, distances):
            if not doc:
                continue
            meta = meta or {}
            if source:
                meta.setdefault("source_name", source.name)
            score = float(distance) if distance is not None else float("inf")
            merged.append((score, doc, meta))

    merged.sort(key=lambda item: item[0])
    merged = merged[: args.top_k]
    for idx, (_, doc, meta) in enumerate(merged, start=1):
        source_name = meta.get("source_name")
        path = meta.get("path", "unknown")
        start_line = meta.get("start_line", "?")
        end_line = meta.get("end_line", "?")
        prefix = f"{source_name} • " if source_name else ""
        print(f"#{idx} {prefix}{path} ({start_line}-{end_line})")
        print(doc)
        print("-" * 80)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
