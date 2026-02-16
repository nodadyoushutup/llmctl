from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
import hashlib
import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

try:
    import chromadb
except ImportError:  # pragma: no cover
    chromadb = None

try:
    from celery.utils.log import get_task_logger
except ModuleNotFoundError:  # pragma: no cover
    def get_task_logger(name: str):
        return logging.getLogger(name)

try:
    from services.celery_app import celery_app
except ModuleNotFoundError:  # pragma: no cover
    class _NoopControl:
        def revoke(self, *args, **kwargs) -> None:
            return None

    class _NoopCeleryApp:
        control = _NoopControl()

        def task(self, *args, **kwargs):
            def _decorator(fn):
                fn.run = fn
                fn.apply_async = lambda *a, **k: SimpleNamespace(id=None)
                return fn

            return _decorator

    celery_app = _NoopCeleryApp()
from rag.engine.config import build_source_config, load_config
from rag.integrations.git_sync import ensure_git_repo, git_fetch_and_reset
from rag.integrations.google_drive_sync import DriveSyncStats, count_syncable_files, sync_folder
from rag.engine.ingest import _iter_files, get_collection, index_paths
from rag.engine.logging_utils import log_sink, submit_with_log_context
from rag.repositories.source_file_states import (
    SourceFileStateInput,
    delete_source_file_states,
    list_source_file_states,
    summarize_source_file_states,
    upsert_source_file_states,
)
from services.integrations import load_integration_settings
from rag.repositories.sources import get_source, schedule_source_next_index, update_source_index
from core.config import Config
from core.db import init_db, init_engine
from core.models import (
    RAG_INDEX_JOB_ACTIVE_STATUSES,
    RAG_INDEX_JOB_KIND_INDEX,
    RAG_INDEX_JOB_STATUS_CANCELLED,
    RAG_INDEX_JOB_STATUS_FAILED,
    RAG_INDEX_JOB_STATUS_PAUSED,
    RAG_INDEX_JOB_STATUS_PAUSING,
    RAG_INDEX_JOB_STATUS_QUEUED,
    RAG_INDEX_JOB_STATUS_SUCCEEDED,
    RAG_INDEX_TRIGGER_MANUAL,
    RAG_INDEX_TRIGGER_SCHEDULED,
)
from rag.repositories.index_jobs import (
    active_index_job,
    append_index_job_output,
    cancel_index_job,
    create_index_job,
    get_index_job,
    has_active_index_job,
    index_job_meta,
    latest_index_job,
    list_active_index_jobs,
    mark_index_job_finished,
    mark_index_job_running,
    pause_index_job,
    resume_index_job,
    set_index_job_celery_id,
    set_index_job_meta,
)
from rag.worker.queues import queue_for_source_kind


logger = get_task_logger(__name__)


class _TaskCancelledError(Exception):
    pass


class _TaskPausedError(Exception):
    pass


INDEX_MODE_FRESH = "fresh"
INDEX_MODE_DELTA = "delta"
_INDEX_MODE_VALUES = {INDEX_MODE_FRESH, INDEX_MODE_DELTA}

TASK_KIND_INDEX = RAG_INDEX_JOB_KIND_INDEX
TASK_STATUS_QUEUED = RAG_INDEX_JOB_STATUS_QUEUED
TASK_STATUS_CANCELLED = RAG_INDEX_JOB_STATUS_CANCELLED
TASK_STATUS_FAILED = RAG_INDEX_JOB_STATUS_FAILED
TASK_STATUS_PAUSED = RAG_INDEX_JOB_STATUS_PAUSED
TASK_STATUS_PAUSING = RAG_INDEX_JOB_STATUS_PAUSING
TASK_STATUS_SUCCEEDED = RAG_INDEX_JOB_STATUS_SUCCEEDED
TASK_ACTIVE_STATUSES = set(RAG_INDEX_JOB_ACTIVE_STATUSES)


def get_task(task_id: int):
    return get_index_job(task_id)


def task_meta(task) -> dict[str, Any]:
    return index_job_meta(task)


def set_task_meta(task_id: int, meta: dict[str, Any]):
    return set_index_job_meta(task_id, meta)


def append_task_output(task_id: int, message: str):
    return append_index_job_output(task_id, message)


def mark_task_running(task_id: int, *, celery_task_id: str | None = None):
    return mark_index_job_running(task_id, celery_task_id=celery_task_id)


def mark_task_finished(
    task_id: int,
    *,
    status: str,
    output: str | None = None,
    error: str | None = None,
):
    return mark_index_job_finished(task_id, status=status, output=output, error=error)


def mark_task_paused(
    task_id: int,
    *,
    message: str = "Task paused. Resume to continue indexing from checkpoint.",
):
    return mark_index_job_finished(
        task_id,
        status=TASK_STATUS_PAUSED,
        error=None,
        progress_message=message,
    )


def list_active_tasks(
    kind: str | None = None,
    source_id: int | None = None,
):
    if kind and kind != TASK_KIND_INDEX:
        return []
    return list_active_index_jobs(source_id=source_id)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_index_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    if mode in _INDEX_MODE_VALUES:
        return mode
    return INDEX_MODE_FRESH


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_int_list(values: Any) -> list[int]:
    if not isinstance(values, list):
        return []
    result: list[int] = []
    seen: set[int] = set()
    for value in values:
        parsed = _as_int(value, default=-1)
        if parsed < 0 or parsed in seen:
            continue
        seen.add(parsed)
        result.append(parsed)
    return result


