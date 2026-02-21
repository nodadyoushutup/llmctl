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
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.exc import DetachedInstanceError

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
    NODE_EXECUTOR_PROVIDER_CHOICES,
    integration_overview as _integration_overview,
    load_integration_settings as _load_integration_settings,
    load_node_executor_settings,
    node_executor_effective_config_summary,
    migrate_legacy_google_integration_settings,
    resolve_default_model_id,
    resolve_enabled_llm_providers,
    resolve_llm_provider,
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
    FLOWCHART_EDGE_MODE_SOLID,
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
    ChatThread,
    ChatTurn,
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
    NodeArtifact,
    NODE_ARTIFACT_RETENTION_CHOICES,
    NODE_ARTIFACT_RETENTION_FOREVER,
    NODE_ARTIFACT_RETENTION_MAX_COUNT,
    NODE_ARTIFACT_RETENTION_TTL,
    NODE_ARTIFACT_RETENTION_TTL_MAX_COUNT,
    NODE_ARTIFACT_TYPE_DECISION,
    NODE_ARTIFACT_TYPE_END,
    NODE_ARTIFACT_TYPE_FLOWCHART,
    NODE_ARTIFACT_TYPE_MEMORY,
    NODE_ARTIFACT_TYPE_MILESTONE,
    NODE_ARTIFACT_TYPE_PLAN,
    NODE_ARTIFACT_TYPE_RAG,
    NODE_ARTIFACT_TYPE_START,
    NODE_ARTIFACT_TYPE_TASK,
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
    SCRIPT_TYPE_CHOICES,
    SCRIPT_TYPE_LABELS,
    SCRIPT_TYPE_INIT,
    SCRIPT_TYPE_POST_INIT,
    SCRIPT_TYPE_POST_RUN,
    SCRIPT_TYPE_PRE_INIT,
    SYSTEM_MANAGED_MCP_SERVER_KEYS,
)
from core.mcp_config import format_mcp_config, validate_server_key
from core.integrated_mcp import INTEGRATED_MCP_LLMCTL_KEY, sync_integrated_mcp_servers
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
from rag.engine.chromadb_loader import import_chromadb
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
from services.agent_runtime import build_agent_payload as build_runtime_agent_payload
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
from services.execution.idempotency import register_runtime_idempotency_key
from services.realtime_events import emit_contract_event
from services.runtime_contracts import RUNTIME_CONTRACT_VERSION
from web.api_contracts import (
    build_api_error_envelope,
    correlation_id_from_request,
    request_id_from_request,
)

bp = Blueprint("agents", __name__, template_folder="templates")
logger = logging.getLogger(__name__)

