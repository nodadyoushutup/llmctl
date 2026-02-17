from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import threading
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import chromadb
from flask import Flask, jsonify, redirect, render_template, request, url_for

from config import build_source_config, load_config
from db import SSH_KEYS_DIR, init_db, utcnow
from google_drive_sync import service_account_email, verify_folder_access
from provider_adapters import (
    build_embedding_function,
    call_chat_completion,
    get_chat_model,
    get_chat_provider,
    get_embedding_provider,
    has_chat_api_key,
    has_embedding_api_key,
    missing_api_key_message,
    normalize_provider,
)
from source_file_states_store import delete_source_file_states
from settings_store import (
    ensure_integration_defaults,
    load_integration_settings,
    save_integration_settings,
)
from sources_store import (
    SCHEDULE_UNITS,
    SourceInput,
    create_source,
    delete_source,
    get_source,
    list_sources,
    schedule_source_next_index,
    update_source,
    update_source_index,
)
from tasks_store import (
    TASK_KIND_INDEX,
    TASK_ACTIVE_STATUSES,
    TASK_STATUS_FAILED,
    TASK_STATUS_PAUSED,
    TASK_STATUS_PAUSING,
    TASK_STATUS_QUEUED,
    active_task,
    cancel_task,
    create_task,
    delete_task,
    format_dt,
    get_tasks,
    get_task,
    has_active_task,
    latest_task,
    latest_finished_task,
    list_active_tasks,
    list_tasks,
    mark_task_finished,
    pause_task,
    resume_task,
    set_task_celery_id,
    task_meta,
)
from tasks_worker import run_index_task

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "web" / "templates"
STATIC_DIR = BASE_DIR / "web" / "static"
_SUPPORTED_CHAT_RESPONSE_STYLES = {"low", "medium", "high"}
_CHAT_RESPONSE_STYLE_ALIASES = {
    "concise": "low",
    "brief": "low",
    "balanced": "medium",
    "detailed": "high",
    "verbose": "high",
}
_INCOMPLETE_INDEX_STATUSES = set(TASK_ACTIVE_STATUSES) | {TASK_STATUS_PAUSED}
_SOURCE_SCHEDULER_STOP = threading.Event()
_SOURCE_SCHEDULER_LOCK = threading.Lock()
_SOURCE_SCHEDULER_THREAD: threading.Thread | None = None
DOCKER_CHROMA_HOST_ALIASES = {"llmctl-chromadb", "chromadb"}

PAGINATION_PAGE_SIZES = (10, 25, 50, 100)
PAGINATION_DEFAULT_SIZE = 10
PAGINATION_WINDOW = 2

_BASE_SYSTEM_PROMPT = (
    "You are a helpful assistant for a retrieval-augmented generation app. "
    "Use the provided context and the conversation history to answer. "
    "If the answer is not in the context or the conversation, say you do not know. "
    "Prefer the retrieved context when it conflicts with the conversation. "
    "Markdown formatting is supported in the chat UI, so you may use markdown when it improves clarity. "
)

INDEX_MODE_FRESH = "fresh"
INDEX_MODE_DELTA = "delta"
_INDEX_MODE_VALUES = {INDEX_MODE_FRESH, INDEX_MODE_DELTA}


def _normalize_chat_response_style(value: str | None, default: str = "high") -> str:
    candidate = (value or "").strip().lower()
    candidate = _CHAT_RESPONSE_STYLE_ALIASES.get(candidate, candidate)
    if candidate in _SUPPORTED_CHAT_RESPONSE_STYLES:
        return candidate
    return default


def _system_prompt(response_style: str) -> str:
    normalized_style = _normalize_chat_response_style(response_style, "high")
    if normalized_style == "low":
        return (
            _BASE_SYSTEM_PROMPT
            + "Keep responses natural, conversational, concise, direct, and grounded. "
            + "Prioritize the main answer and only the most important supporting detail."
        )
    if normalized_style == "medium":
        return (
            _BASE_SYSTEM_PROMPT
            + "Provide a balanced answer with natural, conversational flow and clear detail. "
            + "Do not force a fixed output template. "
            + "Use brief structure only when helpful."
        )
    return (
        _BASE_SYSTEM_PROMPT
        + "Provide detailed answers grounded in the retrieved context while keeping a natural, "
        + "conversational tone. "
        + "Be thorough but avoid filler; include useful detail only. "
        + "Use clear markdown sections or bullet points when helpful, not as a rigid template. "
        + "If the user asks for a table, return a markdown table and include as much relevant context-backed data as possible. "
        + "If context is incomplete, clearly state what is missing."
    )


def _normalize_chroma_target(host: str, port: int) -> tuple[str, int, str | None]:
    host_value = (host or "").strip()
    # Inside the Docker network, the Chroma service is reachable on container port 8000.
    if host_value.lower() in DOCKER_CHROMA_HOST_ALIASES and port != 8000:
        return (
            "llmctl-chromadb",
            8000,
            "Using llmctl-chromadb:8000 inside Docker. Host-mapped ports (for example 18000) "
            "are only for access from your machine.",
        )
    if host_value.lower() in DOCKER_CHROMA_HOST_ALIASES:
        return "llmctl-chromadb", port, None
    return host_value, port, None