def _as_int_map(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, count in value.items():
        if not key:
            continue
        parsed = _as_int(count)
        if parsed <= 0:
            continue
        result[str(key)] = parsed
    return result


def _task_output_sink(task_id: int):
    lock = threading.Lock()

    def _sink(message: str) -> None:
        if not message:
            return
        for attempt in range(3):
            with lock:
                task = append_task_output(task_id, message)
            if task is not None:
                return
            if attempt < 2:
                time.sleep(0.01 * (2**attempt))

    return _sink


def _merge_counts(target: dict[str, int], incoming: dict[str, int]) -> None:
    for key, value in incoming.items():
        target[key] = target.get(key, 0) + int(value or 0)


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _ensure_task_continuing(task_id: int) -> None:
    current = get_task(task_id)
    if current and current.status == TASK_STATUS_CANCELLED:
        raise _TaskCancelledError("Task cancelled by user.")
    if current and current.status == TASK_STATUS_PAUSING:
        raise _TaskPausedError("Task pause requested by user.")


def _should_stop(task_id: int) -> bool:
    current = get_task(task_id)
    if not current:
        return False
    return current.status in {TASK_STATUS_CANCELLED, TASK_STATUS_PAUSING}


def _persist_progress(
    task_id: int,
    meta: dict[str, Any],
    completed_source_ids: list[int],
    source_checkpoints: dict[str, dict[str, Any]],
    reset_applied_source_ids: list[int],
    progress_fields: dict[str, Any] | None = None,
) -> None:
    progress = meta.get("progress")
    if not isinstance(progress, dict):
        progress = {}
    progress["completed_source_ids"] = completed_source_ids
    progress["source_checkpoints"] = source_checkpoints
    progress["reset_applied_source_ids"] = reset_applied_source_ids
    if progress_fields:
        for key, value in progress_fields.items():
            progress[key] = value
    meta["progress"] = progress
    set_task_meta(task_id, meta)


def _finalize_source_success(
    *,
    source_id: int,
    source_checkpoints: dict[str, dict[str, Any]],
    completed_source_ids: list[int],
) -> None:
    source_checkpoints.pop(str(source_id), None)
    if source_id not in completed_source_ids:
        completed_source_ids.append(source_id)


def _path_fingerprint(path: Path) -> str:
    hasher = hashlib.sha1()
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                hasher.update(chunk)
    except OSError:
        try:
            stat = path.stat()
        except OSError:
            return ""
        return f"stat:{int(stat.st_size)}:{int(getattr(stat, 'st_mtime_ns', stat.st_mtime))}"
    return f"sha1:{hasher.hexdigest()}"


@dataclass(frozen=True)
class _IndexedPathOutcome:
    rel_path: str
    indexed: bool
    doc_type: str | None
    chunk_count: int
    file_total: int
    chunk_total: int
    files_by_type: dict[str, int]
    chunks_by_type: dict[str, int]


def _index_paths_parallel(
    *,
    source_config: Any,
    source_meta: dict[str, Any],
    paths: list[Path],
    delete_first: bool,
    max_workers: int,
    should_stop: Callable[[], bool] | None = None,
    on_file_done: Callable[[_IndexedPathOutcome, int, int], None] | None = None,
) -> tuple[int, int, dict[str, int], dict[str, int], dict[str, tuple[bool, str | None, int]]]:
    if not paths:
        return 0, 0, {}, {}, {}

    worker_count = min(max(1, int(max_workers)), len(paths))
    if worker_count <= 1:
        raise ValueError("_index_paths_parallel requires max_workers > 1.")

    repo_root = Path(source_config.repo_root)
    local_state = threading.local()

    def _collection_for_worker():
        cached = getattr(local_state, "collection", None)
        if cached is not None:
            return cached
        client = chromadb.HttpClient(
            host=source_config.chroma_host,
            port=source_config.chroma_port,
        )
        collection = get_collection(client, source_config, reset=False)
        local_state.collection = collection
        return collection

    def _run_single(path: Path, rel_path: str) -> _IndexedPathOutcome:
        indexed = False
        doc_type: str | None = None
        chunk_count = 0
        seen_result = False

        def _on_file_result(
            callback_rel_path: str,
            callback_indexed: bool,
            callback_doc_type: str | None,
            callback_chunk_count: int,
        ) -> None:
            nonlocal indexed, doc_type, chunk_count, seen_result
            if callback_rel_path != rel_path:
                return
            indexed = bool(callback_indexed)
            doc_type = callback_doc_type
            chunk_count = int(callback_chunk_count or 0)
            seen_result = True

        collection = _collection_for_worker()
        file_total, chunk_total, files_by_type, chunks_by_type = index_paths(
            collection,
            source_config,
            [path],
            delete_first=delete_first,
            source_meta=source_meta,
            on_file_result=_on_file_result,
            should_stop=should_stop,
        )
        if not seen_result:
            indexed = file_total > 0
            if indexed and files_by_type:
                doc_type = next(iter(files_by_type))
                chunk_count = int(chunk_total or 0)
            else:
                doc_type = None
                chunk_count = 0
        return _IndexedPathOutcome(
            rel_path=rel_path,
            indexed=indexed,
            doc_type=doc_type,
            chunk_count=chunk_count,
            file_total=file_total,
            chunk_total=chunk_total,
            files_by_type=dict(files_by_type),
            chunks_by_type=dict(chunks_by_type),
        )

    total_files = 0
    total_chunks = 0
    files_by_type: dict[str, int] = {}
    chunks_by_type: dict[str, int] = {}
    indexed_results: dict[str, tuple[bool, str | None, int]] = {}
    parallel_workers = max(
        1,
        int(getattr(source_config, "index_parallel_workers", 1)),
    )
    completed = 0
    total = len(paths)
    path_iter = iter(paths)
    in_flight: dict[Any, str] = {}

    def _submit_next(executor: ThreadPoolExecutor) -> bool:
        if should_stop and should_stop():
            return False
        try:
            path = next(path_iter)
        except StopIteration:
            return False
        rel_path = _relative_path(path, repo_root)
        future = submit_with_log_context(executor, _run_single, path, rel_path)
        in_flight[future] = rel_path
        return True

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        for _ in range(worker_count):
            if not _submit_next(executor):
                break

        while in_flight:
            done, _ = wait(set(in_flight), return_when=FIRST_COMPLETED)
            for future in done:
                rel_path = in_flight.pop(future)
                try:
                    outcome = future.result()
                except Exception:
                    for pending in in_flight:
                        pending.cancel()
                    raise
                completed += 1
                total_files += int(outcome.file_total or 0)
                total_chunks += int(outcome.chunk_total or 0)
                _merge_counts(files_by_type, outcome.files_by_type)
                _merge_counts(chunks_by_type, outcome.chunks_by_type)
                indexed_results[outcome.rel_path] = (
                    bool(outcome.indexed),
                    outcome.doc_type,
                    int(outcome.chunk_count or 0),
                )
                if on_file_done:
                    on_file_done(outcome, completed, total)
                if not (should_stop and should_stop()):
                    _submit_next(executor)

    return total_files, total_chunks, files_by_type, chunks_by_type, indexed_results


def _run_source_delta_index(
    *,
    task_id: int,
    source: Any,
    source_config: Any,
    source_meta: dict[str, Any],
    checkpoint: dict[str, Any],
    should_reset: bool,
    service_account_json: str,
    meta: dict[str, Any],
    completed_source_ids: list[int],
    source_checkpoints: dict[str, dict[str, Any]],
    reset_applied_source_ids: list[int],
) -> tuple[int, int, dict[str, int]]:
    if source.kind == "google_drive":
        local_dir = (getattr(source, "local_path", "") or "").strip()
        folder_id = (getattr(source, "drive_folder_id", "") or "").strip()
        if not local_dir:
            raise RuntimeError("Google Drive source is missing local sync path.")
        if not folder_id:
            raise RuntimeError("Google Drive source is missing folder ID.")

        append_task_output(task_id, f"Syncing {source.name} from Google Drive...")
        drive_total_files: int | None = None
        try:
            drive_total_files = count_syncable_files(service_account_json, folder_id)
        except Exception as exc:
            append_task_output(
                task_id,
                f"{source.name}: unable to pre-count Google Drive files ({exc}).",
            )

        drive_seen = 0
        _persist_progress(
            task_id,
            meta,
            completed_source_ids,
            source_checkpoints,
            reset_applied_source_ids,
            progress_fields={
                "phase": "syncing",
                "file_index": None,
                "files_total": None,
                "files_completed": None,
                "current_file_path": None,
                "current_file_chunks_embedded": None,
                "current_file_chunks_total": None,
                "drive_files_seen": 0,
                "drive_files_total": drive_total_files,
            },
        )

        def _on_drive_file_downloaded(_path: Path, _stats: DriveSyncStats) -> None:
            nonlocal drive_seen
            drive_seen += 1
            _persist_progress(
                task_id,
                meta,
                completed_source_ids,
                source_checkpoints,
                reset_applied_source_ids,
                progress_fields={
                    "phase": "syncing",
                    "drive_files_seen": drive_seen,
                    "drive_files_total": drive_total_files,
                },
            )
            if _should_stop(task_id):
                _ensure_task_continuing(task_id)

        stats = sync_folder(
            service_account_json,
            folder_id,
            Path(local_dir),
            on_file_downloaded=_on_drive_file_downloaded,
            max_workers=max(1, int(source_config.drive_sync_workers)),
        )
        _ensure_task_continuing(task_id)
        append_task_output(
            task_id,
            (
                f"{source.name}: downloaded {stats.files_downloaded} files "
                f"from {stats.folders_synced} folders "
                f"(skipped {stats.files_skipped})."
            ),
        )

    repo_root = Path(source_config.repo_root)
    all_paths = list(_iter_files(source_config))
    total_discovered = len(all_paths)
    scanned: list[tuple[Path, str, str]] = []
    current_fingerprint_by_path: dict[str, str] = {}
    for file_index, path in enumerate(all_paths, start=1):
        _ensure_task_continuing(task_id)
        rel_path = _relative_path(path, repo_root)
        fingerprint = _path_fingerprint(path)
        if not rel_path or not fingerprint:
            continue
        scanned.append((path, rel_path, fingerprint))
        current_fingerprint_by_path[rel_path] = fingerprint
        _persist_progress(
            task_id,
            meta,
            completed_source_ids,
            source_checkpoints,
            reset_applied_source_ids,
            progress_fields={
                "phase": "preparing",
                "file_index": file_index,
                "files_total": total_discovered,
                "files_completed": max(0, file_index - 1),
                "current_file_path": rel_path,
                "current_file_chunks_embedded": None,
                "current_file_chunks_total": None,
            },
        )

    existing_states = {state.path: state for state in list_source_file_states(source.id)}
    effective_reset = bool(should_reset)
    if (
        not effective_reset
        and not existing_states
        and _as_int(getattr(source, "indexed_file_count", None)) > 0
    ):
        effective_reset = True
        append_task_output(
            task_id,
            (
                f"{source.name}: no prior delta state found; rebuilding baseline from "
                "scratch this run."
            ),
        )

    client = chromadb.HttpClient(host=source_config.chroma_host, port=source_config.chroma_port)
    collection = get_collection(client, source_config, reset=effective_reset)
    if effective_reset and source.id not in reset_applied_source_ids:
        reset_applied_source_ids.append(source.id)
        _persist_progress(
            task_id,
            meta,
            completed_source_ids,
            source_checkpoints,
            reset_applied_source_ids,
        )
        delete_source_file_states(source.id)
        existing_states = {}

    changed_entries: list[tuple[Path, str]] = []
    for path, rel_path, fingerprint in scanned:
        existing = existing_states.get(rel_path)
        if effective_reset or not existing or str(existing.fingerprint or "") != fingerprint:
            changed_entries.append((path, rel_path))

    removed_paths = []
    if not effective_reset:
        removed_paths = sorted(
            [path for path in existing_states if path not in current_fingerprint_by_path]
        )

    if removed_paths:
        removed = 0
        for rel_path in removed_paths:
            try:
                collection.delete(where={"path": rel_path})
                removed += 1
            except Exception:
                continue
        delete_source_file_states(source.id, paths=removed_paths)
        append_task_output(
            task_id,
            f"{source.name}: removed {removed} stale file paths from collection.",
        )

    resume_path = str(checkpoint.get("last_indexed_path") or "").strip()
    processed_base = _as_int(checkpoint.get("delta_files_processed"))
    if resume_path:
        resume_index = -1
        for idx, (_, rel_path) in enumerate(changed_entries):
            if rel_path == resume_path:
                resume_index = idx
                break
        if resume_index >= 0:
            changed_entries = changed_entries[resume_index + 1 :]
            append_task_output(task_id, f"{source.name}: delta resume after {resume_path}.")
        else:
            processed_base = 0

    changed_count = len(changed_entries)
    append_task_output(
        task_id,
        (
            f"{source.name}: delta plan has {changed_count} changed/new files "
            f"and {len(removed_paths)} removed files."
        ),
    )

    files_total_for_source = processed_base + changed_count
    _persist_progress(
        task_id,
        meta,
        completed_source_ids,
        source_checkpoints,
        reset_applied_source_ids,
        progress_fields={
            "phase": "indexing",
            "file_index": None,
            "files_total": files_total_for_source,
            "files_completed": processed_base,
            "current_file_path": None,
            "current_file_chunks_embedded": None,
            "current_file_chunks_total": None,
            "drive_files_seen": None,
            "drive_files_total": None,
        },
    )

    indexed_results: dict[str, tuple[bool, str | None, int]] = {}

    def _on_file_progress(
        rel_path: str,
        file_position: int,
        file_count: int,
        stage: str,
    ) -> None:
        absolute_file_index = processed_base + file_position
        completed_files = (
            max(0, absolute_file_index - 1) if stage == "start" else absolute_file_index
        )
        progress_fields: dict[str, Any] = {
            "phase": "indexing",
            "file_index": absolute_file_index,
            "files_total": processed_base + file_count,
            "files_completed": completed_files,
            "current_file_path": rel_path,
        }
        if stage == "start":
            progress_fields["current_file_chunks_embedded"] = 0
            progress_fields["current_file_chunks_total"] = None
        elif stage == "skipped":
            progress_fields["current_file_chunks_embedded"] = None
            progress_fields["current_file_chunks_total"] = 0
        if stage in {"complete", "skipped"}:
            source_checkpoints[str(source.id)] = {
                "index_mode": INDEX_MODE_DELTA,
                "last_indexed_path": rel_path,
                "delta_files_processed": absolute_file_index,
            }
        _persist_progress(
            task_id,
            meta,
            completed_source_ids,
            source_checkpoints,
            reset_applied_source_ids,
            progress_fields=progress_fields,
        )

    def _on_file_embedding_progress(
        rel_path: str,
        embedded_chunks: int,
        total_chunks: int,
    ) -> None:
        _persist_progress(
            task_id,
            meta,
            completed_source_ids,
            source_checkpoints,
            reset_applied_source_ids,
            progress_fields={
                "phase": "indexing",
                "current_file_path": rel_path,
                "current_file_chunks_embedded": embedded_chunks,
                "current_file_chunks_total": total_chunks,
            },
        )

    def _on_file_result(
        rel_path: str,
        indexed: bool,
        doc_type: str | None,
        chunk_count: int,
    ) -> None:
        indexed_results[rel_path] = (indexed, doc_type, int(chunk_count or 0))

    def _on_parallel_file_done(
        outcome: _IndexedPathOutcome,
        completed_count: int,
        total_count: int,
    ) -> None:
        absolute_file_index = processed_base + completed_count
        source_checkpoints[str(source.id)] = {
            "index_mode": INDEX_MODE_DELTA,
            "last_indexed_path": outcome.rel_path,
            "delta_files_processed": absolute_file_index,
        }
        _persist_progress(
            task_id,
            meta,
            completed_source_ids,
            source_checkpoints,
            reset_applied_source_ids,
            progress_fields={
                "phase": "indexing",
                "file_index": absolute_file_index,
                "files_total": processed_base + total_count,
                "files_completed": absolute_file_index,
                "current_file_path": outcome.rel_path,
                "current_file_chunks_embedded": (
                    outcome.chunk_count if outcome.indexed else None
                ),
                "current_file_chunks_total": (
                    outcome.chunk_count if outcome.indexed else 0
                ),
            },
        )

    if changed_entries:
        changed_paths = [item[0] for item in changed_entries]
        if parallel_workers > 1 and len(changed_paths) > 1:
            (
                _,
                _,
                _,
                _,
                parallel_results,
            ) = _index_paths_parallel(
                source_config=source_config,
                source_meta=source_meta,
                paths=changed_paths,
                delete_first=True,
                max_workers=parallel_workers,
                should_stop=lambda: _should_stop(task_id),
                on_file_done=_on_parallel_file_done,
            )
            indexed_results.update(parallel_results)
        else:
            index_paths(
                collection,
                source_config,
                changed_paths,
                delete_first=True,
                source_meta=source_meta,
                on_file_progress=_on_file_progress,
                on_file_embedding_progress=_on_file_embedding_progress,
                on_file_result=_on_file_result,
                should_stop=lambda: _should_stop(task_id),
            )

    if indexed_results:
        state_updates: list[SourceFileStateInput] = []
        for rel_path, (indexed, doc_type, chunk_count) in indexed_results.items():
            fingerprint = current_fingerprint_by_path.get(rel_path)
            if not fingerprint:
                continue
            state_updates.append(
                SourceFileStateInput(
                    path=rel_path,
                    fingerprint=fingerprint,
                    indexed=indexed,
                    doc_type=doc_type if indexed else None,
                    chunk_count=chunk_count if indexed else 0,
                )
            )
        upsert_source_file_states(source.id, state_updates)

    _ensure_task_continuing(task_id)

    stats = summarize_source_file_states(source.id)
    _persist_progress(
        task_id,
        meta,
        completed_source_ids,
        source_checkpoints,
        reset_applied_source_ids,
        progress_fields={
            "phase": "indexing",
            "files_total": files_total_for_source,
            "files_completed": processed_base + len(indexed_results),
            "current_file_chunks_embedded": None,
            "current_file_chunks_total": None,
        },
    )
    return (
        stats.indexed_file_count,
        stats.indexed_chunk_count,
        stats.indexed_file_types,
    )


@celery_app.task(bind=True, name="rag.worker.tasks.run_index_task")
def run_index_task(
    self,
    task_id: int,
    source_id: int | None,
    reset: bool,
    index_mode: str = INDEX_MODE_FRESH,
) -> None:
    init_engine(Config.SQLALCHEMY_DATABASE_URI)
    init_db()
    if source_id is None:
        mark_task_finished(
            task_id,
            status=TASK_STATUS_FAILED,
            error="Stage 6 enforces per-source indexing jobs only.",
            output="Stage 6 enforces per-source indexing jobs only.",
        )
        return

    initial = get_task(task_id)
    if initial and initial.status in {TASK_STATUS_CANCELLED, TASK_STATUS_PAUSED}:
        return

    mark_task_running(task_id, celery_task_id=self.request.id)
    append_task_output(task_id, "Index task started.")

    if source_id is not None:
        active_for_source = list_active_tasks(kind=TASK_KIND_INDEX, source_id=source_id)
        if len(active_for_source) > 1:
            keeper = active_for_source[-1]
            if keeper.id != task_id:
                message = (
                    "Duplicate source index task detected; skipping this run to avoid "
                    "double indexing work."
                )
                append_task_output(task_id, message)
                mark_task_finished(
                    task_id,
                    status=TASK_STATUS_CANCELLED,
                    output=message,
                    error=message,
                )
                return

    output_lines: list[str] = []
    error: str | None = None

    try:
        with log_sink(_task_output_sink(task_id)):
            if chromadb is None:
                raise RuntimeError("chromadb package is required for RAG index jobs.")
            config = load_config()
            append_task_output(
                task_id,
                (
                    "Concurrency profile: "
                    f"file_workers={max(1, int(getattr(config, 'index_parallel_workers', 1)))} "
                    f"page_workers={max(1, int(getattr(config, 'pdf_page_workers', 1)))} "
                    f"embed_workers={max(1, int(getattr(config, 'embed_parallel_requests', 1)))}"
                ),
            )
            github_settings = load_integration_settings("github")
            drive_settings = load_integration_settings("google_workspace")
            service_account_json = drive_settings.get("service_account_json") or ""

            source = get_source(source_id)
            if not source:
                raise RuntimeError("Source not found.")
            source_by_id = {source.id: source}
            ordered_source_ids = [source.id]

            current_task = get_task(task_id)
            meta = task_meta(current_task) if current_task else {}
            task_reset = bool(meta.get("reset", reset))
            task_index_mode = _normalize_index_mode(meta.get("index_mode", index_mode))
            meta["reset"] = task_reset
            meta["index_mode"] = task_index_mode
            meta["source_id"] = source_id
            meta["source_order"] = ordered_source_ids

            progress = meta.get("progress")
            if not isinstance(progress, dict):
                progress = {}
            completed_source_ids = [
                sid
                for sid in _as_int_list(progress.get("completed_source_ids"))
                if sid in source_by_id
            ]

            raw_checkpoints = progress.get("source_checkpoints")
            source_checkpoints: dict[str, dict[str, Any]] = {}
            if isinstance(raw_checkpoints, dict):
                for key, value in raw_checkpoints.items():
                    source_key = str(key)
                    if source_key.isdigit() and isinstance(value, dict):
                        source_checkpoints[source_key] = dict(value)

            reset_applied_source_ids = [
                sid
                for sid in _as_int_list(progress.get("reset_applied_source_ids"))
                if sid in source_by_id
            ]

            _persist_progress(
                task_id,
                meta,
                completed_source_ids,
                source_checkpoints,
                reset_applied_source_ids,
                progress_fields={
                    "source_total": len(ordered_source_ids),
                },
            )

            errors: list[str] = []

            for source_index, current_source_id in enumerate(ordered_source_ids, start=1):
                source = source_by_id.get(current_source_id)
                if not source:
                    continue
                if current_source_id in completed_source_ids:
                    continue

                append_task_output(task_id, f"Indexing {source.name}...")

                source_config = build_source_config(config, source, github_settings)
                source_meta = {
                    "source_id": source.id,
                    "source_name": source.name,
                    "source_kind": source.kind,
                }

                should_reset = bool(task_reset) and source.id not in reset_applied_source_ids

                try:
                    _ensure_task_continuing(task_id)
                    checkpoint = source_checkpoints.get(str(source.id), {})
                    if task_index_mode == INDEX_MODE_DELTA:
                        base_file_count = _as_int(checkpoint.get("delta_files_processed"))
                        base_chunk_count = 0
                        base_file_types = {}
                        base_chunk_types = {}
                    else:
                        base_file_count = _as_int(checkpoint.get("indexed_file_count"))
                        base_chunk_count = _as_int(checkpoint.get("indexed_chunk_count"))
                        base_file_types = _as_int_map(checkpoint.get("indexed_file_types"))
                        base_chunk_types = _as_int_map(checkpoint.get("indexed_chunk_types"))

                    _persist_progress(
                        task_id,
                        meta,
                        completed_source_ids,
                        source_checkpoints,
                        reset_applied_source_ids,
                        progress_fields={
                            "source_total": len(ordered_source_ids),
                            "source_index": source_index,
                            "source_id": source.id,
                            "source_name": source.name,
                            "source_kind": source.kind,
                            "phase": "preparing",
                            "file_index": None,
                            "files_total": None,
                            "files_completed": base_file_count,
                            "current_file_path": None,
                            "current_file_chunks_embedded": None,
                            "current_file_chunks_total": None,
                            "drive_files_seen": None,
                            "drive_files_total": None,
                        },
                    )

                    if source.kind == "github":
                        append_task_output(task_id, f"Syncing {source.name} from GitHub...")
                        ensure_git_repo(source_config)
                        git_fetch_and_reset(source_config)

                    if task_index_mode == INDEX_MODE_DELTA:
                        total_files, total_chunks, files_by_type = _run_source_delta_index(
                            task_id=task_id,
                            source=source,
                            source_config=source_config,
                            source_meta=source_meta,
                            checkpoint=checkpoint,
                            should_reset=should_reset,
                            service_account_json=service_account_json,
                            meta=meta,
                            completed_source_ids=completed_source_ids,
                            source_checkpoints=source_checkpoints,
                            reset_applied_source_ids=reset_applied_source_ids,
                        )
                    elif source.kind == "google_drive":
                        local_dir = (getattr(source, "local_path", "") or "").strip()
                        folder_id = (getattr(source, "drive_folder_id", "") or "").strip()
                        if not local_dir:
                            raise RuntimeError(
                                "Google Drive source is missing local sync path."
                            )
                        if not folder_id:
                            raise RuntimeError(
                                "Google Drive source is missing folder ID."
                            )

                        append_task_output(
                            task_id, f"Syncing {source.name} from Google Drive..."
                        )
                        client = chromadb.HttpClient(
                            host=source_config.chroma_host, port=source_config.chroma_port
                        )
                        collection = get_collection(
                            client, source_config, reset=should_reset
                        )
                        if should_reset and source.id not in reset_applied_source_ids:
                            reset_applied_source_ids.append(source.id)
                            _persist_progress(
                                task_id,
                                meta,
                                completed_source_ids,
                                source_checkpoints,
                                reset_applied_source_ids,
                            )

                        drive_seen = 0
                        resume_seen = _as_int(checkpoint.get("drive_files_seen"))
                        drive_total_files: int | None = None
                        try:
                            drive_total_files = count_syncable_files(
                                service_account_json,
                                folder_id,
                            )
                        except Exception as exc:
                            append_task_output(
                                task_id,
                                (
                                    f"{source.name}: unable to pre-count Google Drive files "
                                    f"({exc})."
                                ),
                            )
                        files_total_for_source = (
                            base_file_count
                            + max(0, drive_total_files - resume_seen)
                            if drive_total_files is not None
                            else None
                        )
                        indexed_files = base_file_count
                        indexed_chunks = base_chunk_count
                        indexed_files_by_type = dict(base_file_types)
                        indexed_chunks_by_type = dict(base_chunk_types)

                        if resume_seen > 0:
                            append_task_output(
                                task_id,
                                (
                                    f"{source.name}: resume checkpoint at downloaded file "
                                    f"#{resume_seen}."
                                ),
                            )

                        local_root = Path(local_dir)
                        _persist_progress(
                            task_id,
                            meta,
                            completed_source_ids,
                            source_checkpoints,
                            reset_applied_source_ids,
                            progress_fields={
                                "phase": "syncing",
                                "file_index": None,
                                "files_total": files_total_for_source,
                                "files_completed": base_file_count,
                                "current_file_path": None,
                                "current_file_chunks_embedded": None,
                                "current_file_chunks_total": None,
                                "drive_files_seen": resume_seen,
                                "drive_files_total": drive_total_files,
                            },
                        )

                        def _on_drive_file_downloaded(
                            path: Path, stats: DriveSyncStats
                        ) -> None:
                            nonlocal drive_seen
                            drive_seen += 1
                            rel_path = _relative_path(path, local_root)
                            relative_file_index = max(0, drive_seen - resume_seen)
                            absolute_file_index = base_file_count + relative_file_index
                            if drive_seen <= resume_seen:
                                _persist_progress(
                                    task_id,
                                    meta,
                                    completed_source_ids,
                                    source_checkpoints,
                                    reset_applied_source_ids,
                                    progress_fields={
                                        "phase": "syncing",
                                        "files_total": files_total_for_source,
                                        "files_completed": base_file_count,
                                        "drive_files_seen": drive_seen,
                                        "drive_files_total": drive_total_files,
                                    },
                                )
                                if _should_stop(task_id):
                                    _ensure_task_continuing(task_id)
                                return
                            pending_index_paths.append(path)
                            _persist_progress(
                                task_id,
                                meta,
                                completed_source_ids,
                                source_checkpoints,
                                reset_applied_source_ids,
                                progress_fields={
                                    "phase": "indexing",
                                    "file_index": absolute_file_index,
                                    "files_total": files_total_for_source,
                                    "files_completed": max(0, absolute_file_index - 1),
                                    "current_file_path": rel_path,
                                    "current_file_chunks_embedded": 0,
                                    "current_file_chunks_total": None,
                                    "drive_files_seen": drive_seen,
                                    "drive_files_total": drive_total_files,
                                },
                            )

                        pending_index_paths: list[Path] = []
                        parallel_workers = max(
                            1,
                            int(getattr(source_config, "index_parallel_workers", 1)),
                        )

                        stats = sync_folder(
                            service_account_json,
                            folder_id,
                            Path(local_dir),
                            on_file_downloaded=_on_drive_file_downloaded,
                            max_workers=max(1, int(source_config.drive_sync_workers)),
                        )

                        _ensure_task_continuing(task_id)

                        append_task_output(
                            task_id,
                            (
                                f"{source.name}: downloaded {stats.files_downloaded} files "
                                f"from {stats.folders_synced} folders "
                                f"(skipped {stats.files_skipped})."
                            ),
                        )

                        if pending_index_paths:
                            if parallel_workers > 1 and len(pending_index_paths) > 1:

                                def _on_parallel_drive_done(
                                    outcome: _IndexedPathOutcome,
                                    completed_count: int,
                                    total_count: int,
                                ) -> None:
                                    nonlocal indexed_files, indexed_chunks
                                    indexed_files += int(outcome.file_total or 0)
                                    indexed_chunks += int(outcome.chunk_total or 0)
                                    _merge_counts(indexed_files_by_type, outcome.files_by_type)
                                    _merge_counts(indexed_chunks_by_type, outcome.chunks_by_type)
                                    absolute_file_index = base_file_count + completed_count
                                    source_checkpoints[str(source.id)] = {
                                        "last_indexed_path": outcome.rel_path,
                                        "indexed_file_count": indexed_files,
                                        "indexed_chunk_count": indexed_chunks,
                                        "indexed_file_types": dict(indexed_files_by_type),
                                        "indexed_chunk_types": dict(indexed_chunks_by_type),
                                        "drive_files_seen": drive_seen,
                                    }
                                    _persist_progress(
                                        task_id,
                                        meta,
                                        completed_source_ids,
                                        source_checkpoints,
                                        reset_applied_source_ids,
                                        progress_fields={
                                            "phase": "indexing",
                                            "file_index": absolute_file_index,
                                            "files_total": files_total_for_source,
                                            "files_completed": absolute_file_index,
                                            "current_file_path": outcome.rel_path,
                                            "current_file_chunks_embedded": (
                                                outcome.chunk_count if outcome.indexed else None
                                            ),
                                            "current_file_chunks_total": (
                                                outcome.chunk_count if outcome.indexed else 0
                                            ),
                                            "drive_files_seen": drive_seen,
                                            "drive_files_total": drive_total_files,
                                        },
                                    )
                                    update_source_index(
                                        source.id,
                                        last_indexed_at=_utcnow(),
                                        last_error=None,
                                        indexed_file_count=indexed_files,
                                        indexed_chunk_count=indexed_chunks,
                                        indexed_file_types=json.dumps(
                                            indexed_files_by_type, sort_keys=True
                                        ),
                                    )

                                _index_paths_parallel(
                                    source_config=source_config,
                                    source_meta=source_meta,
                                    paths=pending_index_paths,
                                    delete_first=False,
                                    max_workers=parallel_workers,
                                    should_stop=lambda: _should_stop(task_id),
                                    on_file_done=_on_parallel_drive_done,
                                )
                            else:
                                for file_index, path in enumerate(pending_index_paths, start=1):
                                    _ensure_task_continuing(task_id)
                                    rel_path = _relative_path(path, local_root)
                                    absolute_file_index = base_file_count + file_index
                                    _persist_progress(
                                        task_id,
                                        meta,
                                        completed_source_ids,
                                        source_checkpoints,
                                        reset_applied_source_ids,
                                        progress_fields={
                                            "phase": "indexing",
                                            "file_index": absolute_file_index,
                                            "files_total": files_total_for_source,
                                            "files_completed": max(
                                                0, absolute_file_index - 1
                                            ),
                                            "current_file_path": rel_path,
                                            "current_file_chunks_embedded": 0,
                                            "current_file_chunks_total": None,
                                            "drive_files_seen": drive_seen,
                                            "drive_files_total": drive_total_files,
                                        },
                                    )

                                    def _on_file_embedding_progress(
                                        embedding_rel_path: str,
                                        embedded_chunks: int,
                                        total_chunks: int,
                                    ) -> None:
                                        _persist_progress(
                                            task_id,
                                            meta,
                                            completed_source_ids,
                                            source_checkpoints,
                                            reset_applied_source_ids,
                                            progress_fields={
                                                "phase": "indexing",
                                                "file_index": absolute_file_index,
                                                "files_total": files_total_for_source,
                                                "files_completed": max(
                                                    0, absolute_file_index - 1
                                                ),
                                                "current_file_path": (
                                                    embedding_rel_path or rel_path
                                                ),
                                                "current_file_chunks_embedded": embedded_chunks,
                                                "current_file_chunks_total": total_chunks,
                                                "drive_files_seen": drive_seen,
                                                "drive_files_total": drive_total_files,
                                            },
                                        )

                                    (
                                        file_total,
                                        chunk_total,
                                        files_by_type,
                                        chunks_by_type,
                                    ) = index_paths(
                                        collection,
                                        source_config,
                                        [path],
                                        source_meta=source_meta,
                                        on_file_embedding_progress=_on_file_embedding_progress,
                                        should_stop=lambda: _should_stop(task_id),
                                    )
                                    indexed_files += file_total
                                    indexed_chunks += chunk_total
                                    _merge_counts(indexed_files_by_type, files_by_type)
                                    _merge_counts(indexed_chunks_by_type, chunks_by_type)
                                    source_checkpoints[str(source.id)] = {
                                        "last_indexed_path": rel_path,
                                        "indexed_file_count": indexed_files,
                                        "indexed_chunk_count": indexed_chunks,
                                        "indexed_file_types": dict(indexed_files_by_type),
                                        "indexed_chunk_types": dict(indexed_chunks_by_type),
                                        "drive_files_seen": drive_seen,
                                    }
                                    _persist_progress(
                                        task_id,
                                        meta,
                                        completed_source_ids,
                                        source_checkpoints,
                                        reset_applied_source_ids,
                                        progress_fields={
                                            "phase": "indexing",
                                            "file_index": absolute_file_index,
                                            "files_total": files_total_for_source,
                                            "files_completed": absolute_file_index,
                                            "current_file_path": rel_path,
                                            "drive_files_seen": drive_seen,
                                            "drive_files_total": drive_total_files,
                                        },
                                    )
                                    update_source_index(
                                        source.id,
                                        last_indexed_at=_utcnow(),
                                        last_error=None,
                                        indexed_file_count=indexed_files,
                                        indexed_chunk_count=indexed_chunks,
                                        indexed_file_types=json.dumps(
                                            indexed_files_by_type, sort_keys=True
                                        ),
                                    )
                                    append_task_output(
                                        task_id,
                                        (
                                            f"{source.name}: synced {stats.files_downloaded} files "
                                            f"(skipped {stats.files_skipped}), "
                                            f"indexed {indexed_files} files / {indexed_chunks} chunks."
                                        ),
                                    )

                        _persist_progress(
                            task_id,
                            meta,
                            completed_source_ids,
                            source_checkpoints,
                            reset_applied_source_ids,
                            progress_fields={
                                "phase": "indexing",
                                "files_total": files_total_for_source,
                                "files_completed": indexed_files,
                                "current_file_chunks_embedded": None,
                                "current_file_chunks_total": None,
                                "drive_files_seen": drive_seen,
                                "drive_files_total": drive_total_files,
                            },
                        )

                        total_files = indexed_files
                        total_chunks = indexed_chunks
                        files_by_type = indexed_files_by_type
                    else:
                        all_paths = list(_iter_files(source_config))
                        resume_path = str(checkpoint.get("last_indexed_path") or "").strip()
                        completed_paths_checkpoint = {
                            str(path or "").strip()
                            for path in (checkpoint.get("completed_paths") or [])
                            if str(path or "").strip()
                        }

                        if completed_paths_checkpoint:
                            filtered_paths: list[Path] = []
                            for path in all_paths:
                                rel_path = _relative_path(path, Path(source_config.repo_root))
                                if rel_path in completed_paths_checkpoint:
                                    continue
                                filtered_paths.append(path)
                            if len(filtered_paths) != len(all_paths):
                                all_paths = filtered_paths
                                base_file_count = max(
                                    base_file_count, len(completed_paths_checkpoint)
                                )
                                append_task_output(
                                    task_id,
                                    (
                                        f"{source.name}: resuming parallel checkpoint with "
                                        f"{len(completed_paths_checkpoint)} completed files."
                                    ),
                                )

                        if resume_path and not completed_paths_checkpoint:
                            path_index = -1
                            for idx, path in enumerate(all_paths):
                                if (
                                    _relative_path(path, Path(source_config.repo_root))
                                    == resume_path
                                ):
                                    path_index = idx
                                    break
                            if path_index >= 0:
                                all_paths = all_paths[path_index + 1 :]
                                append_task_output(
                                    task_id,
                                    f"{source.name}: resuming after {resume_path}.",
                                )
                            else:
                                append_task_output(
                                    task_id,
                                    (
                                        f"{source.name}: resume checkpoint not found "
                                        "in current source; restarting from beginning."
                                    ),
                                )
                                base_file_count = 0
                                base_chunk_count = 0
                                base_file_types = {}
                                base_chunk_types = {}

                        files_total_for_source = base_file_count + len(all_paths)
                        _persist_progress(
                            task_id,
                            meta,
                            completed_source_ids,
                            source_checkpoints,
                            reset_applied_source_ids,
                            progress_fields={
                                "phase": "indexing",
                                "file_index": None,
                                "files_total": files_total_for_source,
                                "files_completed": base_file_count,
                                "current_file_path": None,
                                "current_file_chunks_embedded": None,
                                "current_file_chunks_total": None,
                            },
                        )

                        client = chromadb.HttpClient(
                            host=source_config.chroma_host, port=source_config.chroma_port
                        )
                        collection = get_collection(
                            client, source_config, reset=should_reset
                        )
                        if should_reset and source.id not in reset_applied_source_ids:
                            reset_applied_source_ids.append(source.id)
                            _persist_progress(
                                task_id,
                                meta,
                                completed_source_ids,
                                source_checkpoints,
                                reset_applied_source_ids,
                            )
                        parallel_workers = max(
                            1,
                            int(getattr(source_config, "index_parallel_workers", 1)),
                        )

                        def _on_file_progress(
                            rel_path: str,
                            file_position: int,
                            file_count: int,
                            stage: str,
                        ) -> None:
                            absolute_file_index = base_file_count + file_position
                            completed_files = (
                                max(0, absolute_file_index - 1)
                                if stage == "start"
                                else absolute_file_index
                            )
                            progress_fields: dict[str, Any] = {
                                "phase": "indexing",
                                "file_index": absolute_file_index,
                                "files_total": base_file_count + file_count,
                                "files_completed": completed_files,
                                "current_file_path": rel_path,
                            }
                            if stage == "start":
                                progress_fields["current_file_chunks_embedded"] = 0
                                progress_fields["current_file_chunks_total"] = None
                            elif stage == "skipped":
                                progress_fields["current_file_chunks_embedded"] = None
                                progress_fields["current_file_chunks_total"] = 0
                            _persist_progress(
                                task_id,
                                meta,
                                completed_source_ids,
                                source_checkpoints,
                                reset_applied_source_ids,
                                progress_fields=progress_fields,
                            )

                        def _on_file_embedding_progress(
                            rel_path: str,
                            embedded_chunks: int,
                            total_chunks: int,
                        ) -> None:
                            _persist_progress(
                                task_id,
                                meta,
                                completed_source_ids,
                                source_checkpoints,
                                reset_applied_source_ids,
                                progress_fields={
                                    "phase": "indexing",
                                    "current_file_path": rel_path,
                                    "current_file_chunks_embedded": embedded_chunks,
                                    "current_file_chunks_total": total_chunks,
                                },
                            )

                        def _on_file_indexed(
                            rel_path: str,
                            file_total: int,
                            chunk_total: int,
                            files_by_type: dict[str, int],
                            chunks_by_type: dict[str, int],
                        ) -> None:
                            merged_file_types = dict(base_file_types)
                            merged_chunk_types = dict(base_chunk_types)
                            _merge_counts(merged_file_types, files_by_type)
                            _merge_counts(merged_chunk_types, chunks_by_type)

                            source_checkpoints[str(source.id)] = {
                                "last_indexed_path": rel_path,
                                "indexed_file_count": base_file_count + file_total,
                                "indexed_chunk_count": base_chunk_count + chunk_total,
                                "indexed_file_types": merged_file_types,
                                "indexed_chunk_types": merged_chunk_types,
                            }
                            _persist_progress(
                                task_id,
                                meta,
                                completed_source_ids,
                                source_checkpoints,
                                reset_applied_source_ids,
                                progress_fields={
                                    "phase": "indexing",
                                    "files_total": files_total_for_source,
                                },
                            )
                            update_source_index(
                                source.id,
                                last_indexed_at=_utcnow(),
                                last_error=None,
                                indexed_file_count=base_file_count + file_total,
                                indexed_chunk_count=base_chunk_count + chunk_total,
                                indexed_file_types=json.dumps(
                                    merged_file_types, sort_keys=True
                                ),
                            )

                        if parallel_workers > 1 and len(all_paths) > 1:
                            running_file_total = 0
                            running_chunk_total = 0
                            running_files_by_type = dict(base_file_types)
                            running_chunks_by_type = dict(base_chunk_types)

                            def _on_parallel_file_done(
                                outcome: _IndexedPathOutcome,
                                completed_count: int,
                                total_count: int,
                            ) -> None:
                                nonlocal running_file_total, running_chunk_total
                                running_file_total += int(outcome.file_total or 0)
                                running_chunk_total += int(outcome.chunk_total or 0)
                                _merge_counts(running_files_by_type, outcome.files_by_type)
                                _merge_counts(running_chunks_by_type, outcome.chunks_by_type)
                                completed_paths_checkpoint.add(outcome.rel_path)
                                absolute_file_index = base_file_count + completed_count
                                source_checkpoints[str(source.id)] = {
                                    "last_indexed_path": outcome.rel_path,
                                    "indexed_file_count": base_file_count
                                    + running_file_total,
                                    "indexed_chunk_count": base_chunk_count
                                    + running_chunk_total,
                                    "indexed_file_types": dict(running_files_by_type),
                                    "indexed_chunk_types": dict(running_chunks_by_type),
                                    "completed_paths": sorted(completed_paths_checkpoint),
                                }
                                _persist_progress(
                                    task_id,
                                    meta,
                                    completed_source_ids,
                                    source_checkpoints,
                                    reset_applied_source_ids,
                                    progress_fields={
                                        "phase": "indexing",
                                        "file_index": absolute_file_index,
                                        "files_total": base_file_count + total_count,
                                        "files_completed": absolute_file_index,
                                        "current_file_path": outcome.rel_path,
                                        "current_file_chunks_embedded": (
                                            outcome.chunk_count
                                            if outcome.indexed
                                            else None
                                        ),
                                        "current_file_chunks_total": (
                                            outcome.chunk_count if outcome.indexed else 0
                                        ),
                                    },
                                )
                                update_source_index(
                                    source.id,
                                    last_indexed_at=_utcnow(),
                                    last_error=None,
                                    indexed_file_count=base_file_count
                                    + running_file_total,
                                    indexed_chunk_count=base_chunk_count
                                    + running_chunk_total,
                                    indexed_file_types=json.dumps(
                                        running_files_by_type, sort_keys=True
                                    ),
                                )

                            (
                                file_total,
                                chunk_total,
                                files_by_type,
                                _,
                                _,
                            ) = _index_paths_parallel(
                                source_config=source_config,
                                source_meta=source_meta,
                                paths=all_paths,
                                delete_first=False,
                                max_workers=parallel_workers,
                                should_stop=lambda: _should_stop(task_id),
                                on_file_done=_on_parallel_file_done,
                            )
                        else:
                            file_total, chunk_total, files_by_type, _ = index_paths(
                                collection,
                                source_config,
                                all_paths,
                                source_meta=source_meta,
                                on_file_indexed=_on_file_indexed,
                                on_file_progress=_on_file_progress,
                                on_file_embedding_progress=_on_file_embedding_progress,
                                should_stop=lambda: _should_stop(task_id),
                            )

                        _ensure_task_continuing(task_id)

                        total_files = base_file_count + file_total
                        total_chunks = base_chunk_count + chunk_total
                        merged_file_types = dict(base_file_types)
                        _merge_counts(merged_file_types, files_by_type)
                        files_by_type = merged_file_types
                        _persist_progress(
                            task_id,
                            meta,
                            completed_source_ids,
                            source_checkpoints,
                            reset_applied_source_ids,
                            progress_fields={
                                "phase": "indexing",
                                "files_total": files_total_for_source,
                                "files_completed": total_files,
                                "current_file_chunks_embedded": None,
                                "current_file_chunks_total": None,
                            },
                        )

                    update_source_index(
                        source.id,
                        last_indexed_at=_utcnow(),
                        last_error=None,
                        indexed_file_count=total_files,
                        indexed_chunk_count=total_chunks,
                        indexed_file_types=json.dumps(files_by_type, sort_keys=True),
                    )
                    if task_index_mode == INDEX_MODE_FRESH:
                        delete_source_file_states(source.id)
                    schedule_source_next_index(source.id, from_time=_utcnow())

                    _finalize_source_success(
                        source_id=source.id,
                        source_checkpoints=source_checkpoints,
                        completed_source_ids=completed_source_ids,
                    )
                    _persist_progress(
                        task_id,
                        meta,
                        completed_source_ids,
                        source_checkpoints,
                        reset_applied_source_ids,
                        progress_fields={
                            "phase": "complete",
                            "file_index": total_files if total_files > 0 else None,
                            "files_total": total_files,
                            "files_completed": total_files,
                            "current_file_chunks_embedded": None,
                            "current_file_chunks_total": None,
                        },
                    )

                    summary = f"{source.name}: {total_files} files, {total_chunks} chunks"
                    output_lines.append(summary)
                    append_task_output(task_id, summary)
                except _TaskPausedError:
                    append_task_output(
                        task_id,
                        "Task pause detected. Current progress saved; resume to continue.",
                    )
                    mark_task_paused(
                        task_id,
                        message="Task paused. Resume to continue indexing from checkpoint.",
                    )
                    return
                except _TaskCancelledError:
                    append_task_output(
                        task_id, "Task cancellation detected. Stopping remaining work."
                    )
                    return
                except Exception as exc:
                    update_source_index(
                        source.id,
                        last_indexed_at=source.last_indexed_at,
                        last_error=str(exc),
                    )
                    schedule_source_next_index(source.id, from_time=_utcnow())
                    errors.append(f"{source.name}: {exc}")
                    failure_line = f"{source.name}: failed ({exc})"
                    output_lines.append(failure_line)
                    append_task_output(task_id, failure_line)
                    if source_id is not None:
                        break

            if errors:
                error = "; ".join(errors)
    except Exception as exc:
        logger.exception("Index task failed")
        error = str(exc)
        output_lines.append(f"Task failed: {error}")
        append_task_output(task_id, f"Task failed: {error}")

    status = TASK_STATUS_FAILED if error else TASK_STATUS_SUCCEEDED
    output = None
    if output_lines:
        current = get_task(task_id)
        if current and not current.output:
            output = "\n".join(output_lines)

    latest = get_task(task_id)
    if latest and latest.status in {TASK_STATUS_CANCELLED, TASK_STATUS_PAUSED}:
        return

    mark_task_finished(task_id, status=status, output=output, error=error)


def _normalize_trigger_mode(value: str | None) -> str:
    trigger = (value or RAG_INDEX_TRIGGER_MANUAL).strip().lower()
    if trigger in {RAG_INDEX_TRIGGER_MANUAL, RAG_INDEX_TRIGGER_SCHEDULED}:
        return trigger
    raise ValueError("Trigger mode must be manual or scheduled.")


def _enqueue_index_task(
    task_id: int,
    source_id: int,
    reset: bool,
    index_mode: str,
) -> bool:
    source = get_source(source_id)
    if not source:
        mark_task_finished(
            task_id,
            status=TASK_STATUS_FAILED,
            output="Source not found.",
            error="Source not found.",
        )
        return False
    queue_name = queue_for_source_kind(getattr(source, "kind", ""))
    try:
        result = run_index_task.apply_async(
            args=[task_id, source_id, bool(reset), _normalize_index_mode(index_mode)],
            ignore_result=True,
            queue=queue_name,
        )
    except Exception as exc:
        mark_task_finished(
            task_id,
            status=TASK_STATUS_FAILED,
            output="Failed to enqueue index job.",
            error=str(exc),
        )
        return False
    set_index_job_celery_id(task_id, getattr(result, "id", None))
    return True


def start_source_index_job(
    source_id: int,
    *,
    reset: bool = False,
    index_mode: str = INDEX_MODE_FRESH,
    trigger_mode: str = RAG_INDEX_TRIGGER_MANUAL,
):
    source = get_source(source_id)
    if not source:
        raise ValueError("Source not found.")
    if has_active_index_job(source_id=source_id):
        return None

    mode = _normalize_index_mode(index_mode)
    trigger = _normalize_trigger_mode(trigger_mode)
    meta: dict[str, Any] = {
        "reset": bool(reset),
        "index_mode": mode,
        "source_id": source_id,
        "source_order": [source_id],
    }
    job = create_index_job(
        source_id=source_id,
        kind=TASK_KIND_INDEX,
        mode=mode,
        trigger_mode=trigger,
        meta=meta,
    )
    if not _enqueue_index_task(job.id, source_id, bool(reset), mode):
        return None
    return get_task(job.id)


def resume_source_index_job(source_id: int):
    if has_active_index_job(source_id=source_id):
        return None
    paused = latest_index_job(source_id=source_id, statuses={TASK_STATUS_PAUSED})
    if not paused:
        return None
    updated = resume_index_job(paused.id)
    if not updated or updated.status != TASK_STATUS_QUEUED:
        return None
    meta = task_meta(updated)
    reset = bool(meta.get("reset"))
    mode = _normalize_index_mode(meta.get("index_mode", updated.mode))
    if not _enqueue_index_task(updated.id, source_id, reset, mode):
        return None
    return get_task(updated.id)


def pause_source_index_job(source_id: int):
    job = active_index_job(source_id=source_id)
    if not job:
        return None
    updated = pause_index_job(job.id)
    if not updated:
        return None
    celery_task_id = (job.celery_task_id or "").strip()
    if celery_task_id and updated.status == TASK_STATUS_PAUSED:
        try:
            celery_app.control.revoke(celery_task_id, terminate=False)
        except Exception:
            pass
    return get_task(job.id)


def cancel_source_index_job(source_id: int):
    job = active_index_job(source_id=source_id)
    if not job:
        return None
    celery_task_id = (job.celery_task_id or "").strip()
    if celery_task_id:
        try:
            celery_app.control.revoke(celery_task_id, terminate=True, signal="SIGTERM")
        except Exception:
            pass
    cancel_index_job(job.id)
    return get_task(job.id)


def source_index_job_snapshot(source_id: int) -> dict[str, Any]:
    source = get_source(source_id)
    if not source:
        raise ValueError("Source not found.")
    active = active_index_job(source_id=source_id)
    if active:
        return {
            "running": True,
            "status": active.status,
            "index_mode": _normalize_index_mode(active.mode),
            "source_id": source_id,
            "last_started_at": active.started_at.isoformat() if active.started_at else None,
            "last_finished_at": None,
            "last_error": None,
            "last_indexed_at": (
                source.last_indexed_at.isoformat() if source.last_indexed_at else None
            ),
            "can_resume": False,
            "paused_job_id": None,
            "progress": task_meta(active).get("progress"),
        }
    latest = latest_index_job(source_id=source_id)
    progress = task_meta(latest).get("progress") if latest else None
    paused = latest is not None and latest.status == TASK_STATUS_PAUSED
    return {
        "running": False,
        "status": latest.status if latest else None,
        "index_mode": _normalize_index_mode(latest.mode) if latest else None,
        "source_id": source_id,
        "last_started_at": latest.started_at.isoformat() if latest and latest.started_at else None,
        "last_finished_at": (
            latest.finished_at.isoformat() if latest and latest.finished_at else None
        ),
        "last_error": source.last_error,
        "last_indexed_at": source.last_indexed_at.isoformat() if source.last_indexed_at else None,
        "can_resume": paused,
        "paused_job_id": latest.id if paused else None,
        "progress": progress,
    }