DEFAULT_TASKS_PER_PAGE = 10
TASKS_PER_PAGE_OPTIONS = (10, 25, 50, 100)
DEFAULT_RUNS_PER_PAGE = DEFAULT_TASKS_PER_PAGE
RUNS_PER_PAGE_OPTIONS = TASKS_PER_PAGE_OPTIONS
FLOWCHART_NODE_TYPE_SET = set(FLOWCHART_NODE_TYPE_CHOICES)
DOCKER_CHROMA_HOST_ALIASES = {"llmctl-chromadb", "chromadb"}
QUICK_DEFAULT_SETTINGS_PROVIDER = "quick"
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
MODEL_PROVIDER_API_CONTRACT_VERSION = RUNTIME_CONTRACT_VERSION
MODEL_LIST_SORT_FIELDS = {
    "name": LLMModel.name,
    "provider": LLMModel.provider,
    "created_at": LLMModel.created_at,
    "updated_at": LLMModel.updated_at,
}
PROVIDER_LIST_SORT_FIELDS = {"id", "label", "enabled", "is_default", "model"}
MODEL_COMPATIBILITY_KEYS: dict[str, tuple[str, ...]] = {
    "codex": (
        "model",
        "approval_policy",
        "sandbox_mode",
        "network_access",
        "model_reasoning_effort",
        "shell_env_inherit",
        "shell_env_ignore_default_excludes",
        "notice_hide_key",
        "notice_hide_enabled",
        "notice_migration_from",
        "notice_migration_to",
    ),
    "gemini": (
        "model",
        "approval_mode",
        "sandbox",
        "use_vertex_ai",
        "project",
        "location",
        "extra_args",
    ),
    "claude": ("model",),
    "vllm_local": (
        "model",
        "temperature",
        "max_tokens",
        "request_timeout_seconds",
        "agent_markdown_filename",
    ),
    "vllm_remote": (
        "model",
        "base_url_override",
        "temperature",
        "max_tokens",
        "request_timeout_seconds",
        "agent_markdown_filename",
    ),
}
QWEN_DEFAULT_MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"
QWEN_DEFAULT_MODEL_DIR_NAME = "qwen2.5-0.5b-instruct"
HUGGINGFACE_REPO_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$"
)
HUGGINGFACE_DOWNLOAD_JOB_STATUS_ACTIVE = {"queued", "running"}
HUGGINGFACE_DOWNLOAD_JOB_TTL_SECONDS = 6 * 60 * 60
FLOWCHART_TRACE_DEFAULT_LIMIT = 50
FLOWCHART_TRACE_MAX_LIMIT = 200
FLOWCHART_RUN_CONTROL_ACTIONS = {
    "pause",
    "resume",
    "cancel",
    "retry",
    "skip",
    "rewind",
}
FLOWCHART_RUN_CONTROL_REPLAY_ACTIONS = {"retry", "skip", "rewind"}
FLOWCHART_RUN_ACTIVE_STATUSES = {"queued", "running", "stopping", "pausing", "paused"}
FLOWCHART_RUN_TERMINAL_STATUSES = {"completed", "succeeded", "failed", "stopped", "canceled"}
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
    FLOWCHART_NODE_TYPE_PLAN,
    FLOWCHART_NODE_TYPE_MILESTONE,
    FLOWCHART_NODE_TYPE_MEMORY,
}
FLOWCHART_NODE_TYPE_REQUIRES_REF = {
    FLOWCHART_NODE_TYPE_FLOWCHART,
    FLOWCHART_NODE_TYPE_PLAN,
    FLOWCHART_NODE_TYPE_MILESTONE,
}
FLOWCHART_NODE_TYPE_AUTO_REF = {
    FLOWCHART_NODE_TYPE_PLAN,
    FLOWCHART_NODE_TYPE_MILESTONE,
    FLOWCHART_NODE_TYPE_MEMORY,
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
        "mcp": False,
        "scripts": False,
        "skills": False,
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
MILESTONE_NODE_ACTION_CREATE_OR_UPDATE = "create_or_update"
MILESTONE_NODE_ACTION_MARK_COMPLETE = "mark_complete"
MILESTONE_NODE_ACTION_CHOICES = (
    MILESTONE_NODE_ACTION_CREATE_OR_UPDATE,
    MILESTONE_NODE_ACTION_MARK_COMPLETE,
)
MEMORY_NODE_ACTION_ADD = "add"
MEMORY_NODE_ACTION_RETRIEVE = "retrieve"
MEMORY_NODE_ACTION_CHOICES = (
    MEMORY_NODE_ACTION_ADD,
    MEMORY_NODE_ACTION_RETRIEVE,
)
MEMORY_NODE_MODE_LLM_GUIDED = "llm_guided"
MEMORY_NODE_MODE_DETERMINISTIC = "deterministic"
MEMORY_NODE_MODE_CHOICES = (
    MEMORY_NODE_MODE_LLM_GUIDED,
    MEMORY_NODE_MODE_DETERMINISTIC,
)
MEMORY_NODE_RETRY_COUNT_DEFAULT = 1
MEMORY_NODE_RETRY_COUNT_MAX = 5
MEMORY_NODE_FALLBACK_ENABLED_DEFAULT = True
PLAN_NODE_ACTION_CREATE_OR_UPDATE = "create_or_update_plan"
PLAN_NODE_ACTION_COMPLETE_PLAN_ITEM = "complete_plan_item"
PLAN_NODE_ACTION_CHOICES = (
    PLAN_NODE_ACTION_CREATE_OR_UPDATE,
    PLAN_NODE_ACTION_COMPLETE_PLAN_ITEM,
)
DEFAULT_NODE_ARTIFACT_RETENTION_TTL_SECONDS = 3600
DEFAULT_NODE_ARTIFACT_RETENTION_MAX_COUNT = 25
FLOWCHART_FAN_IN_MODE_ALL = "all"
FLOWCHART_FAN_IN_MODE_ANY = "any"
FLOWCHART_FAN_IN_MODE_CUSTOM = "custom"
FLOWCHART_FAN_IN_MODE_CHOICES = (
    FLOWCHART_FAN_IN_MODE_ALL,
    FLOWCHART_FAN_IN_MODE_ANY,
    FLOWCHART_FAN_IN_MODE_CUSTOM,
)
FLOWCHART_DECISION_NO_MATCH_POLICY_FAIL = "fail"
FLOWCHART_DECISION_NO_MATCH_POLICY_FALLBACK = "fallback"
FLOWCHART_DECISION_NO_MATCH_POLICY_CHOICES = (
    FLOWCHART_DECISION_NO_MATCH_POLICY_FAIL,
    FLOWCHART_DECISION_NO_MATCH_POLICY_FALLBACK,
)


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


def _canonical_rag_execution_mode(value: object) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in {"index", "fresh", "fresh_index", "indexing"}:
        return "indexing"
    if cleaned in {"delta", "delta_index", "delta_indexing"}:
        return "delta_indexing"
    if cleaned in {"query"}:
        return "query"
    return ""


def _task_execution_mode(task: AgentTask | None) -> str:
    if task is None:
        return ""
    if task.kind == RAG_QUICK_INDEX_TASK_KIND:
        return "indexing"
    if task.kind == RAG_QUICK_DELTA_TASK_KIND:
        return "delta_indexing"

    _prompt_text, prompt_payload = parse_prompt_input(task.prompt)
    if isinstance(prompt_payload, dict):
        flowchart_node_type = str(prompt_payload.get("flowchart_node_type") or "").strip().lower()
        if flowchart_node_type == FLOWCHART_NODE_TYPE_RAG:
            prompt_mode = _canonical_rag_execution_mode(prompt_payload.get("flowchart_node_mode"))
            if prompt_mode:
                return prompt_mode
        task_context = prompt_payload.get("task_context")
        if isinstance(task_context, dict):
            quick_context = task_context.get("rag_quick_run")
            if isinstance(quick_context, dict):
                quick_mode = _canonical_rag_execution_mode(quick_context.get("mode"))
                if quick_mode:
                    return quick_mode

    raw_output = str(task.output or "").strip()
    if raw_output.startswith("{"):
        try:
            output_payload = json.loads(raw_output)
        except json.JSONDecodeError:
            output_payload = {}
        if isinstance(output_payload, dict):
            mode = _canonical_rag_execution_mode(output_payload.get("mode"))
            if mode:
                return mode
            quick_payload = output_payload.get("quick_rag")
            if isinstance(quick_payload, dict):
                quick_mode = _canonical_rag_execution_mode(quick_payload.get("mode"))
                if quick_mode:
                    return quick_mode
    return ""


def _is_rag_node_task(task: AgentTask | None) -> bool:
    if task is None:
        return False
    if is_quick_rag_task_kind(task.kind):
        return True
    _prompt_text, prompt_payload = parse_prompt_input(task.prompt)
    if isinstance(prompt_payload, dict):
        flowchart_node_type = str(prompt_payload.get("flowchart_node_type") or "").strip().lower()
        if flowchart_node_type == FLOWCHART_NODE_TYPE_RAG:
            return True
    raw_output = str(task.output or "").strip()
    if raw_output.startswith("{"):
        try:
            output_payload = json.loads(raw_output)
        except json.JSONDecodeError:
            output_payload = {}
        if isinstance(output_payload, dict):
            if str(output_payload.get("node_type") or "").strip().lower() == FLOWCHART_NODE_TYPE_RAG:
                return True
    return False


def _task_stage_label(task: AgentTask, stage_key: str, default_label: str) -> str:
    if stage_key != "llm_query":
        return default_label
    if not _is_rag_node_task(task):
        return default_label
    execution_mode = _task_execution_mode(task)
    if execution_mode == "indexing":
        return "RAG Indexing"
    if execution_mode == "delta_indexing":
        return "RAG Delta Indexing"
    return default_label


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
    return build_runtime_agent_payload(agent)


def _serialize_agent_priority(priority: AgentPriority) -> dict[str, object]:
    return {
        "id": priority.id,
        "position": int(priority.position or 0),
        "content": str(priority.content or ""),
    }


def _serialize_agent_skill(skill: Skill) -> dict[str, object]:
    latest_version = _latest_skill_version(skill)
    return {
        "id": skill.id,
        "name": skill.name,
        "display_name": skill.display_name,
        "status": skill.status,
        "latest_version": latest_version.version if latest_version is not None else None,
    }


def _serialize_role_option(role: Role) -> dict[str, object]:
    return {
        "id": role.id,
        "name": role.name,
    }


def _serialize_role_list_item(
    role: Role,
    *,
    binding_count: int = 0,
) -> dict[str, object]:
    return {
        "id": role.id,
        "name": role.name,
        "description": role.description or "",
        "binding_count": max(0, int(binding_count or 0)),
        "is_system": bool(role.is_system),
        "created_at": _human_time(role.created_at),
        "updated_at": _human_time(role.updated_at),
    }


def _serialize_role_assigned_agent(agent: Agent) -> dict[str, object]:
    return {
        "id": agent.id,
        "name": agent.name,
        "description": agent.description or "",
    }


def _serialize_role_detail(
    role: Role,
    *,
    assigned_agents: list[Agent] | None = None,
) -> dict[str, object]:
    assigned = assigned_agents or []
    details = _load_role_details(role)
    return {
        **_serialize_role_list_item(role, binding_count=len(assigned)),
        "details": details,
        "details_json": json.dumps(details, indent=2, sort_keys=True),
        "assigned_agents": [
            _serialize_role_assigned_agent(agent)
            for agent in assigned
        ],
    }


def _serialize_agent_list_item(
    agent: Agent,
    *,
    role_name: str | None = None,
    status: str = "stopped",
) -> dict[str, object]:
    return {
        "id": agent.id,
        "name": agent.name,
        "description": agent.description or "",
        "is_system": bool(agent.is_system),
        "role_id": agent.role_id,
        "role_name": role_name or "",
        "status": status,
        "last_run_at": _human_time(agent.last_run_at),
        "created_at": _human_time(agent.created_at),
        "updated_at": _human_time(agent.updated_at),
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


def _clone_task_scripts(
    session,
    source_task_id: int,
    target_task_id: int,
) -> None:
    rows = session.execute(
        select(
            agent_task_scripts.c.script_id,
            agent_task_scripts.c.position,
        )
        .where(agent_task_scripts.c.agent_task_id == source_task_id)
        .order_by(agent_task_scripts.c.position.asc(), agent_task_scripts.c.script_id.asc())
    ).all()
    if not rows:
        return
    session.execute(
        agent_task_scripts.insert(),
        [
            {
                "agent_task_id": target_task_id,
                "script_id": int(script_id),
                "position": int(position) if position is not None else None,
            }
            for script_id, position in rows
        ],
    )


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
    for stage_key, default_label in TASK_STAGE_ORDER:
        label = _task_stage_label(task, stage_key, default_label)
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
        chromadb = import_chromadb()
    except (ImportError, ModuleNotFoundError):
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


def _split_csv_values(raw: str | None) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for part in str(raw or "").split(","):
        cleaned = part.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        values.append(cleaned)
    return values


def _resolved_quick_default_settings(
    *,
    agents: list[Agent],
    models: list[LLMModel],
    mcp_servers: list[MCPServer],
    integration_options: list[dict[str, object]],
) -> dict[str, object]:
    settings = _load_integration_settings(QUICK_DEFAULT_SETTINGS_PROVIDER)
    agent_ids = {agent.id for agent in agents}
    model_ids = {model.id for model in models}
    mcp_ids = {server.id for server in mcp_servers}
    integration_option_keys = {
        str(option.get("key") or "").strip()
        for option in integration_options
        if str(option.get("key") or "").strip()
    }
    connected_integration_keys = [
        str(option.get("key") or "").strip()
        for option in integration_options
        if str(option.get("key") or "").strip() and bool(option.get("connected"))
    ]

    resolved_agent_id: int | None = None
    try:
        selected_agent_id = _coerce_optional_int(
            settings.get("default_agent_id"),
            field_name="default_agent_id",
            minimum=1,
        )
        if selected_agent_id is not None and selected_agent_id in agent_ids:
            resolved_agent_id = selected_agent_id
    except ValueError:
        resolved_agent_id = None

    resolved_model_id = _quick_node_default_model_id(models)
    try:
        selected_model_id = _coerce_optional_int(
            settings.get("default_model_id"),
            field_name="default_model_id",
            minimum=1,
        )
        if selected_model_id is not None and selected_model_id in model_ids:
            resolved_model_id = selected_model_id
    except ValueError:
        pass

    selected_mcp_ids = _coerce_chat_id_list(
        _split_csv_values(settings.get("default_mcp_server_ids")),
        field_name="default_mcp_server_id",
    )
    resolved_mcp_server_ids: list[int] = []
    for mcp_id in selected_mcp_ids:
        if mcp_id in mcp_ids and mcp_id not in resolved_mcp_server_ids:
            resolved_mcp_server_ids.append(mcp_id)

    resolved_integration_keys: list[str] = []
    if "default_integration_keys" in settings:
        parsed_integration_keys = _split_csv_values(settings.get("default_integration_keys"))
        valid_keys, _ = validate_task_integration_keys(parsed_integration_keys)
        for key in valid_keys:
            if key in integration_option_keys and key not in resolved_integration_keys:
                resolved_integration_keys.append(key)
    else:
        for key in connected_integration_keys:
            if key in integration_option_keys and key not in resolved_integration_keys:
                resolved_integration_keys.append(key)

    return {
        "default_agent_id": resolved_agent_id,
        "default_model_id": resolved_model_id,
        "default_mcp_server_ids": resolved_mcp_server_ids,
        "default_integration_keys": resolved_integration_keys,
    }


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
        "use_vertex_ai": _normalize_optional_bool(config.get("use_vertex_ai")),
        "project": str(config.get("project") or ""),
        "location": str(config.get("location") or ""),
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
        use_vertex_raw = form.get("gemini_use_vertex_ai", "").strip().lower()
        use_vertex_value = None
        if use_vertex_raw == "true":
            use_vertex_value = True
        elif use_vertex_raw == "false":
            use_vertex_value = False
        return {
            "model": form.get("gemini_model", "").strip(),
            "approval_mode": form.get("gemini_approval_mode", "").strip(),
            "sandbox": sandbox_value,
            "use_vertex_ai": use_vertex_value,
            "project": form.get("gemini_project", "").strip(),
            "location": form.get("gemini_location", "").strip(),
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
        "use_vertex_ai": _as_bool(settings.get("gemini_use_vertex_ai")),
        "project": settings.get("gemini_project") or "",
        "location": settings.get("gemini_location") or "",
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


def _jira_project_options(settings: dict[str, str]) -> list[dict[str, str]]:
    return _merge_selected_option(
        _parse_option_entries(settings.get("project_options")),
        settings.get("project_key"),
    )


def _jira_board_options(settings: dict[str, str]) -> list[dict[str, str]]:
    options = _parse_option_entries(settings.get("board_options"))
    selected_board = (settings.get("board") or "").strip()
    selected_label = (settings.get("board_label") or "").strip()
    if selected_board and all(
        option.get("value") != selected_board for option in options
    ):
        options.insert(
            0,
            {
                "value": selected_board,
                "label": selected_label or selected_board,
            },
        )
    return options


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
        jira_project_options = _jira_project_options(jira_settings)

    if jira_board_options is None:
        jira_board_options = _jira_board_options(jira_settings)

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
    context = _settings_integrations_context(
        integration_section=section,
        gitconfig_content=gitconfig_content,
        github_repo_options=github_repo_options,
        jira_project_options=jira_project_options,
        jira_board_options=jira_board_options,
        confluence_space_options=confluence_space_options,
    )
    if _workflow_wants_json():
        return {
            "integration_section": section,
            "integration_sections": [
                {
                    "id": key,
                    "label": value["label"],
                }
                for key, value in INTEGRATION_SETTINGS_SECTIONS.items()
            ],
            **context,
        }
    return render_template(
        "settings_integrations.html",
        integration_section=section,
        page_title=f"Settings - Integrations - {section_meta['label']}",
        **context,
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
                        name_raw = item.get("name")
                        if not isinstance(name_raw, str):
                            continue
                        name = name_raw.strip()
                        if not name:
                            continue
                        board_id = item.get("id")
                        if isinstance(board_id, int):
                            value = str(board_id)
                        elif isinstance(board_id, str):
                            value = board_id.strip()
                        else:
                            value = name
                        if not value or value in seen:
                            continue
                        label = name
                        location = item.get("location")
                        if isinstance(location, dict):
                            location_project = location.get("projectKey")
                            if isinstance(location_project, str):
                                cleaned_project = location_project.strip()
                                if cleaned_project:
                                    label = f"{label} ({cleaned_project})"
                        boards.append({"value": value, "label": label})
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


def _fetch_jira_board_by_id(
    api_key: str,
    site: str,
    board_id: int,
) -> dict[str, object] | None:
    if not api_key or not site or board_id < 1:
        return None
    base = _normalize_atlassian_site(site)
    if not base:
        return None
    headers = _build_atlassian_headers(api_key)
    url = f"{base}/rest/agile/1.0/board/{board_id}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except HTTPError as exc:
        body_snippet = _error_body_snippet(exc)
        logger.warning(
            "Jira board lookup by id: HTTP error code=%s url=%s body=%s",
            exc.code,
            url,
            body_snippet,
        )
        if exc.code in {401, 403}:
            raise ValueError("Jira API key is invalid or lacks board access.") from exc
        if exc.code == 404:
            return None
        raise ValueError("Jira API error while fetching board.") from exc
    except URLError as exc:
        logger.warning("Jira board lookup by id: network error url=%s", url)
        raise ValueError("Unable to reach Jira API.") from exc
    if isinstance(payload, dict):
        return payload
    return None


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
    flowchart_node_id: int | None = None,
) -> tuple[list[AgentTask], int, int, int]:
    with session_scope() as session:
        filters = []
        if agent_id is not None:
            filters.append(AgentTask.agent_id == agent_id)
        if flowchart_node_id is not None:
            filters.append(AgentTask.flowchart_node_id == flowchart_node_id)
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


def _parse_json_dict(raw: str | dict[str, object] | None) -> dict[str, object]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_json_list(raw: str | list[object] | None) -> list[object]:
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def _format_json_object_for_display(raw: str | dict[str, object] | None) -> str:
    payload = _parse_json_dict(raw)
    return json.dumps(payload, indent=2, sort_keys=True)


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


def _request_path_uses_api_prefix() -> bool:
    api_prefix = str(current_app.config.get("API_PREFIX", "/api")).strip() or "/api"
    if api_prefix == "/":
        return False
    normalized_prefix = f"/{api_prefix.strip('/')}"
    path = request.path or ""
    return path == normalized_prefix or path.startswith(f"{normalized_prefix}/")


def _agents_wants_json() -> bool:
    if _request_path_uses_api_prefix():
        return True
    if (request.args.get("format") or "").strip().lower() == "json":
        return True
    accepted = request.accept_mimetypes
    return (
        accepted["application/json"] > 0
        and accepted["application/json"] >= accepted["text/html"]
    )


def _agent_api_request() -> bool:
    return _request_path_uses_api_prefix() or request.is_json


def _nodes_wants_json() -> bool:
    if _request_path_uses_api_prefix():
        return True
    if (request.args.get("format") or "").strip().lower() == "json":
        return True
    accepted = request.accept_mimetypes
    return (
        accepted["application/json"] > 0
        and accepted["application/json"] >= accepted["text/html"]
    )


def _stage3_api_request() -> bool:
    return _request_path_uses_api_prefix() or request.is_json


def _workflow_wants_json() -> bool:
    if _request_path_uses_api_prefix():
        return True
    if (request.args.get("format") or "").strip().lower() == "json":
        return True
    accepted = request.accept_mimetypes
    return (
        accepted["application/json"] > 0
        and accepted["application/json"] >= accepted["text/html"]
    )


def _workflow_api_request() -> bool:
    return _request_path_uses_api_prefix() or request.is_json


def _settings_request_payload() -> dict[str, object]:
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        return payload
    return {}


def _settings_form_value(
    payload: dict[str, object],
    key: str,
    default: str = "",
) -> str:
    if key in payload:
        value = payload.get(key)
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)
    return request.form.get(key, default)


def _settings_form_list(payload: dict[str, object], key: str) -> list[str]:
    if key in payload:
        raw = payload.get(key)
        if raw is None:
            return []
        if isinstance(raw, list):
            return [str(item) for item in raw if item is not None]
        return [str(raw)]
    return request.form.getlist(key)


def _flowchart_wants_json() -> bool:
    if _request_path_uses_api_prefix():
        return True
    if (request.args.get("format") or "").strip().lower() == "json":
        return True
    accepted = request.accept_mimetypes
    return (
        accepted["application/json"] > 0
        and accepted["application/json"] >= accepted["text/html"]
    )


def _run_wants_json() -> bool:
    if _request_path_uses_api_prefix():
        return True
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


def _coerce_optional_bool(
    value: object,
    *,
    field_name: str,
) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if not cleaned:
            return None
        if cleaned in {"1", "true", "yes", "on"}:
            return True
        if cleaned in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"{field_name} must be a boolean.")
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
        raise ValueError(f"{field_name} must be a boolean.")
    raise ValueError(f"{field_name} must be a boolean.")


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


def _coerce_flowchart_edge_control_points(
    value: object, *, field_name: str
) -> list[dict[str, float]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array.")
    normalized: list[dict[str, float]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"{field_name}[{index}] must be an object.")
        x = _coerce_float(item.get("x"), field_name=f"{field_name}[{index}].x")
        y = _coerce_float(item.get("y"), field_name=f"{field_name}[{index}].y")
        normalized.append({"x": round(x, 2), "y": round(y, 2)})
        if len(normalized) >= 24:
            break
    return normalized


FLOWCHART_EDGE_CONTROL_STYLE_HARD = "hard"
FLOWCHART_EDGE_CONTROL_STYLE_CURVED = "curved"
FLOWCHART_EDGE_CONTROL_STYLE_CHOICES = {
    FLOWCHART_EDGE_CONTROL_STYLE_HARD,
    FLOWCHART_EDGE_CONTROL_STYLE_CURVED,
}


def _coerce_flowchart_edge_control_style(value: object, *, field_name: str) -> str:
    cleaned = str(value or "").strip().lower()
    if not cleaned:
        return FLOWCHART_EDGE_CONTROL_STYLE_HARD
    if cleaned not in FLOWCHART_EDGE_CONTROL_STYLE_CHOICES:
        raise ValueError(
            f"{field_name} must be one of {', '.join(sorted(FLOWCHART_EDGE_CONTROL_STYLE_CHOICES))}."
        )
    return cleaned


def _flowchart_edge_control_geometry(
    value: object,
) -> tuple[list[dict[str, float]], str]:
    payload = value
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return [], FLOWCHART_EDGE_CONTROL_STYLE_HARD
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            return [], FLOWCHART_EDGE_CONTROL_STYLE_HARD
    if isinstance(payload, dict):
        raw_points = payload.get("points")
        raw_style = payload.get("style")
    elif isinstance(payload, list):
        raw_points = payload
        raw_style = FLOWCHART_EDGE_CONTROL_STYLE_HARD
    else:
        return [], FLOWCHART_EDGE_CONTROL_STYLE_HARD
    try:
        points = _coerce_flowchart_edge_control_points(
            raw_points,
            field_name="edge.control_points",
        )
    except ValueError:
        points = []
    try:
        style = _coerce_flowchart_edge_control_style(
            raw_style,
            field_name="edge.control_point_style",
        )
    except ValueError:
        style = FLOWCHART_EDGE_CONTROL_STYLE_HARD
    return points, style


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


def _normalized_decision_conditions(
    value: object,
) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, str]] = []
    seen_connector_ids: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        connector_id = str(item.get("connector_id") or "").strip()
        if not connector_id or connector_id in seen_connector_ids:
            continue
        seen_connector_ids.add(connector_id)
        normalized.append(
            {
                "connector_id": connector_id,
                "condition_text": str(item.get("condition_text") or "").strip(),
            }
        )
    return normalized


