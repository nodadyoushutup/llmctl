from __future__ import annotations

import base64
from io import BytesIO
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import uuid
from pathlib import Path, PurePosixPath
from datetime import datetime, timezone
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import selectinload

from services.celery_app import HUGGINGFACE_DOWNLOAD_QUEUE, celery_app
from services.code_review import (
    CODE_REVIEW_FAIL_EMOJI,
    CODE_REVIEW_PASS_EMOJI,
    CODE_REVIEW_ROLE_PROMPT,
    CODE_REVIEW_TASK_KIND,
    ensure_code_reviewer_agent,
    ensure_code_reviewer_role,
)
from core.config import Config
from core.db import session_scope, utcnow
from chat.contracts import (
    CHAT_REASON_SELECTOR_SCOPE,
    RAGContractError,
    RAG_HEALTH_CONFIGURED_UNHEALTHY as CHAT_RAG_HEALTH_CONFIGURED_UNHEALTHY,
)
from chat.rag_client import get_rag_contract_client
from chat.runtime import (
    CHAT_DEFAULT_THREAD_TITLE,
    CHAT_RESPONSE_COMPLEXITY_MEDIUM as CHAT_RESPONSE_COMPLEXITY_DEFAULT,
    archive_thread as archive_chat_thread,
    clear_thread as clear_chat_thread,
    create_thread as create_chat_thread,
    delete_thread as delete_chat_thread,
    execute_turn as execute_chat_turn,
    normalize_response_complexity as normalize_chat_response_complexity,
    get_thread as get_chat_thread,
    list_activity as list_chat_activity,
    list_threads as list_chat_threads,
    restore_thread as restore_chat_thread,
    update_thread_config as update_chat_thread_config,
)
from chat.settings import (
    load_chat_default_settings_payload,
    load_chat_runtime_settings_payload,
    save_chat_default_settings,
    save_chat_runtime_settings,
)
from services.integrations import (
    GOOGLE_CLOUD_PROVIDER,
    GOOGLE_WORKSPACE_PROVIDER,
    LLM_PROVIDER_LABELS,
    LLM_PROVIDERS,
    NODE_EXECUTOR_DOCKER_API_STALL_SECONDS_CHOICES,
    NODE_EXECUTOR_DOCKER_PULL_POLICY_CHOICES,
    NODE_EXECUTOR_FALLBACK_PROVIDER_CHOICES,
    NODE_EXECUTOR_PROVIDER_CHOICES,
    NODE_SKILL_BINDING_MODE_CHOICES,
    NODE_SKILL_BINDING_MODE_REJECT,
    NODE_SKILL_BINDING_MODE_WARN,
    integration_overview as _integration_overview,
    load_integration_settings as _load_integration_settings,
    load_node_executor_settings,
    node_executor_effective_config_summary,
    migrate_legacy_google_integration_settings,
    normalize_node_skill_binding_mode,
    resolve_default_model_id,
    resolve_enabled_llm_providers,
    resolve_llm_provider,
    resolve_node_skill_binding_mode,
    save_node_executor_settings,
    save_integration_settings as _save_integration_settings,
)
from services.instruction_adapters import (
    NON_FRONTIER_DEFAULT_INSTRUCTION_FILENAME,
    is_frontier_instruction_provider,
    validate_agent_markdown_filename,
)
from core.models import (
    Agent,
    AgentPriority,
    AgentTask,
    Attachment,
    FLOWCHART_EDGE_MODE_CHOICES,
    FLOWCHART_NODE_TYPE_CHOICES,
    FLOWCHART_NODE_TYPE_DECISION,
    FLOWCHART_NODE_TYPE_END,
    FLOWCHART_NODE_TYPE_FLOWCHART,
    FLOWCHART_NODE_TYPE_MEMORY,
    FLOWCHART_NODE_TYPE_MILESTONE,
    FLOWCHART_NODE_TYPE_PLAN,
    FLOWCHART_NODE_TYPE_RAG,
    FLOWCHART_NODE_TYPE_START,
    FLOWCHART_NODE_TYPE_TASK,
    Flowchart,
    FlowchartEdge,
    FlowchartNode,
    FlowchartRun,
    FlowchartRunNode,
    LLMModel,
    Memory,
    MCP_SERVER_TYPE_CUSTOM,
    MCP_SERVER_TYPE_INTEGRATED,
    MCPServer,
    Milestone,
    MILESTONE_HEALTH_CHOICES,
    MILESTONE_HEALTH_GREEN,
    MILESTONE_PRIORITY_CHOICES,
    MILESTONE_PRIORITY_MEDIUM,
    MILESTONE_STATUS_CHOICES,
    MILESTONE_STATUS_DONE,
    MILESTONE_STATUS_PLANNED,
    Plan,
    PlanStage,
    PlanTask,
    Role,
    Run,
    RUN_ACTIVE_STATUSES,
    SKILL_STATUS_ACTIVE,
    SKILL_STATUS_ARCHIVED,
    SKILL_STATUS_CHOICES,
    Skill,
    SkillFile,
    SkillVersion,
    Script,
    agent_skill_bindings,
    agent_task_attachments,
    agent_task_scripts,
    ensure_legacy_skill_script_writable,
    flowchart_node_mcp_servers,
    flowchart_node_attachments,
    flowchart_node_skills,
    flowchart_node_scripts,
    is_legacy_skill_script_type,
    task_template_attachments,
    SCRIPT_TYPE_CHOICES,
    SCRIPT_TYPE_LABELS,
    SCRIPT_TYPE_INIT,
    SCRIPT_TYPE_POST_INIT,
    SCRIPT_TYPE_POST_RUN,
    SCRIPT_TYPE_PRE_INIT,
    SYSTEM_MANAGED_MCP_SERVER_KEYS,
    TaskTemplate,
)
from core.mcp_config import format_mcp_config, validate_server_key
from core.integrated_mcp import sync_integrated_mcp_servers
from core.prompt_envelope import (
    build_prompt_envelope,
    parse_prompt_input,
    serialize_prompt_envelope,
)
from core.task_integrations import (
    TASK_INTEGRATION_KEYS,
    TASK_INTEGRATION_LABELS,
    TASK_INTEGRATION_OPTIONS,
    parse_task_integration_keys,
    serialize_task_integration_keys,
    validate_task_integration_keys,
)
from core.quick_node import (
    build_quick_node_agent_profile,
    build_quick_node_system_contract,
)
from core.vllm_models import discover_vllm_local_models
from rag.engine.config import load_config as load_rag_config
from rag.domain import (
    RAG_FLOWCHART_MODE_CHOICES as RAG_NODE_MODE_CHOICES,
    RAG_FLOWCHART_MODE_DELTA_INDEX as RAG_NODE_MODE_DELTA_INDEX,
    RAG_FLOWCHART_MODE_FRESH_INDEX as RAG_NODE_MODE_FRESH_INDEX,
    RAG_FLOWCHART_MODE_QUERY as RAG_NODE_MODE_QUERY,
    RAG_HEALTH_CONFIGURED_UNHEALTHY as RAG_DOMAIN_HEALTH_CONFIGURED_UNHEALTHY,
    RAG_HEALTH_UNCONFIGURED as RAG_DOMAIN_HEALTH_UNCONFIGURED,
    list_collection_contract as rag_list_collection_contract,
    normalize_collection_selection as rag_normalize_collection_selection,
    rag_health_snapshot as rag_domain_health_snapshot,
)
from rag.integrations.google_drive_sync import (
    service_account_email as _google_drive_service_account_email,
)
from rag.repositories.settings import (
    ensure_rag_setting_defaults as _ensure_rag_setting_defaults,
    load_rag_settings as _load_rag_settings,
    save_rag_settings as _save_rag_settings,
)
from storage.script_storage import read_script_file, remove_script_file, write_script_file
from storage.attachment_storage import remove_attachment_file, write_attachment_file
from core.task_stages import TASK_STAGE_ORDER
from core.task_kinds import (
    QUICK_TASK_KIND,
    RAG_QUICK_DELTA_TASK_KIND,
    RAG_QUICK_INDEX_TASK_KIND,
    is_quick_rag_task_kind,
    is_quick_task_kind,
    task_kind_label,
)
from services.skills import (
    MAX_SKILL_FILE_BYTES,
    SkillPackage,
    SkillPackageValidationError,
    build_skill_package,
    build_skill_package_from_directory,
    encode_binary_skill_content,
    export_skill_package_from_db,
    format_validation_errors,
    import_skill_package_to_db,
    is_binary_skill_content,
    load_skill_bundle,
    serialize_skill_bundle,
)
from services.tasks import (
    build_one_off_output_contract,
    claude_runtime_diagnostics,
    run_agent,
    run_agent_task,
    run_flowchart,
    run_huggingface_download_task,
)
from services.huggingface_downloads import (
    model_directory_has_downloaded_contents as _shared_model_directory_has_downloaded_contents,
    run_huggingface_model_download as _shared_run_huggingface_model_download,
    summarize_subprocess_error as _shared_summarize_subprocess_error,
    vllm_local_model_container_path as _shared_vllm_local_model_container_path,
    vllm_local_model_directory as _shared_vllm_local_model_directory,
)

bp = Blueprint("agents", __name__, template_folder="templates")
logger = logging.getLogger(__name__)

DEFAULT_TASKS_PER_PAGE = 10
TASKS_PER_PAGE_OPTIONS = (10, 25, 50, 100)
DEFAULT_RUNS_PER_PAGE = DEFAULT_TASKS_PER_PAGE
RUNS_PER_PAGE_OPTIONS = TASKS_PER_PAGE_OPTIONS
FLOWCHART_NODE_TYPE_SET = set(FLOWCHART_NODE_TYPE_CHOICES)
DOCKER_CHROMA_HOST_ALIASES = {"llmctl-chromadb", "chromadb"}
CODEX_MODEL_PREFERENCE = (
    "gpt-5.2-codex",
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
    "gpt-5.2",
    "gpt-5.1-codex-max",
    "gpt-5.1-codex-mini",
)
GEMINI_MODEL_OPTIONS = (
    "gemini-3-pro-preview",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
)
CLAUDE_MODEL_OPTIONS = (
    "claude-sonnet-4-5",
    "claude-opus-4-1",
    "claude-3-7-sonnet-latest",
    "claude-3-5-haiku-latest",
)
QWEN_DEFAULT_MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"
QWEN_DEFAULT_MODEL_DIR_NAME = "qwen2.5-0.5b-instruct"
HUGGINGFACE_REPO_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$"
)
HUGGINGFACE_DOWNLOAD_JOB_STATUS_ACTIVE = {"queued", "running"}
HUGGINGFACE_DOWNLOAD_JOB_TTL_SECONDS = 6 * 60 * 60
HUGGINGFACE_DOWNLOAD_JOB_MAX_RECORDS = 64
_huggingface_download_jobs_lock = threading.Lock()
_huggingface_download_jobs: dict[str, dict[str, object]] = {}
IMAGE_ATTACHMENT_EXTENSIONS = {
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".webp",
}
SCRIPT_TYPE_FIELDS = {
    SCRIPT_TYPE_PRE_INIT: "pre_init_script_ids",
    SCRIPT_TYPE_INIT: "init_script_ids",
    SCRIPT_TYPE_POST_INIT: "post_init_script_ids",
    SCRIPT_TYPE_POST_RUN: "post_run_script_ids",
}
SCRIPT_TYPE_WRITE_CHOICES = tuple(
    (value, label)
    for value, label in SCRIPT_TYPE_CHOICES
    if not is_legacy_skill_script_type(value)
)
RAG_DB_PROVIDER_CHOICES = ("chroma",)
RAG_MODEL_PROVIDER_CHOICES = ("openai", "gemini")
SKILL_UPLOAD_MAX_FILE_BYTES = MAX_SKILL_FILE_BYTES
SKILL_UPLOAD_ALLOWED_EXTENSIONS = {
    ".bat",
    ".bash",
    ".cfg",
    ".conf",
    ".css",
    ".csv",
    ".docx",
    ".env",
    ".gif",
    ".html",
    ".ini",
    ".ipynb",
    ".java",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".log",
    ".md",
    ".pdf",
    ".png",
    ".pptx",
    ".ps1",
    ".py",
    ".rb",
    ".rst",
    ".scss",
    ".sh",
    ".sql",
    ".svg",
    ".toml",
    ".ts",
    ".tsv",
    ".tsx",
    ".txt",
    ".webp",
    ".xml",
    ".yaml",
    ".yml",
    ".zsh",
}
SKILL_UPLOAD_BINARY_EXTENSIONS = {
    ".docx",
    ".gif",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".pptx",
    ".webp",
}
SKILL_UPLOAD_ALLOWED_BASENAMES = {
    ".env",
    ".gitignore",
    "dockerfile",
    "license",
    "makefile",
    "notice",
    "readme",
}
SKILL_UPLOAD_BLOCKED_EXTENSIONS = {
    ".apk",
    ".appimage",
    ".bin",
    ".com",
    ".dll",
    ".dmg",
    ".exe",
    ".iso",
    ".jar",
    ".msi",
    ".scr",
    ".so",
}
SKILL_UPLOAD_CONFLICT_MODES = {"ask", "replace", "keep_both", "skip"}
SKILL_MUTABLE_SOURCE_TYPES = {"ui", "import", "local", "path", "upload", "legacy_skill_script"}
RAG_OPENAI_EMBED_MODEL_OPTIONS = (
    "text-embedding-3-small",
    "text-embedding-3-large",
)
RAG_OPENAI_CHAT_MODEL_OPTIONS = (
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4.1-mini",
    "gpt-4.1",
)
RAG_GEMINI_EMBED_MODEL_OPTIONS = (
    "models/gemini-embedding-001",
    "models/text-embedding-004",
)
RAG_GEMINI_CHAT_MODEL_OPTIONS = GEMINI_MODEL_OPTIONS
RAG_CHAT_RESPONSE_STYLE_CHOICES = ("low", "medium", "high")
RAG_CHAT_RESPONSE_STYLE_ALIASES = {
    "concise": "low",
    "brief": "low",
    "balanced": "medium",
    "detailed": "high",
    "verbose": "high",
}
NODE_SKILL_BINDING_WRITE_ERROR = (
    "Node-level skill binding is disabled. Assign skills on the Agent instead."
)
NODE_SKILL_BINDING_WRITE_WARNING = (
    "Node-level skill payloads are deprecated and ignored. Assign skills on the Agent."
)

MILESTONE_STATUS_LABELS = {
    "planned": "planned",
    "in_progress": "in progress",
    "at_risk": "at risk",
    "done": "done",
    "archived": "archived",
}
MILESTONE_STATUS_CLASSES = {
    "planned": "status-idle",
    "in_progress": "status-running",
    "at_risk": "status-warning",
    "done": "status-success",
    "archived": "status-idle",
}
MILESTONE_PRIORITY_LABELS = {
    "low": "low",
    "medium": "medium",
    "high": "high",
}
MILESTONE_HEALTH_LABELS = {
    "green": "green",
    "yellow": "yellow",
    "red": "red",
}
MILESTONE_HEALTH_CLASSES = {
    "green": "status-success",
    "yellow": "status-warning",
    "red": "status-failed",
}
MILESTONE_STATUS_OPTIONS = tuple(
    (value, MILESTONE_STATUS_LABELS.get(value, value)) for value in MILESTONE_STATUS_CHOICES
)
MILESTONE_PRIORITY_OPTIONS = tuple(
    (value, MILESTONE_PRIORITY_LABELS.get(value, value))
    for value in MILESTONE_PRIORITY_CHOICES
)
MILESTONE_HEALTH_OPTIONS = tuple(
    (value, MILESTONE_HEALTH_LABELS.get(value, value)) for value in MILESTONE_HEALTH_CHOICES
)
SKILL_STATUS_LABELS = {
    "draft": "draft",
    "active": "active",
    "archived": "archived",
}
SKILL_STATUS_OPTIONS = tuple(
    (value, SKILL_STATUS_LABELS.get(value, value)) for value in SKILL_STATUS_CHOICES
)

FLOWCHART_NODE_TYPE_WITH_REF = {
    FLOWCHART_NODE_TYPE_FLOWCHART,
    FLOWCHART_NODE_TYPE_TASK,
    FLOWCHART_NODE_TYPE_PLAN,
    FLOWCHART_NODE_TYPE_MILESTONE,
    FLOWCHART_NODE_TYPE_MEMORY,
}
FLOWCHART_NODE_TYPE_REQUIRES_REF = {
    FLOWCHART_NODE_TYPE_FLOWCHART,
    FLOWCHART_NODE_TYPE_PLAN,
    FLOWCHART_NODE_TYPE_MILESTONE,
}
FLOWCHART_NODE_UTILITY_COMPATIBILITY = {
    FLOWCHART_NODE_TYPE_START: {
        "model": False,
        "mcp": False,
        "scripts": False,
        "skills": False,
        "attachments": False,
    },
    FLOWCHART_NODE_TYPE_END: {
        "model": False,
        "mcp": False,
        "scripts": False,
        "skills": False,
        "attachments": False,
    },
    FLOWCHART_NODE_TYPE_FLOWCHART: {
        "model": False,
        "mcp": False,
        "scripts": False,
        "skills": False,
        "attachments": False,
    },
    FLOWCHART_NODE_TYPE_TASK: {
        "model": True,
        "mcp": True,
        "scripts": True,
        "skills": True,
        "attachments": True,
    },
    FLOWCHART_NODE_TYPE_PLAN: {
        "model": True,
        "mcp": True,
        "scripts": True,
        "skills": True,
        "attachments": True,
    },
    FLOWCHART_NODE_TYPE_MILESTONE: {
        "model": True,
        "mcp": True,
        "scripts": True,
        "skills": True,
        "attachments": True,
    },
    FLOWCHART_NODE_TYPE_MEMORY: {
        "model": True,
        "mcp": True,
        "scripts": True,
        "skills": True,
        "attachments": True,
    },
    FLOWCHART_NODE_TYPE_DECISION: {
        "model": False,
        "mcp": True,
        "scripts": True,
        "skills": True,
        "attachments": False,
    },
    FLOWCHART_NODE_TYPE_RAG: {
        "model": True,
        "mcp": False,
        "scripts": False,
        "skills": False,
        "attachments": False,
    },
}
FLOWCHART_END_MAX_OUTGOING_EDGES = 0
FLOWCHART_DEFAULT_START_X = 280.0
FLOWCHART_DEFAULT_START_Y = 170.0


def _parse_agent_payload(raw_json: str) -> tuple[str, str | None, str | None]:
    payload = json.loads(raw_json)

    prompt_text = None
    name = None

    if isinstance(payload, dict):
        name_value = payload.get("name") or payload.get("title")
        if isinstance(name_value, str):
            name = name_value.strip() or None
        prompt_value = payload.get("prompt")
        if isinstance(prompt_value, str):
            prompt_text = prompt_value
        formatted = json.dumps(payload, indent=2, sort_keys=True)
        return formatted, prompt_text, name

    if isinstance(payload, str):
        return raw_json.strip(), payload, None

    formatted = json.dumps(payload, indent=2, sort_keys=True)
    return formatted, None, None


def _parse_task_prompt(raw_prompt: str | None) -> tuple[str | None, str | None]:
    if not raw_prompt:
        return None, None
    if not raw_prompt.strip():
        return raw_prompt, None
    prompt_text, payload = parse_prompt_input(raw_prompt)
    if payload is None:
        return raw_prompt, None
    formatted = json.dumps(payload, indent=2, sort_keys=True)
    return prompt_text or None, formatted


def _quick_rag_task_context(task: AgentTask) -> dict[str, object]:
    _prompt_text, payload = parse_prompt_input(task.prompt)
    if not isinstance(payload, dict):
        return {}
    task_context = payload.get("task_context")
    if not isinstance(task_context, dict):
        return {}
    quick_context = task_context.get("rag_quick_run")
    if not isinstance(quick_context, dict):
        return {}
    return quick_context


def _quick_rag_task_display_name(task: AgentTask) -> str:
    base_label = task_kind_label(task.kind)
    quick_context = _quick_rag_task_context(task)
    source_name = str(quick_context.get("source_name") or "").strip()
    if source_name:
        return f"{base_label} ({source_name})"
    return base_label


def _sync_quick_rag_task_from_index_job(_session, _task: AgentTask) -> None:
    # Legacy RAG index jobs were removed; quick RAG activity now relies on node state.
    return


def _parse_role_details(raw_json: str) -> str:
    if not raw_json:
        return "{}"
    payload = json.loads(raw_json)
    if not isinstance(payload, dict):
        raise ValueError("Role details must be a JSON object.")
    return json.dumps(payload, indent=2, sort_keys=True)


def _ordered_agent_priorities(agent: Agent) -> list[AgentPriority]:
    priorities = list(agent.priorities or [])
    priorities.sort(
        key=lambda entry: (
            int(entry.position) if entry.position is not None else 2**31 - 1,
            int(entry.id),
        )
    )
    return priorities


def _reindex_agent_priorities(priorities: list[AgentPriority]) -> None:
    for index, priority in enumerate(priorities, start=1):
        priority.position = index


def _save_uploaded_attachments(
    session,
    uploads,
) -> list[Attachment]:
    attachments: list[Attachment] = []
    for upload in uploads:
        if not upload or not upload.filename:
            continue
        file_name = Path(upload.filename).name if upload.filename else ""
        if not file_name or file_name in {".", ".."}:
            raise ValueError("Attachment file name is invalid.")
        content = upload.read()
        content_type = (upload.mimetype or "").strip() or None
        attachment = Attachment.create(
            session,
            file_name=file_name,
            file_path=None,
            content_type=content_type,
            size_bytes=len(content) if content is not None else 0,
        )
        path = write_attachment_file(attachment.id, file_name, content)
        attachment.file_path = str(path)
        attachments.append(attachment)
    return attachments


def _attach_attachments(target, attachments: list[Attachment]) -> None:
    if not attachments:
        return
    existing_ids = {item.id for item in getattr(target, "attachments", [])}
    for attachment in attachments:
        if attachment.id in existing_ids:
            continue
        target.attachments.append(attachment)


def _attachment_in_use(session, attachment_id: int) -> bool:
    task_refs = session.execute(
        select(func.count())
        .select_from(agent_task_attachments)
        .where(agent_task_attachments.c.attachment_id == attachment_id)
    ).scalar_one()
    if task_refs:
        return True
    template_refs = session.execute(
        select(func.count())
        .select_from(task_template_attachments)
        .where(task_template_attachments.c.attachment_id == attachment_id)
    ).scalar_one()
    if template_refs:
        return True
    flowchart_node_refs = session.execute(
        select(func.count())
        .select_from(flowchart_node_attachments)
        .where(flowchart_node_attachments.c.attachment_id == attachment_id)
    ).scalar_one()
    if flowchart_node_refs:
        return True
    return False


def _unlink_attachment(session, attachment_id: int) -> None:
    session.execute(
        delete(agent_task_attachments).where(
            agent_task_attachments.c.attachment_id == attachment_id
        )
    )
    session.execute(
        delete(task_template_attachments).where(
            task_template_attachments.c.attachment_id == attachment_id
        )
    )
    session.execute(
        delete(flowchart_node_attachments).where(
            flowchart_node_attachments.c.attachment_id == attachment_id
        )
    )


def _delete_attachment_if_unused(session, attachment: Attachment) -> str | None:
    if _attachment_in_use(session, attachment.id):
        return None
    file_path = attachment.file_path
    session.delete(attachment)
    return file_path


def _is_image_attachment(attachment: Attachment) -> bool:
    if attachment.content_type and attachment.content_type.startswith("image/"):
        return True
    suffix = Path(attachment.file_name or "").suffix.lower()
    return bool(suffix) and suffix in IMAGE_ATTACHMENT_EXTENSIONS


def _load_prompt_payload(prompt_json: str | None, prompt_text: str | None) -> object | None:
    if prompt_json:
        try:
            return json.loads(prompt_json)
        except json.JSONDecodeError:
            pass
    if prompt_text:
        return prompt_text
    return prompt_json


def _load_role_details(role: Role) -> dict[str, object]:
    if not role.details_json:
        return {}
    try:
        payload = json.loads(role.details_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_role_payload(role: Role) -> dict[str, object]:
    return {
        "name": role.name,
        "description": role.description or "",
        "details": _load_role_details(role),
    }


def _build_agent_payload(agent: Agent) -> dict[str, object]:
    description = agent.description or agent.name or ""
    return {
        "id": agent.id,
        "name": agent.name,
        "description": description,
    }


def _build_agent_prompt_payload(agent: Agent) -> object | None:
    agent_payload = _build_agent_payload(agent)
    role = agent.role
    if agent.role_id and role is not None:
        agent_payload["role"] = _build_role_payload(role)
        return agent_payload
    return agent_payload


def _group_scripts_by_type(scripts: list[Script]) -> dict[str, list[Script]]:
    grouped = {script_type: [] for script_type in SCRIPT_TYPE_FIELDS}
    for script in scripts:
        grouped.setdefault(script.script_type, []).append(script)
    for script_list in grouped.values():
        script_list.sort(key=lambda item: item.file_name.lower())
    return grouped


def _group_selected_scripts_by_type(
    scripts: list[Script],
) -> dict[str, list[Script]]:
    grouped = {script_type: [] for script_type in SCRIPT_TYPE_FIELDS}
    for script in scripts:
        grouped.setdefault(script.script_type, []).append(script)
    return grouped


def _parse_script_selection() -> tuple[dict[str, list[int]], list[int], str | None]:
    script_ids_by_type: dict[str, list[int]] = {}
    try:
        for script_type, field_name in SCRIPT_TYPE_FIELDS.items():
            values = [value.strip() for value in request.form.getlist(field_name)]
            ids: list[int] = []
            for value in values:
                if not value:
                    continue
                if not value.isdigit():
                    raise ValueError("Script selection is invalid.")
                ids.append(int(value))
            script_ids_by_type[script_type] = ids
    except ValueError as exc:
        return {}, [], str(exc)

    legacy_values = [value.strip() for value in request.form.getlist("script_ids")]
    legacy_ids: list[int] = []
    for value in legacy_values:
        if not value:
            continue
        if not value.isdigit():
            return {}, [], "Script selection is invalid."
        legacy_ids.append(int(value))

    return script_ids_by_type, legacy_ids, None


def _parse_node_integration_selection() -> tuple[list[str], str | None]:
    raw_values = [value.strip() for value in request.form.getlist("integration_keys")]
    selected_keys, invalid_keys = validate_task_integration_keys(raw_values)
    if invalid_keys:
        return [], "Integration selection is invalid."
    return selected_keys, None


def _build_node_integration_options() -> list[dict[str, object]]:
    overview = _integration_overview()
    options: list[dict[str, object]] = []
    for option in TASK_INTEGRATION_OPTIONS:
        key = str(option.get("key") or "").strip().lower()
        if key not in TASK_INTEGRATION_KEYS:
            continue
        label = str(option.get("label") or key)
        description = str(option.get("description") or "")
        provider_overview = overview.get(key)
        connected = False
        if isinstance(provider_overview, dict):
            connected = bool(provider_overview.get("connected"))
        options.append(
            {
                "key": key,
                "label": label,
                "description": description,
                "connected": connected,
            }
        )
    return options


def _resolve_script_selection(
    session,
    script_ids_by_type: dict[str, list[int]],
    legacy_ids: list[int],
) -> tuple[dict[str, list[int]], str | None]:
    has_typed_selection = any(script_ids_by_type.values())
    all_ids: list[int] = []
    if has_typed_selection:
        for ids in script_ids_by_type.values():
            all_ids.extend(ids)
    else:
        all_ids = legacy_ids

    if not all_ids:
        return {script_type: [] for script_type in SCRIPT_TYPE_FIELDS}, None

    if len(all_ids) != len(set(all_ids)):
        return {}, "Duplicate scripts are not allowed."

    scripts = (
        session.execute(select(Script).where(Script.id.in_(all_ids)))
        .scalars()
        .all()
    )
    scripts_by_id = {script.id: script for script in scripts}
    if len(scripts_by_id) != len(set(all_ids)):
        return {}, "One or more scripts were not found."
    for script in scripts_by_id.values():
        if is_legacy_skill_script_type(script.script_type):
            return {}, "Legacy script_type=skill records are disabled. Use Skills attachments instead."

    if not has_typed_selection:
        grouped = {script_type: [] for script_type in SCRIPT_TYPE_FIELDS}
        for script_id in all_ids:
            script = scripts_by_id[script_id]
            grouped.setdefault(script.script_type, []).append(script_id)
        return grouped, None

    for script_type, ids in script_ids_by_type.items():
        for script_id in ids:
            script = scripts_by_id[script_id]
            if script.script_type != script_type:
                return {}, "Script selection is invalid."

    return script_ids_by_type, None


def _set_task_scripts(
    session,
    task_id: int,
    script_ids_by_type: dict[str, list[int]],
) -> None:
    session.execute(
        delete(agent_task_scripts).where(
            agent_task_scripts.c.agent_task_id == task_id
        )
    )
    rows: list[dict[str, int]] = []
    for ids in script_ids_by_type.values():
        for position, script_id in enumerate(ids, start=1):
            rows.append(
                {
                    "agent_task_id": task_id,
                    "script_id": script_id,
                    "position": position,
                }
            )
    if rows:
        session.execute(agent_task_scripts.insert(), rows)


def _set_flowchart_node_scripts(
    session,
    node_id: int,
    script_ids: list[int],
) -> None:
    session.execute(
        delete(flowchart_node_scripts).where(flowchart_node_scripts.c.flowchart_node_id == node_id)
    )
    if not script_ids:
        return
    rows = [
        {
            "flowchart_node_id": node_id,
            "script_id": script_id,
            "position": position,
        }
        for position, script_id in enumerate(script_ids, start=1)
    ]
    session.execute(flowchart_node_scripts.insert(), rows)


def _set_flowchart_node_skills(
    session,
    node_id: int,
    skill_ids: list[int],
) -> None:
    session.execute(
        delete(flowchart_node_skills).where(flowchart_node_skills.c.flowchart_node_id == node_id)
    )
    if not skill_ids:
        return
    rows = [
        {
            "flowchart_node_id": node_id,
            "skill_id": skill_id,
            "position": position,
        }
        for position, skill_id in enumerate(skill_ids, start=1)
    ]
    session.execute(flowchart_node_skills.insert(), rows)


def _set_flowchart_node_attachments(
    session,
    node_id: int,
    attachment_ids: list[int],
) -> None:
    session.execute(
        delete(flowchart_node_attachments).where(
            flowchart_node_attachments.c.flowchart_node_id == node_id
        )
    )
    if not attachment_ids:
        return
    rows = [
        {
            "flowchart_node_id": node_id,
            "attachment_id": attachment_id,
        }
        for attachment_id in attachment_ids
    ]
    session.execute(flowchart_node_attachments.insert(), rows)


def _set_agent_skills(
    session,
    agent_id: int,
    skill_ids: list[int],
) -> None:
    session.execute(delete(agent_skill_bindings).where(agent_skill_bindings.c.agent_id == agent_id))
    if not skill_ids:
        return
    rows = [
        {
            "agent_id": agent_id,
            "skill_id": skill_id,
            "position": position,
        }
        for position, skill_id in enumerate(skill_ids, start=1)
    ]
    session.execute(agent_skill_bindings.insert(), rows)


def _ordered_agent_skills(agent: Agent) -> list[Skill]:
    return list(agent.skills or [])


def _node_skill_binding_mode(settings: dict[str, str] | None = None) -> str:
    return resolve_node_skill_binding_mode(settings or _load_integration_settings("llm"))


def _node_skill_binding_write_rejected(*, mode: str | None = None) -> tuple[dict[str, object], int]:
    normalized_mode = normalize_node_skill_binding_mode(mode)
    return {
        "error": NODE_SKILL_BINDING_WRITE_ERROR,
        "deprecated": True,
        "node_skill_binding_mode": normalized_mode,
    }, 400


def _node_skill_binding_deprecation_warning(*, mode: str | None = None) -> dict[str, object]:
    normalized_mode = normalize_node_skill_binding_mode(mode)
    return {
        "deprecated": True,
        "ignored": True,
        "warning": NODE_SKILL_BINDING_WRITE_WARNING,
        "node_skill_binding_mode": normalized_mode,
    }


def _log_node_skill_binding_deprecation_event(
    *,
    source: str,
    mode: str,
    flowchart_id: int | None = None,
    node_id: int | None = None,
    extra: dict[str, object] | None = None,
) -> None:
    event: dict[str, object] = {
        "event": "deprecated_node_skill_binding_payload",
        "source": source,
        "mode": normalize_node_skill_binding_mode(mode),
        "path": request.path,
        "method": request.method,
    }
    if flowchart_id is not None:
        event["flowchart_id"] = flowchart_id
    if node_id is not None:
        event["flowchart_node_id"] = node_id
    if extra:
        event.update(extra)
    logger.warning(
        "Deprecated node-level skill payload encountered: %s",
        json.dumps(event, sort_keys=True, default=str),
    )


def _assert_flowchart_node_owner(session, *, flowchart_id: int, node_id: int) -> None:
    flowchart_node = session.get(FlowchartNode, node_id)
    if flowchart_node is None or flowchart_node.flowchart_id != flowchart_id:
        abort(404)


def _read_script_content(script: Script) -> str:
    file_contents = read_script_file(script.file_path)
    if file_contents:
        return file_contents
    return script.content or ""


def _latest_skill_version(skill: Skill) -> SkillVersion | None:
    versions = sorted(list(skill.versions or []), key=lambda item: item.id or 0, reverse=True)
    return versions[0] if versions else None


def _skill_file_content(version: SkillVersion | None, path: str) -> str:
    if version is None:
        return ""
    for entry in version.files or []:
        if entry.path == path:
            return entry.content or ""
    return ""


def _default_skill_markdown(
    *,
    name: str,
    display_name: str,
    description: str,
    version: str,
    status: str,
) -> str:
    title = display_name or name or "Skill"
    return (
        "---\n"
        f"name: {name}\n"
        f"display_name: {display_name}\n"
        f"description: {description}\n"
        f"version: {version}\n"
        f"status: {status}\n"
        "---\n\n"
        f"# {title}\n"
    )


def _parse_skill_extra_files(raw_payload: str) -> tuple[list[tuple[str, str]], str | None]:
    cleaned = (raw_payload or "").strip()
    if not cleaned:
        return [], None
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return [], "Extra files JSON must be valid JSON."
    if not isinstance(payload, list):
        return [], "Extra files JSON must be an array."
    files: list[tuple[str, str]] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            return [], f"extra_files_json[{index}] must be an object."
        path = item.get("path")
        content = item.get("content")
        if not isinstance(path, str) or not path.strip():
            return [], f"extra_files_json[{index}].path is required."
        if not isinstance(content, str):
            return [], f"extra_files_json[{index}].content must be a string."
        files.append((path.strip(), content))
    return files, None


def _normalize_skill_relative_path(raw_path: str) -> str:
    posix_value = str(raw_path or "").replace("\\", "/")
    rel = PurePosixPath(posix_value)
    if rel.is_absolute():
        return ""
    normalized_parts: list[str] = []
    for part in rel.parts:
        if part in {"", ".", ".."}:
            return ""
        normalized_parts.append(part)
    return "/".join(normalized_parts)


def _is_git_based_skill(skill: Skill) -> bool:
    source_type = str(skill.source_type or "").strip().lower()
    return source_type == "git"


def _skill_upload_path_error(path: str) -> str | None:
    normalized = _normalize_skill_relative_path(path)
    if not normalized:
        return "Upload target paths must be relative and path-safe."
    if normalized == "SKILL.md":
        return "SKILL.md must be edited in the SKILL.md field, not uploaded."
    file_name = PurePosixPath(normalized).name.lower()
    extension = PurePosixPath(normalized).suffix.lower()
    if extension in SKILL_UPLOAD_BLOCKED_EXTENSIONS:
        return f"File extension '{extension}' is blocked."
    if extension in SKILL_UPLOAD_ALLOWED_EXTENSIONS:
        return None
    root_dir = normalized.split("/", 1)[0].lower()
    if not extension and root_dir in {"scripts", "references"}:
        return None
    if not extension and file_name in SKILL_UPLOAD_ALLOWED_BASENAMES:
        return None
    return (
        "Upload file type is not allowed. Allowed files include text/code/docs plus "
        "images, data files, PDF, DOCX, and PPTX."
    )


def _is_skill_upload_binary_path(path: str) -> bool:
    extension = PurePosixPath(path).suffix.lower()
    return extension in SKILL_UPLOAD_BINARY_EXTENSIONS


def _next_skill_keep_both_path(path: str, occupied_paths: set[str]) -> str:
    normalized = _normalize_skill_relative_path(path)
    parent = PurePosixPath(normalized).parent.as_posix()
    if parent == ".":
        parent = ""
    name = PurePosixPath(normalized).name
    suffixes = PurePosixPath(name).suffixes
    suffix = "".join(suffixes)
    stem = name[: -len(suffix)] if suffix else name
    index = 1
    while True:
        candidate_name = f"{stem} ({index}){suffix}"
        candidate_path = f"{parent}/{candidate_name}" if parent else candidate_name
        if candidate_path not in occupied_paths:
            return candidate_path
        index += 1


def _parse_skill_existing_files_draft(
    raw_payload: str,
    *,
    existing_paths: set[str],
) -> tuple[list[dict[str, object]], str | None]:
    if not existing_paths:
        return [], None
    stripped = (raw_payload or "").strip()
    if not stripped:
        return [
            {"original_path": path, "path": path, "delete": False}
            for path in sorted(existing_paths)
        ], None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return [], "Existing files draft payload must be valid JSON."
    if not isinstance(payload, list):
        return [], "Existing files draft payload must be a JSON array."

    parsed: list[dict[str, object]] = []
    seen_paths: set[str] = set()
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            return [], f"existing_files_json[{index}] must be an object."
        original_raw = str(item.get("original_path") or "")
        original_path = _normalize_skill_relative_path(original_raw)
        if not original_path or original_path not in existing_paths:
            return [], f"existing_files_json[{index}].original_path is invalid."
        if original_path in seen_paths:
            return [], f"existing_files_json[{index}].original_path is duplicated."
        seen_paths.add(original_path)

        delete_value = item.get("delete")
        delete_flag = bool(delete_value is True or str(delete_value).strip().lower() in {"1", "true", "yes", "on"})
        target_raw = str(item.get("path") or "")
        target_path = _normalize_skill_relative_path(target_raw) if not delete_flag else ""
        if not delete_flag:
            if not target_path:
                return [], f"existing_files_json[{index}].path is required."
            if target_path == "SKILL.md":
                return [], "Non-SKILL files cannot be renamed to SKILL.md."
        parsed.append(
            {
                "original_path": original_path,
                "path": target_path,
                "delete": delete_flag,
            }
        )

    missing = existing_paths - seen_paths
    if missing:
        return [], "Existing files draft payload is incomplete."
    return parsed, None


def _parse_skill_upload_specs(
    raw_payload: str,
    *,
    upload_count: int,
) -> tuple[list[dict[str, object]], str | None]:
    stripped = (raw_payload or "").strip()
    if upload_count == 0:
        return [], None
    if not stripped:
        return [], "Upload path mapping is required for uploaded files."
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return [], "Upload path mapping must be valid JSON."
    if not isinstance(payload, list):
        return [], "Upload path mapping must be a JSON array."

    specs: list[dict[str, object]] = []
    seen_indexes: set[int] = set()
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            return [], f"upload_specs_json[{index}] must be an object."
        upload_index_raw = item.get("index")
        if not isinstance(upload_index_raw, int):
            return [], f"upload_specs_json[{index}].index must be an integer."
        if upload_index_raw < 0 or upload_index_raw >= upload_count:
            return [], f"upload_specs_json[{index}].index is out of range."
        if upload_index_raw in seen_indexes:
            return [], f"upload_specs_json[{index}].index is duplicated."
        seen_indexes.add(upload_index_raw)

        raw_path = str(item.get("path") or "")
        normalized_path = _normalize_skill_relative_path(raw_path)
        if not normalized_path:
            return [], f"upload_specs_json[{index}].path is required."
        path_error = _skill_upload_path_error(normalized_path)
        if path_error:
            return [], path_error

        conflict_mode = str(item.get("conflict") or "ask").strip().lower()
        if conflict_mode not in SKILL_UPLOAD_CONFLICT_MODES:
            return [], f"upload_specs_json[{index}].conflict must be one of ask/replace/keep_both/skip."

        specs.append(
            {
                "index": upload_index_raw,
                "path": normalized_path,
                "conflict": conflict_mode,
            }
        )

    if len(seen_indexes) != upload_count:
        return [], "Upload path mapping must include each uploaded file exactly once."
    specs.sort(key=lambda item: int(item["index"]))
    return specs, None


def _read_skill_upload_content(path: str, payload: bytes) -> tuple[str | None, str | None]:
    if len(payload) > SKILL_UPLOAD_MAX_FILE_BYTES:
        return None, f"Uploaded file '{path}' exceeds the 10 MB limit."
    if _is_skill_upload_binary_path(path):
        return encode_binary_skill_content(payload), None
    try:
        return payload.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, f"Uploaded file '{path}' must be UTF-8 text for this file type."


def _collect_skill_upload_entries() -> tuple[list[dict[str, object]], str | None]:
    uploaded_files = [
        upload
        for upload in request.files.getlist("upload_files")
        if upload is not None and str(upload.filename or "").strip()
    ]
    specs, parse_error = _parse_skill_upload_specs(
        request.form.get("upload_specs_json", ""),
        upload_count=len(uploaded_files),
    )
    if parse_error:
        return [], parse_error
    if not specs:
        return [], None

    entries: list[dict[str, object]] = []
    for spec in specs:
        index = int(spec["index"])
        upload = uploaded_files[index]
        target_path = str(spec["path"])
        payload = upload.read()
        content, content_error = _read_skill_upload_content(target_path, payload)
        if content_error:
            return [], content_error
        assert content is not None
        entries.append(
            {
                "path": target_path,
                "content": content,
                "conflict": str(spec["conflict"]),
                "file_name": str(upload.filename or "").strip(),
            }
        )
    return entries, None


def _apply_skill_upload_conflicts(
    file_map: dict[str, str],
    upload_entries: list[dict[str, object]],
) -> tuple[dict[str, str], str | None]:
    occupied = set(file_map.keys())
    for entry in upload_entries:
        path = str(entry["path"])
        content = str(entry["content"])
        conflict = str(entry["conflict"] or "ask").strip().lower()
        exists = path in occupied
        if exists:
            if conflict == "replace":
                file_map[path] = content
                continue
            if conflict == "keep_both":
                keep_both_path = _next_skill_keep_both_path(path, occupied)
                file_map[keep_both_path] = content
                occupied.add(keep_both_path)
                continue
            if conflict == "skip":
                continue
            return {}, (
                "Upload conflict requires a choice. Select replace, keep both, or skip "
                f"for '{path}'."
            )
        file_map[path] = content
        occupied.add(path)
    return file_map, None


def _skill_file_preview_content(content: str) -> str:
    if is_binary_skill_content(content):
        return "[Binary file content hidden]"
    if len(content or "") > 5000:
        return content[:5000] + "\n... (truncated)"
    return content or ""


def _build_skill_preview(package: SkillPackage) -> dict[str, object]:
    paths = [entry.path for entry in package.files]
    warnings: list[str] = []
    if not any(path.startswith("scripts/") for path in paths):
        warnings.append("No scripts/ files found; this package is guidance-only.")
    if any(path.startswith("references/") for path in paths):
        warnings.append("references/ files are lazy-loaded and not injected into fallback prompts.")
    if any(path.startswith("assets/") for path in paths):
        warnings.append("assets/ files are stored in package materialization paths only.")

    compatibility_hints = [
        "Native adapter targets: Codex, Claude Code, Gemini CLI.",
        "Fallback mode injects SKILL.md excerpts only (deterministic caps apply).",
    ]
    return {
        "metadata": {
            "name": package.metadata.name,
            "display_name": package.metadata.display_name,
            "description": package.metadata.description,
            "version": package.metadata.version,
            "status": package.metadata.status,
        },
        "manifest_hash": package.manifest_hash,
        "manifest": package.manifest,
        "files": [
            {
                "path": entry.path,
                "size_bytes": entry.size_bytes,
                "checksum": entry.checksum,
            }
            for entry in package.files
        ],
        "warnings": warnings,
        "compatibility_hints": compatibility_hints,
    }


def _human_time(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _parse_milestone_due_date(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.endswith("Z"):
        cleaned = f"{cleaned[:-1]}+00:00"
    try:
        if "T" in cleaned:
            parsed = datetime.fromisoformat(cleaned)
        else:
            parsed = datetime.fromisoformat(f"{cleaned}T00:00:00")
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_completed_at(value: str | None) -> datetime | None:
    return _parse_milestone_due_date(value)


def _normalize_milestone_choice(
    value: str | None,
    *,
    choices: tuple[str, ...],
    fallback: str,
) -> str:
    cleaned = (value or "").strip().lower()
    if cleaned in choices:
        return cleaned
    return fallback


def _parse_milestone_progress(value: str | None) -> int | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return 0
    try:
        parsed = int(cleaned)
    except ValueError:
        return None
    if parsed < 0 or parsed > 100:
        return None
    return parsed


def _milestone_status_value(milestone: Milestone) -> str:
    status = _normalize_milestone_choice(
        milestone.status,
        choices=MILESTONE_STATUS_CHOICES,
        fallback=MILESTONE_STATUS_PLANNED,
    )
    if milestone.completed:
        return MILESTONE_STATUS_DONE
    return status


def _milestone_priority_value(milestone: Milestone) -> str:
    return _normalize_milestone_choice(
        milestone.priority,
        choices=MILESTONE_PRIORITY_CHOICES,
        fallback=MILESTONE_PRIORITY_MEDIUM,
    )


def _milestone_health_value(milestone: Milestone) -> str:
    return _normalize_milestone_choice(
        milestone.health,
        choices=MILESTONE_HEALTH_CHOICES,
        fallback=MILESTONE_HEALTH_GREEN,
    )


def _milestone_progress_value(milestone: Milestone) -> int:
    progress = milestone.progress_percent
    if progress is None:
        return 0
    if progress < 0:
        return 0
    if progress > 100:
        return 100
    return progress


def _milestone_template_context() -> dict[str, object]:
    return {
        "milestone_status_options": MILESTONE_STATUS_OPTIONS,
        "milestone_priority_options": MILESTONE_PRIORITY_OPTIONS,
        "milestone_health_options": MILESTONE_HEALTH_OPTIONS,
        "milestone_status_labels": MILESTONE_STATUS_LABELS,
        "milestone_status_classes": MILESTONE_STATUS_CLASSES,
        "milestone_priority_labels": MILESTONE_PRIORITY_LABELS,
        "milestone_health_labels": MILESTONE_HEALTH_LABELS,
        "milestone_health_classes": MILESTONE_HEALTH_CLASSES,
        "milestone_status_value": _milestone_status_value,
        "milestone_priority_value": _milestone_priority_value,
        "milestone_health_value": _milestone_health_value,
        "milestone_progress_value": _milestone_progress_value,
    }


def _format_bytes(value: int | None) -> str:
    if value is None:
        return "-"
    if value < 1024:
        return f"{value} B"
    size = float(value)
    for unit in ("KB", "MB", "GB", "TB"):
        size /= 1024
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
    return f"{size:.1f} TB"


_STAGE_STATUS_CLASSES = {
    "pending": "status-queued",
    "running": "status-running",
    "completed": "status-success",
    "failed": "status-failed",
    "skipped": "status-idle",
}


def _parse_stage_logs(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items() if value is not None}


def _task_output_for_display(raw: str | None) -> str:
    if not raw:
        return ""
    stripped = raw.strip()
    if not stripped.startswith("{"):
        return raw
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return raw
    if not isinstance(payload, dict):
        return raw
    if str(payload.get("node_type") or "").strip() != FLOWCHART_NODE_TYPE_TASK:
        return raw

    raw_output = payload.get("raw_output")
    if isinstance(raw_output, str) and raw_output.strip():
        return raw_output

    structured_output = payload.get("structured_output")
    if isinstance(structured_output, str) and structured_output.strip():
        return structured_output
    if isinstance(structured_output, dict):
        text_value = structured_output.get("text")
        if isinstance(text_value, str) and text_value.strip():
            return text_value

    return raw


def _build_stage_status_map(
    task_status: str | None,
    current_stage: str | None,
) -> dict[str, str]:
    stage_keys = [stage_key for stage_key, _ in TASK_STAGE_ORDER]
    index_map = {stage_key: index for index, stage_key in enumerate(stage_keys)}
    statuses = {stage_key: "pending" for stage_key in stage_keys}
    if not task_status:
        return statuses
    if task_status == "succeeded":
        return {stage_key: "completed" for stage_key in stage_keys}
    if task_status == "running":
        if current_stage in index_map:
            current_index = index_map[current_stage]
            for stage_key, index in index_map.items():
                if index < current_index:
                    statuses[stage_key] = "completed"
                elif index == current_index:
                    statuses[stage_key] = "running"
        return statuses
    if task_status == "failed":
        if current_stage in index_map:
            current_index = index_map[current_stage]
            for stage_key, index in index_map.items():
                if index < current_index:
                    statuses[stage_key] = "completed"
                elif index == current_index:
                    statuses[stage_key] = "failed"
                else:
                    statuses[stage_key] = "skipped"
        return statuses
    if task_status in {"canceled", "stopped"}:
        if current_stage in index_map:
            current_index = index_map[current_stage]
            for stage_key, index in index_map.items():
                if index < current_index:
                    statuses[stage_key] = "completed"
                else:
                    statuses[stage_key] = "skipped"
        else:
            statuses = {stage_key: "skipped" for stage_key in stage_keys}
        return statuses
    return statuses


def _build_stage_entries(task: AgentTask) -> list[dict[str, str]]:
    stage_logs = _parse_stage_logs(task.stage_logs)
    status_map = _build_stage_status_map(task.status, task.current_stage)
    entries: list[dict[str, str]] = []
    for stage_key, label in TASK_STAGE_ORDER:
        status = status_map.get(stage_key, "pending")
        entries.append(
            {
                "key": stage_key,
                "label": label,
                "status": status,
                "status_label": status.replace("_", " "),
                "status_class": _STAGE_STATUS_CLASSES.get(status, "status-idle"),
                "logs": stage_logs.get(stage_key, ""),
            }
        )
    return entries


def _script_type_label(value: str | None) -> str:
    if not value:
        return "-"
    if is_legacy_skill_script_type(value):
        return "Legacy Skill (read-only)"
    return SCRIPT_TYPE_LABELS.get(value, value)


def _safe_redirect_target(target: str | None, fallback: str) -> str:
    if not target:
        return fallback
    if target.startswith("/") and "://" not in target and "\\\\" not in target:
        return target
    return fallback


def _parse_positive_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed < 1:
        return default
    return parsed


def _parse_run_settings(run_mode: str, run_max_loops_raw: str) -> tuple[int | None, str | None]:
    if run_mode == "forever":
        return None, None
    if not run_max_loops_raw:
        return None, "Autorun limit is required unless running forever."
    try:
        run_max_loops = int(run_max_loops_raw)
    except ValueError:
        return None, "Autorun limit must be a number."
    if run_max_loops < 1:
        return None, "Autorun limit must be at least 1."
    return run_max_loops, None


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
            "Using llmctl-chromadb:8000 inside Docker. Host-mapped ports (for example 18000) "
            "are only for access from your machine.",
        )
    if host_value.lower() in DOCKER_CHROMA_HOST_ALIASES:
        return "llmctl-chromadb", port, None
    return host_value, port, None


def _resolved_chroma_settings(
    settings: dict[str, str] | None = None,
) -> dict[str, str]:
    settings = settings or _load_integration_settings("chroma")
    host = (settings.get("host") or "").strip() or (Config.CHROMA_HOST or "").strip()
    port_raw = (settings.get("port") or "").strip() or (Config.CHROMA_PORT or "").strip()
    parsed_port = _parse_chroma_port(port_raw)
    normalized_hint = ""
    if host and parsed_port is not None:
        host, parsed_port, hint = _normalize_chroma_target(host, parsed_port)
        normalized_hint = hint or ""
        port = str(parsed_port)
    else:
        port = str(parsed_port) if parsed_port is not None else ""
    ssl_raw = (settings.get("ssl") or "").strip().lower()
    if not ssl_raw:
        ssl_raw = (Config.CHROMA_SSL or "").strip().lower()
    return {
        "host": host,
        "port": port,
        "ssl": "true" if ssl_raw == "true" else "false",
        "normalized_hint": normalized_hint,
    }


def _chroma_connected(settings: dict[str, str]) -> bool:
    return bool(
        (settings.get("host") or "").strip()
        and _parse_chroma_port(settings.get("port")) is not None
    )


def _chroma_endpoint_label(host: str, port: int | None) -> str:
    host_label = host or "not set"
    port_label = str(port) if port is not None else "not set"
    return f"{host_label}:{port_label}"


def _chroma_http_client(
    settings: dict[str, str],
) -> tuple[object | None, str, int | None, str | None, str | None]:
    host = (settings.get("host") or "").strip()
    port = _parse_chroma_port(settings.get("port"))
    if not host or port is None:
        return None, host, port, None, "Chroma host and port are required."
    host, port, normalized_hint = _normalize_chroma_target(host, port)
    ssl = _as_bool(settings.get("ssl"))
    try:
        import chromadb  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        return None, host, port, normalized_hint, "Python package 'chromadb' is not installed."
    try:
        client = chromadb.HttpClient(host=host, port=port, ssl=ssl)
    except TypeError:
        client = chromadb.HttpClient(host=host, port=port)
    except Exception as exc:
        return None, host, port, normalized_hint, str(exc)
    return client, host, port, normalized_hint, None


def _list_collection_names(collections: object) -> list[str]:
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


def _google_service_account_email(settings: dict[str, str]) -> str | None:
    raw = (settings.get("service_account_json") or "").strip()
    if not raw:
        return None
    try:
        return _google_drive_service_account_email(raw)
    except ValueError:
        return None


def _rag_nav_health_payload() -> dict[str, str | None]:
    try:
        health = rag_domain_health_snapshot()
    except Exception as exc:
        return {
            "state": RAG_DOMAIN_HEALTH_CONFIGURED_UNHEALTHY,
            "provider": "chroma",
            "error": str(exc),
        }
    return {
        "state": str(health.get("state") or RAG_DOMAIN_HEALTH_UNCONFIGURED),
        "provider": str(health.get("provider") or "chroma"),
        "error": str(health.get("error") or "").strip() or None,
    }


@bp.app_context_processor
def _inject_template_helpers() -> dict[str, object]:
    return {
        "human_time": _human_time,
        "integration_overview": _integration_overview(),
        "rag_nav_health": _rag_nav_health_payload(),
        "task_kind_label": task_kind_label,
        "script_type_label": _script_type_label,
    }


def _load_agents() -> list[Agent]:
    with session_scope() as session:
        agents = (
            session.execute(
                select(Agent)
                .order_by(Agent.created_at.desc())
            )
            .scalars()
            .all()
        )
    return agents


def _load_roles() -> list[Role]:
    with session_scope() as session:
        return (
            session.execute(select(Role).order_by(Role.created_at.desc()))
            .scalars()
            .all()
        )


def _quick_node_default_model_id(models: list[LLMModel]) -> int | None:
    if not models:
        return None
    configured_default = resolve_default_model_id(_load_integration_settings("llm"))
    model_ids = {model.id for model in models}
    if configured_default in model_ids:
        return configured_default
    return models[0].id


def _load_runs(limit: int | None = None) -> list[Run]:
    with session_scope() as session:
        stmt = select(Run).options(selectinload(Run.agent)).order_by(
            Run.created_at.desc()
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        return session.execute(stmt).scalars().all()


def _load_runs_page(page: int, per_page: int) -> tuple[list[Run], int, int, int]:
    with session_scope() as session:
        total_runs = session.execute(select(func.count(Run.id))).scalar_one()
        total_pages = (
            max(1, (total_runs + per_page - 1) // per_page) if total_runs else 1
        )
        page = max(1, min(page, total_pages))
        runs: list[Run] = []
        if total_runs:
            stmt = (
                select(Run)
                .options(selectinload(Run.agent))
                .order_by(Run.created_at.desc())
                .limit(per_page)
                .offset((page - 1) * per_page)
            )
            runs = session.execute(stmt).scalars().all()
        return runs, total_runs, page, total_pages


def _active_agent_ids(agent_ids: list[int]) -> set[int]:
    if not agent_ids:
        return set()
    with session_scope() as session:
        rows = (
            session.execute(
                select(Run.agent_id)
                .where(
                    Run.agent_id.in_(agent_ids),
                    Run.status.in_(RUN_ACTIVE_STATUSES),
                )
                .distinct()
            )
            .scalars()
            .all()
        )
    return set(rows)


def _agent_status_by_id(agent_ids: list[int]) -> dict[int, str]:
    if not agent_ids:
        return {}
    status_by_id: dict[int, str] = {}
    with session_scope() as session:
        active_rows = session.execute(
            select(Run.agent_id, Run.status, Run.updated_at)
            .where(
                Run.agent_id.in_(agent_ids),
                Run.status.in_(RUN_ACTIVE_STATUSES),
            )
            .order_by(Run.updated_at.desc())
        ).all()
        for row in active_rows:
            agent_id = row[0]
            if agent_id not in status_by_id:
                status_by_id[agent_id] = row[1]

        latest_runs = (
            select(Run.agent_id, func.max(Run.updated_at).label("latest_updated"))
            .where(Run.agent_id.in_(agent_ids))
            .group_by(Run.agent_id)
            .subquery()
        )
        rows = session.execute(
            select(Run.agent_id, Run.status).join(
                latest_runs,
                (Run.agent_id == latest_runs.c.agent_id)
                & (Run.updated_at == latest_runs.c.latest_updated),
            )
        ).all()
        for row in rows:
            status_by_id.setdefault(row[0], row[1])
    return status_by_id


def _load_default_agent() -> Agent | None:
    with session_scope() as session:
        return (
            session.execute(select(Agent).order_by(Agent.created_at.desc()).limit(1))
            .scalars()
            .first()
        )


def _agent_rollup(agents: list[Agent]) -> tuple[list[Agent], dict[str, object]]:
    agent_ids = [agent.id for agent in agents]
    active_ids = _active_agent_ids(agent_ids)
    active_agents = [agent for agent in agents if agent.id in active_ids]
    error_agents = [agent for agent in agents if agent.last_error]
    last_run_at = max(
        (agent.last_run_at for agent in agents if agent.last_run_at),
        default=None,
    )
    summary = {
        "total": len(agents),
        "active": len(active_agents),
        "errors": len(error_agents),
        "last_run_at": last_run_at,
    }
    return active_agents, summary


def _settings_summary() -> dict[str, object]:
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    return summary


def _provider_command(provider: str | None) -> str:
    if provider == "codex":
        return f"{Config.CODEX_CMD} exec"
    if provider == "gemini":
        return Config.GEMINI_CMD
    if provider == "claude":
        return f"{Config.CLAUDE_CMD} --print"
    if provider == "vllm_local":
        return f"{Config.VLLM_LOCAL_CMD} run-batch"
    if provider == "vllm_remote":
        return "HTTP /v1/chat/completions"
    return "-"


def _provider_model(provider: str | None, settings: dict[str, str] | None = None) -> str:
    if provider == "codex":
        settings = settings or _load_integration_settings("llm")
        model = (settings.get("codex_model") or "").strip()
        return model or Config.CODEX_MODEL or _codex_default_model()
    if provider == "gemini":
        return Config.GEMINI_MODEL or "default"
    if provider == "claude":
        return Config.CLAUDE_MODEL or _claude_default_model()
    if provider == "vllm_local":
        settings = settings or _load_integration_settings("llm")
        model = (settings.get("vllm_local_model") or "").strip()
        return model or _vllm_local_default_model()
    if provider == "vllm_remote":
        settings = settings or _load_integration_settings("llm")
        model = (settings.get("vllm_remote_model") or "").strip()
        return model or _vllm_remote_default_model()
    return "default"


def _provider_summary(
    provider: str | None = None,
    *,
    settings: dict[str, str] | None = None,
    enabled_providers: set[str] | None = None,
) -> dict[str, str | None]:
    settings = settings or _load_integration_settings("llm")
    enabled = enabled_providers or resolve_enabled_llm_providers(settings)
    selected = provider or resolve_llm_provider(
        settings=settings, enabled_providers=enabled
    )
    label = LLM_PROVIDER_LABELS.get(selected, selected) if selected else "not set"
    return {
        "provider": selected,
        "label": label,
        "command": _provider_command(selected),
        "model": _provider_model(selected, settings),
    }


def _provider_options() -> list[dict[str, str]]:
    return [
        {"value": key, "label": LLM_PROVIDER_LABELS.get(key, key)}
        for key in LLM_PROVIDERS
    ]


def _as_bool(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def _instruction_flag_default_native(provider: str) -> bool:
    normalized = str(provider or "").strip().lower()
    return normalized in {"codex", "gemini", "claude"}


def _instruction_flag_default_fallback(provider: str) -> bool:
    del provider
    return True


def _instruction_runtime_flags(settings: dict[str, str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for provider in LLM_PROVIDERS:
        native_key = f"instruction_native_enabled_{provider}"
        fallback_key = f"instruction_fallback_enabled_{provider}"
        native_raw = settings.get(native_key)
        fallback_raw = settings.get(fallback_key)
        native_enabled = (
            _as_bool(native_raw)
            if native_raw is not None
            else _instruction_flag_default_native(provider)
        )
        fallback_enabled = (
            _as_bool(fallback_raw)
            if fallback_raw is not None
            else _instruction_flag_default_fallback(provider)
        )
        rows.append(
            {
                "provider": provider,
                "label": LLM_PROVIDER_LABELS.get(provider, provider),
                "native_key": native_key,
                "fallback_key": fallback_key,
                "native_enabled": native_enabled,
                "fallback_enabled": fallback_enabled,
                "supports_native": _instruction_flag_default_native(provider),
            }
        )
    return rows


def _default_model_overview(
    settings: dict[str, str] | None = None,
) -> dict[str, object]:
    settings = settings or _load_integration_settings("llm")
    default_model_id = resolve_default_model_id(settings)
    if default_model_id is None:
        return {
            "id": None,
            "label": "not set",
            "provider_label": None,
            "model_name": None,
            "name": None,
        }
    with session_scope() as session:
        model = session.get(LLMModel, default_model_id)
        if model is None:
            return {
                "id": default_model_id,
                "label": "missing",
                "provider_label": None,
                "model_name": None,
                "name": None,
            }
        model_name = _model_display_name(model)
        provider_label = LLM_PROVIDER_LABELS.get(model.provider, model.provider)
        label = f"{model.name} ({provider_label} / {model_name})"
        return {
            "id": model.id,
            "label": label,
            "provider_label": provider_label,
            "model_name": model_name,
            "name": model.name,
        }


def _decode_model_config(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _configured_agent_markdown_filename(config: dict[str, object]) -> str:
    candidate = str(config.get("agent_markdown_filename") or "").strip()
    return candidate or NON_FRONTIER_DEFAULT_INSTRUCTION_FILENAME


def _apply_model_markdown_filename_validation(
    provider: str,
    config_payload: dict[str, object],
) -> str | None:
    if is_frontier_instruction_provider(provider):
        config_payload.pop("agent_markdown_filename", None)
        return None
    raw_value = str(config_payload.get("agent_markdown_filename") or "").strip()
    if not raw_value:
        raw_value = NON_FRONTIER_DEFAULT_INSTRUCTION_FILENAME
    try:
        config_payload["agent_markdown_filename"] = validate_agent_markdown_filename(
            raw_value
        )
    except ValueError as exc:
        return str(exc)
    return None


def _codex_model_config_defaults(
    config: dict[str, object],
    *,
    default_model: str | None = None,
) -> dict[str, object]:
    model = str(config.get("model") or "").strip()
    if not model:
        model = default_model or _codex_default_model()
    return {
        "model": model,
        "approval_policy": config.get("approval_policy") or "never",
        "sandbox_mode": config.get("sandbox_mode") or "danger-full-access",
        "network_access": config.get("network_access") or "enabled",
        "model_reasoning_effort": config.get("model_reasoning_effort") or "high",
        "shell_env_inherit": config.get("shell_env_inherit") or "all",
        "shell_env_ignore_default_excludes": _as_bool(
            str(config.get("shell_env_ignore_default_excludes"))
            if config.get("shell_env_ignore_default_excludes") is not None
            else ""
        ),
        "notice_hide_key": config.get("notice_hide_key") or "",
        "notice_hide_enabled": _as_bool(
            str(config.get("notice_hide_enabled"))
            if config.get("notice_hide_enabled") is not None
            else ""
        ),
        "notice_migration_from": config.get("notice_migration_from") or "",
        "notice_migration_to": config.get("notice_migration_to") or "",
    }


def _normalize_optional_bool(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "false"}:
            return normalized
    return ""


def _normalize_args_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [str(item).strip() for item in value]
        return "\n".join(part for part in parts if part)
    return str(value)


def _gemini_model_config_defaults(config: dict[str, object]) -> dict[str, object]:
    return {
        "model": config.get("model") or "",
        "approval_mode": config.get("approval_mode") or "",
        "sandbox": _normalize_optional_bool(config.get("sandbox")),
        "extra_args": _normalize_args_text(config.get("extra_args")),
    }


def _simple_model_config_defaults(config: dict[str, object]) -> dict[str, object]:
    return {"model": config.get("model") or ""}


def _vllm_local_default_model(models: list[dict[str, str]] | None = None) -> str:
    entries = models or discover_vllm_local_models()
    if entries:
        return entries[0]["value"]
    return ""


def _vllm_remote_default_model() -> str:
    return Config.VLLM_REMOTE_DEFAULT_MODEL or "GLM-4.7-Flash"


def _vllm_number_defaults(
    config: dict[str, object],
    *,
    temperature_default: str = "0.2",
    max_tokens_default: str = "2048",
    timeout_default: str = "180",
) -> dict[str, str]:
    def _pick(key: str, fallback: str) -> str:
        value = config.get(key)
        if value is None:
            return fallback
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or fallback
        return str(value)

    return {
        "temperature": _pick("temperature", temperature_default),
        "max_tokens": _pick("max_tokens", max_tokens_default),
        "request_timeout_seconds": _pick("request_timeout_seconds", timeout_default),
    }


def _vllm_local_model_config_defaults(
    config: dict[str, object],
    *,
    default_model: str,
) -> dict[str, object]:
    numbers = _vllm_number_defaults(config)
    return {
        "model": str(config.get("model") or default_model),
        "temperature": numbers["temperature"],
        "max_tokens": numbers["max_tokens"],
        "request_timeout_seconds": numbers["request_timeout_seconds"],
        "agent_markdown_filename": _configured_agent_markdown_filename(config),
    }


def _vllm_remote_model_config_defaults(
    config: dict[str, object],
    *,
    default_model: str,
) -> dict[str, object]:
    numbers = _vllm_number_defaults(
        config,
        temperature_default="0.2",
        max_tokens_default="4096",
        timeout_default="240",
    )
    return {
        "model": str(config.get("model") or default_model),
        "base_url_override": str(
            config.get("base_url_override") or config.get("base_url") or ""
        ),
        "temperature": numbers["temperature"],
        "max_tokens": numbers["max_tokens"],
        "request_timeout_seconds": numbers["request_timeout_seconds"],
        "agent_markdown_filename": _configured_agent_markdown_filename(config),
    }


def _parse_model_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = []
    for chunk in raw.replace(",", "\n").splitlines():
        value = chunk.strip()
        if value:
            parts.append(value)
    return parts


def _codex_default_model(options: list[str] | None = None) -> str:
    if options:
        for model in CODEX_MODEL_PREFERENCE:
            if model in options:
                return model
        return options[0]
    return CODEX_MODEL_PREFERENCE[0]


def _ordered_codex_models(options: set[str]) -> list[str]:
    ordered = []
    seen = set()
    for model in CODEX_MODEL_PREFERENCE:
        if model in options:
            ordered.append(model)
            seen.add(model)
    remainder = sorted([model for model in options if model not in seen], key=str.lower)
    ordered.extend(remainder)
    return ordered


def _ordered_gemini_models(options: set[str]) -> list[str]:
    ordered = []
    seen = set()
    for model in GEMINI_MODEL_OPTIONS:
        if model in options:
            ordered.append(model)
            seen.add(model)
    remainder = sorted([model for model in options if model not in seen], key=str.lower)
    ordered.extend(remainder)
    return ordered


def _claude_default_model(options: list[str] | None = None) -> str:
    if options:
        for model in CLAUDE_MODEL_OPTIONS:
            if model in options:
                return model
        return options[0]
    return CLAUDE_MODEL_OPTIONS[0]


def _ordered_claude_models(options: set[str]) -> list[str]:
    ordered = []
    seen = set()
    for model in CLAUDE_MODEL_OPTIONS:
        if model in options:
            ordered.append(model)
            seen.add(model)
    remainder = sorted([model for model in options if model not in seen], key=str.lower)
    ordered.extend(remainder)
    return ordered


def _provider_default_model(
    provider: str,
    settings: dict[str, str] | None = None,
) -> str:
    if provider == "codex":
        return Config.CODEX_MODEL or _codex_default_model()
    if provider == "gemini":
        return Config.GEMINI_MODEL or ""
    if provider == "claude":
        return Config.CLAUDE_MODEL or _claude_default_model()
    if provider == "vllm_local":
        settings = settings or _load_integration_settings("llm")
        configured = (settings.get("vllm_local_model") or "").strip()
        return configured or _vllm_local_default_model()
    if provider == "vllm_remote":
        settings = settings or _load_integration_settings("llm")
        configured = (settings.get("vllm_remote_model") or "").strip()
        return configured or _vllm_remote_default_model()
    return ""


def _provider_model_options(
    settings: dict[str, str] | None = None,
    models: list[LLMModel] | None = None,
) -> dict[str, list[str]]:
    settings = settings or _load_integration_settings("llm")
    models = models or _load_llm_models()
    local_vllm_models = discover_vllm_local_models()
    options: dict[str, set[str]] = {provider: set() for provider in LLM_PROVIDERS}
    if "codex" in options:
        options["codex"].update(CODEX_MODEL_PREFERENCE)
    if "gemini" in options:
        options["gemini"].update(GEMINI_MODEL_OPTIONS)
    if "claude" in options:
        options["claude"].update(CLAUDE_MODEL_OPTIONS)
    if "vllm_local" in options:
        options["vllm_local"].update(item["value"] for item in local_vllm_models)
    if "vllm_remote" in options:
        options["vllm_remote"].add(_vllm_remote_default_model())
    for provider in LLM_PROVIDERS:
        options[provider].update(
            _parse_model_list(settings.get(f"{provider}_models"))
        )
        settings_model = (settings.get(f"{provider}_model") or "").strip()
        if settings_model:
            options[provider].add(settings_model)
        default_model = _provider_default_model(provider, settings=settings)
        if default_model:
            options[provider].add(default_model.strip())
    for model in models:
        if model.provider not in options:
            continue
        config = _decode_model_config(model.config_json)
        model_name = str(config.get("model") or "").strip()
        if model_name:
            options[model.provider].add(model_name)
    ordered: dict[str, list[str]] = {}
    for provider, values in options.items():
        if provider == "codex":
            ordered[provider] = _ordered_codex_models(values)
        elif provider == "gemini":
            ordered[provider] = _ordered_gemini_models(values)
        elif provider == "claude":
            ordered[provider] = _ordered_claude_models(values)
        else:
            ordered[provider] = sorted(values, key=str.lower)
    return ordered


def _model_option_allowed(
    provider: str,
    model_name: str,
    model_options: dict[str, list[str]],
) -> bool:
    if not model_name:
        return True
    return model_name in model_options.get(provider, [])


def _model_config_payload(provider: str, form: dict[str, str]) -> dict[str, object]:
    if provider == "codex":
        return {
            "model": form.get("codex_model", "").strip(),
            "approval_policy": form.get("codex_approval_policy", "").strip(),
            "sandbox_mode": form.get("codex_sandbox_mode", "").strip(),
            "network_access": form.get("codex_network_access", "").strip(),
            "model_reasoning_effort": form.get("codex_model_reasoning_effort", "").strip(),
            "shell_env_inherit": form.get("codex_shell_env_inherit", "").strip(),
            "shell_env_ignore_default_excludes": (
                form.get("codex_shell_env_ignore_default_excludes", "")
                .strip()
                .lower()
                == "true"
            ),
            "notice_hide_key": form.get("codex_notice_hide_key", "").strip(),
            "notice_hide_enabled": (
                form.get("codex_notice_hide_enabled", "").strip().lower() == "true"
            ),
            "notice_migration_from": form.get("codex_notice_migration_from", "").strip(),
            "notice_migration_to": form.get("codex_notice_migration_to", "").strip(),
        }
    if provider == "gemini":
        sandbox_raw = form.get("gemini_sandbox", "").strip().lower()
        sandbox_value = None
        if sandbox_raw == "true":
            sandbox_value = True
        elif sandbox_raw == "false":
            sandbox_value = False
        return {
            "model": form.get("gemini_model", "").strip(),
            "approval_mode": form.get("gemini_approval_mode", "").strip(),
            "sandbox": sandbox_value,
            "extra_args": form.get("gemini_extra_args", "").strip(),
        }
    if provider == "claude":
        return {"model": form.get("claude_model", "").strip()}
    if provider == "vllm_local":
        return {
            "model": form.get("vllm_local_model", "").strip(),
            "temperature": form.get("vllm_local_temperature", "").strip(),
            "max_tokens": form.get("vllm_local_max_tokens", "").strip(),
            "request_timeout_seconds": form.get(
                "vllm_local_request_timeout_seconds", ""
            ).strip(),
            "agent_markdown_filename": form.get("agent_markdown_filename", "").strip(),
        }
    if provider == "vllm_remote":
        return {
            "model": form.get("vllm_remote_model", "").strip(),
            "base_url_override": form.get("vllm_remote_base_url_override", "").strip(),
            "temperature": form.get("vllm_remote_temperature", "").strip(),
            "max_tokens": form.get("vllm_remote_max_tokens", "").strip(),
            "request_timeout_seconds": form.get(
                "vllm_remote_request_timeout_seconds", ""
            ).strip(),
            "agent_markdown_filename": form.get("agent_markdown_filename", "").strip(),
        }
    return {}


def _load_llm_models() -> list[LLMModel]:
    with session_scope() as session:
        return (
            session.execute(select(LLMModel).order_by(LLMModel.created_at.desc()))
            .scalars()
            .all()
        )


def _model_display_name(model: LLMModel) -> str:
    config = _decode_model_config(model.config_json)
    model_name = str(config.get("model") or "").strip()
    if model.provider == "vllm_local" and model_name:
        for item in discover_vllm_local_models():
            if item["value"] == model_name:
                return item["label"]
    return model_name or "default"


def _codex_settings_payload(settings: dict[str, str]) -> dict[str, object]:
    return {
        "api_key": settings.get("codex_api_key") or "",
    }


def _gemini_settings_payload(settings: dict[str, str]) -> dict[str, object]:
    return {
        "api_key": settings.get("gemini_api_key") or "",
    }


def _claude_settings_payload(settings: dict[str, str]) -> dict[str, object]:
    runtime = claude_runtime_diagnostics()
    return {
        "api_key": settings.get("claude_api_key") or "",
        "runtime": runtime,
    }


def _vllm_local_settings_payload(settings: dict[str, str]) -> dict[str, object]:
    local_models = discover_vllm_local_models()
    local_default = (
        (settings.get("vllm_local_model") or "").strip()
        or _vllm_local_default_model(local_models)
    )
    huggingface_token = _vllm_local_huggingface_token(settings)
    downloaded_models = _downloaded_vllm_local_models_payload(local_models)
    return {
        "command": Config.VLLM_LOCAL_CMD,
        "models": local_models,
        "model": local_default,
        "custom_dir": Config.VLLM_LOCAL_CUSTOM_MODELS_DIR,
        "qwen": _qwen_action_payload(),
        "huggingface": {
            "token": huggingface_token,
            "configured": bool(huggingface_token),
            "downloaded_models": downloaded_models,
        },
        "download_job": _active_huggingface_download_job_payload(),
    }


def _vllm_local_huggingface_token(settings: dict[str, str] | None = None) -> str:
    settings = settings or _load_integration_settings("llm")
    return (settings.get("vllm_local_hf_token") or "").strip()


def _download_job_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_download_job_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _clamp_download_percent(value: object) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(100.0, numeric))


def _prune_huggingface_download_jobs_locked() -> None:
    _sync_huggingface_download_jobs_locked()
    now = datetime.now(timezone.utc)
    stale_ids: list[str] = []
    for job_id, job in _huggingface_download_jobs.items():
        status = str(job.get("status") or "")
        if status in HUGGINGFACE_DOWNLOAD_JOB_STATUS_ACTIVE:
            continue
        finished_at = _parse_download_job_timestamp(job.get("finished_at"))
        if finished_at is None:
            continue
        if (now - finished_at).total_seconds() > HUGGINGFACE_DOWNLOAD_JOB_TTL_SECONDS:
            stale_ids.append(job_id)
    for job_id in stale_ids:
        _huggingface_download_jobs.pop(job_id, None)

    if len(_huggingface_download_jobs) <= HUGGINGFACE_DOWNLOAD_JOB_MAX_RECORDS:
        return
    ordered_ids = sorted(
        _huggingface_download_jobs.keys(),
        key=lambda item: (
            _parse_download_job_timestamp(_huggingface_download_jobs[item].get("started_at"))
            or datetime.min.replace(tzinfo=timezone.utc)
        ),
    )
    keep_ids = set(ordered_ids[-HUGGINGFACE_DOWNLOAD_JOB_MAX_RECORDS :])
    for job_id in ordered_ids:
        if job_id not in keep_ids:
            _huggingface_download_jobs.pop(job_id, None)


def _map_celery_download_state(state: str) -> tuple[str, str]:
    normalized = (state or "").strip().upper()
    if normalized in {"PENDING", "RECEIVED"}:
        return "queued", "queued"
    if normalized in {"STARTED", "PROGRESS", "RETRY"}:
        return "running", "running"
    if normalized == "SUCCESS":
        return "succeeded", "succeeded"
    if normalized in {"FAILURE", "REVOKED"}:
        return "failed", "failed"
    return "running", "running"


def _sync_huggingface_download_jobs_locked() -> None:
    now = _download_job_timestamp()
    for job in _huggingface_download_jobs.values():
        job_id = str(job.get("id") or "")
        if not job_id:
            continue
        try:
            async_result = celery_app.AsyncResult(job_id)
            raw_state = str(async_result.state or "")
            raw_info = async_result.info
        except Exception:
            continue
        status, default_phase = _map_celery_download_state(raw_state)
        info = raw_info if isinstance(raw_info, dict) else {}

        job["status"] = status
        job["phase"] = str(info.get("phase") or default_phase)
        if info.get("kind") is not None:
            job["kind"] = str(info.get("kind") or job.get("kind") or "")
        if info.get("model_id") is not None:
            job["model_id"] = str(info.get("model_id") or job.get("model_id") or "")
        if info.get("target_dir") is not None:
            job["target_dir"] = str(info.get("target_dir") or job.get("target_dir") or "")
        if info.get("summary"):
            job["summary"] = str(info.get("summary") or "")
        if info.get("percent") is not None:
            job["percent"] = _clamp_download_percent(info.get("percent"))
        elif status == "succeeded":
            job["percent"] = 100.0
        log_lines = info.get("log_lines")
        if isinstance(log_lines, list):
            job["log_lines"] = [str(line)[:240] for line in log_lines][-24:]
        if status == "failed":
            error_detail = ""
            if isinstance(raw_info, BaseException):
                error_detail = str(raw_info)
            elif isinstance(raw_info, dict):
                error_detail = str(raw_info.get("error") or raw_info.get("summary") or "")
            else:
                error_detail = str(raw_info or "")
            error_detail = error_detail.strip()
            if error_detail:
                job["error"] = error_detail
                if not str(job.get("summary") or "").strip():
                    job["summary"] = error_detail
        if status == "succeeded" and not str(job.get("summary") or "").strip():
            job["summary"] = f"Downloaded {job.get('model_id') or 'model'}."
        if status == "queued" and not str(job.get("summary") or "").strip():
            job["summary"] = "Queued download."
        job["updated_at"] = now
        if status in {"succeeded", "failed"} and not str(job.get("finished_at") or "").strip():
            job["finished_at"] = now


def _serialize_huggingface_download_job(job: dict[str, object]) -> dict[str, object]:
    return {
        "id": str(job.get("id") or ""),
        "kind": str(job.get("kind") or ""),
        "status": str(job.get("status") or ""),
        "phase": str(job.get("phase") or ""),
        "model_id": str(job.get("model_id") or ""),
        "target_dir": str(job.get("target_dir") or ""),
        "summary": str(job.get("summary") or ""),
        "error": str(job.get("error") or ""),
        "percent": _clamp_download_percent(job.get("percent")),
        "log_lines": list(job.get("log_lines") or []),
        "started_at": str(job.get("started_at") or ""),
        "updated_at": str(job.get("updated_at") or ""),
        "finished_at": str(job.get("finished_at") or ""),
    }


def _active_huggingface_download_job_payload() -> dict[str, object] | None:
    with _huggingface_download_jobs_lock:
        _prune_huggingface_download_jobs_locked()
        active_jobs = [
            _serialize_huggingface_download_job(job)
            for job in _huggingface_download_jobs.values()
            if str(job.get("status") or "") in HUGGINGFACE_DOWNLOAD_JOB_STATUS_ACTIVE
        ]
    if not active_jobs:
        return None
    active_jobs.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
    return active_jobs[0]


def _find_active_huggingface_download_job_for_target(target_dir: str) -> dict[str, object] | None:
    with _huggingface_download_jobs_lock:
        _prune_huggingface_download_jobs_locked()
        active_jobs = [
            _serialize_huggingface_download_job(job)
            for job in _huggingface_download_jobs.values()
            if str(job.get("target_dir") or "") == target_dir
            and str(job.get("status") or "") in HUGGINGFACE_DOWNLOAD_JOB_STATUS_ACTIVE
        ]
    if not active_jobs:
        return None
    active_jobs.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
    return active_jobs[0]


def _get_huggingface_download_job(job_id: str) -> dict[str, object] | None:
    with _huggingface_download_jobs_lock:
        _prune_huggingface_download_jobs_locked()
        job = _huggingface_download_jobs.get(job_id)
        if job is None:
            return None
        return _serialize_huggingface_download_job(job)


def _start_huggingface_download_job(
    *,
    kind: str,
    model_id: str,
    model_dir_name: str,
    token: str,
    model_container_path: str,
) -> tuple[dict[str, object], bool]:
    target_dir = str(_vllm_local_model_directory(model_dir_name))
    existing = _find_active_huggingface_download_job_for_target(target_dir)
    if existing is not None:
        return existing, False

    timestamp = _download_job_timestamp()
    result = run_huggingface_download_task.apply_async(
        kwargs={
            "kind": kind,
            "model_id": model_id,
            "model_dir_name": model_dir_name,
            "token": token,
            "model_container_path": model_container_path,
        },
        queue=HUGGINGFACE_DOWNLOAD_QUEUE,
    )
    job_id = str(result.id or uuid.uuid4().hex)
    with _huggingface_download_jobs_lock:
        _huggingface_download_jobs[job_id] = {
            "id": job_id,
            "kind": kind,
            "status": "queued",
            "phase": "queued",
            "model_id": model_id,
            "target_dir": target_dir,
            "summary": "Queued download.",
            "error": "",
            "percent": 0.0,
            "log_lines": [],
            "started_at": timestamp,
            "updated_at": timestamp,
            "finished_at": "",
        }
        _prune_huggingface_download_jobs_locked()
    snapshot = _get_huggingface_download_job(job_id)
    if snapshot is None:
        raise RuntimeError("Failed to initialize HuggingFace download job.")
    return snapshot, True


def _vllm_local_model_container_path(model_dir_name: str) -> str:
    return _shared_vllm_local_model_container_path(model_dir_name)


def _normalize_vllm_local_model_dir_name(value: str | None) -> str:
    dir_name = (value or "").strip().strip("/")
    if not dir_name:
        return ""
    if Path(dir_name).name != dir_name:
        return ""
    if "\\" in dir_name:
        return ""
    return dir_name


def _vllm_local_model_directory(model_dir_name: str) -> Path:
    return _shared_vllm_local_model_directory(model_dir_name)


def _downloaded_vllm_local_models_payload(
    local_models: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    entries = local_models if local_models is not None else discover_vllm_local_models()
    custom_root = Path(Config.VLLM_LOCAL_CUSTOM_MODELS_DIR).resolve()
    payload: list[dict[str, str]] = []
    for item in entries:
        path_text = str(item.get("path") or "").strip()
        if not path_text:
            continue
        model_dir = Path(path_text).resolve()
        try:
            model_dir.relative_to(custom_root)
        except ValueError:
            continue
        dir_name = _normalize_vllm_local_model_dir_name(model_dir.name)
        if not dir_name:
            continue
        payload.append(
            {
                "dir_name": dir_name,
                "label": str(item.get("label") or dir_name),
                "value": str(item.get("value") or "").strip(),
                "target_dir": str(model_dir),
                "container_path": _vllm_local_model_container_path(dir_name),
                "status": "Downloaded",
            }
        )
    return payload


def _find_downloaded_vllm_local_model(model_dir_name: str) -> dict[str, str] | None:
    normalized_dir_name = _normalize_vllm_local_model_dir_name(model_dir_name)
    if not normalized_dir_name:
        return None
    for item in _downloaded_vllm_local_models_payload():
        if item.get("dir_name") == normalized_dir_name:
            return item
    return None


def _remove_vllm_local_model_directory(model_dir_name: str) -> bool:
    normalized_dir_name = _normalize_vllm_local_model_dir_name(model_dir_name)
    if not normalized_dir_name:
        raise ValueError("Model directory name is invalid.")
    custom_root = Path(Config.VLLM_LOCAL_CUSTOM_MODELS_DIR).resolve()
    model_dir = _vllm_local_model_directory(normalized_dir_name)
    try:
        model_dir.relative_to(custom_root)
    except ValueError as exc:
        raise ValueError("Model directory is outside configured custom models root.") from exc
    if not model_dir.exists():
        return False
    shutil.rmtree(model_dir)
    return True


def _model_directory_has_downloaded_contents(model_dir: Path) -> bool:
    return _shared_model_directory_has_downloaded_contents(model_dir)


def _normalize_huggingface_repo_id(value: str | None) -> str:
    model_id = (value or "").strip()
    if not HUGGINGFACE_REPO_ID_PATTERN.fullmatch(model_id):
        return ""
    return model_id


def _huggingface_model_dir_name(model_id: str) -> str:
    raw_name = (model_id.rsplit("/", 1)[-1] if "/" in model_id else model_id).strip()
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", raw_name).strip("._-").lower()
    return cleaned or "huggingface-model"


def _qwen_model_id() -> str:
    model_id = (os.getenv("QWEN_MODEL_ID") or QWEN_DEFAULT_MODEL_ID).strip()
    return model_id or QWEN_DEFAULT_MODEL_ID


def _qwen_model_dir_name() -> str:
    dir_name = (os.getenv("QWEN_MODEL_DIR_NAME") or QWEN_DEFAULT_MODEL_DIR_NAME).strip()
    dir_name = dir_name.strip("/").strip()
    return dir_name or QWEN_DEFAULT_MODEL_DIR_NAME


def _qwen_model_container_path() -> str:
    return _vllm_local_model_container_path(_qwen_model_dir_name())


def _qwen_model_directory() -> Path:
    return _vllm_local_model_directory(_qwen_model_dir_name())


def _qwen_model_downloaded() -> bool:
    return _model_directory_has_downloaded_contents(_qwen_model_directory())


def _qwen_action_payload() -> dict[str, str | bool]:
    installed = _qwen_model_downloaded()
    return {
        "installed": installed,
        "action": "remove" if installed else "download",
        "model_id": _qwen_model_id(),
        "model_dir_name": _qwen_model_dir_name(),
        "target_dir": str(_qwen_model_directory()),
        "model_container_path": _qwen_model_container_path(),
    }


def _run_huggingface_model_download(
    model_id: str,
    model_dir_name: str,
    *,
    token: str = "",
    model_container_path: str,
    progress_callback=None,
) -> None:
    _shared_run_huggingface_model_download(
        model_id,
        model_dir_name,
        token=token,
        model_container_path=model_container_path,
        progress_callback=progress_callback,
    )


def _run_qwen_download(*, token: str = "") -> None:
    _run_huggingface_model_download(
        _qwen_model_id(),
        _qwen_model_dir_name(),
        token=token,
        model_container_path=_qwen_model_container_path(),
    )


def _summarize_subprocess_error(exc: subprocess.CalledProcessError) -> str:
    return _shared_summarize_subprocess_error(exc)


def _remove_qwen_model_directory() -> bool:
    custom_root = Path(Config.VLLM_LOCAL_CUSTOM_MODELS_DIR).resolve()
    model_dir = _qwen_model_directory()
    try:
        model_dir.relative_to(custom_root)
    except ValueError as exc:
        raise ValueError("Qwen model directory is outside configured custom models root.") from exc
    if not model_dir.exists():
        return False
    shutil.rmtree(model_dir)
    return True


def _vllm_remote_settings_payload(settings: dict[str, str]) -> dict[str, object]:
    remote_default = (
        (settings.get("vllm_remote_model") or "").strip() or _vllm_remote_default_model()
    )
    remote_models = _parse_model_list(settings.get("vllm_remote_models"))
    if remote_default and remote_default not in remote_models:
        remote_models.insert(0, remote_default)
    return {
        "base_url": (settings.get("vllm_remote_base_url") or "").strip()
        or Config.VLLM_REMOTE_BASE_URL,
        "api_key": (settings.get("vllm_remote_api_key") or "").strip(),
        "model": remote_default,
        "models": remote_models,
    }


def _gitconfig_path() -> Path:
    return Path.home() / ".gitconfig"


def _parse_link_header(header: str) -> str | None:
    if not header:
        return None
    for chunk in header.split(","):
        parts = [part.strip() for part in chunk.split(";")]
        if len(parts) < 2:
            continue
        if parts[1] == 'rel="next"':
            url_part = parts[0]
            if url_part.startswith("<") and url_part.endswith(">"):
                return url_part[1:-1]
    return None


def _parse_github_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_github_timestamp(value: str | None) -> str:
    parsed = _parse_github_datetime(value)
    if parsed is None:
        return value or "-"
    return _human_time(parsed)


def _github_status_badge(
    state: str | None, is_draft: bool, merged_at: str | None
) -> tuple[str, str]:
    if merged_at:
        return "merged", "status-merged"
    if is_draft:
        return "draft", "status-draft"
    if state == "open":
        return "open", "status-open"
    return "closed", "status-idle"


def _format_jira_timestamp(value: str | None) -> str:
    parsed = _parse_github_datetime(value)
    if parsed is None:
        return value or "-"
    return _human_time(parsed)


def _jira_status_badge(status: dict | None) -> tuple[str, str]:
    if not isinstance(status, dict):
        return "unknown", "status-idle"
    name = status.get("name") or "unknown"
    category = status.get("statusCategory")
    category_key = ""
    if isinstance(category, dict):
        category_key = category.get("key") or ""
    if category_key == "done":
        return name, "status-success"
    if category_key == "indeterminate":
        return name, "status-running"
    if category_key == "new":
        return name, "status-open"
    return name, "status-idle"


def _jira_avatar_url(user: dict | None) -> str:
    if not isinstance(user, dict):
        return ""
    avatars = user.get("avatarUrls")
    if not isinstance(avatars, dict):
        return ""
    for key in ("48x48", "32x32", "24x24", "16x16"):
        value = avatars.get(key)
        if isinstance(value, str) and value:
            return value
    for value in avatars.values():
        if isinstance(value, str) and value:
            return value
    return ""


def _user_initial(name: str | None) -> str:
    if not isinstance(name, str):
        return "?"
    stripped = name.strip()
    if not stripped:
        return "?"
    return stripped[:1].upper()


def _adf_to_text(node: object) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_adf_to_text(item) for item in node)
    if not isinstance(node, dict):
        return ""
    node_type = node.get("type")
    content = node.get("content")
    if node_type == "text":
        return node.get("text", "")
    if node_type == "hardBreak":
        return "\n"
    if node_type in {"paragraph", "heading", "blockquote"}:
        text = _adf_to_text(content)
        if text:
            return f"{text.strip()}\n"
        return ""
    if node_type == "codeBlock":
        text = _adf_to_text(content)
        if text:
            return f"{text.rstrip()}\n"
        return ""
    if node_type in {"bulletList", "orderedList"}:
        items: list[str] = []
        index = 1
        if isinstance(content, list):
            for child in content:
                if not isinstance(child, dict) or child.get("type") != "listItem":
                    continue
                item_text = _adf_to_text(child.get("content"))
                item_text = " ".join(item_text.splitlines()).strip()
                prefix = "- " if node_type == "bulletList" else f"{index}. "
                items.append(prefix + item_text if item_text else prefix.strip())
                index += 1
        return "\n".join(items) + ("\n" if items else "")
    if node_type == "listItem":
        return _adf_to_text(content)
    if content:
        return _adf_to_text(content)
    return ""


def _normalize_adf_text(value: object) -> str:
    text = _adf_to_text(value)
    if not text:
        return ""
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(lines).strip()


def _label_style(color: str) -> str:
    cleaned = color.strip().lstrip("#")
    if len(cleaned) != 6:
        return (
            "background: rgba(148, 163, 184, 0.18); "
            "border-color: rgba(148, 163, 184, 0.4); "
            "color: #e2e8f0;"
        )
    try:
        red = int(cleaned[0:2], 16)
        green = int(cleaned[2:4], 16)
        blue = int(cleaned[4:6], 16)
    except ValueError:
        return (
            "background: rgba(148, 163, 184, 0.18); "
            "border-color: rgba(148, 163, 184, 0.4); "
            "color: #e2e8f0;"
        )
    luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255
    text_color = "#0b0f14" if luminance > 0.7 else "#f8fafc"
    return (
        f"background: rgba({red}, {green}, {blue}, 0.18); "
        f"border-color: rgba({red}, {green}, {blue}, 0.45); "
        f"color: {text_color};"
    )


def _normalize_github_labels(labels: object) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    if not isinstance(labels, list):
        return normalized
    for item in labels:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or ""
        if not name:
            continue
        color = item.get("color") or ""
        normalized.append({"name": name, "style": _label_style(color)})
    return normalized


def _extract_user_logins(items: object) -> list[str]:
    if not isinstance(items, list):
        return []
    logins = {
        item.get("login")
        for item in items
        if isinstance(item, dict) and item.get("login")
    }
    return sorted(logins)


def _fetch_github_repos(pat: str) -> list[str]:
    repos: list[str] = []
    if not pat:
        return repos
    url = "https://api.github.com/user/repos?per_page=100&sort=updated"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {pat}",
        "User-Agent": "llmctl-studio",
    }
    while url:
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.load(response)
                repos.extend(
                    item["full_name"]
                    for item in payload
                    if isinstance(item, dict) and "full_name" in item
                )
                url = _parse_link_header(response.headers.get("Link", ""))
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise ValueError("GitHub PAT is invalid or lacks repo access.") from exc
            raise ValueError("GitHub API error while fetching repositories.") from exc
        except URLError as exc:
            raise ValueError("Unable to reach GitHub API.") from exc
    return sorted(set(repos))


def _normalize_atlassian_site(site: str) -> str:
    cleaned = (site or "").strip()
    if not cleaned:
        return ""
    if not cleaned.startswith(("http://", "https://")):
        cleaned = f"https://{cleaned}"
    return cleaned.rstrip("/")


def _normalize_confluence_site(site: str) -> str:
    base = _normalize_atlassian_site(site)
    if not base:
        return ""
    if not base.endswith("/wiki"):
        return f"{base}/wiki"
    return base


def _parse_option_entries(raw: str | None) -> list[dict[str, str]]:
    cleaned = (raw or "").strip()
    if not cleaned:
        return []
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    options: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in payload:
        value = ""
        label = ""
        if isinstance(item, dict):
            value = (item.get("value") or "").strip()
            label = (item.get("label") or "").strip()
        elif isinstance(item, str):
            value = item.strip()
        if not value or value in seen:
            continue
        options.append({"value": value, "label": label or value})
        seen.add(value)
    options.sort(key=lambda option: option["label"].lower())
    return options


def _serialize_option_entries(options: list[dict[str, str]]) -> str:
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in options:
        if not isinstance(item, dict):
            continue
        value = (item.get("value") or "").strip()
        label = (item.get("label") or "").strip()
        if not value or value in seen:
            continue
        normalized.append({"value": value, "label": label or value})
        seen.add(value)
    if not normalized:
        return ""
    return json.dumps(normalized, separators=(",", ":"))


def _merge_selected_option(
    options: list[dict[str, str]], selected: str | None
) -> list[dict[str, str]]:
    merged = list(options)
    cleaned_selected = (selected or "").strip()
    if not cleaned_selected:
        return merged
    if all(option.get("value") != cleaned_selected for option in merged):
        merged.insert(0, {"value": cleaned_selected, "label": cleaned_selected})
    return merged


def _confluence_space_options(settings: dict[str, str]) -> list[dict[str, str]]:
    return _merge_selected_option(
        _parse_option_entries(settings.get("space_options")),
        settings.get("space"),
    )


def _normalize_rag_db_provider(value: str | None) -> str:
    candidate = (value or "").strip().lower()
    if candidate in RAG_DB_PROVIDER_CHOICES:
        return candidate
    return RAG_DB_PROVIDER_CHOICES[0]


def _normalize_rag_model_provider(value: str | None) -> str:
    candidate = (value or "").strip().lower()
    if candidate in RAG_MODEL_PROVIDER_CHOICES:
        return candidate
    return "openai"


def _normalize_rag_chat_response_style(value: str | None) -> str:
    candidate = (value or "").strip().lower()
    candidate = RAG_CHAT_RESPONSE_STYLE_ALIASES.get(candidate, candidate)
    if candidate in RAG_CHAT_RESPONSE_STYLE_CHOICES:
        return candidate
    return "high"


def _coerce_rag_int_str(
    value: str | None,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> str:
    raw = (value or "").strip()
    try:
        parsed = int(raw)
    except ValueError:
        parsed = default
    if minimum is not None and parsed < minimum:
        parsed = minimum
    if maximum is not None and parsed > maximum:
        parsed = maximum
    return str(parsed)


def _coerce_rag_float_str(
    value: str | None,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> str:
    raw = (value or "").strip()
    try:
        parsed = float(raw)
    except ValueError:
        parsed = default
    if minimum is not None and parsed < minimum:
        parsed = minimum
    if maximum is not None and parsed > maximum:
        parsed = maximum
    text = f"{parsed:.4f}".rstrip("0").rstrip(".")
    return text or str(default)


def _coerce_rag_model_choice(
    value: str | None,
    *,
    default: str,
    choices: tuple[str, ...],
) -> str:
    candidate = (value or "").strip()
    if candidate in choices:
        return candidate
    return default


def _rag_model_option_entries(
    choices: tuple[str, ...],
    selected: str | None,
) -> list[dict[str, str]]:
    base_options = [{"value": option, "label": option} for option in choices]
    return _merge_selected_option(base_options, selected)


def _rag_default_settings() -> dict[str, str]:
    config = load_rag_config()
    return {
        "db_provider": "chroma",
        "embed_provider": _normalize_rag_model_provider(config.embed_provider),
        "chat_provider": _normalize_rag_model_provider(config.chat_provider),
        "openai_embed_model": config.openai_embedding_model or "text-embedding-3-small",
        "gemini_embed_model": config.gemini_embedding_model or "models/gemini-embedding-001",
        "openai_chat_model": config.openai_chat_model or "gpt-4o-mini",
        "gemini_chat_model": config.gemini_chat_model or "gemini-2.5-flash",
        "chat_temperature": _coerce_rag_float_str(str(config.chat_temperature), 0.2),
        "chat_response_style": _normalize_rag_chat_response_style(
            config.chat_response_style
        ),
        "chat_top_k": str(config.chat_top_k),
        "chat_max_history": str(config.chat_max_history),
        "chat_max_context_chars": str(config.chat_max_context_chars),
        "chat_snippet_chars": str(config.chat_snippet_chars),
        "chat_context_budget_tokens": str(config.chat_context_budget_tokens),
        "index_parallel_workers": str(config.index_parallel_workers),
        "embed_parallel_requests": str(config.embed_parallel_requests),
    }


def _effective_rag_settings() -> dict[str, str]:
    defaults = _rag_default_settings()
    try:
        _ensure_rag_setting_defaults("rag", defaults)
    except Exception:
        pass
    stored = _load_rag_settings("rag")
    settings = {**defaults, **stored}
    settings["db_provider"] = _normalize_rag_db_provider(settings.get("db_provider"))
    settings["embed_provider"] = _normalize_rag_model_provider(
        settings.get("embed_provider")
    )
    settings["chat_provider"] = _normalize_rag_model_provider(
        settings.get("chat_provider")
    )
    settings["chat_response_style"] = _normalize_rag_chat_response_style(
        settings.get("chat_response_style")
    )
    settings["chat_temperature"] = _coerce_rag_float_str(
        settings.get("chat_temperature"),
        float(defaults["chat_temperature"] or 0.2),
        minimum=0.0,
        maximum=2.0,
    )
    settings["chat_top_k"] = _coerce_rag_int_str(
        settings.get("chat_top_k"),
        int(defaults["chat_top_k"] or 5),
        minimum=1,
        maximum=20,
    )
    settings["chat_max_history"] = _coerce_rag_int_str(
        settings.get("chat_max_history"),
        int(defaults["chat_max_history"] or 8),
        minimum=1,
        maximum=50,
    )
    settings["chat_max_context_chars"] = _coerce_rag_int_str(
        settings.get("chat_max_context_chars"),
        int(defaults["chat_max_context_chars"] or 12000),
        minimum=1000,
        maximum=1000000,
    )
    settings["chat_snippet_chars"] = _coerce_rag_int_str(
        settings.get("chat_snippet_chars"),
        int(defaults["chat_snippet_chars"] or 600),
        minimum=100,
        maximum=10000,
    )
    settings["chat_context_budget_tokens"] = _coerce_rag_int_str(
        settings.get("chat_context_budget_tokens"),
        int(defaults["chat_context_budget_tokens"] or 8000),
        minimum=256,
        maximum=100000,
    )
    settings["index_parallel_workers"] = _coerce_rag_int_str(
        settings.get("index_parallel_workers"),
        int(defaults["index_parallel_workers"] or 1),
        minimum=1,
        maximum=64,
    )
    settings["embed_parallel_requests"] = _coerce_rag_int_str(
        settings.get("embed_parallel_requests"),
        int(defaults["embed_parallel_requests"] or 1),
        minimum=1,
        maximum=64,
    )
    settings["openai_embed_model"] = (settings.get("openai_embed_model") or "").strip() or defaults["openai_embed_model"]
    settings["gemini_embed_model"] = (settings.get("gemini_embed_model") or "").strip() or defaults["gemini_embed_model"]
    settings["openai_chat_model"] = (settings.get("openai_chat_model") or "").strip() or defaults["openai_chat_model"]
    settings["gemini_chat_model"] = (settings.get("gemini_chat_model") or "").strip() or defaults["gemini_chat_model"]
    return settings


def _settings_integrations_context(
    *,
    integration_section: str | None = None,
    gitconfig_content: str | None = None,
    github_repo_options: list[str] | None = None,
    jira_project_options: list[dict[str, str]] | None = None,
    jira_board_options: list[dict[str, str]] | None = None,
    confluence_space_options: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    migrate_legacy_google_integration_settings()
    summary = _settings_summary()
    llm_settings = _load_integration_settings("llm")
    github_settings = _load_integration_settings("github")
    jira_settings = _load_integration_settings("jira")
    confluence_settings = _load_integration_settings("confluence")
    google_cloud_settings = _load_integration_settings(GOOGLE_CLOUD_PROVIDER)
    google_workspace_settings = _load_integration_settings(GOOGLE_WORKSPACE_PROVIDER)
    vllm_local_settings = _vllm_local_settings_payload(llm_settings)
    google_cloud_service_email = _google_service_account_email(google_cloud_settings)
    google_workspace_service_email = _google_service_account_email(
        google_workspace_settings
    )
    chroma_settings = _resolved_chroma_settings()
    rag_settings = _effective_rag_settings()
    gitconfig_path = _gitconfig_path()
    gitconfig_exists = gitconfig_path.exists()
    resolved_gitconfig_content = gitconfig_content
    if resolved_gitconfig_content is None:
        resolved_gitconfig_content = ""
        if integration_section == "git" and gitconfig_exists:
            try:
                resolved_gitconfig_content = gitconfig_path.read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError as exc:
                flash(f"Unable to read {gitconfig_path}: {exc}", "error")

    if github_repo_options is None:
        github_repo_options = []
        selected_repo = github_settings.get("repo")
        if selected_repo:
            github_repo_options = [selected_repo]

    if jira_project_options is None:
        jira_project_options = []
        selected_project = jira_settings.get("project_key")
        if selected_project:
            jira_project_options = [
                {"value": selected_project, "label": selected_project}
            ]

    if jira_board_options is None:
        jira_board_options = []
        selected_board = jira_settings.get("board")
        if selected_board:
            jira_board_options = [{"value": selected_board, "label": selected_board}]

    if confluence_space_options is None:
        confluence_space_options = _confluence_space_options(confluence_settings)

    chroma_connected = _chroma_connected(chroma_settings)
    rag_chroma_ready = rag_settings.get("db_provider") != "chroma" or chroma_connected

    return {
        "vllm_local_settings": vllm_local_settings,
        "github_settings": github_settings,
        "jira_settings": jira_settings,
        "confluence_settings": confluence_settings,
        "google_cloud_settings": google_cloud_settings,
        "google_cloud_connected": bool(
            (google_cloud_settings.get("service_account_json") or "").strip()
        ),
        "google_cloud_service_email": google_cloud_service_email,
        "google_workspace_settings": google_workspace_settings,
        "google_workspace_connected": bool(
            (google_workspace_settings.get("service_account_json") or "").strip()
        ),
        "google_workspace_service_email": google_workspace_service_email,
        "chroma_settings": chroma_settings,
        "rag_settings": rag_settings,
        "github_repo_options": github_repo_options,
        "jira_project_options": jira_project_options,
        "jira_board_options": jira_board_options,
        "confluence_space_options": confluence_space_options,
        "github_connected": bool(
            (github_settings.get("pat") or "").strip()
            or (github_settings.get("ssh_key_path") or "").strip()
        ),
        "jira_connected": bool((jira_settings.get("api_key") or "").strip()),
        "confluence_connected": bool((confluence_settings.get("api_key") or "").strip()),
        "chroma_connected": chroma_connected,
        "rag_chroma_ready": rag_chroma_ready,
        "rag_db_provider_choices": RAG_DB_PROVIDER_CHOICES,
        "rag_model_provider_choices": RAG_MODEL_PROVIDER_CHOICES,
        "rag_chat_response_style_choices": RAG_CHAT_RESPONSE_STYLE_CHOICES,
        "gitconfig_path": str(gitconfig_path),
        "gitconfig_exists": gitconfig_exists,
        "gitconfig_content": resolved_gitconfig_content,
        "summary": summary,
        "active_page": "settings_integrations",
    }


INTEGRATION_SETTINGS_SECTIONS: dict[str, dict[str, str]] = {
    "git": {
        "label": "Git",
        "endpoint": "agents.settings_integrations_git",
    },
    "github": {
        "label": "GitHub",
        "endpoint": "agents.settings_integrations_github",
    },
    "jira": {
        "label": "Jira",
        "endpoint": "agents.settings_integrations_jira",
    },
    "confluence": {
        "label": "Confluence",
        "endpoint": "agents.settings_integrations_confluence",
    },
    "google_cloud": {
        "label": "Google Cloud",
        "endpoint": "agents.settings_integrations_google_cloud",
    },
    "google_workspace": {
        "label": "Google Workspace",
        "endpoint": "agents.settings_integrations_google_workspace",
    },
    "huggingface": {
        "label": "Hugging Face",
        "endpoint": "agents.settings_integrations_huggingface",
    },
    "chroma": {
        "label": "ChromaDB",
        "endpoint": "agents.settings_integrations_chroma",
    },
}


def _render_settings_integrations_page(
    section: str,
    *,
    gitconfig_content: str | None = None,
    github_repo_options: list[str] | None = None,
    jira_project_options: list[dict[str, str]] | None = None,
    jira_board_options: list[dict[str, str]] | None = None,
    confluence_space_options: list[dict[str, str]] | None = None,
):
    section_meta = INTEGRATION_SETTINGS_SECTIONS.get(section)
    if section_meta is None:
        abort(404)
    return render_template(
        "settings_integrations.html",
        integration_section=section,
        page_title=f"Settings - Integrations - {section_meta['label']}",
        **_settings_integrations_context(
            integration_section=section,
            gitconfig_content=gitconfig_content,
            github_repo_options=github_repo_options,
            jira_project_options=jira_project_options,
            jira_board_options=jira_board_options,
            confluence_space_options=confluence_space_options,
        ),
    )


def _strip_confluence_html(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(
        r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|tr|blockquote|pre)>",
        "\n",
        text,
    )
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = unescape(text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    compact = "\n".join(line for line in lines if line)
    return compact.strip()


def _sanitize_confluence_html(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = re.sub(
        r"(?is)<(script|style|iframe|object|embed)[^>]*>.*?</\1>",
        "",
        value,
    )
    cleaned = re.sub(r'(?i)\son[a-z]+\s*=\s*"[^"]*"', "", cleaned)
    cleaned = re.sub(r"(?i)\son[a-z]+\s*=\s*'[^']*'", "", cleaned)
    cleaned = re.sub(r"(?i)\son[a-z]+\s*=\s*[^ >]+", "", cleaned)
    cleaned = re.sub(r"(?i)javascript:", "", cleaned)
    return cleaned.strip()


def _safe_site_label(site: str) -> str:
    cleaned = (site or "").strip()
    if not cleaned:
        return ""
    if not cleaned.startswith(("http://", "https://")):
        cleaned = f"https://{cleaned}"
    parsed = urlparse(cleaned)
    host = parsed.netloc or parsed.path
    return host.split("/")[0]


def _safe_email_domain(email: str) -> str:
    cleaned = (email or "").strip()
    if "@" not in cleaned:
        return ""
    return cleaned.split("@", 1)[1]


def _error_body_snippet(exc: HTTPError) -> str:
    try:
        body = exc.read()
    except Exception:
        return ""
    if isinstance(body, bytes):
        text = body.decode("utf-8", "ignore")
    else:
        text = str(body)
    return text.replace("\n", " ")[:300]


def _combine_atlassian_key(api_key: str, username: str) -> str:
    cleaned_key = (api_key or "").strip()
    if not cleaned_key:
        return ""
    if ":" in cleaned_key:
        return cleaned_key
    cleaned_user = (username or "").strip()
    if not cleaned_user:
        return cleaned_key
    return f"{cleaned_user}:{cleaned_key}"


def _build_atlassian_headers(api_key: str) -> dict[str, str]:
    cleaned = (api_key or "").strip()
    if not cleaned:
        return {}
    headers = {
        "Accept": "application/json",
        "User-Agent": "llmctl-studio",
    }
    if ":" in cleaned:
        logger.info("Atlassian auth: using basic key_len=%s", len(cleaned))
        encoded = base64.b64encode(cleaned.encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {encoded}"
    else:
        logger.info("Atlassian auth: using bearer key_len=%s", len(cleaned))
        headers["Authorization"] = f"Bearer {cleaned}"
    return headers


def _jira_board_url(
    base: str, start_at: int, max_results: int, project_key: str | None = None
) -> str:
    params: dict[str, str | int] = {
        "startAt": start_at,
        "maxResults": max_results,
    }
    cleaned_project = (project_key or "").strip()
    if cleaned_project:
        params["projectKeyOrId"] = cleaned_project
    return f"{base}/rest/agile/1.0/board?{urlencode(params)}"


def _fetch_jira_boards(
    api_key: str, site: str, project_key: str | None = None
) -> list[dict[str, str]]:
    boards: list[dict[str, str]] = []
    if not api_key or not site:
        return boards
    base = _normalize_atlassian_site(site)
    if not base:
        return boards
    cleaned_project = (project_key or "").strip()
    auth_mode = "basic" if ":" in api_key else "bearer"
    logger.info(
        "Jira refresh: requesting boards auth=%s site=%s project=%s",
        auth_mode,
        _safe_site_label(base),
        cleaned_project or "any",
    )
    headers = _build_atlassian_headers(api_key)
    url = _jira_board_url(base, 0, 50, cleaned_project)
    seen: set[str] = set()
    while url:
        logger.info("Jira refresh: request url=%s", url)
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                status_code = getattr(response, "status", None)
                logger.info("Jira refresh: response status=%s", status_code)
                payload = json.load(response)
                values = payload.get("values")
                page_count = len(values) if isinstance(values, list) else 0
                logger.info(
                    "Jira refresh: page items=%s isLast=%s",
                    page_count,
                    payload.get("isLast"),
                )
                if isinstance(values, list):
                    for item in values:
                        if not isinstance(item, dict):
                            continue
                        name = item.get("name")
                        if not isinstance(name, str):
                            continue
                        value = name.strip()
                        if not value or value in seen:
                            continue
                        boards.append({"value": value, "label": value})
                        seen.add(value)
                is_last = payload.get("isLast")
                if isinstance(is_last, bool) and is_last:
                    url = None
                    continue
                start_at = payload.get("startAt")
                max_results = payload.get("maxResults")
                total = payload.get("total")
                if (
                    isinstance(start_at, int)
                    and isinstance(max_results, int)
                    and isinstance(total, int)
                ):
                    if start_at + max_results >= total:
                        url = None
                    else:
                        url = _jira_board_url(
                            base, start_at + max_results, max_results, cleaned_project
                        )
                else:
                    url = None
        except HTTPError as exc:
            body_snippet = _error_body_snippet(exc)
            logger.warning(
                "Jira refresh: HTTP error code=%s url=%s body=%s",
                exc.code,
                url,
                body_snippet,
            )
            if exc.code in {401, 403}:
                raise ValueError(
                    "Jira API key is invalid or lacks board access."
                ) from exc
            if exc.code == 404:
                raise ValueError("Jira site URL not found.") from exc
            raise ValueError("Jira API error while fetching boards.") from exc
        except URLError as exc:
            logger.warning("Jira refresh: network error url=%s", url)
            raise ValueError("Unable to reach Jira API.") from exc
    logger.info("Jira refresh: loaded %s boards", len(boards))
    boards.sort(key=lambda item: item["label"].lower())
    return boards


def _fetch_jira_projects(api_key: str, site: str) -> list[dict[str, str]]:
    projects: list[dict[str, str]] = []
    if not api_key or not site:
        return projects
    base = _normalize_atlassian_site(site)
    if not base:
        return projects
    auth_mode = "basic" if ":" in api_key else "bearer"
    logger.info(
        "Jira refresh: requesting projects auth=%s site=%s",
        auth_mode,
        _safe_site_label(base),
    )
    headers = _build_atlassian_headers(api_key)
    url = f"{base}/rest/api/3/project/search?startAt=0&maxResults=50"
    seen: set[str] = set()
    while url:
        logger.info("Jira refresh: request url=%s", url)
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                status_code = getattr(response, "status", None)
                logger.info("Jira refresh: response status=%s", status_code)
                payload = json.load(response)
                values = payload.get("values")
                page_count = len(values) if isinstance(values, list) else 0
                logger.info(
                    "Jira refresh: project page items=%s isLast=%s",
                    page_count,
                    payload.get("isLast"),
                )
                if isinstance(values, list):
                    for item in values:
                        if not isinstance(item, dict):
                            continue
                        key = item.get("key") or ""
                        name = item.get("name") or ""
                        key = key.strip() if isinstance(key, str) else ""
                        name = name.strip() if isinstance(name, str) else ""
                        value = key or name
                        if not value or value in seen:
                            continue
                        label = value
                        if key and name and key != name:
                            label = f"{key} - {name}"
                        projects.append({"value": value, "label": label})
                        seen.add(value)
                is_last = payload.get("isLast")
                if isinstance(is_last, bool) and is_last:
                    url = None
                    continue
                start_at = payload.get("startAt")
                max_results = payload.get("maxResults")
                total = payload.get("total")
                if (
                    isinstance(start_at, int)
                    and isinstance(max_results, int)
                    and isinstance(total, int)
                ):
                    if start_at + max_results >= total:
                        url = None
                    else:
                        url = (
                            f"{base}/rest/api/3/project/search?startAt="
                            f"{start_at + max_results}&maxResults={max_results}"
                        )
                else:
                    url = None
        except HTTPError as exc:
            body_snippet = _error_body_snippet(exc)
            logger.warning(
                "Jira refresh: HTTP error code=%s url=%s body=%s",
                exc.code,
                url,
                body_snippet,
            )
            if exc.code in {401, 403}:
                raise ValueError(
                    "Jira API key is invalid or lacks project access."
                ) from exc
            if exc.code == 404:
                raise ValueError("Jira site URL not found.") from exc
            raise ValueError("Jira API error while fetching projects.") from exc
        except URLError as exc:
            logger.warning("Jira refresh: network error url=%s", url)
            raise ValueError("Unable to reach Jira API.") from exc
    logger.info("Jira refresh: loaded %s projects", len(projects))
    projects.sort(key=lambda item: item["label"].lower())
    return projects


def _fetch_jira_board_by_name(
    api_key: str, site: str, board_name: str
) -> dict[str, object] | None:
    if not api_key or not site:
        return None
    target = (board_name or "").strip()
    if not target:
        return None
    base = _normalize_atlassian_site(site)
    if not base:
        return None
    headers = _build_atlassian_headers(api_key)
    url = (
        f"{base}/rest/agile/1.0/board?"
        f"{urlencode({'startAt': 0, 'maxResults': 50, 'name': target})}"
    )
    target_lower = target.lower()
    fallback_match: dict[str, object] | None = None
    while url:
        logger.info("Jira board lookup: request url=%s", url)
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.load(response)
                values = payload.get("values")
                if isinstance(values, list):
                    for item in values:
                        if not isinstance(item, dict):
                            continue
                        name = item.get("name")
                        if not isinstance(name, str):
                            continue
                        cleaned = name.strip()
                        if cleaned == target:
                            return item
                        if cleaned.lower() == target_lower and fallback_match is None:
                            fallback_match = item
                is_last = payload.get("isLast")
                if isinstance(is_last, bool) and is_last:
                    url = None
                    continue
                start_at = payload.get("startAt")
                max_results = payload.get("maxResults")
                total = payload.get("total")
                if (
                    isinstance(start_at, int)
                    and isinstance(max_results, int)
                    and isinstance(total, int)
                ):
                    if start_at + max_results >= total:
                        url = None
                    else:
                        url = (
                            f"{base}/rest/agile/1.0/board?startAt="
                            f"{start_at + max_results}&maxResults={max_results}"
                        )
                else:
                    url = None
        except HTTPError as exc:
            body_snippet = _error_body_snippet(exc)
            logger.warning(
                "Jira board lookup: HTTP error code=%s url=%s body=%s",
                exc.code,
                url,
                body_snippet,
            )
            if exc.code in {401, 403}:
                raise ValueError(
                    "Jira API key is invalid or lacks board access."
                ) from exc
            if exc.code == 404:
                raise ValueError("Jira site URL not found.") from exc
            raise ValueError("Jira API error while fetching board.") from exc
        except URLError as exc:
            logger.warning("Jira board lookup: network error url=%s", url)
            raise ValueError("Unable to reach Jira API.") from exc
    return fallback_match


def _fetch_jira_board_configuration(
    api_key: str, site: str, board_id: int
) -> dict[str, object]:
    if not api_key or not site or not board_id:
        return {}
    base = _normalize_atlassian_site(site)
    if not base:
        return {}
    headers = _build_atlassian_headers(api_key)
    url = f"{base}/rest/agile/1.0/board/{board_id}/configuration"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except HTTPError as exc:
        body_snippet = _error_body_snippet(exc)
        logger.warning(
            "Jira board config: HTTP error code=%s url=%s body=%s",
            exc.code,
            url,
            body_snippet,
        )
        if exc.code in {401, 403}:
            raise ValueError("Jira API key is invalid or lacks board access.") from exc
        if exc.code == 404:
            raise ValueError("Jira board configuration not found.") from exc
        raise ValueError("Jira API error while fetching board config.") from exc
    except URLError as exc:
        logger.warning("Jira board config: network error url=%s", url)
        raise ValueError("Unable to reach Jira API.") from exc
    if isinstance(payload, dict):
        return payload
    return {}


def _fetch_jira_board_issues(
    api_key: str, site: str, board_id: int
) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    if not api_key or not site or not board_id:
        return issues
    base = _normalize_atlassian_site(site)
    if not base:
        return issues
    headers = _build_atlassian_headers(api_key)
    start_at = 0
    max_results = 50
    total: int | None = None
    while True:
        query = urlencode(
            {
                "startAt": start_at,
                "maxResults": max_results,
                "fields": "summary,status,assignee,issuetype,priority",
            }
        )
        url = f"{base}/rest/agile/1.0/board/{board_id}/issue?{query}"
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.load(response)
        except HTTPError as exc:
            body_snippet = _error_body_snippet(exc)
            logger.warning(
                "Jira board issues: HTTP error code=%s url=%s body=%s",
                exc.code,
                url,
                body_snippet,
            )
            if exc.code in {401, 403}:
                raise ValueError("Jira API key is invalid or lacks board access.") from exc
            if exc.code == 404:
                raise ValueError("Jira board issues not found.") from exc
            raise ValueError("Jira API error while fetching board issues.") from exc
        except URLError as exc:
            logger.warning("Jira board issues: network error url=%s", url)
            raise ValueError("Unable to reach Jira API.") from exc
        if not isinstance(payload, dict):
            break
        values = payload.get("issues")
        if isinstance(values, list):
            for item in values:
                if not isinstance(item, dict):
                    continue
                fields = item.get("fields", {})
                if not isinstance(fields, dict):
                    fields = {}
                status = fields.get("status", {})
                if not isinstance(status, dict):
                    status = {}
                status_category = status.get("statusCategory", {})
                if not isinstance(status_category, dict):
                    status_category = {}
                assignee = fields.get("assignee", {})
                if not isinstance(assignee, dict):
                    assignee = {}
                issue_type = fields.get("issuetype", {})
                if not isinstance(issue_type, dict):
                    issue_type = {}
                priority = fields.get("priority", {})
                if not isinstance(priority, dict):
                    priority = {}
                key = item.get("key") or ""
                issues.append(
                    {
                        "key": key,
                        "summary": fields.get("summary") or "Untitled issue",
                        "status": status.get("name") or "",
                        "status_id": status.get("id") or "",
                        "status_category": status_category.get("key") or "",
                        "assignee": assignee.get("displayName") or "",
                        "issue_type": issue_type.get("name") or "",
                        "priority": priority.get("name") or "",
                        "url": f"{base}/browse/{key}" if key else "",
                    }
                )
        total_value = payload.get("total")
        if isinstance(total_value, int):
            total = total_value
        if total is None:
            break
        start_at += max_results
        if start_at >= total:
            break
    return issues


def _build_jira_board_columns(
    board_config: dict[str, object], issues: list[dict[str, object]]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    columns: list[dict[str, object]] = []
    unmapped: list[dict[str, object]] = []
    column_config = board_config.get("columnConfig", {})
    if not isinstance(column_config, dict):
        column_config = {}
    column_defs = column_config.get("columns", [])
    if not isinstance(column_defs, list):
        column_defs = []
    status_id_map: dict[str, int] = {}
    status_name_map: dict[str, int] = {}
    for column in column_defs:
        if not isinstance(column, dict):
            continue
        name = column.get("name") or "Untitled"
        statuses = column.get("statuses", [])
        status_ids: list[str] = []
        status_names: list[str] = []
        if isinstance(statuses, list):
            for status in statuses:
                if not isinstance(status, dict):
                    continue
                status_id = status.get("id")
                status_name = status.get("name")
                if isinstance(status_id, str) and status_id:
                    status_ids.append(status_id)
                if isinstance(status_name, str) and status_name:
                    status_names.append(status_name)
        index = len(columns)
        for status_id in status_ids:
            status_id_map.setdefault(status_id, index)
        for status_name in status_names:
            status_name_map.setdefault(status_name.lower(), index)
        columns.append(
            {
                "name": name,
                "status_ids": status_ids,
                "status_names": status_names,
                "issues": [],
            }
        )
    for issue in issues:
        status_id = issue.get("status_id")
        status_name = issue.get("status")
        index = None
        if isinstance(status_id, str) and status_id in status_id_map:
            index = status_id_map[status_id]
        elif isinstance(status_name, str):
            index = status_name_map.get(status_name.lower())
        if index is None or index >= len(columns):
            unmapped.append(issue)
        else:
            columns[index]["issues"].append(issue)
    return columns, unmapped


def _fetch_jira_issue(
    api_key: str, site: str, issue_key: str
) -> dict[str, object]:
    if not api_key or not site or not issue_key:
        return {}
    base = _normalize_atlassian_site(site)
    if not base:
        return {}
    headers = _build_atlassian_headers(api_key)
    fields = ",".join(
        [
            "summary",
            "description",
            "status",
            "assignee",
            "reporter",
            "priority",
            "issuetype",
            "labels",
            "created",
            "updated",
            "components",
            "fixVersions",
            "project",
            "parent",
            "subtasks",
        ]
    )
    query = urlencode({"fields": fields})
    url = f"{base}/rest/api/3/issue/{quote(issue_key)}?{query}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except HTTPError as exc:
        body_snippet = _error_body_snippet(exc)
        logger.warning(
            "Jira issue: HTTP error code=%s url=%s body=%s",
            exc.code,
            url,
            body_snippet,
        )
        if exc.code in {401, 403}:
            raise ValueError("Jira API key is invalid or lacks issue access.") from exc
        if exc.code == 404:
            raise ValueError("Jira issue not found.") from exc
        raise ValueError("Jira API error while fetching issue.") from exc
    except URLError as exc:
        logger.warning("Jira issue: network error url=%s", url)
        raise ValueError("Unable to reach Jira API.") from exc
    if not isinstance(payload, dict):
        return {}
    fields_payload = payload.get("fields", {})
    if not isinstance(fields_payload, dict):
        fields_payload = {}
    status_payload = fields_payload.get("status")
    status_label, status_class = _jira_status_badge(
        status_payload if isinstance(status_payload, dict) else None
    )
    assignee = fields_payload.get("assignee", {})
    if not isinstance(assignee, dict):
        assignee = {}
    reporter = fields_payload.get("reporter", {})
    if not isinstance(reporter, dict):
        reporter = {}
    assignee_name = assignee.get("displayName") or ""
    reporter_name = reporter.get("displayName") or ""
    issue_type = fields_payload.get("issuetype", {})
    if not isinstance(issue_type, dict):
        issue_type = {}
    priority = fields_payload.get("priority", {})
    if not isinstance(priority, dict):
        priority = {}
    project = fields_payload.get("project", {})
    if not isinstance(project, dict):
        project = {}
    parent = fields_payload.get("parent", {})
    if not isinstance(parent, dict):
        parent = {}
    parent_fields = parent.get("fields", {}) if isinstance(parent, dict) else {}
    if not isinstance(parent_fields, dict):
        parent_fields = {}
    labels = [
        label
        for label in fields_payload.get("labels", [])
        if isinstance(label, str) and label
    ]
    components = [
        component.get("name")
        for component in fields_payload.get("components", [])
        if isinstance(component, dict) and component.get("name")
    ]
    fix_versions = [
        version.get("name")
        for version in fields_payload.get("fixVersions", [])
        if isinstance(version, dict) and version.get("name")
    ]
    subtasks: list[dict[str, object]] = []
    subtask_items = fields_payload.get("subtasks", [])
    if isinstance(subtask_items, list):
        for item in subtask_items:
            if not isinstance(item, dict):
                continue
            subtask_fields = item.get("fields", {})
            if not isinstance(subtask_fields, dict):
                subtask_fields = {}
            subtask_status = subtask_fields.get("status")
            subtask_status_label, subtask_status_class = _jira_status_badge(
                subtask_status if isinstance(subtask_status, dict) else None
            )
            subtask_assignee = subtask_fields.get("assignee", {})
            if not isinstance(subtask_assignee, dict):
                subtask_assignee = {}
            subtask_assignee_name = subtask_assignee.get("displayName") or ""
            subtasks.append(
                {
                    "key": item.get("key") or "",
                    "summary": subtask_fields.get("summary") or "Untitled",
                    "status_label": subtask_status_label,
                    "status_class": subtask_status_class,
                    "assignee": subtask_assignee_name,
                    "assignee_avatar": _jira_avatar_url(subtask_assignee),
                    "assignee_initial": _user_initial(subtask_assignee_name),
                }
            )
    issue_key_value = payload.get("key") or issue_key
    return {
        "key": issue_key_value,
        "summary": fields_payload.get("summary") or "Untitled issue",
        "description": _normalize_adf_text(fields_payload.get("description")),
        "status_label": status_label,
        "status_class": status_class,
        "status": (
            status_payload.get("name")
            if isinstance(status_payload, dict)
            else ""
        ),
        "assignee": assignee_name,
        "assignee_avatar": _jira_avatar_url(assignee),
        "assignee_initial": _user_initial(assignee_name),
        "reporter": reporter_name,
        "reporter_avatar": _jira_avatar_url(reporter),
        "reporter_initial": _user_initial(reporter_name),
        "priority": priority.get("name") or "",
        "issue_type": issue_type.get("name") or "",
        "labels": labels,
        "components": components,
        "fix_versions": fix_versions,
        "created_at": _format_jira_timestamp(fields_payload.get("created")),
        "updated_at": _format_jira_timestamp(fields_payload.get("updated")),
        "project_key": project.get("key") or "",
        "project_name": project.get("name") or "",
        "parent": {
            "key": parent.get("key") or "",
            "summary": parent_fields.get("summary") or "",
        }
        if parent
        else {},
        "subtasks": subtasks,
        "url": f"{base}/browse/{issue_key_value}",
    }


def _fetch_jira_issue_comments(
    api_key: str, site: str, issue_key: str
) -> list[dict[str, object]]:
    comments: list[dict[str, object]] = []
    if not api_key or not site or not issue_key:
        return comments
    base = _normalize_atlassian_site(site)
    if not base:
        return comments
    headers = _build_atlassian_headers(api_key)
    start_at = 0
    max_results = 50
    total: int | None = None
    while True:
        query = urlencode(
            {"startAt": start_at, "maxResults": max_results, "orderBy": "-created"}
        )
        url = f"{base}/rest/api/3/issue/{quote(issue_key)}/comment?{query}"
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.load(response)
        except HTTPError as exc:
            body_snippet = _error_body_snippet(exc)
            logger.warning(
                "Jira comments: HTTP error code=%s url=%s body=%s",
                exc.code,
                url,
                body_snippet,
            )
            if exc.code in {401, 403}:
                raise ValueError("Jira API key is invalid or lacks comment access.") from exc
            if exc.code == 404:
                raise ValueError("Jira issue comments not found.") from exc
            raise ValueError("Jira API error while fetching comments.") from exc
        except URLError as exc:
            logger.warning("Jira comments: network error url=%s", url)
            raise ValueError("Unable to reach Jira API.") from exc
        if not isinstance(payload, dict):
            break
        values = payload.get("comments")
        if isinstance(values, list):
            for item in values:
                if not isinstance(item, dict):
                    continue
                author = item.get("author", {})
                if not isinstance(author, dict):
                    author = {}
                author_name = author.get("displayName") or "unknown"
                body = _normalize_adf_text(item.get("body"))
                comments.append(
                    {
                        "author": author_name,
                        "author_initial": _user_initial(author_name),
                        "author_avatar": _jira_avatar_url(author),
                        "body": body,
                        "created_at": _format_jira_timestamp(item.get("created")),
                        "updated_at": _format_jira_timestamp(item.get("updated")),
                    }
                )
        total_value = payload.get("total")
        if isinstance(total_value, int):
            total = total_value
        if total is None:
            break
        start_at += max_results
        if start_at >= total:
            break
    return comments


def _fetch_confluence_spaces(api_key: str, site: str) -> list[dict[str, str]]:
    spaces: list[dict[str, str]] = []
    if not api_key or not site:
        return spaces
    base = _normalize_confluence_site(site)
    if not base:
        return spaces
    auth_mode = "basic" if ":" in api_key else "bearer"
    logger.info(
        "Confluence refresh: requesting spaces auth=%s site=%s",
        auth_mode,
        _safe_site_label(base),
    )
    headers = _build_atlassian_headers(api_key)
    url = f"{base}/rest/api/space?start=0&limit=50"
    seen: set[str] = set()
    while url:
        logger.info("Confluence refresh: request url=%s", url)
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                status_code = getattr(response, "status", None)
                logger.info("Confluence refresh: response status=%s", status_code)
                payload = json.load(response)
                results = payload.get("results")
                page_count = len(results) if isinstance(results, list) else 0
                logger.info(
                    "Confluence refresh: page items=%s next=%s",
                    page_count,
                    bool(payload.get("_links", {}).get("next")),
                )
                if isinstance(results, list):
                    for item in results:
                        if not isinstance(item, dict):
                            continue
                        key = item.get("key") or ""
                        name = item.get("name") or ""
                        key = key.strip() if isinstance(key, str) else ""
                        name = name.strip() if isinstance(name, str) else ""
                        value = key or name
                        if not value or value in seen:
                            continue
                        label = value
                        if key and name and key != name:
                            label = f"{key} - {name}"
                        spaces.append({"value": value, "label": label})
                        seen.add(value)
                next_link = None
                links = payload.get("_links")
                if isinstance(links, dict):
                    next_link = links.get("next")
                if next_link:
                    if isinstance(next_link, str) and next_link.startswith("http"):
                        url = next_link
                    elif isinstance(next_link, str):
                        url = f"{base}{next_link}"
                    else:
                        url = None
                    continue
                start = payload.get("start")
                limit = payload.get("limit")
                size = payload.get("size")
                if (
                    isinstance(start, int)
                    and isinstance(limit, int)
                    and isinstance(size, int)
                ):
                    if size < limit:
                        url = None
                    else:
                        url = (
                            f"{base}/rest/api/space?start={start + limit}&limit={limit}"
                        )
                else:
                    url = None
        except HTTPError as exc:
            body_snippet = _error_body_snippet(exc)
            logger.warning(
                "Confluence refresh: HTTP error code=%s url=%s body=%s",
                exc.code,
                url,
                body_snippet,
            )
            if exc.code in {401, 403}:
                raise ValueError(
                    "Confluence API key is invalid or lacks space access."
                ) from exc
            if exc.code == 404:
                raise ValueError("Confluence site URL not found.") from exc
            raise ValueError("Confluence API error while fetching spaces.") from exc
        except URLError as exc:
            logger.warning("Confluence refresh: network error url=%s", url)
            raise ValueError("Unable to reach Confluence API.") from exc
    logger.info("Confluence refresh: loaded %s spaces", len(spaces))
    spaces.sort(key=lambda item: item["label"].lower())
    return spaces


def _confluence_page_link(base: str, page: dict[str, object]) -> str:
    links = page.get("_links")
    if not isinstance(links, dict):
        return ""
    webui = links.get("webui")
    if not isinstance(webui, str) or not webui:
        return ""
    if webui.startswith("http://") or webui.startswith("https://"):
        return webui
    return f"{base}{webui}" if webui.startswith("/") else f"{base}/{webui}"


def _build_confluence_page_tree(
    pages: list[dict[str, object]]
) -> list[dict[str, object]]:
    if not pages:
        return []
    page_map: dict[str, dict[str, object]] = {}
    children_by_parent: dict[str, list[str]] = {}
    roots: list[str] = []
    for item in pages:
        page_id = str(item.get("id") or "").strip()
        if not page_id:
            continue
        page_map[page_id] = dict(item)
    for page_id, item in page_map.items():
        parent_id = str(item.get("parent_id") or "").strip()
        if parent_id and parent_id in page_map:
            children_by_parent.setdefault(parent_id, []).append(page_id)
            continue
        roots.append(page_id)
    for child_ids in children_by_parent.values():
        child_ids.sort(
            key=lambda child_id: str(
                page_map.get(child_id, {}).get("title") or ""
            ).lower()
        )
    roots.sort(
        key=lambda root_id: str(page_map.get(root_id, {}).get("title") or "").lower()
    )
    ordered: list[dict[str, object]] = []
    stack: list[tuple[str, int]] = [(root_id, 0) for root_id in reversed(roots)]
    seen: set[str] = set()
    while stack:
        current_id, depth = stack.pop()
        if current_id in seen:
            continue
        seen.add(current_id)
        item = dict(page_map.get(current_id) or {})
        if not item:
            continue
        item["depth"] = depth
        ordered.append(item)
        for child_id in reversed(children_by_parent.get(current_id, [])):
            stack.append((child_id, depth + 1))
    return ordered


def _fetch_confluence_pages(
    api_key: str, site: str, space_key: str
) -> list[dict[str, object]]:
    pages: list[dict[str, object]] = []
    if not api_key or not site or not space_key:
        return pages
    base = _normalize_confluence_site(site)
    if not base:
        return pages
    headers = _build_atlassian_headers(api_key)
    start = 0
    limit = 50
    seen: set[str] = set()
    while True:
        query = urlencode(
            {
                "spaceKey": space_key,
                "type": "page",
                "status": "current",
                "start": start,
                "limit": limit,
                "expand": "history.lastUpdated,version,ancestors",
            }
        )
        url = f"{base}/rest/api/content?{query}"
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.load(response)
        except HTTPError as exc:
            body_snippet = _error_body_snippet(exc)
            logger.warning(
                "Confluence pages: HTTP error code=%s url=%s body=%s",
                exc.code,
                url,
                body_snippet,
            )
            if exc.code in {401, 403}:
                raise ValueError(
                    "Confluence API key is invalid or lacks page access."
                ) from exc
            if exc.code == 404:
                raise ValueError("Confluence space not found.") from exc
            raise ValueError("Confluence API error while fetching pages.") from exc
        except URLError as exc:
            logger.warning("Confluence pages: network error url=%s", url)
            raise ValueError("Unable to reach Confluence API.") from exc
        if not isinstance(payload, dict):
            break
        results = payload.get("results")
        if isinstance(results, list):
            for item in results:
                if not isinstance(item, dict):
                    continue
                page_id = str(item.get("id") or "").strip()
                if not page_id or page_id in seen:
                    continue
                history = item.get("history")
                if not isinstance(history, dict):
                    history = {}
                last_updated = history.get("lastUpdated")
                if not isinstance(last_updated, dict):
                    last_updated = {}
                author = last_updated.get("by")
                if not isinstance(author, dict):
                    author = {}
                ancestors = item.get("ancestors")
                if not isinstance(ancestors, list):
                    ancestors = []
                parent_id = ""
                if ancestors:
                    parent_candidate = ancestors[-1]
                    if isinstance(parent_candidate, dict):
                        parent_id = str(parent_candidate.get("id") or "").strip()
                pages.append(
                    {
                        "id": page_id,
                        "title": str(item.get("title") or "Untitled page"),
                        "status": str(item.get("status") or "current"),
                        "updated_at": _format_jira_timestamp(
                            last_updated.get("when")
                            if isinstance(last_updated.get("when"), str)
                            else None
                        ),
                        "updated_by": str(author.get("displayName") or ""),
                        "url": _confluence_page_link(base, item),
                        "parent_id": parent_id,
                    }
                )
                seen.add(page_id)
        size = payload.get("size")
        if not isinstance(size, int) or size < limit:
            break
        start += limit
    return _build_confluence_page_tree(pages)


def _fetch_confluence_page(
    api_key: str, site: str, page_id: str
) -> dict[str, object]:
    if not api_key or not site or not page_id:
        return {}
    base = _normalize_confluence_site(site)
    if not base:
        return {}
    headers = _build_atlassian_headers(api_key)
    query = urlencode(
        {
            "expand": "space,history.lastUpdated,version,body.view",
        }
    )
    url = f"{base}/rest/api/content/{quote(page_id)}?{query}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except HTTPError as exc:
        body_snippet = _error_body_snippet(exc)
        logger.warning(
            "Confluence page: HTTP error code=%s url=%s body=%s",
            exc.code,
            url,
            body_snippet,
        )
        if exc.code in {401, 403}:
            raise ValueError(
                "Confluence API key is invalid or lacks page access."
            ) from exc
        if exc.code == 404:
            raise ValueError("Confluence page not found.") from exc
        raise ValueError("Confluence API error while fetching page.") from exc
    except URLError as exc:
        logger.warning("Confluence page: network error url=%s", url)
        raise ValueError("Unable to reach Confluence API.") from exc
    if not isinstance(payload, dict):
        return {}
    history = payload.get("history")
    if not isinstance(history, dict):
        history = {}
    last_updated = history.get("lastUpdated")
    if not isinstance(last_updated, dict):
        last_updated = {}
    author = last_updated.get("by")
    if not isinstance(author, dict):
        author = {}
    space = payload.get("space")
    if not isinstance(space, dict):
        space = {}
    body = payload.get("body")
    if not isinstance(body, dict):
        body = {}
    view = body.get("view")
    if not isinstance(view, dict):
        view = {}
    version = payload.get("version")
    if not isinstance(version, dict):
        version = {}
    raw_body_html = view.get("value")
    body_html = _sanitize_confluence_html(raw_body_html if isinstance(raw_body_html, str) else "")
    body_text = _strip_confluence_html(raw_body_html if isinstance(raw_body_html, str) else "")
    if len(body_text) > 6000:
        body_text = f"{body_text[:6000].rstrip()}..."
    return {
        "id": str(payload.get("id") or page_id),
        "title": str(payload.get("title") or "Untitled page"),
        "status": str(payload.get("status") or "current"),
        "space": str(space.get("key") or ""),
        "updated_at": _format_jira_timestamp(
            last_updated.get("when")
            if isinstance(last_updated.get("when"), str)
            else None
        ),
        "updated_by": str(author.get("displayName") or ""),
        "version": str(version.get("number") or ""),
        "body_html": body_html,
        "body_text": body_text,
        "url": _confluence_page_link(base, payload),
    }


def _fetch_github_pull_requests(
    pat: str, repo_full_name: str, status_filter: str = "open"
) -> list[dict[str, object]]:
    pulls: list[dict[str, object]] = []
    if not pat or not repo_full_name:
        return pulls
    filter_key = (status_filter or "open").strip().lower()
    if filter_key not in {"all", "open", "closed", "merged", "draft"}:
        filter_key = "open"
    api_state = "all"
    if filter_key == "open":
        api_state = "open"
    elif filter_key == "draft":
        api_state = "open"
    elif filter_key in {"closed", "merged"}:
        api_state = "closed"
    url = (
        f"https://api.github.com/repos/{repo_full_name}/pulls"
        f"?per_page=50&state={api_state}&sort=updated&direction=desc"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {pat}",
        "User-Agent": "llmctl-studio",
    }
    while url:
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.load(response)
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    state = item.get("state", "open")
                    is_draft = bool(item.get("draft"))
                    merged_at = item.get("merged_at")
                    status_label, status_class = _github_status_badge(
                        state, is_draft, merged_at
                    )
                    if filter_key != "all" and status_label != filter_key:
                        continue
                    updated_label = _format_github_timestamp(item.get("updated_at"))
                    created_label = _format_github_timestamp(item.get("created_at"))
                    labels = _normalize_github_labels(item.get("labels", []))
                    comments = item.get("comments", 0)
                    review_comments = item.get("review_comments", 0)
                    comment_total = 0
                    if isinstance(comments, int):
                        comment_total += comments
                    if isinstance(review_comments, int):
                        comment_total += review_comments
                    pulls.append(
                        {
                            "title": item.get("title", "Untitled pull request"),
                            "number": str(item.get("number", "")),
                            "author": (
                                item.get("user", {}).get("login")
                                if isinstance(item.get("user"), dict)
                                else "unknown"
                            ),
                            "status_label": status_label,
                            "status_class": status_class,
                            "updated_at": updated_label,
                            "created_at": created_label,
                            "labels": labels,
                            "comment_count": comment_total,
                        }
                    )
                url = _parse_link_header(response.headers.get("Link", ""))
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise ValueError("GitHub PAT is invalid or lacks repo access.") from exc
            if exc.code == 404:
                raise ValueError("Repository not found or access denied.") from exc
            raise ValueError("GitHub API error while fetching pull requests.") from exc
        except URLError as exc:
            raise ValueError("Unable to reach GitHub API.") from exc
    return pulls


def _fetch_github_list(url: str, headers: dict[str, str], label: str) -> list[dict]:
    items: list[dict] = []
    while url:
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.load(response)
                if isinstance(payload, list):
                    items.extend(
                        item for item in payload if isinstance(item, dict)
                    )
                url = _parse_link_header(response.headers.get("Link", ""))
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise ValueError("GitHub PAT is invalid or lacks repo access.") from exc
            if exc.code == 404:
                raise ValueError("Pull request not found or access denied.") from exc
            raise ValueError(f"GitHub API error while fetching {label}.") from exc
        except URLError as exc:
            raise ValueError("Unable to reach GitHub API.") from exc
    return items


def _fetch_github_pull_request_detail(
    pat: str, repo_full_name: str, pr_number: int
) -> dict[str, object]:
    if not pat or not repo_full_name:
        return {}
    url = f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {pat}",
        "User-Agent": "llmctl-studio",
    }
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise ValueError("GitHub PAT is invalid or lacks repo access.") from exc
        if exc.code == 404:
            raise ValueError("Pull request not found or access denied.") from exc
        raise ValueError("GitHub API error while fetching pull request.") from exc
    except URLError as exc:
        raise ValueError("Unable to reach GitHub API.") from exc

    if not isinstance(payload, dict):
        return {}
    state = payload.get("state", "open")
    is_draft = bool(payload.get("draft"))
    merged_at = payload.get("merged_at")
    status_label, status_class = _github_status_badge(state, is_draft, merged_at)
    assignees = _extract_user_logins(payload.get("assignees"))
    requested_reviewers = _extract_user_logins(payload.get("requested_reviewers"))
    labels = _normalize_github_labels(payload.get("labels", []))
    commits = payload.get("commits")
    changed_files = payload.get("changed_files")
    additions = payload.get("additions")
    deletions = payload.get("deletions")
    return {
        "number": str(payload.get("number", pr_number)),
        "title": payload.get("title") or "Pull request",
        "body": payload.get("body") or "",
        "author": (
            payload.get("user", {}).get("login")
            if isinstance(payload.get("user"), dict)
            else "unknown"
        ),
        "status_label": status_label,
        "status_class": status_class,
        "created_at": _format_github_timestamp(payload.get("created_at")),
        "updated_at": _format_github_timestamp(payload.get("updated_at")),
        "merged_at": _format_github_timestamp(merged_at) if merged_at else "",
        "html_url": payload.get("html_url", ""),
        "head": (
            payload.get("head", {}).get("ref")
            if isinstance(payload.get("head"), dict)
            else ""
        ),
        "base": (
            payload.get("base", {}).get("ref")
            if isinstance(payload.get("base"), dict)
            else ""
        ),
        "commits": commits if isinstance(commits, int) else 0,
        "changed_files": changed_files if isinstance(changed_files, int) else 0,
        "additions": additions if isinstance(additions, int) else 0,
        "deletions": deletions if isinstance(deletions, int) else 0,
        "assignees": assignees,
        "requested_reviewers": requested_reviewers,
        "labels": labels,
    }


def _fetch_github_pull_request_timeline(
    pat: str, repo_full_name: str, pr_number: int
) -> tuple[list[dict[str, object]], set[str]]:
    if not pat or not repo_full_name:
        return [], set()
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {pat}",
        "User-Agent": "llmctl-studio",
    }
    issue_comments_url = (
        f"https://api.github.com/repos/{repo_full_name}/issues/{pr_number}/comments"
        "?per_page=100"
    )
    reviews_url = (
        f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}/reviews"
        "?per_page=100"
    )
    review_comments_url = (
        f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}/comments"
        "?per_page=100"
    )
    issue_comments = _fetch_github_list(
        issue_comments_url, headers, "pull request comments"
    )
    reviews = _fetch_github_list(reviews_url, headers, "pull request reviews")
    review_comments = _fetch_github_list(
        review_comments_url, headers, "pull request review comments"
    )

    comments: list[dict[str, object]] = []
    reviewers: set[str] = set()

    def build_comment(
        *,
        author: str,
        body: str,
        created_at_raw: str | None,
        badge_label: str,
        badge_class: str,
        context: str = "",
    ) -> None:
        comments.append(
            {
                "author": author,
                "body": body,
                "created_at": _format_github_timestamp(created_at_raw),
                "badge_label": badge_label,
                "badge_class": badge_class,
                "context": context,
                "sort_key": _parse_github_datetime(created_at_raw)
                or datetime.min.replace(tzinfo=timezone.utc),
            }
        )

    for item in issue_comments:
        author = (
            item.get("user", {}).get("login")
            if isinstance(item.get("user"), dict)
            else "unknown"
        )
        build_comment(
            author=author,
            body=item.get("body") or "",
            created_at_raw=item.get("created_at"),
            badge_label="comment",
            badge_class="status-idle",
        )

    for review in reviews:
        author = (
            review.get("user", {}).get("login")
            if isinstance(review.get("user"), dict)
            else "unknown"
        )
        if author:
            reviewers.add(author)
        state = (review.get("state") or "commented").replace("_", " ").lower()
        if state == "approved":
            badge_class = "status-success"
        elif state == "changes requested":
            badge_class = "status-failed"
        elif state == "dismissed":
            badge_class = "status-warning"
        else:
            badge_class = "status-idle"
        build_comment(
            author=author,
            body=review.get("body") or "",
            created_at_raw=review.get("submitted_at"),
            badge_label=f"review {state}",
            badge_class=badge_class,
        )

    for review_comment in review_comments:
        author = (
            review_comment.get("user", {}).get("login")
            if isinstance(review_comment.get("user"), dict)
            else "unknown"
        )
        path = review_comment.get("path") or ""
        line = review_comment.get("line")
        position = review_comment.get("position")
        context = path
        if isinstance(line, int):
            context = f"{path}:{line}" if path else str(line)
        elif isinstance(position, int):
            context = f"{path}:{position}" if path else str(position)
        build_comment(
            author=author,
            body=review_comment.get("body") or "",
            created_at_raw=review_comment.get("created_at"),
            badge_label="review comment",
            badge_class="status-idle",
            context=context,
        )

    comments.sort(key=lambda item: item["sort_key"])
    for item in comments:
        item.pop("sort_key", None)
    return comments, reviewers




def _build_github_code_review_prompt(
    repo: str,
    pr_number: int,
    pr_title: str | None,
    pr_url: str | None,
    role_prompt: str | None = None,
) -> str:
    pr_label = f"{repo}#{pr_number}" if repo else f"#{pr_number}"
    base_prompt = role_prompt.strip() if role_prompt else CODE_REVIEW_ROLE_PROMPT
    lines = [
        base_prompt,
        "",
        f"Pull request to review: {pr_label}",
    ]
    if pr_title:
        lines.append(f"Title: {pr_title}")
    if pr_url:
        lines.append(f"URL: {pr_url}")
    lines.extend(
        [
            "",
            "Requirements:",
            "- Use the GitHub MCP tools to read the PR, diff, and relevant files.",
            "- Leave feedback as a comment on the pull request (not just in this response).",
            (
                f"- Start the comment with {CODE_REVIEW_PASS_EMOJI} pass "
                f"or {CODE_REVIEW_FAIL_EMOJI} fail."
            ),
            "- Cite explicit files/lines or include short code blocks with file paths.",
            "- Do a full, proper code review every time.",
            "- If you cannot post a comment, explain why in your output.",
        ]
    )
    return "\n".join(lines)


def _fetch_github_actions(pat: str, repo_full_name: str) -> list[dict[str, str]]:
    runs: list[dict[str, str]] = []
    if not pat or not repo_full_name:
        return runs
    url = (
        f"https://api.github.com/repos/{repo_full_name}/actions/runs"
        "?per_page=20"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {pat}",
        "User-Agent": "llmctl-studio",
    }
    while url:
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.load(response)
                items = payload.get("workflow_runs", []) if isinstance(payload, dict) else []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    status = item.get("status") or "completed"
                    conclusion = item.get("conclusion") or ""
                    if status in {"queued", "in_progress"}:
                        status_label = status.replace("_", " ")
                        status_class = "status-warning"
                    elif conclusion == "success":
                        status_label = "success"
                        status_class = "status-success"
                    elif conclusion in {"failure", "timed_out", "action_required"}:
                        status_label = conclusion.replace("_", " ")
                        status_class = "status-failed"
                    elif conclusion:
                        status_label = conclusion.replace("_", " ")
                        status_class = "status-idle"
                    else:
                        status_label = "completed"
                        status_class = "status-idle"
                    updated_raw = item.get("updated_at")
                    if isinstance(updated_raw, str):
                        try:
                            updated_at = datetime.fromisoformat(
                                updated_raw.replace("Z", "+00:00")
                            )
                            updated_label = _human_time(updated_at)
                        except ValueError:
                            updated_label = updated_raw
                    else:
                        updated_label = "-"
                    runs.append(
                        {
                            "name": item.get("name")
                            or item.get("display_title")
                            or "Workflow run",
                            "event": item.get("event", ""),
                            "branch": item.get("head_branch", ""),
                            "status_label": status_label,
                            "status_class": status_class,
                            "updated_at": updated_label,
                        }
                    )
                url = _parse_link_header(response.headers.get("Link", ""))
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise ValueError("GitHub PAT is invalid or lacks actions access.") from exc
            if exc.code == 404:
                raise ValueError("Repository not found or access denied.") from exc
            raise ValueError("GitHub API error while fetching workflow runs.") from exc
        except URLError as exc:
            raise ValueError("Unable to reach GitHub API.") from exc
    return runs


def _fetch_github_contents(
    pat: str, repo_full_name: str, path: str
) -> dict[str, object]:
    if not pat or not repo_full_name:
        return {"entries": [], "file": None, "path": path, "is_dir": True}
    cleaned_path = path.strip("/")
    encoded_path = quote(cleaned_path)
    if cleaned_path:
        url = f"https://api.github.com/repos/{repo_full_name}/contents/{encoded_path}"
    else:
        url = f"https://api.github.com/repos/{repo_full_name}/contents"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {pat}",
        "User-Agent": "llmctl-studio",
    }
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise ValueError("GitHub PAT is invalid or lacks repo access.") from exc
        if exc.code == 404:
            raise ValueError("Repository path not found or access denied.") from exc
        raise ValueError("GitHub API error while fetching code.") from exc
    except URLError as exc:
        raise ValueError("Unable to reach GitHub API.") from exc

    if isinstance(payload, list):
        entries = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            entries.append(
                {
                    "name": item.get("name", ""),
                    "path": item.get("path", ""),
                    "type": item.get("type", ""),
                }
            )
        entries.sort(
            key=lambda entry: (
                0 if entry.get("type") == "dir" else 1,
                entry.get("name", "").lower(),
            )
        )
        return {"entries": entries, "file": None, "path": cleaned_path, "is_dir": True}

    if isinstance(payload, dict):
        if payload.get("type") == "file":
            content = payload.get("content", "")
            if payload.get("encoding") == "base64":
                try:
                    decoded = base64.b64decode(content).decode("utf-8", errors="replace")
                except (ValueError, UnicodeDecodeError):
                    decoded = ""
            else:
                decoded = ""
            return {
                "entries": [],
                "file": {
                    "name": payload.get("name", ""),
                    "path": payload.get("path", cleaned_path),
                    "content": decoded,
                },
                "path": cleaned_path,
                "is_dir": False,
            }
        if payload.get("type") == "dir":
            return {"entries": [], "file": None, "path": cleaned_path, "is_dir": True}

    return {"entries": [], "file": None, "path": cleaned_path, "is_dir": True}


def _load_tasks_page(
    page: int,
    per_page: int,
    *,
    agent_id: int | None = None,
    node_type: str | None = None,
    status: str | None = None,
) -> tuple[list[AgentTask], int, int, int]:
    with session_scope() as session:
        filters = []
        if agent_id is not None:
            filters.append(AgentTask.agent_id == agent_id)
        if node_type:
            flowchart_kind = f"flowchart_{node_type}"
            kind_filters = [AgentTask.kind == flowchart_kind]
            if node_type == FLOWCHART_NODE_TYPE_RAG:
                kind_filters.extend(
                    [
                        AgentTask.kind == RAG_QUICK_INDEX_TASK_KIND,
                        AgentTask.kind == RAG_QUICK_DELTA_TASK_KIND,
                    ]
                )
            filters.append(
                or_(
                    AgentTask.flowchart_node_id.in_(
                        select(FlowchartNode.id).where(FlowchartNode.node_type == node_type)
                    ),
                    *kind_filters,
                )
            )
        if status:
            filters.append(AgentTask.status == status)

        count_stmt = select(func.count(AgentTask.id))
        if filters:
            count_stmt = count_stmt.where(*filters)
        total_tasks = session.execute(count_stmt).scalar_one()
        total_pages = (
            max(1, (total_tasks + per_page - 1) // per_page) if total_tasks else 1
        )
        page = max(1, min(page, total_pages))
        tasks = []
        if total_tasks:
            stmt = (
                select(AgentTask)
                .order_by(AgentTask.created_at.desc())
                .limit(per_page)
                .offset((page - 1) * per_page)
            )
            if filters:
                stmt = stmt.where(*filters)
            tasks = session.execute(stmt).scalars().all()
            for task in tasks:
                _sync_quick_rag_task_from_index_job(session, task)
        return tasks, total_tasks, page, total_pages


def _normalize_flowchart_node_type(value: str | None) -> str | None:
    cleaned = str(value or "").strip().lower()
    if not cleaned:
        return None
    return cleaned if cleaned in FLOWCHART_NODE_TYPE_SET else None


def _flowchart_node_type_from_task_kind(kind: str | None) -> str | None:
    cleaned = str(kind or "").strip().lower()
    if not cleaned or not cleaned.startswith("flowchart_"):
        return None
    return _normalize_flowchart_node_type(cleaned.removeprefix("flowchart_"))


def _build_pagination_items(
    current_page: int, total_pages: int
) -> list[dict[str, int | str]]:
    items: list[dict[str, int | str]] = []
    if total_pages <= 7:
        for page in range(1, total_pages + 1):
            items.append({"type": "page", "page": page})
        return items

    items.append({"type": "page", "page": 1})

    if current_page <= 4:
        window_start, window_end = 2, 5
    elif current_page >= total_pages - 3:
        window_start, window_end = total_pages - 4, total_pages - 1
    else:
        window_start, window_end = current_page - 2, current_page + 2

    if window_start > 2:
        items.append({"type": "gap"})

    for page in range(window_start, window_end + 1):
        items.append({"type": "page", "page": page})

    if window_end < total_pages - 1:
        items.append({"type": "gap"})

    items.append({"type": "page", "page": total_pages})
    return items


def _load_task_templates() -> list[TaskTemplate]:
    with session_scope() as session:
        return (
            session.execute(select(TaskTemplate).order_by(TaskTemplate.created_at.desc()))
            .scalars()
            .all()
        )

PAGINATION_PAGE_SIZES = (10, 25, 50, 100)
PAGINATION_DEFAULT_SIZE = 10
PAGINATION_WINDOW = 2
WORKFLOW_LIST_PER_PAGE = 10


def _parse_page(value: str | None) -> int:
    try:
        page = int(value)
    except (TypeError, ValueError):
        return 1
    return page if page > 0 else 1


def _parse_page_size(value: str | None) -> int:
    try:
        per_page = int(value)
    except (TypeError, ValueError):
        return PAGINATION_DEFAULT_SIZE
    return per_page if per_page in PAGINATION_PAGE_SIZES else PAGINATION_DEFAULT_SIZE


def _pagination_items(current_page: int, total_pages: int) -> list[int | None]:
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


def _build_pagination(
    base_path: str,
    page: int,
    per_page: int,
    total_count: int,
) -> dict[str, object]:
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages

    def _page_url(target_page: int, target_per_page: int | None = None) -> str:
        params = {
            "page": target_page,
            "per_page": target_per_page or per_page,
        }
        return f"{base_path}?{urlencode(params)}"

    page_items = []
    for item in _pagination_items(page, total_pages):
        if item is None:
            page_items.append({"label": "...", "url": None, "is_gap": True})
        else:
            page_items.append(
                {
                    "label": str(item),
                    "url": _page_url(item),
                    "is_gap": False,
                    "is_current": item == page,
                }
            )

    if total_count > 0:
        start_index = (page - 1) * per_page + 1
        end_index = min(total_count, page * per_page)
    else:
        start_index = 0
        end_index = 0

    return {
        "base_path": base_path,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "total_count": total_count,
        "start_index": start_index,
        "end_index": end_index,
        "page_items": page_items,
        "prev_url": _page_url(page - 1) if page > 1 else None,
        "next_url": _page_url(page + 1) if page < total_pages else None,
        "page_sizes": PAGINATION_PAGE_SIZES,
    }


def _load_mcp_servers() -> list[MCPServer]:
    with session_scope() as session:
        return (
            session.execute(
                select(MCPServer)
                .options(
                    selectinload(MCPServer.task_templates),
                    selectinload(MCPServer.flowchart_nodes),
                    selectinload(MCPServer.tasks),
                )
                .order_by(MCPServer.created_at.desc())
            )
            .scalars()
            .all()
        )


def _coerce_chat_id_list(raw_values: list[object], *, field_name: str) -> list[int]:
    ordered: list[int] = []
    for raw in raw_values:
        parsed = _coerce_optional_int(raw, field_name=field_name, minimum=1)
        if parsed is None:
            continue
        if parsed not in ordered:
            ordered.append(parsed)
    return ordered


def _coerce_chat_collection_list(raw_values: list[object]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        cleaned = str(raw or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return ordered


def _chat_rag_health_payload() -> tuple[dict[str, object], list[dict[str, str]]]:
    client = get_rag_contract_client()
    try:
        health = client.health()
        collections = client.list_collections()
    except RAGContractError as exc:
        return (
            {
                "state": CHAT_RAG_HEALTH_CONFIGURED_UNHEALTHY,
                "provider": "chroma",
                "error": str(exc),
            },
            [],
        )
    health_payload = {
        "state": health.state,
        "provider": health.provider,
        "error": health.error,
    }
    collection_payload = [
        {
            "id": item.id,
            "name": item.name,
            "provider": item.provider,
            "status": item.status or "",
        }
        for item in collections
    ]
    collection_payload.sort(key=lambda item: item["name"].lower())
    return health_payload, collection_payload


def _resolved_chat_default_settings(
    *,
    models: list[LLMModel],
    mcp_servers: list[MCPServer],
    rag_collections: list[dict[str, str]],
) -> dict[str, object]:
    settings = load_chat_default_settings_payload()
    llm_settings = _load_integration_settings("llm")
    model_ids = {model.id for model in models}
    mcp_ids = {server.id for server in mcp_servers}
    rag_ids = {
        str(item.get("id") or "").strip()
        for item in rag_collections
        if str(item.get("id") or "").strip()
    }
    default_model_id = settings.get("default_model_id")
    llm_default_model_id = resolve_default_model_id(llm_settings)
    resolved_model_id = (
        default_model_id
        if isinstance(default_model_id, int) and default_model_id in model_ids
        else (
            llm_default_model_id
            if isinstance(llm_default_model_id, int) and llm_default_model_id in model_ids
            else None
        )
    )
    resolved_mcp_server_ids: list[int] = []
    for raw_id in settings.get("default_mcp_server_ids", []):
        if isinstance(raw_id, int) and raw_id in mcp_ids and raw_id not in resolved_mcp_server_ids:
            resolved_mcp_server_ids.append(raw_id)
    resolved_rag_collections: list[str] = []
    for raw_collection in settings.get("default_rag_collections", []):
        cleaned = str(raw_collection or "").strip()
        if not cleaned or cleaned not in rag_ids or cleaned in resolved_rag_collections:
            continue
        resolved_rag_collections.append(cleaned)
    return {
        "default_model_id": resolved_model_id,
        "default_response_complexity": normalize_chat_response_complexity(
            settings.get("default_response_complexity"),
            default=CHAT_RESPONSE_COMPLEXITY_DEFAULT,
        ),
        "default_mcp_server_ids": resolved_mcp_server_ids,
        "default_rag_collections": resolved_rag_collections,
    }


def _split_mcp_servers_by_type(
    mcp_servers: list[MCPServer],
) -> tuple[list[MCPServer], list[MCPServer]]:
    integrated = [
        mcp
        for mcp in mcp_servers
        if (mcp.server_type or MCP_SERVER_TYPE_CUSTOM) == MCP_SERVER_TYPE_INTEGRATED
    ]
    custom = [
        mcp
        for mcp in mcp_servers
        if (mcp.server_type or MCP_SERVER_TYPE_CUSTOM) != MCP_SERVER_TYPE_INTEGRATED
    ]
    return integrated, custom


def _load_scripts() -> list[Script]:
    with session_scope() as session:
        return (
            session.execute(select(Script).order_by(Script.created_at.desc()))
            .scalars()
            .all()
        )


def _load_skills() -> list[Skill]:
    with session_scope() as session:
        return (
            session.execute(
                select(Skill)
                .options(
                    selectinload(Skill.versions).selectinload(SkillVersion.files),
                    selectinload(Skill.agents),
                )
                .order_by(Skill.created_at.desc())
            )
            .scalars()
            .all()
        )


def _load_memories() -> list[Memory]:
    with session_scope() as session:
        return (
            session.execute(select(Memory).order_by(Memory.created_at.desc()))
            .scalars()
            .all()
        )


def _load_attachments() -> list[Attachment]:
    with session_scope() as session:
        return (
            session.execute(
                select(Attachment)
                .options(
                    selectinload(Attachment.tasks),
                    selectinload(Attachment.templates),
                    selectinload(Attachment.flowchart_nodes),
                )
                .order_by(Attachment.created_at.desc())
            )
            .scalars()
            .all()
        )


def _load_milestones() -> list[Milestone]:
    with session_scope() as session:
        return (
            session.execute(
                select(Milestone).order_by(
                    Milestone.completed.asc(),
                    Milestone.due_date.is_(None),
                    Milestone.due_date.asc(),
                    Milestone.created_at.desc(),
                )
            )
            .scalars()
            .all()
        )


def _parse_json_dict(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _flowchart_request_payload() -> dict[str, object]:
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        return payload
    return {}


def _flowchart_as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _flowchart_wants_json() -> bool:
    if (request.args.get("format") or "").strip().lower() == "json":
        return True
    accepted = request.accept_mimetypes
    return (
        accepted["application/json"] > 0
        and accepted["application/json"] >= accepted["text/html"]
    )


def _run_wants_json() -> bool:
    if (request.args.get("format") or "").strip().lower() == "json":
        return True
    accepted = request.accept_mimetypes
    return (
        accepted["application/json"] > 0
        and accepted["application/json"] >= accepted["text/html"]
    )


def _coerce_optional_int(
    value: object,
    *,
    field_name: str,
    minimum: int | None = None,
) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        value = cleaned
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer.") from exc
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{field_name} must be >= {minimum}.")
    return parsed


def _coerce_float(value: object, *, field_name: str, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return default
        value = cleaned
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number.") from exc


def _coerce_optional_handle_id(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip().lower()
    if not cleaned:
        return None
    if not re.fullmatch(r"[a-z][0-9]+", cleaned):
        raise ValueError(f"{field_name} is invalid.")
    return cleaned


def _coerce_flowchart_edge_mode(value: object, *, field_name: str) -> str:
    cleaned = str(value).strip().lower()
    if not cleaned:
        raise ValueError(
            f"{field_name} is required and must be one of {', '.join(FLOWCHART_EDGE_MODE_CHOICES)}."
        )
    if cleaned not in FLOWCHART_EDGE_MODE_CHOICES:
        raise ValueError(
            f"{field_name} must be one of {', '.join(FLOWCHART_EDGE_MODE_CHOICES)}."
        )
    return cleaned


def _flowchart_node_compatibility(node_type: str) -> dict[str, bool]:
    return FLOWCHART_NODE_UTILITY_COMPATIBILITY.get(
        node_type,
        {
            "model": False,
            "mcp": False,
            "scripts": False,
            "skills": False,
            "attachments": False,
        },
    )


def _validate_flowchart_utility_compatibility(
    node_type: str,
    *,
    model_id: int | None,
    mcp_server_ids: list[int] | None = None,
    script_ids: list[int] | None = None,
    skill_ids: list[int] | None = None,
    attachment_ids: list[int] | None = None,
) -> list[str]:
    compatibility = _flowchart_node_compatibility(node_type)
    errors: list[str] = []
    if model_id is not None and not compatibility["model"]:
        errors.append(f"Node type '{node_type}' does not support models.")
    if mcp_server_ids and not compatibility["mcp"]:
        errors.append(f"Node type '{node_type}' does not support MCP servers.")
    if script_ids and not compatibility["scripts"]:
        errors.append(f"Node type '{node_type}' does not support scripts.")
    if skill_ids and not compatibility["skills"]:
        errors.append(f"Node type '{node_type}' does not support skills.")
    if attachment_ids and not compatibility["attachments"]:
        errors.append(f"Node type '{node_type}' does not support attachments.")
    return errors


def _serialize_flowchart(flowchart: Flowchart) -> dict[str, object]:
    return {
        "id": flowchart.id,
        "name": flowchart.name,
        "description": flowchart.description,
        "max_node_executions": flowchart.max_node_executions,
        "max_runtime_minutes": flowchart.max_runtime_minutes,
        "max_parallel_nodes": flowchart.max_parallel_nodes,
        "created_at": _human_time(flowchart.created_at),
        "updated_at": _human_time(flowchart.updated_at),
    }


def _serialize_flowchart_node(node: FlowchartNode) -> dict[str, object]:
    return {
        "id": node.id,
        "flowchart_id": node.flowchart_id,
        "node_type": node.node_type,
        "title": node.title,
        "ref_id": node.ref_id,
        "x": node.x,
        "y": node.y,
        "config": _parse_json_dict(node.config_json),
        "model_id": node.model_id,
        "mcp_server_ids": [server.id for server in node.mcp_servers],
        "script_ids": [script.id for script in node.scripts],
        "attachment_ids": [attachment.id for attachment in node.attachments],
        "compatibility": _flowchart_node_compatibility(node.node_type),
        "created_at": _human_time(node.created_at),
        "updated_at": _human_time(node.updated_at),
    }


def _serialize_flowchart_edge(edge: FlowchartEdge) -> dict[str, object]:
    return {
        "id": edge.id,
        "flowchart_id": edge.flowchart_id,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "source_handle_id": edge.source_handle_id,
        "target_handle_id": edge.target_handle_id,
        "edge_mode": edge.edge_mode,
        "condition_key": edge.condition_key,
        "label": edge.label,
        "created_at": _human_time(edge.created_at),
        "updated_at": _human_time(edge.updated_at),
    }


def _ensure_flowchart_start_node(
    session,
    *,
    flowchart_id: int,
) -> FlowchartNode:
    start_node = (
        session.execute(
            select(FlowchartNode)
            .where(
                FlowchartNode.flowchart_id == flowchart_id,
                FlowchartNode.node_type == FLOWCHART_NODE_TYPE_START,
            )
            .order_by(FlowchartNode.id.asc())
        )
        .scalars()
        .first()
    )
    if start_node is not None:
        return start_node
    return FlowchartNode.create(
        session,
        flowchart_id=flowchart_id,
        node_type=FLOWCHART_NODE_TYPE_START,
        title="Start",
        x=FLOWCHART_DEFAULT_START_X,
        y=FLOWCHART_DEFAULT_START_Y,
        config_json=json.dumps({}, sort_keys=True),
    )


def _serialize_flowchart_run(run: FlowchartRun) -> dict[str, object]:
    return {
        "id": run.id,
        "flowchart_id": run.flowchart_id,
        "status": run.status,
        "celery_task_id": run.celery_task_id,
        "created_at": _human_time(run.created_at),
        "started_at": _human_time(run.started_at),
        "finished_at": _human_time(run.finished_at),
        "updated_at": _human_time(run.updated_at),
    }


def _serialize_node_executor_metadata(task: AgentTask | None) -> dict[str, object]:
    if task is None:
        return {
            "selected_provider": "",
            "final_provider": "",
            "provider_dispatch_id": "",
            "workspace_identity": "",
            "dispatch_status": "",
            "fallback_attempted": False,
            "fallback_reason": "",
            "dispatch_uncertain": False,
            "api_failure_category": "",
            "cli_fallback_used": False,
            "cli_preflight_passed": None,
            "provider_route": "",
            "dispatch_timeline": [],
        }
    selected_provider = str(task.selected_provider or "").strip()
    final_provider = str(task.final_provider or "").strip()
    provider_dispatch_id = str(task.provider_dispatch_id or "").strip()
    workspace_identity = str(task.workspace_identity or "").strip()
    dispatch_status = str(task.dispatch_status or "").strip()
    fallback_attempted = bool(task.fallback_attempted)
    fallback_reason = str(task.fallback_reason or "").strip()
    dispatch_uncertain = bool(task.dispatch_uncertain)
    api_failure_category = str(task.api_failure_category or "").strip()
    cli_fallback_used = bool(task.cli_fallback_used)
    cli_preflight_passed = (
        None if task.cli_preflight_passed is None else bool(task.cli_preflight_passed)
    )
    timeline: list[str] = []
    if selected_provider:
        timeline.append(f"selected={selected_provider}")
    if provider_dispatch_id:
        timeline.append(f"dispatch_id={provider_dispatch_id}")
    if dispatch_status:
        timeline.append(f"dispatch={dispatch_status}")
    if fallback_attempted:
        timeline.append(f"fallback={fallback_reason or 'unknown'}")
    if dispatch_uncertain:
        timeline.append("dispatch_uncertain=true")
    if final_provider:
        timeline.append(f"final={final_provider}")
    provider_route = ""
    if selected_provider and final_provider:
        provider_route = f"{selected_provider} -> {final_provider}"
    elif selected_provider:
        provider_route = selected_provider
    elif final_provider:
        provider_route = final_provider
    return {
        "selected_provider": selected_provider,
        "final_provider": final_provider,
        "provider_dispatch_id": provider_dispatch_id,
        "workspace_identity": workspace_identity,
        "dispatch_status": dispatch_status,
        "fallback_attempted": fallback_attempted,
        "fallback_reason": fallback_reason,
        "dispatch_uncertain": dispatch_uncertain,
        "api_failure_category": api_failure_category,
        "cli_fallback_used": cli_fallback_used,
        "cli_preflight_passed": cli_preflight_passed,
        "provider_route": provider_route,
        "dispatch_timeline": timeline,
    }


def _serialize_run_task(task: AgentTask) -> dict[str, object]:
    metadata = _serialize_node_executor_metadata(task)
    return {
        "id": task.id,
        "status": task.status,
        "started_at": _human_time(task.started_at),
        "finished_at": _human_time(task.finished_at),
        **metadata,
    }


def _flowchart_trace_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        try:
            return int(cleaned, 10)
        except ValueError:
            return None
    return None


def _flowchart_serialize_context_source(
    item: object,
    *,
    default_edge_mode: str,
) -> dict[str, object] | None:
    if not isinstance(item, dict):
        return None
    source_node_id = _flowchart_trace_int(
        item.get("source_node_id", item.get("node_id"))
    )
    source_node_type = str(
        item.get("source_node_type", item.get("node_type")) or ""
    ).strip()
    edge_mode = str(item.get("edge_mode") or default_edge_mode).strip().lower()
    if edge_mode not in {"solid", "dotted"}:
        edge_mode = default_edge_mode
    condition_key = str(item.get("condition_key") or "").strip() or None
    return {
        "source_edge_id": _flowchart_trace_int(item.get("source_edge_id")),
        "source_node_id": source_node_id,
        "source_node_type": source_node_type or None,
        "condition_key": condition_key,
        "execution_index": _flowchart_trace_int(item.get("execution_index")),
        "sequence": _flowchart_trace_int(item.get("sequence")),
        "edge_mode": edge_mode,
    }


def _flowchart_run_node_context_trace(
    input_context: dict[str, object],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    raw_trigger_sources = input_context.get("trigger_sources")
    if not isinstance(raw_trigger_sources, list):
        raw_trigger_sources = input_context.get("upstream_nodes")
    trigger_sources: list[dict[str, object]] = []
    if isinstance(raw_trigger_sources, list):
        for item in raw_trigger_sources:
            serialized = _flowchart_serialize_context_source(
                item,
                default_edge_mode="solid",
            )
            if serialized is None:
                continue
            if str(serialized.get("edge_mode")) != "solid":
                continue
            trigger_sources.append(serialized)

    raw_pulled_sources = input_context.get("pulled_dotted_sources")
    if not isinstance(raw_pulled_sources, list):
        raw_pulled_sources = input_context.get("dotted_upstream_nodes")
    pulled_dotted_sources: list[dict[str, object]] = []
    if isinstance(raw_pulled_sources, list):
        for item in raw_pulled_sources:
            serialized = _flowchart_serialize_context_source(
                item,
                default_edge_mode="dotted",
            )
            if serialized is None:
                continue
            if str(serialized.get("edge_mode")) != "dotted":
                continue
            pulled_dotted_sources.append(serialized)

    return trigger_sources, pulled_dotted_sources


def _serialize_flowchart_run_node(
    node_run: FlowchartRunNode,
    task: AgentTask | None = None,
) -> dict[str, object]:
    input_context = _parse_json_dict(node_run.input_context_json)
    trigger_sources, pulled_dotted_sources = _flowchart_run_node_context_trace(
        input_context
    )
    run_metadata = _serialize_node_executor_metadata(task)
    return {
        "id": node_run.id,
        "flowchart_run_id": node_run.flowchart_run_id,
        "flowchart_node_id": node_run.flowchart_node_id,
        "execution_index": node_run.execution_index,
        "agent_task_id": node_run.agent_task_id,
        "status": node_run.status,
        "input_context": input_context,
        "trigger_sources": trigger_sources,
        "pulled_dotted_sources": pulled_dotted_sources,
        "trigger_source_count": len(trigger_sources),
        "pulled_dotted_source_count": len(pulled_dotted_sources),
        "output_state": _parse_json_dict(node_run.output_state_json),
        "routing_state": _parse_json_dict(node_run.routing_state_json),
        "error": node_run.error,
        "created_at": _human_time(node_run.created_at),
        "started_at": _human_time(node_run.started_at),
        "finished_at": _human_time(node_run.finished_at),
        "updated_at": _human_time(node_run.updated_at),
        **run_metadata,
    }


def _flowchart_node_task_kind(node_type: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", (node_type or "").strip().lower()).strip("_")
    if not cleaned:
        cleaned = "node"
    return f"flowchart_{cleaned}"


def _flowchart_node_task_prompt(
    *,
    flowchart_id: int,
    run_id: int,
    node_run: FlowchartRunNode,
    node_type: str,
) -> str:
    payload = {
        "kind": "flowchart_node_activity",
        "flowchart_id": flowchart_id,
        "flowchart_run_id": run_id,
        "flowchart_node_id": node_run.flowchart_node_id,
        "flowchart_node_run_id": node_run.id,
        "flowchart_node_type": node_type,
        "execution_index": node_run.execution_index,
        "input_context": _parse_json_dict(node_run.input_context_json),
    }
    return json.dumps(payload, sort_keys=True)


def _backfill_flowchart_node_activity_tasks(
    session,
    *,
    flowchart_id: int,
    run_id: int,
) -> int:
    rows = (
        session.execute(
            select(FlowchartRunNode, FlowchartNode)
            .join(FlowchartNode, FlowchartNode.id == FlowchartRunNode.flowchart_node_id)
            .where(
                FlowchartRunNode.flowchart_run_id == run_id,
                FlowchartNode.flowchart_id == flowchart_id,
                FlowchartRunNode.agent_task_id.is_(None),
            )
            .order_by(FlowchartRunNode.created_at.asc(), FlowchartRunNode.id.asc())
        )
        .all()
    )
    created_count = 0
    for node_run, node in rows:
        template_id = node.ref_id if node.node_type == FLOWCHART_NODE_TYPE_TASK else None
        output = (node_run.output_state_json or "").strip() or None
        task = AgentTask.create(
            session,
            task_template_id=template_id,
            flowchart_id=flowchart_id,
            flowchart_run_id=run_id,
            flowchart_node_id=node_run.flowchart_node_id,
            status=node_run.status or "queued",
            kind=_flowchart_node_task_kind(node.node_type),
            prompt=_flowchart_node_task_prompt(
                flowchart_id=flowchart_id,
                run_id=run_id,
                node_run=node_run,
                node_type=node.node_type,
            ),
            output=output,
            error=node_run.error,
            started_at=node_run.started_at,
            finished_at=node_run.finished_at,
        )
        node_run.agent_task_id = task.id
        created_count += 1
    return created_count


def _flowchart_status_class(status: str | None) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"running"}:
        return "status-running"
    if normalized in {"stopping"}:
        return "status-warning"
    if normalized in {"queued", "pending"}:
        return "status-queued"
    if normalized in {"completed", "succeeded"}:
        return "status-success"
    if normalized in {"failed", "error"}:
        return "status-failed"
    if normalized in {"canceled", "cancelled", "stopped"}:
        return "status-canceled"
    return "status-idle"


def _flowchart_catalog(session) -> dict[str, object]:
    integration_overview = _integration_overview()
    rag_health = rag_domain_health_snapshot()
    rag_collections_contract = rag_list_collection_contract()
    rag_collection_rows = rag_collections_contract.get("collections")
    if not isinstance(rag_collection_rows, list):
        rag_collection_rows = []
    agents = (
        session.execute(select(Agent).order_by(Agent.created_at.desc())).scalars().all()
    )
    models = (
        session.execute(select(LLMModel).order_by(LLMModel.created_at.desc()))
        .scalars()
        .all()
    )
    mcp_servers = (
        session.execute(select(MCPServer).order_by(MCPServer.created_at.desc()))
        .scalars()
        .all()
    )
    scripts = (
        session.execute(
            select(Script).order_by(Script.created_at.desc())
        )
        .scalars()
        .all()
    )
    attachments = (
        session.execute(select(Attachment).order_by(Attachment.created_at.desc()))
        .scalars()
        .all()
    )
    scripts = [
        script for script in scripts if not is_legacy_skill_script_type(script.script_type)
    ]
    task_templates = (
        session.execute(
            select(TaskTemplate)
            .options(
                selectinload(TaskTemplate.mcp_servers),
                selectinload(TaskTemplate.scripts),
            )
            .order_by(TaskTemplate.created_at.desc())
        )
        .scalars()
        .all()
    )
    plans = session.execute(select(Plan).order_by(Plan.created_at.desc())).scalars().all()
    flowcharts = (
        session.execute(select(Flowchart).order_by(Flowchart.created_at.desc()))
        .scalars()
        .all()
    )
    milestones = (
        session.execute(select(Milestone).order_by(Milestone.created_at.desc()))
        .scalars()
        .all()
    )
    memories = (
        session.execute(select(Memory).order_by(Memory.created_at.desc())).scalars().all()
    )
    return {
        "agents": [
            {
                "id": agent.id,
                "name": agent.name,
            }
            for agent in agents
        ],
        "models": [
            {
                "id": model.id,
                "name": model.name,
                "provider": model.provider,
                "model_name": _model_display_name(model),
            }
            for model in models
        ],
        "mcp_servers": [
            {
                "id": server.id,
                "name": server.name,
                "server_key": server.server_key,
                "server_type": server.server_type,
            }
            for server in mcp_servers
        ],
        "scripts": [
            {"id": script.id, "file_name": script.file_name, "script_type": script.script_type}
            for script in scripts
        ],
        "attachments": [
            {
                "id": attachment.id,
                "file_name": attachment.file_name,
                "content_type": attachment.content_type,
                "size_bytes": attachment.size_bytes,
            }
            for attachment in attachments
        ],
        "task_integrations": [
            {
                "key": str(option["key"]).strip().lower(),
                "label": str(option.get("label") or option["key"]),
                "description": str(option.get("description") or ""),
                "connected": bool(
                    integration_overview.get(str(option["key"]).strip().lower(), {}).get(
                        "connected"
                    )
                ),
            }
            for option in TASK_INTEGRATION_OPTIONS
            if option.get("key")
        ],
        "tasks": [
            {
                "id": task.id,
                "name": task.name,
                "prompt": task.prompt,
                "model_id": task.model_id,
                "mcp_server_ids": [server.id for server in task.mcp_servers],
                "script_ids": [script.id for script in task.scripts],
            }
            for task in task_templates
        ],
        "flowcharts": [
            {"id": flowchart.id, "name": flowchart.name} for flowchart in flowcharts
        ],
        "plans": [{"id": plan.id, "name": plan.name} for plan in plans],
        "milestones": [
            {"id": milestone.id, "name": milestone.name} for milestone in milestones
        ],
        "memories": [{"id": memory.id, "title": memory.title} for memory in memories],
        "rag_health": {
            "state": str(rag_health.get("state") or RAG_DOMAIN_HEALTH_UNCONFIGURED),
            "provider": str(rag_health.get("provider") or "chroma"),
            "error": str(rag_health.get("error") or "").strip() or None,
        },
        "rag_collections": [
            {
                "id": str(item.get("id") or "").strip(),
                "name": str(item.get("name") or "").strip(),
                "status": str(item.get("status") or "").strip() or "",
            }
            for item in rag_collection_rows
            if isinstance(item, dict)
            and str(item.get("id") or "").strip()
            and str(item.get("name") or "").strip()
        ],
    }


def _flowchart_ref_exists(
    session,
    *,
    node_type: str,
    ref_id: int | None,
) -> bool:
    if ref_id is None:
        return False
    if node_type == FLOWCHART_NODE_TYPE_FLOWCHART:
        return session.get(Flowchart, ref_id) is not None
    if node_type == FLOWCHART_NODE_TYPE_TASK:
        return session.get(TaskTemplate, ref_id) is not None
    if node_type == FLOWCHART_NODE_TYPE_PLAN:
        return session.get(Plan, ref_id) is not None
    if node_type == FLOWCHART_NODE_TYPE_MILESTONE:
        return session.get(Milestone, ref_id) is not None
    if node_type == FLOWCHART_NODE_TYPE_MEMORY:
        return session.get(Memory, ref_id) is not None
    return True


def _task_node_has_prompt(config: object) -> bool:
    if not isinstance(config, dict):
        return False
    prompt = config.get("task_prompt")
    return isinstance(prompt, str) and bool(prompt.strip())


def _is_rag_embedding_model_provider(provider: str | None) -> bool:
    return str(provider or "").strip().lower() in {"codex", "gemini"}


def _sanitize_rag_node_config(
    config_payload: dict[str, object],
    *,
    model_provider: str | None = None,
) -> dict[str, object]:
    mode = str(config_payload.get("mode") or "").strip().lower()
    if mode not in RAG_NODE_MODE_CHOICES:
        raise ValueError(
            "config.mode is required and must be one of: "
            + ", ".join(RAG_NODE_MODE_CHOICES)
            + "."
        )

    collections = rag_normalize_collection_selection(
        config_payload.get("collections")
    )
    if not collections:
        collections = rag_normalize_collection_selection(
            config_payload.get("selected_collections")
        )
    if not collections:
        raise ValueError("config.collections requires at least one selected collection.")

    sanitized: dict[str, object] = {
        "mode": mode,
        "collections": collections,
    }
    if mode == RAG_NODE_MODE_QUERY:
        question_prompt = str(config_payload.get("question_prompt") or "").strip()
        if not question_prompt:
            raise ValueError("config.question_prompt is required for query mode.")
        sanitized["question_prompt"] = question_prompt
        top_k = _coerce_optional_int(
            config_payload.get("top_k"),
            field_name="config.top_k",
            minimum=1,
        )
        if top_k is not None:
            sanitized["top_k"] = min(top_k, 20)
    elif model_provider is not None and not _is_rag_embedding_model_provider(
        model_provider
    ):
        raise ValueError(
            "Index modes require an embedding-capable model provider (codex or gemini)."
        )

    return sanitized


def _validate_flowchart_graph_snapshot(
    nodes: list[dict[str, object]],
    edges: list[dict[str, object]],
) -> list[str]:
    errors: list[str] = []
    node_ids: set[int] = set()
    node_type_by_id: dict[int, str] = {}
    incoming: dict[int, int] = {}
    outgoing: dict[int, int] = {}

    for node in nodes:
        node_id = int(node["id"])
        node_ids.add(node_id)
        node_type = str(node.get("node_type") or "")
        config_payload = node.get("config") if isinstance(node.get("config"), dict) else {}
        node_type_by_id[node_id] = node_type
        incoming.setdefault(node_id, 0)
        outgoing.setdefault(node_id, 0)
        if node_type not in FLOWCHART_NODE_TYPE_CHOICES:
            errors.append(f"Node {node_id} has unknown node_type '{node_type}'.")
            continue
        ref_id = node.get("ref_id")
        if node_type in FLOWCHART_NODE_TYPE_REQUIRES_REF and ref_id is None:
            errors.append(f"Node {node_id} ({node_type}) requires ref_id.")
        if node_type not in FLOWCHART_NODE_TYPE_WITH_REF and ref_id is not None:
            errors.append(f"Node {node_id} ({node_type}) does not allow ref_id.")
        if (
            node_type == FLOWCHART_NODE_TYPE_TASK
            and ref_id is None
            and not _task_node_has_prompt(config_payload)
        ):
            errors.append(
                f"Node {node_id} ({node_type}) requires ref_id or config.task_prompt."
            )
        if node_type == FLOWCHART_NODE_TYPE_RAG:
            try:
                _sanitize_rag_node_config(config_payload)
            except ValueError as exc:
                errors.append(f"Node {node_id} ({node_type}) {exc}")
        if node_type == FLOWCHART_NODE_TYPE_TASK and "integration_keys" in config_payload:
            raw_integration_keys = config_payload.get("integration_keys")
            if raw_integration_keys is not None and not isinstance(
                raw_integration_keys, list
            ):
                errors.append(
                    f"Node {node_id} ({node_type}) config.integration_keys must be an array."
                )
            elif isinstance(raw_integration_keys, list):
                _, invalid_integration_keys = validate_task_integration_keys(
                    raw_integration_keys
                )
                if invalid_integration_keys:
                    errors.append(
                        f"Node {node_id} ({node_type}) config.integration_keys contains invalid keys: "
                        + ", ".join(invalid_integration_keys)
                        + "."
                    )

        compatibility = _flowchart_node_compatibility(node_type)
        if node.get("model_id") is not None and not compatibility["model"]:
            errors.append(f"Node {node_id} ({node_type}) does not support models.")
        mcp_server_ids = node.get("mcp_server_ids") or []
        if mcp_server_ids and not compatibility["mcp"]:
            errors.append(f"Node {node_id} ({node_type}) does not support MCP servers.")
        script_ids = node.get("script_ids") or []
        if script_ids and not compatibility["scripts"]:
            errors.append(f"Node {node_id} ({node_type}) does not support scripts.")
        skill_ids = node.get("skill_ids") or []
        if skill_ids and not compatibility["skills"]:
            errors.append(f"Node {node_id} ({node_type}) does not support skills.")
        attachment_ids = node.get("attachment_ids") or []
        if attachment_ids and not compatibility["attachments"]:
            errors.append(f"Node {node_id} ({node_type}) does not support attachments.")

    start_nodes = [node for node in nodes if node.get("node_type") == FLOWCHART_NODE_TYPE_START]
    if len(start_nodes) != 1:
        errors.append(
            f"Flowchart must contain exactly one start node; found {len(start_nodes)}."
        )

    decision_solid_outgoing_keys: dict[int, list[str]] = {}
    decision_solid_outgoing_counts: dict[int, int] = {}
    edge_modes_by_pair: dict[tuple[int, int], set[str]] = {}
    for edge in edges:
        edge_mode = str(edge.get("edge_mode") or "").strip().lower()
        if edge_mode not in FLOWCHART_EDGE_MODE_CHOICES:
            edge_token = edge.get("id")
            if edge_token is None:
                edge_token = (
                    f"{edge.get('source_node_id')}->{edge.get('target_node_id')}"
                )
            errors.append(
                f"Edge {edge_token} must define edge_mode as solid or dotted."
            )
        source_node_id = int(edge["source_node_id"])
        target_node_id = int(edge["target_node_id"])
        if source_node_id not in node_ids:
            errors.append(f"Edge source node {source_node_id} does not exist.")
            continue
        if target_node_id not in node_ids:
            errors.append(f"Edge target node {target_node_id} does not exist.")
            continue
        outgoing[source_node_id] = outgoing.get(source_node_id, 0) + 1
        incoming[target_node_id] = incoming.get(target_node_id, 0) + 1
        if edge_mode in FLOWCHART_EDGE_MODE_CHOICES:
            edge_modes_by_pair.setdefault((source_node_id, target_node_id), set()).add(
                edge_mode
            )
        node_type = node_type_by_id.get(source_node_id)
        condition_key = (str(edge.get("condition_key") or "")).strip()
        if edge_mode == "solid":
            if node_type == FLOWCHART_NODE_TYPE_DECISION:
                if not condition_key:
                    errors.append(
                        f"Decision node {source_node_id} requires condition_key on each solid outgoing edge."
                    )
                decision_solid_outgoing_keys.setdefault(source_node_id, []).append(
                    condition_key
                )
                decision_solid_outgoing_counts[source_node_id] = (
                    decision_solid_outgoing_counts.get(source_node_id, 0) + 1
                )
            elif condition_key:
                errors.append(
                    "Only decision nodes may define condition_key on solid edges "
                    f"(source node {source_node_id})."
                )
        elif edge_mode == "dotted" and condition_key and node_type != FLOWCHART_NODE_TYPE_DECISION:
            errors.append(
                "Only decision nodes may define condition_key on dotted edges "
                f"(source node {source_node_id})."
            )

    for (source_node_id, target_node_id), modes in edge_modes_by_pair.items():
        if "solid" in modes and "dotted" in modes:
            errors.append(
                f"Edges {source_node_id}->{target_node_id} cannot mix solid and dotted modes for the same source/target pair."
            )

    for node in nodes:
        node_id = int(node["id"])
        node_type = str(node.get("node_type") or "")
        if node_type not in FLOWCHART_NODE_TYPE_CHOICES:
            continue
        outgoing_count = outgoing.get(node_id, 0)
        if node_type == FLOWCHART_NODE_TYPE_END:
            if outgoing_count > FLOWCHART_END_MAX_OUTGOING_EDGES:
                errors.append(f"End node {node_id} cannot have outgoing edges.")
        if node.get("node_type") != FLOWCHART_NODE_TYPE_DECISION:
            continue
        if decision_solid_outgoing_counts.get(node_id, 0) == 0:
            errors.append(f"Decision node {node_id} must have at least one solid outgoing edge.")
        keys = [key for key in decision_solid_outgoing_keys.get(node_id, []) if key]
        if len(keys) != len(set(keys)):
            errors.append(
                f"Decision node {node_id} has duplicate condition_key values across solid edges."
            )

    if len(start_nodes) == 1:
        start_id = int(start_nodes[0]["id"])
        visited: set[int] = set()
        frontier = [start_id]
        adjacency: dict[int, list[int]] = {}
        for edge in edges:
            edge_mode = str(edge.get("edge_mode") or "").strip().lower()
            if edge_mode != "solid":
                continue
            source_node_id = int(edge["source_node_id"])
            target_node_id = int(edge["target_node_id"])
            adjacency.setdefault(source_node_id, []).append(target_node_id)
        while frontier:
            current = frontier.pop()
            if current in visited:
                continue
            visited.add(current)
            for target_id in adjacency.get(current, []):
                if target_id not in visited:
                    frontier.append(target_id)
        disconnected = sorted(node_ids.difference(visited))
        if disconnected:
            errors.append(
                "Disconnected required nodes found: "
                + ", ".join(str(node_id) for node_id in disconnected)
            )

    seen_errors: set[str] = set()
    deduped_errors: list[str] = []
    for error in errors:
        if error in seen_errors:
            continue
        seen_errors.add(error)
        deduped_errors.append(error)
    return deduped_errors


def _flowchart_graph_state(
    flowchart_nodes: list[FlowchartNode],
    flowchart_edges: list[FlowchartEdge],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    nodes = [
        {
            "id": node.id,
            "node_type": node.node_type,
            "ref_id": node.ref_id,
            "config": _parse_json_dict(node.config_json),
            "model_id": node.model_id,
            "mcp_server_ids": [server.id for server in node.mcp_servers],
            "script_ids": [script.id for script in node.scripts],
            "attachment_ids": [attachment.id for attachment in node.attachments],
        }
        for node in flowchart_nodes
    ]
    edges = [
        {
            "id": edge.id,
            "source_node_id": edge.source_node_id,
            "target_node_id": edge.target_node_id,
            "source_handle_id": edge.source_handle_id,
            "target_handle_id": edge.target_handle_id,
            "edge_mode": edge.edge_mode,
            "condition_key": edge.condition_key,
            "label": edge.label,
        }
        for edge in flowchart_edges
    ]
    return nodes, edges


def _validate_flowchart_graph(
    flowchart_nodes: list[FlowchartNode],
    flowchart_edges: list[FlowchartEdge],
) -> list[str]:
    nodes, edges = _flowchart_graph_state(flowchart_nodes, flowchart_edges)
    return _validate_flowchart_graph_snapshot(nodes, edges)


@bp.get("/")
def index():
    return redirect(url_for("agents.dashboard"))


@bp.get("/overview")
def dashboard():
    agents = _load_agents()
    active_agents, summary = _agent_rollup(agents)
    recent_agents = agents[:5]
    recent_runs = sorted(
        [agent for agent in agents if agent.last_run_at],
        key=lambda agent: agent.last_run_at or agent.created_at,
        reverse=True,
    )[:5]
    return render_template(
        "dashboard.html",
        agents=agents,
        active_agents=active_agents,
        recent_agents=recent_agents,
        recent_runs=recent_runs,
        summary=summary,
        human_time=_human_time,
        page_title="Overview",
        active_page="overview",
    )


@bp.get("/agents")
def list_agents():
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    agent_ids = [agent.id for agent in agents]
    agent_status_by_id = _agent_status_by_id(agent_ids)
    roles = _load_roles()
    roles_by_id = {role.id: role.name for role in roles}
    return render_template(
        "agents.html",
        agents=agents,
        agent_status_by_id=agent_status_by_id,
        roles_by_id=roles_by_id,
        summary=summary,
        human_time=_human_time,
        page_title="Agents",
        active_page="agents",
    )


@bp.get("/agents/new")
def new_agent():
    roles = _load_roles()
    return render_template(
        "agent_new.html",
        roles=roles,
        page_title="Create Agent",
        active_page="agents",
    )


@bp.post("/agents")
def create_agent():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    role_raw = request.form.get("role_id", "").strip()

    if not description:
        flash("Agent description is required.", "error")
        return redirect(url_for("agents.new_agent"))

    if not name:
        name = "Untitled Agent"

    role_id = None
    if role_raw:
        try:
            role_id = int(role_raw)
        except ValueError:
            flash("Role must be a number.", "error")
            return redirect(url_for("agents.new_agent"))
    with session_scope() as session:
        if role_id is not None:
            role = session.get(Role, role_id)
            if role is None:
                flash("Role not found.", "error")
                return redirect(url_for("agents.new_agent"))
        prompt_payload = {"description": description}
        prompt_json = json.dumps(prompt_payload, indent=2, sort_keys=True)
        agent = Agent.create(
            session,
            name=name,
            role_id=role_id,
            description=description,
            prompt_json=prompt_json,
            prompt_text=None,
            autonomous_prompt=None,
            is_system=False,
        )
        agent_id = agent.id

    flash(f"Agent {agent_id} created.", "success")
    return redirect(url_for("agents.view_agent", agent_id=agent_id))


@bp.get("/agents/<int:agent_id>")
def view_agent(agent_id: int):
    roles = _load_roles()
    roles_by_id = {role.id: role.name for role in roles}
    with session_scope() as session:
        agent = (
            session.execute(
                select(Agent)
                .options(
                    selectinload(Agent.priorities),
                    selectinload(Agent.skills).selectinload(Skill.versions),
                )
                .where(Agent.id == agent_id)
            )
            .scalars()
            .one_or_none()
        )
        if agent is None:
            abort(404)
        priorities = _ordered_agent_priorities(agent)
        assigned_skills = _ordered_agent_skills(agent)
    agent_status_by_id = _agent_status_by_id([agent.id])
    agent_status = agent_status_by_id.get(agent.id, "stopped")
    return render_template(
        "agent_detail.html",
        agent=agent,
        priorities=priorities,
        assigned_skills=assigned_skills,
        agent_status=agent_status,
        roles_by_id=roles_by_id,
        human_time=_human_time,
        page_title=f"Agent - {agent.name}",
        active_page="agents",
        agent_section="overview",
    )


@bp.get("/agents/<int:agent_id>/edit")
def edit_agent(agent_id: int):
    roles = _load_roles()
    with session_scope() as session:
        agent = (
            session.execute(
                select(Agent)
                .options(
                    selectinload(Agent.priorities),
                    selectinload(Agent.skills).selectinload(Skill.versions),
                )
                .where(Agent.id == agent_id)
            )
            .scalars()
            .one_or_none()
        )
        if agent is None:
            abort(404)
        priorities = _ordered_agent_priorities(agent)
        assigned_skills = _ordered_agent_skills(agent)
        assigned_skill_ids = {skill.id for skill in assigned_skills}
        available_skills = (
            session.execute(
                select(Skill)
                .options(selectinload(Skill.versions))
                .where(Skill.status != SKILL_STATUS_ARCHIVED)
                .order_by(Skill.display_name.asc(), Skill.name.asc(), Skill.id.asc())
            )
            .scalars()
            .all()
        )
        available_skills = [
            skill for skill in available_skills if skill.id not in assigned_skill_ids
        ]
    return render_template(
        "agent_edit.html",
        agent=agent,
        roles=roles,
        priorities=priorities,
        assigned_skills=assigned_skills,
        available_skills=available_skills,
        page_title=f"Edit Agent - {agent.name}",
        active_page="agents",
    )


@bp.post("/agents/<int:agent_id>")
def update_agent(agent_id: int):
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    role_raw = request.form.get("role_id", "").strip()

    if not description:
        flash("Agent description is required.", "error")
        return redirect(url_for("agents.edit_agent", agent_id=agent_id))

    role_id = None
    if role_raw:
        try:
            role_id = int(role_raw)
        except ValueError:
            flash("Role must be a number.", "error")
            return redirect(url_for("agents.edit_agent", agent_id=agent_id))

    with session_scope() as session:
        agent = session.get(Agent, agent_id)
        if agent is None:
            abort(404)
        if role_id is not None:
            role = session.get(Role, role_id)
            if role is None:
                flash("Role not found.", "error")
                return redirect(url_for("agents.edit_agent", agent_id=agent_id))
        if not name:
            name = agent.name or "Untitled Agent"
        prompt_payload = {"description": description}
        prompt_json = json.dumps(prompt_payload, indent=2, sort_keys=True)
        agent.name = name
        agent.description = description
        agent.prompt_json = prompt_json
        agent.prompt_text = None
        agent.autonomous_prompt = None
        agent.role_id = role_id

    flash("Agent updated.", "success")
    return redirect(url_for("agents.view_agent", agent_id=agent_id))


@bp.post("/agents/<int:agent_id>/skills")
def attach_agent_skill(agent_id: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.edit_agent", agent_id=agent_id)
    )
    payload = _flowchart_request_payload()
    raw_skill_id = payload.get("skill_id") if payload else request.form.get("skill_id")
    try:
        skill_id = _coerce_optional_int(raw_skill_id, field_name="skill_id", minimum=1)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(redirect_target)
    if skill_id is None:
        flash("skill_id is required.", "error")
        return redirect(redirect_target)

    with session_scope() as session:
        agent = (
            session.execute(
                select(Agent).options(selectinload(Agent.skills)).where(Agent.id == agent_id)
            )
            .scalars()
            .one_or_none()
        )
        if agent is None:
            abort(404)
        skill = session.get(Skill, skill_id)
        if skill is None:
            flash(f"Skill {skill_id} was not found.", "error")
            return redirect(redirect_target)
        if (skill.status or SKILL_STATUS_ACTIVE) == SKILL_STATUS_ARCHIVED:
            flash(f"Skill {skill_id} is archived and cannot be assigned.", "error")
            return redirect(redirect_target)

        ordered_ids = [item.id for item in _ordered_agent_skills(agent)]
        if skill_id not in ordered_ids:
            ordered_ids.append(skill_id)
            _set_agent_skills(session, agent_id, ordered_ids)
            flash("Skill assigned.", "success")
        else:
            flash("Skill already assigned.", "info")

    return redirect(redirect_target)


@bp.post("/agents/<int:agent_id>/skills/<int:skill_id>/delete")
def detach_agent_skill(agent_id: int, skill_id: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.edit_agent", agent_id=agent_id)
    )
    with session_scope() as session:
        agent = (
            session.execute(
                select(Agent).options(selectinload(Agent.skills)).where(Agent.id == agent_id)
            )
            .scalars()
            .one_or_none()
        )
        if agent is None:
            abort(404)
        ordered_ids = [item.id for item in _ordered_agent_skills(agent) if item.id != skill_id]
        _set_agent_skills(session, agent_id, ordered_ids)
    flash("Skill removed.", "success")
    return redirect(redirect_target)


@bp.post("/agents/<int:agent_id>/skills/<int:skill_id>/move")
def move_agent_skill(agent_id: int, skill_id: int):
    direction = (request.form.get("direction") or "").strip().lower()
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.edit_agent", agent_id=agent_id)
    )
    if direction not in {"up", "down"}:
        flash("Invalid skill reorder direction.", "error")
        return redirect(redirect_target)

    with session_scope() as session:
        agent = (
            session.execute(
                select(Agent).options(selectinload(Agent.skills)).where(Agent.id == agent_id)
            )
            .scalars()
            .one_or_none()
        )
        if agent is None:
            abort(404)
        ordered_ids = [item.id for item in _ordered_agent_skills(agent)]
        index = next((idx for idx, item_id in enumerate(ordered_ids) if item_id == skill_id), None)
        if index is None:
            abort(404)
        if direction == "up" and index > 0:
            ordered_ids[index - 1], ordered_ids[index] = ordered_ids[index], ordered_ids[index - 1]
        elif direction == "down" and index < len(ordered_ids) - 1:
            ordered_ids[index + 1], ordered_ids[index] = ordered_ids[index], ordered_ids[index + 1]
        _set_agent_skills(session, agent_id, ordered_ids)

    return redirect(redirect_target)


@bp.post("/agents/<int:agent_id>/priorities")
def create_agent_priority(agent_id: int):
    content = request.form.get("content", "").strip()
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.edit_agent", agent_id=agent_id)
    )
    if not content:
        flash("Priority content is required.", "error")
        return redirect(redirect_target)
    with session_scope() as session:
        agent = (
            session.execute(
                select(Agent)
                .options(selectinload(Agent.priorities))
                .where(Agent.id == agent_id)
            )
            .scalars()
            .one_or_none()
        )
        if agent is None:
            abort(404)
        position = len(_ordered_agent_priorities(agent)) + 1
        AgentPriority.create(
            session,
            agent_id=agent_id,
            position=position,
            content=content,
        )
    flash("Priority added.", "success")
    return redirect(redirect_target)


@bp.post("/agents/<int:agent_id>/priorities/<int:priority_id>")
def update_agent_priority(agent_id: int, priority_id: int):
    content = request.form.get("content", "").strip()
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.edit_agent", agent_id=agent_id)
    )
    if not content:
        flash("Priority content is required.", "error")
        return redirect(redirect_target)
    with session_scope() as session:
        priority = session.get(AgentPriority, priority_id)
        if priority is None or priority.agent_id != agent_id:
            abort(404)
        priority.content = content
    flash("Priority updated.", "success")
    return redirect(redirect_target)


@bp.post("/agents/<int:agent_id>/priorities/<int:priority_id>/move")
def move_agent_priority(agent_id: int, priority_id: int):
    direction = (request.form.get("direction") or "").strip().lower()
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.edit_agent", agent_id=agent_id)
    )
    if direction not in {"up", "down"}:
        flash("Invalid priority reorder direction.", "error")
        return redirect(redirect_target)
    with session_scope() as session:
        agent = (
            session.execute(
                select(Agent)
                .options(selectinload(Agent.priorities))
                .where(Agent.id == agent_id)
            )
            .scalars()
            .one_or_none()
        )
        if agent is None:
            abort(404)
        priorities = _ordered_agent_priorities(agent)
        index = next(
            (entry_index for entry_index, item in enumerate(priorities) if item.id == priority_id),
            None,
        )
        if index is None:
            abort(404)
        if direction == "up" and index > 0:
            priorities[index - 1], priorities[index] = priorities[index], priorities[index - 1]
        elif direction == "down" and index < len(priorities) - 1:
            priorities[index + 1], priorities[index] = priorities[index], priorities[index + 1]
        _reindex_agent_priorities(priorities)
    return redirect(redirect_target)


@bp.post("/agents/<int:agent_id>/priorities/<int:priority_id>/delete")
def delete_agent_priority(agent_id: int, priority_id: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.edit_agent", agent_id=agent_id)
    )
    with session_scope() as session:
        agent = (
            session.execute(
                select(Agent)
                .options(selectinload(Agent.priorities))
                .where(Agent.id == agent_id)
            )
            .scalars()
            .one_or_none()
        )
        if agent is None:
            abort(404)
        priorities = _ordered_agent_priorities(agent)
        priority = next((item for item in priorities if item.id == priority_id), None)
        if priority is None:
            abort(404)
        session.delete(priority)
        priorities = [item for item in priorities if item.id != priority_id]
        _reindex_agent_priorities(priorities)
    flash("Priority deleted.", "success")
    return redirect(redirect_target)


@bp.post("/roles")
def create_role():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    raw_details = request.form.get("details_json", "").strip()

    if not description:
        flash("Role description is required.", "error")
        return redirect(url_for("agents.new_role"))

    try:
        formatted_details = _parse_role_details(raw_details)
    except json.JSONDecodeError as exc:
        flash(f"Invalid JSON: {exc.msg}", "error")
        return redirect(url_for("agents.new_role"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("agents.new_role"))

    if not name:
        name = "Untitled Role"

    with session_scope() as session:
        role = Role.create(
            session,
            name=name,
            description=description,
            details_json=formatted_details,
            is_system=False,
        )

    flash("Role created.", "success")
    return redirect(url_for("agents.view_role", role_id=role.id))


@bp.post("/agents/<int:agent_id>/start")
def start_agent(agent_id: int):
    fallback_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_agents")
    )
    with session_scope() as session:
        agent = session.get(Agent, agent_id)
        if agent is None:
            abort(404)
        active_run_id = session.execute(
            select(Run.id)
            .where(
                Run.agent_id == agent_id,
                Run.status.in_(RUN_ACTIVE_STATUSES),
            )
            .order_by(Run.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if active_run_id:
            flash("Autorun is already enabled for this agent.", "info")
            return redirect(url_for("agents.view_run", run_id=active_run_id))
        run = Run.create(
            session,
            agent_id=agent_id,
            run_max_loops=agent.run_max_loops,
            status="starting",
            last_started_at=utcnow(),
            run_end_requested=False,
        )
        agent.last_started_at = run.last_started_at
        agent.run_end_requested = False
        session.flush()
        run_id = run.id

    task = run_agent.delay(run_id)

    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            return redirect(fallback_target)
        run.task_id = task.id
        agent = session.get(Agent, run.agent_id)
        if agent is not None:
            agent.task_id = task.id

    flash("Autorun enabled.", "success")
    return redirect(url_for("agents.view_run", run_id=run_id))


@bp.post("/agents/<int:agent_id>/stop")
def stop_agent(agent_id: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_agents")
    )
    task_id = None
    with session_scope() as session:
        agent = session.get(Agent, agent_id)
        if agent is None:
            abort(404)
        run = (
            session.execute(
                select(Run)
                .where(
                    Run.agent_id == agent_id,
                    Run.status.in_(RUN_ACTIVE_STATUSES),
                )
                .order_by(Run.created_at.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if run is None:
            agent.run_end_requested = False
            flash("Autorun is already off.", "info")
            return redirect(redirect_target)
        if run.task_id:
            run.run_end_requested = True
            if run.status in {"starting", "running"}:
                run.status = "stopping"
        else:
            run.status = "stopped"
            run.run_end_requested = False
        if run.task_id:
            run.last_run_task_id = run.task_id
        task_id = run.task_id
        agent.run_end_requested = run.run_end_requested
        if run.task_id:
            agent.last_run_task_id = run.task_id

    if task_id and Config.CELERY_REVOKE_ON_STOP:
        celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")

    flash("Autorun disable requested.", "success")
    return redirect(redirect_target)


@bp.post("/agents/<int:agent_id>/delete")
def delete_agent(agent_id: int):
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_agents")
    )
    with session_scope() as session:
        agent = session.get(Agent, agent_id)
        if agent is None:
            abort(404)
        active_run_id = (
            session.execute(
                select(Run.id)
                .where(
                    Run.agent_id == agent_id,
                    Run.status.in_(RUN_ACTIVE_STATUSES),
                )
                .order_by(Run.created_at.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if active_run_id:
            flash("Disable autorun before deleting.", "error")
            return redirect(next_url)
        runs = (
            session.execute(select(Run).where(Run.agent_id == agent_id))
            .scalars()
            .all()
        )
        run_ids = [run.id for run in runs]
        tasks = (
            session.execute(select(AgentTask).where(AgentTask.agent_id == agent_id))
            .scalars()
            .all()
        )
        task_count = len(tasks)
        for task in tasks:
            task.agent_id = None
        if run_ids:
            session.execute(
                update(AgentTask)
                .where(AgentTask.run_id.in_(run_ids))
                .values(run_id=None)
            )
            for run in runs:
                session.delete(run)
        session.delete(agent)

    flash("Agent deleted.", "success")
    if task_count:
        flash(f"Detached from {task_count} task(s).", "info")
    return redirect(next_url)


@bp.post("/runs/<int:run_id>/start")
def start_run(run_id: int):
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            abort(404)
        target = url_for("agents.view_agent", agent_id=run.agent_id)
    flash("Autoruns are managed from the agent.", "info")
    return redirect(target)


@bp.post("/runs/<int:run_id>/cancel")
def cancel_run(run_id: int):
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            abort(404)
        target = url_for("agents.view_agent", agent_id=run.agent_id)
    flash("Autoruns are managed from the agent.", "info")
    return redirect(target)


@bp.post("/runs/<int:run_id>/end")
def end_run(run_id: int):
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            abort(404)
        target = url_for("agents.view_agent", agent_id=run.agent_id)
    flash("Autoruns are managed from the agent.", "info")
    return redirect(target)


@bp.post("/runs/<int:run_id>/delete")
def delete_run(run_id: int):
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.runs")
    )
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            abort(404)
        if run.status in RUN_ACTIVE_STATUSES:
            flash("Disable autorun before deleting.", "error")
            return redirect(next_url)
        session.execute(
            update(AgentTask)
            .where(AgentTask.run_id == run_id)
            .values(run_id=None)
        )
        session.delete(run)
    flash("Autorun deleted.", "success")
    return redirect(next_url)


@bp.get("/runs/new")
def new_run():
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    selected_agent_id = request.args.get("agent_id", "").strip()
    selected_agent: int | None = None
    if selected_agent_id.isdigit():
        selected_agent = int(selected_agent_id)
    return render_template(
        "run_new.html",
        agents=agents,
        selected_agent_id=selected_agent,
        summary=summary,
        page_title="Autoruns",
        active_page="runs",
    )


@bp.get("/runs/<int:run_id>")
def view_run(run_id: int):
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            abort(404)
        agent = session.get(Agent, run.agent_id)
        if agent is None:
            abort(404)
        run_task_id = run.task_id or run.last_run_task_id
        if run_task_id is None:
            run_task_id = session.execute(
                select(AgentTask.run_task_id)
                .where(
                    AgentTask.run_id == run_id,
                    AgentTask.run_task_id.isnot(None),
                )
                .order_by(AgentTask.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
        run_tasks: list[AgentTask] = []
        provider_filter = (request.args.get("provider") or "").strip().lower()
        dispatch_status_filter = (
            request.args.get("dispatch_status") or ""
        ).strip().lower()
        fallback_filter = (request.args.get("fallback_attempted") or "").strip().lower()
        fallback_filter_value: bool | None = None
        if fallback_filter in {"true", "1", "yes", "on"}:
            fallback_filter_value = True
        elif fallback_filter in {"false", "0", "no", "off"}:
            fallback_filter_value = False
        loops_completed = 0
        if run_task_id:
            task_query = select(AgentTask).where(
                AgentTask.run_task_id == run_task_id,
                AgentTask.run_id == run_id,
            )
            count_query = select(func.count(AgentTask.id)).where(
                AgentTask.run_task_id == run_task_id,
                AgentTask.run_id == run_id,
            )
            if provider_filter in {"workspace", "docker", "kubernetes"}:
                task_query = task_query.where(AgentTask.final_provider == provider_filter)
                count_query = count_query.where(AgentTask.final_provider == provider_filter)
            if dispatch_status_filter in {
                "dispatch_pending",
                "dispatch_submitted",
                "dispatch_confirmed",
                "dispatch_failed",
                "fallback_started",
            }:
                task_query = task_query.where(AgentTask.dispatch_status == dispatch_status_filter)
                count_query = count_query.where(AgentTask.dispatch_status == dispatch_status_filter)
            if fallback_filter_value is not None:
                task_query = task_query.where(
                    AgentTask.fallback_attempted.is_(fallback_filter_value)
                )
                count_query = count_query.where(
                    AgentTask.fallback_attempted.is_(fallback_filter_value)
                )
            run_tasks = (
                session.execute(task_query.order_by(AgentTask.created_at.desc()).limit(50))
                .scalars()
                .all()
            )
            loops_completed = session.execute(count_query).scalar_one()
    run_max_loops = run.run_max_loops or 0
    run_is_forever = run_max_loops < 1
    loops_remaining = (
        None if run_is_forever else max(run_max_loops - loops_completed, 0)
    )
    run_tasks_payload = [_serialize_run_task(task) for task in run_tasks]
    if _run_wants_json():
        return {
            "run": {
                "id": run.id,
                "agent_id": run.agent_id,
                "name": run.name,
                "status": run.status,
                "task_id": run.task_id,
                "last_run_task_id": run.last_run_task_id,
                "run_max_loops": run_max_loops,
                "created_at": _human_time(run.created_at),
                "last_started_at": _human_time(run.last_started_at),
                "last_stopped_at": _human_time(run.last_stopped_at),
                "updated_at": _human_time(run.updated_at),
            },
            "agent": {
                "id": agent.id,
                "name": agent.name,
            },
            "run_task_id": run_task_id,
            "loops_completed": int(loops_completed),
            "loops_remaining": loops_remaining,
            "run_is_forever": run_is_forever,
            "run_tasks": run_tasks_payload,
            "filters": {
                "provider": provider_filter,
                "dispatch_status": dispatch_status_filter,
                "fallback_attempted": (
                    ""
                    if fallback_filter_value is None
                    else ("true" if fallback_filter_value else "false")
                ),
            },
        }
    return render_template(
        "run_detail.html",
        run=run,
        agent=agent,
        run_task_id=run_task_id,
        run_tasks=run_tasks_payload,
        loops_completed=loops_completed,
        loops_remaining=loops_remaining,
        run_is_forever=run_is_forever,
        run_max_loops=run_max_loops,
        summary=summary,
        page_title=run.name or f"Autorun {run.id}",
        active_page="runs",
    )


@bp.get("/runs/<int:run_id>/edit")
def edit_run(run_id: int):
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            abort(404)
        agent = session.get(Agent, run.agent_id)
        if agent is None:
            abort(404)
    run_max_loops = run.run_max_loops or 0
    run_is_forever = run_max_loops < 1
    return render_template(
        "run_edit.html",
        run=run,
        agent=agent,
        agents=agents,
        run_max_loops=run_max_loops,
        run_is_forever=run_is_forever,
        summary=summary,
        page_title=f"Autorun - {run.name or agent.name}",
        active_page="runs",
    )


@bp.post("/runs/<int:run_id>")
def update_run(run_id: int):
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            abort(404)
        target = url_for("agents.view_agent", agent_id=run.agent_id)
    flash("Autoruns are managed from the agent.", "info")
    return redirect(target)


@bp.post("/runs")
def create_run():
    flash("Autoruns are created automatically when you enable autorun on an agent.", "info")
    return redirect(url_for("agents.list_agents"))


@bp.get("/runs")
def runs():
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    page = _parse_positive_int(request.args.get("page"), 1)
    per_page = _parse_positive_int(request.args.get("per_page"), DEFAULT_RUNS_PER_PAGE)
    if per_page not in RUNS_PER_PAGE_OPTIONS:
        per_page = DEFAULT_RUNS_PER_PAGE
    runs, total_runs, page, total_pages = _load_runs_page(page, per_page)
    pagination_items = _build_pagination_items(page, total_pages)
    current_url = request.full_path
    if current_url.endswith("?"):
        current_url = current_url[:-1]
    return render_template(
        "runs.html",
        runs=runs,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total_runs=total_runs,
        per_page_options=RUNS_PER_PAGE_OPTIONS,
        pagination_items=pagination_items,
        current_url=current_url,
        summary=summary,
        human_time=_human_time,
        page_title="Autoruns",
        active_page="runs",
    )


@bp.get("/quick")
def quick_task():
    sync_integrated_mcp_servers()
    agents = _load_agents()
    models = _load_llm_models()
    mcp_servers = _load_mcp_servers()
    integration_options = _build_node_integration_options()
    default_selected_integration_keys = [
        str(option["key"])
        for option in integration_options
        if bool(option.get("connected"))
    ]
    _, summary = _agent_rollup(agents)
    default_model_id = _quick_node_default_model_id(models)
    return render_template(
        "quick_task.html",
        agents=agents,
        models=models,
        mcp_servers=mcp_servers,
        integration_options=integration_options,
        selected_integration_keys=default_selected_integration_keys,
        default_model_id=default_model_id,
        summary=summary,
        page_title="Quick Node",
        active_page="quick",
        fixed_list_page=True,
    )


@bp.get("/chat")
def chat_page():
    sync_integrated_mcp_servers()
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    models = _load_llm_models()
    mcp_servers = _load_mcp_servers()
    threads = list_chat_threads()
    try:
        selected_thread_id = _coerce_optional_int(
            request.args.get("thread_id"),
            field_name="thread_id",
            minimum=1,
        )
    except ValueError:
        selected_thread_id = None
    selected_thread = None
    if selected_thread_id is not None:
        selected_thread = get_chat_thread(selected_thread_id)
    if selected_thread is not None and str(selected_thread.get("status") or "") != "active":
        selected_thread = None
    if selected_thread is None and threads:
        selected_thread = get_chat_thread(int(threads[0]["id"]))
    rag_health, rag_collections = _chat_rag_health_payload()
    chat_default_settings = _resolved_chat_default_settings(
        models=models,
        mcp_servers=mcp_servers,
        rag_collections=rag_collections,
    )
    return render_template(
        "chat_runtime.html",
        summary=summary,
        page_title="Live Chat",
        active_page="chat",
        models=models,
        mcp_servers=mcp_servers,
        threads=threads,
        selected_thread=selected_thread,
        rag_health=rag_health,
        rag_collections=rag_collections,
        chat_default_settings=chat_default_settings,
        chat_settings=load_chat_runtime_settings_payload(),
        fixed_list_page=True,
    )


@bp.get("/chat/activity")
def chat_activity():
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    event_class = (request.args.get("event_class") or "").strip() or None
    event_type = (request.args.get("event_type") or "").strip() or None
    reason_code = (request.args.get("reason_code") or "").strip() or None
    try:
        thread_id = _coerce_optional_int(
            request.args.get("thread_id"),
            field_name="thread_id",
            minimum=1,
        )
    except ValueError:
        thread_id = None
    events = list_chat_activity(
        event_class=event_class,
        event_type=event_type,
        reason_code=reason_code,
        thread_id=thread_id,
    )
    threads = list_chat_threads(include_archived=True)
    return render_template(
        "chat_activity.html",
        summary=summary,
        page_title="Chat Activity",
        active_page="chat_activity",
        events=events,
        threads=threads,
        selected_event_class=event_class or "",
        selected_event_type=event_type or "",
        selected_reason_code=reason_code or "",
        selected_thread_id=thread_id,
    )


@bp.post("/chat/threads")
def create_chat_thread_route():
    try:
        title = (request.form.get("title") or "").strip() or CHAT_DEFAULT_THREAD_TITLE
        default_settings = load_chat_default_settings_payload()
        default_response_complexity = normalize_chat_response_complexity(
            default_settings.get("default_response_complexity"),
            default=CHAT_RESPONSE_COMPLEXITY_DEFAULT,
        )
        response_complexity = normalize_chat_response_complexity(
            request.form.get("response_complexity"),
            default=default_response_complexity,
        )
        model_id_raw = request.form.get("model_id")
        if model_id_raw is None or not str(model_id_raw).strip():
            default_model_id = default_settings.get("default_model_id")
            if isinstance(default_model_id, int):
                model_id = default_model_id
            else:
                model_id = resolve_default_model_id(_load_integration_settings("llm"))
        else:
            model_id = _coerce_optional_int(
                model_id_raw,
                field_name="model_id",
                minimum=1,
            )
        mcp_values = request.form.getlist("mcp_server_ids")
        if not mcp_values and request.form.get("mcp_selection_present") is None:
            mcp_values = [
                str(value)
                for value in default_settings.get("default_mcp_server_ids", [])
                if isinstance(value, int)
            ]
        mcp_server_ids = _coerce_chat_id_list(
            mcp_values,
            field_name="mcp_server_id",
        )
        rag_values = request.form.getlist("rag_collections")
        if not rag_values and request.form.get("rag_selection_present") is None:
            rag_values = [
                str(value)
                for value in default_settings.get("default_rag_collections", [])
            ]
        rag_collections = _coerce_chat_collection_list(
            rag_values
        )
        thread = create_chat_thread(
            title=title,
            model_id=model_id,
            mcp_server_ids=mcp_server_ids,
            rag_collections=rag_collections,
            response_complexity=response_complexity,
        )
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("agents.chat_page"))
    flash("Chat thread created.", "success")
    return redirect(url_for("agents.chat_page", thread_id=thread["id"]))


@bp.post("/chat/threads/<int:thread_id>/config")
def update_chat_thread_route(thread_id: int):
    try:
        response_complexity = normalize_chat_response_complexity(
            request.form.get("response_complexity"),
            default=CHAT_RESPONSE_COMPLEXITY_DEFAULT,
        )
        model_id_raw = request.form.get("model_id")
        if model_id_raw is None:
            existing_thread = get_chat_thread(thread_id)
            model_id = _coerce_optional_int(
                None if existing_thread is None else existing_thread.get("model_id"),
                field_name="model_id",
                minimum=1,
            )
        else:
            model_id = _coerce_optional_int(
                model_id_raw,
                field_name="model_id",
                minimum=1,
            )
        mcp_server_ids = _coerce_chat_id_list(
            request.form.getlist("mcp_server_ids"),
            field_name="mcp_server_id",
        )
        rag_collections = _coerce_chat_collection_list(
            request.form.getlist("rag_collections")
        )
        update_chat_thread_config(
            thread_id,
            model_id=model_id,
            mcp_server_ids=mcp_server_ids,
            rag_collections=rag_collections,
            response_complexity=response_complexity,
        )
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("agents.chat_page", thread_id=thread_id))
    flash("Chat thread settings updated.", "success")
    return redirect(url_for("agents.chat_page", thread_id=thread_id))


@bp.post("/chat/threads/<int:thread_id>/archive")
def archive_chat_thread_route(thread_id: int):
    if not archive_chat_thread(thread_id):
        abort(404)
    flash("Chat thread archived.", "success")
    return redirect(url_for("agents.chat_page"))


@bp.post("/chat/threads/<int:thread_id>/restore")
def restore_chat_thread_route(thread_id: int):
    if not restore_chat_thread(thread_id):
        abort(404)
    flash("Chat thread restored.", "success")
    return redirect(url_for("agents.chat_page", thread_id=thread_id))


@bp.post("/chat/threads/<int:thread_id>/clear")
def clear_chat_thread_route(thread_id: int):
    if not clear_chat_thread(thread_id):
        abort(404)
    flash("Chat thread cleared.", "success")
    return redirect(url_for("agents.chat_page", thread_id=thread_id))


@bp.post("/chat/threads/<int:thread_id>/delete")
def delete_chat_thread_route(thread_id: int):
    if not delete_chat_thread(thread_id):
        abort(404)
    flash("Chat thread deleted.", "success")
    return redirect(url_for("agents.chat_page"))


@bp.post("/quick")
def create_quick_task():
    agent_id_raw = request.form.get("agent_id", "").strip()
    model_id_raw = request.form.get("model_id", "").strip()
    mcp_server_ids_raw = [
        value.strip() for value in request.form.getlist("mcp_server_ids")
    ]
    selected_integration_keys, integration_error = _parse_node_integration_selection()
    prompt = request.form.get("prompt", "").strip()
    uploads = request.files.getlist("attachments")
    if not prompt:
        flash("Prompt is required.", "error")
        return redirect(url_for("agents.quick_task"))
    if integration_error:
        flash(integration_error, "error")
        return redirect(url_for("agents.quick_task"))

    try:
        with session_scope() as session:
            models = (
                session.execute(select(LLMModel).order_by(LLMModel.created_at.desc()))
                .scalars()
                .all()
            )
            if not models:
                flash("Create at least one model before sending a quick node.", "error")
                return redirect(url_for("agents.quick_task"))
            model_ids = {model.id for model in models}
            selected_model_id = _coerce_optional_int(
                model_id_raw,
                field_name="model_id",
                minimum=1,
            )
            if selected_model_id is None:
                selected_model_id = _quick_node_default_model_id(models)
            if selected_model_id is None:
                flash("Model is required.", "error")
                return redirect(url_for("agents.quick_task"))
            if selected_model_id not in model_ids:
                flash("Select a valid model.", "error")
                return redirect(url_for("agents.quick_task"))
            agent_id: int | None = None
            agent: Agent | None = None
            if agent_id_raw:
                agent_id = _coerce_optional_int(
                    agent_id_raw,
                    field_name="agent_id",
                    minimum=1,
                )
                if agent_id is None:
                    flash("Select a valid agent.", "error")
                    return redirect(url_for("agents.quick_task"))
                agent = session.get(Agent, agent_id)
                if agent is None:
                    flash("Agent not found.", "error")
                    return redirect(url_for("agents.quick_task"))
            selected_mcp_ids: list[int] = []
            for raw_id in mcp_server_ids_raw:
                if not raw_id:
                    continue
                parsed_id = _coerce_optional_int(
                    raw_id,
                    field_name="mcp_server_id",
                    minimum=1,
                )
                if parsed_id is None:
                    flash("Invalid MCP server selection.", "error")
                    return redirect(url_for("agents.quick_task"))
                if parsed_id not in selected_mcp_ids:
                    selected_mcp_ids.append(parsed_id)
            selected_mcp_servers: list[MCPServer] = []
            if selected_mcp_ids:
                selected_mcp_servers = (
                    session.execute(
                        select(MCPServer).where(MCPServer.id.in_(selected_mcp_ids))
                    )
                    .scalars()
                    .all()
                )
                if len(selected_mcp_servers) != len(selected_mcp_ids):
                    flash("One or more MCP servers were not found.", "error")
                    return redirect(url_for("agents.quick_task"))
                mcp_by_id = {server.id: server for server in selected_mcp_servers}
                selected_mcp_servers = [
                    mcp_by_id[mcp_id] for mcp_id in selected_mcp_ids
                ]
            system_contract = build_quick_node_system_contract()
            agent_profile = build_quick_node_agent_profile()
            if agent is not None:
                system_contract = {}
                if agent.role_id and agent.role is not None:
                    system_contract["role"] = _build_role_payload(agent.role)
                agent_profile = _build_agent_payload(agent)
            prompt_payload = serialize_prompt_envelope(
                build_prompt_envelope(
                    user_request=prompt,
                    system_contract=system_contract,
                    agent_profile=agent_profile,
                    task_context={"kind": QUICK_TASK_KIND},
                    output_contract=build_one_off_output_contract(),
                )
            )
            task = AgentTask.create(
                session,
                agent_id=agent_id,
                model_id=selected_model_id,
                status="queued",
                prompt=prompt_payload,
                kind=QUICK_TASK_KIND,
                integration_keys_json=serialize_task_integration_keys(
                    selected_integration_keys
                ),
            )
            task.mcp_servers = selected_mcp_servers
            attachments = _save_uploaded_attachments(session, uploads)
            _attach_attachments(task, attachments)
            task_id = task.id
    except ValueError as exc:
        flash(str(exc) or "Invalid quick node configuration.", "error")
        return redirect(url_for("agents.quick_task"))
    except OSError as exc:
        logger.exception("Failed to save quick node attachments")
        flash(str(exc) or "Failed to save attachments.", "error")
        return redirect(url_for("agents.quick_task"))

    celery_task = run_agent_task.delay(task_id)

    with session_scope() as session:
        task = session.get(AgentTask, task_id)
        if task is not None:
            task.celery_task_id = celery_task.id

    flash(f"Quick node {task_id} queued.", "success")
    return redirect(url_for("agents.view_node", task_id=task_id))


@bp.get("/api/chat/threads/<int:thread_id>")
def api_chat_thread(thread_id: int):
    payload = get_chat_thread(thread_id)
    if payload is None:
        return {"error": "Thread not found."}, 404
    return payload


@bp.get("/api/chat/activity")
def api_chat_activity():
    event_class = (request.args.get("event_class") or "").strip() or None
    event_type = (request.args.get("event_type") or "").strip() or None
    reason_code = (request.args.get("reason_code") or "").strip() or None
    try:
        thread_id = _coerce_optional_int(
            request.args.get("thread_id"),
            field_name="thread_id",
            minimum=1,
        )
    except ValueError:
        return {"error": "thread_id must be an integer."}, 400
    return {
        "events": list_chat_activity(
            event_class=event_class,
            event_type=event_type,
            reason_code=reason_code,
            thread_id=thread_id,
        )
    }


@bp.post("/api/chat/threads/<int:thread_id>/turn")
def api_chat_turn(thread_id: int):
    payload = request.get_json(silent=True) or {}
    for key in ("model_id", "mcp_server_ids", "rag_collections", "response_complexity"):
        if key in payload:
            return {
                "error": (
                    "Model, response complexity, MCP, and RAG selectors "
                    "are session-scoped only."
                ),
                "reason_code": CHAT_REASON_SELECTOR_SCOPE,
            }, 400
    message = str(payload.get("message") or "").strip()
    if not message:
        return {"error": "Message is required."}, 400
    try:
        result = execute_chat_turn(thread_id=thread_id, message=message)
    except ValueError as exc:
        return {"error": str(exc)}, 400
    thread_payload = get_chat_thread(thread_id)
    if result.ok:
        return {
            "ok": True,
            "thread_id": result.thread_id,
            "turn_id": result.turn_id,
            "request_id": result.request_id,
            "reply": result.reply,
            "thread": thread_payload,
        }
    status_code = 500
    if result.reason_code == "RAG_UNAVAILABLE_FOR_SELECTED_COLLECTIONS":
        status_code = 503
    elif result.reason_code == "RAG_RETRIEVAL_EXECUTION_FAILED":
        status_code = 502
    return {
        "ok": False,
        "thread_id": result.thread_id,
        "turn_id": result.turn_id,
        "request_id": result.request_id,
        "reason_code": result.reason_code,
        "error": result.error,
        "rag_health_state": result.rag_health_state,
        "selected_collections": result.selected_collections,
        "thread": thread_payload,
    }, status_code


@bp.get("/nodes", endpoint="list_nodes")
def list_nodes():
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    page = _parse_positive_int(request.args.get("page"), 1)
    per_page = _parse_positive_int(request.args.get("per_page"), DEFAULT_TASKS_PER_PAGE)
    if per_page not in TASKS_PER_PAGE_OPTIONS:
        per_page = DEFAULT_TASKS_PER_PAGE
    agent_filter_options = []
    filter_agent_ids = set()
    for agent in agents:
        label = agent.name or f"Agent {agent.id}"
        agent_filter_options.append({"value": agent.id, "label": label})
        filter_agent_ids.add(agent.id)
    agent_filter_options.sort(key=lambda item: item["label"].lower())

    with session_scope() as session:
        status_values = {
            value
            for value in session.execute(select(AgentTask.status).distinct())
            .scalars()
            .all()
            if value
        }
        node_type_values = {
            normalized
            for normalized in (
                _normalize_flowchart_node_type(value)
                for value in session.execute(
                    select(FlowchartNode.node_type)
                    .join(AgentTask, AgentTask.flowchart_node_id == FlowchartNode.id)
                    .distinct()
                )
                .scalars()
                .all()
            )
            if normalized
        }
        for kind_value in (
            value
            for value in session.execute(select(AgentTask.kind).distinct())
            .scalars()
            .all()
            if value
        ):
            normalized = _flowchart_node_type_from_task_kind(kind_value)
            if normalized:
                node_type_values.add(normalized)

    node_type_filter_raw = (
        request.args.get("node_type") or request.args.get("kind") or ""
    ).strip()
    normalized_node_type_filter = _normalize_flowchart_node_type(node_type_filter_raw)
    node_type_filter = (
        normalized_node_type_filter
        if normalized_node_type_filter in node_type_values
        else None
    )
    status_filter_raw = (request.args.get("status") or "").strip()
    status_filter = status_filter_raw if status_filter_raw in status_values else None
    agent_filter = None
    agent_filter_raw = request.args.get("agent_id")
    if agent_filter_raw:
        candidate = _parse_positive_int(agent_filter_raw, 0)
        if candidate in filter_agent_ids:
            agent_filter = candidate

    status_order = {
        "pending": 0,
        "queued": 1,
        "running": 2,
        "succeeded": 3,
        "failed": 4,
        "canceled": 5,
    }
    node_type_options = [
        {"value": node_type, "label": node_type.replace("_", " ")}
        for node_type in sorted(node_type_values)
    ]
    task_status_options = [
        {"value": status, "label": status.replace("_", " ")}
        for status in sorted(
            status_values, key=lambda value: (status_order.get(value, 99), value)
        )
    ]

    tasks, total_tasks, page, total_pages = _load_tasks_page(
        page,
        per_page,
        agent_id=agent_filter,
        node_type=node_type_filter,
        status=status_filter,
    )
    pagination_items = _build_pagination_items(page, total_pages)
    agent_ids = {task.agent_id for task in tasks if task.agent_id is not None}
    agents_by_id = {}
    if agent_ids:
        with session_scope() as session:
            rows = session.execute(
                select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids))
            ).all()
        agents_by_id = {row[0]: row[1] for row in rows}
    flowchart_node_ids = {
        task.flowchart_node_id
        for task in tasks
        if task.flowchart_node_id is not None
    }
    flowchart_node_types_by_id: dict[int, str] = {}
    flowchart_node_names_by_id: dict[int, str] = {}
    if flowchart_node_ids:
        with session_scope() as session:
            rows = session.execute(
                select(
                    FlowchartNode.id,
                    FlowchartNode.node_type,
                    FlowchartNode.title,
                    FlowchartNode.config_json,
                    FlowchartNode.ref_id,
                ).where(
                    FlowchartNode.id.in_(flowchart_node_ids)
                )
            ).all()
            template_ids = {
                int(row[4])
                for row in rows
                if row[4] is not None
                and str(row[1] or "").strip().lower() == FLOWCHART_NODE_TYPE_TASK
            }
            template_name_by_id: dict[int, str] = {}
            if template_ids:
                template_name_by_id = {
                    int(row[0]): str(row[1])
                    for row in session.execute(
                        select(TaskTemplate.id, TaskTemplate.name).where(
                            TaskTemplate.id.in_(template_ids)
                        )
                    ).all()
                }
        for row in rows:
            node_id = int(row[0])
            node_type = str(row[1] or "").strip().lower()
            title = str(row[2] or "").strip()
            config = _parse_json_dict(row[3])
            inline_name = config.get("task_name")
            task_name = str(inline_name).strip() if isinstance(inline_name, str) else ""
            if not task_name:
                task_name = title
            if not task_name and row[4] is not None and node_type == FLOWCHART_NODE_TYPE_TASK:
                task_name = template_name_by_id.get(int(row[4]), "")
            if not task_name:
                type_label = (node_type or "node").replace("_", " ")
                task_name = f"{type_label} node"
            flowchart_node_types_by_id[node_id] = node_type
            flowchart_node_names_by_id[node_id] = task_name
    task_node_types: dict[int, str | None] = {}
    task_node_names: dict[int, str] = {}
    for task in tasks:
        flowchart_node_type = (
            _normalize_flowchart_node_type(
                flowchart_node_types_by_id.get(task.flowchart_node_id)
            )
            if task.flowchart_node_id is not None
            else None
        )
        resolved_node_type = flowchart_node_type or _flowchart_node_type_from_task_kind(
            task.kind
        )
        if not resolved_node_type and is_quick_rag_task_kind(task.kind):
            resolved_node_type = FLOWCHART_NODE_TYPE_RAG
        task_node_types[task.id] = resolved_node_type
        if task.flowchart_node_id is not None:
            task_node_names[task.id] = flowchart_node_names_by_id.get(
                task.flowchart_node_id, f"Node {task.flowchart_node_id}"
            )
        elif is_quick_rag_task_kind(task.kind):
            task_node_names[task.id] = _quick_rag_task_display_name(task)
        elif is_quick_task_kind(task.kind):
            task_node_names[task.id] = "Quick node"
        else:
            task_node_names[task.id] = "-"
    current_url = request.full_path
    if current_url.endswith("?"):
        current_url = current_url[:-1]
    return render_template(
        "tasks.html",
        tasks=tasks,
        agents_by_id=agents_by_id,
        task_node_types=task_node_types,
        task_node_names=task_node_names,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total_tasks=total_tasks,
        per_page_options=TASKS_PER_PAGE_OPTIONS,
        pagination_items=pagination_items,
        agent_filter_options=agent_filter_options,
        node_type_options=node_type_options,
        task_status_options=task_status_options,
        quick_rag_task_kinds=[
            RAG_QUICK_INDEX_TASK_KIND,
            RAG_QUICK_DELTA_TASK_KIND,
        ],
        agent_filter=agent_filter,
        node_type_filter=node_type_filter,
        status_filter=status_filter,
        current_url=current_url,
        summary=summary,
        human_time=_human_time,
        page_title="Nodes",
        active_page="nodes",
    )


@bp.get("/nodes/<int:task_id>", endpoint="view_node")
def view_node(task_id: int):
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    selected_integration_labels: list[str] = []
    task_integrations_legacy_default = False
    with session_scope() as session:
        task = (
            session.execute(
                select(AgentTask)
                .options(
                    selectinload(AgentTask.scripts),
                    selectinload(AgentTask.attachments),
                    selectinload(AgentTask.mcp_servers),
                )
                .where(AgentTask.id == task_id)
            )
            .scalars()
            .first()
        )
        if task is None:
            abort(404)
        _sync_quick_rag_task_from_index_job(session, task)
        agent = None
        if task.agent_id is not None:
            agent = (
                session.execute(
                    select(Agent)
                    .where(Agent.id == task.agent_id)
                )
                .scalars()
                .first()
            )
        template = (
            session.get(TaskTemplate, task.task_template_id)
            if task.task_template_id
            else None
        )
        stage_entries = _build_stage_entries(task)
        prompt_text, prompt_json = _parse_task_prompt(task.prompt)
        task_output = _task_output_for_display(task.output)
        selected_integration_keys = parse_task_integration_keys(task.integration_keys_json)
        if selected_integration_keys is None:
            task_integrations_legacy_default = True
            selected_integration_labels = [
                TASK_INTEGRATION_LABELS[key]
                for key in sorted(TASK_INTEGRATION_KEYS)
            ]
        else:
            selected_integration_labels = [
                TASK_INTEGRATION_LABELS[key]
                for key in sorted(selected_integration_keys)
                if key in TASK_INTEGRATION_LABELS
            ]
    return render_template(
        "task_detail.html",
        task=task,
        task_output=task_output,
        is_quick_task=is_quick_task_kind(task.kind),
        is_quick_rag_task=is_quick_rag_task_kind(task.kind),
        quick_rag_task_context=_quick_rag_task_context(task),
        agent=agent,
        template=template,
        stage_entries=stage_entries,
        prompt_text=prompt_text,
        prompt_json=prompt_json,
        selected_integration_labels=selected_integration_labels,
        task_integrations_legacy_default=task_integrations_legacy_default,
        summary=summary,
        page_title=f"Node {task_id}",
        active_page="nodes",
    )


@bp.post(
    "/nodes/<int:task_id>/attachments/<int:attachment_id>/remove",
    endpoint="remove_node_attachment",
)
def remove_node_attachment(task_id: int, attachment_id: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.view_node", task_id=task_id)
    )
    removed_path: str | None = None
    with session_scope() as session:
        task = (
            session.execute(
                select(AgentTask)
                .options(selectinload(AgentTask.attachments))
                .where(AgentTask.id == task_id)
            )
            .scalars()
            .first()
        )
        if task is None:
            abort(404)
        attachment = next(
            (item for item in task.attachments if item.id == attachment_id), None
        )
        if attachment is None:
            flash("Attachment not found on this node.", "error")
            return redirect(redirect_target)
        task.attachments.remove(attachment)
        session.flush()
        removed_path = _delete_attachment_if_unused(session, attachment)
    if removed_path:
        remove_attachment_file(removed_path)
    flash("Attachment removed.", "success")
    return redirect(redirect_target)


@bp.get("/nodes/<int:task_id>/status", endpoint="node_status")
def node_status(task_id: int):
    with session_scope() as session:
        task = session.get(AgentTask, task_id)
        if task is None:
            abort(404)
        _sync_quick_rag_task_from_index_job(session, task)
        return {
            "id": task.id,
            "status": task.status,
            "run_task_id": task.run_task_id,
            "celery_task_id": task.celery_task_id,
            "prompt_length": len(task.prompt) if task.prompt else 0,
            "output": _task_output_for_display(task.output),
            "error": task.error or "",
            "current_stage": task.current_stage or "",
            "stage_logs": _parse_stage_logs(task.stage_logs),
            "stage_entries": _build_stage_entries(task),
            "started_at": _human_time(task.started_at),
            "finished_at": _human_time(task.finished_at),
            "created_at": _human_time(task.created_at),
        }


@bp.post("/nodes/<int:task_id>/cancel", endpoint="cancel_node")
def cancel_node(task_id: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_nodes")
    )
    with session_scope() as session:
        task = session.get(AgentTask, task_id)
        if task is None:
            abort(404)
        if task.status not in {"queued", "running"}:
            flash("Node is not running.", "info")
            return redirect(redirect_target)
        if task.celery_task_id and Config.CELERY_REVOKE_ON_STOP:
            celery_app.control.revoke(
                task.celery_task_id, terminate=True, signal="SIGTERM"
            )
        task.status = "canceled"
        task.error = "Canceled by user."
        task.finished_at = utcnow()
    flash("Node cancel requested.", "success")
    return redirect(redirect_target)


@bp.post("/nodes/<int:task_id>/delete", endpoint="delete_node")
def delete_node(task_id: int):
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_nodes")
    )
    with session_scope() as session:
        task = session.get(AgentTask, task_id)
        if task is None:
            abort(404)
        if task.status in {"queued", "running"} and task.celery_task_id:
            if Config.CELERY_REVOKE_ON_STOP:
                celery_app.control.revoke(
                    task.celery_task_id, terminate=True, signal="SIGTERM"
                )
        session.delete(task)
    flash("Node deleted.", "success")
    return redirect(next_url)


@bp.get("/nodes/new", endpoint="new_node")
def new_node():
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    scripts = _load_scripts()
    scripts_by_type = _group_scripts_by_type(scripts)
    selected_scripts_by_type = {script_type: [] for script_type in SCRIPT_TYPE_FIELDS}
    integration_options = _build_node_integration_options()
    default_selected_integration_keys = [
        str(option["key"])
        for option in integration_options
        if bool(option.get("connected"))
    ]
    return render_template(
        "new_task.html",
        agents=agents,
        scripts_by_type=scripts_by_type,
        selected_scripts_by_type=selected_scripts_by_type,
        script_type_fields=SCRIPT_TYPE_FIELDS,
        script_type_choices=SCRIPT_TYPE_WRITE_CHOICES,
        integration_options=integration_options,
        selected_integration_keys=default_selected_integration_keys,
        summary=summary,
        page_title="New Node",
        active_page="nodes",
    )


@bp.post("/nodes/new", endpoint="create_node")
def create_node():
    agent_id_raw = request.form.get("agent_id", "").strip()
    prompt = request.form.get("prompt", "").strip()
    uploads = request.files.getlist("attachments")
    script_ids_by_type, legacy_ids, script_error = _parse_script_selection()
    selected_integration_keys, integration_error = _parse_node_integration_selection()
    if not agent_id_raw:
        flash("Select an agent.", "error")
        return redirect(url_for("agents.new_node"))
    try:
        agent_id = int(agent_id_raw)
    except ValueError:
        flash("Select a valid agent.", "error")
        return redirect(url_for("agents.new_node"))
    if not prompt:
        flash("Prompt is required.", "error")
        return redirect(url_for("agents.new_node"))
    if script_error:
        flash(script_error, "error")
        return redirect(url_for("agents.new_node"))
    if integration_error:
        flash(integration_error, "error")
        return redirect(url_for("agents.new_node"))

    try:
        with session_scope() as session:
            agent = session.get(Agent, agent_id)
            if agent is None:
                flash("Agent not found.", "error")
                return redirect(url_for("agents.new_node"))
            script_ids_by_type, script_error = _resolve_script_selection(
                session,
                script_ids_by_type,
                legacy_ids,
            )
            if script_error:
                flash(script_error, "error")
                return redirect(url_for("agents.new_node"))
            task = AgentTask.create(
                session,
                agent_id=agent_id,
                status="queued",
                prompt=prompt,
                integration_keys_json=serialize_task_integration_keys(
                    selected_integration_keys
                ),
            )
            _set_task_scripts(session, task.id, script_ids_by_type)
            attachments = _save_uploaded_attachments(session, uploads)
            _attach_attachments(task, attachments)
            task_id = task.id
    except (OSError, ValueError) as exc:
        logger.exception("Failed to save task attachments")
        flash(str(exc) or "Failed to save attachments.", "error")
        return redirect(url_for("agents.new_node"))

    celery_task = run_agent_task.delay(task_id)

    with session_scope() as session:
        task = session.get(AgentTask, task_id)
        if task is not None:
            task.celery_task_id = celery_task.id

    flash(f"Node {task_id} queued.", "success")
    return redirect(url_for("agents.list_nodes"))


@bp.get("/plans")
def list_plans():
    page = _parse_page(request.args.get("page"))
    per_page = WORKFLOW_LIST_PER_PAGE
    with session_scope() as session:
        total_count = session.execute(select(func.count(Plan.id))).scalar_one()
        pagination = _build_pagination(request.path, page, per_page, total_count)
        offset = (pagination["page"] - 1) * per_page
        rows = session.execute(
            select(
                Plan,
                func.count(func.distinct(PlanStage.id)),
                func.count(PlanTask.id),
            )
            .outerjoin(PlanStage, PlanStage.plan_id == Plan.id)
            .outerjoin(PlanTask, PlanTask.plan_stage_id == PlanStage.id)
            .group_by(Plan.id)
            .order_by(Plan.created_at.desc())
            .limit(per_page)
            .offset(offset)
        ).all()
    plans = [
        {
            "plan": plan,
            "stage_count": int(stage_count or 0),
            "task_count": int(task_count or 0),
        }
        for plan, stage_count, task_count in rows
    ]
    return render_template(
        "plans.html",
        plans=plans,
        pagination=pagination,
        human_time=_human_time,
        fixed_list_page=True,
        page_title="Plans",
        active_page="plans",
    )


@bp.get("/plans/new")
def new_plan():
    flash("Create plans by adding Plan nodes in a flowchart.", "error")
    return redirect(url_for("agents.list_flowcharts"))


@bp.post("/plans")
def create_plan():
    flash("Create plans by adding Plan nodes in a flowchart.", "error")
    return redirect(url_for("agents.list_flowcharts"))


@bp.get("/plans/<int:plan_id>")
def view_plan(plan_id: int):
    with session_scope() as session:
        plan = (
            session.execute(
                select(Plan)
                .options(selectinload(Plan.stages).selectinload(PlanStage.tasks))
                .where(Plan.id == plan_id)
            )
            .scalars()
            .first()
        )
        if plan is None:
            abort(404)
    stage_count = len(plan.stages)
    task_count = sum(len(stage.tasks) for stage in plan.stages)
    return render_template(
        "plan_detail.html",
        plan=plan,
        stage_count=stage_count,
        task_count=task_count,
        human_time=_human_time,
        page_title=f"Plan - {plan.name}",
        active_page="plans",
    )


@bp.get("/plans/<int:plan_id>/edit")
def edit_plan(plan_id: int):
    with session_scope() as session:
        plan = session.get(Plan, plan_id)
        if plan is None:
            abort(404)
    return render_template(
        "plan_edit.html",
        plan=plan,
        page_title="Edit Plan",
        active_page="plans",
    )


@bp.post("/plans/<int:plan_id>")
def update_plan(plan_id: int):
    name = request.form.get("name", "").strip()
    if not name:
        flash("Plan name is required.", "error")
        return redirect(url_for("agents.edit_plan", plan_id=plan_id))
    description = request.form.get("description", "").strip() or None
    completed_at_raw = request.form.get("completed_at", "").strip()
    completed_at = _parse_completed_at(completed_at_raw)
    if completed_at_raw and completed_at is None:
        flash("Completed at must be a valid date/time.", "error")
        return redirect(url_for("agents.edit_plan", plan_id=plan_id))

    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.view_plan", plan_id=plan_id)
    )
    with session_scope() as session:
        plan = session.get(Plan, plan_id)
        if plan is None:
            abort(404)
        plan.name = name
        plan.description = description
        plan.completed_at = completed_at

    flash("Plan updated.", "success")
    return redirect(redirect_target)


@bp.post("/plans/<int:plan_id>/delete")
def delete_plan(plan_id: int):
    next_url = _safe_redirect_target(request.form.get("next"), url_for("agents.list_plans"))
    with session_scope() as session:
        plan = session.get(Plan, plan_id)
        if plan is None:
            abort(404)
        stage_ids = (
            session.execute(select(PlanStage.id).where(PlanStage.plan_id == plan_id))
            .scalars()
            .all()
        )
        if stage_ids:
            session.execute(
                delete(PlanTask).where(PlanTask.plan_stage_id.in_(stage_ids))
            )
        session.execute(delete(PlanStage).where(PlanStage.plan_id == plan_id))
        session.delete(plan)
    flash("Plan deleted.", "success")
    return redirect(next_url)


@bp.post("/plans/<int:plan_id>/stages")
def create_plan_stage(plan_id: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.view_plan", plan_id=plan_id)
    )
    name = request.form.get("name", "").strip()
    if not name:
        flash("Stage name is required.", "error")
        return redirect(redirect_target)
    description = request.form.get("description", "").strip() or None
    completed_at_raw = request.form.get("completed_at", "").strip()
    completed_at = _parse_completed_at(completed_at_raw)
    if completed_at_raw and completed_at is None:
        flash("Stage completed at must be a valid date/time.", "error")
        return redirect(redirect_target)

    with session_scope() as session:
        plan = session.get(Plan, plan_id)
        if plan is None:
            abort(404)
        max_position = session.execute(
            select(func.max(PlanStage.position)).where(PlanStage.plan_id == plan_id)
        ).scalar_one()
        PlanStage.create(
            session,
            plan_id=plan_id,
            name=name,
            description=description,
            position=(max_position or 0) + 1,
            completed_at=completed_at,
        )

    flash("Plan stage added.", "success")
    return redirect(redirect_target)


@bp.post("/plans/<int:plan_id>/stages/<int:stage_id>")
def update_plan_stage(plan_id: int, stage_id: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.view_plan", plan_id=plan_id)
    )
    name = request.form.get("name", "").strip()
    if not name:
        flash("Stage name is required.", "error")
        return redirect(redirect_target)
    description = request.form.get("description", "").strip() or None
    completed_at_raw = request.form.get("completed_at", "").strip()
    completed_at = _parse_completed_at(completed_at_raw)
    if completed_at_raw and completed_at is None:
        flash("Stage completed at must be a valid date/time.", "error")
        return redirect(redirect_target)

    with session_scope() as session:
        stage = session.get(PlanStage, stage_id)
        if stage is None or stage.plan_id != plan_id:
            abort(404)
        stage.name = name
        stage.description = description
        stage.completed_at = completed_at

    flash("Plan stage updated.", "success")
    return redirect(redirect_target)


@bp.post("/plans/<int:plan_id>/stages/<int:stage_id>/delete")
def delete_plan_stage(plan_id: int, stage_id: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.view_plan", plan_id=plan_id)
    )
    with session_scope() as session:
        stage = session.get(PlanStage, stage_id)
        if stage is None or stage.plan_id != plan_id:
            abort(404)
        session.execute(delete(PlanTask).where(PlanTask.plan_stage_id == stage_id))
        session.delete(stage)
    flash("Plan stage deleted.", "success")
    return redirect(redirect_target)


@bp.post("/plans/<int:plan_id>/stages/<int:stage_id>/tasks")
def create_plan_task(plan_id: int, stage_id: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.view_plan", plan_id=plan_id)
    )
    name = request.form.get("name", "").strip()
    if not name:
        flash("Task name is required.", "error")
        return redirect(redirect_target)
    description = request.form.get("description", "").strip() or None
    completed_at_raw = request.form.get("completed_at", "").strip()
    completed_at = _parse_completed_at(completed_at_raw)
    if completed_at_raw and completed_at is None:
        flash("Task completed at must be a valid date/time.", "error")
        return redirect(redirect_target)

    with session_scope() as session:
        stage = session.get(PlanStage, stage_id)
        if stage is None or stage.plan_id != plan_id:
            abort(404)
        max_position = session.execute(
            select(func.max(PlanTask.position)).where(PlanTask.plan_stage_id == stage_id)
        ).scalar_one()
        PlanTask.create(
            session,
            plan_stage_id=stage_id,
            name=name,
            description=description,
            position=(max_position or 0) + 1,
            completed_at=completed_at,
        )

    flash("Plan task added.", "success")
    return redirect(redirect_target)


@bp.post("/plans/<int:plan_id>/stages/<int:stage_id>/tasks/<int:task_id>")
def update_plan_task(plan_id: int, stage_id: int, task_id: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.view_plan", plan_id=plan_id)
    )
    name = request.form.get("name", "").strip()
    if not name:
        flash("Task name is required.", "error")
        return redirect(redirect_target)
    description = request.form.get("description", "").strip() or None
    completed_at_raw = request.form.get("completed_at", "").strip()
    completed_at = _parse_completed_at(completed_at_raw)
    if completed_at_raw and completed_at is None:
        flash("Task completed at must be a valid date/time.", "error")
        return redirect(redirect_target)

    with session_scope() as session:
        stage = session.get(PlanStage, stage_id)
        task = session.get(PlanTask, task_id)
        if (
            stage is None
            or stage.plan_id != plan_id
            or task is None
            or task.plan_stage_id != stage_id
        ):
            abort(404)
        task.name = name
        task.description = description
        task.completed_at = completed_at

    flash("Plan task updated.", "success")
    return redirect(redirect_target)


@bp.post("/plans/<int:plan_id>/stages/<int:stage_id>/tasks/<int:task_id>/delete")
def delete_plan_task(plan_id: int, stage_id: int, task_id: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.view_plan", plan_id=plan_id)
    )
    with session_scope() as session:
        stage = session.get(PlanStage, stage_id)
        task = session.get(PlanTask, task_id)
        if (
            stage is None
            or stage.plan_id != plan_id
            or task is None
            or task.plan_stage_id != stage_id
        ):
            abort(404)
        session.delete(task)
    flash("Plan task deleted.", "success")
    return redirect(redirect_target)


def _read_milestone_form() -> tuple[dict[str, object] | None, str | None]:
    name = request.form.get("name", "").strip()
    if not name:
        return None, "Name is required."

    status = _normalize_milestone_choice(
        request.form.get("status"),
        choices=MILESTONE_STATUS_CHOICES,
        fallback=MILESTONE_STATUS_PLANNED,
    )
    priority = _normalize_milestone_choice(
        request.form.get("priority"),
        choices=MILESTONE_PRIORITY_CHOICES,
        fallback=MILESTONE_PRIORITY_MEDIUM,
    )
    health = _normalize_milestone_choice(
        request.form.get("health"),
        choices=MILESTONE_HEALTH_CHOICES,
        fallback=MILESTONE_HEALTH_GREEN,
    )

    start_date_raw = request.form.get("start_date", "").strip()
    start_date = _parse_milestone_due_date(start_date_raw)
    if start_date_raw and start_date is None:
        return None, "Start date must be a valid date."

    due_date_raw = request.form.get("due_date", "").strip()
    due_date = _parse_milestone_due_date(due_date_raw)
    if due_date_raw and due_date is None:
        return None, "Due date must be a valid date."
    if start_date and due_date and due_date < start_date:
        return None, "Due date must be on or after the start date."

    progress = _parse_milestone_progress(request.form.get("progress_percent"))
    if progress is None:
        return None, "Progress must be a whole number between 0 and 100."

    payload: dict[str, object] = {
        "name": name,
        "description": request.form.get("description", "").strip() or None,
        "status": status,
        "priority": priority,
        "owner": request.form.get("owner", "").strip() or None,
        "start_date": start_date,
        "due_date": due_date,
        "progress_percent": progress,
        "health": health,
        "success_criteria": request.form.get("success_criteria", "").strip() or None,
        "dependencies": request.form.get("dependencies", "").strip() or None,
        "links": request.form.get("links", "").strip() or None,
        "latest_update": request.form.get("latest_update", "").strip() or None,
    }
    completed = status == MILESTONE_STATUS_DONE
    payload["completed"] = completed
    if completed:
        payload["progress_percent"] = max(progress, 100)
    return payload, None


@bp.get("/milestones")
def list_milestones():
    page = _parse_page(request.args.get("page"))
    per_page = WORKFLOW_LIST_PER_PAGE
    with session_scope() as session:
        total_count = session.execute(select(func.count(Milestone.id))).scalar_one()
        pagination = _build_pagination(request.path, page, per_page, total_count)
        offset = (pagination["page"] - 1) * per_page
        milestones = (
            session.execute(
                select(Milestone)
                .order_by(
                    Milestone.completed.asc(),
                    Milestone.due_date.is_(None),
                    Milestone.due_date.asc(),
                    Milestone.created_at.desc(),
                )
                .limit(per_page)
                .offset(offset)
            )
            .scalars()
            .all()
        )
    return render_template(
        "milestones.html",
        milestones=milestones,
        pagination=pagination,
        human_time=_human_time,
        **_milestone_template_context(),
        fixed_list_page=True,
        page_title="Milestones",
        active_page="milestones",
    )


@bp.get("/milestones/new")
def new_milestone():
    flash("Create milestones by adding Milestone nodes in a flowchart.", "error")
    return redirect(url_for("agents.list_flowcharts"))


@bp.post("/milestones")
def create_milestone():
    flash("Create milestones by adding Milestone nodes in a flowchart.", "error")
    return redirect(url_for("agents.list_flowcharts"))


@bp.get("/milestones/<int:milestone_id>")
def view_milestone(milestone_id: int):
    with session_scope() as session:
        milestone = session.get(Milestone, milestone_id)
        if milestone is None:
            abort(404)
    return render_template(
        "milestone_detail.html",
        milestone=milestone,
        human_time=_human_time,
        **_milestone_template_context(),
        page_title=f"Milestone - {milestone.name}",
        active_page="milestones",
    )


@bp.get("/milestones/<int:milestone_id>/edit")
def edit_milestone(milestone_id: int):
    with session_scope() as session:
        milestone = session.get(Milestone, milestone_id)
        if milestone is None:
            abort(404)
    return render_template(
        "milestone_edit.html",
        milestone=milestone,
        **_milestone_template_context(),
        page_title=f"Edit Milestone - {milestone.name}",
        active_page="milestones",
    )


@bp.post("/milestones/<int:milestone_id>")
def update_milestone(milestone_id: int):
    payload, error = _read_milestone_form()
    if error or payload is None:
        flash(error or "Invalid milestone payload.", "error")
        return redirect(url_for("agents.edit_milestone", milestone_id=milestone_id))
    with session_scope() as session:
        milestone = session.get(Milestone, milestone_id)
        if milestone is None:
            abort(404)
        for field, value in payload.items():
            setattr(milestone, field, value)
    flash("Milestone updated.", "success")
    return redirect(url_for("agents.view_milestone", milestone_id=milestone_id))


@bp.post("/milestones/<int:milestone_id>/delete")
def delete_milestone(milestone_id: int):
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_milestones")
    )
    with session_scope() as session:
        milestone = session.get(Milestone, milestone_id)
        if milestone is None:
            abort(404)
        session.delete(milestone)
    flash("Milestone deleted.", "success")
    return redirect(next_url)


@bp.get("/task-templates")
def list_task_templates():
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    page = _parse_page(request.args.get("page"))
    per_page = WORKFLOW_LIST_PER_PAGE
    with session_scope() as session:
        total_count = session.execute(
            select(func.count(FlowchartNode.id)).where(
                FlowchartNode.node_type.in_(
                    [FLOWCHART_NODE_TYPE_TASK, FLOWCHART_NODE_TYPE_RAG]
                )
            )
        ).scalar_one()
        pagination = _build_pagination(request.path, page, per_page, total_count)
        offset = (pagination["page"] - 1) * per_page
        task_rows = (
            session.execute(
                select(FlowchartNode, Flowchart)
                .join(Flowchart, Flowchart.id == FlowchartNode.flowchart_id)
                .where(
                    FlowchartNode.node_type.in_(
                        [FLOWCHART_NODE_TYPE_TASK, FLOWCHART_NODE_TYPE_RAG]
                    )
                )
                .order_by(FlowchartNode.updated_at.desc(), FlowchartNode.id.desc())
                .limit(per_page)
                .offset(offset)
            )
            .all()
        )
        template_name_by_id: dict[int, str] = {}
        template_ids = {
            int(node.ref_id)
            for node, _flowchart in task_rows
            if node.ref_id is not None and int(node.ref_id) > 0
        }
        if template_ids:
            template_name_by_id = {
                int(row[0]): str(row[1])
                for row in session.execute(
                    select(TaskTemplate.id, TaskTemplate.name).where(
                        TaskTemplate.id.in_(template_ids)
                    )
                ).all()
            }

    task_nodes: list[dict[str, object]] = []
    for node, flowchart in task_rows:
        config = _parse_json_dict(node.config_json)
        task_name = str(node.title or "").strip()
        prompt_text = ""
        if node.node_type == FLOWCHART_NODE_TYPE_RAG:
            if not task_name:
                task_name = f"RAG node {node.id}"
            rag_mode = str(config.get("mode") or "query").strip().lower() or "query"
            if rag_mode == RAG_NODE_MODE_QUERY:
                prompt_text = str(config.get("question_prompt") or "").strip()
            if not prompt_text:
                selected_collections = rag_normalize_collection_selection(
                    config.get("collections")
                )
                if selected_collections:
                    prompt_text = (
                        f"mode={rag_mode} | collections="
                        + ", ".join(selected_collections)
                    )
                else:
                    prompt_text = f"mode={rag_mode}"
        else:
            inline_name = config.get("task_name")
            inline_prompt = config.get("task_prompt")
            if not task_name:
                task_name = str(inline_name).strip() if isinstance(inline_name, str) else ""
            if not task_name and node.ref_id is not None:
                task_name = template_name_by_id.get(int(node.ref_id), "")
            if not task_name:
                task_name = f"Task node {node.id}"

            prompt_text = str(inline_prompt).strip() if isinstance(inline_prompt, str) else ""
            if not prompt_text and node.ref_id is not None:
                legacy_name = template_name_by_id.get(int(node.ref_id), "")
                if legacy_name:
                    prompt_text = f"Legacy template reference: {legacy_name}"
                else:
                    prompt_text = "Legacy template reference."
        prompt_preview = " ".join(prompt_text.split())
        if len(prompt_preview) > 180:
            prompt_preview = f"{prompt_preview[:177]}..."
        task_nodes.append(
            {
                "node_id": node.id,
                "task_name": task_name,
                "prompt_preview": prompt_preview or "-",
                "node_type": str(node.node_type or "").strip().lower(),
                "flowchart_id": flowchart.id,
                "flowchart_name": flowchart.name,
            }
        )

    return render_template(
        "task_templates.html",
        task_nodes=task_nodes,
        pagination=pagination,
        summary=summary,
        human_time=_human_time,
        fixed_list_page=True,
        page_title="Workflow Nodes",
        active_page="templates",
    )


@bp.get("/task-templates/new")
def new_task_template():
    flash("Create tasks by adding Task nodes in a flowchart.", "error")
    return redirect(url_for("agents.list_flowcharts"))


@bp.get("/task-templates/<int:template_id>")
def view_task_template(template_id: int):
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    agents_by_id = {agent.id: agent.name for agent in agents}
    with session_scope() as session:
        template = (
            session.execute(
                select(TaskTemplate)
                .options(selectinload(TaskTemplate.attachments))
                .where(TaskTemplate.id == template_id)
            )
            .scalars()
            .first()
        )
        if template is None:
            abort(404)
        task_count = session.execute(
            select(func.count(AgentTask.id)).where(
                AgentTask.task_template_id == template_id
            )
        ).scalar_one()
    return render_template(
        "task_template_detail.html",
        template=template,
        agents_by_id=agents_by_id,
        task_count=task_count,
        summary=summary,
        human_time=_human_time,
        page_title=f"Task - {template.name}",
        active_page="templates",
    )


@bp.get("/task-templates/<int:template_id>/edit")
def edit_task_template(template_id: int):
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    with session_scope() as session:
        template = (
            session.execute(
                select(TaskTemplate)
                .options(selectinload(TaskTemplate.attachments))
                .where(TaskTemplate.id == template_id)
            )
            .scalars()
            .first()
        )
        if template is None:
            abort(404)
    return render_template(
        "task_template_edit.html",
        template=template,
        agents=agents,
        summary=summary,
        page_title=f"Edit Task - {template.name}",
        active_page="templates",
    )


@bp.get("/flowcharts")
def list_flowcharts():
    with session_scope() as session:
        rows = session.execute(
            select(
                Flowchart,
                func.count(func.distinct(FlowchartNode.id)),
                func.count(func.distinct(FlowchartEdge.id)),
                func.count(func.distinct(FlowchartRun.id)),
            )
            .outerjoin(FlowchartNode, FlowchartNode.flowchart_id == Flowchart.id)
            .outerjoin(FlowchartEdge, FlowchartEdge.flowchart_id == Flowchart.id)
            .outerjoin(FlowchartRun, FlowchartRun.flowchart_id == Flowchart.id)
            .group_by(Flowchart.id)
            .order_by(Flowchart.created_at.desc())
        ).all()
    flowcharts = [
        {
            **_serialize_flowchart(flowchart),
            "node_count": int(node_count or 0),
            "edge_count": int(edge_count or 0),
            "run_count": int(run_count or 0),
        }
        for flowchart, node_count, edge_count, run_count in rows
    ]
    if _flowchart_wants_json():
        return {"flowcharts": flowcharts}
    return render_template(
        "flowcharts.html",
        flowcharts=flowcharts,
        page_title="Flowcharts",
        active_page="flowcharts",
    )


@bp.get("/flowcharts/new")
def new_flowchart():
    with session_scope() as session:
        catalog = _flowchart_catalog(session)
    defaults = {
        "max_node_executions": None,
        "max_runtime_minutes": None,
        "max_parallel_nodes": 1,
        "node_types": list(FLOWCHART_NODE_TYPE_CHOICES),
    }
    if _flowchart_wants_json():
        return {"defaults": defaults, "catalog": catalog}
    return render_template(
        "flowchart_new.html",
        defaults=defaults,
        catalog=catalog,
        page_title="Create Flowchart",
        active_page="flowcharts",
    )


@bp.post("/flowcharts")
def create_flowchart():
    payload = _flowchart_request_payload()
    is_api_request = request.is_json or bool(payload) or _flowchart_wants_json()
    name = str((payload.get("name") if payload else request.form.get("name")) or "").strip()
    description = str(
        (payload.get("description") if payload else request.form.get("description")) or ""
    ).strip()
    max_node_executions_raw = (
        payload.get("max_node_executions")
        if payload
        else request.form.get("max_node_executions")
    )
    max_runtime_minutes_raw = (
        payload.get("max_runtime_minutes")
        if payload
        else request.form.get("max_runtime_minutes")
    )
    max_parallel_nodes_raw = (
        payload.get("max_parallel_nodes")
        if payload
        else request.form.get("max_parallel_nodes")
    )
    if not name:
        if is_api_request:
            return {"error": "Flowchart name is required."}, 400
        flash("Flowchart name is required.", "error")
        return redirect(url_for("agents.new_flowchart"))
    try:
        max_node_executions = _coerce_optional_int(
            max_node_executions_raw,
            field_name="max_node_executions",
            minimum=1,
        )
        max_runtime_minutes = _coerce_optional_int(
            max_runtime_minutes_raw,
            field_name="max_runtime_minutes",
            minimum=1,
        )
        max_parallel_nodes = _coerce_optional_int(
            max_parallel_nodes_raw,
            field_name="max_parallel_nodes",
            minimum=1,
        )
    except ValueError as exc:
        if is_api_request:
            return {"error": str(exc)}, 400
        flash(str(exc), "error")
        return redirect(url_for("agents.new_flowchart"))
    if max_parallel_nodes is None:
        max_parallel_nodes = 1

    with session_scope() as session:
        flowchart = Flowchart.create(
            session,
            name=name,
            description=description or None,
            max_node_executions=max_node_executions,
            max_runtime_minutes=max_runtime_minutes,
            max_parallel_nodes=max_parallel_nodes,
        )
        _ensure_flowchart_start_node(session, flowchart_id=flowchart.id)
    flowchart_payload = _serialize_flowchart(flowchart)
    if is_api_request:
        return {"flowchart": flowchart_payload}, 201
    flash("Flowchart created.", "success")
    return redirect(url_for("agents.view_flowchart", flowchart_id=int(flowchart_payload["id"])))


@bp.get("/flowcharts/<int:flowchart_id>")
def view_flowchart(flowchart_id: int):
    wants_json = _flowchart_wants_json()
    selected_node_raw = (request.args.get("node") or "").strip()
    selected_node_id: int | None = None
    active_run_id: int | None = None
    if selected_node_raw:
        try:
            parsed_selected_node_id = int(selected_node_raw)
        except ValueError:
            parsed_selected_node_id = 0
        if parsed_selected_node_id > 0:
            selected_node_id = parsed_selected_node_id
    with session_scope() as session:
        existing_flowchart = session.get(Flowchart, flowchart_id)
        if existing_flowchart is None:
            abort(404)
        _ensure_flowchart_start_node(session, flowchart_id=flowchart_id)
        flowchart = (
            session.execute(
                select(Flowchart)
                .options(
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.mcp_servers),
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.scripts),
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.skills),
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.attachments),
                    selectinload(Flowchart.edges),
                )
                .where(Flowchart.id == flowchart_id)
            )
            .scalars()
            .first()
        )
        runs: list[FlowchartRun] = []
        if wants_json:
            runs = (
                session.execute(
                    select(FlowchartRun)
                    .where(FlowchartRun.flowchart_id == flowchart_id)
                    .order_by(FlowchartRun.created_at.desc())
                    .limit(25)
                )
                .scalars()
                .all()
            )
        catalog = _flowchart_catalog(session)
        validation_errors = _validate_flowchart_graph(flowchart.nodes, flowchart.edges)
        for node in flowchart.nodes:
            if (
                node.node_type in FLOWCHART_NODE_TYPE_WITH_REF
                and node.ref_id is not None
                and not _flowchart_ref_exists(
                    session,
                    node_type=node.node_type,
                    ref_id=node.ref_id,
                )
            ):
                validation_errors.append(
                    f"Node {node.id} ({node.node_type}) ref_id {node.ref_id} does not exist."
                )
        if selected_node_id is not None and all(
            node.id != selected_node_id for node in flowchart.nodes
        ):
            selected_node_id = None
        active_run_id = (
            session.execute(
                select(FlowchartRun.id)
                .where(
                    FlowchartRun.flowchart_id == flowchart_id,
                    FlowchartRun.status.in_(["queued", "running", "stopping"]),
                )
                .order_by(FlowchartRun.created_at.desc(), FlowchartRun.id.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
    flowchart_payload = _serialize_flowchart(flowchart)
    graph_payload = {
        "nodes": [_serialize_flowchart_node(node) for node in flowchart.nodes],
        "edges": [_serialize_flowchart_edge(edge) for edge in flowchart.edges],
    }
    runs_payload = [_serialize_flowchart_run(run) for run in runs]
    validation_payload = {
        "valid": len(validation_errors) == 0,
        "errors": validation_errors,
    }
    if wants_json:
        return {
            "flowchart": flowchart_payload,
            "graph": graph_payload,
            "runs": runs_payload,
            "validation": validation_payload,
        }
    return render_template(
        "flowchart_detail.html",
        flowchart=flowchart_payload,
        graph=graph_payload,
        validation=validation_payload,
        catalog=catalog,
        node_types=list(FLOWCHART_NODE_TYPE_CHOICES),
        rag_palette_state=str(
            ((catalog.get("rag_health") or {}).get("state"))
            or RAG_DOMAIN_HEALTH_UNCONFIGURED
        ),
        selected_node_id=selected_node_id,
        active_run_id=active_run_id,
        page_title=f"Flowchart - {flowchart_payload['name']}",
        active_page="flowcharts",
    )


@bp.get("/flowcharts/<int:flowchart_id>/history")
def view_flowchart_history(flowchart_id: int):
    with session_scope() as session:
        flowchart = session.get(Flowchart, flowchart_id)
        if flowchart is None:
            abort(404)
        start_node_id = (
            session.execute(
                select(FlowchartNode.id)
                .where(
                    FlowchartNode.flowchart_id == flowchart_id,
                    FlowchartNode.node_type == FLOWCHART_NODE_TYPE_START,
                )
                .order_by(FlowchartNode.id.asc())
            )
            .scalars()
            .first()
        )
        run_rows = (
            session.execute(
                select(FlowchartRun, func.count(FlowchartRunNode.id))
                .outerjoin(
                    FlowchartRunNode,
                    FlowchartRunNode.flowchart_run_id == FlowchartRun.id,
                )
                .where(FlowchartRun.flowchart_id == flowchart_id)
                .group_by(FlowchartRun.id)
                .order_by(FlowchartRun.created_at.desc())
            )
            .all()
        )

        run_ids = [run.id for run, _ in run_rows]
        start_counts: dict[int, int] = {}
        if start_node_id is not None and run_ids:
            start_count_rows = (
                session.execute(
                    select(
                        FlowchartRunNode.flowchart_run_id,
                        func.count(FlowchartRunNode.id),
                    )
                    .where(
                        FlowchartRunNode.flowchart_run_id.in_(run_ids),
                        FlowchartRunNode.flowchart_node_id == start_node_id,
                    )
                    .group_by(FlowchartRunNode.flowchart_run_id)
                )
                .all()
            )
            start_counts = {
                int(run_id): int(count or 0) for run_id, count in start_count_rows
            }

    flowchart_payload = _serialize_flowchart(flowchart)
    runs_payload: list[dict[str, object]] = []
    for run, node_run_count in run_rows:
        node_count = int(node_run_count or 0)
        cycle_count = start_counts.get(run.id, 1 if node_count > 0 else 0)
        runs_payload.append(
            {
                **_serialize_flowchart_run(run),
                "node_run_count": node_count,
                "cycle_count": int(cycle_count),
            }
        )

    if _flowchart_wants_json():
        return {
            "flowchart": flowchart_payload,
            "runs": runs_payload,
        }
    return render_template(
        "flowchart_history.html",
        flowchart=flowchart_payload,
        runs=runs_payload,
        status_class=_flowchart_status_class,
        page_title=f"Flowchart History - {flowchart_payload['name']}",
        active_page="flowcharts",
    )


@bp.get("/flowcharts/<int:flowchart_id>/history/<int:run_id>")
def view_flowchart_history_run(flowchart_id: int, run_id: int):
    with session_scope() as session:
        flowchart = session.get(Flowchart, flowchart_id)
        if flowchart is None:
            abort(404)
        flowchart_run = session.get(FlowchartRun, run_id)
        if flowchart_run is None or flowchart_run.flowchart_id != flowchart_id:
            abort(404)
        _backfill_flowchart_node_activity_tasks(
            session,
            flowchart_id=flowchart_id,
            run_id=run_id,
        )

        start_node_id = (
            session.execute(
                select(FlowchartNode.id)
                .where(
                    FlowchartNode.flowchart_id == flowchart_id,
                    FlowchartNode.node_type == FLOWCHART_NODE_TYPE_START,
                )
                .order_by(FlowchartNode.id.asc())
            )
            .scalars()
            .first()
        )

        node_run_rows = (
            session.execute(
                select(FlowchartRunNode, FlowchartNode)
                .join(FlowchartNode, FlowchartNode.id == FlowchartRunNode.flowchart_node_id)
                .where(FlowchartRunNode.flowchart_run_id == run_id)
                .order_by(FlowchartRunNode.created_at.asc(), FlowchartRunNode.id.asc())
            )
            .all()
        )
        node_task_ids = sorted(
            {
                int(node_run.agent_task_id)
                for node_run, _node in node_run_rows
                if node_run.agent_task_id is not None
            }
        )
        node_task_map: dict[int, AgentTask] = {}
        if node_task_ids:
            tasks = (
                session.execute(
                    select(AgentTask).where(AgentTask.id.in_(node_task_ids))
                )
                .scalars()
                .all()
            )
            node_task_map = {int(task.id): task for task in tasks}

    flowchart_payload = _serialize_flowchart(flowchart)
    run_payload = _serialize_flowchart_run(flowchart_run)

    node_runs_payload: list[dict[str, object]] = []
    cycle_index = 0
    for node_run, node in node_run_rows:
        if start_node_id is not None and node_run.flowchart_node_id == start_node_id:
            cycle_index += 1
        if cycle_index == 0:
            cycle_index = 1
        node_runs_payload.append(
            {
                **_serialize_flowchart_run_node(
                    node_run,
                    node_task_map.get(int(node_run.agent_task_id or 0)),
                ),
                "node_title": node.title or f"{node.node_type} node",
                "node_type": node.node_type,
                "cycle_index": cycle_index,
            }
        )
    cycle_count = cycle_index if cycle_index > 0 else (1 if node_runs_payload else 0)
    run_payload["node_run_count"] = len(node_runs_payload)
    run_payload["cycle_count"] = int(cycle_count)

    if _flowchart_wants_json():
        return {
            "flowchart": flowchart_payload,
            "flowchart_run": run_payload,
            "node_runs": node_runs_payload,
        }
    return render_template(
        "flowchart_history_run_detail.html",
        flowchart=flowchart_payload,
        flowchart_run=run_payload,
        node_runs=node_runs_payload,
        status_class=_flowchart_status_class,
        page_title=f"Flowchart Run {run_id} - {flowchart_payload['name']}",
        active_page="flowcharts",
    )


@bp.get("/flowcharts/<int:flowchart_id>/edit")
def edit_flowchart(flowchart_id: int):
    with session_scope() as session:
        flowchart = session.get(Flowchart, flowchart_id)
        if flowchart is None:
            abort(404)
        catalog = _flowchart_catalog(session)
    flowchart_payload = _serialize_flowchart(flowchart)
    if _flowchart_wants_json():
        return {
            "flowchart": flowchart_payload,
            "catalog": catalog,
        }
    return render_template(
        "flowchart_edit.html",
        flowchart=flowchart_payload,
        catalog=catalog,
        page_title="Edit Flowchart",
        active_page="flowcharts",
    )


@bp.post("/flowcharts/<int:flowchart_id>")
def update_flowchart(flowchart_id: int):
    payload = _flowchart_request_payload()
    is_api_request = request.is_json or bool(payload) or _flowchart_wants_json()
    name = str((payload.get("name") if payload else request.form.get("name")) or "").strip()
    description = str(
        (payload.get("description") if payload else request.form.get("description")) or ""
    ).strip()
    max_node_executions_raw = (
        payload.get("max_node_executions")
        if payload
        else request.form.get("max_node_executions")
    )
    max_runtime_minutes_raw = (
        payload.get("max_runtime_minutes")
        if payload
        else request.form.get("max_runtime_minutes")
    )
    max_parallel_nodes_raw = (
        payload.get("max_parallel_nodes")
        if payload
        else request.form.get("max_parallel_nodes")
    )
    if not name:
        if is_api_request:
            return {"error": "Flowchart name is required."}, 400
        flash("Flowchart name is required.", "error")
        return redirect(url_for("agents.edit_flowchart", flowchart_id=flowchart_id))
    try:
        max_node_executions = _coerce_optional_int(
            max_node_executions_raw,
            field_name="max_node_executions",
            minimum=1,
        )
        max_runtime_minutes = _coerce_optional_int(
            max_runtime_minutes_raw,
            field_name="max_runtime_minutes",
            minimum=1,
        )
        max_parallel_nodes = _coerce_optional_int(
            max_parallel_nodes_raw,
            field_name="max_parallel_nodes",
            minimum=1,
        )
    except ValueError as exc:
        if is_api_request:
            return {"error": str(exc)}, 400
        flash(str(exc), "error")
        return redirect(url_for("agents.edit_flowchart", flowchart_id=flowchart_id))
    if max_parallel_nodes is None:
        max_parallel_nodes = 1

    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.view_flowchart", flowchart_id=flowchart_id)
    )
    with session_scope() as session:
        flowchart = session.get(Flowchart, flowchart_id)
        if flowchart is None:
            abort(404)
        flowchart.name = name
        flowchart.description = description or None
        flowchart.max_node_executions = max_node_executions
        flowchart.max_runtime_minutes = max_runtime_minutes
        flowchart.max_parallel_nodes = max_parallel_nodes
    flowchart_payload = _serialize_flowchart(flowchart)
    if is_api_request:
        return {"flowchart": flowchart_payload}
    flash("Flowchart updated.", "success")
    return redirect(redirect_target)


@bp.post("/flowcharts/<int:flowchart_id>/delete")
def delete_flowchart(flowchart_id: int):
    is_api_request = request.is_json or _flowchart_wants_json()
    next_url = _safe_redirect_target(request.form.get("next"), url_for("agents.list_flowcharts"))
    with session_scope() as session:
        flowchart = session.get(Flowchart, flowchart_id)
        if flowchart is None:
            abort(404)

        node_ids = (
            session.execute(
                select(FlowchartNode.id).where(FlowchartNode.flowchart_id == flowchart_id)
            )
            .scalars()
            .all()
        )
        run_ids = (
            session.execute(
                select(FlowchartRun.id).where(FlowchartRun.flowchart_id == flowchart_id)
            )
            .scalars()
            .all()
        )

        task_ids = set(
            session.execute(
                select(AgentTask.id).where(AgentTask.flowchart_id == flowchart_id)
            )
            .scalars()
            .all()
        )
        if run_ids:
            task_ids.update(
                session.execute(
                    select(AgentTask.id).where(AgentTask.flowchart_run_id.in_(run_ids))
                )
                .scalars()
                .all()
            )
            session.execute(
                delete(FlowchartRunNode).where(FlowchartRunNode.flowchart_run_id.in_(run_ids))
            )
        if node_ids:
            task_ids.update(
                session.execute(
                    select(AgentTask.id).where(AgentTask.flowchart_node_id.in_(node_ids))
                )
                .scalars()
                .all()
            )
            session.execute(
                delete(flowchart_node_mcp_servers).where(
                    flowchart_node_mcp_servers.c.flowchart_node_id.in_(node_ids)
                )
            )
            session.execute(
                delete(flowchart_node_scripts).where(
                    flowchart_node_scripts.c.flowchart_node_id.in_(node_ids)
                )
            )
            session.execute(
                delete(flowchart_node_skills).where(
                    flowchart_node_skills.c.flowchart_node_id.in_(node_ids)
                )
            )
            session.execute(
                delete(flowchart_node_attachments).where(
                    flowchart_node_attachments.c.flowchart_node_id.in_(node_ids)
                )
            )

        session.execute(delete(FlowchartEdge).where(FlowchartEdge.flowchart_id == flowchart_id))
        if node_ids:
            session.execute(delete(FlowchartNode).where(FlowchartNode.id.in_(node_ids)))
        if run_ids:
            session.execute(delete(FlowchartRun).where(FlowchartRun.id.in_(run_ids)))
        if task_ids:
            tasks = (
                session.execute(select(AgentTask).where(AgentTask.id.in_(task_ids)))
                .scalars()
                .all()
            )
            for task in tasks:
                session.delete(task)

        session.delete(flowchart)
    if is_api_request:
        return {"deleted": True, "flowchart_id": flowchart_id}
    flash("Flowchart deleted.", "success")
    return redirect(next_url)


@bp.get("/flowcharts/<int:flowchart_id>/graph")
def get_flowchart_graph(flowchart_id: int):
    with session_scope() as session:
        existing_flowchart = session.get(Flowchart, flowchart_id)
        if existing_flowchart is None:
            abort(404)
        _ensure_flowchart_start_node(session, flowchart_id=flowchart_id)
        flowchart = (
            session.execute(
                select(Flowchart)
                .options(
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.mcp_servers),
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.scripts),
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.skills),
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.attachments),
                    selectinload(Flowchart.edges),
                )
                .where(Flowchart.id == flowchart_id)
            )
            .scalars()
            .first()
        )
        errors = _validate_flowchart_graph(flowchart.nodes, flowchart.edges)
        for node in flowchart.nodes:
            if (
                node.node_type in FLOWCHART_NODE_TYPE_WITH_REF
                and node.ref_id is not None
                and not _flowchart_ref_exists(
                    session,
                    node_type=node.node_type,
                    ref_id=node.ref_id,
                )
            ):
                errors.append(
                    f"Node {node.id} ({node.node_type}) ref_id {node.ref_id} does not exist."
                )
    return {
        "flowchart_id": flowchart_id,
        "nodes": [_serialize_flowchart_node(node) for node in flowchart.nodes],
        "edges": [_serialize_flowchart_edge(edge) for edge in flowchart.edges],
        "validation": {"valid": len(errors) == 0, "errors": errors},
    }


@bp.post("/flowcharts/<int:flowchart_id>/graph")
def upsert_flowchart_graph(flowchart_id: int):
    payload = _flowchart_request_payload()
    if not payload:
        graph_json = request.form.get("graph_json", "").strip()
        if graph_json:
            try:
                parsed = json.loads(graph_json)
            except json.JSONDecodeError:
                return {"error": "graph_json must be valid JSON."}, 400
            if isinstance(parsed, dict):
                payload = parsed

    raw_nodes = payload.get("nodes")
    raw_edges = payload.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        return {"error": "Graph payload must contain nodes[] and edges[] arrays."}, 400

    node_skill_binding_mode = _node_skill_binding_mode()
    node_skill_warnings: list[str] = []
    validation_errors: list[str] = []
    try:
        with session_scope() as session:
            flowchart = session.get(Flowchart, flowchart_id)
            if flowchart is None:
                abort(404)

            existing_nodes = (
                session.execute(
                    select(FlowchartNode)
                    .options(
                        selectinload(FlowchartNode.mcp_servers),
                        selectinload(FlowchartNode.scripts),
                        selectinload(FlowchartNode.skills),
                        selectinload(FlowchartNode.attachments),
                    )
                    .where(FlowchartNode.flowchart_id == flowchart_id)
                )
                .scalars()
                .all()
            )
            existing_nodes_by_id = {node.id: node for node in existing_nodes}
            existing_start_node = next(
                (
                    node
                    for node in existing_nodes
                    if node.node_type == FLOWCHART_NODE_TYPE_START
                ),
                None,
            )
            keep_node_ids: set[int] = set()
            token_to_node_id: dict[str, int] = {}

            for index, raw_node in enumerate(raw_nodes):
                if not isinstance(raw_node, dict):
                    raise ValueError(f"nodes[{index}] must be an object.")
                node_type = str(raw_node.get("node_type") or "").strip().lower()
                if node_type not in FLOWCHART_NODE_TYPE_CHOICES:
                    raise ValueError(f"nodes[{index}] has invalid node_type '{node_type}'.")
                node_id_raw = raw_node.get("id")
                node_id = _coerce_optional_int(node_id_raw, field_name=f"nodes[{index}].id")
                ref_id = _coerce_optional_int(
                    raw_node.get("ref_id"), field_name=f"nodes[{index}].ref_id"
                )
                model_field_present = "model_id" in raw_node
                model_id = _coerce_optional_int(
                    raw_node.get("model_id"), field_name=f"nodes[{index}].model_id"
                )
                x = _coerce_float(raw_node.get("x"), field_name=f"nodes[{index}].x")
                y = _coerce_float(raw_node.get("y"), field_name=f"nodes[{index}].y")
                title = str(raw_node.get("title") or "").strip() or None
                config = raw_node.get("config")
                if config is None and "config_json" in raw_node:
                    config = raw_node.get("config_json")
                if config is None:
                    config_payload: dict[str, object] = {}
                elif isinstance(config, dict):
                    config_payload = config
                else:
                    raise ValueError(f"nodes[{index}].config must be an object.")
                if node_type == FLOWCHART_NODE_TYPE_TASK:
                    raw_integration_keys = config_payload.get("integration_keys")
                    if raw_integration_keys is not None:
                        if not isinstance(raw_integration_keys, list):
                            raise ValueError(
                                f"nodes[{index}].config.integration_keys must be an array."
                            )
                        (
                            selected_integration_keys,
                            invalid_integration_keys,
                        ) = validate_task_integration_keys(raw_integration_keys)
                        if invalid_integration_keys:
                            raise ValueError(
                                f"nodes[{index}].config.integration_keys contains invalid key(s): "
                                + ", ".join(invalid_integration_keys)
                                + "."
                            )
                        config_payload["integration_keys"] = selected_integration_keys
                    config_payload.pop("route_key_path", None)
                else:
                    config_payload.pop("integration_keys", None)
                if node_type == FLOWCHART_NODE_TYPE_RAG:
                    selected_model_provider: str | None = None
                    if model_id is not None:
                        selected_model = session.get(LLMModel, model_id)
                        if selected_model is None:
                            raise ValueError(f"nodes[{index}].model_id {model_id} was not found.")
                        selected_model_provider = selected_model.provider
                    config_payload = _sanitize_rag_node_config(
                        config_payload,
                        model_provider=selected_model_provider,
                    )

                if node_type in FLOWCHART_NODE_TYPE_REQUIRES_REF and ref_id is None:
                    raise ValueError(f"nodes[{index}] requires ref_id for node_type '{node_type}'.")
                if node_type not in FLOWCHART_NODE_TYPE_WITH_REF and ref_id is not None:
                    raise ValueError(
                        f"nodes[{index}] node_type '{node_type}' does not allow ref_id."
                    )
                if (
                    node_type == FLOWCHART_NODE_TYPE_TASK
                    and ref_id is None
                    and not _task_node_has_prompt(config_payload)
                ):
                    raise ValueError(
                        f"nodes[{index}] task node requires ref_id or config.task_prompt."
                    )
                compatibility_errors = _validate_flowchart_utility_compatibility(
                    node_type,
                    model_id=model_id if model_field_present else None,
                )
                if compatibility_errors:
                    raise ValueError(compatibility_errors[0])

                flowchart_node = (
                    existing_nodes_by_id.get(node_id) if node_id is not None else None
                )
                if (
                    flowchart_node is None
                    and node_type == FLOWCHART_NODE_TYPE_START
                    and existing_start_node is not None
                ):
                    flowchart_node = existing_start_node
                if flowchart_node is None:
                    flowchart_node = FlowchartNode.create(
                        session,
                        flowchart_id=flowchart_id,
                        node_type=node_type,
                        ref_id=ref_id,
                        title=title,
                        x=x,
                        y=y,
                        config_json=json.dumps(config_payload, sort_keys=True),
                    )
                else:
                    flowchart_node.node_type = node_type
                    flowchart_node.ref_id = ref_id
                    flowchart_node.title = title
                    flowchart_node.x = x
                    flowchart_node.y = y
                    flowchart_node.config_json = json.dumps(config_payload, sort_keys=True)
                if model_field_present:
                    if model_id is not None and session.get(LLMModel, model_id) is None:
                        raise ValueError(f"nodes[{index}].model_id {model_id} was not found.")
                    flowchart_node.model_id = model_id

                if (
                    node_type in FLOWCHART_NODE_TYPE_WITH_REF
                    and flowchart_node.ref_id is not None
                    and not _flowchart_ref_exists(
                        session,
                        node_type=node_type,
                        ref_id=flowchart_node.ref_id,
                    )
                ):
                    raise ValueError(
                        f"nodes[{index}] references missing ref_id {flowchart_node.ref_id}."
                    )

                if "mcp_server_ids" in raw_node:
                    mcp_server_ids_raw = raw_node.get("mcp_server_ids")
                    if not isinstance(mcp_server_ids_raw, list):
                        raise ValueError(f"nodes[{index}].mcp_server_ids must be an array.")
                    mcp_server_ids: list[int] = []
                    for mcp_index, mcp_id_raw in enumerate(mcp_server_ids_raw):
                        mcp_id = _coerce_optional_int(
                            mcp_id_raw,
                            field_name=f"nodes[{index}].mcp_server_ids[{mcp_index}]",
                            minimum=1,
                        )
                        if mcp_id is None:
                            raise ValueError(
                                f"nodes[{index}].mcp_server_ids[{mcp_index}] is invalid."
                            )
                        mcp_server_ids.append(mcp_id)
                    compatibility_errors = _validate_flowchart_utility_compatibility(
                        node_type,
                        model_id=None,
                        mcp_server_ids=mcp_server_ids,
                    )
                    if compatibility_errors:
                        raise ValueError(compatibility_errors[0])
                    selected_servers = (
                        session.execute(select(MCPServer).where(MCPServer.id.in_(mcp_server_ids)))
                        .scalars()
                        .all()
                    )
                    if len(selected_servers) != len(set(mcp_server_ids)):
                        raise ValueError(f"nodes[{index}] contains unknown MCP server IDs.")
                    flowchart_node.mcp_servers = selected_servers

                if "script_ids" in raw_node:
                    script_ids_raw = raw_node.get("script_ids")
                    if not isinstance(script_ids_raw, list):
                        raise ValueError(f"nodes[{index}].script_ids must be an array.")
                    script_ids: list[int] = []
                    for script_index, script_id_raw in enumerate(script_ids_raw):
                        script_id = _coerce_optional_int(
                            script_id_raw,
                            field_name=f"nodes[{index}].script_ids[{script_index}]",
                            minimum=1,
                        )
                        if script_id is None:
                            raise ValueError(
                                f"nodes[{index}].script_ids[{script_index}] is invalid."
                            )
                        script_ids.append(script_id)
                    compatibility_errors = _validate_flowchart_utility_compatibility(
                        node_type,
                        model_id=None,
                        script_ids=script_ids,
                    )
                    if compatibility_errors:
                        raise ValueError(compatibility_errors[0])
                    selected_scripts = (
                        session.execute(select(Script).where(Script.id.in_(script_ids)))
                        .scalars()
                        .all()
                    )
                    if len(selected_scripts) != len(set(script_ids)):
                        raise ValueError(f"nodes[{index}] contains unknown script IDs.")
                    if any(is_legacy_skill_script_type(item.script_type) for item in selected_scripts):
                        raise ValueError(
                            "Legacy script_type=skill records cannot be attached. "
                            "Assign first-class Skills to an Agent instead."
                        )
                    _set_flowchart_node_scripts(session, flowchart_node.id, script_ids)

                if "attachment_ids" in raw_node:
                    attachment_ids_raw = raw_node.get("attachment_ids")
                    if not isinstance(attachment_ids_raw, list):
                        raise ValueError(f"nodes[{index}].attachment_ids must be an array.")
                    attachment_ids: list[int] = []
                    for attachment_index, attachment_id_raw in enumerate(attachment_ids_raw):
                        attachment_id = _coerce_optional_int(
                            attachment_id_raw,
                            field_name=f"nodes[{index}].attachment_ids[{attachment_index}]",
                            minimum=1,
                        )
                        if attachment_id is None:
                            raise ValueError(
                                f"nodes[{index}].attachment_ids[{attachment_index}] is invalid."
                            )
                        attachment_ids.append(attachment_id)
                    if len(attachment_ids) != len(set(attachment_ids)):
                        raise ValueError(f"nodes[{index}].attachment_ids cannot contain duplicates.")
                    compatibility_errors = _validate_flowchart_utility_compatibility(
                        node_type,
                        model_id=None,
                        attachment_ids=attachment_ids,
                    )
                    if compatibility_errors:
                        raise ValueError(compatibility_errors[0])
                    selected_attachments = (
                        session.execute(select(Attachment).where(Attachment.id.in_(attachment_ids)))
                        .scalars()
                        .all()
                    )
                    if len(selected_attachments) != len(set(attachment_ids)):
                        raise ValueError(f"nodes[{index}] contains unknown attachment IDs.")
                    _set_flowchart_node_attachments(session, flowchart_node.id, attachment_ids)

                if "skill_ids" in raw_node:
                    if node_skill_binding_mode == NODE_SKILL_BINDING_MODE_REJECT:
                        raise ValueError(
                            f"nodes[{index}].skill_ids is no longer writable; assign skills on the Agent."
                        )
                    skill_ids_raw = raw_node.get("skill_ids")
                    if not isinstance(skill_ids_raw, list):
                        raise ValueError(f"nodes[{index}].skill_ids must be an array.")
                    skill_ids: list[int] = []
                    for skill_index, skill_id_raw in enumerate(skill_ids_raw):
                        skill_id = _coerce_optional_int(
                            skill_id_raw,
                            field_name=f"nodes[{index}].skill_ids[{skill_index}]",
                            minimum=1,
                        )
                        if skill_id is None:
                            raise ValueError(
                                f"nodes[{index}].skill_ids[{skill_index}] is invalid."
                            )
                        skill_ids.append(skill_id)
                    if len(skill_ids) != len(set(skill_ids)):
                        raise ValueError(f"nodes[{index}].skill_ids cannot contain duplicates.")
                    _log_node_skill_binding_deprecation_event(
                        source="flowchart_graph_upsert",
                        mode=node_skill_binding_mode,
                        flowchart_id=flowchart_id,
                        node_id=flowchart_node.id,
                        extra={
                            "field": f"nodes[{index}].skill_ids",
                            "skill_id_count": len(skill_ids),
                        },
                    )
                    node_skill_warnings.append(
                        f"nodes[{index}].skill_ids was ignored; assign skills on the Agent."
                    )

                keep_node_ids.add(flowchart_node.id)
                if node_id_raw is not None:
                    token_to_node_id[str(node_id_raw)] = flowchart_node.id
                if raw_node.get("client_id") is not None:
                    token_to_node_id[str(raw_node["client_id"])] = flowchart_node.id
                token_to_node_id[str(flowchart_node.id)] = flowchart_node.id

            session.execute(delete(FlowchartEdge).where(FlowchartEdge.flowchart_id == flowchart_id))

            for index, raw_edge in enumerate(raw_edges):
                if not isinstance(raw_edge, dict):
                    raise ValueError(f"edges[{index}] must be an object.")
                source_raw = raw_edge.get("source_node_id")
                target_raw = raw_edge.get("target_node_id")
                if source_raw is None and "source" in raw_edge:
                    source_raw = raw_edge.get("source")
                if target_raw is None and "target" in raw_edge:
                    target_raw = raw_edge.get("target")
                source_node_id = token_to_node_id.get(str(source_raw))
                target_node_id = token_to_node_id.get(str(target_raw))
                if source_node_id is None:
                    raise ValueError(f"edges[{index}].source_node_id is invalid.")
                if target_node_id is None:
                    raise ValueError(f"edges[{index}].target_node_id is invalid.")
                source_handle_id = _coerce_optional_handle_id(
                    raw_edge.get("source_handle_id"),
                    field_name=f"edges[{index}].source_handle_id",
                )
                target_handle_id = _coerce_optional_handle_id(
                    raw_edge.get("target_handle_id"),
                    field_name=f"edges[{index}].target_handle_id",
                )
                if "edge_mode" not in raw_edge:
                    raise ValueError(f"edges[{index}].edge_mode is required.")
                edge_mode = _coerce_flowchart_edge_mode(
                    raw_edge.get("edge_mode"),
                    field_name=f"edges[{index}].edge_mode",
                )
                condition_key = str(raw_edge.get("condition_key") or "").strip() or None
                label = str(raw_edge.get("label") or "").strip() or None
                FlowchartEdge.create(
                    session,
                    flowchart_id=flowchart_id,
                    source_node_id=source_node_id,
                    target_node_id=target_node_id,
                    source_handle_id=source_handle_id,
                    target_handle_id=target_handle_id,
                    edge_mode=edge_mode,
                    condition_key=condition_key,
                    label=label,
                )

            removed_node_ids = set(existing_nodes_by_id).difference(keep_node_ids)
            if removed_node_ids:
                session.execute(
                    delete(flowchart_node_mcp_servers).where(
                        flowchart_node_mcp_servers.c.flowchart_node_id.in_(removed_node_ids)
                    )
                )
                session.execute(
                    delete(flowchart_node_scripts).where(
                        flowchart_node_scripts.c.flowchart_node_id.in_(removed_node_ids)
                    )
                )
                session.execute(
                    delete(flowchart_node_skills).where(
                        flowchart_node_skills.c.flowchart_node_id.in_(removed_node_ids)
                    )
                )
                session.execute(
                    delete(flowchart_node_attachments).where(
                        flowchart_node_attachments.c.flowchart_node_id.in_(removed_node_ids)
                    )
                )
                session.execute(
                    delete(FlowchartNode).where(FlowchartNode.id.in_(removed_node_ids))
                )

            updated_nodes = (
                session.execute(
                    select(FlowchartNode)
                    .options(
                        selectinload(FlowchartNode.mcp_servers),
                        selectinload(FlowchartNode.scripts),
                        selectinload(FlowchartNode.skills),
                        selectinload(FlowchartNode.attachments),
                    )
                    .where(FlowchartNode.flowchart_id == flowchart_id)
                    .order_by(FlowchartNode.id.asc())
                )
                .scalars()
                .all()
            )
            updated_edges = (
                session.execute(
                    select(FlowchartEdge)
                    .where(FlowchartEdge.flowchart_id == flowchart_id)
                    .order_by(FlowchartEdge.id.asc())
                )
                .scalars()
                .all()
            )
            validation_errors = _validate_flowchart_graph(updated_nodes, updated_edges)
            for node in updated_nodes:
                if (
                    node.node_type in FLOWCHART_NODE_TYPE_WITH_REF
                    and node.ref_id is not None
                    and not _flowchart_ref_exists(
                        session,
                        node_type=node.node_type,
                        ref_id=node.ref_id,
                    )
                ):
                    validation_errors.append(
                        f"Node {node.id} ({node.node_type}) ref_id {node.ref_id} does not exist."
                    )
            if validation_errors:
                raise ValueError("Flowchart graph validation failed.")
    except ValueError as exc:
        if validation_errors:
            return {
                "error": str(exc),
                "validation": {"valid": False, "errors": validation_errors},
            }, 400
        return {"error": str(exc)}, 400

    response_payload = get_flowchart_graph(flowchart_id)
    if node_skill_warnings:
        response_payload.update(
            _node_skill_binding_deprecation_warning(mode=node_skill_binding_mode)
        )
        response_payload["warnings"] = sorted(set(node_skill_warnings))
    return response_payload


@bp.get("/flowcharts/<int:flowchart_id>/validate")
def validate_flowchart(flowchart_id: int):
    with session_scope() as session:
        flowchart = (
            session.execute(
                select(Flowchart)
                .options(
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.mcp_servers),
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.scripts),
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.skills),
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.attachments),
                    selectinload(Flowchart.edges),
                )
                .where(Flowchart.id == flowchart_id)
            )
            .scalars()
            .first()
        )
        if flowchart is None:
            abort(404)
        errors = _validate_flowchart_graph(flowchart.nodes, flowchart.edges)
        for node in flowchart.nodes:
            if (
                node.node_type in FLOWCHART_NODE_TYPE_WITH_REF
                and node.ref_id is not None
                and not _flowchart_ref_exists(
                    session,
                    node_type=node.node_type,
                    ref_id=node.ref_id,
                )
            ):
                errors.append(
                    f"Node {node.id} ({node.node_type}) ref_id {node.ref_id} does not exist."
                )
    return {
        "flowchart_id": flowchart_id,
        "valid": len(errors) == 0,
        "errors": errors,
    }


@bp.post("/flowcharts/<int:flowchart_id>/run")
def run_flowchart_route(flowchart_id: int):
    validation_errors: list[str] = []
    with session_scope() as session:
        flowchart = (
            session.execute(
                select(Flowchart)
                .options(
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.mcp_servers),
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.scripts),
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.skills),
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.attachments),
                    selectinload(Flowchart.edges),
                )
                .where(Flowchart.id == flowchart_id)
            )
            .scalars()
            .first()
        )
        if flowchart is None:
            abort(404)
        validation_errors = _validate_flowchart_graph(flowchart.nodes, flowchart.edges)
        for node in flowchart.nodes:
            if (
                node.node_type in FLOWCHART_NODE_TYPE_WITH_REF
                and node.ref_id is not None
                and not _flowchart_ref_exists(
                    session,
                    node_type=node.node_type,
                    ref_id=node.ref_id,
                )
            ):
                validation_errors.append(
                    f"Node {node.id} ({node.node_type}) ref_id {node.ref_id} does not exist."
                )
        if validation_errors:
            return {
                "error": "Flowchart graph validation failed.",
                "validation": {"valid": False, "errors": validation_errors},
            }, 400
        flowchart_run = FlowchartRun.create(
            session,
            flowchart_id=flowchart_id,
            status="queued",
        )
        run_id = flowchart_run.id

    async_result = run_flowchart.delay(flowchart_id, run_id)
    flowchart_run_payload: dict[str, object]
    with session_scope() as session:
        flowchart_run = session.get(FlowchartRun, run_id)
        if flowchart_run is None:
            abort(404)
        flowchart_run.celery_task_id = async_result.id
        flowchart_run_payload = _serialize_flowchart_run(flowchart_run)
    return {
        "flowchart_run": {
            **flowchart_run_payload,
            "validation": {"valid": True, "errors": []},
        }
    }, 202


@bp.get("/flowcharts/runs/<int:run_id>")
def view_flowchart_run(run_id: int):
    with session_scope() as session:
        flowchart_run = session.get(FlowchartRun, run_id)
        if flowchart_run is None:
            abort(404)
        flowchart = session.get(Flowchart, flowchart_run.flowchart_id)
        node_runs = (
            session.execute(
                select(FlowchartRunNode)
                .where(FlowchartRunNode.flowchart_run_id == run_id)
                .order_by(
                    FlowchartRunNode.execution_index.asc(),
                    FlowchartRunNode.created_at.asc(),
                    FlowchartRunNode.id.asc(),
                )
            )
            .scalars()
            .all()
        )
    return {
        "flowchart_run": _serialize_flowchart_run(flowchart_run),
        "flowchart": _serialize_flowchart(flowchart) if flowchart is not None else None,
        "node_runs": [_serialize_flowchart_run_node(node_run) for node_run in node_runs],
    }


@bp.get("/flowcharts/runs/<int:run_id>/status")
def flowchart_run_status(run_id: int):
    with session_scope() as session:
        flowchart_run = session.get(FlowchartRun, run_id)
        if flowchart_run is None:
            abort(404)
        rows = session.execute(
            select(FlowchartRunNode.status, func.count(FlowchartRunNode.id))
            .where(FlowchartRunNode.flowchart_run_id == run_id)
            .group_by(FlowchartRunNode.status)
        ).all()
    counts = {str(status): int(count or 0) for status, count in rows}
    return {
        "id": flowchart_run.id,
        "status": flowchart_run.status,
        "created_at": _human_time(flowchart_run.created_at),
        "started_at": _human_time(flowchart_run.started_at),
        "finished_at": _human_time(flowchart_run.finished_at),
        "counts": counts,
    }


@bp.get("/flowcharts/<int:flowchart_id>/runtime")
def flowchart_runtime_status(flowchart_id: int):
    active_run_id: int | None = None
    active_run_status: str | None = None
    running_node_ids: list[int] = []
    with session_scope() as session:
        flowchart = session.get(Flowchart, flowchart_id)
        if flowchart is None:
            abort(404)
        active_run = (
            session.execute(
                select(FlowchartRun)
                .where(
                    FlowchartRun.flowchart_id == flowchart_id,
                    FlowchartRun.status.in_(["queued", "running", "stopping"]),
                )
                .order_by(FlowchartRun.created_at.desc(), FlowchartRun.id.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if active_run is None:
            return {
                "flowchart_id": flowchart_id,
                "active_run_id": None,
                "active_run_status": None,
                "running_node_ids": [],
            }
        active_run_id = int(active_run.id)
        active_run_status = str(active_run.status or "")
        running_node_ids = [
            int(node_id)
            for node_id in session.execute(
                select(FlowchartRunNode.flowchart_node_id)
                .where(
                    FlowchartRunNode.flowchart_run_id == active_run_id,
                    FlowchartRunNode.status == "running",
                )
                .order_by(
                    FlowchartRunNode.execution_index.asc(),
                    FlowchartRunNode.created_at.asc(),
                    FlowchartRunNode.id.asc(),
                )
            )
            .scalars()
            .all()
            if isinstance(node_id, int) and node_id > 0
        ]
    return {
        "flowchart_id": flowchart_id,
        "active_run_id": active_run_id,
        "active_run_status": active_run_status,
        "running_node_ids": running_node_ids,
    }


@bp.post("/flowcharts/runs/<int:run_id>/cancel")
def cancel_flowchart_run(run_id: int):
    payload = _flowchart_request_payload()
    wants_json = request.is_json or bool(payload) or _flowchart_wants_json()
    force_value = payload.get("force")
    if force_value is None:
        force_value = request.form.get("force")
    if force_value is None:
        force_value = request.args.get("force")
    force = _flowchart_as_bool(force_value)

    revoke_actions: list[tuple[str, bool]] = []
    action = "none"
    updated = False
    flowchart_id: int | None = None
    with session_scope() as session:
        flowchart_run = session.get(FlowchartRun, run_id)
        if flowchart_run is None:
            abort(404)
        flowchart_id = flowchart_run.flowchart_id
        now = utcnow()
        current_status = str(flowchart_run.status or "").strip().lower()

        if force:
            if current_status in {"queued", "running", "stopping"}:
                action = "canceled"
                updated = True
                flowchart_run.status = "canceled"
                flowchart_run.finished_at = now
                if flowchart_run.celery_task_id:
                    revoke_actions.append((flowchart_run.celery_task_id, True))

                node_runs = (
                    session.execute(
                        select(FlowchartRunNode).where(FlowchartRunNode.flowchart_run_id == run_id)
                    )
                    .scalars()
                    .all()
                )
                for node_run in node_runs:
                    if node_run.status in {"queued", "running", "pending"}:
                        node_run.status = "canceled"
                        node_run.finished_at = now

                tasks = (
                    session.execute(select(AgentTask).where(AgentTask.flowchart_run_id == run_id))
                    .scalars()
                    .all()
                )
                for task in tasks:
                    if task.status in {"pending", "queued", "running"}:
                        task.status = "canceled"
                        task.finished_at = now
                        if not task.error:
                            task.error = "Canceled by user."
                    if task.celery_task_id:
                        revoke_actions.append((task.celery_task_id, True))
        else:
            if current_status == "queued":
                action = "stopped"
                updated = True
                flowchart_run.status = "stopped"
                flowchart_run.finished_at = now
                if flowchart_run.celery_task_id:
                    revoke_actions.append((flowchart_run.celery_task_id, False))
            elif current_status == "running":
                action = "stopping"
                updated = True
                flowchart_run.status = "stopping"
            elif current_status == "stopping":
                action = "stopping"

        response_payload = {
            "flowchart_run": _serialize_flowchart_run(flowchart_run),
            "force": force,
            "updated": updated,
            "action": action,
            "canceled": action == "canceled",
            "stop_requested": action in {"stopping", "stopped"},
        }

    for task_id, terminate in revoke_actions:
        try:
            if terminate:
                celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
            else:
                celery_app.control.revoke(task_id)
        except Exception as exc:
            logger.warning("Failed to revoke flowchart task %s: %s", task_id, exc)

    if wants_json:
        return response_payload

    default_next = (
        url_for("agents.view_flowchart_history_run", flowchart_id=flowchart_id, run_id=run_id)
        if flowchart_id is not None
        else url_for("agents.list_flowcharts")
    )
    redirect_target = _safe_redirect_target(request.form.get("next"), default_next)
    if response_payload["action"] == "canceled":
        flash("Flowchart force stop requested.", "success")
    elif response_payload["action"] == "stopped":
        flash("Flowchart stopped.", "success")
    elif response_payload["action"] == "stopping":
        flash("Flowchart stop requested. It will stop after the current node finishes.", "success")
    else:
        flash("Flowchart run is not active.", "info")
    return redirect(redirect_target)


@bp.get("/flowcharts/<int:flowchart_id>/nodes/<int:node_id>/utilities")
def get_flowchart_node_utilities(flowchart_id: int, node_id: int):
    with session_scope() as session:
        flowchart_node = (
            session.execute(
                select(FlowchartNode)
                .options(
                    selectinload(FlowchartNode.mcp_servers),
                    selectinload(FlowchartNode.scripts),
                    selectinload(FlowchartNode.attachments),
                )
                .where(FlowchartNode.id == node_id)
            )
            .scalars()
            .first()
        )
        if flowchart_node is None or flowchart_node.flowchart_id != flowchart_id:
            abort(404)
        compatibility_errors = _validate_flowchart_utility_compatibility(
            flowchart_node.node_type,
            model_id=flowchart_node.model_id,
            mcp_server_ids=[server.id for server in flowchart_node.mcp_servers],
            script_ids=[script.id for script in flowchart_node.scripts],
            attachment_ids=[attachment.id for attachment in flowchart_node.attachments],
        )
        return {
            "node": _serialize_flowchart_node(flowchart_node),
            "catalog": _flowchart_catalog(session),
            "validation": {
                "valid": len(compatibility_errors) == 0,
                "errors": compatibility_errors,
            },
        }


@bp.post("/flowcharts/<int:flowchart_id>/nodes/<int:node_id>/model")
def set_flowchart_node_model(flowchart_id: int, node_id: int):
    payload = _flowchart_request_payload()
    model_id_raw = payload.get("model_id") if payload else request.form.get("model_id")
    try:
        model_id = _coerce_optional_int(model_id_raw, field_name="model_id", minimum=1)
    except ValueError as exc:
        return {"error": str(exc)}, 400

    with session_scope() as session:
        flowchart_node = session.get(FlowchartNode, node_id)
        if flowchart_node is None or flowchart_node.flowchart_id != flowchart_id:
            abort(404)
        errors = _validate_flowchart_utility_compatibility(
            flowchart_node.node_type,
            model_id=model_id,
        )
        if errors:
            return {"error": errors[0]}, 400
        if model_id is not None and session.get(LLMModel, model_id) is None:
            return {"error": f"Model {model_id} was not found."}, 404
        if (
            flowchart_node.node_type == FLOWCHART_NODE_TYPE_RAG
            and model_id is not None
        ):
            selected_model = session.get(LLMModel, model_id)
            rag_config = _parse_json_dict(flowchart_node.config_json)
            rag_mode = str(rag_config.get("mode") or "").strip().lower()
            if rag_mode in {RAG_NODE_MODE_FRESH_INDEX, RAG_NODE_MODE_DELTA_INDEX}:
                if selected_model is None or not _is_rag_embedding_model_provider(
                    selected_model.provider
                ):
                    return {
                        "error": (
                            "Index modes require an embedding-capable model provider "
                            "(codex or gemini)."
                        )
                    }, 400
        flowchart_node.model_id = model_id
        return {"node": _serialize_flowchart_node(flowchart_node)}


@bp.post("/flowcharts/<int:flowchart_id>/nodes/<int:node_id>/mcp-servers")
def attach_flowchart_node_mcp(flowchart_id: int, node_id: int):
    payload = _flowchart_request_payload()
    mcp_id_raw = payload.get("mcp_server_id") if payload else request.form.get("mcp_server_id")
    try:
        mcp_id = _coerce_optional_int(mcp_id_raw, field_name="mcp_server_id", minimum=1)
    except ValueError as exc:
        return {"error": str(exc)}, 400
    if mcp_id is None:
        return {"error": "mcp_server_id is required."}, 400

    with session_scope() as session:
        flowchart_node = (
            session.execute(
                select(FlowchartNode)
                .options(selectinload(FlowchartNode.mcp_servers))
                .where(FlowchartNode.id == node_id)
            )
            .scalars()
            .first()
        )
        if flowchart_node is None or flowchart_node.flowchart_id != flowchart_id:
            abort(404)
        errors = _validate_flowchart_utility_compatibility(
            flowchart_node.node_type,
            model_id=None,
            mcp_server_ids=[mcp_id],
        )
        if errors:
            return {"error": errors[0]}, 400
        server = session.get(MCPServer, mcp_id)
        if server is None:
            return {"error": f"MCP server {mcp_id} was not found."}, 404
        existing = {item.id for item in flowchart_node.mcp_servers}
        if server.id not in existing:
            flowchart_node.mcp_servers.append(server)
        return {"node": _serialize_flowchart_node(flowchart_node)}


@bp.post("/flowcharts/<int:flowchart_id>/nodes/<int:node_id>/mcp-servers/<int:mcp_id>/delete")
def detach_flowchart_node_mcp(flowchart_id: int, node_id: int, mcp_id: int):
    with session_scope() as session:
        flowchart_node = (
            session.execute(
                select(FlowchartNode)
                .options(selectinload(FlowchartNode.mcp_servers))
                .where(FlowchartNode.id == node_id)
            )
            .scalars()
            .first()
        )
        if flowchart_node is None or flowchart_node.flowchart_id != flowchart_id:
            abort(404)
        for server in list(flowchart_node.mcp_servers):
            if server.id == mcp_id:
                flowchart_node.mcp_servers.remove(server)
        return {"node": _serialize_flowchart_node(flowchart_node)}


@bp.post("/flowcharts/<int:flowchart_id>/nodes/<int:node_id>/scripts")
def attach_flowchart_node_script(flowchart_id: int, node_id: int):
    payload = _flowchart_request_payload()
    script_id_raw = payload.get("script_id") if payload else request.form.get("script_id")
    try:
        script_id = _coerce_optional_int(script_id_raw, field_name="script_id", minimum=1)
    except ValueError as exc:
        return {"error": str(exc)}, 400
    if script_id is None:
        return {"error": "script_id is required."}, 400

    with session_scope() as session:
        flowchart_node = (
            session.execute(
                select(FlowchartNode)
                .options(
                    selectinload(FlowchartNode.scripts),
                    selectinload(FlowchartNode.skills),
                )
                .where(FlowchartNode.id == node_id)
            )
            .scalars()
            .first()
        )
        if flowchart_node is None or flowchart_node.flowchart_id != flowchart_id:
            abort(404)
        errors = _validate_flowchart_utility_compatibility(
            flowchart_node.node_type,
            model_id=None,
            script_ids=[script_id],
        )
        if errors:
            return {"error": errors[0]}, 400
        script = session.get(Script, script_id)
        if script is None:
            return {"error": f"Script {script_id} was not found."}, 404
        if is_legacy_skill_script_type(script.script_type):
            return {
                "error": (
                    "Legacy script_type=skill records cannot be attached. "
                    "Assign first-class Skills on an Agent."
                )
            }, 400
        ordered_ids = [item.id for item in flowchart_node.scripts]
        if script_id not in ordered_ids:
            ordered_ids.append(script_id)
            _set_flowchart_node_scripts(session, node_id, ordered_ids)
        refreshed = (
            session.execute(
                select(FlowchartNode)
                .options(
                    selectinload(FlowchartNode.scripts),
                    selectinload(FlowchartNode.skills),
                )
                .where(FlowchartNode.id == node_id)
            )
            .scalars()
            .first()
        )
        return {"node": _serialize_flowchart_node(refreshed)}


@bp.post("/flowcharts/<int:flowchart_id>/nodes/<int:node_id>/scripts/<int:script_id>/delete")
def detach_flowchart_node_script(flowchart_id: int, node_id: int, script_id: int):
    with session_scope() as session:
        flowchart_node = (
            session.execute(
                select(FlowchartNode)
                .options(
                    selectinload(FlowchartNode.scripts),
                    selectinload(FlowchartNode.skills),
                )
                .where(FlowchartNode.id == node_id)
            )
            .scalars()
            .first()
        )
        if flowchart_node is None or flowchart_node.flowchart_id != flowchart_id:
            abort(404)
        ordered_ids = [item.id for item in flowchart_node.scripts if item.id != script_id]
        _set_flowchart_node_scripts(session, node_id, ordered_ids)
        refreshed = (
            session.execute(
                select(FlowchartNode)
                .options(
                    selectinload(FlowchartNode.scripts),
                    selectinload(FlowchartNode.skills),
                )
                .where(FlowchartNode.id == node_id)
            )
            .scalars()
            .first()
        )
        return {"node": _serialize_flowchart_node(refreshed)}


@bp.post("/flowcharts/<int:flowchart_id>/nodes/<int:node_id>/scripts/reorder")
def reorder_flowchart_node_scripts(flowchart_id: int, node_id: int):
    payload = _flowchart_request_payload()
    script_ids_raw = payload.get("script_ids")
    if script_ids_raw is None:
        raw_values = [value.strip() for value in request.form.getlist("script_ids")]
        script_ids_raw = raw_values
    if not isinstance(script_ids_raw, list):
        return {"error": "script_ids must be an array."}, 400

    script_ids: list[int] = []
    for index, script_id_raw in enumerate(script_ids_raw):
        try:
            script_id = _coerce_optional_int(
                script_id_raw,
                field_name=f"script_ids[{index}]",
                minimum=1,
            )
        except ValueError as exc:
            return {"error": str(exc)}, 400
        if script_id is None:
            return {"error": f"script_ids[{index}] is invalid."}, 400
        script_ids.append(script_id)

    if len(script_ids) != len(set(script_ids)):
        return {"error": "script_ids cannot contain duplicates."}, 400

    with session_scope() as session:
        flowchart_node = (
            session.execute(
                select(FlowchartNode)
                .options(
                    selectinload(FlowchartNode.scripts),
                    selectinload(FlowchartNode.skills),
                )
                .where(FlowchartNode.id == node_id)
            )
            .scalars()
            .first()
        )
        if flowchart_node is None or flowchart_node.flowchart_id != flowchart_id:
            abort(404)
        errors = _validate_flowchart_utility_compatibility(
            flowchart_node.node_type,
            model_id=None,
            script_ids=script_ids,
        )
        if errors:
            return {"error": errors[0]}, 400
        if any(is_legacy_skill_script_type(script.script_type) for script in flowchart_node.scripts):
            return {
                "error": (
                    "Legacy script_type=skill records cannot be reordered; "
                    "migrate to first-class Skills."
                )
            }, 400
        existing_ids = {script.id for script in flowchart_node.scripts}
        if set(script_ids) != existing_ids:
            return {
                "error": "script_ids must include each attached script exactly once."
            }, 400
        _set_flowchart_node_scripts(session, node_id, script_ids)
        refreshed = (
            session.execute(
                select(FlowchartNode)
                .options(
                    selectinload(FlowchartNode.scripts),
                    selectinload(FlowchartNode.skills),
                )
                .where(FlowchartNode.id == node_id)
            )
            .scalars()
            .first()
        )
        return {"node": _serialize_flowchart_node(refreshed)}


@bp.post("/flowcharts/<int:flowchart_id>/nodes/<int:node_id>/skills")
def attach_flowchart_node_skill(flowchart_id: int, node_id: int):
    payload = _flowchart_request_payload()
    skill_id_raw = payload.get("skill_id") if payload else request.form.get("skill_id")
    try:
        skill_id = _coerce_optional_int(skill_id_raw, field_name="skill_id", minimum=1)
    except ValueError as exc:
        return {"error": str(exc)}, 400
    if skill_id is None:
        return {"error": "skill_id is required."}, 400
    mode = _node_skill_binding_mode()
    if mode == NODE_SKILL_BINDING_MODE_REJECT:
        return _node_skill_binding_write_rejected(mode=mode)
    with session_scope() as session:
        flowchart_node = (
            session.execute(
                select(FlowchartNode)
                .options(
                    selectinload(FlowchartNode.mcp_servers),
                    selectinload(FlowchartNode.scripts),
                )
                .where(FlowchartNode.id == node_id)
            )
            .scalars()
            .first()
        )
        if flowchart_node is None or flowchart_node.flowchart_id != flowchart_id:
            abort(404)
        _log_node_skill_binding_deprecation_event(
            source="flowchart_node_skill_attach",
            mode=mode,
            flowchart_id=flowchart_id,
            node_id=node_id,
            extra={"skill_id": skill_id},
        )
        response_payload = {
            "node": _serialize_flowchart_node(flowchart_node),
        }
        response_payload.update(_node_skill_binding_deprecation_warning(mode=mode))
        return response_payload


@bp.post("/flowcharts/<int:flowchart_id>/nodes/<int:node_id>/skills/<int:skill_id>/delete")
def detach_flowchart_node_skill(flowchart_id: int, node_id: int, skill_id: int):
    mode = _node_skill_binding_mode()
    if mode == NODE_SKILL_BINDING_MODE_REJECT:
        return _node_skill_binding_write_rejected(mode=mode)
    with session_scope() as session:
        flowchart_node = (
            session.execute(
                select(FlowchartNode)
                .options(
                    selectinload(FlowchartNode.mcp_servers),
                    selectinload(FlowchartNode.scripts),
                )
                .where(FlowchartNode.id == node_id)
            )
            .scalars()
            .first()
        )
        if flowchart_node is None or flowchart_node.flowchart_id != flowchart_id:
            abort(404)
        _log_node_skill_binding_deprecation_event(
            source="flowchart_node_skill_detach",
            mode=mode,
            flowchart_id=flowchart_id,
            node_id=node_id,
            extra={"skill_id": skill_id},
        )
        response_payload = {
            "node": _serialize_flowchart_node(flowchart_node),
        }
        response_payload.update(_node_skill_binding_deprecation_warning(mode=mode))
        return response_payload


@bp.post("/flowcharts/<int:flowchart_id>/nodes/<int:node_id>/skills/reorder")
def reorder_flowchart_node_skills(flowchart_id: int, node_id: int):
    payload = _flowchart_request_payload()
    skill_ids_raw = payload.get("skill_ids")
    if skill_ids_raw is None:
        skill_ids_raw = [value.strip() for value in request.form.getlist("skill_ids")]
    if not isinstance(skill_ids_raw, list):
        return {"error": "skill_ids must be an array."}, 400
    skill_ids: list[int] = []
    for index, skill_id_raw in enumerate(skill_ids_raw):
        try:
            skill_id = _coerce_optional_int(
                skill_id_raw,
                field_name=f"skill_ids[{index}]",
                minimum=1,
            )
        except ValueError as exc:
            return {"error": str(exc)}, 400
        if skill_id is None:
            return {"error": f"skill_ids[{index}] is invalid."}, 400
        skill_ids.append(skill_id)
    if len(skill_ids) != len(set(skill_ids)):
        return {"error": "skill_ids cannot contain duplicates."}, 400
    mode = _node_skill_binding_mode()
    if mode == NODE_SKILL_BINDING_MODE_REJECT:
        return _node_skill_binding_write_rejected(mode=mode)
    with session_scope() as session:
        flowchart_node = (
            session.execute(
                select(FlowchartNode)
                .options(
                    selectinload(FlowchartNode.mcp_servers),
                    selectinload(FlowchartNode.scripts),
                )
                .where(FlowchartNode.id == node_id)
            )
            .scalars()
            .first()
        )
        if flowchart_node is None or flowchart_node.flowchart_id != flowchart_id:
            abort(404)
        _log_node_skill_binding_deprecation_event(
            source="flowchart_node_skill_reorder",
            mode=mode,
            flowchart_id=flowchart_id,
            node_id=node_id,
            extra={"skill_id_count": len(skill_ids)},
        )
        response_payload = {
            "node": _serialize_flowchart_node(flowchart_node),
        }
        response_payload.update(_node_skill_binding_deprecation_warning(mode=mode))
        return response_payload


@bp.get("/mcps")
def list_mcps():
    sync_integrated_mcp_servers()
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    mcp_servers = _load_mcp_servers()
    integrated_mcp_servers, custom_mcp_servers = _split_mcp_servers_by_type(mcp_servers)
    return render_template(
        "mcps.html",
        integrated_mcp_servers=integrated_mcp_servers,
        custom_mcp_servers=custom_mcp_servers,
        summary=summary,
        human_time=_human_time,
        page_title="MCP Servers",
        active_page="mcps",
    )


@bp.get("/models")
def list_models():
    models = _load_llm_models()
    llm_settings = _load_integration_settings("llm")
    default_model_id = resolve_default_model_id(llm_settings)
    model_rows = []
    for model in models:
        model_rows.append(
            {
                "id": model.id,
                "name": model.name,
                "description": model.description,
                "provider": model.provider,
                "provider_label": LLM_PROVIDER_LABELS.get(model.provider, model.provider),
                "model_name": _model_display_name(model),
                "is_default": model.id == default_model_id,
            }
        )
    return render_template(
        "models.html",
        models=model_rows,
        default_model_id=default_model_id,
        page_title="Models",
        active_page="models",
    )


@bp.get("/models/new")
def new_model():
    model_options = _provider_model_options()
    local_vllm_models = discover_vllm_local_models()
    codex_default_model = _codex_default_model(model_options.get("codex"))
    vllm_local_default_model = _vllm_local_default_model(local_vllm_models)
    vllm_remote_default_model = _vllm_remote_default_model()
    return render_template(
        "model_new.html",
        provider_options=_provider_options(),
        selected_provider="codex",
        codex_config=_codex_model_config_defaults(
            {},
            default_model=codex_default_model,
        ),
        gemini_config=_gemini_model_config_defaults({}),
        claude_config=_simple_model_config_defaults({}),
        vllm_local_config=_vllm_local_model_config_defaults(
            {},
            default_model=vllm_local_default_model,
        ),
        vllm_remote_config=_vllm_remote_model_config_defaults(
            {},
            default_model=vllm_remote_default_model,
        ),
        vllm_local_models=local_vllm_models,
        model_options=model_options,
        page_title="Create Model",
        active_page="models",
    )


@bp.post("/models")
def create_model():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    provider = (request.form.get("provider") or "").strip().lower()

    if not name:
        flash("Model name is required.", "error")
        return redirect(url_for("agents.new_model"))
    if provider not in LLM_PROVIDERS:
        flash("Unknown provider selection.", "error")
        return redirect(url_for("agents.new_model"))

    config_payload = _model_config_payload(provider, request.form)
    markdown_filename_error = _apply_model_markdown_filename_validation(
        provider,
        config_payload,
    )
    if markdown_filename_error:
        flash(markdown_filename_error, "error")
        return redirect(url_for("agents.new_model"))
    model_options = _provider_model_options()
    model_name = str(config_payload.get("model") or "").strip()
    if provider == "codex" and not _model_option_allowed(provider, model_name, model_options):
        flash("Codex model must be selected from the configured options.", "error")
        return redirect(url_for("agents.new_model"))
    if provider == "vllm_local" and not _model_option_allowed(
        provider,
        model_name,
        model_options,
    ):
        flash(
            "vLLM Local model must be selected from the discovered local model options.",
            "error",
        )
        return redirect(url_for("agents.new_model"))
    config_json = json.dumps(config_payload, indent=2, sort_keys=True)

    with session_scope() as session:
        model = LLMModel.create(
            session,
            name=name,
            description=description or None,
            provider=provider,
            config_json=config_json,
        )

    flash(f"Model {model.id} created.", "success")
    return redirect(url_for("agents.view_model", model_id=model.id))


@bp.get("/models/<int:model_id>")
def view_model(model_id: int):
    with session_scope() as session:
        model = session.get(LLMModel, model_id)
        if model is None:
            abort(404)
        attached_templates = (
            session.execute(
                select(TaskTemplate)
                .where(TaskTemplate.model_id == model_id)
                .order_by(TaskTemplate.created_at.desc())
            )
            .scalars()
            .all()
        )
        attached_nodes = (
            session.execute(
                select(FlowchartNode)
                .where(FlowchartNode.model_id == model_id)
                .order_by(FlowchartNode.created_at.desc())
            )
            .scalars()
            .all()
        )
        attached_tasks = (
            session.execute(
                select(AgentTask)
                .where(AgentTask.model_id == model_id)
                .order_by(AgentTask.created_at.desc())
            )
            .scalars()
            .all()
        )
        flowcharts_by_id: dict[int, str] = {}
        flowchart_ids = {
            node.flowchart_id for node in attached_nodes if node.flowchart_id is not None
        }
        if flowchart_ids:
            rows = session.execute(
                select(Flowchart.id, Flowchart.name).where(Flowchart.id.in_(flowchart_ids))
            ).all()
            flowcharts_by_id = {row[0]: row[1] for row in rows}
    llm_settings = _load_integration_settings("llm")
    default_model_id = resolve_default_model_id(llm_settings)
    is_default = default_model_id == model_id
    config = _decode_model_config(model.config_json)
    formatted_config = json.dumps(config, indent=2, sort_keys=True)
    provider_label = LLM_PROVIDER_LABELS.get(model.provider, model.provider)
    return render_template(
        "model_detail.html",
        model=model,
        provider_label=provider_label,
        model_name=_model_display_name(model),
        config_json=formatted_config,
        attached_templates=attached_templates,
        attached_nodes=attached_nodes,
        attached_tasks=attached_tasks,
        flowcharts_by_id=flowcharts_by_id,
        is_default=is_default,
        page_title=f"Model - {model.name}",
        active_page="models",
    )


@bp.get("/models/<int:model_id>/edit")
def edit_model(model_id: int):
    with session_scope() as session:
        model = session.get(LLMModel, model_id)
        if model is None:
            abort(404)
    config = _decode_model_config(model.config_json)
    model_options = _provider_model_options()
    local_vllm_models = discover_vllm_local_models()
    codex_default_model = _codex_default_model(model_options.get("codex"))
    vllm_local_default_model = _vllm_local_default_model(local_vllm_models)
    vllm_remote_default_model = _vllm_remote_default_model()
    return render_template(
        "model_edit.html",
        model=model,
        provider_options=_provider_options(),
        selected_provider=model.provider,
        codex_config=_codex_model_config_defaults(
            config if model.provider == "codex" else {},
            default_model=codex_default_model,
        ),
        gemini_config=_gemini_model_config_defaults(
            config if model.provider == "gemini" else {}
        ),
        claude_config=_simple_model_config_defaults(
            config if model.provider == "claude" else {}
        ),
        vllm_local_config=_vllm_local_model_config_defaults(
            config if model.provider == "vllm_local" else {},
            default_model=vllm_local_default_model,
        ),
        vllm_remote_config=_vllm_remote_model_config_defaults(
            config if model.provider == "vllm_remote" else {},
            default_model=vllm_remote_default_model,
        ),
        vllm_local_models=local_vllm_models,
        model_options=model_options,
        page_title=f"Edit Model - {model.name}",
        active_page="models",
    )


@bp.post("/models/<int:model_id>")
def update_model(model_id: int):
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    provider = (request.form.get("provider") or "").strip().lower()

    if not name:
        flash("Model name is required.", "error")
        return redirect(url_for("agents.edit_model", model_id=model_id))
    if provider not in LLM_PROVIDERS:
        flash("Unknown provider selection.", "error")
        return redirect(url_for("agents.edit_model", model_id=model_id))

    config_payload = _model_config_payload(provider, request.form)
    markdown_filename_error = _apply_model_markdown_filename_validation(
        provider,
        config_payload,
    )
    if markdown_filename_error:
        flash(markdown_filename_error, "error")
        return redirect(url_for("agents.edit_model", model_id=model_id))
    model_options = _provider_model_options()
    model_name = str(config_payload.get("model") or "").strip()
    if provider == "codex" and not _model_option_allowed(provider, model_name, model_options):
        flash("Codex model must be selected from the configured options.", "error")
        return redirect(url_for("agents.edit_model", model_id=model_id))
    if provider == "vllm_local" and not _model_option_allowed(
        provider,
        model_name,
        model_options,
    ):
        flash(
            "vLLM Local model must be selected from the discovered local model options.",
            "error",
        )
        return redirect(url_for("agents.edit_model", model_id=model_id))
    config_json = json.dumps(config_payload, indent=2, sort_keys=True)

    with session_scope() as session:
        model = session.get(LLMModel, model_id)
        if model is None:
            abort(404)
        model.name = name
        model.description = description or None
        model.provider = provider
        model.config_json = config_json

    flash("Model updated.", "success")
    return redirect(url_for("agents.view_model", model_id=model_id))


@bp.post("/models/default")
def update_default_model():
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_models")
    )
    model_raw = request.form.get("model_id", "").strip()
    if not model_raw.isdigit():
        flash("Model selection required.", "error")
        return redirect(next_url)
    model_id = int(model_raw)
    make_default = _as_bool(request.form.get("is_default"))
    with session_scope() as session:
        model = session.get(LLMModel, model_id)
        if model is None:
            flash("Model not found.", "error")
            return redirect(next_url)
    if make_default:
        payload = {
            "default_model_id": str(model_id),
            f"provider_enabled_{model.provider}": "true",
        }
        _save_integration_settings("llm", payload)
        flash("Default model updated.", "success")
    else:
        _save_integration_settings("llm", {"default_model_id": ""})
        flash("Default model cleared.", "success")
    return redirect(next_url)


@bp.post("/models/<int:model_id>/delete")
def delete_model(model_id: int):
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_models")
    )
    with session_scope() as session:
        model = session.get(LLMModel, model_id)
        if model is None:
            abort(404)
        attached_templates = (
            session.execute(select(TaskTemplate).where(TaskTemplate.model_id == model_id))
            .scalars()
            .all()
        )
        attached_nodes = (
            session.execute(select(FlowchartNode).where(FlowchartNode.model_id == model_id))
            .scalars()
            .all()
        )
        attached_tasks = (
            session.execute(select(AgentTask).where(AgentTask.model_id == model_id))
            .scalars()
            .all()
        )
        for template in attached_templates:
            template.model_id = None
        for node in attached_nodes:
            node.model_id = None
        for task in attached_tasks:
            task.model_id = None
        session.delete(model)

    flash("Model deleted.", "success")
    detached_count = len(attached_templates) + len(attached_nodes) + len(attached_tasks)
    if detached_count:
        flash(f"Detached from {detached_count} binding(s).", "info")
    llm_settings = _load_integration_settings("llm")
    if resolve_default_model_id(llm_settings) == model_id:
        _save_integration_settings("llm", {"default_model_id": ""})
        flash("Default model cleared.", "info")
    return redirect(next_url)


@bp.get("/mcps/new")
def new_mcp():
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    return render_template(
        "mcp_new.html",
        summary=summary,
        page_title="Create Custom MCP Server",
        active_page="mcps",
    )


@bp.post("/mcps")
def create_mcp():
    name = request.form.get("name", "").strip()
    server_key = request.form.get("server_key", "").strip()
    description = request.form.get("description", "").strip()
    raw_config = request.form.get("config_json", "").strip()

    if not name or not server_key:
        flash("Name and server key are required.", "error")
        return redirect(url_for("agents.new_mcp"))
    if not raw_config:
        flash("MCP config TOML is required.", "error")
        return redirect(url_for("agents.new_mcp"))
    if server_key in SYSTEM_MANAGED_MCP_SERVER_KEYS:
        flash(
            f"Server key '{server_key}' is system-managed and cannot be created manually.",
            "error",
        )
        return redirect(url_for("agents.new_mcp"))

    try:
        validate_server_key(server_key)
        formatted_config = format_mcp_config(raw_config, server_key=server_key)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("agents.new_mcp"))

    with session_scope() as session:
        existing = session.execute(
            select(MCPServer).where(MCPServer.server_key == server_key)
        ).scalar_one_or_none()
        if existing is not None:
            flash("Server key is already in use.", "error")
            return redirect(url_for("agents.new_mcp"))
        mcp = MCPServer.create(
            session,
            name=name,
            server_key=server_key,
            description=description or None,
            config_json=formatted_config,
            server_type=MCP_SERVER_TYPE_CUSTOM,
        )

    flash(f"MCP server {mcp.id} created.", "success")
    return redirect(url_for("agents.view_mcp", mcp_id=mcp.id))


@bp.get("/mcps/<int:mcp_id>/edit")
def edit_mcp(mcp_id: int):
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    with session_scope() as session:
        mcp_server = session.get(MCPServer, mcp_id)
        if mcp_server is None:
            abort(404)
        if mcp_server.is_integrated:
            flash("Integrated MCP servers are managed from Integrations settings.", "error")
            return redirect(url_for("agents.view_mcp", mcp_id=mcp_id))
    return render_template(
        "mcp_edit.html",
        mcp_server=mcp_server,
        summary=summary,
        page_title=f"Edit Custom MCP Server - {mcp_server.name}",
        active_page="mcps",
    )


@bp.post("/mcps/<int:mcp_id>")
def update_mcp(mcp_id: int):
    name = request.form.get("name", "").strip()
    server_key = request.form.get("server_key", "").strip()
    description = request.form.get("description", "").strip()
    raw_config = request.form.get("config_json", "").strip()

    if not name or not server_key:
        flash("Name and server key are required.", "error")
        return redirect(url_for("agents.edit_mcp", mcp_id=mcp_id))
    if not raw_config:
        flash("MCP config TOML is required.", "error")
        return redirect(url_for("agents.edit_mcp", mcp_id=mcp_id))

    try:
        validate_server_key(server_key)
        formatted_config = format_mcp_config(raw_config, server_key=server_key)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("agents.edit_mcp", mcp_id=mcp_id))

    with session_scope() as session:
        mcp = session.get(MCPServer, mcp_id)
        if mcp is None:
            abort(404)
        if mcp.is_integrated:
            flash("Integrated MCP servers are managed from Integrations settings.", "error")
            return redirect(url_for("agents.view_mcp", mcp_id=mcp_id))
        if (
            server_key in SYSTEM_MANAGED_MCP_SERVER_KEYS
            and server_key != mcp.server_key
        ):
            flash(
                f"Server key '{server_key}' is system-managed and cannot be edited manually.",
                "error",
            )
            return redirect(url_for("agents.edit_mcp", mcp_id=mcp_id))
        existing = (
            session.execute(
                select(MCPServer).where(
                    MCPServer.server_key == server_key, MCPServer.id != mcp_id
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            flash("Server key is already in use.", "error")
            return redirect(url_for("agents.edit_mcp", mcp_id=mcp_id))
        mcp.name = name
        mcp.server_key = server_key
        mcp.description = description or None
        mcp.config_json = formatted_config

    flash("MCP server updated.", "success")
    return redirect(url_for("agents.view_mcp", mcp_id=mcp_id))


@bp.post("/mcps/<int:mcp_id>/delete")
def delete_mcp(mcp_id: int):
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_mcps")
    )
    with session_scope() as session:
        mcp = session.get(MCPServer, mcp_id)
        if mcp is None:
            abort(404)
        if mcp.is_integrated:
            flash("Integrated MCP servers cannot be deleted.", "error")
            return redirect(next_url)
        attached_templates = list(mcp.task_templates)
        attached_nodes = list(mcp.flowchart_nodes)
        attached_tasks = list(mcp.tasks)
        if attached_templates:
            mcp.task_templates = []
        if attached_nodes:
            mcp.flowchart_nodes = []
        if attached_tasks:
            mcp.tasks = []
        session.delete(mcp)

    flash("MCP server deleted.", "success")
    detached_count = len(attached_templates) + len(attached_nodes) + len(attached_tasks)
    if detached_count:
        flash(f"Detached from {detached_count} binding(s).", "info")
    return redirect(next_url)


@bp.get("/mcps/<int:mcp_id>")
def view_mcp(mcp_id: int):
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    with session_scope() as session:
        mcp_server = (
            session.execute(
                select(MCPServer)
                .options(
                    selectinload(MCPServer.task_templates),
                    selectinload(MCPServer.flowchart_nodes),
                    selectinload(MCPServer.tasks),
                )
                .where(MCPServer.id == mcp_id)
            )
            .scalars()
            .first()
        )
        if mcp_server is None:
            abort(404)
        attached_templates = list(mcp_server.task_templates)
        attached_nodes = list(mcp_server.flowchart_nodes)
        attached_tasks = list(mcp_server.tasks)
        flowchart_ids = {
            node.flowchart_id for node in attached_nodes if node.flowchart_id is not None
        }
        flowcharts_by_id: dict[int, str] = {}
        if flowchart_ids:
            rows = session.execute(
                select(Flowchart.id, Flowchart.name).where(Flowchart.id.in_(flowchart_ids))
            ).all()
            flowcharts_by_id = {row[0]: row[1] for row in rows}
    return render_template(
        "mcp_detail.html",
        mcp_server=mcp_server,
        attached_templates=attached_templates,
        attached_nodes=attached_nodes,
        attached_tasks=attached_tasks,
        flowcharts_by_id=flowcharts_by_id,
        summary=summary,
        human_time=_human_time,
        page_title=mcp_server.name,
        active_page="mcps",
    )


@bp.get("/scripts")
def list_scripts():
    scripts = _load_scripts()
    return render_template(
        "scripts.html",
        scripts=scripts,
        human_time=_human_time,
        page_title="Scripts",
        active_page="scripts",
    )


@bp.get("/skills")
def list_skills():
    skills = _load_skills()
    skill_rows: list[dict[str, object]] = []
    for skill in skills:
        latest_version = _latest_skill_version(skill)
        skill_rows.append(
            {
                "id": skill.id,
                "name": skill.name,
                "display_name": skill.display_name,
                "description": skill.description or "",
                "status": skill.status,
                "source_type": skill.source_type,
                "is_git_read_only": _is_git_based_skill(skill),
                "version_count": len(skill.versions or []),
                "latest_version": latest_version.version if latest_version is not None else None,
                "binding_count": len(skill.agents or []),
                "created_at": skill.created_at,
                "updated_at": skill.updated_at,
            }
        )
    return render_template(
        "skills.html",
        skills=skill_rows,
        human_time=_human_time,
        page_title="Skills",
        active_page="skills",
    )


@bp.get("/skills/new")
def new_skill():
    return render_template(
        "skill_new.html",
        skill_status_options=SKILL_STATUS_OPTIONS,
        upload_conflict_options=["ask", "replace", "keep_both", "skip"],
        max_upload_bytes=SKILL_UPLOAD_MAX_FILE_BYTES,
        page_title="Create Skill",
        active_page="skills",
    )


@bp.post("/skills")
def create_skill():
    name = request.form.get("name", "").strip()
    display_name = request.form.get("display_name", "").strip()
    description = request.form.get("description", "").strip()
    version = request.form.get("version", "").strip()
    status = request.form.get("status", "").strip().lower() or SKILL_STATUS_ACTIVE
    skill_md = request.form.get("skill_md", "")
    source_ref = request.form.get("source_ref", "").strip()
    extra_files_json = request.form.get("extra_files_json", "")

    extra_files, parse_error = _parse_skill_extra_files(extra_files_json)
    if parse_error:
        flash(parse_error, "error")
        return redirect(url_for("agents.new_skill"))
    upload_entries, upload_error = _collect_skill_upload_entries()
    if upload_error:
        flash(upload_error, "error")
        return redirect(url_for("agents.new_skill"))

    if not skill_md.strip():
        skill_md = _default_skill_markdown(
            name=name or "skill",
            display_name=display_name or "Skill",
            description=description or "Describe how and when this skill should be used.",
            version=version or "1.0.0",
            status=status or SKILL_STATUS_ACTIVE,
        )

    draft_file_map: dict[str, str] = {"SKILL.md": skill_md}
    for raw_path, content in extra_files:
        normalized_path = _normalize_skill_relative_path(raw_path)
        if not normalized_path:
            flash("Extra file paths must be relative and path-safe.", "error")
            return redirect(url_for("agents.new_skill"))
        path_error = _skill_upload_path_error(normalized_path)
        if path_error:
            flash(path_error, "error")
            return redirect(url_for("agents.new_skill"))
        if normalized_path in draft_file_map:
            flash(f"Duplicate file path in extra files: {normalized_path}", "error")
            return redirect(url_for("agents.new_skill"))
        draft_file_map[normalized_path] = content
    draft_file_map, conflict_error = _apply_skill_upload_conflicts(draft_file_map, upload_entries)
    if conflict_error:
        flash(conflict_error, "error")
        return redirect(url_for("agents.new_skill"))

    files = list(draft_file_map.items())
    metadata_overrides = {
        "name": name,
        "display_name": display_name,
        "description": description,
        "version": version,
        "status": status,
    }

    try:
        package = build_skill_package(files, metadata_overrides=metadata_overrides)
    except SkillPackageValidationError as exc:
        errors = format_validation_errors(exc.errors)
        message = str(errors[0].get("message") or "Skill package validation failed.")
        flash(message, "error")
        return redirect(url_for("agents.new_skill"))

    try:
        with session_scope() as session:
            result = import_skill_package_to_db(
                session,
                package,
                source_type="ui",
                source_ref=source_ref or "web:create",
                actor=None,
            )
            skill_id = result.skill_id
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("agents.new_skill"))

    flash("Skill created.", "success")
    return redirect(url_for("agents.view_skill", skill_id=skill_id))


@bp.get("/skills/import")
def import_skill():
    return render_template(
        "skill_import.html",
        preview=None,
        validation_errors=[],
        form_values={},
        page_title="Import Skill",
        active_page="skills",
    )


@bp.post("/skills/import")
def import_skill_submit():
    action = (request.form.get("action") or "preview").strip().lower()
    source_kind = (request.form.get("source_kind") or "upload").strip().lower()
    local_path = request.form.get("local_path", "").strip()
    source_ref = request.form.get("source_ref", "").strip()
    actor = request.form.get("actor", "").strip()
    git_url = request.form.get("git_url", "").strip()

    form_values = {
        "source_kind": source_kind,
        "local_path": local_path,
        "source_ref": source_ref,
        "actor": actor,
        "git_url": git_url,
    }

    package: SkillPackage
    try:
        if source_kind == "upload":
            uploaded = request.files.get("bundle_file")
            if uploaded is None or not uploaded.filename:
                flash("Bundle upload is required.", "error")
                return redirect(url_for("agents.import_skill"))
            payload = uploaded.read().decode("utf-8", errors="replace")
            package = load_skill_bundle(payload)
        elif source_kind == "path":
            if not local_path:
                flash("Local path is required.", "error")
                return redirect(url_for("agents.import_skill"))
            package = build_skill_package_from_directory(local_path)
        elif source_kind == "git":
            flash("Git-based skill import is deferred to v1.1.", "error")
            return redirect(url_for("agents.import_skill"))
        else:
            flash("Unknown import source.", "error")
            return redirect(url_for("agents.import_skill"))
    except SkillPackageValidationError as exc:
        return render_template(
            "skill_import.html",
            preview=None,
            validation_errors=format_validation_errors(exc.errors),
            form_values=form_values,
            page_title="Import Skill",
            active_page="skills",
        )

    preview = _build_skill_preview(package)

    if action == "import":
        try:
            with session_scope() as session:
                result = import_skill_package_to_db(
                    session,
                    package,
                    source_type="import",
                    source_ref=source_ref or source_kind,
                    actor=actor or None,
                )
                skill_id = result.skill_id
        except ValueError as exc:
            flash(str(exc), "error")
            return render_template(
                "skill_import.html",
                preview=preview,
                validation_errors=[],
                form_values=form_values,
                page_title="Import Skill",
                active_page="skills",
            )
        flash("Skill imported.", "success")
        return redirect(url_for("agents.view_skill", skill_id=skill_id))

    return render_template(
        "skill_import.html",
        preview=preview,
        validation_errors=[],
        form_values=form_values,
        page_title="Import Skill",
        active_page="skills",
    )


@bp.get("/skills/<int:skill_id>")
def view_skill(skill_id: int):
    requested_version = request.args.get("version", "").strip()
    with session_scope() as session:
        skill = (
            session.execute(
                select(Skill)
                .options(
                    selectinload(Skill.versions).selectinload(SkillVersion.files),
                    selectinload(Skill.agents),
                )
                .where(Skill.id == skill_id)
            )
            .scalars()
            .first()
        )
        if skill is None:
            abort(404)

        versions = sorted(list(skill.versions or []), key=lambda item: item.id or 0, reverse=True)
        selected_version = None
        if requested_version:
            for entry in versions:
                if entry.version == requested_version:
                    selected_version = entry
                    break
        if selected_version is None and versions:
            selected_version = versions[0]

        attached_agents = sorted(
            list(skill.agents or []),
            key=lambda item: (item.name or "").lower(),
        )

    preview = None
    if selected_version is not None:
        preview = {
            "version_id": selected_version.id,
            "version": selected_version.version,
            "manifest_hash": selected_version.manifest_hash or "",
            "manifest": _parse_json_dict(selected_version.manifest_json),
            "files": [
                {
                    "id": entry.id,
                    "path": entry.path,
                    "size_bytes": entry.size_bytes,
                    "checksum": entry.checksum,
                    "is_binary": is_binary_skill_content(entry.content or ""),
                    "content_preview": _skill_file_preview_content(entry.content or ""),
                }
                for entry in sorted(list(selected_version.files or []), key=lambda item: item.path)
            ],
            "skill_md": _skill_file_content(selected_version, "SKILL.md"),
        }

    return render_template(
        "skill_detail.html",
        skill=skill,
        versions=versions,
        selected_version=selected_version,
        preview=preview,
        attached_agents=attached_agents,
        skill_is_git_read_only=_is_git_based_skill(skill),
        human_time=_human_time,
        page_title=f"Skill - {skill.display_name}",
        active_page="skills",
    )


@bp.get("/skills/<int:skill_id>/edit")
def edit_skill(skill_id: int):
    with session_scope() as session:
        skill = (
            session.execute(
                select(Skill)
                .options(selectinload(Skill.versions).selectinload(SkillVersion.files))
                .where(Skill.id == skill_id)
            )
            .scalars()
            .first()
        )
        if skill is None:
            abort(404)
        if _is_git_based_skill(skill):
            flash("Git-based skills are read-only in Studio. Edit the source repo instead.", "info")
            return redirect(url_for("agents.view_skill", skill_id=skill_id))
        latest_version = _latest_skill_version(skill)
        latest_non_skill_files = []
        if latest_version is not None:
            for entry in sorted(list(latest_version.files or []), key=lambda item: item.path):
                if entry.path == "SKILL.md":
                    continue
                latest_non_skill_files.append(
                    {
                        "path": entry.path,
                        "size_bytes": entry.size_bytes,
                        "is_binary": is_binary_skill_content(entry.content or ""),
                    }
                )
    return render_template(
        "skill_edit.html",
        skill=skill,
        latest_version=latest_version,
        latest_skill_md=_skill_file_content(latest_version, "SKILL.md"),
        latest_non_skill_files=latest_non_skill_files,
        skill_status_options=SKILL_STATUS_OPTIONS,
        upload_conflict_options=["ask", "replace", "keep_both", "skip"],
        max_upload_bytes=SKILL_UPLOAD_MAX_FILE_BYTES,
        page_title=f"Edit Skill - {skill.display_name}",
        active_page="skills",
    )


@bp.post("/skills/<int:skill_id>")
def update_skill(skill_id: int):
    display_name = request.form.get("display_name", "").strip()
    description = request.form.get("description", "").strip()
    status = request.form.get("status", "").strip().lower()
    new_version = request.form.get("new_version", "").strip()
    new_skill_md = request.form.get("new_skill_md", "")
    existing_files_json = request.form.get("existing_files_json", "")
    extra_files_json = request.form.get("extra_files_json", "")
    source_ref = request.form.get("source_ref", "").strip()

    if status not in SKILL_STATUS_CHOICES:
        flash("Select a valid skill status.", "error")
        return redirect(url_for("agents.edit_skill", skill_id=skill_id))

    extra_files, parse_error = _parse_skill_extra_files(extra_files_json)
    if parse_error:
        flash(parse_error, "error")
        return redirect(url_for("agents.edit_skill", skill_id=skill_id))
    upload_entries, upload_error = _collect_skill_upload_entries()
    if upload_error:
        flash(upload_error, "error")
        return redirect(url_for("agents.edit_skill", skill_id=skill_id))

    try:
        with session_scope() as session:
            skill = (
                session.execute(
                    select(Skill)
                    .options(selectinload(Skill.versions).selectinload(SkillVersion.files))
                    .where(Skill.id == skill_id)
                )
                .scalars()
                .first()
            )
            if skill is None:
                abort(404)
            if _is_git_based_skill(skill):
                flash("Git-based skills are read-only in Studio. Edit the source repo instead.", "error")
                return redirect(url_for("agents.view_skill", skill_id=skill_id))

            if not display_name:
                flash("Display name is required.", "error")
                return redirect(url_for("agents.edit_skill", skill_id=skill_id))
            if not description:
                flash("Description is required.", "error")
                return redirect(url_for("agents.edit_skill", skill_id=skill_id))

            latest_version = _latest_skill_version(skill)
            latest_skill_md = _skill_file_content(latest_version, "SKILL.md")
            latest_non_skill_map: dict[str, str] = {}
            if latest_version is not None:
                latest_non_skill_map = {
                    str(entry.path): str(entry.content or "")
                    for entry in sorted(list(latest_version.files or []), key=lambda item: item.path)
                    if str(entry.path) != "SKILL.md"
                }
            existing_actions, existing_error = _parse_skill_existing_files_draft(
                existing_files_json,
                existing_paths=set(latest_non_skill_map.keys()),
            )
            if existing_error:
                flash(existing_error, "error")
                return redirect(url_for("agents.edit_skill", skill_id=skill_id))

            draft_non_skill_map: dict[str, str] = {}
            occupied_paths: set[str] = set()
            existing_changed = False
            for action in existing_actions:
                original_path = str(action["original_path"])
                delete_flag = bool(action["delete"])
                if delete_flag:
                    existing_changed = True
                    continue
                target_path = str(action["path"])
                if target_path in occupied_paths:
                    flash(f"Duplicate target path in existing file draft: {target_path}", "error")
                    return redirect(url_for("agents.edit_skill", skill_id=skill_id))
                if target_path != original_path:
                    existing_changed = True
                    rename_path_error = _skill_upload_path_error(target_path)
                    if rename_path_error:
                        flash(rename_path_error, "error")
                        return redirect(url_for("agents.edit_skill", skill_id=skill_id))
                occupied_paths.add(target_path)
                draft_non_skill_map[target_path] = latest_non_skill_map[original_path]

            legacy_extra_changed = False
            for raw_path, content in extra_files:
                normalized_path = _normalize_skill_relative_path(raw_path)
                if not normalized_path:
                    flash("Extra file paths must be relative and path-safe.", "error")
                    return redirect(url_for("agents.edit_skill", skill_id=skill_id))
                path_error = _skill_upload_path_error(normalized_path)
                if path_error:
                    flash(path_error, "error")
                    return redirect(url_for("agents.edit_skill", skill_id=skill_id))
                if normalized_path in draft_non_skill_map:
                    flash(f"Duplicate file path: {normalized_path}", "error")
                    return redirect(url_for("agents.edit_skill", skill_id=skill_id))
                legacy_extra_changed = True
                draft_non_skill_map[normalized_path] = content

            pre_upload_map = dict(draft_non_skill_map)
            draft_non_skill_map, conflict_error = _apply_skill_upload_conflicts(
                draft_non_skill_map,
                upload_entries,
            )
            if conflict_error:
                flash(conflict_error, "error")
                return redirect(url_for("agents.edit_skill", skill_id=skill_id))
            upload_changed = draft_non_skill_map != pre_upload_map

            staged_skill_md = new_skill_md
            if new_version:
                if not staged_skill_md.strip():
                    staged_skill_md = (
                        latest_skill_md
                        or _default_skill_markdown(
                            name=skill.name,
                            display_name=display_name,
                            description=description,
                            version=new_version,
                            status=status,
                        )
                    )
                skill.display_name = display_name
                skill.description = description
                skill.status = status
                skill.updated_by = None
                files = [("SKILL.md", staged_skill_md), *list(draft_non_skill_map.items())]
                package = build_skill_package(
                    files,
                    metadata_overrides={
                        "name": skill.name,
                        "display_name": display_name,
                        "description": description,
                        "version": new_version,
                        "status": status,
                    },
                )
                import_skill_package_to_db(
                    session,
                    package,
                    source_type=(
                        skill.source_type
                        if (skill.source_type or "").strip().lower() in SKILL_MUTABLE_SOURCE_TYPES
                        else "ui"
                    ),
                    source_ref=source_ref or skill.source_ref or f"web:skill:{skill_id}",
                    actor=None,
                )
            else:
                staged_skill_md = staged_skill_md or latest_skill_md
                changed_non_skill_paths = set(draft_non_skill_map.keys()) != set(latest_non_skill_map.keys())
                changed_non_skill_content = any(
                    draft_non_skill_map.get(path) != latest_non_skill_map.get(path)
                    for path in set(draft_non_skill_map.keys()) | set(latest_non_skill_map.keys())
                )
                has_file_changes = (
                    existing_changed
                    or changed_non_skill_paths
                    or changed_non_skill_content
                    or upload_changed
                    or legacy_extra_changed
                    or (staged_skill_md != latest_skill_md)
                )
                if has_file_changes:
                    flash(
                        "New version is required to publish SKILL.md or file changes.",
                        "error",
                    )
                    return redirect(url_for("agents.edit_skill", skill_id=skill_id))
                skill.display_name = display_name
                skill.description = description
                skill.status = status
                skill.updated_by = None
    except SkillPackageValidationError as exc:
        errors = format_validation_errors(exc.errors)
        message = str(errors[0].get("message") or "Skill package validation failed.")
        flash(message, "error")
        return redirect(url_for("agents.edit_skill", skill_id=skill_id))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("agents.edit_skill", skill_id=skill_id))

    flash("Skill updated.", "success")
    return redirect(url_for("agents.view_skill", skill_id=skill_id))


@bp.get("/skills/<int:skill_id>/export")
def export_skill(skill_id: int):
    requested_version = request.args.get("version", "").strip() or None
    with session_scope() as session:
        try:
            package = export_skill_package_from_db(
                session,
                skill_id=skill_id,
                version=requested_version,
            )
        except ValueError:
            abort(404)
    payload = serialize_skill_bundle(package, pretty=True).encode("utf-8")
    file_name = f"{package.metadata.name}-{package.metadata.version}.skill.json"
    return send_file(
        BytesIO(payload),
        mimetype="application/json",
        as_attachment=True,
        download_name=file_name,
    )


@bp.post("/skills/<int:skill_id>/delete")
def delete_skill(skill_id: int):
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_skills")
    )
    with session_scope() as session:
        skill = (
            session.execute(
                select(Skill)
                .options(
                    selectinload(Skill.flowchart_nodes),
                    selectinload(Skill.agents),
                )
                .where(Skill.id == skill_id)
            )
            .scalars()
            .first()
        )
        if skill is None:
            abort(404)
        if _is_git_based_skill(skill):
            flash("Git-based skills are read-only in Studio and cannot be deleted here.", "error")
            return redirect(url_for("agents.view_skill", skill_id=skill_id))
        attached_nodes = list(skill.flowchart_nodes or [])
        attached_agents = list(skill.agents or [])
        if attached_nodes:
            skill.flowchart_nodes = []
        if attached_agents:
            skill.agents = []
        session.delete(skill)

    flash("Skill deleted.", "success")
    if attached_nodes:
        flash(f"Detached from {len(attached_nodes)} flowchart node binding(s).", "info")
    if attached_agents:
        flash(f"Detached from {len(attached_agents)} agent binding(s).", "info")
    return redirect(next_url)


@bp.get("/attachments")
def list_attachments():
    attachments = _load_attachments()
    return render_template(
        "attachments.html",
        attachments=attachments,
        human_time=_human_time,
        format_bytes=_format_bytes,
        page_title="Attachments",
        active_page="attachments",
    )


@bp.get("/attachments/<int:attachment_id>")
def view_attachment(attachment_id: int):
    with session_scope() as session:
        attachment = (
            session.execute(
                select(Attachment)
                .options(
                    selectinload(Attachment.tasks),
                    selectinload(Attachment.templates),
                    selectinload(Attachment.flowchart_nodes),
                )
                .where(Attachment.id == attachment_id)
            )
            .scalars()
            .first()
        )
        if attachment is None:
            abort(404)
        tasks = list(attachment.tasks)
        templates = list(attachment.templates)
        flowchart_nodes = list(attachment.flowchart_nodes)

        tasks.sort(key=lambda item: item.created_at or datetime.min, reverse=True)
        templates.sort(key=lambda item: item.created_at or datetime.min, reverse=True)
        flowchart_nodes.sort(key=lambda item: item.updated_at or datetime.min, reverse=True)

        agent_ids = {task.agent_id for task in tasks if task.agent_id is not None}
        template_ids = {task.task_template_id for task in tasks if task.task_template_id}
        flowchart_ids = {
            int(node.flowchart_id)
            for node in flowchart_nodes
            if node.flowchart_id is not None
        }

        agents_by_id: dict[int, str] = {}
        if agent_ids:
            rows = session.execute(
                select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids))
            ).all()
            agents_by_id = {row[0]: row[1] for row in rows}

        templates_by_id: dict[int, str] = {}
        if template_ids:
            rows = session.execute(
                select(TaskTemplate.id, TaskTemplate.name).where(
                    TaskTemplate.id.in_(template_ids)
                )
            ).all()
            templates_by_id = {row[0]: row[1] for row in rows}

        flowcharts_by_id: dict[int, str] = {}
        if flowchart_ids:
            rows = session.execute(
                select(Flowchart.id, Flowchart.name).where(
                    Flowchart.id.in_(flowchart_ids)
                )
            ).all()
            flowcharts_by_id = {row[0]: row[1] for row in rows}

    is_image_attachment = _is_image_attachment(attachment)
    attachment_preview_url = None
    if is_image_attachment and attachment.file_path:
        attachment_preview_url = url_for(
            "agents.view_attachment_file", attachment_id=attachment.id
        )

    return render_template(
        "attachment_detail.html",
        attachment=attachment,
        attachment_preview_url=attachment_preview_url,
        is_image_attachment=is_image_attachment,
        tasks=tasks,
        templates=templates,
        flowchart_nodes=flowchart_nodes,
        agents_by_id=agents_by_id,
        templates_by_id=templates_by_id,
        flowcharts_by_id=flowcharts_by_id,
        human_time=_human_time,
        format_bytes=_format_bytes,
        page_title=f"Attachment - {attachment.file_name}",
        active_page="attachments",
    )


@bp.get("/attachments/<int:attachment_id>/file")
def view_attachment_file(attachment_id: int):
    with session_scope() as session:
        attachment = session.get(Attachment, attachment_id)
        if attachment is None or not attachment.file_path:
            abort(404)
        file_path = Path(attachment.file_path)
        content_type = attachment.content_type
        file_name = attachment.file_name

    if not file_path.exists():
        abort(404)
    try:
        attachments_root = Path(Config.ATTACHMENTS_DIR).resolve()
        resolved_path = file_path.resolve()
    except OSError:
        abort(404)
    if resolved_path != attachments_root and attachments_root not in resolved_path.parents:
        abort(404)

    return send_file(
        resolved_path,
        mimetype=content_type or None,
        as_attachment=False,
        download_name=file_name,
        conditional=True,
    )


@bp.post("/attachments/<int:attachment_id>/delete")
def delete_attachment(attachment_id: int):
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_attachments")
    )
    removed_path: str | None = None
    with session_scope() as session:
        attachment = session.get(Attachment, attachment_id)
        if attachment is None:
            abort(404)
        removed_path = attachment.file_path
        _unlink_attachment(session, attachment.id)
        session.delete(attachment)
    if removed_path:
        remove_attachment_file(removed_path)
    flash("Attachment deleted.", "success")
    return redirect(next_url)


@bp.get("/memories")
def list_memories():
    page = _parse_page(request.args.get("page"))
    per_page = WORKFLOW_LIST_PER_PAGE
    with session_scope() as session:
        total_count = session.execute(select(func.count(Memory.id))).scalar_one()
        pagination = _build_pagination(request.path, page, per_page, total_count)
        offset = (pagination["page"] - 1) * per_page
        memories = (
            session.execute(
                select(Memory)
                .order_by(Memory.created_at.desc())
                .limit(per_page)
                .offset(offset)
            )
            .scalars()
            .all()
        )
    return render_template(
        "memories.html",
        memories=memories,
        pagination=pagination,
        human_time=_human_time,
        fixed_list_page=True,
        page_title="Memories",
        active_page="memories",
    )


@bp.get("/memories/new")
def new_memory():
    flash("Create memories by adding Memory nodes in a flowchart.", "error")
    return redirect(url_for("agents.list_flowcharts"))


@bp.post("/memories")
def create_memory():
    flash("Create memories by adding Memory nodes in a flowchart.", "error")
    return redirect(url_for("agents.list_flowcharts"))


@bp.get("/memories/<int:memory_id>")
def view_memory(memory_id: int):
    with session_scope() as session:
        memory = session.get(Memory, memory_id)
        if memory is None:
            abort(404)
    return render_template(
        "memory_detail.html",
        memory=memory,
        human_time=_human_time,
        page_title="Memory",
        active_page="memories",
    )


@bp.get("/memories/<int:memory_id>/edit")
def edit_memory(memory_id: int):
    with session_scope() as session:
        memory = session.get(Memory, memory_id)
        if memory is None:
            abort(404)
    return render_template(
        "memory_edit.html",
        memory=memory,
        page_title="Edit Memory",
        active_page="memories",
    )


@bp.post("/memories/<int:memory_id>")
def update_memory(memory_id: int):
    description = request.form.get("description", "").strip()
    if not description:
        flash("Description is required.", "error")
        return redirect(url_for("agents.edit_memory", memory_id=memory_id))

    with session_scope() as session:
        memory = session.get(Memory, memory_id)
        if memory is None:
            abort(404)
        memory.description = description

    flash("Memory updated.", "success")
    return redirect(url_for("agents.view_memory", memory_id=memory_id))


@bp.post("/memories/<int:memory_id>/delete")
def delete_memory(memory_id: int):
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_memories")
    )
    with session_scope() as session:
        memory = session.get(Memory, memory_id)
        if memory is None:
            abort(404)
        session.delete(memory)

    flash("Memory deleted.", "success")
    return redirect(next_url)


@bp.get("/scripts/new")
def new_script():
    return render_template(
        "script_new.html",
        script_types=SCRIPT_TYPE_WRITE_CHOICES,
        page_title="Create Script",
        active_page="scripts",
    )


@bp.post("/scripts")
def create_script():
    file_name = request.form.get("file_name", "").strip()
    description = request.form.get("description", "").strip()
    script_type = request.form.get("script_type", "").strip()
    content = request.form.get("content", "")
    uploaded_file = request.files.get("script_file")

    if uploaded_file and uploaded_file.filename:
        file_name = file_name or uploaded_file.filename
        content_bytes = uploaded_file.read()
        content = content_bytes.decode("utf-8", errors="replace")

    file_name = Path(file_name).name if file_name else ""
    if not file_name or file_name in {".", ".."}:
        flash("File name is required.", "error")
        return redirect(url_for("agents.new_script"))
    if script_type not in SCRIPT_TYPE_LABELS:
        flash("Select a valid script type.", "error")
        return redirect(url_for("agents.new_script"))
    try:
        ensure_legacy_skill_script_writable(script_type)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("agents.new_script"))
    if not content or not content.strip():
        flash("Script content is required.", "error")
        return redirect(url_for("agents.new_script"))

    try:
        with session_scope() as session:
            script = Script.create(
                session,
                file_name=file_name,
                description=description or None,
                content=content,
                script_type=script_type,
            )
            path = write_script_file(script.id, file_name, content)
            script.file_path = str(path)
    except OSError:
        logger.exception("Failed to write script %s to disk", file_name)
        flash("Failed to write the script file.", "error")
        return redirect(url_for("agents.new_script"))

    flash(f"Script {script.id} created.", "success")
    return redirect(url_for("agents.view_script", script_id=script.id))


@bp.get("/scripts/<int:script_id>")
def view_script(script_id: int):
    with session_scope() as session:
        script = (
            session.execute(
                select(Script)
                .options(
                    selectinload(Script.tasks),
                    selectinload(Script.task_templates),
                    selectinload(Script.flowchart_nodes),
                )
                .where(Script.id == script_id)
            )
            .scalars()
            .first()
        )
        if script is None:
            abort(404)
        attached_tasks = list(script.tasks)
        attached_templates = list(script.task_templates)
        attached_nodes = list(script.flowchart_nodes)
        flowchart_ids = {
            node.flowchart_id for node in attached_nodes if node.flowchart_id is not None
        }
        flowcharts_by_id: dict[int, str] = {}
        if flowchart_ids:
            rows = session.execute(
                select(Flowchart.id, Flowchart.name).where(Flowchart.id.in_(flowchart_ids))
            ).all()
            flowcharts_by_id = {row[0]: row[1] for row in rows}
        script_content = _read_script_content(script)
    return render_template(
        "script_detail.html",
        script=script,
        script_content=script_content,
        attached_tasks=attached_tasks,
        attached_templates=attached_templates,
        attached_nodes=attached_nodes,
        flowcharts_by_id=flowcharts_by_id,
        human_time=_human_time,
        page_title=f"Script - {script.file_name}",
        active_page="scripts",
    )


@bp.get("/scripts/<int:script_id>/edit")
def edit_script(script_id: int):
    with session_scope() as session:
        script = session.get(Script, script_id)
        if script is None:
            abort(404)
        script_content = _read_script_content(script)
    return render_template(
        "script_edit.html",
        script=script,
        script_content=script_content,
        script_types=SCRIPT_TYPE_WRITE_CHOICES,
        page_title=f"Edit Script - {script.file_name}",
        active_page="scripts",
    )


@bp.post("/scripts/<int:script_id>")
def update_script(script_id: int):
    file_name = request.form.get("file_name", "").strip()
    description = request.form.get("description", "").strip()
    script_type = request.form.get("script_type", "").strip()
    content = request.form.get("content", "")
    uploaded_file = request.files.get("script_file")

    if uploaded_file and uploaded_file.filename:
        file_name = file_name or uploaded_file.filename
        content_bytes = uploaded_file.read()
        content = content_bytes.decode("utf-8", errors="replace")

    try:
        with session_scope() as session:
            script = session.get(Script, script_id)
            if script is None:
                abort(404)
            if not file_name:
                file_name = script.file_name
            file_name = Path(file_name).name if file_name else ""
            if not file_name or file_name in {".", ".."}:
                flash("File name is required.", "error")
                return redirect(url_for("agents.edit_script", script_id=script_id))
            if script_type not in SCRIPT_TYPE_LABELS:
                flash("Select a valid script type.", "error")
                return redirect(url_for("agents.edit_script", script_id=script_id))
            try:
                ensure_legacy_skill_script_writable(script_type)
            except ValueError as exc:
                flash(str(exc), "error")
                return redirect(url_for("agents.edit_script", script_id=script_id))
            if not content or not content.strip():
                flash("Script content is required.", "error")
                return redirect(url_for("agents.edit_script", script_id=script_id))
            old_path = script.file_path
            script.file_name = file_name
            script.description = description or None
            script.content = content
            script.script_type = script_type
            path = write_script_file(script.id, file_name, content)
            script.file_path = str(path)
            if old_path and old_path != script.file_path:
                remove_script_file(old_path)
    except OSError:
        logger.exception("Failed to write script %s to disk", script_id)
        flash("Failed to write the script file.", "error")
        return redirect(url_for("agents.edit_script", script_id=script_id))

    flash("Script updated.", "success")
    return redirect(url_for("agents.view_script", script_id=script_id))


@bp.post("/scripts/<int:script_id>/delete")
def delete_script(script_id: int):
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_scripts")
    )
    with session_scope() as session:
        script = session.get(Script, script_id)
        if script is None:
            abort(404)
        script_path = script.file_path
        attached_tasks = list(script.tasks)
        attached_templates = list(script.task_templates)
        attached_nodes = list(script.flowchart_nodes)
        if attached_tasks:
            script.tasks = []
        if attached_templates:
            script.task_templates = []
        if attached_nodes:
            script.flowchart_nodes = []
        session.delete(script)

    flash("Script deleted.", "success")
    detached_count = len(attached_tasks) + len(attached_templates) + len(attached_nodes)
    if detached_count:
        flash(f"Detached from {detached_count} binding(s).", "info")
    remove_script_file(script_path)
    return redirect(next_url)


@bp.get("/github")
def github_workspace():
    settings = _load_integration_settings("github")
    repo = settings.get("repo") or "No repository selected"
    pat = settings.get("pat") or ""
    tab = request.args.get("tab", "pulls").strip().lower()
    if tab not in {"pulls", "actions", "code"}:
        tab = "pulls"
    pr_status = request.args.get("pr_status", "open").strip().lower()
    if pr_status not in {"all", "open", "closed", "merged", "draft"}:
        pr_status = "open"
    pr_author_raw = (request.args.get("pr_author") or "all").strip()
    pr_author = "all"
    code_path = request.args.get("path", "").strip().lstrip("/")
    pull_requests: list[dict[str, object]] = []
    pr_error = None
    pr_authors: list[str] = []
    actions: list[dict[str, str]] = []
    actions_error = None
    code_entries: list[dict[str, str]] = []
    code_file = None
    code_error = None
    code_parent = ""
    code_selected_path = ""
    if pat and settings.get("repo"):
        repo_name = settings.get("repo", "")
        try:
            pull_requests = _fetch_github_pull_requests(pat, repo_name, pr_status)
        except ValueError as exc:
            pr_error = str(exc)
        if pull_requests:
            authors = {
                pr.get("author") for pr in pull_requests if pr.get("author")
            }
            pr_authors = sorted(authors, key=lambda value: value.lower())
            if pr_author_raw and pr_author_raw.lower() != "all":
                selected_author = None
                for author in pr_authors:
                    if author.lower() == pr_author_raw.lower():
                        selected_author = author
                        break
                if selected_author:
                    pull_requests = [
                        pr
                        for pr in pull_requests
                        if (pr.get("author") or "").lower()
                        == selected_author.lower()
                    ]
                    pr_author = selected_author
        try:
            actions = _fetch_github_actions(pat, repo_name)
        except ValueError as exc:
            actions_error = str(exc)
        try:
            contents = _fetch_github_contents(pat, repo_name, code_path)
            code_entries = contents.get("entries", [])
            code_file = contents.get("file")
            if code_path:
                code_parent = "/".join(code_path.split("/")[:-1])
            if isinstance(code_file, dict):
                code_selected_path = code_file.get("path", "")
            if code_file and code_path:
                try:
                    parent_contents = _fetch_github_contents(pat, repo_name, code_parent)
                    code_entries = parent_contents.get("entries", [])
                except ValueError:
                    pass
        except ValueError as exc:
            code_error = str(exc)
    return render_template(
        "github.html",
        github_repo=repo,
        github_repo_selected=bool(settings.get("repo")),
        github_connected=bool(settings.get("pat")),
        github_pull_requests=pull_requests,
        github_pr_error=pr_error,
        github_pr_status=pr_status,
        github_pr_author=pr_author,
        github_pr_authors=pr_authors,
        github_actions=actions,
        github_actions_error=actions_error,
        github_code_entries=code_entries,
        github_code_file=code_file,
        github_code_error=code_error,
        github_code_path=code_path,
        github_code_parent=code_parent,
        github_code_selected_path=code_selected_path,
        github_active_tab=tab,
        page_title="GitHub",
        active_page="github",
    )


def _render_github_pull_request_page(pr_number: int, active_tab: str):
    settings = _load_integration_settings("github")
    repo = settings.get("repo") or ""
    pat = settings.get("pat") or ""
    if not repo or not pat:
        flash(
            "GitHub repository and PAT are required to view pull requests.",
            "error",
        )
        return redirect(url_for("agents.github_workspace", tab="pulls"))
    tab_labels = {
        "conversation": "Conversation",
        "commits": "Commits",
        "checks": "Checks",
        "files": "Files changed",
    }
    selected_tab = active_tab if active_tab in tab_labels else "conversation"
    pr_error = None
    comments_error = None
    pull_request: dict[str, object] = {}
    comments: list[dict[str, object]] = []
    reviewers: list[str] = []
    try:
        pull_request = _fetch_github_pull_request_detail(pat, repo, pr_number)
    except ValueError as exc:
        pr_error = str(exc)
    if pull_request:
        try:
            comments, reviewer_logins = _fetch_github_pull_request_timeline(
                pat, repo, pr_number
            )
            reviewers = sorted(
                set(pull_request.get("requested_reviewers", []))
                | set(reviewer_logins)
            )
        except ValueError as exc:
            comments_error = str(exc)
            reviewers = pull_request.get("requested_reviewers", [])
    base_title = (
        f"PR #{pr_number} - {pull_request.get('title')}"
        if pull_request.get("title")
        else f"PR #{pr_number}"
    )
    page_title = f"{base_title} - {tab_labels[selected_tab]}"
    return render_template(
        "github_pull_request.html",
        github_repo=repo or "No repository selected",
        github_connected=bool(pat),
        github_pr=pull_request,
        github_pr_number=pr_number,
        github_pr_comments=comments,
        github_pr_reviewers=reviewers,
        github_pr_active_tab=selected_tab,
        github_pr_error=pr_error,
        github_pr_comments_error=comments_error,
        page_title=page_title,
        active_page="github",
    )


@bp.get("/github/pulls/<int:pr_number>")
def github_pull_request(pr_number: int):
    return _render_github_pull_request_page(pr_number, "conversation")


@bp.get("/github/pulls/<int:pr_number>/commits")
def github_pull_request_commits(pr_number: int):
    return _render_github_pull_request_page(pr_number, "commits")


@bp.get("/github/pulls/<int:pr_number>/checks")
def github_pull_request_checks(pr_number: int):
    return _render_github_pull_request_page(pr_number, "checks")


@bp.get("/github/pulls/<int:pr_number>/files")
def github_pull_request_files(pr_number: int):
    return _render_github_pull_request_page(pr_number, "files")


@bp.post("/github/pulls/<int:pr_number>/code-review")
def github_pull_request_code_review(pr_number: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"),
        url_for("agents.github_pull_request", pr_number=pr_number),
    )
    settings = _load_integration_settings("github")
    repo = settings.get("repo") or ""
    pat = settings.get("pat") or ""
    if not repo or not pat:
        flash(
            "GitHub repository and PAT are required to run code reviews.",
            "error",
        )
        return redirect(redirect_target)

    pr_title = request.form.get("pr_title", "").strip() or None
    pr_url = request.form.get("pr_url", "").strip() or None
    if not pr_url and repo:
        pr_url = f"https://github.com/{repo}/pull/{pr_number}"

    with session_scope() as session:
        role = ensure_code_reviewer_role(session)
        agent = ensure_code_reviewer_agent(session, role)
        prompt = _build_github_code_review_prompt(
            repo=repo,
            pr_number=pr_number,
            pr_title=pr_title,
            pr_url=pr_url,
            role_prompt=role.description if role is not None else None,
        )
        task = AgentTask.create(
            session,
            agent_id=agent.id,
            status="queued",
            prompt=prompt,
            kind=CODE_REVIEW_TASK_KIND,
        )
        task_id = task.id

    celery_task = run_agent_task.delay(task_id)

    with session_scope() as session:
        task = session.get(AgentTask, task_id)
        if task is not None:
            task.celery_task_id = celery_task.id

    flash(f"Code review node {task_id} queued.", "success")
    return redirect(url_for("agents.view_node", task_id=task_id))


@bp.get("/jira")
def jira_workspace():
    settings = _load_integration_settings("jira")
    board = settings.get("board") or "No board selected"
    site = settings.get("site") or "No site configured"
    api_key = settings.get("api_key") or ""
    email = settings.get("email") or ""
    board_columns: list[dict[str, object]] = []
    board_unmapped: list[dict[str, object]] = []
    board_error: str | None = None
    board_issue_total: int | None = None
    board_type: str | None = None
    board_url: str | None = None
    board_column_count = 0
    if api_key and settings.get("board") and settings.get("site"):
        auth_key = _combine_atlassian_key(api_key, email)
        if ":" not in auth_key:
            board_error = (
                "Jira API key needs an Atlassian email. Enter it in settings."
            )
        else:
            try:
                board_info = _fetch_jira_board_by_name(
                    auth_key, settings.get("site") or "", settings.get("board") or ""
                )
                if not board_info:
                    board_error = (
                        "Selected Jira board not found. Refresh boards in settings."
                    )
                else:
                    board_id = board_info.get("id")
                    if isinstance(board_id, str) and board_id.isdigit():
                        board_id = int(board_id)
                    if isinstance(board_id, int):
                        board_type = board_info.get("type") or None
                        location = board_info.get("location", {})
                        if isinstance(location, dict):
                            project_key = location.get("projectKey")
                            base = _normalize_atlassian_site(settings.get("site") or "")
                            if (
                                isinstance(project_key, str)
                                and project_key
                                and base
                            ):
                                board_url = (
                                    f"{base}/jira/software/c/projects/"
                                    f"{project_key}/boards/{board_id}"
                                )
                        board_config = _fetch_jira_board_configuration(
                            auth_key, settings.get("site") or "", board_id
                        )
                        issues = _fetch_jira_board_issues(
                            auth_key, settings.get("site") or "", board_id
                        )
                        board_issue_total = len(issues)
                        board_columns, board_unmapped = _build_jira_board_columns(
                            board_config, issues
                        )
                        board_column_count = len(board_columns) + (
                            1 if board_unmapped else 0
                        )
                        if not board_columns:
                            board_error = "No columns returned for this board."
                    else:
                        board_error = "Selected Jira board is missing an id."
            except ValueError as exc:
                board_error = str(exc)
    return render_template(
        "jira.html",
        jira_board=board,
        jira_site=site,
        jira_board_selected=bool(settings.get("board")),
        jira_connected=bool(settings.get("api_key")),
        jira_board_columns=board_columns,
        jira_board_unmapped=board_unmapped,
        jira_board_error=board_error,
        jira_board_issue_total=board_issue_total,
        jira_board_type=board_type,
        jira_board_url=board_url,
        jira_board_column_count=board_column_count,
        page_title="Jira",
        active_page="jira",
    )


@bp.get("/jira/issues/<issue_key>")
def jira_issue_detail(issue_key: str):
    settings = _load_integration_settings("jira")
    board = settings.get("board") or "No board selected"
    site = settings.get("site") or "No site configured"
    api_key = settings.get("api_key") or ""
    email = settings.get("email") or ""
    issue: dict[str, object] = {"key": issue_key, "summary": "Jira issue"}
    issue_error: str | None = None
    comments_error: str | None = None
    comments: list[dict[str, object]] = []
    if not api_key or not settings.get("site"):
        issue_error = "Jira API key and site URL are required to load issues."
    else:
        auth_key = _combine_atlassian_key(api_key, email)
        if ":" not in auth_key:
            issue_error = (
                "Jira API key needs an Atlassian email. Enter it in settings."
            )
        else:
            try:
                fetched_issue = _fetch_jira_issue(
                    auth_key, settings.get("site") or "", issue_key
                )
                if not fetched_issue:
                    issue_error = "Issue not found or access denied."
                else:
                    issue = fetched_issue
                    try:
                        comments = _fetch_jira_issue_comments(
                            auth_key, settings.get("site") or "", issue_key
                        )
                    except ValueError as exc:
                        comments_error = str(exc)
            except ValueError as exc:
                issue_error = str(exc)
    page_title = (
        f"{issue.get('key')} - {issue.get('summary')}"
        if issue
        else f"{issue_key} - Jira"
    )
    return render_template(
        "jira_issue.html",
        jira_board=board,
        jira_site=site,
        jira_issue=issue,
        jira_issue_error=issue_error,
        jira_comments=comments,
        jira_comments_error=comments_error,
        page_title=page_title,
        active_page="jira",
    )


@bp.get("/confluence")
def confluence_workspace():
    settings = _load_integration_settings("confluence")
    selected_space = (settings.get("space") or "").strip()
    selected_space_name = selected_space or "No space selected"
    for option in _confluence_space_options(settings):
        option_value = (option.get("value") or "").strip()
        if option_value != selected_space:
            continue
        option_label = (option.get("label") or "").strip()
        if " - " in option_label:
            selected_space_name = option_label.split(" - ", 1)[1].strip() or option_label
        elif option_label:
            selected_space_name = option_label
        break
    site = settings.get("site") or "No site configured"
    api_key = settings.get("api_key") or ""
    email = settings.get("email") or ""
    pages: list[dict[str, object]] = []
    page: dict[str, object] | None = None
    selected_page_id = request.args.get("page", "").strip()
    confluence_error: str | None = None
    if not selected_space:
        confluence_error = "Set a Confluence space in Integrations to load pages."
    if api_key and settings.get("site") and selected_space:
        auth_key = _combine_atlassian_key(api_key, email)
        if ":" not in auth_key:
            confluence_error = (
                "Confluence API key needs an Atlassian email. Enter it in settings."
            )
        else:
            try:
                pages = _fetch_confluence_pages(
                    auth_key,
                    settings.get("site") or "",
                    selected_space,
                )
                if pages:
                    page_id = selected_page_id or pages[0].get("id", "")
                    if page_id:
                        page = _fetch_confluence_page(
                            auth_key,
                            settings.get("site") or "",
                            page_id,
                        )
                elif selected_page_id:
                    page = _fetch_confluence_page(
                        auth_key,
                        settings.get("site") or "",
                        selected_page_id,
                    )
            except ValueError as exc:
                confluence_error = str(exc)
    return render_template(
        "confluence.html",
        confluence_space=selected_space or "No space selected",
        confluence_space_name=selected_space_name,
        confluence_space_key=selected_space,
        confluence_pages=pages,
        confluence_selected_page=page,
        confluence_page_id=selected_page_id or (page.get("id") if page else ""),
        confluence_error=confluence_error,
        confluence_site=site,
        confluence_space_selected=bool(selected_space),
        confluence_connected=bool(settings.get("api_key")),
        page_title="Confluence",
        active_page="confluence",
    )


@bp.get("/chroma")
def chroma_workspace():
    return redirect(url_for("agents.chroma_collections"))


@bp.get("/chroma/collections")
def chroma_collections():
    chroma_settings = _resolved_chroma_settings()
    if not _chroma_connected(chroma_settings):
        flash("Configure ChromaDB host and port in Integrations first.", "error")
        return redirect(url_for("agents.settings_integrations_chroma"))

    client, host, port, normalized_hint, error = _chroma_http_client(chroma_settings)
    collections: list[dict[str, object]] = []
    chroma_error: str | None = None
    if error or client is None:
        chroma_error = (
            f"Failed to connect to Chroma at {_chroma_endpoint_label(host, port)}: {error}"
        )
    else:
        try:
            collection_names = _list_collection_names(client.list_collections())
            for collection_name in collection_names:
                count: int | None = None
                metadata: dict[str, object] = {}
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
                        "count": count,
                        "metadata_preview": (
                            json.dumps(metadata, sort_keys=True) if metadata else "{}"
                        ),
                    }
                )
        except Exception as exc:
            chroma_error = f"Failed to load collections: {exc}"

    page = _parse_page(request.args.get("page"))
    per_page = _parse_page_size(request.args.get("per_page"))
    total_collections = len(collections)
    total_pages = (
        max(1, (total_collections + per_page - 1) // per_page)
        if total_collections
        else 1
    )
    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page
    paged_collections = collections[offset : offset + per_page]
    pagination_items = _build_pagination_items(page, total_pages)

    return render_template(
        "chroma_collections.html",
        collections=paged_collections,
        chroma_error=chroma_error,
        chroma_host=host,
        chroma_port=port,
        chroma_ssl="enabled" if _as_bool(chroma_settings.get("ssl")) else "disabled",
        chroma_normalized_hint=normalized_hint,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        per_page_options=PAGINATION_PAGE_SIZES,
        total_collections=total_collections,
        pagination_items=pagination_items,
        page_title="ChromaDB Collections",
        active_page="chroma",
    )


@bp.get("/chroma/collections/detail")
def chroma_collection_detail():
    collection_name = (request.args.get("name") or "").strip()
    if not collection_name:
        flash("Collection name is required.", "error")
        return redirect(url_for("agents.chroma_collections"))

    chroma_settings = _resolved_chroma_settings()
    if not _chroma_connected(chroma_settings):
        flash("Configure ChromaDB host and port in Integrations first.", "error")
        return redirect(url_for("agents.settings_integrations_chroma"))

    client, host, port, normalized_hint, error = _chroma_http_client(chroma_settings)
    if error or client is None:
        flash(
            f"Failed to connect to Chroma at {_chroma_endpoint_label(host, port)}: {error}",
            "error",
        )
        return redirect(url_for("agents.chroma_collections"))

    try:
        collection = client.get_collection(name=collection_name)
        count = collection.count()
        raw_metadata = getattr(collection, "metadata", None)
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    except Exception as exc:
        flash(f"Failed to load collection '{collection_name}': {exc}", "error")
        return redirect(url_for("agents.chroma_collections"))

    return render_template(
        "chroma_collection_detail.html",
        collection_name=collection_name,
        collection_count=count,
        collection_metadata=metadata,
        collection_metadata_json=json.dumps(metadata, sort_keys=True, indent=2)
        if metadata
        else "{}",
        chroma_host=host,
        chroma_port=port,
        chroma_ssl="enabled" if _as_bool(chroma_settings.get("ssl")) else "disabled",
        chroma_normalized_hint=normalized_hint,
        page_title=f"ChromaDB - {collection_name}",
        active_page="chroma",
    )


@bp.post("/chroma/collections/delete")
def delete_chroma_collection():
    collection_name = request.form.get("collection_name", "").strip()
    next_page = request.form.get("next", "").strip().lower()
    if not collection_name:
        flash("Collection name is required.", "error")
        return redirect(url_for("agents.chroma_collections"))

    chroma_settings = _resolved_chroma_settings()
    if not _chroma_connected(chroma_settings):
        flash("Configure ChromaDB host and port in Integrations first.", "error")
        return redirect(url_for("agents.settings_integrations_chroma"))

    client, host, port, _, error = _chroma_http_client(chroma_settings)
    if error or client is None:
        flash(
            f"Failed to connect to Chroma at {_chroma_endpoint_label(host, port)}: {error}",
            "error",
        )
        if next_page == "detail":
            return redirect(
                url_for("agents.chroma_collection_detail", name=collection_name)
            )
        return redirect(url_for("agents.chroma_collections"))

    try:
        client.delete_collection(name=collection_name)
    except Exception as exc:
        flash(f"Failed to delete collection '{collection_name}': {exc}", "error")
        if next_page == "detail":
            return redirect(
                url_for("agents.chroma_collection_detail", name=collection_name)
            )
        return redirect(url_for("agents.chroma_collections"))

    flash("Collection deleted.", "success")
    return redirect(url_for("agents.chroma_collections"))


@bp.post("/task-templates")
def create_task_template():
    flash("Create tasks by adding Task nodes in a flowchart.", "error")
    return redirect(url_for("agents.list_flowcharts"))


@bp.post("/task-templates/<int:template_id>")
def update_task_template(template_id: int):
    name = request.form.get("name", "").strip()
    prompt = request.form.get("prompt", "").strip()
    description = request.form.get("description", "").strip()
    agent_id_raw = request.form.get("agent_id", "").strip()
    uploads = request.files.getlist("attachments")
    agent_id: int | None = None
    if agent_id_raw:
        if not agent_id_raw.isdigit():
            flash("Select a valid agent.", "error")
            return redirect(url_for("agents.edit_task_template", template_id=template_id))
        agent_id = int(agent_id_raw)
    if not name or not prompt:
        flash("Template name and prompt are required.", "error")
        return redirect(url_for("agents.edit_task_template", template_id=template_id))
    try:
        with session_scope() as session:
            template = session.get(TaskTemplate, template_id)
            if template is None:
                abort(404)
            if agent_id is not None:
                agent = session.get(Agent, agent_id)
                if agent is None:
                    flash("Agent not found.", "error")
                    return redirect(
                        url_for("agents.edit_task_template", template_id=template_id)
                    )
            template.name = name
            template.prompt = prompt
            template.description = description or None
            template.agent_id = agent_id
            attachments = _save_uploaded_attachments(session, uploads)
            _attach_attachments(template, attachments)
    except (OSError, ValueError) as exc:
        logger.exception("Failed to save template attachments")
        flash(str(exc) or "Failed to save attachments.", "error")
        return redirect(url_for("agents.edit_task_template", template_id=template_id))
    flash("Template updated.", "success")
    return redirect(url_for("agents.view_task_template", template_id=template_id))


@bp.post("/task-templates/<int:template_id>/attachments/<int:attachment_id>/remove")
def remove_task_template_attachment(template_id: int, attachment_id: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"),
        url_for("agents.edit_task_template", template_id=template_id),
    )
    removed_path: str | None = None
    with session_scope() as session:
        template = (
            session.execute(
                select(TaskTemplate)
                .options(selectinload(TaskTemplate.attachments))
                .where(TaskTemplate.id == template_id)
            )
            .scalars()
            .first()
        )
        if template is None:
            abort(404)
        attachment = next(
            (item for item in template.attachments if item.id == attachment_id), None
        )
        if attachment is None:
            flash("Attachment not found on this template.", "error")
            return redirect(redirect_target)
        template.attachments.remove(attachment)
        session.flush()
        removed_path = _delete_attachment_if_unused(session, attachment)
    if removed_path:
        remove_attachment_file(removed_path)
    flash("Attachment removed.", "success")
    return redirect(redirect_target)


@bp.post("/task-templates/<int:template_id>/delete")
def delete_task_template(template_id: int):
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_task_templates")
    )
    with session_scope() as session:
        template = session.get(TaskTemplate, template_id)
        if template is None:
            abort(404)
        tasks_with_template = (
            session.execute(
                select(AgentTask).where(AgentTask.task_template_id == template_id)
            )
            .scalars()
            .all()
        )
        for task in tasks_with_template:
            task.task_template_id = None
        session.delete(template)
    flash("Template deleted.", "success")
    return redirect(next_url)


@bp.get("/settings")
def settings():
    summary = _settings_summary()
    integration_overview = _integration_overview()
    llm_settings = _load_integration_settings("llm")
    enabled_providers = resolve_enabled_llm_providers(llm_settings)
    provider_overview = _provider_summary(
        settings=llm_settings, enabled_providers=enabled_providers
    )
    default_model_summary = _default_model_overview(llm_settings)
    gitconfig_path = _gitconfig_path()
    gitconfig_overview = {
        "path": str(gitconfig_path),
        "exists": gitconfig_path.exists(),
    }
    core_overview = {
        "DATA_DIR": Config.DATA_DIR,
        "DATABASE_FILENAME": Config.DATABASE_FILENAME,
        "CODEX_MODEL": Config.CODEX_MODEL or "default",
        "VLLM_LOCAL_CMD": Config.VLLM_LOCAL_CMD,
        "VLLM_LOCAL_CUSTOM_MODELS_DIR": Config.VLLM_LOCAL_CUSTOM_MODELS_DIR,
        "VLLM_REMOTE_BASE_URL": Config.VLLM_REMOTE_BASE_URL or "not set",
    }
    celery_overview = {
        "CELERY_BROKER_URL": Config.CELERY_BROKER_URL,
        "CELERY_RESULT_BACKEND": Config.CELERY_RESULT_BACKEND,
    }
    runtime_overview = {
        "AGENT_POLL_SECONDS": Config.AGENT_POLL_SECONDS,
        "CELERY_REVOKE_ON_STOP": (
            "enabled" if Config.CELERY_REVOKE_ON_STOP else "disabled"
        ),
    }
    return render_template(
        "settings.html",
        core_overview=core_overview,
        celery_overview=celery_overview,
        runtime_overview=runtime_overview,
        integration_overview=integration_overview,
        provider_overview=provider_overview,
        default_model_summary=default_model_summary,
        gitconfig_overview=gitconfig_overview,
        summary=summary,
        page_title="Settings",
        active_page="settings_overview",
    )


@bp.get("/settings/roles")
@bp.get("/roles")
def list_roles():
    page = _parse_page(request.args.get("page"))
    per_page = _parse_page_size(request.args.get("per_page"))
    with session_scope() as session:
        total_count = session.execute(select(func.count(Role.id))).scalar_one()
        pagination = _build_pagination(request.path, page, per_page, total_count)
        offset = (pagination["page"] - 1) * per_page
        roles = (
            session.execute(
                select(Role)
                .order_by(Role.created_at.desc())
                .limit(per_page)
                .offset(offset)
            )
            .scalars()
            .all()
        )
    return render_template(
        "roles.html",
        roles=roles,
        pagination=pagination,
        human_time=_human_time,
        page_title="Roles",
        active_page="roles",
    )


@bp.get("/settings/roles/new")
@bp.get("/roles/new")
def new_role():
    return render_template(
        "role_new.html",
        page_title="Create Role",
        active_page="roles",
    )


@bp.get("/settings/roles/<int:role_id>")
@bp.get("/roles/<int:role_id>")
def view_role(role_id: int):
    with session_scope() as session:
        role = session.get(Role, role_id)
        if role is None:
            abort(404)
    return render_template(
        "role_detail.html",
        role=role,
        human_time=_human_time,
        page_title=f"Role - {role.name}",
        active_page="roles",
    )


@bp.get("/settings/roles/<int:role_id>/edit")
@bp.get("/roles/<int:role_id>/edit")
def edit_role(role_id: int):
    with session_scope() as session:
        role = session.get(Role, role_id)
        if role is None:
            abort(404)
    return render_template(
        "role_edit.html",
        role=role,
        page_title=f"Edit Role - {role.name}",
        active_page="roles",
    )


@bp.post("/settings/roles/<int:role_id>")
@bp.post("/roles/<int:role_id>")
def update_role(role_id: int):
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    raw_details = request.form.get("details_json", "").strip()

    if not description:
        flash("Role description is required.", "error")
        return redirect(url_for("agents.edit_role", role_id=role_id))

    try:
        formatted_details = _parse_role_details(raw_details)
    except json.JSONDecodeError as exc:
        flash(f"Invalid JSON: {exc.msg}", "error")
        return redirect(url_for("agents.edit_role", role_id=role_id))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("agents.edit_role", role_id=role_id))

    with session_scope() as session:
        role = session.get(Role, role_id)
        if role is None:
            abort(404)
        if not name:
            name = role.name or "Untitled Role"
        role.name = name
        role.description = description
        role.details_json = formatted_details

    flash("Role updated.", "success")
    return redirect(url_for("agents.view_role", role_id=role_id))


@bp.post("/settings/roles/<int:role_id>/delete")
@bp.post("/roles/<int:role_id>/delete")
def delete_role(role_id: int):
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_roles")
    )
    with session_scope() as session:
        role = session.get(Role, role_id)
        if role is None:
            abort(404)
        assigned_agents = (
            session.execute(
                select(Agent).where(Agent.role_id == role_id)
            )
            .scalars()
            .all()
        )
        for agent in assigned_agents:
            agent.role_id = None
        session.delete(role)

    flash("Role deleted.", "success")
    if assigned_agents:
        flash(
            f"Removed role from {len(assigned_agents)} agent(s).",
            "info",
        )
    return redirect(next_url)


@bp.get("/settings/core")
def settings_core():
    summary = _settings_summary()
    core_config = {
        "DATA_DIR": Config.DATA_DIR,
        "DATABASE_FILENAME": Config.DATABASE_FILENAME,
        "SQLALCHEMY_DATABASE_URI": Config.SQLALCHEMY_DATABASE_URI,
        "AGENT_POLL_SECONDS": Config.AGENT_POLL_SECONDS,
        "LLM_PROVIDER": resolve_llm_provider() or "not set",
        "CODEX_CMD": Config.CODEX_CMD,
        "CODEX_MODEL": Config.CODEX_MODEL or "default",
        "GEMINI_CMD": Config.GEMINI_CMD,
        "GEMINI_MODEL": Config.GEMINI_MODEL or "default",
        "CLAUDE_CMD": Config.CLAUDE_CMD,
        "CLAUDE_MODEL": Config.CLAUDE_MODEL or "default",
        "VLLM_LOCAL_CMD": Config.VLLM_LOCAL_CMD,
        "VLLM_REMOTE_BASE_URL": Config.VLLM_REMOTE_BASE_URL or "not set",
        "VLLM_LOCAL_CUSTOM_MODELS_DIR": Config.VLLM_LOCAL_CUSTOM_MODELS_DIR,
    }
    return render_template(
        "settings_core.html",
        core_config=core_config,
        summary=summary,
        page_title="Settings - Core",
        active_page="settings_core",
    )


@bp.get("/settings/provider")
@bp.get("/settings/provider/controls")
def settings_provider():
    return _render_settings_provider_page("controls")


PROVIDER_SETTINGS_SECTIONS: dict[str, dict[str, str]] = {
    "controls": {
        "label": "Controls",
        "endpoint": "agents.settings_provider",
    },
    "codex": {
        "label": "Codex Auth",
        "endpoint": "agents.settings_provider_codex",
    },
    "gemini": {
        "label": "Gemini Auth",
        "endpoint": "agents.settings_provider_gemini",
    },
    "claude": {
        "label": "Claude Auth",
        "endpoint": "agents.settings_provider_claude",
    },
    "vllm_local": {
        "label": "vLLM Local",
        "endpoint": "agents.settings_provider_vllm_local",
    },
    "vllm_remote": {
        "label": "vLLM Remote",
        "endpoint": "agents.settings_provider_vllm_remote",
    },
}


def _settings_provider_context() -> dict[str, object]:
    summary = _settings_summary()
    llm_settings = _load_integration_settings("llm")
    enabled_providers = resolve_enabled_llm_providers(llm_settings)
    provider_summary = _provider_summary(
        settings=llm_settings, enabled_providers=enabled_providers
    )
    default_model_summary = _default_model_overview(llm_settings)
    codex_settings = _codex_settings_payload(llm_settings)
    gemini_settings = _gemini_settings_payload(llm_settings)
    claude_settings = _claude_settings_payload(llm_settings)
    vllm_local_settings = _vllm_local_settings_payload(llm_settings)
    vllm_remote_settings = _vllm_remote_settings_payload(llm_settings)
    provider_details = []
    for provider in LLM_PROVIDERS:
        provider_details.append(
            {
                "id": provider,
                "label": LLM_PROVIDER_LABELS.get(provider, provider),
                "command": _provider_command(provider),
                "model": _provider_model(provider, llm_settings),
                "enabled": provider in enabled_providers,
                "is_default": provider == provider_summary["provider"],
            }
        )
    return {
        "provider_summary": provider_summary,
        "provider_details": provider_details,
        "default_model_summary": default_model_summary,
        "codex_settings": codex_settings,
        "gemini_settings": gemini_settings,
        "claude_settings": claude_settings,
        "vllm_local_settings": vllm_local_settings,
        "vllm_remote_settings": vllm_remote_settings,
        "summary": summary,
        "active_page": "settings_provider",
    }


def _render_settings_provider_page(section: str):
    section_meta = PROVIDER_SETTINGS_SECTIONS.get(section)
    if section_meta is None:
        abort(404)
    return render_template(
        "settings_provider.html",
        provider_section=section,
        page_title=f"Settings - Providers - {section_meta['label']}",
        **_settings_provider_context(),
    )


@bp.get("/settings/provider/codex")
def settings_provider_codex():
    return _render_settings_provider_page("codex")


@bp.get("/settings/provider/gemini")
def settings_provider_gemini():
    return _render_settings_provider_page("gemini")


@bp.get("/settings/provider/claude")
def settings_provider_claude():
    return _render_settings_provider_page("claude")


@bp.get("/settings/provider/vllm-local")
def settings_provider_vllm_local():
    return _render_settings_provider_page("vllm_local")


@bp.get("/settings/provider/vllm-remote")
def settings_provider_vllm_remote():
    return _render_settings_provider_page("vllm_remote")


@bp.post("/settings/provider")
def update_provider_settings():
    default_provider = (request.form.get("default_provider") or "").strip().lower()
    if default_provider and default_provider not in LLM_PROVIDERS:
        flash("Unknown provider selection.", "error")
        return redirect(url_for("agents.settings_provider"))
    enabled: set[str] = set()
    for provider in LLM_PROVIDERS:
        if _as_bool(request.form.get(f"provider_enabled_{provider}")):
            enabled.add(provider)
    if default_provider:
        enabled.add(default_provider)
    payload = {
        f"provider_enabled_{provider}": "true" if provider in enabled else ""
        for provider in LLM_PROVIDERS
    }
    payload["provider"] = default_provider if default_provider in enabled else ""
    _save_integration_settings("llm", payload)
    if not enabled:
        flash("No providers enabled. Agents require a default model or provider.", "info")
    flash("Provider settings updated.", "success")
    return redirect(url_for("agents.settings_provider"))


@bp.post("/settings/provider/codex")
def update_codex_settings():
    api_key = request.form.get("codex_api_key", "")
    payload = {
        "codex_api_key": api_key,
    }
    _save_integration_settings("llm", payload)
    flash("Codex auth settings updated.", "success")
    return redirect(url_for("agents.settings_provider_codex"))


@bp.post("/settings/provider/gemini")
def update_gemini_settings():
    api_key = request.form.get("gemini_api_key", "")
    payload = {
        "gemini_api_key": api_key,
    }
    _save_integration_settings("llm", payload)
    flash("Gemini auth settings updated.", "success")
    return redirect(url_for("agents.settings_provider_gemini"))


@bp.post("/settings/provider/claude")
def update_claude_settings():
    api_key = request.form.get("claude_api_key", "")
    payload = {
        "claude_api_key": api_key,
    }
    _save_integration_settings("llm", payload)
    flash("Claude auth settings updated.", "success")
    return redirect(url_for("agents.settings_provider_claude"))


@bp.post("/settings/provider/vllm-local")
def update_vllm_local_settings():
    local_model = request.form.get("vllm_local_model", "")
    discovered_local_values = {item["value"] for item in discover_vllm_local_models()}
    local_model_clean = local_model.strip()
    if local_model_clean and local_model_clean not in discovered_local_values:
        flash("vLLM local model must be selected from discovered local models.", "error")
        return redirect(url_for("agents.settings_provider_vllm_local"))
    payload = {
        "vllm_local_model": local_model_clean,
        # Local provider runs in-container through CLI; clear deprecated HTTP fields.
        "vllm_local_base_url": "",
        "vllm_local_api_key": "",
    }
    if "vllm_local_hf_token" in request.form:
        payload["vllm_local_hf_token"] = request.form.get("vllm_local_hf_token", "")
    _save_integration_settings("llm", payload)
    flash("vLLM Local settings updated.", "success")
    return redirect(url_for("agents.settings_provider_vllm_local"))


@bp.post("/settings/provider/vllm-local/qwen/start")
def start_vllm_local_qwen_download():
    llm_settings = _load_integration_settings("llm")
    huggingface_token = _vllm_local_huggingface_token(llm_settings)
    if _qwen_model_downloaded():
        return {
            "ok": False,
            "error": "Qwen model is already downloaded. Use remove to delete it first.",
        }, 409

    job, created = _start_huggingface_download_job(
        kind="qwen",
        model_id=_qwen_model_id(),
        model_dir_name=_qwen_model_dir_name(),
        token=huggingface_token,
        model_container_path=_qwen_model_container_path(),
    )
    return {
        "ok": True,
        "created": created,
        "message": "Qwen download started." if created else "Qwen download already in progress.",
        "download_job": job,
        "status_url": url_for(
            "agents.vllm_local_huggingface_download_status",
            job_id=str(job.get("id") or ""),
        ),
    }, 202


@bp.post("/settings/provider/vllm-local/huggingface/start")
def start_vllm_local_huggingface_download():
    llm_settings = _load_integration_settings("llm")
    huggingface_token = _vllm_local_huggingface_token(llm_settings)
    if not huggingface_token:
        return {
            "ok": False,
            "error": "Set and save a HuggingFace token before downloading arbitrary models.",
        }, 400

    model_id = _normalize_huggingface_repo_id(
        request.form.get("vllm_local_hf_model_id", "")
    )
    if not model_id:
        return {
            "ok": False,
            "error": "HuggingFace model ID must use owner/model format.",
        }, 400

    model_dir_name = _huggingface_model_dir_name(model_id)
    model_directory = _vllm_local_model_directory(model_dir_name)
    if _model_directory_has_downloaded_contents(model_directory):
        model_container_path = _vllm_local_model_container_path(model_dir_name)
        return {
            "ok": False,
            "error": f"{model_id} already exists at {model_directory} ({model_container_path}).",
        }, 409

    job, created = _start_huggingface_download_job(
        kind="huggingface",
        model_id=model_id,
        model_dir_name=model_dir_name,
        token=huggingface_token,
        model_container_path=_vllm_local_model_container_path(model_dir_name),
    )
    return {
        "ok": True,
        "created": created,
        "message": (
            f"{model_id} download started."
            if created
            else f"{model_id} download already in progress."
        ),
        "download_job": job,
        "status_url": url_for(
            "agents.vllm_local_huggingface_download_status",
            job_id=str(job.get("id") or ""),
        ),
    }, 202


@bp.get("/settings/provider/vllm-local/downloads/<job_id>")
def vllm_local_huggingface_download_status(job_id: str):
    job = _get_huggingface_download_job(job_id.strip())
    if job is None:
        abort(404)
    return {"download_job": job}


@bp.post("/settings/provider/vllm-local/qwen")
def toggle_vllm_local_qwen_model():
    llm_settings = _load_integration_settings("llm")
    huggingface_token = _vllm_local_huggingface_token(llm_settings)
    action = (request.form.get("qwen_action") or "").strip().lower()
    if action not in {"download", "remove"}:
        flash("Unknown Qwen action.", "error")
        return redirect(url_for("agents.settings_integrations_huggingface"))
    if action == "download":
        if _qwen_model_downloaded():
            flash("Qwen model is already downloaded.", "info")
            return redirect(url_for("agents.settings_integrations_huggingface"))
        try:
            job, created = _start_huggingface_download_job(
                kind="qwen",
                model_id=_qwen_model_id(),
                model_dir_name=_qwen_model_dir_name(),
                token=huggingface_token,
                model_container_path=_qwen_model_container_path(),
            )
        except Exception:
            logger.exception("Failed to queue Qwen download.")
            flash("Failed to queue Qwen download.", "error")
        else:
            if created:
                flash(
                    f"Qwen download queued in background (job {job.get('id')}).",
                    "success",
                )
            else:
                flash("Qwen download is already in progress.", "info")
        return redirect(url_for("agents.settings_integrations_huggingface"))

    try:
        removed = _remove_qwen_model_directory()
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("agents.settings_integrations_huggingface"))
    except OSError as exc:
        logger.exception("Failed to remove Qwen directory.")
        flash(f"Failed to remove Qwen model files: {exc}", "error")
        return redirect(url_for("agents.settings_integrations_huggingface"))

    if removed:
        configured_model = (llm_settings.get("vllm_local_model") or "").strip()
        if configured_model in {str(_qwen_model_directory()), _qwen_model_container_path()}:
            _save_integration_settings("llm", {"vllm_local_model": ""})
        flash("Qwen model removed.", "success")
    else:
        flash("Qwen model directory is already absent.", "info")
    return redirect(url_for("agents.settings_integrations_huggingface"))


@bp.post("/settings/provider/vllm-local/huggingface")
def download_vllm_local_huggingface_model():
    llm_settings = _load_integration_settings("llm")
    huggingface_token = _vllm_local_huggingface_token(llm_settings)
    if not huggingface_token:
        flash(
            "Set and save a HuggingFace token before downloading arbitrary HuggingFace models.",
            "error",
        )
        return redirect(url_for("agents.settings_integrations_huggingface"))

    model_id = _normalize_huggingface_repo_id(
        request.form.get("vllm_local_hf_model_id", "")
    )
    if not model_id:
        flash("HuggingFace model ID must use owner/model format.", "error")
        return redirect(url_for("agents.settings_integrations_huggingface"))

    model_dir_name = _huggingface_model_dir_name(model_id)
    model_directory = _vllm_local_model_directory(model_dir_name)
    model_container_path = _vllm_local_model_container_path(model_dir_name)
    if _model_directory_has_downloaded_contents(model_directory):
        flash(
            f"{model_id} already exists at {model_directory} ({model_container_path}).",
            "info",
        )
        return redirect(url_for("agents.settings_integrations_huggingface"))

    try:
        job, created = _start_huggingface_download_job(
            kind="huggingface",
            model_id=model_id,
            model_dir_name=model_dir_name,
            token=huggingface_token,
            model_container_path=model_container_path,
        )
    except Exception:
        logger.exception("Failed to queue HuggingFace model download.")
        flash("Failed to queue HuggingFace model download.", "error")
    else:
        if created:
            flash(f"{model_id} download queued in background (job {job.get('id')}).", "success")
        else:
            flash(f"{model_id} download is already in progress.", "info")
    return redirect(url_for("agents.settings_integrations_huggingface"))


@bp.post("/settings/provider/vllm-local/huggingface/delete")
def delete_vllm_local_huggingface_model():
    model_dir_name = _normalize_vllm_local_model_dir_name(
        request.form.get("model_dir_name")
    )
    if not model_dir_name:
        flash("Model directory name is required.", "error")
        return redirect(url_for("agents.settings_integrations_huggingface"))

    model_entry = _find_downloaded_vllm_local_model(model_dir_name)
    if model_entry is None:
        flash("Model directory is already absent.", "info")
        return redirect(url_for("agents.settings_integrations_huggingface"))

    try:
        removed = _remove_vllm_local_model_directory(model_dir_name)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("agents.settings_integrations_huggingface"))
    except OSError as exc:
        logger.exception("Failed to remove HuggingFace model directory.")
        flash(f"Failed to remove downloaded model files: {exc}", "error")
        return redirect(url_for("agents.settings_integrations_huggingface"))

    if not removed:
        flash("Model directory is already absent.", "info")
        return redirect(url_for("agents.settings_integrations_huggingface"))

    llm_settings = _load_integration_settings("llm")
    configured_model = (llm_settings.get("vllm_local_model") or "").strip()
    configured_matches = {
        str(model_entry.get("value") or "").strip(),
        str(model_entry.get("target_dir") or "").strip(),
        str(model_entry.get("container_path") or "").strip(),
    }
    configured_matches.discard("")
    if configured_model and configured_model in configured_matches:
        _save_integration_settings("llm", {"vllm_local_model": ""})

    label = str(model_entry.get("label") or model_dir_name).strip() or model_dir_name
    flash(f"Removed downloaded model: {label}.", "success")
    return redirect(url_for("agents.settings_integrations_huggingface"))


@bp.post("/settings/provider/vllm-remote")
def update_vllm_remote_settings():
    remote_base_url = request.form.get("vllm_remote_base_url", "")
    remote_api_key = request.form.get("vllm_remote_api_key", "")
    remote_model = request.form.get("vllm_remote_model", "")
    remote_models = request.form.get("vllm_remote_models", "")
    payload = {
        "vllm_remote_base_url": remote_base_url,
        "vllm_remote_api_key": remote_api_key,
        "vllm_remote_model": remote_model,
        "vllm_remote_models": remote_models,
    }
    _save_integration_settings("llm", payload)
    flash("vLLM Remote settings updated.", "success")
    return redirect(url_for("agents.settings_provider_vllm_remote"))


@bp.get("/settings/celery")
def settings_celery():
    summary = _settings_summary()
    celery_config = {
        "CELERY_BROKER_URL": Config.CELERY_BROKER_URL,
        "CELERY_RESULT_BACKEND": Config.CELERY_RESULT_BACKEND,
        "CELERY_REVOKE_ON_STOP": Config.CELERY_REVOKE_ON_STOP,
    }
    broker_options = Config.CELERY_BROKER_TRANSPORT_OPTIONS or {}
    return render_template(
        "settings_celery.html",
        celery_config=celery_config,
        broker_options=broker_options,
        summary=summary,
        page_title="Settings - Celery",
        active_page="settings_celery",
    )


@bp.get("/settings/runtime")
@bp.get("/settings/runtime/node")
def settings_runtime():
    return _render_settings_runtime_page("node")


RUNTIME_SETTINGS_SECTIONS: dict[str, dict[str, str]] = {
    "node": {
        "label": "Node Runtime",
        "endpoint": "agents.settings_runtime",
    },
    "rag": {
        "label": "RAG Runtime",
        "endpoint": "agents.settings_runtime_rag",
    },
    "chat": {
        "label": "Chat Runtime",
        "endpoint": "agents.settings_runtime_chat",
    },
}


def _node_executor_settings_options() -> dict[str, list[dict[str, str]]]:
    provider_options = [
        {"value": "workspace", "label": "Workspace"},
        {"value": "docker", "label": "Docker"},
        {"value": "kubernetes", "label": "Kubernetes"},
    ]
    fallback_provider_options = [
        {"value": "workspace", "label": "Workspace"}
    ]
    docker_pull_policy_options = [
        {"value": "always", "label": "Always"},
        {"value": "if_not_present", "label": "If Not Present"},
        {"value": "never", "label": "Never"},
    ]
    docker_api_stall_seconds_options = [
        {"value": "5", "label": "5 seconds"},
        {"value": "10", "label": "10 seconds"},
        {"value": "15", "label": "15 seconds"},
    ]
    return {
        "provider_options": [
            option
            for option in provider_options
            if option["value"] in set(NODE_EXECUTOR_PROVIDER_CHOICES)
        ],
        "fallback_provider_options": [
            option
            for option in fallback_provider_options
            if option["value"] in set(NODE_EXECUTOR_FALLBACK_PROVIDER_CHOICES)
        ],
        "docker_pull_policy_options": [
            option
            for option in docker_pull_policy_options
            if option["value"] in set(NODE_EXECUTOR_DOCKER_PULL_POLICY_CHOICES)
        ],
        "docker_api_stall_seconds_options": [
            option
            for option in docker_api_stall_seconds_options
            if option["value"] in set(NODE_EXECUTOR_DOCKER_API_STALL_SECONDS_CHOICES)
        ],
    }


def _settings_runtime_context() -> dict[str, object]:
    summary = _settings_summary()
    config = {
        "AGENT_POLL_SECONDS": Config.AGENT_POLL_SECONDS,
        "CELERY_REVOKE_ON_STOP": Config.CELERY_REVOKE_ON_STOP,
    }
    llm_settings = _load_integration_settings("llm")
    enabled_providers = resolve_enabled_llm_providers(llm_settings)
    llm_config = _provider_summary(
        settings=llm_settings, enabled_providers=enabled_providers
    )
    instruction_runtime_flags = _instruction_runtime_flags(llm_settings)
    node_skill_binding_mode = _node_skill_binding_mode(llm_settings)
    node_executor_settings = load_node_executor_settings()
    node_executor_options = _node_executor_settings_options()
    node_skill_binding_modes = [
        {
            "value": NODE_SKILL_BINDING_MODE_WARN,
            "label": "warn",
            "description": "Accept legacy node skill payloads, ignore writes, and emit warnings.",
        },
        {
            "value": NODE_SKILL_BINDING_MODE_REJECT,
            "label": "reject",
            "description": "Reject legacy node skill payloads with validation errors.",
        },
    ]
    rag_settings = _effective_rag_settings()
    openai_auth_configured = bool((llm_settings.get("codex_api_key") or "").strip())
    gemini_auth_configured = bool((llm_settings.get("gemini_api_key") or "").strip())
    rag_chroma_ready = rag_settings.get("db_provider") != "chroma" or _chroma_connected(
        _resolved_chroma_settings()
    )
    return {
        "config": config,
        "llm_config": llm_config,
        "instruction_runtime_flags": instruction_runtime_flags,
        "node_skill_binding_mode": node_skill_binding_mode,
        "node_skill_binding_modes": node_skill_binding_modes,
        "node_executor_settings": node_executor_settings,
        "node_executor_options": node_executor_options,
        "rag_settings": rag_settings,
        "rag_chroma_ready": rag_chroma_ready,
        "rag_db_provider_choices": RAG_DB_PROVIDER_CHOICES,
        "rag_model_provider_choices": RAG_MODEL_PROVIDER_CHOICES,
        "rag_openai_embed_model_options": _rag_model_option_entries(
            RAG_OPENAI_EMBED_MODEL_OPTIONS,
            rag_settings.get("openai_embed_model"),
        ),
        "rag_gemini_embed_model_options": _rag_model_option_entries(
            RAG_GEMINI_EMBED_MODEL_OPTIONS,
            rag_settings.get("gemini_embed_model"),
        ),
        "rag_openai_chat_model_options": _rag_model_option_entries(
            RAG_OPENAI_CHAT_MODEL_OPTIONS,
            rag_settings.get("openai_chat_model"),
        ),
        "rag_gemini_chat_model_options": _rag_model_option_entries(
            RAG_GEMINI_CHAT_MODEL_OPTIONS,
            rag_settings.get("gemini_chat_model"),
        ),
        "rag_chat_response_style_choices": RAG_CHAT_RESPONSE_STYLE_CHOICES,
        "rag_openai_auth_configured": openai_auth_configured,
        "rag_gemini_auth_configured": gemini_auth_configured,
        "chat_runtime_settings": load_chat_runtime_settings_payload(),
        "summary": summary,
        "active_page": "settings_runtime",
    }


def _render_settings_runtime_page(section: str):
    section_meta = RUNTIME_SETTINGS_SECTIONS.get(section)
    if section_meta is None:
        abort(404)
    return render_template(
        "settings_runtime.html",
        runtime_section=section,
        page_title=f"Settings - Runtime - {section_meta['label']}",
        **_settings_runtime_context(),
    )


@bp.get("/settings/runtime/rag")
def settings_runtime_rag():
    return _render_settings_runtime_page("rag")


@bp.get("/settings/runtime/chat")
def settings_runtime_chat():
    return _render_settings_runtime_page("chat")


@bp.get("/settings/chat")
def settings_chat():
    summary = _settings_summary()
    models = _load_llm_models()
    mcp_servers = _load_mcp_servers()
    rag_health, rag_collections = _chat_rag_health_payload()
    chat_default_settings = _resolved_chat_default_settings(
        models=models,
        mcp_servers=mcp_servers,
        rag_collections=rag_collections,
    )
    return render_template(
        "settings_chat.html",
        models=models,
        mcp_servers=mcp_servers,
        rag_health=rag_health,
        rag_collections=rag_collections,
        chat_default_settings=chat_default_settings,
        chat_runtime_settings=load_chat_runtime_settings_payload(),
        summary=summary,
        page_title="Settings - Chat",
        active_page="settings_chat",
    )


@bp.post("/settings/chat/defaults")
def update_chat_default_settings_route():
    models = _load_llm_models()
    mcp_servers = _load_mcp_servers()
    model_ids = {model.id for model in models}
    mcp_ids = {server.id for server in mcp_servers}
    selected_model_id = _coerce_optional_int(
        request.form.get("default_model_id"),
        field_name="default_model_id",
        minimum=1,
    )
    if selected_model_id is not None and selected_model_id not in model_ids:
        flash("Default model selection is invalid.", "error")
        return redirect(url_for("agents.settings_chat"))
    selected_mcp_server_ids = _coerce_chat_id_list(
        request.form.getlist("default_mcp_server_ids"),
        field_name="default_mcp_server_id",
    )
    if any(server_id not in mcp_ids for server_id in selected_mcp_server_ids):
        flash("Default MCP server selection is invalid.", "error")
        return redirect(url_for("agents.settings_chat"))
    rag_health, rag_collections = _chat_rag_health_payload()
    available_rag_ids = {
        str(item.get("id") or "").strip()
        for item in rag_collections
        if str(item.get("id") or "").strip()
    }
    selected_rag_collections = _coerce_chat_collection_list(
        request.form.getlist("default_rag_collections")
    )
    if selected_rag_collections and (
        rag_health.get("state") != "configured_healthy" or not available_rag_ids
    ):
        flash("RAG defaults are unavailable until RAG is healthy.", "error")
        return redirect(url_for("agents.settings_chat"))
    if any(collection_id not in available_rag_ids for collection_id in selected_rag_collections):
        flash("Default RAG collection selection is invalid.", "error")
        return redirect(url_for("agents.settings_chat"))
    selected_default_response_complexity = normalize_chat_response_complexity(
        request.form.get("default_response_complexity"),
        default=CHAT_RESPONSE_COMPLEXITY_DEFAULT,
    )
    save_chat_default_settings(
        {
            "default_model_id": str(selected_model_id or ""),
            "default_response_complexity": selected_default_response_complexity,
            "default_mcp_server_ids": [
                str(server_id) for server_id in selected_mcp_server_ids
            ],
            "default_rag_collections": selected_rag_collections,
        }
    )
    flash("Chat default settings updated.", "success")
    return redirect(url_for("agents.settings_chat"))


@bp.post("/settings/runtime/chat")
def update_chat_runtime_settings_route():
    payload = {
        "history_budget_percent": request.form.get("history_budget_percent", ""),
        "rag_budget_percent": request.form.get("rag_budget_percent", ""),
        "mcp_budget_percent": request.form.get("mcp_budget_percent", ""),
        "compaction_trigger_percent": request.form.get("compaction_trigger_percent", ""),
        "compaction_target_percent": request.form.get("compaction_target_percent", ""),
        "preserve_recent_turns": request.form.get("preserve_recent_turns", ""),
        "rag_top_k": request.form.get("rag_top_k", ""),
        "default_context_window_tokens": request.form.get(
            "default_context_window_tokens",
            "",
        ),
        "max_compaction_summary_chars": request.form.get(
            "max_compaction_summary_chars",
            "",
        ),
    }
    save_chat_runtime_settings(payload)
    flash("Chat runtime settings updated.", "success")
    if (request.form.get("return_to") or "").strip().lower() == "runtime":
        return redirect(url_for("agents.settings_runtime_chat"))
    return redirect(url_for("agents.settings_chat"))


@bp.post("/settings/runtime/instructions")
def update_instruction_runtime_settings_route():
    payload: dict[str, str] = {}
    for provider in LLM_PROVIDERS:
        native_key = f"instruction_native_enabled_{provider}"
        fallback_key = f"instruction_fallback_enabled_{provider}"
        payload[native_key] = "true" if _as_bool(request.form.get(native_key)) else ""
        payload[fallback_key] = (
            "true" if _as_bool(request.form.get(fallback_key)) else ""
        )
    _save_integration_settings("llm", payload)
    flash("Instruction runtime adapter flags updated.", "success")
    return redirect(url_for("agents.settings_runtime"))


@bp.post("/settings/runtime/node-skill-binding")
def update_node_skill_binding_mode_route():
    raw_mode = (request.form.get("node_skill_binding_mode") or "").strip().lower()
    if raw_mode and raw_mode not in NODE_SKILL_BINDING_MODE_CHOICES:
        flash("Node skill compatibility mode is invalid.", "error")
        return redirect(url_for("agents.settings_runtime"))
    selected_mode = normalize_node_skill_binding_mode(raw_mode)
    _save_integration_settings(
        "llm", {"node_skill_binding_mode": selected_mode}
    )
    flash(
        f"Node skill compatibility mode set to {selected_mode}.",
        "success",
    )
    return redirect(url_for("agents.settings_runtime"))


@bp.post("/settings/runtime/node-executor")
def update_node_executor_runtime_settings_route():
    # Auth is not available yet. Once RBAC ships, limit this endpoint to admins.
    kubeconfig_value = request.form.get("k8s_kubeconfig", "")
    kubeconfig_clear = _as_bool(request.form.get("k8s_kubeconfig_clear"))
    payload = {
        "provider": request.form.get("provider", ""),
        "fallback_provider": request.form.get("fallback_provider", ""),
        "fallback_enabled": "true" if _as_bool(request.form.get("fallback_enabled")) else "false",
        "fallback_on_dispatch_error": (
            "true" if _as_bool(request.form.get("fallback_on_dispatch_error")) else "false"
        ),
        "dispatch_timeout_seconds": request.form.get("dispatch_timeout_seconds", ""),
        "execution_timeout_seconds": request.form.get("execution_timeout_seconds", ""),
        "log_collection_timeout_seconds": request.form.get(
            "log_collection_timeout_seconds",
            "",
        ),
        "cancel_grace_timeout_seconds": request.form.get(
            "cancel_grace_timeout_seconds",
            "",
        ),
        "cancel_force_kill_enabled": (
            "true" if _as_bool(request.form.get("cancel_force_kill_enabled")) else "false"
        ),
        "workspace_root": request.form.get("workspace_root", ""),
        "workspace_identity_key": request.form.get("workspace_identity_key", ""),
        "docker_host": request.form.get("docker_host", ""),
        "docker_image": request.form.get("docker_image", ""),
        "docker_network": request.form.get("docker_network", ""),
        "docker_pull_policy": request.form.get("docker_pull_policy", ""),
        "docker_env_json": request.form.get("docker_env_json", ""),
        "docker_api_stall_seconds": request.form.get("docker_api_stall_seconds", ""),
        "k8s_namespace": request.form.get("k8s_namespace", ""),
        "k8s_image": request.form.get("k8s_image", ""),
        "k8s_in_cluster": "true" if _as_bool(request.form.get("k8s_in_cluster")) else "false",
        "k8s_service_account": request.form.get("k8s_service_account", ""),
        "k8s_gpu_limit": request.form.get("k8s_gpu_limit", ""),
        "k8s_image_pull_secrets_json": request.form.get(
            "k8s_image_pull_secrets_json",
            "",
        ),
    }
    if kubeconfig_clear:
        payload["k8s_kubeconfig"] = ""
    elif kubeconfig_value.strip():
        payload["k8s_kubeconfig"] = kubeconfig_value
    try:
        save_node_executor_settings(payload)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("agents.settings_runtime"))
    flash("Node executor runtime settings updated.", "success")
    return redirect(url_for("agents.settings_runtime"))


@bp.get("/settings/runtime/node-executor/effective")
def node_executor_runtime_effective_config_route():
    return {"node_executor": node_executor_effective_config_summary()}


@bp.get("/settings/gitconfig")
def settings_gitconfig():
    return redirect(url_for("agents.settings_integrations_git"))


@bp.post("/settings/gitconfig")
def update_gitconfig():
    return update_integrations_gitconfig()


@bp.get("/settings/integrations/git")
def settings_integrations_git():
    sync_integrated_mcp_servers()
    return _render_settings_integrations_page("git")


@bp.post("/settings/integrations/git")
def update_integrations_gitconfig():
    gitconfig_path = _gitconfig_path()
    gitconfig_content = request.form.get("gitconfig_content", "")
    try:
        gitconfig_path.write_text(gitconfig_content, encoding="utf-8")
    except OSError as exc:
        flash(f"Unable to write {gitconfig_path}: {exc}", "error")
        return _render_settings_integrations_page(
            "git",
            gitconfig_content=gitconfig_content,
        )
    flash("Git config saved.", "success")
    return redirect(url_for("agents.settings_integrations_git"))


@bp.get("/settings/integrations")
def settings_integrations():
    return redirect(url_for("agents.settings_integrations_git"))


@bp.get("/settings/integrations/github")
def settings_integrations_github():
    sync_integrated_mcp_servers()
    return _render_settings_integrations_page("github")


@bp.get("/settings/integrations/jira")
def settings_integrations_jira():
    sync_integrated_mcp_servers()
    return _render_settings_integrations_page("jira")


@bp.get("/settings/integrations/confluence")
def settings_integrations_confluence():
    sync_integrated_mcp_servers()
    return _render_settings_integrations_page("confluence")


@bp.get("/settings/integrations/google-drive")
def settings_integrations_google_drive():
    return redirect(url_for("agents.settings_integrations_google_cloud"))


@bp.get("/settings/integrations/google-cloud")
def settings_integrations_google_cloud():
    sync_integrated_mcp_servers()
    return _render_settings_integrations_page("google_cloud")


@bp.get("/settings/integrations/google-workspace")
def settings_integrations_google_workspace():
    sync_integrated_mcp_servers()
    return _render_settings_integrations_page("google_workspace")


@bp.get("/settings/integrations/huggingface")
def settings_integrations_huggingface():
    sync_integrated_mcp_servers()
    return _render_settings_integrations_page("huggingface")


@bp.get("/settings/integrations/chroma")
def settings_integrations_chroma():
    sync_integrated_mcp_servers()
    return _render_settings_integrations_page("chroma")


@bp.get("/settings/integrations/rag")
def settings_integrations_rag():
    return redirect(url_for("agents.settings_runtime_rag"))


@bp.post("/settings/integrations/github")
def update_github_settings():
    action = request.form.get("action", "").strip()
    pat = request.form.get("github_pat", "").strip()
    current_settings = _load_integration_settings("github")
    existing_key_path = (current_settings.get("ssh_key_path") or "").strip()
    uploaded_key = request.files.get("github_ssh_key")
    clear_key = request.form.get("github_ssh_key_clear", "").lower() in {"1", "true", "on"}
    logger.info(
        "GitHub settings update action=%s has_pat=%s has_repo=%s",
        action or "save",
        bool(pat),
        "github_repo" in request.form,
    )
    payload = {"pat": pat}
    if "github_repo" in request.form:
        payload["repo"] = request.form.get("github_repo", "").strip()
    if clear_key and existing_key_path:
        existing_path = Path(existing_key_path)
        try:
            if existing_path.is_file() and Path(Config.SSH_KEYS_DIR) in existing_path.parents:
                existing_path.unlink()
        except OSError:
            logger.warning("Failed to remove GitHub SSH key at %s", existing_key_path)
        payload["ssh_key_path"] = ""
        flash("GitHub SSH key removed.", "success")
    elif uploaded_key and uploaded_key.filename:
        key_bytes = uploaded_key.read()
        if not key_bytes:
            flash("Uploaded SSH key is empty.", "error")
        elif len(key_bytes) > 256 * 1024:
            flash("SSH key is too large.", "error")
        else:
            key_path = Path(Config.SSH_KEYS_DIR) / "github_ssh_key.pem"
            try:
                key_path.write_bytes(key_bytes)
                key_path.chmod(0o600)
                payload["ssh_key_path"] = str(key_path)
                flash("GitHub SSH key uploaded.", "success")
            except OSError as exc:
                logger.warning("Failed to save GitHub SSH key: %s", exc)
                flash("Unable to save GitHub SSH key.", "error")
    _save_integration_settings("github", payload)
    sync_integrated_mcp_servers()
    if action == "refresh":
        repo_options: list[str] = []
        if pat:
            try:
                logger.info("GitHub refresh: requesting repositories")
                repo_options = _fetch_github_repos(pat)
                if repo_options:
                    logger.info("GitHub refresh: loaded %s repositories", len(repo_options))
                    flash(f"Loaded {len(repo_options)} repositories.", "success")
                else:
                    logger.info("GitHub refresh: no repositories returned")
                    flash("No repositories returned for this PAT.", "info")
            except ValueError as exc:
                logger.warning("GitHub refresh: failed with error=%s", exc)
                flash(str(exc), "error")
        else:
            logger.info("GitHub refresh: missing PAT")
            flash("GitHub PAT is required to refresh repositories.", "error")
        return _render_settings_integrations_page(
            "github",
            github_repo_options=repo_options,
        )
    flash("GitHub settings updated.", "success")
    return redirect(url_for("agents.settings_integrations_github"))


@bp.post("/settings/integrations/google-drive")
def update_google_drive_settings():
    return update_google_cloud_settings()


@bp.post("/settings/integrations/google-cloud")
def update_google_cloud_settings():
    service_account_json = request.form.get(
        "google_cloud_service_account_json", ""
    ).strip()
    if not service_account_json:
        service_account_json = request.form.get(
            "google_drive_service_account_json", ""
        ).strip()
    google_cloud_project_id = request.form.get("google_cloud_project_id", "").strip()
    raw_google_cloud_mcp_enabled = request.form.get("google_cloud_mcp_enabled")
    if raw_google_cloud_mcp_enabled is None:
        google_cloud_mcp_enabled = "true"
    else:
        google_cloud_mcp_enabled = (
            "true" if _as_bool(raw_google_cloud_mcp_enabled) else "false"
        )

    if google_cloud_project_id and any(char.isspace() for char in google_cloud_project_id):
        flash("Google Cloud project ID cannot contain spaces.", "error")
        return redirect(url_for("agents.settings_integrations_google_cloud"))

    if service_account_json:
        try:
            _google_drive_service_account_email(service_account_json)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("agents.settings_integrations_google_cloud"))

    _save_integration_settings(
        GOOGLE_CLOUD_PROVIDER,
        {
            "service_account_json": service_account_json,
            "google_cloud_project_id": google_cloud_project_id,
            "google_cloud_mcp_enabled": google_cloud_mcp_enabled,
        },
    )
    sync_integrated_mcp_servers()
    flash("Google Cloud settings updated.", "success")
    return redirect(url_for("agents.settings_integrations_google_cloud"))


@bp.post("/settings/integrations/google-workspace")
def update_google_workspace_settings():
    service_account_json = request.form.get(
        "workspace_service_account_json", ""
    ).strip()
    delegated_user_email = request.form.get(
        "workspace_delegated_user_email", ""
    ).strip()
    raw_google_workspace_mcp_enabled = request.form.get("google_workspace_mcp_enabled")
    if raw_google_workspace_mcp_enabled is None:
        google_workspace_mcp_enabled = "false"
    else:
        google_workspace_mcp_enabled = (
            "true" if _as_bool(raw_google_workspace_mcp_enabled) else "false"
        )

    if delegated_user_email and any(char.isspace() for char in delegated_user_email):
        flash("Workspace delegated user email cannot contain spaces.", "error")
        return redirect(url_for("agents.settings_integrations_google_workspace"))

    if service_account_json:
        try:
            _google_drive_service_account_email(service_account_json)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("agents.settings_integrations_google_workspace"))

    _save_integration_settings(
        GOOGLE_WORKSPACE_PROVIDER,
        {
            "service_account_json": service_account_json,
            "workspace_delegated_user_email": delegated_user_email,
            "google_workspace_mcp_enabled": google_workspace_mcp_enabled,
        },
    )
    sync_integrated_mcp_servers()
    flash("Google Workspace settings updated.", "success")
    return redirect(url_for("agents.settings_integrations_google_workspace"))


@bp.post("/settings/integrations/huggingface")
def update_huggingface_settings():
    token = request.form.get("vllm_local_hf_token", "")
    _save_integration_settings("llm", {"vllm_local_hf_token": token})
    flash("HuggingFace settings updated.", "success")
    return redirect(url_for("agents.settings_integrations_huggingface"))


@bp.post("/settings/integrations/chroma")
def update_chroma_settings():
    host = request.form.get("chroma_host", "").strip()
    port = request.form.get("chroma_port", "").strip()
    ssl = "true" if _as_bool(request.form.get("chroma_ssl")) else "false"
    normalized_hint = None
    if port:
        try:
            parsed_port = int(port)
        except ValueError:
            flash("Chroma port must be a number between 1 and 65535.", "error")
            return redirect(url_for("agents.settings_integrations_chroma"))
        if parsed_port < 1 or parsed_port > 65535:
            flash("Chroma port must be a number between 1 and 65535.", "error")
            return redirect(url_for("agents.settings_integrations_chroma"))
        if host:
            host, parsed_port, normalized_hint = _normalize_chroma_target(host, parsed_port)
        port = str(parsed_port)
    _save_integration_settings(
        "chroma",
        {
            "host": host,
            "port": port,
            "ssl": ssl,
        },
    )
    sync_integrated_mcp_servers()
    if normalized_hint:
        flash(normalized_hint, "info")
    flash("ChromaDB settings updated.", "success")
    return redirect(url_for("agents.settings_integrations_chroma"))


@bp.post("/settings/runtime/rag")
@bp.post("/settings/integrations/rag")
def update_rag_settings():
    defaults = _rag_default_settings()
    db_provider = _normalize_rag_db_provider(request.form.get("rag_db_provider"))
    embed_provider = _normalize_rag_model_provider(request.form.get("rag_embed_provider"))
    chat_provider = _normalize_rag_model_provider(request.form.get("rag_chat_provider"))
    chat_response_style = _normalize_rag_chat_response_style(
        request.form.get("rag_chat_response_style")
    )
    chat_temperature = _coerce_rag_float_str(
        request.form.get("rag_chat_temperature"),
        float(defaults.get("chat_temperature") or 0.2),
        minimum=0.0,
        maximum=2.0,
    )
    openai_embed_model = _coerce_rag_model_choice(
        request.form.get("rag_openai_embed_model"),
        default=defaults["openai_embed_model"],
        choices=RAG_OPENAI_EMBED_MODEL_OPTIONS,
    )
    gemini_embed_model = _coerce_rag_model_choice(
        request.form.get("rag_gemini_embed_model"),
        default=defaults["gemini_embed_model"],
        choices=RAG_GEMINI_EMBED_MODEL_OPTIONS,
    )
    openai_chat_model = _coerce_rag_model_choice(
        request.form.get("rag_openai_chat_model"),
        default=defaults["openai_chat_model"],
        choices=RAG_OPENAI_CHAT_MODEL_OPTIONS,
    )
    gemini_chat_model = _coerce_rag_model_choice(
        request.form.get("rag_gemini_chat_model"),
        default=defaults["gemini_chat_model"],
        choices=RAG_GEMINI_CHAT_MODEL_OPTIONS,
    )
    payload = {
        "db_provider": db_provider,
        "embed_provider": embed_provider,
        "chat_provider": chat_provider,
        # RAG runtime auth uses Provider settings as source-of-truth.
        "openai_api_key": "",
        "gemini_api_key": "",
        "openai_embed_model": openai_embed_model,
        "gemini_embed_model": gemini_embed_model,
        "openai_chat_model": openai_chat_model,
        "gemini_chat_model": gemini_chat_model,
        "chat_temperature": chat_temperature,
        "openai_chat_temperature": chat_temperature,
        "chat_response_style": chat_response_style,
        "chat_top_k": _coerce_rag_int_str(
            request.form.get("rag_chat_top_k"),
            int(defaults.get("chat_top_k") or 5),
            minimum=1,
            maximum=20,
        ),
        "chat_max_history": _coerce_rag_int_str(
            request.form.get("rag_chat_max_history"),
            int(defaults.get("chat_max_history") or 8),
            minimum=1,
            maximum=50,
        ),
        "chat_max_context_chars": _coerce_rag_int_str(
            request.form.get("rag_chat_max_context_chars"),
            int(defaults.get("chat_max_context_chars") or 12000),
            minimum=1000,
            maximum=1000000,
        ),
        "chat_snippet_chars": _coerce_rag_int_str(
            request.form.get("rag_chat_snippet_chars"),
            int(defaults.get("chat_snippet_chars") or 600),
            minimum=100,
            maximum=10000,
        ),
        "chat_context_budget_tokens": _coerce_rag_int_str(
            request.form.get("rag_chat_context_budget_tokens"),
            int(defaults.get("chat_context_budget_tokens") or 8000),
            minimum=256,
            maximum=100000,
        ),
        "index_parallel_workers": _coerce_rag_int_str(
            request.form.get("rag_index_parallel_workers"),
            int(defaults.get("index_parallel_workers") or 1),
            minimum=1,
            maximum=64,
        ),
        "embed_parallel_requests": _coerce_rag_int_str(
            request.form.get("rag_embed_parallel_requests"),
            int(defaults.get("embed_parallel_requests") or 1),
            minimum=1,
            maximum=64,
        ),
    }
    _save_rag_settings("rag", payload)

    chroma_ready = _chroma_connected(_resolved_chroma_settings())
    if db_provider == "chroma" and not chroma_ready:
        flash(
            "RAG settings saved. Configure ChromaDB host and port before indexing or chat.",
            "warning",
        )
    else:
        flash("RAG settings updated.", "success")
    return redirect(url_for("agents.settings_runtime_rag"))


@bp.post("/settings/integrations/jira")
def update_jira_settings():
    action = request.form.get("action", "").strip()
    api_key = request.form.get("jira_api_key", "").strip()
    email = request.form.get("jira_email", "").strip()
    site = request.form.get("jira_site", "").strip()
    project_key = request.form.get("jira_project_key", "").strip()
    logger.info(
        "Jira settings update action=%s key_len=%s key_has_colon=%s email_domain=%s site_host=%s has_board=%s",
        action or "save",
        len(api_key),
        ":" in api_key,
        _safe_email_domain(email),
        _safe_site_label(site),
        "jira_board" in request.form,
    )
    payload = {
        "api_key": api_key,
        "email": email,
        "site": site,
        "project_key": project_key,
    }
    if "jira_board" in request.form:
        payload["board"] = request.form.get("jira_board", "").strip()
    _save_integration_settings("jira", payload)
    sync_integrated_mcp_servers()
    if action == "refresh":
        board_options: list[dict[str, str]] = []
        project_options: list[dict[str, str]] = []
        if api_key and site:
            try:
                auth_key = _combine_atlassian_key(api_key, email)
                email_valid = True
                if email and "@" not in email:
                    email_valid = False
                    flash(
                        "Jira email must include a full address (name@domain).",
                        "error",
                    )
                needs_email = ":" not in auth_key
                if needs_email:
                    flash(
                        "Jira API key needs an Atlassian email. Enter it above or use email:token.",
                        "error",
                    )
                logger.info(
                    "Jira refresh: starting email_set=%s",
                    bool(email),
                )
                if not email_valid or needs_email:
                    logger.info("Jira refresh: skipped due to email validation")
                else:
                    project_options = _fetch_jira_projects(auth_key, site)
                    if project_options:
                        logger.info(
                            "Jira refresh: loaded %s projects", len(project_options)
                        )
                        flash(f"Loaded {len(project_options)} projects.", "success")
                    else:
                        logger.info("Jira refresh: no projects returned")
                        flash("No projects returned for this Jira key.", "info")
                    if project_key:
                        board_options = _fetch_jira_boards(
                            auth_key, site, project_key
                        )
                        if board_options:
                            logger.info(
                                "Jira refresh: loaded %s boards", len(board_options)
                            )
                            flash(
                                f"Loaded {len(board_options)} boards for {project_key}.",
                                "success",
                            )
                        else:
                            logger.info("Jira refresh: no boards returned")
                            flash(
                                f"No boards returned for project {project_key}.",
                                "info",
                            )
                    else:
                        flash(
                            "Select a Jira project and refresh to load boards.",
                            "info",
                        )
            except ValueError as exc:
                logger.warning("Jira refresh: failed with error=%s", exc)
                flash(str(exc), "error")
        else:
            logger.info("Jira refresh: missing api key or site")
            flash(
                "Jira API key and site URL are required to refresh projects and boards.",
                "error",
            )
        if project_key and all(
            option.get("value") != project_key for option in project_options
        ):
            project_options.insert(
                0, {"value": project_key, "label": project_key}
            )
        return _render_settings_integrations_page(
            "jira",
            jira_project_options=project_options,
            jira_board_options=board_options,
        )
    flash("Jira settings updated.", "success")
    return redirect(url_for("agents.settings_integrations_jira"))


@bp.post("/settings/integrations/confluence")
def update_confluence_settings():
    action = request.form.get("action", "").strip()
    existing_settings = _load_integration_settings("confluence")
    jira_settings = _load_integration_settings("jira")
    jira_site = _normalize_confluence_site((jira_settings.get("site") or "").strip())
    api_key = (
        request.form.get("confluence_api_key", "").strip()
        if "confluence_api_key" in request.form
        else (existing_settings.get("api_key") or jira_settings.get("api_key") or "").strip()
    )
    email = (
        request.form.get("confluence_email", "").strip()
        if "confluence_email" in request.form
        else (existing_settings.get("email") or jira_settings.get("email") or "").strip()
    )
    site = (
        request.form.get("confluence_site", "").strip()
        if "confluence_site" in request.form
        else (existing_settings.get("site") or jira_site or "").strip()
    )
    site = _normalize_confluence_site(site)
    configured_space = (
        request.form.get("confluence_space", "").strip()
        if "confluence_space" in request.form
        else (existing_settings.get("space") or "").strip()
    )
    logger.info(
        "Confluence settings update action=%s key_len=%s key_has_colon=%s email_domain=%s site_host=%s has_space=%s",
        action or "save",
        len(api_key),
        ":" in api_key,
        _safe_email_domain(email),
        _safe_site_label(site),
        "confluence_space" in request.form,
    )
    payload = {
        "api_key": api_key,
        "email": email,
        "site": site,
        "space": configured_space,
    }
    _save_integration_settings("confluence", payload)
    sync_integrated_mcp_servers()
    if action == "refresh":
        space_options: list[dict[str, str]] = []
        cache_payload: str | None = None
        if api_key and site:
            try:
                auth_key = _combine_atlassian_key(api_key, email)
                email_valid = True
                if email and "@" not in email:
                    email_valid = False
                    flash(
                        "Confluence email must include a full address (name@domain).",
                        "error",
                    )
                needs_email = ":" not in auth_key
                if needs_email:
                    flash(
                        "Confluence API key needs an Atlassian email. Enter it above or use email:token.",
                        "error",
                    )
                logger.info(
                    "Confluence refresh: starting email_set=%s",
                    bool(email),
                )
                if not email_valid or needs_email:
                    logger.info("Confluence refresh: skipped due to email validation")
                else:
                    space_options = _fetch_confluence_spaces(auth_key, site)
                    cache_payload = _serialize_option_entries(space_options)
                    if space_options:
                        logger.info(
                            "Confluence refresh: loaded %s spaces", len(space_options)
                        )
                        flash(f"Loaded {len(space_options)} spaces.", "success")
                    else:
                        logger.info("Confluence refresh: no spaces returned")
                        flash("No spaces returned for this Confluence key.", "info")
            except ValueError as exc:
                logger.warning("Confluence refresh: failed with error=%s", exc)
                flash(str(exc), "error")
        else:
            logger.info("Confluence refresh: missing api key or site")
            flash(
                "Confluence API key and site URL are required to refresh spaces.",
                "error",
            )
        if cache_payload is not None:
            _save_integration_settings("confluence", {"space_options": cache_payload})
        confluence_settings = _load_integration_settings("confluence")
        if not space_options:
            space_options = _confluence_space_options(confluence_settings)
        else:
            space_options = _merge_selected_option(
                space_options, confluence_settings.get("space")
            )
        return _render_settings_integrations_page(
            "confluence",
            confluence_space_options=space_options,
        )
    flash("Confluence settings updated.", "success")
    return redirect(url_for("agents.settings_integrations_confluence"))
