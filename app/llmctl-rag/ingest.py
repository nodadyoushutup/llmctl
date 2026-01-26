from __future__ import annotations

import argparse
import fnmatch
import os
import sys
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

from config import (
    RagConfig,
    build_source_config,
    chunker_signature,
    load_config,
    max_file_bytes_for,
    parser_signature,
)
from chunkers import build_chunker_registry
from parsers import build_parser_registry, guess_doc_type, is_doc_type_enabled
from pipeline import make_chunk_id, make_doc_group_id
from logging_utils import log_event
from git_sync import ensure_git_repo, git_fetch_and_reset
from settings_store import load_integration_settings
from sources_store import list_sources
from versions import CHUNKER_VERSION, PARSER_VERSION
from token_utils import TokenCounter


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

    doc_type = guess_doc_type(path)
    if doc_type:
        type_globs = config.exclude_globs_by_type.get(doc_type, [])
        for pattern in type_globs:
            if fnmatch.fnmatch(rel_posix, pattern) or fnmatch.fnmatch(rel.name, pattern):
                return True

    return False


def _relative_path(path: Path, config: RagConfig) -> str | None:
    try:
        return path.relative_to(config.repo_root).as_posix()
    except ValueError:
        return None


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


def _is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            chunk = handle.read(2048)
        return b"\x00" in chunk
    except OSError:
        return True


def _skip_reason(path: Path, config: RagConfig, doc_type: str | None) -> str:
    if not is_doc_type_enabled(config, doc_type):
        return "disabled_doc_type"
    try:
        stat = path.stat()
    except OSError:
        return "stat_failed"
    if stat.st_size > max_file_bytes_for(config, doc_type):
        return "too_large"
    if _is_binary(path):
        return "binary_or_unsupported"
    return "parse_failed_or_empty"


