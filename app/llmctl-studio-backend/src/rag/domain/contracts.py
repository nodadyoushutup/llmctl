from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import logging
import socket
import time
from pathlib import Path
from typing import Any, Callable

try:
    import chromadb
except ImportError:  # pragma: no cover
    chromadb = None

from core.config import Config
from core.db import session_scope, utcnow
from core.models import RAGRetrievalAudit, RAGSource
from rag.engine.config import build_source_config, load_config
from rag.engine.ingest import _iter_files, get_collection, index_paths
from rag.engine.logging_utils import log_sink as rag_log_sink
from rag.engine.retrieval import get_collections, query_collections
from rag.integrations.git_sync import ensure_git_repo, git_fetch_and_reset
from rag.integrations.google_drive_sync import sync_folder
from rag.providers.adapters import has_embedding_api_key
from rag.repositories.source_file_states import (
    SourceFileStateInput,
    delete_source_file_states,
    list_source_file_states,
    summarize_source_file_states,
    upsert_source_file_states,
)
from rag.repositories.sources import (
    list_sources,
    schedule_source_next_index,
    update_source_index,
)
from services.integrations import load_integration_settings

logger = logging.getLogger(__name__)

RAG_CONTRACT_VERSION = "v1"
RAG_PROVIDER = "chroma"

RAG_HEALTH_UNCONFIGURED = "unconfigured"
RAG_HEALTH_CONFIGURED_UNHEALTHY = "configured_unhealthy"
RAG_HEALTH_CONFIGURED_HEALTHY = "configured_healthy"

RAG_REASON_UNAVAILABLE_FOR_SELECTED_COLLECTIONS = (
    "RAG_UNAVAILABLE_FOR_SELECTED_COLLECTIONS"
)
RAG_REASON_RETRIEVAL_EXECUTION_FAILED = "RAG_RETRIEVAL_EXECUTION_FAILED"

RAG_FLOWCHART_MODE_FRESH_INDEX = "fresh_index"
RAG_FLOWCHART_MODE_DELTA_INDEX = "delta_index"
RAG_FLOWCHART_MODE_QUERY = "query"
RAG_FLOWCHART_MODE_CHOICES = (
    RAG_FLOWCHART_MODE_FRESH_INDEX,
    RAG_FLOWCHART_MODE_DELTA_INDEX,
    RAG_FLOWCHART_MODE_QUERY,
)

RAG_HEALTH_TIMEOUT_SECONDS = 2.0
DOCKER_CHROMA_HOST_ALIASES = {"llmctl-chromadb", "chromadb"}


class RagContractError(RuntimeError):
    def __init__(
        self,
        *,
        reason_code: str,
        status_code: int,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.status_code = status_code
        self.metadata = metadata or {}

    def as_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "reason_code": self.reason_code,
                "message": str(self),
                "metadata": self.metadata,
            }
        }


