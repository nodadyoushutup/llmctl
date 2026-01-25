from __future__ import annotations

import argparse
import sys

import chromadb

from config import load_config


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

    client = chromadb.HttpClient(host=config.chroma_host, port=config.chroma_port)
    try:
        collection = client.get_collection(name=config.collection)
    except Exception as exc:
        print(f"Failed to load collection '{config.collection}': {exc}", file=sys.stderr)
        return 1

    results = query(collection, args.question, args.top_k)
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]

    for idx, (doc, meta) in enumerate(zip(documents, metadatas), start=1):
        path = meta.get("path", "unknown")
        start_line = meta.get("start_line", "?")
        end_line = meta.get("end_line", "?")
        print(f"#{idx} {path} ({start_line}-{end_line})")
        print(doc)
        print("-" * 80)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