def _callable_name(value: object) -> str:
    if value is None:
        return "unknown"
    return getattr(value, "__name__", value.__class__.__name__)



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
    collection,
    config: RagConfig,
    paths: list[Path],
    delete_first: bool = False,
    source_meta: dict[str, object] | None = None,
) -> tuple[int, int, dict[str, int], dict[str, int]]:
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []
    batch_token_total = 0
    token_counter = TokenCounter(config.openai_embedding_model)
    max_request_tokens = int(config.embed_max_tokens_per_request * 0.95)
    max_input_tokens = config.embed_max_tokens_per_input
    if max_request_tokens <= 0:
        max_request_tokens = config.embed_max_tokens_per_request
    if max_input_tokens > max_request_tokens:
        max_input_tokens = max_request_tokens
    max_batch_items = 100

    total_files = 0
    total_chunks = 0
    skipped_files = 0
    files_by_type: dict[str, int] = {}
    chunks_by_type: dict[str, int] = {}
    parser_registry = build_parser_registry()
    chunker_registry = build_chunker_registry()
    parser_sig = parser_signature(config, PARSER_VERSION)
    chunker_sig = chunker_signature(config, CHUNKER_VERSION)

    for path in paths:
        if _is_excluded(path, config):
            log_event(
                "rag_index_skip",
                path=str(path),
                reason="excluded",
            )
            continue

        rel_path = _relative_path(path, config)
        if not rel_path:
            continue

        doc_type_hint = guess_doc_type(path)
        log_event(
            "rag_index_file_start",
            path=str(path),
            rel_path=rel_path,
            doc_type=doc_type_hint,
            message=f"Indexing {rel_path} ({doc_type_hint or 'unknown'})",
        )
        if not is_doc_type_enabled(config, doc_type_hint):
            log_event(
                "rag_index_skip",
                path=str(path),
                reason="disabled_doc_type",
                doc_type=doc_type_hint,
            )
            continue

        should_delete = delete_first
        if not should_delete:
            try:
                existing = collection.get(where={"path": rel_path}, include=["metadatas"])
                for meta in existing.get("metadatas", []) or []:
                    if not meta:
                        continue
                    if (
                        meta.get("parser_signature") != parser_sig
                        or meta.get("chunker_signature") != chunker_sig
                    ):
                        should_delete = True
                        break
            except Exception:
                pass

        if should_delete:
            try:
                collection.delete(where={"path": rel_path})
            except Exception:
                pass

        parser = parser_registry.resolve(path)
        if not parser:
            log_event(
                "rag_index_skip",
                path=str(path),
                reason="no_parser",
                doc_type=doc_type_hint,
            )
            continue
        parser_name = _callable_name(parser)
        log_event(
            "rag_index_parser_selected",
            path=str(path),
            rel_path=rel_path,
            doc_type=doc_type_hint,
            parser=parser_name,
            message=f"Parsing {rel_path} with {parser_name}",
        )
        parsed = parser(path, config)
        if parsed is None:
            skipped_files += 1
            log_event(
                "rag_index_skip",
                path=str(path),
                reason=_skip_reason(path, config, doc_type_hint),
                doc_type=doc_type_hint,
            )
            continue

        total_files += 1
        files_by_type[parsed.doc_type] = files_by_type.get(parsed.doc_type, 0) + 1
        log_event(
            "rag_index_parsed",
            path=str(path),
            rel_path=rel_path,
            doc_type=parsed.doc_type,
            language=parsed.language,
            message=f"Parsed {rel_path} as {parsed.doc_type}",
        )
        file_hash = parsed.source.get("file_hash")
        doc_group_id = make_doc_group_id(Path(rel_path))
        chunker = chunker_registry.resolve(parsed.doc_type)
        if not chunker:
            skipped_files += 1
            log_event(
                "rag_index_skip",
                path=str(path),
                reason="no_chunker",
                doc_type=parsed.doc_type,
            )
            continue
        chunker_name = _callable_name(chunker)
        log_event(
            "rag_index_chunker_selected",
            path=str(path),
            rel_path=rel_path,
            doc_type=parsed.doc_type,
            chunker=chunker_name,
            message=f"Chunking {rel_path} with {chunker_name}",
        )
        chunks = chunker(parsed, config)
        log_event(
            "rag_index_chunked",
            path=str(path),
            rel_path=rel_path,
            doc_type=parsed.doc_type,
            chunk_count=len(chunks),
            message=f"Chunked {rel_path}: {len(chunks)} chunks",
        )
        chunk_counter = 0

        def flush_batch() -> None:
            nonlocal batch_token_total
            if not ids:
                return
            _add_batch(collection, ids, documents, metadatas)
            ids.clear()
            documents.clear()
            metadatas.clear()
            batch_token_total = 0

        for chunk_index, chunk in enumerate(chunks):
            text = chunk.text.strip()
            if not text:
                continue

            source = chunk.source or parsed.doc_type
            page = None
            if chunk.metadata:
                page = chunk.metadata.get("page_number") or chunk.metadata.get("page")

            base_metadata: dict[str, object] = {
                "path": rel_path,
                "doc_type": parsed.doc_type,
                "language": parsed.language,
                "file_hash": file_hash,
                "source": source,
                "doc_group_id": chunk.doc_group_id or doc_group_id,
                "parser_version": PARSER_VERSION,
                "chunker_version": CHUNKER_VERSION,
                "parser_signature": parser_sig,
                "chunker_signature": chunker_sig,
                "original_chunk_index": chunk_index,
            }
            if chunk.start_line is not None:
                base_metadata["start_line"] = chunk.start_line
            if chunk.end_line is not None:
                base_metadata["end_line"] = chunk.end_line
            if chunk.start_offset is not None:
                base_metadata["start_offset"] = chunk.start_offset
            if chunk.end_offset is not None:
                base_metadata["end_offset"] = chunk.end_offset
            if chunk.metadata:
                base_metadata.update(chunk.metadata)
            if source_meta:
                base_metadata.update(source_meta)

            parts = token_counter.split(text, max_input_tokens)
            if len(parts) > 1:
                log_event(
                    "rag_index_chunk_split",
                    path=str(path),
                    doc_type=parsed.doc_type,
                    original_tokens=sum(token_count for _, token_count in parts),
                    split_count=len(parts),
                )

            for part_index, (part_text, token_count) in enumerate(parts):
                if token_count <= 0:
                    continue
                if batch_token_total + token_count > max_request_tokens and ids:
                    flush_batch()
                if token_count > max_request_tokens:
                    flush_batch()

                metadata = dict(base_metadata)
                metadata["chunk_index"] = chunk_counter
                if len(parts) > 1:
                    metadata["split_index"] = part_index
                    metadata["split_count"] = len(parts)

                doc_id = make_chunk_id(Path(rel_path), str(source), page, chunk_counter)
                ids.append(doc_id)
                documents.append(part_text)
                metadatas.append(metadata)
                batch_token_total += token_count
                chunk_counter += 1
                total_chunks += 1
                chunks_by_type[parsed.doc_type] = chunks_by_type.get(parsed.doc_type, 0) + 1

                if len(ids) >= max_batch_items:
                    flush_batch()

        log_event(
            "rag_index_file_complete",
            path=str(path),
            rel_path=rel_path,
            doc_type=parsed.doc_type,
            chunks=chunk_counter,
            message=f"Completed {rel_path}: {chunk_counter} chunks indexed",
        )

    _add_batch(collection, ids, documents, metadatas)
    log_event(
        "rag_index_summary",
        total_files=total_files,
        total_chunks=total_chunks,
        skipped_files=skipped_files,
        files_by_type=files_by_type,
        chunks_by_type=chunks_by_type,
    )
    return total_files, total_chunks, files_by_type, chunks_by_type


def ingest(
    config: RagConfig, reset: bool, source_meta: dict[str, object] | None = None
) -> tuple[int, int, dict[str, int], dict[str, int]]:
    client = chromadb.HttpClient(host=config.chroma_host, port=config.chroma_port)
    collection = get_collection(client, config, reset=reset)
    total_files, total_chunks, files_by_type, chunks_by_type = index_paths(
        collection,
        config,
        list(_iter_files(config)),
        source_meta=source_meta,
    )

    print(
        f"Indexed {total_chunks} chunks from {total_files} files into '{config.collection}'."
    )
    return total_files, total_chunks, files_by_type, chunks_by_type


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
        sources = list_sources()
        if sources:
            github_settings = load_integration_settings("github")
            for source in sources:
                source_config = build_source_config(config, source, github_settings)
                source_meta = {
                    "source_id": source.id,
                    "source_name": source.name,
                    "source_kind": source.kind,
                }
                if source.kind == "github":
                    ensure_git_repo(source_config)
                    git_fetch_and_reset(source_config)
                ingest(source_config, reset=args.reset, source_meta=source_meta)
        else:
            ingest(config, reset=args.reset)
    except Exception as exc:
        print(f"Ingest failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