def normalize_collection_selection(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    selected: list[str] = []
    seen: set[str] = set()
    for value in values:
        token = str(value or "").strip()
        if not token:
            continue
        lowered = token.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        selected.append(token)
    return selected


def _parse_port(raw: str | None) -> int | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        parsed = int(text)
    except ValueError:
        return None
    if parsed < 1 or parsed > 65535:
        return None
    return parsed


def _normalize_chroma_target(host: str, port: int) -> tuple[str, int]:
    cleaned = (host or "").strip()
    if cleaned.lower() in DOCKER_CHROMA_HOST_ALIASES and port != 8000:
        return "llmctl-chromadb", 8000
    if cleaned.lower() in DOCKER_CHROMA_HOST_ALIASES:
        return "llmctl-chromadb", port
    return cleaned, port


def _resolve_chroma_target() -> tuple[str, int | None]:
    settings = load_integration_settings("chroma")
    host = (settings.get("host") or "").strip() or (Config.CHROMA_HOST or "").strip()
    port = _parse_port(settings.get("port")) or _parse_port(Config.CHROMA_PORT)
    if not host or port is None:
        return host, port
    normalized_host, normalized_port = _normalize_chroma_target(host, port)
    return normalized_host, normalized_port


def rag_health_snapshot() -> dict[str, Any]:
    host, port = _resolve_chroma_target()
    if not host or port is None:
        return {
            "state": RAG_HEALTH_UNCONFIGURED,
            "provider": RAG_PROVIDER,
            "host": host or "",
            "port": port,
            "configured": False,
            "healthy": False,
            "timeout_seconds": RAG_HEALTH_TIMEOUT_SECONDS,
            "error": "Chroma host/port not configured.",
        }

    try:
        with socket.create_connection((host, port), timeout=RAG_HEALTH_TIMEOUT_SECONDS):
            pass
    except OSError as exc:
        return {
            "state": RAG_HEALTH_CONFIGURED_UNHEALTHY,
            "provider": RAG_PROVIDER,
            "host": host,
            "port": port,
            "configured": True,
            "healthy": False,
            "timeout_seconds": RAG_HEALTH_TIMEOUT_SECONDS,
            "error": str(exc),
        }
    return {
        "state": RAG_HEALTH_CONFIGURED_HEALTHY,
        "provider": RAG_PROVIDER,
        "host": host,
        "port": port,
        "configured": True,
        "healthy": True,
        "timeout_seconds": RAG_HEALTH_TIMEOUT_SECONDS,
        "error": None,
    }


def list_collection_contract() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in list_sources(limit=None):
        collection_name = str(getattr(source, "collection", "") or "").strip()
        if not collection_name:
            continue
        key = collection_name.lower()
        if key in seen:
            continue
        seen.add(key)
        status = "ready"
        if getattr(source, "last_error", None):
            status = "error"
        elif getattr(source, "last_indexed_at", None) is None:
            status = "not_indexed"
        rows.append(
            {
                "id": collection_name,
                "name": collection_name,
                "status": status,
            }
        )
    rows.sort(key=lambda item: str(item.get("name", "")).lower())
    return {"provider": RAG_PROVIDER, "collections": rows}


def _resolve_sources_for_collections(
    selected_collections: list[str],
) -> tuple[list[RAGSource], list[str]]:
    selected_keys = {token.lower(): token for token in selected_collections}
    if not selected_keys:
        return [], []
    matched: list[RAGSource] = []
    matched_keys: set[str] = set()
    for source in list_sources(limit=None):
        collection_name = str(getattr(source, "collection", "") or "").strip()
        source_name = str(getattr(source, "name", "") or "").strip()
        source_id = str(getattr(source, "id", "") or "").strip()
        candidates = {
            collection_name.lower(): collection_name,
            source_name.lower(): source_name,
            source_id.lower(): source_id,
        }
        for candidate_key in list(candidates):
            if not candidate_key or candidate_key not in selected_keys:
                continue
            matched.append(source)
            matched_keys.add(candidate_key)
            break
    missing = [selected_keys[key] for key in selected_keys if key not in matched_keys]
    return matched, missing


def _persist_retrieval_audit_rows(
    *,
    request_id: str | None,
    runtime_kind: str,
    flowchart_run_id: int | None,
    flowchart_node_run_id: int | None,
    rows: list[dict[str, Any]],
) -> None:
    if not rows:
        return
    with session_scope() as session:
        for row in rows:
            RAGRetrievalAudit.create(
                session,
                request_id=request_id or None,
                runtime_kind=runtime_kind,
                flowchart_run_id=flowchart_run_id,
                flowchart_node_run_id=flowchart_node_run_id,
                provider=str(row.get("provider") or RAG_PROVIDER),
                collection=(str(row.get("collection") or "").strip() or None),
                source_id=(str(row.get("source_id") or "").strip() or None),
                path=(str(row.get("path") or "").strip() or None),
                chunk_id=(str(row.get("chunk_id") or "").strip() or None),
                score=row.get("score"),
                snippet=(str(row.get("snippet") or "").strip() or None),
                retrieval_rank=row.get("retrieval_rank"),
            )


def execute_query_contract(
    *,
    question: str,
    collections: list[str],
    top_k: int,
    request_id: str | None = None,
    runtime_kind: str = "chat",
    flowchart_run_id: int | None = None,
    flowchart_node_run_id: int | None = None,
    synthesize_answer: Callable[[str, list[dict[str, Any]]], str | None] | None = None,
) -> dict[str, Any]:
    selected_collections = normalize_collection_selection(collections)
    health = rag_health_snapshot()
    if selected_collections and health["state"] != RAG_HEALTH_CONFIGURED_HEALTHY:
        raise RagContractError(
            reason_code=RAG_REASON_UNAVAILABLE_FOR_SELECTED_COLLECTIONS,
            status_code=503,
            message="RAG is unavailable for selected collections.",
            metadata={
                "rag_health_state": health["state"],
                "selected_collections": selected_collections,
                "provider": RAG_PROVIDER,
            },
        )

    sources, missing = _resolve_sources_for_collections(selected_collections)
    if missing:
        raise RagContractError(
            reason_code=RAG_REASON_UNAVAILABLE_FOR_SELECTED_COLLECTIONS,
            status_code=400,
            message="One or more selected collections are not available.",
            metadata={
                "rag_health_state": health["state"],
                "selected_collections": selected_collections,
                "provider": RAG_PROVIDER,
                "missing_collections": missing,
            },
        )

    context_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    try:
        if selected_collections:
            config = load_config()
            if not has_embedding_api_key(config):
                raise RagContractError(
                    reason_code=RAG_REASON_RETRIEVAL_EXECUTION_FAILED,
                    status_code=500,
                    message="RAG embedding provider API key is not configured.",
                )
            collection_bindings = get_collections(config, sources)
            documents, metadatas = query_collections(
                question,
                collection_bindings,
                max(1, int(top_k)),
            )
            for retrieval_rank, (doc, meta) in enumerate(
                zip(documents, metadatas), start=1
            ):
                text = str(doc or "").strip()
                if not text:
                    continue
                metadata = meta if isinstance(meta, dict) else {}
                collection_name = str(metadata.get("collection") or "").strip()
                context_rows.append(
                    {
                        "text": text,
                        "collection": collection_name or None,
                        "rank": retrieval_rank,
                    }
                )
                audit_rows.append(
                    {
                        "provider": RAG_PROVIDER,
                        "collection": collection_name,
                        "source_id": metadata.get("source_id"),
                        "path": metadata.get("path"),
                        "chunk_id": metadata.get("chunk_id"),
                        "score": metadata.get("score"),
                        "snippet": text[:1200],
                        "retrieval_rank": retrieval_rank,
                    }
                )
    except RagContractError:
        raise
    except Exception as exc:
        raise RagContractError(
            reason_code=RAG_REASON_RETRIEVAL_EXECUTION_FAILED,
            status_code=500,
            message=f"RAG retrieval execution failed: {exc}",
        ) from exc

    _persist_retrieval_audit_rows(
        request_id=request_id,
        runtime_kind=runtime_kind,
        flowchart_run_id=flowchart_run_id,
        flowchart_node_run_id=flowchart_node_run_id,
        rows=audit_rows,
    )

    answer: str | None = None
    synthesis_error: dict[str, Any] | None = None
    if synthesize_answer is not None:
        try:
            answer = synthesize_answer(question, context_rows)
        except Exception as exc:  # synthesis fallback is non-fatal in v1
            synthesis_error = {
                "message": str(exc),
                "type": exc.__class__.__name__,
            }

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "answer": answer,
        "retrieval_context": context_rows,
        "retrieval_stats": {
            "provider": RAG_PROVIDER,
            "top_k": max(1, int(top_k)),
            "retrieved_count": len(context_rows),
            "elapsed_ms": elapsed_ms,
        },
        "synthesis_error": synthesis_error,
        "mode": RAG_FLOWCHART_MODE_QUERY,
        "collections": selected_collections,
    }


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


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
        return ""
    return f"sha1:{hasher.hexdigest()}"