def _normalize_flowchart_fan_in_mode(value: object, *, field_name: str) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in {"", FLOWCHART_FAN_IN_MODE_ALL}:
        return FLOWCHART_FAN_IN_MODE_ALL
    if cleaned == FLOWCHART_FAN_IN_MODE_ANY:
        return FLOWCHART_FAN_IN_MODE_ANY
    if cleaned in {"custom_n", "custom-n", FLOWCHART_FAN_IN_MODE_CUSTOM}:
        return FLOWCHART_FAN_IN_MODE_CUSTOM
    raise ValueError(
        f"{field_name} must be one of: "
        + ", ".join(FLOWCHART_FAN_IN_MODE_CHOICES)
        + "."
    )


def _normalize_decision_no_match_policy(value: object, *, field_name: str) -> str:
    cleaned = str(value or "").strip().lower()
    if not cleaned:
        return ""
    if cleaned in FLOWCHART_DECISION_NO_MATCH_POLICY_CHOICES:
        return cleaned
    raise ValueError(
        f"{field_name} must be one of: "
        + ", ".join(FLOWCHART_DECISION_NO_MATCH_POLICY_CHOICES)
        + "."
    )


def _sanitize_flowchart_node_routing_config(
    config_payload: dict[str, object],
    *,
    field_prefix: str,
) -> dict[str, object]:
    sanitized = dict(config_payload)
    fan_in_mode = _normalize_flowchart_fan_in_mode(
        sanitized.get("fan_in_mode"),
        field_name=f"{field_prefix}.fan_in_mode",
    )
    if fan_in_mode == FLOWCHART_FAN_IN_MODE_ALL:
        sanitized.pop("fan_in_mode", None)
        sanitized.pop("fan_in_custom_count", None)
    elif fan_in_mode == FLOWCHART_FAN_IN_MODE_ANY:
        sanitized["fan_in_mode"] = FLOWCHART_FAN_IN_MODE_ANY
        sanitized.pop("fan_in_custom_count", None)
    else:
        fan_in_custom_count = _coerce_optional_int(
            sanitized.get("fan_in_custom_count"),
            field_name=f"{field_prefix}.fan_in_custom_count",
            minimum=1,
        )
        if fan_in_custom_count is None:
            raise ValueError(
                f"{field_prefix}.fan_in_custom_count is required when fan_in_mode is custom."
            )
        sanitized["fan_in_mode"] = FLOWCHART_FAN_IN_MODE_CUSTOM
        sanitized["fan_in_custom_count"] = fan_in_custom_count

    no_match_policy = _normalize_decision_no_match_policy(
        sanitized.get("no_match_policy"),
        field_name=f"{field_prefix}.no_match_policy",
    )
    fallback_condition_key = str(sanitized.get("fallback_condition_key") or "").strip()
    if fallback_condition_key:
        sanitized["fallback_condition_key"] = fallback_condition_key
    else:
        sanitized.pop("fallback_condition_key", None)
    if no_match_policy:
        sanitized["no_match_policy"] = no_match_policy
    else:
        sanitized.pop("no_match_policy", None)
    if (
        no_match_policy == FLOWCHART_DECISION_NO_MATCH_POLICY_FALLBACK
        and not fallback_condition_key
    ):
        raise ValueError(
            f"{field_prefix}.fallback_condition_key is required when no_match_policy is fallback."
        )
    return sanitized


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
    control_points, control_point_style = _flowchart_edge_control_geometry(
        edge.control_points_json
    )
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
        "control_points": control_points,
        "control_point_style": control_point_style,
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


def _normalize_flowchart_run_status(status: object) -> str:
    return str(status or "").strip().lower()


def _flowchart_build_replay_marker(*, action: str, replay_run_id: int) -> str:
    return f"flowchart-replay:{str(action).strip().lower()}:{int(replay_run_id)}"


def _flowchart_parse_replay_marker(value: object) -> tuple[str, int] | None:
    raw = str(value or "").strip()
    if not raw.startswith("flowchart-replay:"):
        return None
    parts = raw.split(":", 2)
    if len(parts) != 3:
        return None
    action = str(parts[1] or "").strip().lower()
    try:
        replay_run_id = int(parts[2])
    except ValueError:
        return None
    if action not in FLOWCHART_RUN_CONTROL_REPLAY_ACTIONS or replay_run_id <= 0:
        return None
    return action, replay_run_id


def _flowchart_trace_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _flowchart_trace_optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ValueError("value must be a boolean.")


def _flowchart_trace_paginate(
    rows: list[dict[str, object]],
    *,
    limit: int,
    offset: int,
) -> dict[str, object]:
    page_rows = rows[offset : offset + limit]
    return {
        "items": page_rows,
        "total_count": len(rows),
        "limit": limit,
        "offset": offset,
    }


def _flowchart_trace_request_identity(
    *,
    output_state: dict[str, object] | None,
    routing_state: dict[str, object] | None,
) -> tuple[str | None, str | None]:
    output_payload = output_state if isinstance(output_state, dict) else {}
    routing_payload = routing_state if isinstance(routing_state, dict) else {}

    def _tooling_payload(source: dict[str, object]) -> dict[str, object]:
        tooling = source.get("deterministic_tooling")
        return tooling if isinstance(tooling, dict) else {}

    output_tooling = _tooling_payload(output_payload)
    routing_tooling = _tooling_payload(routing_payload)
    request_id = _flowchart_trace_text(
        output_tooling.get("request_id")
        or routing_tooling.get("request_id")
        or output_payload.get("request_id")
        or routing_payload.get("request_id")
    )
    correlation_id = _flowchart_trace_text(
        output_tooling.get("correlation_id")
        or routing_tooling.get("correlation_id")
        or output_payload.get("correlation_id")
        or routing_payload.get("correlation_id")
    )
    return request_id, correlation_id


