from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from flask import Flask, jsonify, redirect, render_template, request, url_for
from openai import OpenAI

from config import build_source_config, load_config
from db import SSH_KEYS_DIR, init_db
from settings_store import (
    ensure_integration_defaults,
    load_integration_settings,
    save_integration_settings,
)
from sources_store import (
    SourceInput,
    create_source,
    delete_source,
    get_source,
    list_sources,
)
from tasks_store import (
    TASK_KIND_INDEX,
    TASK_ACTIVE_STATUSES,
    TASK_STATUS_FAILED,
    active_task,
    create_task,
    delete_task,
    format_dt,
    get_tasks,
    get_task,
    has_active_task,
    latest_task,
    latest_finished_task,
    list_tasks,
    mark_task_finished,
    set_task_celery_id,
    task_meta,
)
from tasks_worker import run_index_task

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "web" / "templates"
STATIC_DIR = BASE_DIR / "web" / "static"

SYSTEM_PROMPT = (
    "You are a helpful assistant for a retrieval-augmented generation app. "
    "Use the provided context and the conversation history to answer. "
    "If the answer is not in the context or the conversation, say you do not know. "
    "Prefer the retrieved context when it conflicts with the conversation. "
    "Keep responses concise and grounded."
)


def create_app() -> Flask:
    app = Flask(__name__, template_folder=str(TEMPLATE_DIR), static_folder=str(STATIC_DIR))
    init_db()
    ensure_integration_defaults(
        "rag",
        {
            "openai_embed_model": "text-embedding-3-small",
            "openai_chat_model": "gpt-4o-mini",
            "openai_chat_temperature": "0.2",
            "chat_top_k": "5",
            "chat_max_history": "8",
            "chat_max_context_chars": "12000",
            "chat_snippet_chars": "600",
            "chat_context_budget_tokens": "8000",
            "chroma_host": "localhost",
            "chroma_port": "8000",
            "web_port": "5050",
        },
    )

    @app.get("/")
    def index() -> str:
        config = load_config()
        github_settings = load_integration_settings("github")
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
        chroma_host = rag_settings.get("chroma_host") or config.chroma_host
        chroma_port = rag_settings.get("chroma_port") or config.chroma_port
        openai_api_key = rag_settings.get("openai_api_key") or (config.openai_api_key or "")
        openai_embed_model = (
            rag_settings.get("openai_embed_model") or config.openai_embedding_model
        )
        openai_chat_model = rag_settings.get("openai_chat_model") or config.chat_model
        openai_chat_temperature = (
            rag_settings.get("openai_chat_temperature") or config.chat_temperature
        )
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
        return render_template(
            "index.html",
            default_top_k=config.chat_top_k,
            has_api_key=bool(config.openai_api_key),
            github_settings=github_settings,
            github_connected=bool(
                (github_settings.get("pat") or "").strip()
                or (github_settings.get("ssh_key_path") or "").strip()
            ),
            rag_settings=rag_settings,
            chroma_host=chroma_host,
            chroma_port=chroma_port,
            openai_api_key=openai_api_key,
            openai_embed_model=openai_embed_model,
            openai_chat_model=openai_chat_model,
            openai_chat_temperature=openai_chat_temperature,
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
            sources=sources,
            sources_notice=sources_notice,
            active_nav="sources",
        )

    @app.get("/sources/new")
    def sources_new() -> str:
        github_settings = load_integration_settings("github")
        return render_template(
            "source_new.html",
            github_connected=bool((github_settings.get("pat") or "").strip()),
            active_nav="sources",
        )

    @app.get("/sources/<int:source_id>")
    def sources_detail(source_id: int) -> str:
        source = get_source(source_id)
        if not source:
            return redirect(url_for("sources_index", notice="source_error"))
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
            active_nav="sources",
        )

    @app.get("/tasks")
    def tasks_index() -> str:
        tasks = list_tasks()
        sources = list_sources()
        sources_by_id = {source.id: source for source in sources}
        notice = request.args.get("notice", "").strip().lower()
        tasks_notice = None
        if notice == "task_deleted":
            tasks_notice = {"type": "success", "message": "Task deleted."}
        return render_template(
            "tasks.html",
            tasks=tasks,
            sources_by_id=sources_by_id,
            tasks_notice=tasks_notice,
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
        return render_template(
            "task_detail.html",
            task=task,
            source=source,
            meta=meta,
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
        openai_api_key = request.form.get("openai_api_key", "").strip()
        openai_embed_model = request.form.get("openai_embed_model", "").strip()
        openai_chat_model = request.form.get("openai_chat_model", "").strip()
        openai_chat_temperature = request.form.get("openai_chat_temperature", "").strip()
        chat_top_k = request.form.get("chat_top_k", "").strip()
        chat_max_history = request.form.get("chat_max_history", "").strip()
        chat_max_context_chars = request.form.get("chat_max_context_chars", "").strip()
        chat_snippet_chars = request.form.get("chat_snippet_chars", "").strip()
        chat_context_budget_tokens = request.form.get(
            "chat_context_budget_tokens", ""
        ).strip()
        web_port = request.form.get("web_port", "").strip()
        payload = {
            "chroma_host": chroma_host,
            "chroma_port": _coerce_int_str(chroma_port),
            "openai_api_key": openai_api_key,
            "openai_embed_model": openai_embed_model,
            "openai_chat_model": openai_chat_model,
            "openai_chat_temperature": _coerce_float_str(openai_chat_temperature),
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

    @app.post("/sources")
    def add_source():
        name = request.form.get("source_name", "").strip()
        kind = request.form.get("source_kind", "").strip().lower()
        local_path = request.form.get("source_local_path", "").strip()
        git_repo = request.form.get("source_git_repo", "").strip()
        git_branch = request.form.get("source_git_branch", "").strip()
        try:
            source = create_source(
                SourceInput(
                    name=name,
                    kind=kind,
                    local_path=local_path,
                    git_repo=git_repo,
                    git_branch=git_branch,
                )
            )
        except Exception:
            return redirect(url_for("sources_index", notice="source_error"))
        return redirect(url_for("sources_detail", source_id=source.id))

    @app.post("/sources/<int:source_id>/delete")
    def remove_source(source_id: int):
        try:
            delete_source(source_id)
        except Exception:
            return redirect(url_for("sources_index", notice="source_error"))
        return redirect(url_for("sources_index", notice="source_deleted"))

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

    @app.get("/api/index")
    def index_status() -> tuple[Any, int]:
        return jsonify(_index_snapshot()), 200

    @app.post("/api/index")
    def index_now() -> tuple[Any, int]:
        payload = request.get_json(silent=True) or {}
        reset = bool(payload.get("reset"))
        started = _start_index(reset, source_id=None)
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
        started = _start_index(reset, source_id=source_id)
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

        if not message:
            return jsonify({"error": "Message is required."}), 400

        if not config.openai_api_key:
            return jsonify({"error": "OPENAI_API_KEY is not set."}), 400

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

        messages = _build_messages(history, message, context, config.chat_max_history)

        try:
            reply = _call_openai(
                config.openai_api_key,
                messages,
                config.chat_model,
                config.chat_temperature,
            )
        except Exception as exc:
            return jsonify({"error": f"OpenAI request failed: {exc}"}), 500

        response = {
            "reply": reply,
            "sources": sources,
            "model": config.chat_model,
            "top_k": top_k,
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
                }
            ),
            200,
        )

    return app


def _task_kind_label(kind: str | None) -> str:
    if not kind:
        return "Task"
    return {"index": "Index"}.get(kind, kind)


def _task_payload(task) -> dict[str, Any]:
    return {
        "id": task.id,
        "kind": task.kind,
        "status": task.status,
        "running": task.status in TASK_ACTIVE_STATUSES,
        "source_id": task.source_id,
        "created_at": format_dt(task.created_at),
        "started_at": format_dt(task.started_at),
        "finished_at": format_dt(task.finished_at),
        "celery_task_id": task.celery_task_id,
        "output": task.output or "",
        "error": task.error or "",
    }


def _index_snapshot(source=None) -> dict[str, Any]:
    if not source:
        active = active_task(kind=TASK_KIND_INDEX)
        if active:
            return {
                "running": True,
                "source_id": active.source_id,
                "mode": "source" if active.source_id else "all",
                "last_started_at": format_dt(active.started_at or active.created_at),
                "last_finished_at": None,
                "last_error": None,
            }
        latest = latest_task(kind=TASK_KIND_INDEX)
        if latest:
            return {
                "running": False,
                "source_id": latest.source_id,
                "mode": "source" if latest.source_id else "all",
                "last_started_at": format_dt(latest.started_at),
                "last_finished_at": format_dt(latest.finished_at),
                "last_error": latest.error,
            }
        finished = latest_finished_task(kind=TASK_KIND_INDEX)
        return {
            "running": False,
            "source_id": finished.source_id if finished else None,
            "mode": "source" if (finished and finished.source_id) else None,
            "last_started_at": format_dt(finished.started_at) if finished else None,
            "last_finished_at": format_dt(finished.finished_at) if finished else None,
            "last_error": finished.error if finished else None,
        }

    active = active_task(kind=TASK_KIND_INDEX, source_id=source.id)
    running = active is not None
    return {
        "running": running,
        "source_id": getattr(source, "id", None),
        "mode": "source",
        "last_started_at": format_dt(active.started_at or active.created_at)
        if running
        else None,
        "last_finished_at": None,
        "last_error": getattr(source, "last_error", None),
        "last_indexed_at": source.last_indexed_at.isoformat()
        if getattr(source, "last_indexed_at", None)
        else None,
    }


def _start_index(reset: bool, source_id: int | None) -> bool:
    if has_active_task(kind=TASK_KIND_INDEX):
        return False
    meta = {"reset": bool(reset)}
    if source_id is not None:
        meta["source_id"] = source_id
    task = create_task(kind=TASK_KIND_INDEX, source_id=source_id, meta=meta)
    try:
        result = run_index_task.apply_async(
            args=[task.id, source_id, reset],
            ignore_result=True,
        )
    except Exception as exc:
        mark_task_finished(
            task.id,
            status=TASK_STATUS_FAILED,
            output="Failed to enqueue task.",
            error=str(exc),
        )
        return False
    if result is not None:
        set_task_celery_id(task.id, getattr(result, "id", None))
    return True


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
    embedding_fn = OpenAIEmbeddingFunction(
        api_key=config.openai_api_key,
        model_name=config.openai_embedding_model,
    )
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
    history: Any, message: str, context: str, max_history: int
) -> list[dict[str, str]]:
    trimmed = _trim_history(history, max_history)
    user_prompt = _build_user_prompt(message, context)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
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
        "Answer the question using the conversation so far and the context below.\n\n"
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


def _call_openai(
    api_key: str,
    messages: list[dict[str, str]],
    model: str,
    temperature: float,
) -> str:
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
    )
    choice = response.choices[0]
    content = choice.message.content if choice and choice.message else None
    return content.strip() if content else ""


if __name__ == "__main__":
    app = create_app()
    config = load_config()
    port = config.web_port
    app.run(host="0.0.0.0", port=port, debug=False)