def _embedding_provider_for_model_provider(model_provider: str) -> str | None:
    cleaned = str(model_provider or "").strip().lower()
    if cleaned == "gemini":
        return "gemini"
    if cleaned == "codex":
        return "openai"
    return None


def _rollback_partial_source_index(
    *,
    source: RAGSource,
    source_config: Any,
    mode: str,
    touched_paths: list[str],
) -> str | None:
    if chromadb is None:
        return "chromadb package is not installed; rollback skipped."
    try:
        client = chromadb.HttpClient(
            host=source_config.chroma_host,
            port=source_config.chroma_port,
        )
        if mode == RAG_FLOWCHART_MODE_FRESH_INDEX:
            try:
                client.delete_collection(name=source_config.collection)
            except Exception:
                pass
            get_collection(client, source_config, reset=False)
            delete_source_file_states(source.id)
            return None
        collection = get_collection(client, source_config, reset=False)
        for rel_path in touched_paths:
            if not rel_path:
                continue
            try:
                collection.delete(where={"path": rel_path})
            except Exception:
                continue
        return None
    except Exception as exc:
        return str(exc)


def _run_fresh_source_index(
    *,
    source: RAGSource,
    source_config: Any,
) -> dict[str, Any]:
    if chromadb is None:
        raise RuntimeError("chromadb package is required for fresh_index.")
    if source.kind == "github":
        ensure_git_repo(source_config)
        git_fetch_and_reset(source_config)
    if source.kind == "google_drive":
        service_account_json = (
            load_integration_settings("google_workspace").get("service_account_json")
            or ""
        ).strip()
        local_path = str(getattr(source, "local_path", "") or "").strip()
        folder_id = str(getattr(source, "drive_folder_id", "") or "").strip()
        if not service_account_json:
            raise RuntimeError(
                "Google Drive service account JSON is required for indexing."
            )
        if not local_path or not folder_id:
            raise RuntimeError("Google Drive source is missing local path or folder id.")
        sync_folder(service_account_json, folder_id, Path(local_path))

    client = chromadb.HttpClient(
        host=source_config.chroma_host,
        port=source_config.chroma_port,
    )
    collection = get_collection(client, source_config, reset=True)
    paths = list(_iter_files(source_config))
    repo_root = Path(source_config.repo_root)
    fingerprints: dict[str, str] = {}
    for path in paths:
        rel_path = _relative_path(path, repo_root)
        fingerprint = _path_fingerprint(path)
        if rel_path and fingerprint:
            fingerprints[rel_path] = fingerprint
    indexed_by_path: dict[str, tuple[bool, str | None, int]] = {}

    def _on_file_result(
        rel_path: str,
        indexed: bool,
        doc_type: str | None,
        chunk_count: int,
    ) -> None:
        indexed_by_path[rel_path] = (indexed, doc_type, int(chunk_count or 0))

    file_total, chunk_total, files_by_type, _ = index_paths(
        collection,
        source_config,
        paths,
        delete_first=False,
        source_meta={
            "source_id": source.id,
            "source_name": source.name,
            "source_kind": source.kind,
        },
        on_file_result=_on_file_result,
    )
    delete_source_file_states(source.id)
    state_updates: list[SourceFileStateInput] = []
    touched_paths: list[str] = []
    for rel_path, (indexed, doc_type, chunk_count) in indexed_by_path.items():
        fingerprint = fingerprints.get(rel_path)
        if not fingerprint:
            continue
        touched_paths.append(rel_path)
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
    update_source_index(
        source.id,
        last_indexed_at=utcnow(),
        last_error=None,
        indexed_file_count=file_total,
        indexed_chunk_count=chunk_total,
        indexed_file_types=json.dumps(files_by_type, sort_keys=True),
    )
    schedule_source_next_index(source.id, from_time=utcnow())
    return {
        "source_id": source.id,
        "source_name": source.name,
        "file_count": int(file_total or 0),
        "chunk_count": int(chunk_total or 0),
        "touched_paths": touched_paths,
    }


