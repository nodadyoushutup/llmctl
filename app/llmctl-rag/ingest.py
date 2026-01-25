from __future__ import annotations

import argparse
import fnmatch
import hashlib
import os
import sys
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

from config import RagConfig, load_config


def _is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            chunk = handle.read(2048)
        return b"\x00" in chunk
    except OSError:
        return True


def _is_excluded(path: Path, config: RagConfig) -> bool:
    try:
        rel = path.relative_to(config.repo_root)
    except ValueError:
        return True

    if any(part in config.exclude_dirs for part in rel.parts):
        return True

    rel_posix = rel.as_posix()
    for pattern in config.exclude_globs:
        if fnmatch.fnmatch(rel_posix, pattern) or fnmatch.fnmatch(rel.name, pattern):
            return True

    if config.include_globs:
        for pattern in config.include_globs:
            if fnmatch.fnmatch(rel_posix, pattern) or fnmatch.fnmatch(rel.name, pattern):
                return False
        return True

    return False


def _relative_path(path: Path, config: RagConfig) -> str | None:
    try:
        return path.relative_to(config.repo_root).as_posix()
    except ValueError:
        return None


def _chunk_lines(lines: list[str], chunk_lines: int, overlap_lines: int):
    if chunk_lines <= 0:
        chunk_lines = 120
    overlap_lines = max(0, min(overlap_lines, chunk_lines - 1))

    start = 0
    total = len(lines)
    while start < total:
        end = min(start + chunk_lines, total)
        yield start, end, "".join(lines[start:end])
        if end >= total:
            break
        start = max(0, end - overlap_lines)


def _iter_files(config: RagConfig):
    for root, dirnames, filenames in os.walk(config.repo_root):
        root_path = Path(root)
        dirnames[:] = [
            d for d in dirnames if not _is_excluded(root_path / d, config)
        ]
        for name in filenames:
            path = root_path / name
            if _is_excluded(path, config):
                continue
            yield path


def _read_text(path: Path, config: RagConfig) -> tuple[str, str] | tuple[None, None]:
    try:
        if path.stat().st_size > config.max_file_bytes:
            return None, None
    except OSError:
        return None, None

    if _is_binary(path):
        return None, None

    try:
        data = path.read_bytes()
    except OSError:
        return None, None

    if b"\x00" in data[:2048]:
        return None, None

    text = data.decode("utf-8", errors="ignore")
    if not text.strip():
        return None, None

    file_hash = hashlib.sha1(data).hexdigest()
    return text, file_hash


def _get_embedding_function(config: RagConfig):
    if not config.openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is required to build embeddings. "
            "Set it in your environment before running ingest."
        )
    return OpenAIEmbeddingFunction(
        api_key=config.openai_api_key,
        model_name=config.openai_embedding_model,
    )


def get_collection(client, config: RagConfig, reset: bool):
    if reset:
        try:
            client.delete_collection(name=config.collection)
        except Exception:
            pass

    return client.get_or_create_collection(
        name=config.collection,
        embedding_function=_get_embedding_function(config),
        metadata={"source": "llmctl-rag"},
    )


def _add_batch(collection, ids, documents, metadatas):
    if not ids:
        return
    if hasattr(collection, "upsert"):
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    else:
        collection.add(ids=ids, documents=documents, metadatas=metadatas)


def delete_paths(collection, config: RagConfig, paths: list[Path]) -> int:
    deleted = 0
    for path in paths:
        if _is_excluded(path, config):
            continue
        rel_path = _relative_path(path, config)
        if not rel_path:
            continue
        try:
            collection.delete(where={"path": rel_path})
            deleted += 1
        except Exception:
            continue
    return deleted


def index_paths(
    collection, config: RagConfig, paths: list[Path], delete_first: bool = False
) -> tuple[int, int]:
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []

    total_files = 0
    total_chunks = 0

    for path in paths:
        if _is_excluded(path, config):
            continue

        rel_path = _relative_path(path, config)
        if not rel_path:
            continue

        if delete_first:
            try:
                collection.delete(where={"path": rel_path})
            except Exception:
                pass

        text, file_hash = _read_text(path, config)
        if text is None:
            continue

        total_files += 1
        lines = text.splitlines(keepends=True)

        for chunk_index, (start, end, chunk) in enumerate(
            _chunk_lines(lines, config.chunk_lines, config.chunk_overlap_lines)
        ):
            chunk = chunk.strip()
            if not chunk:
                continue

            doc_id = f"{rel_path}::chunk-{chunk_index}"
            ids.append(doc_id)
            documents.append(chunk)
            metadatas.append(
                {
                    "path": rel_path,
                    "start_line": start + 1,
                    "end_line": end,
                    "chunk_index": chunk_index,
                    "file_hash": file_hash,
                }
            )
            total_chunks += 1

            if len(ids) >= 100:
                _add_batch(collection, ids, documents, metadatas)
                ids.clear()
                documents.clear()
                metadatas.clear()

    _add_batch(collection, ids, documents, metadatas)
    return total_files, total_chunks


def ingest(config: RagConfig, reset: bool) -> None:
    client = chromadb.HttpClient(host=config.chroma_host, port=config.chroma_port)
    collection = get_collection(client, config, reset=reset)
    total_files, total_chunks = index_paths(
        collection, config, list(_iter_files(config))
    )

    print(
        f"Indexed {total_chunks} chunks from {total_files} files into '{config.collection}'."
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Index this repo into ChromaDB")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete and recreate the collection before indexing",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    config = load_config()

    try:
        ingest(config, reset=args.reset)
    except Exception as exc:
        print(f"Ingest failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