def _flowchart_trace_warning_entries(
    *,
    node_run: FlowchartRunNode,
    output_state: dict[str, object] | None,
    routing_state: dict[str, object] | None,
) -> list[dict[str, object]]:
    warnings: list[dict[str, object]] = []
    if bool(node_run.degraded_status):
        warnings.append(
            {
                "kind": "degraded",
                "message": str(node_run.degraded_reason or "degraded_execution"),
            }
        )
    output_payload = output_state if isinstance(output_state, dict) else {}
    routing_payload = routing_state if isinstance(routing_state, dict) else {}
    tooling_payload = (
        output_payload.get("deterministic_tooling")
        if isinstance(output_payload.get("deterministic_tooling"), dict)
        else routing_payload.get("deterministic_tooling")
        if isinstance(routing_payload.get("deterministic_tooling"), dict)
        else {}
    )
    tool_warnings = tooling_payload.get("warnings") if isinstance(tooling_payload, dict) else []
    if isinstance(tool_warnings, list):
        for item in tool_warnings:
            if isinstance(item, dict):
                warnings.append(
                    {
                        "kind": str(item.get("code") or item.get("kind") or "tool_warning"),
                        "message": str(item.get("message") or "warning").strip(),
                        "details": item.get("details") if isinstance(item.get("details"), dict) else {},
                    }
                )
            else:
                text = str(item or "").strip()
                if text:
                    warnings.append({"kind": "tool_warning", "message": text})
    return warnings


def _k8s_job_name_from_dispatch_id(provider_dispatch_id: str) -> str:
    dispatch_id = str(provider_dispatch_id or "").strip()
    if not dispatch_id.startswith("kubernetes:"):
        return ""
    native_id = dispatch_id.split(":", 1)[1]
    if "/" not in native_id:
        return ""
    return native_id.split("/", 1)[1].strip()


def _runtime_evidence_from_output(task: AgentTask | None) -> dict[str, str]:
    if task is None:
        return {
            "provider_dispatch_id": "",
            "k8s_job_name": "",
            "k8s_pod_name": "",
            "k8s_terminal_reason": "",
        }
    evidence: dict[str, str] = {
        "provider_dispatch_id": "",
        "k8s_job_name": "",
        "k8s_pod_name": "",
        "k8s_terminal_reason": "",
    }
    raw_output = str(task.output or "").strip()
    if raw_output.startswith("{"):
        try:
            output_payload = json.loads(raw_output)
        except json.JSONDecodeError:
            output_payload = {}
        if isinstance(output_payload, dict):
            runtime_evidence = output_payload.get("runtime_evidence")
            if isinstance(runtime_evidence, dict):
                for key in evidence:
                    value = runtime_evidence.get(key)
                    if value is None:
                        continue
                    evidence[key] = str(value).strip()
    provider_dispatch_id = (
        evidence["provider_dispatch_id"] or str(task.provider_dispatch_id or "").strip()
    )
    evidence["provider_dispatch_id"] = provider_dispatch_id
    if not evidence["k8s_job_name"]:
        evidence["k8s_job_name"] = _k8s_job_name_from_dispatch_id(provider_dispatch_id)
    if not evidence["k8s_terminal_reason"]:
        evidence["k8s_terminal_reason"] = (
            str(task.fallback_reason or "").strip()
            or str(task.api_failure_category or "").strip()
            or str(task.status or "").strip()
        )
    return evidence


def _serialize_node_executor_metadata(task: AgentTask | None) -> dict[str, object]:
    if task is None:
        return {
            "selected_provider": "",
            "final_provider": "",
            "provider_dispatch_id": "",
            "execution_mode": "",
            "workspace_identity": "",
            "dispatch_status": "",
            "fallback_attempted": False,
            "fallback_reason": "",
            "dispatch_uncertain": False,
            "api_failure_category": "",
            "cli_fallback_used": False,
            "cli_preflight_passed": None,
            "k8s_job_name": "",
            "k8s_pod_name": "",
            "k8s_terminal_reason": "",
            "provider_route": "",
            "dispatch_timeline": [],
        }
    selected_provider = str(task.selected_provider or "").strip()
    final_provider = str(task.final_provider or "").strip()
    provider_dispatch_id = str(task.provider_dispatch_id or "").strip()
    execution_mode = _task_execution_mode(task)
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
    runtime_evidence = _runtime_evidence_from_output(task)
    provider_dispatch_id = (
        str(runtime_evidence.get("provider_dispatch_id") or "").strip()
        or provider_dispatch_id
    )
    k8s_job_name = str(runtime_evidence.get("k8s_job_name") or "").strip()
    k8s_pod_name = str(runtime_evidence.get("k8s_pod_name") or "").strip()
    k8s_terminal_reason = str(runtime_evidence.get("k8s_terminal_reason") or "").strip()
    timeline: list[str] = []
    if selected_provider:
        timeline.append(f"selected={selected_provider}")
    if provider_dispatch_id:
        timeline.append(f"dispatch_id={provider_dispatch_id}")
    if k8s_job_name:
        timeline.append(f"job={k8s_job_name}")
    if k8s_pod_name:
        timeline.append(f"pod={k8s_pod_name}")
    if dispatch_status:
        timeline.append(f"dispatch={dispatch_status}")
    if k8s_terminal_reason:
        timeline.append(f"terminal={k8s_terminal_reason}")
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
        "execution_mode": execution_mode,
        "workspace_identity": workspace_identity,
        "dispatch_status": dispatch_status,
        "fallback_attempted": fallback_attempted,
        "fallback_reason": fallback_reason,
        "dispatch_uncertain": dispatch_uncertain,
        "api_failure_category": api_failure_category,
        "cli_fallback_used": cli_fallback_used,
        "cli_preflight_passed": cli_preflight_passed,
        "k8s_job_name": k8s_job_name,
        "k8s_pod_name": k8s_pod_name,
        "k8s_terminal_reason": k8s_terminal_reason,
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


def _serialize_run_list_item(run: Run) -> dict[str, object]:
    agent = run.agent
    return {
        "id": run.id,
        "name": run.name or (f"Autorun for {agent.name}" if agent is not None else f"Autorun {run.id}"),
        "agent_id": run.agent_id,
        "agent_name": agent.name if agent is not None else "",
        "status": run.status,
        "task_id": run.task_id,
        "last_run_task_id": run.last_run_task_id,
        "run_max_loops": run.run_max_loops,
        "run_end_requested": bool(run.run_end_requested),
        "created_at": _human_time(run.created_at),
        "last_started_at": _human_time(run.last_started_at),
        "last_stopped_at": _human_time(run.last_stopped_at),
        "updated_at": _human_time(run.updated_at),
    }


def _serialize_node_list_item(
    task: AgentTask,
    *,
    agent_name: str = "",
    node_type: str | None = None,
    node_name: str = "",
) -> dict[str, object]:
    metadata = _serialize_node_executor_metadata(task)
    return {
        "id": task.id,
        "agent_id": task.agent_id,
        "agent_name": agent_name,
        "node_type": node_type or "",
        "node_name": node_name or "-",
        "status": task.status,
        "kind": task.kind or "",
        "run_task_id": task.run_task_id,
        "celery_task_id": task.celery_task_id,
        "started_at": _human_time(task.started_at),
        "finished_at": _human_time(task.finished_at),
        "created_at": _human_time(task.created_at),
        "updated_at": _human_time(task.updated_at),
        **metadata,
    }


def _serialize_workflow_pagination(pagination: dict[str, object]) -> dict[str, object]:
    page_items = pagination.get("page_items")
    items: list[dict[str, object]] = []
    if isinstance(page_items, list):
        for entry in page_items:
            if not isinstance(entry, dict):
                continue
            if bool(entry.get("is_gap")):
                items.append({"type": "gap"})
                continue
            label = str(entry.get("label") or "").strip()
            try:
                parsed_page = int(label)
            except ValueError:
                continue
            items.append(
                {
                    "type": "page",
                    "page": parsed_page,
                    "is_current": bool(entry.get("is_current")),
                }
            )
    return {
        "page": int(pagination.get("page") or 1),
        "per_page": int(pagination.get("per_page") or WORKFLOW_LIST_PER_PAGE),
        "total_pages": int(pagination.get("total_pages") or 1),
        "total_count": int(pagination.get("total_count") or 0),
        "start_index": int(pagination.get("start_index") or 0),
        "end_index": int(pagination.get("end_index") or 0),
        "page_sizes": [int(item) for item in (pagination.get("page_sizes") or [])],
        "items": items,
    }


def _serialize_plan_task(task: PlanTask) -> dict[str, object]:
    return {
        "id": task.id,
        "plan_stage_id": task.plan_stage_id,
        "name": task.name,
        "description": task.description or "",
        "position": task.position,
        "completed_at": _human_time(task.completed_at),
        "created_at": _human_time(task.created_at),
        "updated_at": _human_time(task.updated_at),
    }


def _serialize_plan_stage(stage: PlanStage, *, include_tasks: bool = False) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": stage.id,
        "plan_id": stage.plan_id,
        "name": stage.name,
        "description": stage.description or "",
        "position": stage.position,
        "completed_at": _human_time(stage.completed_at),
        "created_at": _human_time(stage.created_at),
        "updated_at": _human_time(stage.updated_at),
    }
    if include_tasks:
        payload["tasks"] = [_serialize_plan_task(task) for task in (stage.tasks or [])]
    return payload


def _serialize_plan(plan: Plan, *, include_stages: bool = False) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": plan.id,
        "name": plan.name,
        "description": plan.description or "",
        "completed_at": _human_time(plan.completed_at),
        "created_at": _human_time(plan.created_at),
        "updated_at": _human_time(plan.updated_at),
    }
    if include_stages:
        payload["stages"] = [
            _serialize_plan_stage(stage, include_tasks=True)
            for stage in (plan.stages or [])
        ]
    return payload


def _serialize_plan_list_item(
    plan: Plan,
    *,
    stage_count: int,
    task_count: int,
) -> dict[str, object]:
    return {
        **_serialize_plan(plan, include_stages=False),
        "stage_count": int(stage_count or 0),
        "task_count": int(task_count or 0),
    }


def _serialize_milestone(milestone: Milestone) -> dict[str, object]:
    status_value = _milestone_status_value(milestone)
    priority_value = _milestone_priority_value(milestone)
    health_value = _milestone_health_value(milestone)
    progress_value = _milestone_progress_value(milestone)
    return {
        "id": milestone.id,
        "name": milestone.name,
        "description": milestone.description or "",
        "status": status_value,
        "status_label": MILESTONE_STATUS_LABELS.get(status_value, status_value),
        "status_class": MILESTONE_STATUS_CLASSES.get(status_value, "status-idle"),
        "priority": priority_value,
        "priority_label": MILESTONE_PRIORITY_LABELS.get(priority_value, priority_value),
        "owner": milestone.owner or "",
        "completed": bool(milestone.completed),
        "start_date": _human_time(milestone.start_date),
        "due_date": _human_time(milestone.due_date),
        "progress_percent": progress_value,
        "health": health_value,
        "health_label": MILESTONE_HEALTH_LABELS.get(health_value, health_value),
        "health_class": MILESTONE_HEALTH_CLASSES.get(health_value, "status-idle"),
        "success_criteria": milestone.success_criteria or "",
        "dependencies": milestone.dependencies or "",
        "links": milestone.links or "",
        "latest_update": milestone.latest_update or "",
        "created_at": _human_time(milestone.created_at),
        "updated_at": _human_time(milestone.updated_at),
    }


def _serialize_memory(memory: Memory) -> dict[str, object]:
    return {
        "id": memory.id,
        "description": memory.description,
        "created_at": _human_time(memory.created_at),
        "updated_at": _human_time(memory.updated_at),
    }


