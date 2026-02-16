from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
import fnmatch
import os
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable

try:
    import chromadb
except ImportError:  # pragma: no cover
    chromadb = None

from rag.engine.config import (
    RagConfig,
    build_source_config,
    chunker_signature,
    load_config,
    max_file_bytes_for,
    parser_signature,
)
from rag.engine.chunkers import build_chunker_registry
from rag.engine.parsers import build_parser_registry, guess_doc_type, is_doc_type_enabled
from rag.engine.pipeline import make_chunk_id, make_doc_group_id
from rag.engine.logging_utils import log_event, submit_with_log_context
from rag.integrations.git_sync import ensure_git_repo, git_fetch_and_reset
from rag.integrations.google_drive_sync import sync_folder
from rag.repositories.sources import list_sources
from rag.engine.versions import CHUNKER_VERSION, PARSER_VERSION
from rag.providers.adapters import build_embedding_function, get_embedding_model
from rag.engine.token_utils import TokenCounter


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
        dirnames[:] = sorted(
            [d for d in dirnames if not _is_excluded(root_path / d, config)],
            key=str.lower,
        )
        for name in sorted(filenames, key=str.lower):
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
    return build_embedding_function(config)


def get_collection(client, config: RagConfig, reset: bool):
    if reset:
        try:
            client.delete_collection(name=config.collection)
        except Exception:
            pass

    return client.get_or_create_collection(
        name=config.collection,
        embedding_function=_get_embedding_function(config),
        metadata={"source": "llmctl-studio-rag"},
    )


def _add_batch(collection, ids, documents, metadatas):
    if not ids:
        return
    if hasattr(collection, "upsert"):
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    else:
        collection.add(ids=ids, documents=documents, metadatas=metadatas)


def _is_rate_limit_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "429" in message or "too many requests" in message or "rate limit" in message


def _retry_backoff_seconds(attempt: int) -> float:
    return min(30.0, 1.5 * (2**attempt))


