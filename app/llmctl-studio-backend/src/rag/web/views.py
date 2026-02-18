from __future__ import annotations

from datetime import datetime, timezone
import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from core.config import Config
from core.db import session_scope
from core.models import AgentTask
from core.prompt_envelope import (
    build_prompt_envelope,
    parse_prompt_input,
    serialize_prompt_envelope,
)
from core.task_kinds import (
    RAG_QUICK_DELTA_TASK_KIND,
    RAG_QUICK_INDEX_TASK_KIND,
)
from rag.domain import (
    RAG_REASON_RETRIEVAL_EXECUTION_FAILED,
    RAG_REASON_UNAVAILABLE_FOR_SELECTED_COLLECTIONS,
    RagContractError,
    execute_query_contract,
    list_collection_contract,
    normalize_collection_selection,
    rag_health_snapshot,
)
from rag.engine.chromadb_loader import import_chromadb
from rag.engine.config import load_config
from rag.integrations.google_drive_sync import service_account_email, verify_folder_access
from rag.providers.adapters import (
    get_chat_model,
    get_chat_provider,
    has_chat_api_key,
    has_embedding_api_key,
    missing_api_key_message,
)
from rag.repositories.sources import (
    RAGSourceInput,
    create_source,
    delete_source,
    get_source,
    list_sources,
    update_source,
)
from rag.web.routes import (
    RAG_API_CHAT,
    RAG_API_CHROMA_TEST,
    RAG_API_COLLECTIONS,
    RAG_API_COLLECTIONS_LEGACY,
    RAG_API_DRIVE_VERIFY,
    RAG_API_GITHUB_REPOS,
    RAG_API_HEALTH,
    RAG_API_HEALTH_LEGACY,
    RAG_API_RETRIEVE,
    RAG_API_RETRIEVE_LEGACY,
    RAG_PAGE_CHAT,
    RAG_PAGE_SOURCES,
)
from services.execution.contracts import EXECUTION_STATUS_SUCCESS
from services.integrations import load_integration_settings
from services.tasks import (
    execute_rag_chat_completion_via_execution_router,
    run_quick_rag_task,
)

bp = Blueprint("rag", __name__)

DOCKER_CHROMA_HOST_ALIASES = {"llmctl-chromadb", "chromadb"}
CHAT_CONTEXT_CHARS_PER_TOKEN = 4
SUPPORTED_CHAT_RESPONSE_STYLES = {"low", "medium", "high"}
CHAT_RESPONSE_STYLE_ALIASES = {
    "concise": "low",
    "brief": "low",
    "balanced": "medium",
    "detailed": "high",
    "verbose": "high",
}
BASE_SYSTEM_PROMPT = (
    "You are a helpful assistant for a retrieval-augmented generation app. "
    "Use the provided context and the conversation history to answer. "
    "If context is empty, answer directly and be explicit about uncertainty."
)
QUICK_RAG_ACTIVE_STATUSES = {"queued", "running"}
QUICK_RAG_TASK_KINDS = {
    RAG_QUICK_INDEX_TASK_KIND,
    RAG_QUICK_DELTA_TASK_KIND,
}


def _normalize_chat_response_style(value: str | None, default: str = "high") -> str:
    candidate = (value or "").strip().lower()
    candidate = CHAT_RESPONSE_STYLE_ALIASES.get(candidate, candidate)
    if candidate in SUPPORTED_CHAT_RESPONSE_STYLES:
        return candidate
    return default


def _system_prompt(response_style: str) -> str:
    normalized_style = _normalize_chat_response_style(response_style, "high")
    if normalized_style == "low":
        return (
            BASE_SYSTEM_PROMPT
            + " Keep responses natural, conversational, concise, and direct."
        )
    if normalized_style == "medium":
        return (
            BASE_SYSTEM_PROMPT
            + " Keep a natural, conversational tone with balanced detail and clarity. "
            + "Do not force a fixed output template."
        )
    return (
        BASE_SYSTEM_PROMPT
        + " Keep a natural, conversational tone while providing thorough, detailed "
        + "answers. Use structure only when it improves clarity."
    )


def _sanitize_history(history: Any, limit: int) -> list[dict[str, str]]:
    if not isinstance(history, list):
        return []
    cleaned: list[dict[str, str]] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        text = str(item.get("content") or "").strip()
        if not text:
            continue
        cleaned.append({"role": role, "content": text})
    return cleaned[-max(1, limit) :]


def _build_messages(
    *,
    question: str,
    history: Any,
    context_text: str,
    history_limit: int,
    response_style: str,
) -> list[dict[str, str]]:
    prompt = (
        "Answer the question using the conversation and retrieval context.\n\n"
        f"Question: {question}\n\n"
        "Retrieval Context:\n"
        f"{context_text or '(no retrieval context)'}"
    )
    return [
        {"role": "system", "content": _system_prompt(response_style)},
        *_sanitize_history(history, history_limit),
        {"role": "user", "content": prompt},
    ]