def _serialize_memory_node_row(
    memory: Memory,
    flowchart_node: FlowchartNode,
    *,
    flowchart_name: str | None = None,
) -> dict[str, object]:
    payload = _serialize_memory(memory)
    payload.update(
        {
            "flowchart_id": flowchart_node.flowchart_id,
            "flowchart_name": flowchart_name or f"Flowchart {flowchart_node.flowchart_id}",
            "flowchart_node_id": flowchart_node.id,
            "flowchart_node_title": flowchart_node.title or "",
            "node_created_at": _human_time(flowchart_node.created_at),
            "node_updated_at": _human_time(flowchart_node.updated_at),
        }
    )
    return payload


def _model_compatibility_contract(
    provider: str,
    config_payload: dict[str, object],
) -> dict[str, object]:
    normalized_provider = str(provider or "").strip().lower()
    expected_keys = tuple(MODEL_COMPATIBILITY_KEYS.get(normalized_provider, tuple()))
    provided_keys = tuple(
        sorted(
            {
                str(key).strip()
                for key in config_payload.keys()
                if str(key).strip()
            }
        )
    )
    if not expected_keys:
        return {
            "contract_version": MODEL_PROVIDER_API_CONTRACT_VERSION,
            "status": "unsupported_provider",
            "drift_detected": False,
            "provider": normalized_provider,
            "expected_keys": [],
            "provided_keys": list(provided_keys),
            "missing_keys": [],
            "unsupported_keys": [],
        }
    expected_set = set(expected_keys)
    provided_set = set(provided_keys)
    missing_keys = sorted(expected_set.difference(provided_set))
    unsupported_keys = sorted(provided_set.difference(expected_set))
    drift_detected = bool(missing_keys or unsupported_keys)
    return {
        "contract_version": MODEL_PROVIDER_API_CONTRACT_VERSION,
        "status": "drift_detected" if drift_detected else "in_sync",
        "drift_detected": drift_detected,
        "provider": normalized_provider,
        "expected_keys": list(expected_keys),
        "provided_keys": list(provided_keys),
        "missing_keys": missing_keys,
        "unsupported_keys": unsupported_keys,
    }


def _serialize_model(
    model: LLMModel,
    *,
    default_model_id: int | None = None,
    include_config: bool = False,
) -> dict[str, object]:
    config_payload = _decode_model_config(model.config_json)
    compatibility = _model_compatibility_contract(model.provider, config_payload)
    payload: dict[str, object] = {
        "id": model.id,
        "name": model.name,
        "description": model.description or "",
        "provider": model.provider,
        "provider_label": LLM_PROVIDER_LABELS.get(model.provider, model.provider),
        "model_name": _model_display_name(model),
        "is_default": default_model_id is not None and model.id == default_model_id,
        "compatibility": compatibility,
        "created_at": _human_time(model.created_at),
        "updated_at": _human_time(model.updated_at),
    }
    if include_config:
        payload["config"] = config_payload
        payload["config_json"] = _format_json_object_for_display(model.config_json)
    return payload


def _safe_relationship_count(loader) -> int:
    try:
        values = loader()
    except DetachedInstanceError:
        return 0
    return len(values or [])


def _serialize_mcp_server(
    mcp_server: MCPServer,
    *,
    include_config: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": mcp_server.id,
        "name": mcp_server.name,
        "server_key": mcp_server.server_key,
        "description": mcp_server.description or "",
        "server_type": mcp_server.server_type or MCP_SERVER_TYPE_CUSTOM,
        "is_integrated": bool(mcp_server.is_integrated),
        "binding_count": _safe_relationship_count(lambda: mcp_server.flowchart_nodes)
        + _safe_relationship_count(lambda: mcp_server.tasks),
        "created_at": _human_time(mcp_server.created_at),
        "updated_at": _human_time(mcp_server.updated_at),
    }
    if include_config:
        payload["config"] = _parse_json_dict(mcp_server.config_json)
        payload["config_json"] = _format_json_object_for_display(mcp_server.config_json)
    return payload


def _serialize_script(
    script: Script,
    *,
    include_content: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": script.id,
        "file_name": script.file_name,
        "description": script.description or "",
        "script_type": script.script_type,
        "script_type_label": _script_type_label(script.script_type),
        "file_path": script.file_path,
        "binding_count": _safe_relationship_count(lambda: script.tasks)
        + _safe_relationship_count(lambda: script.flowchart_nodes),
        "created_at": _human_time(script.created_at),
        "updated_at": _human_time(script.updated_at),
    }
    if include_content:
        payload["content"] = _read_script_content(script)
    return payload


def _serialize_skill(skill: Skill) -> dict[str, object]:
    latest_version = _latest_skill_version(skill)
    return {
        "id": skill.id,
        "name": skill.name,
        "display_name": skill.display_name,
        "description": skill.description or "",
        "status": skill.status,
        "source_type": skill.source_type,
        "source_ref": skill.source_ref,
        "is_git_read_only": _is_git_based_skill(skill),
        "version_count": len(skill.versions or []),
        "latest_version": latest_version.version if latest_version is not None else None,
        "binding_count": _safe_relationship_count(lambda: skill.agents),
        "created_at": _human_time(skill.created_at),
        "updated_at": _human_time(skill.updated_at),
    }


def _serialize_attachment(attachment: Attachment) -> dict[str, object]:
    is_image = _is_image_attachment(attachment)
    preview_url = (
        url_for("agents.view_attachment_file", attachment_id=attachment.id)
        if is_image and attachment.file_path
        else None
    )
    return {
        "id": attachment.id,
        "file_name": attachment.file_name,
        "file_path": attachment.file_path,
        "content_type": attachment.content_type,
        "size_bytes": attachment.size_bytes,
        "is_image": is_image,
        "preview_url": preview_url,
        "binding_count": _safe_relationship_count(lambda: attachment.tasks)
        + _safe_relationship_count(lambda: attachment.flowchart_nodes),
        "created_at": _human_time(attachment.created_at),
        "updated_at": _human_time(attachment.updated_at),
    }