def create_app() -> Flask:
    app = Flask(__name__, template_folder=str(TEMPLATE_DIR), static_folder=str(STATIC_DIR))
    init_db()
    ensure_integration_defaults(
        "rag",
        {
            "embed_provider": "openai",
            "chat_provider": "openai",
            "openai_embed_model": "text-embedding-3-small",
            "openai_chat_model": "gpt-4o-mini",
            "gemini_embed_model": "models/gemini-embedding-001",
            "gemini_chat_model": "gemini-2.5-flash",
            "chat_temperature": "0.2",
            "openai_chat_temperature": "0.2",
            "chat_response_style": "high",
            "chat_top_k": "5",
            "chat_max_history": "8",
            "chat_max_context_chars": "12000",
            "chat_snippet_chars": "600",
            "chat_context_budget_tokens": "8000",
            "chroma_host": "llmctl-chromadb",
            "chroma_port": "8000",
            "web_port": "5050",
        },
    )

    @app.context_processor
    def _template_helpers() -> dict[str, Any]:
        return {
            "format_source_time": _format_source_time,
            "source_schedule_text": _source_schedule_text,
        }

    @app.get("/")
    def index() -> str:
        config = load_config()
        github_settings = load_integration_settings("github")
        google_drive_settings = load_integration_settings("google_workspace")
        rag_settings = load_integration_settings("rag")
        active_view = request.args.get("view", "chat").strip().lower()
        if active_view not in {"chat", "settings"}:
            active_view = "chat"
        active_nav = active_view
        notice = request.args.get("notice", "").strip().lower()
        settings_notice = None
        if notice == "github_saved":
            settings_notice = {"type": "success", "message": "GitHub settings updated."}
        elif notice == "rag_saved":
            settings_notice = {
                "type": "success",
                "message": "RAG settings updated.",
            }
        elif notice == "github_error":
            settings_notice = {
                "type": "error",
                "message": "GitHub SSH key upload failed.",
            }
        elif notice == "google_drive_saved":
            settings_notice = {
                "type": "success",
                "message": "Google Workspace settings updated.",
            }
        elif notice == "google_drive_error":
            settings_notice = {
                "type": "error",
                "message": "Google Workspace settings update failed.",
            }
        chroma_host = rag_settings.get("chroma_host") or config.chroma_host
        chroma_port = rag_settings.get("chroma_port") or config.chroma_port
        embed_provider = normalize_provider(
            rag_settings.get("embed_provider")
            or config.embed_provider
            or get_embedding_provider(config),
            "openai",
        )
        chat_provider = normalize_provider(
            rag_settings.get("chat_provider")
            or config.chat_provider
            or get_chat_provider(config),
            "openai",
        )
        openai_api_key = rag_settings.get("openai_api_key") or (config.openai_api_key or "")
        gemini_api_key = rag_settings.get("gemini_api_key") or (config.gemini_api_key or "")
        openai_embed_model = (
            rag_settings.get("openai_embed_model") or config.openai_embedding_model
        )
        gemini_embed_model = (
            rag_settings.get("gemini_embed_model") or config.gemini_embedding_model
        )
        openai_chat_model = (
            rag_settings.get("openai_chat_model") or config.openai_chat_model
        )
        gemini_chat_model = (
            rag_settings.get("gemini_chat_model") or config.gemini_chat_model
        )
        chat_temperature = (
            rag_settings.get("chat_temperature")
            or rag_settings.get("openai_chat_temperature")
            or config.chat_temperature
        )
        chat_response_style = _normalize_chat_response_style(
            rag_settings.get("chat_response_style") or config.chat_response_style,
            "high",
        )
        missing_api_key = _missing_api_key_for_active_providers(config)
        chat_top_k = rag_settings.get("chat_top_k") or config.chat_top_k
        chat_max_history = rag_settings.get("chat_max_history") or config.chat_max_history
        chat_max_context_chars = (
            rag_settings.get("chat_max_context_chars") or config.chat_max_context_chars
        )
        chat_snippet_chars = (
            rag_settings.get("chat_snippet_chars") or config.chat_snippet_chars
        )
        chat_context_budget_tokens = (
            rag_settings.get("chat_context_budget_tokens")
            or config.chat_context_budget_tokens
        )
        web_port = rag_settings.get("web_port") or config.web_port
        service_account_json = (
            google_drive_settings.get("service_account_json") or ""
        )
        google_drive_connected = bool(service_account_json.strip())
        google_drive_service_email = None
        if google_drive_connected:
            try:
                google_drive_service_email = service_account_email(
                    service_account_json
                )
            except ValueError:
                google_drive_connected = False
        return render_template(
            "index.html",
            default_top_k=config.chat_top_k,
            missing_api_key=missing_api_key,
            github_settings=github_settings,
            github_connected=bool(
                (github_settings.get("pat") or "").strip()
                or (github_settings.get("ssh_key_path") or "").strip()
            ),
            google_drive_settings=google_drive_settings,
            google_drive_connected=google_drive_connected,
            google_drive_service_email=google_drive_service_email,
            rag_settings=rag_settings,
            chroma_host=chroma_host,
            chroma_port=chroma_port,
            embed_provider=embed_provider,
            chat_provider=chat_provider,
            openai_api_key=openai_api_key,
            gemini_api_key=gemini_api_key,
            openai_embed_model=openai_embed_model,
            gemini_embed_model=gemini_embed_model,
            openai_chat_model=openai_chat_model,
            gemini_chat_model=gemini_chat_model,
            chat_temperature=chat_temperature,
            chat_response_style=chat_response_style,
            chat_top_k=chat_top_k,
            chat_max_history=chat_max_history,
            chat_max_context_chars=chat_max_context_chars,
            chat_snippet_chars=chat_snippet_chars,
            chat_context_budget_tokens=chat_context_budget_tokens,
            web_port=web_port,
            active_view=active_view,
            active_nav=active_nav,
            settings_notice=settings_notice,
        )

    @app.get("/sources")
    def sources_index() -> str:
        sources = list_sources()
        page = _parse_page(request.args.get("page"))
        per_page = _parse_page_size(request.args.get("per_page"))
        paged_sources, total_sources, page, total_pages, pagination_items = _paginate_rows(
            sources,
            page=page,
            per_page=per_page,
        )
        tasks = list_tasks(limit=1000)
        latest_status_by_source: dict[int, str] = {}
        for task in tasks:
            source_ref = getattr(task, "source_id", None)
            if task.kind != TASK_KIND_INDEX or source_ref is None:
                continue
            if source_ref in latest_status_by_source:
                continue
            latest_status_by_source[source_ref] = task.status
        source_active_ids = {
            source_ref
            for source_ref, status in latest_status_by_source.items()
            if status in TASK_ACTIVE_STATUSES
        }
        source_resumable_ids = {
            source_ref
            for source_ref, status in latest_status_by_source.items()
            if status == TASK_STATUS_PAUSED
        }
        notice = request.args.get("notice", "").strip().lower()
        sources_notice = None
        if notice == "source_saved":
            sources_notice = {"type": "success", "message": "Source added."}
        elif notice == "source_deleted":
            sources_notice = {"type": "success", "message": "Source deleted."}
        elif notice == "source_error":
            sources_notice = {"type": "error", "message": "Source update failed."}
        return render_template(
            "sources.html",
            sources=paged_sources,
            sources_notice=sources_notice,
            source_active_ids=source_active_ids,
            source_resumable_ids=source_resumable_ids,
            page=page,
            per_page=per_page,
            per_page_options=PAGINATION_PAGE_SIZES,
            total_sources=total_sources,
            total_pages=total_pages,
            pagination_items=pagination_items,
            active_nav="sources",
        )

    @app.get("/sources/new")
    def sources_new() -> str:
        github_settings = load_integration_settings("github")
        google_drive_settings = load_integration_settings("google_workspace")
        service_account_json = (
            google_drive_settings.get("service_account_json") or ""
        )
        return render_template(
            "source_new.html",
            github_connected=bool((github_settings.get("pat") or "").strip()),
            google_drive_connected=bool(service_account_json.strip()),
            active_nav="sources",
        )

    @app.get("/collections")
    def collections_index() -> str:
        config = load_config()
        sources = list_sources()
        source_by_collection = {source.collection: source for source in sources}
        notice = request.args.get("notice", "").strip().lower()
        collections_notice = None
        if notice == "collection_deleted":
            collections_notice = {"type": "success", "message": "Collection deleted."}
        elif notice == "collection_error":
            collections_notice = {
                "type": "error",
                "message": "Collection operation failed.",
            }

        collections: list[dict[str, Any]] = []
        chroma_error = None
        try:
            client = chromadb.HttpClient(host=config.chroma_host, port=config.chroma_port)
            collection_names = _list_collection_names(client.list_collections())
            for collection_name in collection_names:
                source = source_by_collection.get(collection_name)
                count: int | None = None
                metadata: dict[str, Any] = {}
                try:
                    collection = client.get_collection(name=collection_name)
                    count = collection.count()
                    raw_metadata = getattr(collection, "metadata", None)
                    if isinstance(raw_metadata, dict):
                        metadata = raw_metadata
                except Exception:
                    pass
                collections.append(
                    {
                        "name": collection_name,
                        "source": source,
                        "count": count,
                        "metadata_preview": (
                            json.dumps(metadata, sort_keys=True) if metadata else "{}"
                        ),
                    }
                )
        except Exception as exc:
            chroma_error = str(exc)

        page = _parse_page(request.args.get("page"))
        per_page = _parse_page_size(request.args.get("per_page"))
        (
            paged_collections,
            total_collections,
            page,
            total_pages,
            pagination_items,
        ) = _paginate_rows(collections, page=page, per_page=per_page)

        return render_template(
            "collections.html",
            collections=paged_collections,
            collections_notice=collections_notice,
            chroma_error=chroma_error,
            chroma_host=config.chroma_host,
            chroma_port=config.chroma_port,
            page=page,
            per_page=per_page,
            per_page_options=PAGINATION_PAGE_SIZES,
            total_collections=total_collections,
            total_pages=total_pages,
            pagination_items=pagination_items,
            active_nav="collections",
        )

    @app.get("/collections/detail")
    def collections_detail() -> str:
        collection_name = str(request.args.get("name", "")).strip()
        if not collection_name:
            return redirect(url_for("collections_index", notice="collection_error"))
        config = load_config()
        source = None
        for item in list_sources():
            if item.collection == collection_name:
                source = item
                break

        try:
            client = chromadb.HttpClient(host=config.chroma_host, port=config.chroma_port)
            collection = client.get_collection(name=collection_name)
            count = collection.count()
            raw_metadata = getattr(collection, "metadata", None)
            metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        except Exception:
            return redirect(url_for("collections_index", notice="collection_error"))

        notice = request.args.get("notice", "").strip().lower()
        collection_notice = None
        if notice == "collection_error":
            collection_notice = {
                "type": "error",
                "message": "Collection operation failed.",
            }

        return render_template(
            "collection_detail.html",
            collection_name=collection_name,
            collection_count=count,
            collection_metadata=metadata,
            collection_metadata_json=json.dumps(metadata, sort_keys=True, indent=2)
            if metadata
            else "{}",
            source=source,
            collection_notice=collection_notice,
            active_nav="collections",
        )

    @app.get("/sources/<int:source_id>")
    def sources_detail(source_id: int) -> str:
        source = get_source(source_id)
        if not source:
            return redirect(url_for("sources_index", notice="source_error"))
        active_index_task = active_task(kind=TASK_KIND_INDEX, source_id=source.id)
        latest_index_task = latest_task(kind=TASK_KIND_INDEX, source_id=source.id)
        notice = request.args.get("notice", "").strip().lower()
        source_notice = None
        if notice == "source_collection_cleared":
            source_notice = {
                "type": "success",
                "message": "Collection data cleared for this source.",
            }
        elif notice == "source_busy":
            source_notice = {
                "type": "error",
                "message": "An index task is active. Wait for it to finish before clearing.",
            }
        elif notice == "source_resume_pending":
            source_notice = {
                "type": "error",
                "message": "A paused index exists. Resume it or delete the task before clearing.",
            }
        elif notice == "source_clear_error":
            source_notice = {
                "type": "error",
                "message": "Failed to clear collection data.",
            }
        file_types = []
        if source.indexed_file_types:
            try:
                payload = json.loads(source.indexed_file_types)
                if isinstance(payload, dict):
                    for key, value in payload.items():
                        if value:
                            file_types.append({"type": key, "count": value})
            except json.JSONDecodeError:
                file_types = []
        file_types.sort(key=lambda item: (-item["count"], item["type"]))
        return render_template(
            "source_detail.html",
            source=source,
            file_types=file_types,
            source_notice=source_notice,
            source_is_active=active_index_task is not None,
            source_can_resume=(
                latest_index_task is not None
                and latest_index_task.status == TASK_STATUS_PAUSED
                and active_index_task is None
            ),
            active_nav="sources",
        )

    @app.get("/sources/<int:source_id>/edit")
    def sources_edit(source_id: int) -> str:
        source = get_source(source_id)
        if not source:
            return redirect(url_for("sources_index", notice="source_error"))
        github_settings = load_integration_settings("github")
        google_drive_settings = load_integration_settings("google_workspace")
        service_account_json = (
            google_drive_settings.get("service_account_json") or ""
        )
        notice = request.args.get("notice", "").strip().lower()
        source_notice = None
        if notice == "source_error":
            source_notice = {
                "type": "error",
                "message": "Source update failed.",
            }
        return render_template(
            "source_edit.html",
            source=source,
            github_connected=bool((github_settings.get("pat") or "").strip()),
            google_drive_connected=bool(service_account_json.strip()),
            source_notice=source_notice,
            active_nav="sources",
        )

    @app.get("/tasks")
    def tasks_index() -> str:
        tasks = list_tasks(limit=None)
        page = _parse_page(request.args.get("page"))
        per_page = _parse_page_size(request.args.get("per_page"))
        paged_tasks, total_tasks, page, total_pages, pagination_items = _paginate_rows(
            tasks,
            page=page,
            per_page=per_page,
        )
        sources = list_sources()
        sources_by_id = {source.id: source for source in sources}
        notice = request.args.get("notice", "").strip().lower()
        tasks_notice = None
        if notice == "task_deleted":
            tasks_notice = {"type": "success", "message": "Task deleted."}
        elif notice == "task_cancelled":
            tasks_notice = {"type": "success", "message": "Task cancelled."}
        elif notice == "task_pause_requested":
            tasks_notice = {"type": "success", "message": "Task pause requested."}
        elif notice == "task_paused":
            tasks_notice = {"type": "success", "message": "Task paused."}
        elif notice == "task_resumed":
            tasks_notice = {"type": "success", "message": "Task resumed."}
        elif notice == "task_not_active":
            tasks_notice = {"type": "error", "message": "Task is no longer active."}
        elif notice == "task_not_paused":
            tasks_notice = {"type": "error", "message": "Task is not paused."}
        elif notice == "task_busy":
            tasks_notice = {
                "type": "error",
                "message": "An index task is already active for this source.",
            }
        elif notice == "task_resume_failed":
            tasks_notice = {"type": "error", "message": "Failed to resume task."}
        return render_template(
            "tasks.html",
            tasks=paged_tasks,
            sources_by_id=sources_by_id,
            tasks_notice=tasks_notice,
            page=page,
            per_page=per_page,
            per_page_options=PAGINATION_PAGE_SIZES,
            total_tasks=total_tasks,
            total_pages=total_pages,
            pagination_items=pagination_items,
            active_nav="tasks",
            task_kind_label=_task_kind_label,
        )

    @app.get("/tasks/<int:task_id>")
    def task_detail(task_id: int) -> str:
        task = get_task(task_id)
        if not task:
            return redirect(url_for("tasks_index"))
        source = get_source(task.source_id) if task.source_id else None
        meta = task_meta(task)
        index_mode = _normalize_index_mode(meta.get("index_mode"))
        task_progress = _task_progress_payload(task, meta=meta)
        notice = request.args.get("notice", "").strip().lower()
        task_notice = None
        if notice == "task_cancelled":
            task_notice = {"type": "success", "message": "Task cancelled."}
        elif notice == "task_pause_requested":
            task_notice = {"type": "success", "message": "Task pause requested."}
        elif notice == "task_paused":
            task_notice = {"type": "success", "message": "Task paused."}
        elif notice == "task_resumed":
            task_notice = {"type": "success", "message": "Task resumed."}
        elif notice == "task_not_active":
            task_notice = {"type": "error", "message": "Task is no longer active."}
        elif notice == "task_not_paused":
            task_notice = {"type": "error", "message": "Task is not paused."}
        elif notice == "task_busy":
            task_notice = {
                "type": "error",
                "message": "An index task is already active for this source.",
            }
        elif notice == "task_resume_failed":
            task_notice = {"type": "error", "message": "Failed to resume task."}
        return render_template(
            "task_detail.html",
            task=task,
            source=source,
            meta=meta,
            index_mode=index_mode,
            task_progress=task_progress,
            task_notice=task_notice,
            active_nav="tasks",
            task_kind_label=_task_kind_label,
        )

    @app.get("/tasks/<int:task_id>/status")
    def task_status(task_id: int) -> tuple[Any, int]:
        task = get_task(task_id)
        if not task:
            return jsonify({"error": "Task not found."}), 404
        return jsonify(_task_payload(task)), 200

    @app.get("/api/tasks/status")
    def tasks_status() -> tuple[Any, int]:
        raw_ids = request.args.get("ids", "")
        task_ids = []
        seen = set()
        for value in raw_ids.split(","):
            value = value.strip()
            if not value:
                continue
            try:
                task_id = int(value)
            except ValueError:
                continue
            if task_id in seen:
                continue
            seen.add(task_id)
            task_ids.append(task_id)
        if not task_ids:
            return jsonify({"tasks": []}), 200
        tasks = get_tasks(task_ids)
        payloads = [_task_payload(task) for task in tasks]
        return jsonify({"tasks": payloads}), 200

    @app.post("/tasks/<int:task_id>/delete")
    def remove_task(task_id: int):
        delete_task(task_id)
        return redirect(url_for("tasks_index", notice="task_deleted"))

    @app.post("/tasks/<int:task_id>/cancel")
    def stop_task(task_id: int):
        next_page = request.form.get("next", "").strip().lower()
        task = get_task(task_id)
        if not task or task.status not in TASK_ACTIVE_STATUSES:
            notice = "task_not_active"
        else:
            celery_task_id = (task.celery_task_id or "").strip()
            if celery_task_id:
                try:
                    run_index_task.AsyncResult(celery_task_id).revoke(
                        terminate=True, signal="SIGTERM"
                    )
                except Exception:
                    pass
            updated = cancel_task(task_id)
            notice = "task_cancelled"
            if not updated or updated.status in TASK_ACTIVE_STATUSES:
                notice = "task_not_active"
        if next_page == "detail" and task:
            return redirect(url_for("task_detail", task_id=task_id, notice=notice))
        return redirect(url_for("tasks_index", notice=notice))

    @app.post("/tasks/<int:task_id>/pause")
    def pause_index_task(task_id: int):
        next_page = request.form.get("next", "").strip().lower()
        task = get_task(task_id)
        if not task or task.status not in TASK_ACTIVE_STATUSES:
            notice = "task_not_active"
        else:
            celery_task_id = (task.celery_task_id or "").strip()
            if task.status == TASK_STATUS_QUEUED and celery_task_id:
                try:
                    run_index_task.AsyncResult(celery_task_id).revoke(terminate=False)
                except Exception:
                    pass
            updated = pause_task(task_id)
            if not updated:
                notice = "task_not_active"
            elif updated.status == TASK_STATUS_PAUSED:
                notice = "task_paused"
            else:
                notice = "task_pause_requested"
        if next_page == "detail" and task:
            return redirect(url_for("task_detail", task_id=task_id, notice=notice))
        return redirect(url_for("tasks_index", notice=notice))

    @app.post("/tasks/<int:task_id>/resume")
    def resume_index_task(task_id: int):
        next_page = request.form.get("next", "").strip().lower()
        task = get_task(task_id)
        if not task or task.status != TASK_STATUS_PAUSED:
            notice = "task_not_paused"
        elif task.source_id is None and has_active_task(kind=TASK_KIND_INDEX):
            notice = "task_busy"
        elif task.source_id is not None and has_active_task(
            kind=TASK_KIND_INDEX, source_id=task.source_id
        ):
            notice = "task_busy"
        else:
            meta = task_meta(task)
            reset = bool(meta.get("reset"))
            index_mode = _normalize_index_mode(meta.get("index_mode"))
            source_ref = task.source_id
            updated = resume_task(task_id)
            if not updated or updated.status != TASK_STATUS_QUEUED:
                notice = "task_not_paused"
            else:
                started = _enqueue_index_task(task_id, source_ref, reset, index_mode)
                notice = "task_resumed" if started else "task_resume_failed"
        if next_page == "detail" and task:
            return redirect(url_for("task_detail", task_id=task_id, notice=notice))
        return redirect(url_for("tasks_index", notice=notice))

    @app.post("/settings/github")
    def update_github_settings():
        pat = request.form.get("github_pat", "").strip()
        current_settings = load_integration_settings("github")
        existing_key_path = (current_settings.get("ssh_key_path") or "").strip()
        uploaded_key = request.files.get("github_ssh_key")
        clear_key = request.form.get("github_ssh_key_clear", "").lower() in {
            "1",
            "true",
            "on",
        }
        payload = {"pat": pat}
        if clear_key and existing_key_path:
            existing_path = Path(existing_key_path)
            try:
                if existing_path.is_file() and SSH_KEYS_DIR in existing_path.parents:
                    existing_path.unlink()
            except OSError:
                pass
            payload["ssh_key_path"] = ""
        elif uploaded_key and uploaded_key.filename:
            key_bytes = uploaded_key.read()
            if not key_bytes or len(key_bytes) > 256 * 1024:
                return redirect(
                    url_for("index", view="settings", notice="github_error")
                )
            SSH_KEYS_DIR.mkdir(parents=True, exist_ok=True)
            key_path = SSH_KEYS_DIR / "github_ssh_key.pem"
            try:
                key_path.write_bytes(key_bytes)
                key_path.chmod(0o600)
                payload["ssh_key_path"] = str(key_path)
            except OSError:
                return redirect(
                    url_for("index", view="settings", notice="github_error")
                )
        save_integration_settings("github", payload)
        return redirect(url_for("index", view="settings", notice="github_saved"))

    @app.post("/settings/rag")
    def update_rag_settings():
        chroma_host = request.form.get("chroma_host", "").strip()
        chroma_port = request.form.get("chroma_port", "").strip()
        normalized_chroma_port = _coerce_int_str(chroma_port)
        normalized_chroma_host = chroma_host
        if chroma_host and normalized_chroma_port:
            try:
                fixed_host, fixed_port, _ = _normalize_chroma_target(
                    chroma_host, int(normalized_chroma_port)
                )
                normalized_chroma_host = fixed_host
                normalized_chroma_port = str(fixed_port)
            except (TypeError, ValueError):
                pass
        embed_provider = normalize_provider(
            request.form.get("embed_provider", "").strip(),
            "openai",
        )
        chat_provider = normalize_provider(
            request.form.get("chat_provider", "").strip(),
            "openai",
        )
        openai_api_key = request.form.get("openai_api_key", "").strip()
        gemini_api_key = request.form.get("gemini_api_key", "").strip()
        openai_embed_model = request.form.get("openai_embed_model", "").strip()
        gemini_embed_model = request.form.get("gemini_embed_model", "").strip()
        openai_chat_model = request.form.get("openai_chat_model", "").strip()
        gemini_chat_model = request.form.get("gemini_chat_model", "").strip()
        chat_temperature = (
            request.form.get("chat_temperature", "").strip()
            or request.form.get("openai_chat_temperature", "").strip()
        )
        chat_response_style = _normalize_chat_response_style(
            request.form.get("chat_response_style", "").strip(),
            "high",
        )
        chat_top_k = request.form.get("chat_top_k", "").strip()
        chat_max_history = request.form.get("chat_max_history", "").strip()
        chat_max_context_chars = request.form.get("chat_max_context_chars", "").strip()
        chat_snippet_chars = request.form.get("chat_snippet_chars", "").strip()
        chat_context_budget_tokens = request.form.get(
            "chat_context_budget_tokens", ""
        ).strip()
        web_port = request.form.get("web_port", "").strip()
        payload = {
            "chroma_host": normalized_chroma_host,
            "chroma_port": normalized_chroma_port,
            "embed_provider": embed_provider,
            "chat_provider": chat_provider,
            "openai_api_key": openai_api_key,
            "gemini_api_key": gemini_api_key,
            "openai_embed_model": openai_embed_model,
            "gemini_embed_model": gemini_embed_model,
            "openai_chat_model": openai_chat_model,
            "gemini_chat_model": gemini_chat_model,
            "chat_temperature": _coerce_float_str(chat_temperature),
            "openai_chat_temperature": _coerce_float_str(chat_temperature),
            "chat_response_style": chat_response_style,
            "chat_top_k": _coerce_int_str(chat_top_k),
            "chat_max_history": _coerce_int_str(chat_max_history),
            "chat_max_context_chars": _coerce_int_str(chat_max_context_chars),
            "chat_snippet_chars": _coerce_int_str(chat_snippet_chars),
            "chat_context_budget_tokens": _coerce_int_str(
                chat_context_budget_tokens
            ),
            "web_port": _coerce_int_str(web_port),
        }
        save_integration_settings("rag", payload)
        return redirect(url_for("index", view="settings", notice="rag_saved"))

    @app.post("/settings/google-drive")
    def update_google_drive_settings():
        service_account_json = request.form.get("google_drive_service_account_json", "")
        payload = {"service_account_json": service_account_json}
        try:
            trimmed = service_account_json.strip()
            if trimmed:
                service_account_email(trimmed)
            save_integration_settings("google_workspace", payload)
        except Exception:
            return redirect(
                url_for("index", view="settings", notice="google_drive_error")
            )
        return redirect(
            url_for("index", view="settings", notice="google_drive_saved")
        )

    @app.post("/sources")
    def add_source():
        name = request.form.get("source_name", "").strip()
        kind = request.form.get("source_kind", "").strip().lower()
        local_path = request.form.get("source_local_path", "").strip()
        git_repo = request.form.get("source_git_repo", "").strip()
        git_branch = request.form.get("source_git_branch", "").strip()
        drive_folder_id = request.form.get("source_drive_folder_id", "").strip()
        index_schedule_value = request.form.get("source_index_schedule_value", "").strip()
        index_schedule_unit = request.form.get("source_index_schedule_unit", "").strip()
        try:
            source = create_source(
                SourceInput(
                    name=name,
                    kind=kind,
                    local_path=local_path,
                    git_repo=git_repo,
                    git_branch=git_branch,
                    drive_folder_id=drive_folder_id,
                    index_schedule_value=index_schedule_value,
                    index_schedule_unit=index_schedule_unit,
                )
            )
        except Exception:
            return redirect(url_for("sources_index", notice="source_error"))
        return redirect(url_for("sources_detail", source_id=source.id))

    @app.post("/sources/<int:source_id>")
    def save_source(source_id: int):
        name = request.form.get("source_name", "").strip()
        kind = request.form.get("source_kind", "").strip().lower()
        local_path = request.form.get("source_local_path", "").strip()
        git_repo = request.form.get("source_git_repo", "").strip()
        git_branch = request.form.get("source_git_branch", "").strip()
        drive_folder_id = request.form.get("source_drive_folder_id", "").strip()
        index_schedule_value = request.form.get("source_index_schedule_value", "").strip()
        index_schedule_unit = request.form.get("source_index_schedule_unit", "").strip()
        try:
            source = update_source(
                source_id,
                SourceInput(
                    name=name,
                    kind=kind,
                    local_path=local_path,
                    git_repo=git_repo,
                    git_branch=git_branch,
                    drive_folder_id=drive_folder_id,
                    index_schedule_value=index_schedule_value,
                    index_schedule_unit=index_schedule_unit,
                ),
            )
        except Exception:
            return redirect(
                url_for("sources_edit", source_id=source_id, notice="source_error")
            )
        return redirect(url_for("sources_detail", source_id=source.id))

    @app.post("/sources/<int:source_id>/clear")
    def clear_source_collection(source_id: int):
        source = get_source(source_id)
        if not source:
            return redirect(url_for("sources_index", notice="source_error"))
        if has_active_task(kind=TASK_KIND_INDEX, source_id=source.id):
            return redirect(url_for("sources_detail", source_id=source.id, notice="source_busy"))
        latest_index_task = latest_task(kind=TASK_KIND_INDEX, source_id=source.id)
        if latest_index_task is not None and latest_index_task.status == TASK_STATUS_PAUSED:
            return redirect(
                url_for("sources_detail", source_id=source.id, notice="source_resume_pending")
            )
        try:
            config = load_config()
            client = chromadb.HttpClient(host=config.chroma_host, port=config.chroma_port)
            try:
                client.delete_collection(name=source.collection)
            except Exception:
                pass
            client.get_or_create_collection(
                name=source.collection,
                metadata={"source": "llmctl-rag"},
            )
            update_source_index(
                source.id,
                last_indexed_at=None,
                last_error=None,
                indexed_file_count=0,
                indexed_chunk_count=0,
                indexed_file_types=json.dumps({}),
            )
            delete_source_file_states(source.id)
        except Exception:
            return redirect(url_for("sources_detail", source_id=source.id, notice="source_clear_error"))
        return redirect(
            url_for("sources_detail", source_id=source.id, notice="source_collection_cleared")
        )

    @app.post("/sources/<int:source_id>/delete")
    def remove_source(source_id: int):
        try:
            delete_source(source_id)
        except Exception:
            return redirect(url_for("sources_index", notice="source_error"))
        return redirect(url_for("sources_index", notice="source_deleted"))

    @app.post("/collections/delete")
    def remove_collection():
        collection_name = request.form.get("collection_name", "").strip()
        next_page = request.form.get("next", "").strip().lower()
        if not collection_name:
            if next_page == "detail":
                return redirect(url_for("collections_index", notice="collection_error"))
            return redirect(url_for("collections_index", notice="collection_error"))
        try:
            config = load_config()
            client = chromadb.HttpClient(host=config.chroma_host, port=config.chroma_port)
            client.delete_collection(name=collection_name)
            for source in list_sources():
                if source.collection != collection_name:
                    continue
                update_source_index(
                    source.id,
                    last_indexed_at=None,
                    last_error=None,
                    indexed_file_count=0,
                    indexed_chunk_count=0,
                    indexed_file_types=json.dumps({}),
                )
                delete_source_file_states(source.id)
                break
        except Exception:
            if next_page == "detail":
                return redirect(
                    url_for(
                        "collections_detail",
                        name=collection_name,
                        notice="collection_error",
                    )
                )
            return redirect(url_for("collections_index", notice="collection_error"))
        return redirect(url_for("collections_index", notice="collection_deleted"))

    @app.get("/api/github/repos")
    def github_repos() -> tuple[Any, int]:
        github_settings = load_integration_settings("github")
        pat = (github_settings.get("pat") or "").strip()
        if not pat:
            return jsonify({"error": "GitHub PAT is not configured."}), 400
        try:
            repos = _fetch_github_repos(pat)
        except Exception as exc:
            return jsonify({"error": f"GitHub API error: {exc}"}), 500
        return jsonify({"repos": repos}), 200

    @app.post("/api/google-drive/verify")
    def google_drive_verify() -> tuple[Any, int]:
        payload = request.get_json(silent=True) or {}
        folder_id = str(payload.get("folder_id") or "").strip()
        if not folder_id:
            return jsonify({"ok": False, "error": "Google Drive folder ID is required."}), 400

        service_account_json = str(payload.get("service_account_json") or "").strip()
        if not service_account_json:
            settings = load_integration_settings("google_workspace")
            service_account_json = (settings.get("service_account_json") or "").strip()
        if not service_account_json:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "Google Workspace service account JSON is not configured.",
                    }
                ),
                400,
            )
        try:
            folder = verify_folder_access(service_account_json, folder_id)
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return (
            jsonify(
                {
                    "ok": True,
                    "folder_id": folder.id,
                    "folder_name": folder.name,
                }
            ),
            200,
        )

    @app.get("/api/index")
    def index_status() -> tuple[Any, int]:
        return jsonify(_index_snapshot()), 200

    @app.post("/api/index")
    def index_now() -> tuple[Any, int]:
        payload = request.get_json(silent=True) or {}
        reset = bool(payload.get("reset"))
        index_mode = _normalize_index_mode(payload.get("mode"))
        started = _start_index(reset, source_id=None, index_mode=index_mode)
        status = 202 if started else 409
        data = _index_snapshot()
        data["started"] = started
        return jsonify(data), status

    @app.get("/api/sources/<int:source_id>/index")
    def source_index_status(source_id: int) -> tuple[Any, int]:
        source = get_source(source_id)
        if not source:
            return jsonify({"error": "Source not found."}), 404
        return jsonify(_index_snapshot(source)), 200

    @app.post("/api/sources/<int:source_id>/index")
    def source_index_now(source_id: int) -> tuple[Any, int]:
        source = get_source(source_id)
        if not source:
            return jsonify({"error": "Source not found."}), 404
        payload = request.get_json(silent=True) or {}
        reset = bool(payload.get("reset"))
        index_mode = _normalize_index_mode(payload.get("mode"))
        started = _start_index(reset, source_id=source_id, index_mode=index_mode)
        status = 202 if started else 409
        data = _index_snapshot(source)
        data["started"] = started
        return jsonify(data), status

    @app.post("/api/sources/<int:source_id>/pause")
    def source_pause(source_id: int) -> tuple[Any, int]:
        source = get_source(source_id)
        if not source:
            return jsonify({"error": "Source not found."}), 404
        task = active_task(kind=TASK_KIND_INDEX, source_id=source_id)
        if not task:
            data = _index_snapshot(source)
            data["paused"] = False
            return jsonify(data), 409
        celery_task_id = (task.celery_task_id or "").strip()
        if task.status == TASK_STATUS_QUEUED and celery_task_id:
            try:
                run_index_task.AsyncResult(celery_task_id).revoke(terminate=False)
            except Exception:
                pass
        updated = pause_task(task.id)
        data = _index_snapshot(source)
        data["paused"] = bool(
            updated and updated.status in {TASK_STATUS_PAUSING, TASK_STATUS_PAUSED}
        )
        return jsonify(data), 202

    @app.post("/api/sources/<int:source_id>/resume")
    def source_resume(source_id: int) -> tuple[Any, int]:
        source = get_source(source_id)
        if not source:
            return jsonify({"error": "Source not found."}), 404
        started = _resume_source_index(source_id)
        status = 202 if started else 409
        data = _index_snapshot(source)
        data["started"] = started
        return jsonify(data), status

    @app.post("/api/chat")
    def chat() -> tuple[Any, int]:
        started = time.time()
        payload = request.get_json(silent=True) or {}
        message = str(payload.get("message", "")).strip()
        history = payload.get("history", [])
        config = load_config()
        top_k = _coerce_top_k(payload.get("top_k", config.chat_top_k), config.chat_top_k)
        verbosity = _normalize_chat_response_style(
            str(payload.get("verbosity", "")).strip(),
            config.chat_response_style,
        )

        if not message:
            return jsonify({"error": "Message is required."}), 400

        if not has_chat_api_key(config):
            provider = get_chat_provider(config)
            return jsonify({"error": missing_api_key_message(provider, "Chat")}), 400
        if not has_embedding_api_key(config):
            provider = get_embedding_provider(config)
            return jsonify({"error": missing_api_key_message(provider, "Embedding")}), 400

        sources = list_sources()
        if not sources:
            return jsonify({"error": "No sources configured."}), 400

        try:
            collections = _get_collections(config, sources)
        except Exception as exc:
            return (
                jsonify({"error": f"Failed to load collections: {exc}"}),
                500,
            )

        query_text = _build_query_text(message, history, config.chat_max_history)
        try:
            documents, metadatas = _query_collections(
                query_text, collections, top_k
            )
        except Exception as exc:
            return jsonify({"error": f"Failed to query collections: {exc}"}), 500
        context, sources = _build_context(
            documents,
            metadatas,
            config.chat_max_context_chars,
            config.chat_snippet_chars,
        )

        messages = _build_messages(
            history,
            message,
            context,
            config.chat_max_history,
            verbosity,
        )

        try:
            reply = call_chat_completion(config, messages)
        except Exception as exc:
            provider = get_chat_provider(config)
            return jsonify({"error": f"{provider.title()} request failed: {exc}"}), 500

        response = {
            "reply": reply,
            "sources": sources,
            "provider": get_chat_provider(config),
            "model": get_chat_model(config),
            "top_k": top_k,
            "verbosity": verbosity,
            "elapsed_ms": int((time.time() - started) * 1000),
        }
        return jsonify(response), 200

    @app.get("/api/health")
    def health() -> tuple[Any, int]:
        config = load_config()
        return (
            jsonify(
                {
                    "status": "ok",
                    "collection": config.collection,
                    "chroma_host": config.chroma_host,
                    "chroma_port": config.chroma_port,
                    "embed_provider": get_embedding_provider(config),
                    "chat_provider": get_chat_provider(config),
                }
            ),
            200,
        )

    @app.post("/api/chroma/test")
    def chroma_test() -> tuple[Any, int]:
        payload = request.get_json(silent=True) or {}
        config = load_config()
        host = str(payload.get("host") or "").strip() or config.chroma_host
        port_raw = str(payload.get("port") or "").strip()
        try:
            port = int(port_raw) if port_raw else int(config.chroma_port)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Invalid Chroma port."}), 400
        if port < 1 or port > 65535:
            return jsonify({"ok": False, "error": "Chroma port must be 1-65535."}), 400
        host, port, normalized_hint = _normalize_chroma_target(host, port)
        try:
            client = chromadb.HttpClient(host=host, port=port)
            collections = client.list_collections()
        except Exception as exc:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": f"Failed to connect to Chroma at {host}:{port}: {exc}",
                        "host": host,
                        "port": port,
                        "hint": normalized_hint,
                    }
                ),
                502,
            )
        return (
            jsonify(
                {
                    "ok": True,
                    "host": host,
                    "port": port,
                    "collections_count": len(collections),
                    "hint": normalized_hint,
                }
            ),
            200,
        )

    return app