def _executor_node_identity(seed: str) -> tuple[int, int]:
    digest = abs(hash(seed or "rag-chat"))
    node_id = int((digest % 900_000) + 100_000)
    execution_id = int((time.time_ns() // 1_000_000) % 1_000_000_000)
    if execution_id <= 0:
        execution_id = 1
    return node_id, execution_id


def _chat_completion_via_executor(
    *,
    messages: list[dict[str, str]],
    request_id: str,
) -> str:
    normalized_request_id = str(request_id or "").strip() or f"rag-chat-{time.time_ns()}"
    node_id, execution_id = _executor_node_identity(normalized_request_id)
    execution_result = execute_rag_chat_completion_via_execution_router(
        messages=messages,
        request_id=normalized_request_id,
        node_id=node_id,
        execution_id=execution_id,
    )
    output_state = (
        execution_result.output_state
        if isinstance(execution_result.output_state, dict)
        else {}
    )
    if execution_result.status != EXECUTION_STATUS_SUCCESS:
        error_payload = (
            execution_result.error
            if isinstance(execution_result.error, dict)
            else {}
        )
        message = str(error_payload.get("message") or "").strip()
        if not message:
            message = (
                "Executor RAG chat completion failed with status "
                f"'{str(execution_result.status or 'failed')}'."
            )
        raise RuntimeError(message)
    return str(output_state.get("reply") or "")


def _to_positive_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if parsed < minimum:
        return minimum
    if parsed > maximum:
        return maximum
    return parsed


def _to_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    cleaned = str(value).strip().lower()
    if cleaned in {"1", "true", "yes", "y", "on"}:
        return True
    if cleaned in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _context_char_limit(context_budget_tokens: int, config_max_context_chars: int) -> int:
    budget_chars = max(1000, int(context_budget_tokens) * CHAT_CONTEXT_CHARS_PER_TOKEN)
    return min(max(1000, int(config_max_context_chars)), budget_chars)


def _coerce_datetime_utc(value: datetime | None) -> datetime | None:
    if not value:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_source_time(value: datetime | None) -> str:
    dt = _coerce_datetime_utc(value)
    if not dt:
        return "-"
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _source_schedule_text(source: Any) -> str:
    try:
        schedule_value = int(getattr(source, "index_schedule_value", 0) or 0)
    except (TypeError, ValueError):
        schedule_value = 0
    unit = str(getattr(source, "index_schedule_unit", "") or "").strip().lower()
    if schedule_value <= 0 or unit not in {"minutes", "hours", "days", "weeks"}:
        return "Not scheduled"
    label = unit[:-1] if schedule_value == 1 and unit.endswith("s") else unit
    return f"Every {schedule_value} {label}"


def _source_location(source: Any) -> str:
    kind = str(getattr(source, "kind", "") or "").strip().lower()
    if kind == "local":
        return str(getattr(source, "local_path", "") or "-")
    if kind == "github":
        repo = str(getattr(source, "git_repo", "") or "-")
        branch = str(getattr(source, "git_branch", "") or "").strip()
        return f"{repo}@{branch}" if branch else repo
    if kind == "google_drive":
        folder = str(getattr(source, "drive_folder_id", "") or "-")
        return f"folder {folder}"
    return "-"


def _wants_json_response() -> bool:
    api_prefix = str(current_app.config.get("API_PREFIX", "/api")).strip() or "/api"
    if api_prefix != "/":
        normalized_prefix = f"/{api_prefix.strip('/')}"
        path = str(request.path or "")
        if path == normalized_prefix or path.startswith(f"{normalized_prefix}/"):
            return True
    accept = str(request.headers.get("Accept") or "").lower()
    if "application/json" in accept:
        return True
    requested_with = str(request.headers.get("X-Requested-With") or "").strip().lower()
    return requested_with == "xmlhttprequest"


def _parse_source_ids_csv(raw_ids: str | None) -> list[int]:
    if not raw_ids:
        return []
    source_ids: list[int] = []
    for item in str(raw_ids).split(","):
        cleaned = item.strip()
        if not cleaned:
            continue
        try:
            parsed = int(cleaned)
        except ValueError:
            continue
        if parsed > 0 and parsed not in source_ids:
            source_ids.append(parsed)
    return source_ids


def _quick_rag_context_from_prompt(prompt: str | None) -> dict[str, Any]:
    _user_request, payload = parse_prompt_input(prompt)
    if not isinstance(payload, dict):
        return {}
    task_context = payload.get("task_context")
    if not isinstance(task_context, dict):
        return {}
    quick_context = task_context.get("rag_quick_run")
    if not isinstance(quick_context, dict):
        return {}
    return quick_context


def _active_quick_rag_source_ids() -> set[int]:
    with session_scope() as session:
        tasks = (
            session.execute(
                select(AgentTask).where(
                    AgentTask.kind.in_(tuple(QUICK_RAG_TASK_KINDS)),
                    AgentTask.status.in_(tuple(QUICK_RAG_ACTIVE_STATUSES)),
                )
            )
            .scalars()
            .all()
        )
    source_ids: set[int] = set()
    for task in tasks:
        quick_context = _quick_rag_context_from_prompt(getattr(task, "prompt", None))
        try:
            source_id = int(quick_context.get("source_id") or 0)
        except (TypeError, ValueError):
            source_id = 0
        if source_id > 0:
            source_ids.add(source_id)
    return source_ids


def _normalize_quick_rag_mode(value: str | None) -> tuple[str, str]:
    cleaned = str(value or "").strip().lower()
    if cleaned in {"delta", "delta_index"}:
        return "delta", "delta_index"
    return "fresh", "fresh_index"


def _preferred_quick_rag_model_provider() -> str:
    embed_provider = str(load_config().embed_provider or "").strip().lower()
    if embed_provider == "gemini":
        return "gemini"
    return "codex"


def _source_status_label(source: Any, *, has_active_job: bool) -> str:
    if has_active_job:
        return "Indexing"
    if getattr(source, "last_error", None):
        return "Error"
    if getattr(source, "last_indexed_at", None):
        return "Indexed"
    return "Not indexed"


def _source_status_payload(source: Any, *, has_active_job: bool) -> dict[str, Any]:
    return {
        "id": int(getattr(source, "id")),
        "has_active_job": bool(has_active_job),
        "status": _source_status_label(source, has_active_job=has_active_job),
        "last_indexed_at": (
            getattr(source, "last_indexed_at").isoformat()
            if getattr(source, "last_indexed_at", None)
            else None
        ),
    }


def _resolve_chroma_settings() -> dict[str, str]:
    settings = load_integration_settings("chroma")
    host = (settings.get("host") or "").strip() or (Config.CHROMA_HOST or "").strip()
    port_raw = (settings.get("port") or "").strip() or (Config.CHROMA_PORT or "").strip()
    ssl_raw = (settings.get("ssl") or "").strip().lower() or (Config.CHROMA_SSL or "").strip().lower()
    return {
        "host": host,
        "port": port_raw,
        "ssl": "true" if ssl_raw == "true" else "false",
    }


def _parse_chroma_port(value: str | None) -> int | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        parsed = int(raw)
    except ValueError:
        return None
    if parsed < 1 or parsed > 65535:
        return None
    return parsed


def _normalize_chroma_target(host: str, port: int) -> tuple[str, int, str | None]:
    host_value = (host or "").strip()
    if host_value.lower() in DOCKER_CHROMA_HOST_ALIASES and port != 8000:
        return (
            "llmctl-chromadb",
            8000,
            "Using llmctl-chromadb:8000 inside Docker. Host-mapped ports are for host access only.",
        )
    if host_value.lower() in DOCKER_CHROMA_HOST_ALIASES:
        return "llmctl-chromadb", port, None
    return host_value, port, None


def _fetch_github_repos(pat: str) -> list[str]:
    repos: list[str] = []
    page = 1
    headers = {
        "Authorization": f"token {pat}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "llmctl-studio-rag",
    }
    while page <= 10:
        url = (
            "https://api.github.com/user/repos"
            f"?per_page=100&page={page}&sort=updated"
        )
        request_obj = Request(url, headers=headers)
        try:
            with urlopen(request_obj, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise ValueError("GitHub PAT is invalid or lacks repo access.") from exc
            raise ValueError("GitHub API error while fetching repositories.") from exc
        except URLError as exc:
            raise ValueError("Unable to reach GitHub API.") from exc

        if not isinstance(payload, list):
            break
        batch = [item.get("full_name") for item in payload if item.get("full_name")]
        repos.extend(batch)
        if len(payload) < 100:
            break
        page += 1

    return sorted(set(repos), key=str.lower)


def _source_iso_datetime(value: datetime | None) -> str | None:
    dt = _coerce_datetime_utc(value)
    if not dt:
        return None
    return dt.isoformat()


def _source_file_types(source: Any) -> list[dict[str, Any]]:
    file_types: list[dict[str, Any]] = []
    raw_types = getattr(source, "indexed_file_types", None)
    if not raw_types:
        return file_types
    try:
        parsed = json.loads(raw_types)
    except json.JSONDecodeError:
        return file_types
    if isinstance(parsed, dict):
        for key, value in sorted(parsed.items(), key=lambda item: str(item[0])):
            file_types.append({"type": str(key), "count": int(value or 0)})
    return file_types


def _serialize_source(source: Any, *, has_active_job: bool) -> dict[str, Any]:
    return {
        "id": int(getattr(source, "id")),
        "name": str(getattr(source, "name") or ""),
        "kind": str(getattr(source, "kind") or ""),
        "collection": str(getattr(source, "collection") or ""),
        "local_path": str(getattr(source, "local_path") or ""),
        "git_repo": str(getattr(source, "git_repo") or ""),
        "git_branch": str(getattr(source, "git_branch") or ""),
        "drive_folder_id": str(getattr(source, "drive_folder_id") or ""),
        "index_schedule_value": getattr(source, "index_schedule_value", None),
        "index_schedule_unit": getattr(source, "index_schedule_unit", None),
        "index_schedule_mode": str(getattr(source, "index_schedule_mode") or "fresh"),
        "indexed_file_count": getattr(source, "indexed_file_count", None),
        "indexed_chunk_count": getattr(source, "indexed_chunk_count", None),
        "last_error": str(getattr(source, "last_error") or ""),
        "last_indexed_at": _source_iso_datetime(getattr(source, "last_indexed_at", None)),
        "next_index_at": _source_iso_datetime(getattr(source, "next_index_at", None)),
        "created_at": _source_iso_datetime(getattr(source, "created_at", None)),
        "updated_at": _source_iso_datetime(getattr(source, "updated_at", None)),
        "has_active_job": bool(has_active_job),
        "status": _source_status_label(source, has_active_job=has_active_job),
        "location": _source_location(source),
        "schedule_text": _source_schedule_text(source),
        "file_types": _source_file_types(source),
    }


def _source_form_meta() -> dict[str, Any]:
    github_settings = load_integration_settings("github")
    drive_settings = load_integration_settings("google_workspace")
    service_email = None
    service_json = (drive_settings.get("service_account_json") or "").strip()
    if service_json:
        try:
            service_email = service_account_email(service_json)
        except ValueError:
            service_email = None
    return {
        "github_connected": bool((github_settings.get("pat") or "").strip()),
        "google_drive_connected": bool(service_json),
        "google_drive_service_email": service_email,
        "source_kind_local": "local",
        "source_kind_github": "github",
        "source_kind_google_drive": "google_drive",
        "index_mode_fresh": "fresh",
        "index_mode_delta": "delta",
    }


def _source_input_from_request() -> RAGSourceInput:
    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None or not isinstance(payload, dict):
        payload = {}

    def _value(form_key: str, json_key: str | None = None) -> str:
        if request.is_json:
            key = json_key or form_key
            if key in payload:
                return str(payload.get(key) or "")
            if form_key in payload:
                return str(payload.get(form_key) or "")
        return request.form.get(form_key, "")

    return RAGSourceInput(
        name=_value("source_name", "name"),
        kind=_value("source_kind", "kind"),
        local_path=_value("source_local_path", "local_path"),
        git_repo=_value("source_git_repo", "git_repo"),
        git_branch=_value("source_git_branch", "git_branch"),
        drive_folder_id=_value("source_drive_folder_id", "drive_folder_id"),
        index_schedule_value=_value("source_index_schedule_value", "index_schedule_value"),
        index_schedule_unit=_value("source_index_schedule_unit", "index_schedule_unit"),
        index_schedule_mode=_value("source_index_schedule_mode", "index_schedule_mode"),
    )


@bp.get("/rag")
def rag_root():
    return redirect(url_for("rag.chat_page"))


@bp.get("/api/rag/chat")
@bp.get(RAG_PAGE_CHAT)
def chat_page():
    config = load_config()
    collection_contract = list_collection_contract()
    missing_api_key = None
    if not has_chat_api_key(config):
        missing_api_key = missing_api_key_message(get_chat_provider(config), "Chat")

    if _wants_json_response():
        return {
            "collections": collection_contract.get("collections", []),
            "chat_top_k": config.chat_top_k,
            "chat_verbosity": config.chat_response_style,
            "chat_context_budget_tokens": config.chat_context_budget_tokens,
            "chat_max_history": config.chat_max_history,
            "rag_health": rag_health_snapshot(),
            "missing_api_key": missing_api_key,
            "page_title": "RAG Chat",
        }

    return render_template(
        "rag/chat.html",
        collections=collection_contract.get("collections", []),
        chat_top_k=config.chat_top_k,
        chat_verbosity=config.chat_response_style,
        chat_context_budget_tokens=config.chat_context_budget_tokens,
        chat_max_history=config.chat_max_history,
        rag_health=rag_health_snapshot(),
        missing_api_key=missing_api_key,
        page_title="RAG Chat",
        active_page="rag_chat",
    )


@bp.get("/api/rag/sources")
@bp.get(RAG_PAGE_SOURCES)
def sources_page():
    sources = list_sources(limit=None)
    active_source_ids = _active_quick_rag_source_ids()
    if _wants_json_response():
        return {
            "sources": [
                _serialize_source(source, has_active_job=int(source.id) in active_source_ids)
                for source in sources
            ],
            "active_source_ids": sorted(active_source_ids),
            "rag_health": rag_health_snapshot(),
            "page_title": "RAG Sources",
        }
    return render_template(
        "rag/sources.html",
        sources=sources,
        active_source_ids=active_source_ids,
        source_location=_source_location,
        source_schedule_text=_source_schedule_text,
        format_source_time=_format_source_time,
        rag_health=rag_health_snapshot(),
        page_title="RAG Sources",
        active_page="rag_sources",
        fixed_list_page=True,
    )


@bp.get("/api/rag/sources/new")
@bp.get(f"{RAG_PAGE_SOURCES}/new")
def new_source_page():
    form_meta = _source_form_meta()

    if _wants_json_response():
        return {
            **form_meta,
            "page_title": "New RAG Source",
        }

    return render_template(
        "rag/source_new.html",
        github_connected=form_meta["github_connected"],
        google_drive_connected=form_meta["google_drive_connected"],
        google_drive_service_email=form_meta["google_drive_service_email"],
        source_kind_local=form_meta["source_kind_local"],
        source_kind_github=form_meta["source_kind_github"],
        source_kind_google_drive=form_meta["source_kind_google_drive"],
        index_mode_fresh=form_meta["index_mode_fresh"],
        index_mode_delta=form_meta["index_mode_delta"],
        page_title="New RAG Source",
        active_page="rag_sources",
    )


@bp.post("/api/rag/sources")
@bp.post(RAG_PAGE_SOURCES)
def create_source_page():
    payload = _source_input_from_request()
    try:
        source = create_source(payload)
    except ValueError as exc:
        if _wants_json_response():
            return {"error": str(exc)}, 400
        flash(str(exc), "error")
        return redirect(url_for("rag.new_source_page"))

    if _wants_json_response():
        return {
            "ok": True,
            "source": _serialize_source(source, has_active_job=False),
        }, 201
    flash("Source created.", "success")
    return redirect(url_for("rag.source_detail_page", source_id=source.id))


@bp.get("/api/rag/sources/<int:source_id>")
@bp.get(f"{RAG_PAGE_SOURCES}/<int:source_id>")
def source_detail_page(source_id: int):
    source = get_source(source_id)
    if not source:
        if _wants_json_response():
            return {"error": "Source not found."}, 404
        flash("Source not found.", "error")
        return redirect(url_for("rag.sources_page"))
    active_source_ids = _active_quick_rag_source_ids()
    has_active_job = source_id in active_source_ids

    file_types = _source_file_types(source)
    if _wants_json_response():
        return {
            "source": _serialize_source(source, has_active_job=has_active_job),
            "file_types": file_types,
            "rag_health": rag_health_snapshot(),
            "page_title": f"RAG Source - {source.name}",
        }

    return render_template(
        "rag/source_detail.html",
        source=source,
        file_types=file_types,
        has_active_job=has_active_job,
        source_location=_source_location,
        source_schedule_text=_source_schedule_text,
        format_source_time=_format_source_time,
        rag_health=rag_health_snapshot(),
        page_title=f"RAG Source - {source.name}",
        active_page="rag_sources",
    )


@bp.get("/api/rag/sources/<int:source_id>/edit")
@bp.get(f"{RAG_PAGE_SOURCES}/<int:source_id>/edit")
def edit_source_page(source_id: int):
    source = get_source(source_id)
    if not source:
        if _wants_json_response():
            return {"error": "Source not found."}, 404
        flash("Source not found.", "error")
        return redirect(url_for("rag.sources_page"))

    form_meta = _source_form_meta()
    if _wants_json_response():
        return {
            "source": _serialize_source(source, has_active_job=False),
            **form_meta,
            "page_title": f"Edit RAG Source - {source.name}",
        }

    return render_template(
        "rag/source_edit.html",
        source=source,
        github_connected=form_meta["github_connected"],
        google_drive_connected=form_meta["google_drive_connected"],
        google_drive_service_email=form_meta["google_drive_service_email"],
        source_kind_local=form_meta["source_kind_local"],
        source_kind_github=form_meta["source_kind_github"],
        source_kind_google_drive=form_meta["source_kind_google_drive"],
        index_mode_fresh=form_meta["index_mode_fresh"],
        index_mode_delta=form_meta["index_mode_delta"],
        page_title=f"Edit RAG Source - {source.name}",
        active_page="rag_sources",
    )


@bp.post("/api/rag/sources/<int:source_id>")
@bp.post(f"{RAG_PAGE_SOURCES}/<int:source_id>")
def update_source_page(source_id: int):
    source = get_source(source_id)
    if not source:
        if _wants_json_response():
            return {"error": "Source not found."}, 404
        flash("Source not found.", "error")
        return redirect(url_for("rag.sources_page"))

    payload = _source_input_from_request()
    try:
        updated = update_source(source_id, payload)
    except ValueError as exc:
        if _wants_json_response():
            return {"error": str(exc)}, 400
        flash(str(exc), "error")
        return redirect(url_for("rag.edit_source_page", source_id=source_id))

    if _wants_json_response():
        active_source_ids = _active_quick_rag_source_ids()
        return {
            "ok": True,
            "source": _serialize_source(
                updated,
                has_active_job=int(updated.id) in active_source_ids,
            ),
        }
    flash("Source updated.", "success")
    return redirect(url_for("rag.source_detail_page", source_id=source_id))


@bp.post("/api/rag/sources/<int:source_id>/delete")
@bp.post(f"{RAG_PAGE_SOURCES}/<int:source_id>/delete")
def delete_source_page(source_id: int):
    source = get_source(source_id)
    if not source:
        if _wants_json_response():
            return {"error": "Source not found."}, 404
        flash("Source not found.", "error")
        return redirect(url_for("rag.sources_page"))

    delete_source(source_id)
    if _wants_json_response():
        return {"ok": True, "source_id": source_id}
    flash("Source deleted.", "success")
    return redirect(url_for("rag.sources_page"))


def _start_source_quick_run_response(*, source_id: int, index_mode: str):
    source = get_source(source_id)
    if not source:
        message = "Source not found."
        if _wants_json_response():
            return {"ok": False, "error": message}, 404
        flash(message, "error")
        return redirect(url_for("rag.sources_page"))

    quick_mode, flowchart_mode = _normalize_quick_rag_mode(index_mode)
    task_kind = (
        RAG_QUICK_DELTA_TASK_KIND if quick_mode == "delta" else RAG_QUICK_INDEX_TASK_KIND
    )
    mode_text = "delta index" if quick_mode == "delta" else "index"
    active_source_ids = _active_quick_rag_source_ids()
    if source_id in active_source_ids:
        message = f"A quick {mode_text} run is already active for this source."
        if _wants_json_response():
            return {
                "ok": False,
                "error": message,
                "source": _source_status_payload(source, has_active_job=True),
            }, 409
        flash(message, "warning")
        return redirect(url_for("rag.source_detail_page", source_id=source_id))

    quick_context = {
        "source_id": int(source.id),
        "source_name": str(source.name),
        "collection": str(source.collection),
        "mode": quick_mode,
        "flowchart_mode": flowchart_mode,
        "model_provider": _preferred_quick_rag_model_provider(),
    }
    prompt_payload = serialize_prompt_envelope(
        build_prompt_envelope(
            user_request=f"Quick RAG {mode_text} for source '{source.name}'.",
            task_context={
                "kind": task_kind,
                "rag_quick_run": quick_context,
            },
            output_contract={"format": "json"},
        )
    )
    with session_scope() as session:
        task = AgentTask.create(
            session,
            status="queued",
            kind=task_kind,
            prompt=prompt_payload,
        )
        task_id = int(task.id)
    try:
        async_result = run_quick_rag_task.delay(task_id)
    except Exception as exc:
        now = datetime.now(timezone.utc)
        with session_scope() as session:
            task = session.get(AgentTask, task_id)
            if task is not None:
                task.status = "failed"
                task.error = f"Failed to queue quick {mode_text} run: {exc}"
                task.finished_at = now
        message = f"Failed to queue quick {mode_text} run: {exc}"
        if _wants_json_response():
            return {"ok": False, "error": message}, 500
        flash(message, "error")
        return redirect(url_for("rag.source_detail_page", source_id=source_id))

    with session_scope() as session:
        task = session.get(AgentTask, task_id)
        if task is not None:
            task.celery_task_id = async_result.id

    message = f"Queued quick {mode_text} run for {source.name}."
    if _wants_json_response():
        return {
            "ok": True,
            "task_id": task_id,
            "mode": quick_mode,
            "source": _source_status_payload(source, has_active_job=True),
        }, 202
    flash(message, "success")
    return redirect(url_for("rag.source_detail_page", source_id=source_id))


@bp.post("/api/rag/sources/<int:source_id>/quick-index")
@bp.post(f"{RAG_PAGE_SOURCES}/<int:source_id>/quick-index")
def quick_index_source_page(source_id: int):
    return _start_source_quick_run_response(source_id=source_id, index_mode="fresh")


@bp.post("/api/rag/sources/<int:source_id>/quick-delta-index")
@bp.post(f"{RAG_PAGE_SOURCES}/<int:source_id>/quick-delta-index")
def quick_delta_index_source_page(source_id: int):
    return _start_source_quick_run_response(source_id=source_id, index_mode="delta")


@bp.get("/api/rag/sources/status")
def api_source_status():
    source_ids = _parse_source_ids_csv(request.args.get("ids"))
    sources = list_sources(limit=None)
    active_source_ids = _active_quick_rag_source_ids()
    source_by_id = {int(source.id): source for source in sources}

    if source_ids:
        selected_sources = [source_by_id[source_id] for source_id in source_ids if source_id in source_by_id]
    else:
        selected_sources = sources

    payload = [
        _source_status_payload(
            source,
            has_active_job=int(source.id) in active_source_ids,
        )
        for source in selected_sources
    ]
    return {"sources": payload}


@bp.get(RAG_API_HEALTH)
@bp.get(RAG_API_HEALTH_LEGACY)
def api_health():
    payload = rag_health_snapshot()
    payload["contract_version"] = "v1"
    return payload


@bp.get(RAG_API_COLLECTIONS)
@bp.get(RAG_API_COLLECTIONS_LEGACY)
def api_collections():
    payload = list_collection_contract()
    payload["health"] = rag_health_snapshot()
    payload["contract_version"] = "v1"
    return payload


@bp.post(RAG_API_RETRIEVE)
@bp.post(RAG_API_RETRIEVE_LEGACY)
def api_retrieve():
    started = time.time()
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question") or "").strip()
    if not question:
        return {"error": "question is required."}, 400

    top_k = _to_positive_int(payload.get("top_k"), 5, minimum=1, maximum=20)
    collections = normalize_collection_selection(payload.get("collections"))
    request_id = str(payload.get("request_id") or "").strip() or None
    config = load_config()
    response_style = _normalize_chat_response_style(
        str(payload.get("verbosity") or "").strip(),
        config.chat_response_style,
    )
    history_limit = _to_positive_int(
        payload.get("history_limit"),
        config.chat_max_history,
        minimum=1,
        maximum=50,
    )
    context_budget_tokens = _to_positive_int(
        payload.get("context_budget_tokens"),
        config.chat_context_budget_tokens,
        minimum=256,
        maximum=100000,
    )
    synthesize_answer = _to_bool(
        payload.get("synthesize_answer"),
        default=True,
    )
    max_context_chars = _context_char_limit(
        context_budget_tokens,
        config.chat_max_context_chars,
    )
    history = payload.get("history")

    def _synthesize(question_text: str, retrieval_context: list[dict[str, Any]]) -> str | None:
        if not has_chat_api_key(config):
            raise RuntimeError(
                missing_api_key_message(get_chat_provider(config), "Chat")
            )
        context_text = "\n\n".join(
            str(item.get("text") or "").strip()
            for item in retrieval_context
            if str(item.get("text") or "").strip()
        )
        if max_context_chars > 0 and len(context_text) > max_context_chars:
            context_text = context_text[:max_context_chars]
        messages = _build_messages(
            question=question_text,
            history=history,
            context_text=context_text,
            history_limit=history_limit,
            response_style=response_style,
        )
        return _chat_completion_via_executor(
            messages=messages,
            request_id=request_id or question_text,
        )

    try:
        result = execute_query_contract(
            question=question,
            collections=collections,
            top_k=top_k,
            request_id=request_id,
            runtime_kind="chat",
            synthesize_answer=_synthesize if synthesize_answer else None,
        )
    except RagContractError as exc:
        return exc.as_payload(), exc.status_code

    result["provider"] = get_chat_provider(config)
    result["model"] = get_chat_model(config)
    result["elapsed_ms"] = int((time.time() - started) * 1000)
    result["contract_version"] = "v1"
    return result


@bp.post(RAG_API_CHAT)
def api_chat():
    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message") or payload.get("question") or "").strip()
    if not message:
        return {"error": "Message is required."}, 400

    all_sources = list_sources(limit=None)
    source_by_id = {int(source.id): source for source in all_sources}
    source_ids = payload.get("source_ids") if isinstance(payload.get("source_ids"), list) else []
    selected_collections = normalize_collection_selection(payload.get("collections"))
    if not selected_collections and source_ids:
        for source_id in source_ids:
            try:
                parsed_id = int(source_id)
            except (TypeError, ValueError):
                continue
            source = source_by_id.get(parsed_id)
            if source is None:
                continue
            collection = str(getattr(source, "collection", "") or "").strip()
            if collection:
                selected_collections.append(collection)

    if selected_collections:
        try:
            result = execute_query_contract(
                question=message,
                collections=selected_collections,
                top_k=_to_positive_int(payload.get("top_k"), 5, minimum=1, maximum=20),
                request_id=str(payload.get("request_id") or "").strip() or None,
                runtime_kind="chat",
                synthesize_answer=lambda question_text, retrieval_context: _chat_completion_via_executor(
                    messages=_build_messages(
                        question=question_text,
                        history=payload.get("history"),
                        context_text="\n\n".join(
                            str(item.get("text") or "").strip()
                            for item in retrieval_context
                            if str(item.get("text") or "").strip()
                        ),
                        history_limit=_to_positive_int(
                            payload.get("history_limit"),
                            load_config().chat_max_history,
                            minimum=1,
                            maximum=50,
                        ),
                        response_style=_normalize_chat_response_style(
                            str(payload.get("verbosity") or "").strip(),
                            load_config().chat_response_style,
                        ),
                    ),
                    request_id=str(payload.get("request_id") or "").strip() or question_text,
                ),
            )
        except RagContractError as exc:
            return exc.as_payload(), exc.status_code
        except Exception as exc:
            return {
                "error": {
                    "reason_code": RAG_REASON_RETRIEVAL_EXECUTION_FAILED,
                    "message": str(exc),
                    "metadata": {
                        "provider": "chroma",
                        "selected_collections": selected_collections,
                    },
                }
            }, 500

        return {
            "reply": result.get("answer"),
            "answer": result.get("answer"),
            "retrieval_context": result.get("retrieval_context"),
            "retrieval_stats": result.get("retrieval_stats"),
            "synthesis_error": result.get("synthesis_error"),
            "mode": result.get("mode"),
            "collections": result.get("collections"),
        "provider": get_chat_provider(load_config()),
        "model": get_chat_model(load_config()),
        "contract_version": "v1",
    }

    config = load_config()
    if not has_chat_api_key(config):
        provider = get_chat_provider(config)
        return {
            "error": {
                "reason_code": RAG_REASON_UNAVAILABLE_FOR_SELECTED_COLLECTIONS,
                "message": missing_api_key_message(provider, "Chat"),
                "metadata": {
                    "rag_health_state": rag_health_snapshot()["state"],
                    "selected_collections": [],
                    "provider": "chroma",
                },
            }
        }, 400

    messages = _build_messages(
        question=message,
        history=payload.get("history"),
        context_text="",
        history_limit=_to_positive_int(
            payload.get("history_limit"),
            config.chat_max_history,
            minimum=1,
            maximum=50,
        ),
        response_style=_normalize_chat_response_style(
            str(payload.get("verbosity") or "").strip(),
            config.chat_response_style,
        ),
    )
    try:
        reply = _chat_completion_via_executor(
            messages=messages,
            request_id=str(payload.get("request_id") or "").strip() or message,
        )
    except Exception as exc:
        return {
            "error": {
                "reason_code": RAG_REASON_RETRIEVAL_EXECUTION_FAILED,
                "message": str(exc),
                "metadata": {
                    "provider": "chroma",
                    "selected_collections": [],
                },
            }
        }, 500

    return {
        "reply": reply,
        "answer": reply,
        "retrieval_context": [],
        "retrieval_stats": {"provider": "chroma", "retrieved_count": 0, "top_k": 0},
        "synthesis_error": None,
        "mode": "query",
        "collections": [],
        "provider": get_chat_provider(config),
        "model": get_chat_model(config),
        "contract_version": "v1",
    }


@bp.get(RAG_API_GITHUB_REPOS)
def api_github_repos():
    github_settings = load_integration_settings("github")
    pat = (github_settings.get("pat") or "").strip()
    if not pat:
        return {"error": "GitHub PAT is not configured."}, 400
    try:
        repos = _fetch_github_repos(pat)
    except ValueError as exc:
        return {"error": str(exc)}, 502
    return {"repos": repos}


@bp.post(RAG_API_DRIVE_VERIFY)
def api_google_drive_verify():
    payload = request.get_json(silent=True) or {}
    folder_id = str(payload.get("folder_id") or "").strip()
    if not folder_id:
        return {"ok": False, "error": "Google Drive folder ID is required."}, 400

    service_account_json = str(payload.get("service_account_json") or "").strip()
    if not service_account_json:
        settings = load_integration_settings("google_workspace")
        service_account_json = str(settings.get("service_account_json") or "").strip()
    if not service_account_json:
        return {
            "ok": False,
            "error": "Google Workspace service account JSON is not configured.",
        }, 400

    try:
        info = verify_folder_access(service_account_json, folder_id)
        email = service_account_email(service_account_json)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}, 400
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}, 502

    return {
        "ok": True,
        "folder_id": info.id,
        "folder_name": info.name,
        "service_account_email": email,
    }


@bp.post(RAG_API_CHROMA_TEST)
def api_chroma_test():
    payload = request.get_json(silent=True) or {}
    settings = _resolve_chroma_settings()
    host = str(payload.get("host") or "").strip() or settings.get("host", "")
    port_raw = str(payload.get("port") or "").strip() or settings.get("port", "")

    parsed_port = _parse_chroma_port(port_raw)
    if not host or parsed_port is None:
        return {"ok": False, "error": "Chroma host and port are required."}, 400

    host, port, hint = _normalize_chroma_target(host, parsed_port)

    try:
        chromadb = import_chromadb()
    except (ImportError, ModuleNotFoundError):
        return {
            "ok": False,
            "error": "Python package 'chromadb' is not installed.",
            "host": host,
            "port": port,
            "hint": hint,
        }, 500

    try:
        ssl = str(settings.get("ssl") or "false").strip().lower() == "true"
        try:
            client = chromadb.HttpClient(host=host, port=port, ssl=ssl)
        except TypeError:
            client = chromadb.HttpClient(host=host, port=port)
        collections = client.list_collections()
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Failed to connect to Chroma at {host}:{port}: {exc}",
            "host": host,
            "port": port,
            "hint": hint,
        }, 502

    return {
        "ok": True,
        "host": host,
        "port": port,
        "collections_count": len(collections),
        "hint": hint,
    }