def _run_delta_source_index(
    *,
    source: RAGSource,
    source_config: Any,
) -> dict[str, Any]:
    if chromadb is None:
        raise RuntimeError("chromadb package is required for delta_index.")
    if source.kind == "github":
        ensure_git_repo(source_config)
        git_fetch_and_reset(source_config)
    if source.kind == "google_drive":
        service_account_json = (
            load_integration_settings("google_workspace").get("service_account_json")
            or ""
        ).strip()
        local_path = str(getattr(source, "local_path", "") or "").strip()
        folder_id = str(getattr(source, "drive_folder_id", "") or "").strip()
        if not service_account_json:
            raise RuntimeError(
                "Google Drive service account JSON is required for indexing."
            )
        if not local_path or not folder_id:
            raise RuntimeError("Google Drive source is missing local path or folder id.")
        sync_folder(service_account_json, folder_id, Path(local_path))

    client = chromadb.HttpClient(
        host=source_config.chroma_host,
        port=source_config.chroma_port,
    )
    collection = get_collection(client, source_config, reset=False)
    repo_root = Path(source_config.repo_root)
    all_paths = list(_iter_files(source_config))
    current_by_path: dict[str, tuple[Path, str]] = {}
    for path in all_paths:
        rel_path = _relative_path(path, repo_root)
        fingerprint = _path_fingerprint(path)
        if rel_path and fingerprint:
            current_by_path[rel_path] = (path, fingerprint)

    existing = {state.path: state for state in list_source_file_states(source.id)}
    changed_paths: list[Path] = []
    changed_rel_paths: list[str] = []
    for rel_path, (path, fingerprint) in current_by_path.items():
        existing_state = existing.get(rel_path)
        if existing_state is None or str(existing_state.fingerprint or "") != fingerprint:
            changed_paths.append(path)
            changed_rel_paths.append(rel_path)

    removed_paths = [path for path in existing if path not in current_by_path]
    for rel_path in removed_paths:
        try:
            collection.delete(where={"path": rel_path})
        except Exception:
            continue
    if removed_paths:
        delete_source_file_states(source.id, paths=removed_paths)

    indexed_by_path: dict[str, tuple[bool, str | None, int]] = {}

    def _on_file_result(
        rel_path: str,
        indexed: bool,
        doc_type: str | None,
        chunk_count: int,
    ) -> None:
        indexed_by_path[rel_path] = (indexed, doc_type, int(chunk_count or 0))

    if changed_paths:
        index_paths(
            collection,
            source_config,
            changed_paths,
            delete_first=True,
            source_meta={
                "source_id": source.id,
                "source_name": source.name,
                "source_kind": source.kind,
            },
            on_file_result=_on_file_result,
        )

    updates: list[SourceFileStateInput] = []
    touched_paths = list(changed_rel_paths)
    for rel_path, (indexed, doc_type, chunk_count) in indexed_by_path.items():
        fingerprint = current_by_path.get(rel_path, (None, ""))[1]
        if not fingerprint:
            continue
        updates.append(
            SourceFileStateInput(
                path=rel_path,
                fingerprint=fingerprint,
                indexed=indexed,
                doc_type=doc_type if indexed else None,
                chunk_count=chunk_count if indexed else 0,
            )
        )
    if updates:
        upsert_source_file_states(source.id, updates)

    stats = summarize_source_file_states(source.id)
    update_source_index(
        source.id,
        last_indexed_at=utcnow(),
        last_error=None,
        indexed_file_count=stats.indexed_file_count,
        indexed_chunk_count=stats.indexed_chunk_count,
        indexed_file_types=json.dumps(stats.indexed_file_types, sort_keys=True),
    )
    schedule_source_next_index(source.id, from_time=utcnow())
    return {
        "source_id": source.id,
        "source_name": source.name,
        "file_count": int(stats.indexed_file_count),
        "chunk_count": int(stats.indexed_chunk_count),
        "touched_paths": touched_paths,
    }