def _list_collection_names(collections: Any) -> list[str]:
    names: set[str] = set()
    if collections is None:
        return []
    try:
        for item in collections:
            if isinstance(item, str):
                candidate = item.strip()
            else:
                candidate = str(getattr(item, "name", "") or "").strip()
            if candidate:
                names.add(candidate)
    except TypeError:
        return []
    return sorted(names, key=str.lower)


def _task_kind_label(kind: str | None) -> str:
    if not kind:
        return "Task"
    return {"index": "Index"}.get(kind, kind)


def _normalize_index_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    if mode in _INDEX_MODE_VALUES:
        return mode
    return INDEX_MODE_FRESH


def _task_index_mode(task: Any) -> str:
    return _normalize_index_mode(task_meta(task).get("index_mode"))


def _to_nonnegative_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def _to_positive_int(value: Any) -> int | None:
    parsed = _to_nonnegative_int(value)
    if parsed is None or parsed == 0:
        return None
    return parsed


def _parse_page(value: Any) -> int:
    try:
        page = int(value)
    except (TypeError, ValueError):
        return 1
    return page if page > 0 else 1


def _parse_page_size(value: Any) -> int:
    try:
        per_page = int(value)
    except (TypeError, ValueError):
        return PAGINATION_DEFAULT_SIZE
    return per_page if per_page in PAGINATION_PAGE_SIZES else PAGINATION_DEFAULT_SIZE