class _EmbedBatchRateLimiter:
    def __init__(self, *, min_interval_s: float, tokens_per_minute: int) -> None:
        self._min_interval_s = max(0.0, float(min_interval_s))
        self._tokens_per_minute = max(0, int(tokens_per_minute))
        self._last_request_at = 0.0
        self._recent_requests: deque[tuple[float, int]] = deque()
        self._recent_tokens = 0

    def _prune(self, now: float) -> None:
        cutoff = now - 60.0
        while self._recent_requests and self._recent_requests[0][0] <= cutoff:
            _, tokens = self._recent_requests.popleft()
            self._recent_tokens = max(0, self._recent_tokens - tokens)

    def wait_for_slot(self, batch_tokens: int) -> None:
        token_cost = max(0, int(batch_tokens))
        while True:
            now = time.monotonic()
            wait_for_interval = 0.0
            wait_for_tokens = 0.0

            if self._min_interval_s > 0 and self._last_request_at > 0:
                elapsed = now - self._last_request_at
                if elapsed < self._min_interval_s:
                    wait_for_interval = self._min_interval_s - elapsed

            if self._tokens_per_minute > 0 and token_cost > 0:
                self._prune(now)
                if (
                    self._recent_requests
                    and self._recent_tokens + token_cost > self._tokens_per_minute
                ):
                    oldest_ts, _ = self._recent_requests[0]
                    wait_for_tokens = max(0.0, 60.0 - (now - oldest_ts))

            wait_s = max(wait_for_interval, wait_for_tokens)
            if wait_s <= 0:
                return
            time.sleep(wait_s)

    def record(self, batch_tokens: int) -> None:
        now = time.monotonic()
        self._last_request_at = now
        token_cost = max(0, int(batch_tokens))
        if self._tokens_per_minute <= 0 or token_cost <= 0:
            return
        self._prune(now)
        self._recent_requests.append((now, token_cost))
        self._recent_tokens += token_cost


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
    on_file_indexed: Callable[
        [str, int, int, dict[str, int], dict[str, int]], None
    ]
    | None = None,
    on_file_progress: Callable[[str, int, int, str], None] | None = None,
    on_file_embedding_progress: Callable[[str, int, int], None] | None = None,
    on_file_result: Callable[[str, bool, str | None, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> tuple[int, int, dict[str, int], dict[str, int]]:
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []
    batch_rel_paths: list[str] = []
    batch_token_total = 0
    file_embed_state: dict[str, dict[str, int]] = {}
    embed_parallel_requests = max(1, int(getattr(config, "embed_parallel_requests", 1)))
    token_counter = TokenCounter(get_embedding_model(config))
    max_request_tokens = int(config.embed_max_tokens_per_request * 0.95)
    max_input_tokens = config.embed_max_tokens_per_input
    target_tokens_per_minute = max(0, int(config.embed_target_tokens_per_minute))
    min_request_interval_s = max(0.0, float(config.embed_min_request_interval_s))
    max_retry_attempts = max(0, int(config.embed_rate_limit_max_retries))
    if max_request_tokens <= 0:
        max_request_tokens = config.embed_max_tokens_per_request
    if target_tokens_per_minute > 0:
        max_request_tokens = min(max_request_tokens, target_tokens_per_minute)
    if max_request_tokens <= 0:
        max_request_tokens = max(1, config.embed_max_tokens_per_input)
    if max_input_tokens > max_request_tokens:
        max_input_tokens = max_request_tokens
    max_batch_items = max(1, int(config.embed_max_batch_items))
    rate_limiter = _EmbedBatchRateLimiter(
        min_interval_s=min_request_interval_s,
        tokens_per_minute=target_tokens_per_minute,
    )
    embed_executor = (
        ThreadPoolExecutor(max_workers=embed_parallel_requests)
        if embed_parallel_requests > 1
        else None
    )
    embed_thread_local = threading.local()
    in_flight_batches: dict[Future[None], tuple[dict[str, int], int, int]] = {}

    total_files = 0
    total_chunks = 0
    skipped_files = 0
    files_by_type: dict[str, int] = {}
    chunks_by_type: dict[str, int] = {}
    parser_registry = build_parser_registry()
    chunker_registry = build_chunker_registry()
    parser_sig = parser_signature(config, PARSER_VERSION)
    chunker_sig = chunker_signature(config, CHUNKER_VERSION)
    path_total = len(paths)
    log_event(
        "rag_index_embed_concurrency",
        embed_parallel_requests=embed_parallel_requests,
        message=(
            "Embedding batches configured with "
            f"{embed_parallel_requests} concurrent request worker(s)"
        ),
    )

    def emit_file_progress(rel_path: str, file_position: int, stage: str) -> None:
        if not on_file_progress:
            return
        on_file_progress(rel_path, file_position, path_total, stage)

    def _collection_for_embed_worker():
        cached = getattr(embed_thread_local, "collection", None)
        if cached is not None:
            return cached
        client = chromadb.HttpClient(host=config.chroma_host, port=config.chroma_port)
        worker_collection = get_collection(client, config, reset=False)
        embed_thread_local.collection = worker_collection
        return worker_collection

    def _apply_embedding_progress(embedded_by_path: dict[str, int]) -> None:
        if not on_file_embedding_progress:
            return
        for rel_path, embedded_count in embedded_by_path.items():
            state = file_embed_state.get(rel_path)
            if not state:
                continue
            state["embedded"] += embedded_count
            state["pending"] = max(0, state["pending"] - embedded_count)
            on_file_embedding_progress(
                rel_path,
                state["embedded"],
                state["total"],
            )
            if state["pending"] <= 0 and state["embedded"] >= state["total"]:
                file_embed_state.pop(rel_path, None)

    def _upsert_batch_with_retry(
        *,
        batch_ids: list[str],
        batch_documents: list[str],
        batch_metadatas: list[dict],
        batch_tokens: int,
        batch_items: int,
    ) -> None:
        attempt = 0
        while True:
            try:
                target_collection = collection
                if embed_executor is not None:
                    target_collection = _collection_for_embed_worker()
                _add_batch(
                    target_collection,
                    batch_ids,
                    batch_documents,
                    batch_metadatas,
                )
                return
            except Exception as exc:
                if not _is_rate_limit_error(exc) or attempt >= max_retry_attempts:
                    raise
                backoff_s = _retry_backoff_seconds(attempt)
                log_event(
                    "rag_index_embed_rate_limit_retry",
                    attempt=attempt + 1,
                    backoff_s=round(backoff_s, 3),
                    batch_items=batch_items,
                    batch_tokens=batch_tokens,
                    error=str(exc),
                )
                time.sleep(backoff_s)
                attempt += 1

    def _drain_in_flight(*, wait_all: bool) -> None:
        while in_flight_batches:
            done, _ = wait(set(in_flight_batches), return_when=FIRST_COMPLETED)
            for future in done:
                embedded_by_path, batch_items, batch_tokens = in_flight_batches.pop(future)
                future.result()
                log_event(
                    "rag_index_embed_batch_complete",
                    batch_items=batch_items,
                    batch_tokens=batch_tokens,
                    in_flight=len(in_flight_batches),
                )
                _apply_embedding_progress(embedded_by_path)
            if not wait_all:
                break

    def flush_batch() -> None:
        nonlocal batch_token_total
        if not ids:
            return
        batch_ids = ids.copy()
        batch_documents = documents.copy()
        batch_metadatas = metadatas.copy()
        batch_tokens = batch_token_total
        batch_items = len(batch_ids)
        embedded_by_path: dict[str, int] = {}
        for rel_path in batch_rel_paths:
            embedded_by_path[rel_path] = embedded_by_path.get(rel_path, 0) + 1
        ids.clear()
        documents.clear()
        metadatas.clear()
        batch_rel_paths.clear()
        batch_token_total = 0

        if embed_executor is not None:
            while len(in_flight_batches) >= embed_parallel_requests:
                _drain_in_flight(wait_all=False)
            rate_limiter.wait_for_slot(batch_tokens)
            rate_limiter.record(batch_tokens)
            future = submit_with_log_context(
                embed_executor,
                _upsert_batch_with_retry,
                batch_ids=batch_ids,
                batch_documents=batch_documents,
                batch_metadatas=batch_metadatas,
                batch_tokens=batch_tokens,
                batch_items=batch_items,
            )
            in_flight_batches[future] = (embedded_by_path, batch_items, batch_tokens)
            log_event(
                "rag_index_embed_batch_submitted",
                batch_items=batch_items,
                batch_tokens=batch_tokens,
                in_flight=len(in_flight_batches),
                parallel_limit=embed_parallel_requests,
            )
            return

        rate_limiter.wait_for_slot(batch_tokens)
        rate_limiter.record(batch_tokens)
        _upsert_batch_with_retry(
            batch_ids=batch_ids,
            batch_documents=batch_documents,
            batch_metadatas=batch_metadatas,
            batch_tokens=batch_tokens,
            batch_items=batch_items,
        )
        _apply_embedding_progress(embedded_by_path)

    for file_position, path in enumerate(paths, start=1):
        if should_stop and should_stop():
            break
        rel_path = _relative_path(path, config) or path.as_posix()
        emit_file_progress(rel_path, file_position, "start")
        if _is_excluded(path, config):
            log_event(
                "rag_index_skip",
                path=str(path),
                reason="excluded",
            )
            emit_file_progress(rel_path, file_position, "skipped")
            if on_file_result:
                on_file_result(rel_path, False, None, 0)
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
            emit_file_progress(rel_path, file_position, "skipped")
            if on_file_result:
                on_file_result(rel_path, False, None, 0)
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
            emit_file_progress(rel_path, file_position, "skipped")
            if on_file_result:
                on_file_result(rel_path, False, None, 0)
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
            emit_file_progress(rel_path, file_position, "skipped")
            if on_file_result:
                on_file_result(rel_path, False, None, 0)
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
            emit_file_progress(rel_path, file_position, "skipped")
            if on_file_result:
                on_file_result(rel_path, False, None, 0)
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
        file_records: list[tuple[str, str, dict[str, object], int]] = []

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

                metadata = dict(base_metadata)
                metadata["chunk_index"] = chunk_counter
                if len(parts) > 1:
                    metadata["split_index"] = part_index
                    metadata["split_count"] = len(parts)

                doc_id = make_chunk_id(Path(rel_path), str(source), page, chunk_counter)
                file_records.append((doc_id, part_text, metadata, token_count))
                chunk_counter += 1
                total_chunks += 1
                chunks_by_type[parsed.doc_type] = chunks_by_type.get(parsed.doc_type, 0) + 1

        if on_file_embedding_progress:
            on_file_embedding_progress(rel_path, 0, len(file_records))

        if file_records:
            file_embed_state[rel_path] = {
                "embedded": 0,
                "total": len(file_records),
                "pending": 0,
            }

        for doc_id, part_text, metadata, token_count in file_records:
            if batch_token_total + token_count > max_request_tokens and ids:
                flush_batch()
            if token_count > max_request_tokens:
                flush_batch()
            ids.append(doc_id)
            documents.append(part_text)
            metadatas.append(metadata)
            batch_rel_paths.append(rel_path)
            batch_token_total += token_count
            state = file_embed_state.get(rel_path)
            if state:
                state["pending"] += 1
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
        emit_file_progress(rel_path, file_position, "complete")
        if on_file_result:
            on_file_result(rel_path, True, parsed.doc_type, chunk_counter)
        if on_file_indexed:
            on_file_indexed(
                rel_path,
                total_files,
                total_chunks,
                dict(files_by_type),
                dict(chunks_by_type),
            )

    try:
        flush_batch()
        _drain_in_flight(wait_all=True)
    finally:
        if embed_executor is not None:
            embed_executor.shutdown(wait=True, cancel_futures=False)
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
    config: RagConfig,
    reset: bool,
    source_meta: dict[str, object] | None = None,
    paths: list[Path] | None = None,
    on_file_indexed: Callable[
        [str, int, int, dict[str, int], dict[str, int]], None
    ]
    | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> tuple[int, int, dict[str, int], dict[str, int]]:
    if chromadb is None:
        raise RuntimeError("chromadb package is required for indexing.")
    client = chromadb.HttpClient(host=config.chroma_host, port=config.chroma_port)
    collection = get_collection(client, config, reset=reset)
    files = paths if paths is not None else list(_iter_files(config))
    total_files, total_chunks, files_by_type, chunks_by_type = index_paths(
        collection,
        config,
        files,
        source_meta=source_meta,
        on_file_indexed=on_file_indexed,
        should_stop=should_stop,
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
        from services.integrations import load_integration_settings

        sources = list_sources()
        if sources:
            github_settings = load_integration_settings("github")
            drive_settings = load_integration_settings("google_workspace")
            service_account_json = drive_settings.get("service_account_json") or ""
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
                elif source.kind == "google_drive":
                    local_dir = (getattr(source, "local_path", "") or "").strip()
                    folder_id = (getattr(source, "drive_folder_id", "") or "").strip()
                    if not local_dir:
                        raise RuntimeError("Google Drive source is missing local sync path.")
                    if not folder_id:
                        raise RuntimeError("Google Drive source is missing folder ID.")
                    sync_folder(
                        service_account_json,
                        folder_id,
                        Path(local_dir),
                        max_workers=max(1, int(source_config.drive_sync_workers)),
                    )
                ingest(source_config, reset=args.reset, source_meta=source_meta)
        else:
            ingest(config, reset=args.reset)
    except Exception as exc:
        print(f"Ingest failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