def run_index_for_collections(
    *,
    mode: str,
    collections: list[str],
    model_provider: str,
    on_log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    def _emit_log(message: str) -> None:
        if on_log is None:
            return
        try:
            on_log(str(message or ""))
        except Exception:
            return

    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in {
        RAG_FLOWCHART_MODE_FRESH_INDEX,
        RAG_FLOWCHART_MODE_DELTA_INDEX,
    }:
        raise ValueError("RAG index mode must be fresh_index or delta_index.")
    selected_collections = normalize_collection_selection(collections)
    if not selected_collections:
        raise ValueError("RAG index mode requires at least one collection.")
    health = rag_health_snapshot()
    if health["state"] != RAG_HEALTH_CONFIGURED_HEALTHY:
        raise ValueError(
            f"RAG integration is {health['state']}; indexing is unavailable."
        )

    embedding_provider = _embedding_provider_for_model_provider(model_provider)
    if embedding_provider is None:
        raise ValueError(
            f"Model provider '{model_provider}' does not support RAG indexing."
        )

    sources, missing = _resolve_sources_for_collections(selected_collections)
    if missing:
        raise ValueError(
            "One or more selected collections are unavailable: "
            + ", ".join(missing)
            + "."
        )
    base_config = load_config()
    github_settings = load_integration_settings("github")
    source_summaries: list[dict[str, Any]] = []
    total_files = 0
    total_chunks = 0
    _emit_log(
        "Starting RAG "
        + ("delta indexing" if normalized_mode == RAG_FLOWCHART_MODE_DELTA_INDEX else "indexing")
        + f" for {len(selected_collections)} collection(s)."
    )

    for source in sources:
        source_config = build_source_config(base_config, source, github_settings)
        source_config = replace(
            source_config,
            embed_provider=embedding_provider,
            embed_model=(
                source_config.gemini_embedding_model
                if embedding_provider == "gemini"
                else source_config.openai_embedding_model
            ),
        )
        if not has_embedding_api_key(source_config):
            raise ValueError(
                f"Missing embedding API key for provider '{embedding_provider}'."
            )
        touched_paths: list[str] = []
        try:
            _emit_log(
                f"Indexing source '{source.name}' (collection '{source.collection}')."
            )
            source_summary: dict[str, Any]
            if normalized_mode == RAG_FLOWCHART_MODE_FRESH_INDEX:
                with rag_log_sink(_emit_log):
                    source_summary = _run_fresh_source_index(
                        source=source,
                        source_config=source_config,
                    )
            else:
                with rag_log_sink(_emit_log):
                    source_summary = _run_delta_source_index(
                        source=source,
                        source_config=source_config,
                    )
            touched_paths = list(source_summary.pop("touched_paths", []))
            source_summary["collection"] = source.collection
            source_summaries.append(source_summary)
            total_files += int(source_summary.get("file_count") or 0)
            total_chunks += int(source_summary.get("chunk_count") or 0)
            _emit_log(
                "Completed source "
                + f"'{source.name}' with {int(source_summary.get('file_count') or 0)} files "
                + f"and {int(source_summary.get('chunk_count') or 0)} chunks."
            )
        except Exception as exc:
            rollback_error = _rollback_partial_source_index(
                source=source,
                source_config=source_config,
                mode=normalized_mode,
                touched_paths=touched_paths,
            )
            update_source_index(
                source.id,
                last_indexed_at=getattr(source, "last_indexed_at", None),
                last_error=str(exc),
            )
            if rollback_error:
                _emit_log(
                    f"RAG indexing failed for source '{source.name}' and rollback failed."
                )
                raise ValueError(
                    f"RAG indexing failed for source '{source.name}' and rollback failed: "
                    f"{rollback_error}"
                ) from exc
            _emit_log(f"RAG indexing failed for source '{source.name}'.")
            raise ValueError(
                f"RAG indexing failed for source '{source.name}': {exc}"
            ) from exc

    _emit_log(
        f"RAG indexing complete: {total_files} files, {total_chunks} chunks across {len(source_summaries)} source(s)."
    )
    return {
        "mode": normalized_mode,
        "collections": selected_collections,
        "source_count": len(source_summaries),
        "total_files": total_files,
        "total_chunks": total_chunks,
        "sources": source_summaries,
    }