def _pagination_sequence(current_page: int, total_pages: int) -> list[int | None]:
    if total_pages <= (PAGINATION_WINDOW * 2) + 5:
        return list(range(1, total_pages + 1))

    items: list[int | None] = [1]
    start = max(2, current_page - PAGINATION_WINDOW)
    end = min(total_pages - 1, current_page + PAGINATION_WINDOW)

    if start > 2:
        items.append(None)
    items.extend(range(start, end + 1))
    if end < total_pages - 1:
        items.append(None)
    items.append(total_pages)
    return items


def _build_pagination_items(page: int, total_pages: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for value in _pagination_sequence(page, total_pages):
        if value is None:
            items.append({"type": "gap"})
        else:
            items.append({"type": "page", "page": value})
    return items


def _paginate_rows(
    rows: list[Any], *, page: int, per_page: int
) -> tuple[list[Any], int, int, int, list[dict[str, Any]]]:
    total_count = len(rows)
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    normalized_page = min(page, total_pages)
    start = (normalized_page - 1) * per_page
    end = start + per_page
    paged_rows = rows[start:end]
    pagination_items = _build_pagination_items(normalized_page, total_pages)
    return paged_rows, total_count, normalized_page, total_pages, pagination_items


def _task_progress_payload(
    task: Any, *, meta: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    payload_meta = meta if isinstance(meta, dict) else task_meta(task)
    progress = payload_meta.get("progress")
    if not isinstance(progress, dict):
        return None

    source_total = _to_positive_int(progress.get("source_total"))
    source_index = _to_positive_int(progress.get("source_index"))
    source_name = str(progress.get("source_name") or "").strip() or None
    source_kind = str(progress.get("source_kind") or "").strip() or None

    phase = str(progress.get("phase") or "").strip().lower() or None
    if phase not in {"preparing", "syncing", "indexing", "complete"}:
        phase = None

    file_index = _to_positive_int(progress.get("file_index"))
    files_total = _to_nonnegative_int(progress.get("files_total"))
    files_completed = _to_nonnegative_int(progress.get("files_completed"))
    current_file_path = str(progress.get("current_file_path") or "").strip() or None

    current_file_chunks_embedded = _to_nonnegative_int(
        progress.get("current_file_chunks_embedded")
    )
    current_file_chunks_total = _to_nonnegative_int(
        progress.get("current_file_chunks_total")
    )

    drive_files_seen = _to_nonnegative_int(progress.get("drive_files_seen"))
    drive_files_total = _to_nonnegative_int(progress.get("drive_files_total"))

    has_detail = any(
        value is not None
        for value in [
            source_total,
            source_index,
            source_name,
            phase,
            file_index,
            files_total,
            files_completed,
            current_file_path,
            current_file_chunks_embedded,
            current_file_chunks_total,
            drive_files_seen,
            drive_files_total,
        ]
    )
    if not has_detail:
        return None

    source_label = None
    if source_index and source_total:
        source_label = (
            f"Source {source_index}/{source_total} ({source_name})"
            if source_name
            else f"Source {source_index}/{source_total}"
        )
    elif source_name:
        source_label = source_name

    file_label = None
    if file_index and files_total is not None:
        file_label = f"File {file_index}/{files_total}"
    elif files_total is not None and files_completed is not None:
        file_label = f"Files {files_completed}/{files_total}"
    elif files_completed is not None:
        file_label = f"Files completed: {files_completed}"

    chunk_label = None
    if (
        current_file_chunks_total is not None
        and current_file_chunks_embedded is not None
    ):
        chunk_label = (
            f"Chunks {current_file_chunks_embedded}/{current_file_chunks_total}"
        )
    elif current_file_chunks_embedded is not None:
        chunk_label = f"Chunks {current_file_chunks_embedded}"

    summary_parts: list[str] = []
    if source_label:
        summary_parts.append(source_label)
    if phase and phase != "complete":
        summary_parts.append(phase)
    if file_label:
        summary_parts.append(file_label)
    if chunk_label:
        summary_parts.append(chunk_label)
    if current_file_path:
        summary_parts.append(current_file_path)
    summary = " | ".join(summary_parts) if summary_parts else None

    return {
        "source_total": source_total,
        "source_index": source_index,
        "source_name": source_name,
        "source_kind": source_kind,
        "source_label": source_label,
        "phase": phase,
        "file_index": file_index,
        "files_total": files_total,
        "files_completed": files_completed,
        "file_label": file_label,
        "current_file_path": current_file_path,
        "current_file_chunks_embedded": current_file_chunks_embedded,
        "current_file_chunks_total": current_file_chunks_total,
        "chunk_label": chunk_label,
        "drive_files_seen": drive_files_seen,
        "drive_files_total": drive_files_total,
        "summary": summary,
    }


def _task_payload(task) -> dict[str, Any]:
    return {
        "id": task.id,
        "kind": task.kind,
        "index_mode": _task_index_mode(task),
        "status": task.status,
        "running": task.status in TASK_ACTIVE_STATUSES,
        "source_id": task.source_id,
        "created_at": format_dt(task.created_at),
        "started_at": format_dt(task.started_at),
        "finished_at": format_dt(task.finished_at),
        "celery_task_id": task.celery_task_id,
        "output": task.output or "",
        "error": task.error or "",
        "progress": _task_progress_payload(task),
    }


def _index_snapshot(source=None) -> dict[str, Any]:
    if not source:
        active_tasks = list_active_tasks(kind=TASK_KIND_INDEX)
        if active_tasks:
            active = active_tasks[0]
            progress = _task_progress_payload(active)
            active_source_ids = [task.source_id for task in active_tasks if task.source_id]
            mode = "all" if len(active_tasks) > 1 else ("source" if active.source_id else "all")
            return {
                "running": True,
                "status": active.status,
                "index_mode": _task_index_mode(active),
                "source_id": active.source_id,
                "mode": mode,
                "active_count": len(active_tasks),
                "active_task_ids": [task.id for task in active_tasks],
                "active_source_ids": active_source_ids,
                "last_started_at": format_dt(active.started_at or active.created_at),
                "last_finished_at": None,
                "last_error": None,
                "can_resume": False,
                "paused_task_id": None,
                "progress": progress,
            }
        latest = latest_task(kind=TASK_KIND_INDEX)
        if latest:
            progress = _task_progress_payload(latest)
            return {
                "running": False,
                "status": latest.status,
                "index_mode": _task_index_mode(latest),
                "source_id": latest.source_id,
                "mode": "source" if latest.source_id else "all",
                "last_started_at": format_dt(latest.started_at),
                "last_finished_at": format_dt(latest.finished_at),
                "last_error": latest.error,
                "can_resume": latest.status == TASK_STATUS_PAUSED,
                "paused_task_id": (
                    latest.id if latest.status == TASK_STATUS_PAUSED else None
                ),
                "progress": progress,
            }
        finished = latest_finished_task(kind=TASK_KIND_INDEX)
        return {
            "running": False,
            "status": finished.status if finished else None,
            "index_mode": _task_index_mode(finished) if finished else None,
            "source_id": finished.source_id if finished else None,
            "mode": "source" if (finished and finished.source_id) else None,
            "last_started_at": format_dt(finished.started_at) if finished else None,
            "last_finished_at": format_dt(finished.finished_at) if finished else None,
            "last_error": finished.error if finished else None,
            "can_resume": False,
            "paused_task_id": None,
            "progress": _task_progress_payload(finished) if finished else None,
        }

    active = active_task(kind=TASK_KIND_INDEX, source_id=source.id)
    if active:
        progress = _task_progress_payload(active)
        return {
            "running": True,
            "status": active.status,
            "index_mode": _task_index_mode(active),
            "source_id": source.id,
            "mode": "source",
            "last_started_at": format_dt(active.started_at or active.created_at),
            "last_finished_at": None,
            "last_error": None,
            "last_indexed_at": _isoformat_datetime(
                getattr(source, "last_indexed_at", None)
            ),
            "can_resume": False,
            "paused_task_id": None,
            "progress": progress,
            **_source_schedule_payload(source),
        }

    latest = latest_task(kind=TASK_KIND_INDEX, source_id=source.id)
    if latest and latest.status == TASK_STATUS_PAUSED:
        progress = _task_progress_payload(latest)
        return {
            "running": False,
            "status": latest.status,
            "index_mode": _task_index_mode(latest),
            "source_id": source.id,
            "mode": "source",
            "last_started_at": format_dt(latest.started_at),
            "last_finished_at": format_dt(latest.finished_at),
            "last_error": None,
            "last_indexed_at": _isoformat_datetime(
                getattr(source, "last_indexed_at", None)
            ),
            "can_resume": True,
            "paused_task_id": latest.id,
            "progress": progress,
            **_source_schedule_payload(source),
        }

    return {
        "running": False,
        "status": latest.status if latest else None,
        "index_mode": _task_index_mode(latest) if latest else None,
        "source_id": source.id,
        "mode": "source",
        "last_started_at": format_dt(latest.started_at) if latest else None,
        "last_finished_at": format_dt(latest.finished_at) if latest else None,
        "last_error": getattr(source, "last_error", None),
        "last_indexed_at": _isoformat_datetime(
            getattr(source, "last_indexed_at", None)
        ),
        "can_resume": False,
        "paused_task_id": None,
        "progress": _task_progress_payload(latest) if latest else None,
        **_source_schedule_payload(source),
    }


def _enqueue_index_task(
    task_id: int, source_id: int | None, reset: bool, index_mode: str
) -> bool:
    queue_name = _index_queue_for_source(source_id)
    try:
        result = run_index_task.apply_async(
            args=[task_id, source_id, reset, _normalize_index_mode(index_mode)],
            ignore_result=True,
            queue=queue_name,
        )
    except Exception as exc:
        mark_task_finished(
            task_id,
            status=TASK_STATUS_FAILED,
            output="Failed to enqueue task.",
            error=str(exc),
        )
        return False
    if result is not None:
        set_task_celery_id(task_id, getattr(result, "id", None))
    return True


def _start_index(reset: bool, source_id: int | None, index_mode: str) -> bool:
    normalized_mode = _normalize_index_mode(index_mode)
    if source_id is not None:
        if _source_has_incomplete_index_task(source_id):
            return False
        meta = {
            "reset": bool(reset),
            "index_mode": normalized_mode,
            "source_id": source_id,
            "source_order": [source_id],
        }
        task = create_task(kind=TASK_KIND_INDEX, source_id=source_id, meta=meta)
        return _enqueue_index_task(task.id, source_id, reset, normalized_mode)

    started = False
    for source in list_sources():
        if _source_has_incomplete_index_task(source.id):
            continue
        meta = {
            "reset": bool(reset),
            "index_mode": normalized_mode,
            "source_id": source.id,
            "source_order": [source.id],
        }
        task = create_task(kind=TASK_KIND_INDEX, source_id=source.id, meta=meta)
        if _enqueue_index_task(task.id, source.id, reset, normalized_mode):
            started = True
    return started


def _resume_source_index(source_id: int) -> bool:
    if has_active_task(kind=TASK_KIND_INDEX, source_id=source_id):
        return False
    task = latest_task(kind=TASK_KIND_INDEX, source_id=source_id)
    if not task or task.status != TASK_STATUS_PAUSED:
        return False
    meta = task_meta(task)
    reset = bool(meta.get("reset"))
    index_mode = _normalize_index_mode(meta.get("index_mode"))
    updated = resume_task(task.id)
    if not updated or updated.status != TASK_STATUS_QUEUED:
        return False
    return _enqueue_index_task(updated.id, updated.source_id, reset, index_mode)


def _index_queue_for_source(source_id: int | None) -> str:
    if source_id is None:
        return "llmctl_rag_index"
    source = get_source(source_id)
    kind = (getattr(source, "kind", "") or "").strip().lower()
    if kind == "google_drive":
        return "llmctl_rag_drive"
    if kind == "github":
        return "llmctl_rag_git"
    return "llmctl_rag_index"


def _source_has_incomplete_index_task(source_id: int) -> bool:
    latest = latest_task(kind=TASK_KIND_INDEX, source_id=source_id)
    if not latest:
        return False
    return latest.status in _INCOMPLETE_INDEX_STATUSES


def _coerce_datetime_utc(value: datetime | None) -> datetime | None:
    if not value:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _isoformat_datetime(value: datetime | None) -> str | None:
    dt = _coerce_datetime_utc(value)
    return dt.isoformat() if dt else None


def _format_source_time(value: datetime | None) -> str:
    dt = _coerce_datetime_utc(value)
    if not dt:
        return "-"
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _source_schedule_text(source: Any) -> str:
    raw_value = getattr(source, "index_schedule_value", None)
    raw_unit = str(getattr(source, "index_schedule_unit", "") or "").strip().lower()
    try:
        schedule_value = int(raw_value) if raw_value is not None else 0
    except (TypeError, ValueError):
        schedule_value = 0
    if schedule_value <= 0 or raw_unit not in SCHEDULE_UNITS:
        return "Not scheduled"
    unit = raw_unit[:-1] if schedule_value == 1 and raw_unit.endswith("s") else raw_unit
    return f"Every {schedule_value} {unit}"


def _source_schedule_payload(source: Any) -> dict[str, Any]:
    return {
        "schedule_value": getattr(source, "index_schedule_value", None),
        "schedule_unit": getattr(source, "index_schedule_unit", None),
        "next_index_at": _isoformat_datetime(getattr(source, "next_index_at", None)),
    }


def _source_scheduler_enabled() -> bool:
    value = (os.getenv("LLMCTL_RAG_SOURCE_SCHEDULER", "true") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _source_scheduler_poll_seconds() -> float:
    raw = (os.getenv("LLMCTL_RAG_SOURCE_SCHEDULER_POLL_SECONDS", "15") or "").strip()
    try:
        parsed = float(raw)
    except ValueError:
        return 15.0
    return max(5.0, parsed)


def start_source_scheduler() -> None:
    global _SOURCE_SCHEDULER_THREAD
    if not _source_scheduler_enabled():
        return
    with _SOURCE_SCHEDULER_LOCK:
        if _SOURCE_SCHEDULER_THREAD and _SOURCE_SCHEDULER_THREAD.is_alive():
            return
        _SOURCE_SCHEDULER_STOP.clear()
        thread = threading.Thread(
            target=_source_scheduler_loop,
            name="llmctl-rag-source-scheduler",
            daemon=True,
        )
        _SOURCE_SCHEDULER_THREAD = thread
        thread.start()


def stop_source_scheduler(timeout: float = 2.0) -> None:
    global _SOURCE_SCHEDULER_THREAD
    with _SOURCE_SCHEDULER_LOCK:
        thread = _SOURCE_SCHEDULER_THREAD
        if not thread:
            return
        _SOURCE_SCHEDULER_STOP.set()
    thread.join(timeout=timeout)
    with _SOURCE_SCHEDULER_LOCK:
        if _SOURCE_SCHEDULER_THREAD is thread:
            _SOURCE_SCHEDULER_THREAD = None
        _SOURCE_SCHEDULER_STOP.clear()


def _source_scheduler_loop() -> None:
    poll_seconds = _source_scheduler_poll_seconds()
    while not _SOURCE_SCHEDULER_STOP.is_set():
        try:
            _run_scheduled_source_indexes()
        except Exception:
            pass
        _SOURCE_SCHEDULER_STOP.wait(poll_seconds)


def _source_due_for_schedule(source: Any, now: datetime) -> bool:
    raw_value = getattr(source, "index_schedule_value", None)
    raw_unit = str(getattr(source, "index_schedule_unit", "") or "").strip().lower()
    try:
        schedule_value = int(raw_value) if raw_value is not None else 0
    except (TypeError, ValueError):
        return False
    if schedule_value <= 0 or raw_unit not in SCHEDULE_UNITS:
        return False
    next_index_at = _coerce_datetime_utc(getattr(source, "next_index_at", None))
    if next_index_at is None:
        schedule_source_next_index(source.id, from_time=now)
        return False
    return next_index_at <= now


def _run_scheduled_source_indexes() -> None:
    now = utcnow()
    for source in list_sources():
        if not _source_due_for_schedule(source, now):
            continue
        if _source_has_incomplete_index_task(source.id):
            continue
        _start_index(reset=False, source_id=source.id, index_mode=INDEX_MODE_FRESH)


def _coerce_top_k(value: Any, default: int) -> int:
    try:
        top_k = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(top_k, 12))


def _coerce_float_str(value: str) -> str:
    if not value:
        return ""
    try:
        return str(float(value))
    except ValueError:
        return ""


def _coerce_int_str(value: str) -> str:
    if not value:
        return ""
    try:
        return str(int(value))
    except ValueError:
        return ""


def _get_collections(config, sources) -> list[dict[str, Any]]:
    client = chromadb.HttpClient(host=config.chroma_host, port=config.chroma_port)
    embedding_fn = build_embedding_function(config)
    collections: list[dict[str, Any]] = []
    for source in sources:
        collection_name = getattr(source, "collection", None)
        if not collection_name:
            continue
        collection = client.get_or_create_collection(
            name=collection_name, embedding_function=embedding_fn
        )
        collections.append({"source": source, "collection": collection})
    return collections


def _query_collections(
    message: str, collections: list[dict[str, Any]], top_k: int
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


def _build_messages(
    history: Any,
    message: str,
    context: str,
    max_history: int,
    response_style: str,
) -> list[dict[str, str]]:
    trimmed = _trim_history(history, max_history)
    user_prompt = _build_user_prompt(message, context)
    return [
        {"role": "system", "content": _system_prompt(response_style)},
        *trimmed,
        {"role": "user", "content": user_prompt},
    ]


def _build_query_text(message: str, history: Any, max_history: int) -> str:
    trimmed = _trim_history(history, max_history)
    recent_users = [item["content"] for item in trimmed if item["role"] == "user"]
    parts = recent_users[-2:] + [message]
    combined = "\n".join([part for part in parts if part]).strip()
    if not combined:
        return message
    max_chars = 800
    if len(combined) > max_chars:
        combined = combined[-max_chars:]
    return combined


def _trim_history(history: Any, max_items: int) -> list[dict[str, str]]:
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


def _build_user_prompt(message: str, context: str) -> str:
    if not context:
        context = "(no context retrieved; use conversation if relevant)"
    return (
        "Answer the question using the conversation so far and the context below. "
        "Use markdown formatting when it helps readability.\n\n"
        f"Question: {message}\n\n"
        "Context:\n"
        f"{context}"
    )


def _build_context(
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
        label = _format_label(meta)
        snippet = _truncate(doc.strip(), snippet_chars)
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


def _format_label(meta: dict[str, Any]) -> str:
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


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _missing_api_key_for_active_providers(config) -> str | None:
    messages: list[str] = []
    if not has_embedding_api_key(config):
        messages.append(
            missing_api_key_message(get_embedding_provider(config), "Embedding")
        )
    if not has_chat_api_key(config):
        messages.append(missing_api_key_message(get_chat_provider(config), "Chat"))
    if not messages:
        return None
    return " ".join(messages)


def _fetch_github_repos(pat: str) -> list[str]:
    repos: list[str] = []
    page = 1
    headers = {
        "Authorization": f"token {pat}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "llmctl-rag",
    }
    while page <= 10:
        url = (
            "https://api.github.com/user/repos"
            f"?per_page=100&page={page}&sort=updated"
        )
        request = Request(url, headers=headers)
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, list):
            break
        batch = [item.get("full_name") for item in payload if item.get("full_name")]
        repos.extend(batch)
        if len(payload) < 100:
            break
        page += 1
    unique = sorted(set(repos), key=str.lower)
    return unique


if __name__ == "__main__":
    app = create_app()
    config = load_config()
    port = config.web_port
    app.run(host="0.0.0.0", port=port, debug=False)