def _serialize_choice_options(
    options: tuple[tuple[str, str], ...],
) -> list[dict[str, str]]:
    return [{"value": value, "label": label} for value, label in options]


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
    artifact_history: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    input_context = _parse_json_dict(node_run.input_context_json)
    trigger_sources, pulled_dotted_sources = _flowchart_run_node_context_trace(
        input_context
    )
    run_metadata = _serialize_node_executor_metadata(task)
    routing_state = _parse_json_dict(node_run.routing_state_json)
    runtime_evidence = routing_state.get("runtime_evidence")
    if isinstance(runtime_evidence, dict):
        provider_dispatch_id = str(
            runtime_evidence.get("provider_dispatch_id")
            or run_metadata.get("provider_dispatch_id")
            or ""
        ).strip()
        k8s_job_name = str(
            runtime_evidence.get("k8s_job_name")
            or run_metadata.get("k8s_job_name")
            or _k8s_job_name_from_dispatch_id(provider_dispatch_id)
            or ""
        ).strip()
        k8s_pod_name = str(
            runtime_evidence.get("k8s_pod_name")
            or run_metadata.get("k8s_pod_name")
            or ""
        ).strip()
        k8s_terminal_reason = str(
            runtime_evidence.get("k8s_terminal_reason")
            or run_metadata.get("k8s_terminal_reason")
            or ""
        ).strip()
        run_metadata["provider_dispatch_id"] = provider_dispatch_id
        run_metadata["k8s_job_name"] = k8s_job_name
        run_metadata["k8s_pod_name"] = k8s_pod_name
        run_metadata["k8s_terminal_reason"] = k8s_terminal_reason
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
        "output_contract_version": node_run.output_contract_version,
        "routing_contract_version": node_run.routing_contract_version,
        "degraded_status": bool(node_run.degraded_status),
        "degraded_reason": node_run.degraded_reason,
        "idempotency_key": node_run.idempotency_key,
        "output_state": _parse_json_dict(node_run.output_state_json),
        "routing_state": routing_state,
        "artifact_history": artifact_history or [],
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
        output = (node_run.output_state_json or "").strip() or None
        task = AgentTask.create(
            session,
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


def _is_rag_embedding_model(model: LLMModel | None) -> bool:
    if model is None:
        return False
    if not _is_rag_embedding_model_provider(model.provider):
        return False
    config = _decode_model_config(model.config_json)
    if bool(config.get("embedding_model")):
        return True
    model_name = str(config.get("model") or "").strip().lower()
    display_name = str(model.name or "").strip().lower()
    return "embed" in model_name or "embed" in display_name


def _ensure_flowchart_catalog_embedding_model(session) -> None:
    embedding_candidates: list[LLMModel] = (
        session.execute(
            select(LLMModel).where(LLMModel.provider.in_(["codex", "gemini"]))
        )
        .scalars()
        .all()
    )
    existing_names = {
        str(name or "").strip()
        for name in session.execute(select(LLMModel.name)).scalars().all()
        if str(name or "").strip()
    }
    existing_by_provider_and_model = {
        (
            str(model.provider or "").strip().lower(),
            str(_decode_model_config(model.config_json).get("model") or "").strip().lower(),
        )
        for model in embedding_candidates
        if _is_rag_embedding_model(model)
        and str(_decode_model_config(model.config_json).get("model") or "").strip()
    }
    rag_config = load_rag_config()
    desired_embedding_models: list[tuple[str, str]] = [
        ("codex", str(rag_config.openai_embedding_model or "").strip() or "text-embedding-3-small"),
        ("gemini", str(rag_config.gemini_embedding_model or "").strip() or "models/gemini-embedding-001"),
    ]

    def _unique_auto_name(base_name: str) -> str:
        next_name = base_name
        suffix = 2
        while next_name in existing_names:
            next_name = f"{base_name} {suffix}"
            suffix += 1
        existing_names.add(next_name)
        return next_name

    for provider, model_name in desired_embedding_models:
        normalized_provider = str(provider or "").strip().lower()
        normalized_model_name = str(model_name or "").strip()
        if not normalized_model_name:
            continue
        signature = (normalized_provider, normalized_model_name.lower())
        if signature in existing_by_provider_and_model:
            continue
        provider_label = LLM_PROVIDER_LABELS.get(normalized_provider, normalized_provider)
        next_name = _unique_auto_name(f"RAG Embedding Model ({provider_label}) (Auto)")
        LLMModel.create(
            session,
            name=next_name,
            description="Auto-created embedding model for Flowchart RAG index modes.",
            provider=normalized_provider,
            config_json=json.dumps(
                {"model": normalized_model_name, "embedding_model": True},
                sort_keys=True,
            ),
        )
        existing_by_provider_and_model.add(signature)


def _flowchart_catalog(session) -> dict[str, object]:
    _ensure_flowchart_catalog_embedding_model(session)
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
    memory_rows = []
    for memory in memories:
        description = str(memory.description or "").strip()
        if description:
            title = description.splitlines()[0].strip() or f"Memory {memory.id}"
        else:
            title = f"Memory {memory.id}"
        if len(title) > 80:
            title = f"{title[:77].rstrip()}..."
        memory_rows.append({"id": memory.id, "title": title})
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
                "is_embedding": _is_rag_embedding_model(model),
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
        "flowcharts": [
            {"id": flowchart.id, "name": flowchart.name} for flowchart in flowcharts
        ],
        "plans": [{"id": plan.id, "name": plan.name} for plan in plans],
        "milestones": [
            {"id": milestone.id, "name": milestone.name} for milestone in milestones
        ],
        "memories": memory_rows,
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
    if node_type == FLOWCHART_NODE_TYPE_PLAN:
        return session.get(Plan, ref_id) is not None
    if node_type == FLOWCHART_NODE_TYPE_MILESTONE:
        return session.get(Milestone, ref_id) is not None
    if node_type == FLOWCHART_NODE_TYPE_MEMORY:
        return session.get(Memory, ref_id) is not None
    return True


def _ensure_flowchart_auto_ref(
    session,
    *,
    flowchart_node: FlowchartNode,
) -> None:
    node_type = str(flowchart_node.node_type or "").strip().lower()
    current_ref_id = (
        int(flowchart_node.ref_id)
        if isinstance(flowchart_node.ref_id, int) and flowchart_node.ref_id > 0
        else None
    )
    node_label = str(flowchart_node.title or "").strip() or (
        f"Flowchart {flowchart_node.flowchart_id} node {flowchart_node.id}"
    )

    if node_type == FLOWCHART_NODE_TYPE_PLAN:
        if current_ref_id is not None and session.get(Plan, current_ref_id) is not None:
            return
        plan = Plan.create(session, name=f"{node_label} plan")
        flowchart_node.ref_id = int(plan.id)
        return

    if node_type == FLOWCHART_NODE_TYPE_MILESTONE:
        if (
            current_ref_id is not None
            and session.get(Milestone, current_ref_id) is not None
        ):
            return
        milestone = Milestone.create(session, name=f"{node_label} milestone")
        flowchart_node.ref_id = int(milestone.id)
        return

    if node_type == FLOWCHART_NODE_TYPE_MEMORY:
        if current_ref_id is not None and session.get(Memory, current_ref_id) is not None:
            return
        memory = Memory.create(
            session,
            description=f"Auto memory for {node_label}.",
        )
        flowchart_node.ref_id = int(memory.id)


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


def _normalize_memory_node_action(value: object) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in {"add", "store", "append", "upsert", "create", "create_or_update"}:
        return MEMORY_NODE_ACTION_ADD
    if cleaned in {"retrieve", "fetch", "read", "query", "search", "list"}:
        return MEMORY_NODE_ACTION_RETRIEVE
    return ""


def _normalize_memory_node_mode(value: object) -> str:
    cleaned = str(value or "").strip().lower()
    if not cleaned:
        return MEMORY_NODE_MODE_LLM_GUIDED
    if cleaned in {MEMORY_NODE_MODE_LLM_GUIDED, "llm-guided"}:
        return MEMORY_NODE_MODE_LLM_GUIDED
    if cleaned == MEMORY_NODE_MODE_DETERMINISTIC:
        return MEMORY_NODE_MODE_DETERMINISTIC
    return ""


def _sanitize_memory_node_config(config_payload: dict[str, object]) -> dict[str, object]:
    sanitized = dict(config_payload)
    action_value = config_payload.get("action")
    action = _normalize_memory_node_action(action_value)
    if not action:
        raise ValueError("config.action is required and must be add or retrieve.")
    sanitized["action"] = action
    mode = _normalize_memory_node_mode(config_payload.get("mode"))
    if not mode:
        raise ValueError(
            "config.mode must be one of: " + ", ".join(MEMORY_NODE_MODE_CHOICES) + "."
        )
    sanitized["mode"] = mode
    sanitized["additive_prompt"] = str(config_payload.get("additive_prompt") or "").strip()
    retry_count = _coerce_optional_int(
        config_payload.get("retry_count"),
        field_name="config.retry_count",
        minimum=0,
    )
    if retry_count is None:
        retry_count = MEMORY_NODE_RETRY_COUNT_DEFAULT
    sanitized["retry_count"] = min(retry_count, MEMORY_NODE_RETRY_COUNT_MAX)
    fallback_enabled = _coerce_optional_bool(
        config_payload.get("fallback_enabled"),
        field_name="config.fallback_enabled",
    )
    if fallback_enabled is None:
        fallback_enabled = MEMORY_NODE_FALLBACK_ENABLED_DEFAULT
    sanitized["fallback_enabled"] = fallback_enabled

    retention_mode = str(
        config_payload.get("retention_mode") or NODE_ARTIFACT_RETENTION_TTL
    ).strip().lower()
    if retention_mode not in NODE_ARTIFACT_RETENTION_CHOICES:
        raise ValueError(
            "config.retention_mode must be one of: "
            + ", ".join(NODE_ARTIFACT_RETENTION_CHOICES)
            + "."
        )
    sanitized["retention_mode"] = retention_mode

    ttl_seconds = _coerce_optional_int(
        config_payload.get("retention_ttl_seconds"),
        field_name="config.retention_ttl_seconds",
        minimum=1,
    )
    max_count = _coerce_optional_int(
        config_payload.get("retention_max_count"),
        field_name="config.retention_max_count",
        minimum=1,
    )
    if ttl_seconds is None:
        ttl_seconds = DEFAULT_NODE_ARTIFACT_RETENTION_TTL_SECONDS
    if max_count is None:
        max_count = DEFAULT_NODE_ARTIFACT_RETENTION_MAX_COUNT
    sanitized["retention_ttl_seconds"] = ttl_seconds
    sanitized["retention_max_count"] = max_count
    return sanitized


def _sanitize_flowchart_node_agent_config(
    *,
    session,
    config_payload: dict[str, object],
    field_name: str,
) -> None:
    if "agent_id" not in config_payload:
        return
    agent_id = _coerce_optional_int(
        config_payload.get("agent_id"),
        field_name=field_name,
        minimum=0,
    )
    if agent_id is None or agent_id <= 0:
        config_payload.pop("agent_id", None)
        return
    if session.get(Agent, agent_id) is None:
        raise ValueError(f"{field_name} {agent_id} was not found.")
    config_payload["agent_id"] = agent_id


def _normalize_milestone_node_action(
    value: object,
    *,
    field_name: str,
) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in {"update", "checkpoint", "read", "create", "create_or_update", "create/update"}:
        return MILESTONE_NODE_ACTION_CREATE_OR_UPDATE
    if cleaned in {"complete", "mark_complete", "mark milestone complete"}:
        return MILESTONE_NODE_ACTION_MARK_COMPLETE
    raise ValueError(
        f"{field_name} must be one of: "
        f"{MILESTONE_NODE_ACTION_CREATE_OR_UPDATE}, {MILESTONE_NODE_ACTION_MARK_COMPLETE}."
    )


def _normalize_node_artifact_retention_mode(
    value: object,
    *,
    field_name: str,
) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in {"forever", "none", "disabled"}:
        return NODE_ARTIFACT_RETENTION_FOREVER
    if cleaned in {"max", "max_count"}:
        return NODE_ARTIFACT_RETENTION_MAX_COUNT
    if cleaned in {"ttl_max", "ttl+max", "ttl_max_count"}:
        return NODE_ARTIFACT_RETENTION_TTL_MAX_COUNT
    if cleaned in {"ttl", ""}:
        return NODE_ARTIFACT_RETENTION_TTL
    raise ValueError(
        f"{field_name} must be one of: "
        f"{NODE_ARTIFACT_RETENTION_FOREVER}, {NODE_ARTIFACT_RETENTION_TTL}, "
        f"{NODE_ARTIFACT_RETENTION_MAX_COUNT}, {NODE_ARTIFACT_RETENTION_TTL_MAX_COUNT}."
    )


def _sanitize_milestone_node_config(
    config_payload: dict[str, object],
    *,
    field_prefix: str,
) -> dict[str, object]:
    if "action" not in config_payload:
        raise ValueError(
            f"{field_prefix}.action is required for milestone nodes."
        )
    action = _normalize_milestone_node_action(
        config_payload.get("action"),
        field_name=f"{field_prefix}.action",
    )
    retention_mode = _normalize_node_artifact_retention_mode(
        config_payload.get("retention_mode"),
        field_name=f"{field_prefix}.retention_mode",
    )
    retention_ttl_seconds = _coerce_optional_int(
        config_payload.get("retention_ttl_seconds"),
        field_name=f"{field_prefix}.retention_ttl_seconds",
        minimum=1,
    )
    retention_max_count = _coerce_optional_int(
        config_payload.get("retention_max_count"),
        field_name=f"{field_prefix}.retention_max_count",
        minimum=1,
    )
    sanitized: dict[str, object] = {
        "action": action,
        "additive_prompt": str(config_payload.get("additive_prompt") or "").strip(),
        "retention_mode": retention_mode,
        "retention_ttl_seconds": (
            retention_ttl_seconds
            if retention_ttl_seconds is not None
            else DEFAULT_NODE_ARTIFACT_RETENTION_TTL_SECONDS
        ),
        "retention_max_count": (
            retention_max_count
            if retention_max_count is not None
            else DEFAULT_NODE_ARTIFACT_RETENTION_MAX_COUNT
        ),
    }
    patch = config_payload.get("patch")
    if isinstance(patch, dict):
        sanitized["patch"] = patch
    completion_source_path = str(config_payload.get("completion_source_path") or "").strip()
    if completion_source_path:
        sanitized["completion_source_path"] = completion_source_path
    for key in ("route_key", "route_key_on_terminate"):
        value = str(config_payload.get(key) or "").strip()
        if value:
            sanitized[key] = value
    for key in ("terminate_on_complete", "terminate_on_checkpoint", "terminate_always"):
        if key in config_payload:
            sanitized[key] = _flowchart_as_bool(config_payload.get(key))
    for key in ("loop_checkpoint_every", "loop_exit_after_runs"):
        if key in config_payload:
            coerced = _coerce_optional_int(
                config_payload.get(key),
                field_name=f"{field_prefix}.{key}",
                minimum=0,
            )
            if coerced is not None:
                sanitized[key] = coerced
    return sanitized


def _normalize_plan_node_action(
    value: object,
    *,
    field_name: str,
) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in {
        "create",
        "update",
        "read",
        "create_or_update",
        "create_or_update_plan",
        "create/update",
        "create or update plan",
        "update_completion",
        "complete",
    }:
        return PLAN_NODE_ACTION_CREATE_OR_UPDATE
    if cleaned in {
        "complete_plan_item",
        "complete plan item",
        "mark_plan_item_complete",
        "mark_task_complete",
    }:
        return PLAN_NODE_ACTION_COMPLETE_PLAN_ITEM
    raise ValueError(
        f"{field_name} must be one of: "
        f"{PLAN_NODE_ACTION_CREATE_OR_UPDATE}, {PLAN_NODE_ACTION_COMPLETE_PLAN_ITEM}."
    )


def _sanitize_plan_node_config(
    config_payload: dict[str, object],
    *,
    field_prefix: str,
) -> dict[str, object]:
    if "action" not in config_payload:
        raise ValueError(
            f"{field_prefix}.action is required for plan nodes."
        )
    action = _normalize_plan_node_action(
        config_payload.get("action"),
        field_name=f"{field_prefix}.action",
    )
    retention_mode = _normalize_node_artifact_retention_mode(
        config_payload.get("retention_mode"),
        field_name=f"{field_prefix}.retention_mode",
    )
    retention_ttl_seconds = _coerce_optional_int(
        config_payload.get("retention_ttl_seconds"),
        field_name=f"{field_prefix}.retention_ttl_seconds",
        minimum=1,
    )
    retention_max_count = _coerce_optional_int(
        config_payload.get("retention_max_count"),
        field_name=f"{field_prefix}.retention_max_count",
        minimum=1,
    )
    sanitized: dict[str, object] = {
        "action": action,
        "additive_prompt": str(config_payload.get("additive_prompt") or "").strip(),
        "retention_mode": retention_mode,
        "retention_ttl_seconds": (
            retention_ttl_seconds
            if retention_ttl_seconds is not None
            else DEFAULT_NODE_ARTIFACT_RETENTION_TTL_SECONDS
        ),
        "retention_max_count": (
            retention_max_count
            if retention_max_count is not None
            else DEFAULT_NODE_ARTIFACT_RETENTION_MAX_COUNT
        ),
    }
    completion_source_path = str(config_payload.get("completion_source_path") or "").strip()
    if completion_source_path:
        sanitized["completion_source_path"] = completion_source_path
    if action == PLAN_NODE_ACTION_COMPLETE_PLAN_ITEM:
        plan_item_id = _coerce_optional_int(
            config_payload.get("plan_item_id"),
            field_name=f"{field_prefix}.plan_item_id",
            minimum=1,
        )
        stage_key = str(config_payload.get("stage_key") or "").strip()
        task_key = str(config_payload.get("task_key") or "").strip()
        if plan_item_id is not None:
            sanitized["plan_item_id"] = plan_item_id
        if stage_key:
            sanitized["stage_key"] = stage_key
        if task_key:
            sanitized["task_key"] = task_key
        if plan_item_id is None and not (stage_key and task_key) and not completion_source_path:
            raise ValueError(
                f"{field_prefix} requires plan_item_id, or stage_key + task_key, "
                "or completion_source_path when action is complete_plan_item."
            )
    else:
        patch = config_payload.get("patch")
        if isinstance(patch, dict):
            sanitized["patch"] = patch
    for key in ("route_key", "route_key_on_complete"):
        value = str(config_payload.get(key) or "").strip()
        if value:
            sanitized[key] = value
    return sanitized


def _serialize_node_artifact(node_artifact: NodeArtifact) -> dict[str, object]:
    payload = _parse_json_dict(node_artifact.payload_json)
    return {
        "id": node_artifact.id,
        "flowchart_id": node_artifact.flowchart_id,
        "flowchart_node_id": node_artifact.flowchart_node_id,
        "flowchart_run_id": node_artifact.flowchart_run_id,
        "flowchart_run_node_id": node_artifact.flowchart_run_node_id,
        "node_type": node_artifact.node_type,
        "artifact_type": node_artifact.artifact_type,
        "ref_id": node_artifact.ref_id,
        "execution_index": node_artifact.execution_index,
        "variant_key": node_artifact.variant_key,
        "retention_mode": node_artifact.retention_mode,
        "expires_at": _human_time(node_artifact.expires_at),
        "request_id": node_artifact.request_id,
        "correlation_id": node_artifact.correlation_id,
        "payload": payload,
        "contract_version": node_artifact.contract_version,
        "payload_version": node_artifact.payload_version,
        "idempotency_key": node_artifact.idempotency_key,
        "created_at": _human_time(node_artifact.created_at),
        "updated_at": _human_time(node_artifact.updated_at),
    }


def _parse_node_artifact_list_params(
    *,
    request_id: str,
    correlation_id: str | None,
) -> tuple[dict[str, object] | None, tuple[dict[str, object], int] | None]:
    try:
        limit = _coerce_optional_int(request.args.get("limit"), field_name="limit", minimum=1)
        offset = _coerce_optional_int(request.args.get("offset"), field_name="offset", minimum=0)
        flowchart_id = _coerce_optional_int(
            request.args.get("flowchart_id"),
            field_name="flowchart_id",
            minimum=1,
        )
        flowchart_node_id = _coerce_optional_int(
            request.args.get("flowchart_node_id"),
            field_name="flowchart_node_id",
            minimum=1,
        )
        flowchart_run_id = _coerce_optional_int(
            request.args.get("flowchart_run_id"),
            field_name="flowchart_run_id",
            minimum=1,
        )
        flowchart_run_node_id = _coerce_optional_int(
            request.args.get("flowchart_run_node_id"),
            field_name="flowchart_run_node_id",
            minimum=1,
        )
    except ValueError as exc:
        return None, (
            _workflow_error_envelope(
                code="invalid_request",
                message=str(exc),
                details={},
                request_id=request_id,
                correlation_id=correlation_id,
            ),
            400,
        )

    resolved_limit = min(limit if limit is not None else 50, 200)
    resolved_offset = offset if offset is not None else 0
    descending = str(request.args.get("order") or "desc").strip().lower() != "asc"
    return (
        {
            "limit": resolved_limit,
            "offset": resolved_offset,
            "descending": descending,
            "flowchart_id": flowchart_id,
            "flowchart_node_id": flowchart_node_id,
            "flowchart_run_id": flowchart_run_id,
            "flowchart_run_node_id": flowchart_run_node_id,
        },
        None,
    )


NODE_ARTIFACT_TYPE_FILTER_CHOICES = {
    NODE_ARTIFACT_TYPE_START,
    NODE_ARTIFACT_TYPE_END,
    NODE_ARTIFACT_TYPE_FLOWCHART,
    NODE_ARTIFACT_TYPE_TASK,
    NODE_ARTIFACT_TYPE_PLAN,
    NODE_ARTIFACT_TYPE_MILESTONE,
    NODE_ARTIFACT_TYPE_MEMORY,
    NODE_ARTIFACT_TYPE_DECISION,
    NODE_ARTIFACT_TYPE_RAG,
}


def _workflow_request_id() -> str:
    return request_id_from_request(request)


def _workflow_correlation_id() -> str | None:
    return correlation_id_from_request(request)


def _workflow_error_envelope(
    *,
    code: str,
    message: str,
    details: dict[str, object] | None,
    request_id: str,
    correlation_id: str | None,
) -> dict[str, object]:
    return build_api_error_envelope(
        code=code,
        message=message,
        details=details,
        request_id=request_id,
        correlation_id=correlation_id,
    )


def _workflow_success_payload(
    *,
    payload: dict[str, object],
    request_id: str,
    correlation_id: str | None,
) -> dict[str, object]:
    response: dict[str, object] = {
        "ok": True,
        "contract_version": MODEL_PROVIDER_API_CONTRACT_VERSION,
        "request_id": request_id,
        **payload,
    }
    if correlation_id:
        response["correlation_id"] = correlation_id
    return response


def _workflow_api_error_response(
    *,
    code: str,
    message: str,
    status_code: int,
    details: dict[str, object] | None = None,
) -> tuple[dict[str, object], int]:
    return (
        _workflow_error_envelope(
            code=code,
            message=message,
            details=details or {},
            request_id=_workflow_request_id(),
            correlation_id=_workflow_correlation_id(),
        ),
        status_code,
    )


def _emit_model_provider_event(
    *,
    event_type: str,
    entity_kind: str,
    entity_id: int | str | None,
    payload: dict[str, object],
    request_id: str,
    correlation_id: str | None,
) -> None:
    try:
        emit_contract_event(
            event_type=event_type,
            entity_kind=entity_kind,
            entity_id=entity_id,
            payload=payload,
            request_id=request_id,
            correlation_id=correlation_id,
        )
    except Exception:
        logger.exception(
            "Failed to emit model/provider event %s for %s:%s",
            event_type,
            entity_kind,
            entity_id,
        )


def _validate_flowchart_graph_snapshot(
    nodes: list[dict[str, object]],
    edges: list[dict[str, object]],
) -> list[str]:
    errors: list[str] = []
    node_ids: set[int] = set()
    node_type_by_id: dict[int, str] = {}
    node_config_by_id: dict[int, dict[str, object]] = {}
    incoming: dict[int, int] = {}
    outgoing: dict[int, int] = {}

    for node in nodes:
        node_id = int(node["id"])
        node_ids.add(node_id)
        node_type = str(node.get("node_type") or "")
        config_payload = node.get("config") if isinstance(node.get("config"), dict) else {}
        try:
            config_payload = _sanitize_flowchart_node_routing_config(
                config_payload,
                field_prefix=f"nodes[{node_id}].config",
            )
        except ValueError as exc:
            errors.append(f"Node {node_id} ({node_type}) {exc}")
        node_type_by_id[node_id] = node_type
        node_config_by_id[node_id] = config_payload
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
        if node_type == FLOWCHART_NODE_TYPE_TASK and not _task_node_has_prompt(
            config_payload
        ):
            errors.append(f"Node {node_id} ({node_type}) requires config.task_prompt.")
        if node_type == FLOWCHART_NODE_TYPE_RAG:
            try:
                _sanitize_rag_node_config(config_payload)
            except ValueError as exc:
                errors.append(f"Node {node_id} ({node_type}) {exc}")
        if node_type == FLOWCHART_NODE_TYPE_MILESTONE:
            try:
                _sanitize_milestone_node_config(
                    config_payload,
                    field_prefix=f"nodes[{node_id}].config",
                )
            except ValueError as exc:
                errors.append(f"Node {node_id} ({node_type}) {exc}")
        if node_type == FLOWCHART_NODE_TYPE_PLAN:
            try:
                _sanitize_plan_node_config(
                    config_payload,
                    field_prefix=f"nodes[{node_id}].config",
                )
            except ValueError as exc:
                errors.append(f"Node {node_id} ({node_type}) {exc}")
        if node_type == FLOWCHART_NODE_TYPE_MEMORY:
            try:
                _sanitize_memory_node_config(config_payload)
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
        if node_type == FLOWCHART_NODE_TYPE_MEMORY and not mcp_server_ids:
            errors.append(
                f"Node {node_id} ({node_type}) requires the system-managed LLMCTL MCP server."
            )
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
    solid_parent_ids_by_target: dict[int, set[int]] = {}
    edge_modes_by_pair: dict[tuple[int, int], set[str]] = {}
    for edge in edges:
        edge_token = edge.get("id")
        if edge_token is None:
            edge_token = f"{edge.get('source_node_id')}->{edge.get('target_node_id')}"
        try:
            _coerce_flowchart_edge_control_points(
                edge.get("control_points"),
                field_name=f"edges[{edge_token}].control_points",
            )
        except ValueError as exc:
            errors.append(str(exc))
        try:
            _coerce_flowchart_edge_control_style(
                edge.get("control_point_style"),
                field_name=f"edges[{edge_token}].control_point_style",
            )
        except ValueError as exc:
            errors.append(str(exc))
        edge_mode = str(edge.get("edge_mode") or "").strip().lower()
        if edge_mode not in FLOWCHART_EDGE_MODE_CHOICES:
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
            solid_parent_ids_by_target.setdefault(target_node_id, set()).add(source_node_id)
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
        config_payload = node_config_by_id.get(node_id, {})
        if node_type not in FLOWCHART_NODE_TYPE_CHOICES:
            continue
        outgoing_count = outgoing.get(node_id, 0)
        try:
            fan_in_mode = _normalize_flowchart_fan_in_mode(
                config_payload.get("fan_in_mode"),
                field_name=f"nodes[{node_id}].config.fan_in_mode",
            )
        except ValueError as exc:
            errors.append(f"Node {node_id} ({node_type}) {exc}")
            fan_in_mode = FLOWCHART_FAN_IN_MODE_ALL
        solid_parent_count = len(solid_parent_ids_by_target.get(node_id, set()))
        if fan_in_mode == FLOWCHART_FAN_IN_MODE_CUSTOM:
            try:
                fan_in_custom_count = _coerce_optional_int(
                    config_payload.get("fan_in_custom_count"),
                    field_name=f"nodes[{node_id}].config.fan_in_custom_count",
                    minimum=1,
                )
            except ValueError as exc:
                errors.append(f"Node {node_id} ({node_type}) {exc}")
                fan_in_custom_count = None
            if fan_in_custom_count is None:
                errors.append(
                    f"Node {node_id} ({node_type}) config.fan_in_custom_count is required when fan_in_mode is custom."
                )
            elif solid_parent_count == 0:
                errors.append(
                    f"Node {node_id} ({node_type}) cannot use custom fan-in without solid incoming connectors."
                )
            elif fan_in_custom_count > solid_parent_count:
                errors.append(
                    f"Node {node_id} ({node_type}) config.fan_in_custom_count must be <= solid incoming connector count ({solid_parent_count})."
                )
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
        fallback_condition_key = str(config_payload.get("fallback_condition_key") or "").strip()
        if fallback_condition_key and fallback_condition_key not in set(keys):
            errors.append(
                f"Decision node {node_id} fallback_condition_key '{fallback_condition_key}' does not match a solid outgoing connector."
            )
        try:
            no_match_policy = _normalize_decision_no_match_policy(
                config_payload.get("no_match_policy"),
                field_name=f"nodes[{node_id}].config.no_match_policy",
            )
        except ValueError as exc:
            errors.append(f"Node {node_id} ({node_type}) {exc}")
            no_match_policy = ""
        if (
            no_match_policy == FLOWCHART_DECISION_NO_MATCH_POLICY_FALLBACK
            and not fallback_condition_key
        ):
            errors.append(
                f"Decision node {node_id} requires fallback_condition_key when no_match_policy is fallback."
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
    edges: list[dict[str, object]] = []
    for edge in flowchart_edges:
        control_points, control_point_style = _flowchart_edge_control_geometry(
            edge.control_points_json
        )
        edges.append(
            {
                "id": edge.id,
                "source_node_id": edge.source_node_id,
                "target_node_id": edge.target_node_id,
                "source_handle_id": edge.source_handle_id,
                "target_handle_id": edge.target_handle_id,
                "edge_mode": edge.edge_mode,
                "condition_key": edge.condition_key,
                "label": edge.label,
                "control_points": control_points,
                "control_point_style": control_point_style,
            }
        )
    return nodes, edges


def _validate_flowchart_graph(
    flowchart_nodes: list[FlowchartNode],
    flowchart_edges: list[FlowchartEdge],
) -> list[str]:
    nodes, edges = _flowchart_graph_state(flowchart_nodes, flowchart_edges)
    return _validate_flowchart_graph_snapshot(nodes, edges)










































































































































































def _read_milestone_form(
    source: dict[str, object] | None = None,
) -> tuple[dict[str, object] | None, str | None]:
    if source is None:
        source = request.form.to_dict()

    def _value(key: str) -> str:
        raw = source.get(key)
        if raw is None:
            return ""
        return str(raw).strip()

    name = _value("name")
    if not name:
        return None, "Name is required."

    status = _normalize_milestone_choice(
        _value("status"),
        choices=MILESTONE_STATUS_CHOICES,
        fallback=MILESTONE_STATUS_PLANNED,
    )
    priority = _normalize_milestone_choice(
        _value("priority"),
        choices=MILESTONE_PRIORITY_CHOICES,
        fallback=MILESTONE_PRIORITY_MEDIUM,
    )
    health = _normalize_milestone_choice(
        _value("health"),
        choices=MILESTONE_HEALTH_CHOICES,
        fallback=MILESTONE_HEALTH_GREEN,
    )

    start_date_raw = _value("start_date")
    start_date = _parse_milestone_due_date(start_date_raw)
    if start_date_raw and start_date is None:
        return None, "Start date must be a valid date."

    due_date_raw = _value("due_date")
    due_date = _parse_milestone_due_date(due_date_raw)
    if due_date_raw and due_date is None:
        return None, "Due date must be a valid date."
    if start_date and due_date and due_date < start_date:
        return None, "Due date must be on or after the start date."

    progress = _parse_milestone_progress(_value("progress_percent"))
    if progress is None:
        return None, "Progress must be a whole number between 0 and 100."

    payload: dict[str, object] = {
        "name": name,
        "description": _value("description") or None,
        "status": status,
        "priority": priority,
        "owner": _value("owner") or None,
        "start_date": start_date,
        "due_date": due_date,
        "progress_percent": progress,
        "health": health,
        "success_criteria": _value("success_criteria") or None,
        "dependencies": _value("dependencies") or None,
        "links": _value("links") or None,
        "latest_update": _value("latest_update") or None,
    }
    completed = status == MILESTONE_STATUS_DONE
    payload["completed"] = completed
    if completed:
        payload["progress_percent"] = max(progress, 100)
    return payload, None
















































def _control_cancel_flowchart_run(
    session,
    *,
    run_id: int,
    flowchart_run: FlowchartRun,
    force: bool,
) -> tuple[dict[str, object], list[tuple[str, bool]]]:
    revoke_actions: list[tuple[str, bool]] = []
    action = "none"
    updated = False
    now = utcnow()
    current_status = _normalize_flowchart_run_status(flowchart_run.status)

    if force:
        if current_status in FLOWCHART_RUN_ACTIVE_STATUSES:
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
                if _normalize_flowchart_run_status(node_run.status) in {"queued", "running", "pending"}:
                    node_run.status = "canceled"
                    node_run.finished_at = now

            tasks = (
                session.execute(select(AgentTask).where(AgentTask.flowchart_run_id == run_id))
                .scalars()
                .all()
            )
            for task in tasks:
                if _normalize_flowchart_run_status(task.status) in {"pending", "queued", "running"}:
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
        elif current_status in {"running", "paused", "pausing"}:
            action = "stopping"
            updated = True
            flowchart_run.status = "stopping"
        elif current_status == "stopping":
            action = "stopping"

    return (
        {
            "flowchart_run": _serialize_flowchart_run(flowchart_run),
            "force": force,
            "updated": updated,
            "action": action,
            "canceled": action == "canceled",
            "stop_requested": action in {"stopping", "stopped"},
        },
        revoke_actions,
    )
























def _parse_model_list_query() -> dict[str, object]:
    query_control_requested = any(
        key in request.args
        for key in ("page", "per_page", "search", "provider", "sort_by", "sort_order")
    )
    page = _coerce_optional_int(request.args.get("page"), field_name="page", minimum=1)
    per_page = _coerce_optional_int(
        request.args.get("per_page"),
        field_name="per_page",
        minimum=1,
    )
    search_text = str(request.args.get("search") or "").strip()
    provider_filter = str(request.args.get("provider") or "").strip().lower()
    default_sort_by = "name" if query_control_requested else "created_at"
    default_sort_order = "asc" if query_control_requested else "desc"
    sort_by = str(request.args.get("sort_by") or default_sort_by).strip().lower()
    sort_order = str(request.args.get("sort_order") or default_sort_order).strip().lower()
    if sort_by not in MODEL_LIST_SORT_FIELDS:
        raise ValueError(
            "sort_by must be one of: "
            + ", ".join(sorted(MODEL_LIST_SORT_FIELDS))
            + "."
        )
    if sort_order not in {"asc", "desc"}:
        raise ValueError("sort_order must be 'asc' or 'desc'.")

    resolved_page = page if page is not None else 1
    resolved_per_page = per_page if per_page is not None else (25 if query_control_requested else None)
    if isinstance(resolved_per_page, int):
        resolved_per_page = min(resolved_per_page, 200)
    return {
        "query_control_requested": query_control_requested,
        "page": resolved_page,
        "per_page": resolved_per_page,
        "search_text": search_text,
        "provider_filter": provider_filter,
        "sort_by": sort_by,
        "sort_order": sort_order,
    }


























































































def _render_github_pull_request_page(
    pr_number: int, active_tab: str, *, is_api_request: bool = False
):
    settings = _load_integration_settings("github")
    repo = settings.get("repo") or ""
    pat = settings.get("pat") or ""
    if not repo or not pat:
        if is_api_request:
            return {"error": "GitHub repository and PAT are required to view pull requests."}, 400
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
    if is_api_request:
        return {
            "workspace": "github",
            "repo": repo or "No repository selected",
            "connected": bool(pat),
            "pull_request": pull_request,
            "pull_request_number": pr_number,
            "comments": comments,
            "reviewers": reviewers,
            "active_tab": selected_tab,
            "pull_request_error": pr_error,
            "comments_error": comments_error,
            "page_title": page_title,
        }
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








































def _database_filename_setting() -> str:
    configured = str(getattr(Config, "DATABASE_FILENAME", "") or "").strip()
    if configured:
        return configured
    uri = str(getattr(Config, "SQLALCHEMY_DATABASE_URI", "") or "").strip()
    if not uri:
        return "not set"
    base_uri = uri.split("?", 1)[0]
    if base_uri.lower().startswith("sqlite:"):
        return base_uri.rsplit("/", 1)[-1] or base_uri
    return "managed by database URI"






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


def _normalize_provider_id(raw: object) -> str:
    return str(raw or "").strip().lower().replace("-", "_")


def _provider_details_index(context: dict[str, object]) -> dict[str, dict[str, object]]:
    details = context.get("provider_details")
    rows = details if isinstance(details, list) else []
    indexed: dict[str, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        provider_id = _normalize_provider_id(row.get("id"))
        if not provider_id:
            continue
        indexed[provider_id] = row
    return indexed


def _parse_provider_list_query() -> dict[str, object]:
    page = _coerce_optional_int(request.args.get("page"), field_name="page", minimum=1)
    per_page = _coerce_optional_int(
        request.args.get("per_page"),
        field_name="per_page",
        minimum=1,
    )
    search_text = str(request.args.get("search") or "").strip().lower()
    enabled_raw = str(request.args.get("enabled") or "").strip().lower()
    if enabled_raw and enabled_raw not in {"true", "false"}:
        raise ValueError("enabled must be 'true' or 'false' when provided.")
    sort_by = str(request.args.get("sort_by") or "label").strip().lower()
    if sort_by not in PROVIDER_LIST_SORT_FIELDS:
        raise ValueError(
            "sort_by must be one of: "
            + ", ".join(sorted(PROVIDER_LIST_SORT_FIELDS))
            + "."
        )
    sort_order = str(request.args.get("sort_order") or "asc").strip().lower()
    if sort_order not in {"asc", "desc"}:
        raise ValueError("sort_order must be 'asc' or 'desc'.")
    resolved_page = page if page is not None else 1
    resolved_per_page = min(per_page if per_page is not None else 25, 200)
    return {
        "page": resolved_page,
        "per_page": resolved_per_page,
        "search_text": search_text,
        "enabled_filter": enabled_raw,
        "sort_by": sort_by,
        "sort_order": sort_order,
    }






def _render_settings_provider_page(section: str):
    section_meta = PROVIDER_SETTINGS_SECTIONS.get(section)
    if section_meta is None:
        abort(404)
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    context = _settings_provider_context()
    if _workflow_wants_json():
        return _workflow_success_payload(
            payload={
                "provider_section": section,
                "provider_sections": [
                    {
                        "id": key,
                        "label": value["label"],
                    }
                    for key, value in PROVIDER_SETTINGS_SECTIONS.items()
                ],
                **context,
            },
            request_id=request_id,
            correlation_id=correlation_id,
        )
    return render_template(
        "settings_provider.html",
        provider_section=section,
        page_title=f"Settings - Providers - {section_meta['label']}",
        **context,
    )








































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
        {"value": "kubernetes", "label": "Kubernetes"},
    ]
    return {
        "provider_options": [
            option
            for option in provider_options
            if option["value"] in set(NODE_EXECUTOR_PROVIDER_CHOICES)
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
    node_executor_settings = load_node_executor_settings()
    node_executor_options = _node_executor_settings_options()
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
    context = _settings_runtime_context()
    if _workflow_wants_json():
        return {
            "runtime_section": section,
            "runtime_sections": [
                {
                    "id": key,
                    "label": value["label"],
                }
                for key, value in RUNTIME_SETTINGS_SECTIONS.items()
            ],
            **context,
        }
    return render_template(
        "settings_runtime.html",
        runtime_section=section,
        page_title=f"Settings - Runtime - {section_meta['label']}",
        **context,
    )

__all__ = [name for name in globals() if not name.startswith("__")]
