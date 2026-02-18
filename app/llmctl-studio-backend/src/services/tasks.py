from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import selectors
import subprocess
import tempfile
import time
from collections import deque
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from services.celery_app import celery_app
from services.huggingface_downloads import (
    run_huggingface_model_download,
    summarize_subprocess_error,
    vllm_local_model_directory,
)
from core.config import Config, REPO_ROOT
from core.db import init_db, init_engine, session_scope
from services.integrations import (
    LLM_PROVIDER_LABELS,
    LLM_PROVIDERS,
    load_integration_settings,
    load_node_executor_runtime_settings,
    resolve_default_model_id,
    resolve_enabled_llm_providers,
    resolve_llm_provider,
)
from services.execution.contracts import ExecutionRequest
from services.execution.router import ExecutionRouter
from services.realtime_events import (
    combine_room_keys,
    download_scope_rooms,
    emit_contract_event,
    flowchart_scope_rooms,
    task_scope_rooms,
)
from core.mcp_config import build_mcp_overrides, parse_mcp_config
from core.prompt_envelope import (
    build_prompt_envelope,
    is_prompt_envelope,
    parse_prompt_input,
    serialize_prompt_envelope,
)
from core.task_integrations import (
    is_task_integration_selected,
    parse_task_integration_keys,
    validate_task_integration_keys,
)
from core.models import (
    Agent,
    AgentTask,
    Attachment,
    Flowchart,
    FLOWCHART_EDGE_MODE_DOTTED,
    FLOWCHART_EDGE_MODE_SOLID,
    FlowchartNode,
    FlowchartRun,
    FlowchartRunNode,
    FLOWCHART_NODE_TYPE_DECISION,
    FLOWCHART_NODE_TYPE_END,
    FLOWCHART_NODE_TYPE_FLOWCHART,
    FLOWCHART_NODE_TYPE_MEMORY,
    FLOWCHART_NODE_TYPE_MILESTONE,
    FLOWCHART_NODE_TYPE_PLAN,
    FLOWCHART_NODE_TYPE_RAG,
    FLOWCHART_NODE_TYPE_START,
    FLOWCHART_NODE_TYPE_TASK,
    LLMModel,
    MCPServer,
    Memory,
    Milestone,
    MILESTONE_STATUS_DONE,
    Plan,
    PlanStage,
    PlanTask,
    Run,
    Role,
    RUN_ACTIVE_STATUSES,
    Script,
    SCRIPT_TYPE_INIT,
    SCRIPT_TYPE_POST_INIT,
    SCRIPT_TYPE_POST_RUN,
    SCRIPT_TYPE_PRE_INIT,
    flowchart_node_skills,
)
from services.instruction_adapters import resolve_instruction_adapter
from rag.domain import (
    RAG_FLOWCHART_MODE_DELTA_INDEX,
    RAG_FLOWCHART_MODE_FRESH_INDEX,
    RAG_FLOWCHART_MODE_QUERY,
    RAG_HEALTH_CONFIGURED_HEALTHY,
    execute_query_contract,
    normalize_collection_selection as normalize_rag_collection_selection,
    rag_health_snapshot as rag_runtime_health_snapshot,
    run_index_for_collections,
)
from rag.engine.config import load_config as load_rag_config
from rag.providers.adapters import (
    call_chat_completion as rag_call_chat_completion,
    get_chat_provider as rag_get_chat_provider,
    has_chat_api_key as rag_has_chat_api_key,
    missing_api_key_message as rag_missing_api_key_message,
)
from storage.script_storage import ensure_script_file
from core.task_stages import TASK_STAGE_LABELS, TASK_STAGE_ORDER
from core.task_kinds import (
    RAG_QUICK_DELTA_TASK_KIND,
    RAG_QUICK_INDEX_TASK_KIND,
    is_quick_task_kind,
)
from core.quick_node import (
    build_quick_node_agent_profile,
    build_quick_node_system_contract,
)
from services.skill_adapters import (
    build_skill_fallback_entries,
    materialize_skill_set,
    resolve_agent_skills,
    skill_ids_payload,
    skill_versions_payload,
)
from services.instructions.compiler import (
    InstructionCompileInput,
    compile_instruction_package,
)
from services.instructions.package import (
    materialize_instruction_package,
)

logger = logging.getLogger(__name__)

OUTPUT_INSTRUCTIONS_ONE_OFF = "Do not ask follow-up questions. This is a one-off task."
OUTPUT_INSTRUCTIONS_MARKDOWN = (
    "If Markdown is used, ensure it is valid CommonMark "
    "(for example: balanced code fences and valid link syntax)."
)
INSTRUCTION_SIZE_WARNING_BYTES = 64 * 1024
INSTRUCTION_TOTAL_SIZE_WARNING_BYTES = 96 * 1024
INSTRUCTION_NATIVE_ENABLED_DEFAULTS: dict[str, bool] = {
    "codex": True,
    "gemini": True,
    "claude": True,
    "vllm_local": False,
    "vllm_remote": False,
}
INSTRUCTION_FALLBACK_ENABLED_DEFAULTS: dict[str, bool] = {
    provider: True for provider in LLM_PROVIDERS
}
QUICK_RAG_TASK_KINDS = {
    RAG_QUICK_INDEX_TASK_KIND,
    RAG_QUICK_DELTA_TASK_KIND,
}
EXECUTOR_NODE_TYPE_AGENT_TASK = "agent_task"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_updated_at_version(value: datetime | None) -> str | None:
    if value is None:
        return None
    timestamp = value
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)
    return timestamp.isoformat()


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


def _normalize_quick_rag_mode(value: Any) -> str | None:
    cleaned = str(value or "").strip().lower()
    if cleaned in {"fresh", "index", RAG_FLOWCHART_MODE_FRESH_INDEX}:
        return RAG_FLOWCHART_MODE_FRESH_INDEX
    if cleaned in {"delta", RAG_FLOWCHART_MODE_DELTA_INDEX}:
        return RAG_FLOWCHART_MODE_DELTA_INDEX
    return None


def _normalize_quick_rag_model_provider(value: Any) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned == "gemini":
        return "gemini"
    return "codex"


def _kubernetes_job_name_from_dispatch_id(provider_dispatch_id: Any) -> str:
    dispatch_id = str(provider_dispatch_id or "").strip()
    if not dispatch_id.startswith("kubernetes:"):
        return ""
    native_id = dispatch_id.split(":", 1)[1]
    if "/" not in native_id:
        return ""
    return native_id.split("/", 1)[1].strip()


def _runtime_evidence_payload(
    *,
    run_metadata: dict[str, Any] | None,
    provider_metadata: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    terminal_status: str | None = None,
) -> dict[str, Any]:
    run_metadata = run_metadata if isinstance(run_metadata, dict) else {}
    provider_metadata = provider_metadata if isinstance(provider_metadata, dict) else {}
    error = error if isinstance(error, dict) else {}

    provider_dispatch_id = str(
        run_metadata.get("provider_dispatch_id")
        or provider_metadata.get("provider_dispatch_id")
        or ""
    ).strip()
    k8s_job_name = str(
        run_metadata.get("k8s_job_name")
        or provider_metadata.get("k8s_job_name")
        or _kubernetes_job_name_from_dispatch_id(provider_dispatch_id)
        or ""
    ).strip()
    k8s_pod_name = str(
        run_metadata.get("k8s_pod_name")
        or provider_metadata.get("k8s_pod_name")
        or ""
    ).strip()

    terminal_reason_candidates = [
        run_metadata.get("k8s_terminal_reason"),
        provider_metadata.get("k8s_terminal_reason"),
        run_metadata.get("terminal_reason"),
        provider_metadata.get("terminal_reason"),
        run_metadata.get("fallback_reason"),
        run_metadata.get("api_failure_category"),
        error.get("code"),
        error.get("message"),
    ]
    k8s_terminal_reason = ""
    for candidate in terminal_reason_candidates:
        text = str(candidate or "").strip()
        if text:
            k8s_terminal_reason = text
            break
    if not k8s_terminal_reason and terminal_status:
        k8s_terminal_reason = str(terminal_status).strip().lower()

    return {
        "provider_dispatch_id": provider_dispatch_id,
        "k8s_job_name": k8s_job_name,
        "k8s_pod_name": k8s_pod_name,
        "k8s_terminal_reason": k8s_terminal_reason,
    }


def _quick_rag_worker_compute_disabled(
    _request: ExecutionRequest,
) -> tuple[dict[str, Any], dict[str, Any]]:
    raise RuntimeError(
        "Quick RAG compute must execute in executor runtime; worker execution is disabled."
    )


def _agent_task_worker_compute_disabled(
    _request: ExecutionRequest,
) -> tuple[dict[str, Any], dict[str, Any]]:
    raise RuntimeError(
        "Agent task compute must execute in executor runtime; worker execution is disabled."
    )


def _task_runtime_metadata(
    task: AgentTask,
    *,
    runtime_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(runtime_override, dict):
        return dict(runtime_override)
    return {
        "selected_provider": task.selected_provider,
        "final_provider": task.final_provider,
        "provider_dispatch_id": task.provider_dispatch_id,
        "workspace_identity": task.workspace_identity,
        "dispatch_status": task.dispatch_status,
        "fallback_attempted": bool(task.fallback_attempted),
        "fallback_reason": task.fallback_reason,
        "dispatch_uncertain": bool(task.dispatch_uncertain),
        "api_failure_category": task.api_failure_category,
        "cli_fallback_used": bool(task.cli_fallback_used),
        "cli_preflight_passed": task.cli_preflight_passed,
    }


def _task_event_payload(task: AgentTask) -> dict[str, Any]:
    return {
        "task_id": int(task.id),
        "status": str(task.status),
        "kind": str(task.kind or "task"),
        "run_id": task.run_id,
        "flowchart_id": task.flowchart_id,
        "flowchart_run_id": task.flowchart_run_id,
        "flowchart_node_id": task.flowchart_node_id,
        "current_stage": task.current_stage,
        "started_at": _resolve_updated_at_version(task.started_at),
        "finished_at": _resolve_updated_at_version(task.finished_at),
        "updated_at": _resolve_updated_at_version(task.updated_at),
    }


def _emit_task_event(
    event_type: str,
    *,
    task: AgentTask,
    payload: dict[str, Any] | None = None,
    runtime_override: dict[str, Any] | None = None,
    extra_room_keys: list[str] | None = None,
) -> None:
    event_payload = _task_event_payload(task)
    if payload:
        event_payload.update(payload)
    room_keys = combine_room_keys(
        task_scope_rooms(
            task_id=task.id,
            run_id=task.run_id,
            flowchart_id=task.flowchart_id,
            flowchart_run_id=task.flowchart_run_id,
            flowchart_node_id=task.flowchart_node_id,
        ),
        extra_room_keys,
    )
    emit_contract_event(
        event_type=event_type,
        entity_kind="task",
        entity_id=task.id,
        room_keys=room_keys,
        payload=event_payload,
        runtime=_task_runtime_metadata(task, runtime_override=runtime_override),
    )


def _emit_flowchart_node_event(
    event_type: str,
    *,
    flowchart_id: int,
    flowchart_run_id: int,
    flowchart_node_id: int,
    node_type: str,
    status: str,
    execution_index: int | None = None,
    node_run_id: int | None = None,
    agent_task_id: int | None = None,
    error: str | None = None,
    output_state: dict[str, Any] | None = None,
    routing_state: dict[str, Any] | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    runtime: dict[str, Any] | None = None,
) -> None:
    payload = {
        "flowchart_id": flowchart_id,
        "flowchart_run_id": flowchart_run_id,
        "flowchart_node_id": flowchart_node_id,
        "flowchart_node_type": node_type,
        "node_run_id": node_run_id,
        "agent_task_id": agent_task_id,
        "status": status,
        "execution_index": execution_index,
        "error": error,
        "output_state": output_state,
        "routing_state": routing_state,
        "started_at": _resolve_updated_at_version(started_at),
        "finished_at": _resolve_updated_at_version(finished_at),
    }
    emit_contract_event(
        event_type=event_type,
        entity_kind="flowchart_node",
        entity_id=node_run_id if node_run_id is not None else flowchart_node_id,
        room_keys=flowchart_scope_rooms(
            flowchart_id=flowchart_id,
            flowchart_run_id=flowchart_run_id,
            flowchart_node_id=flowchart_node_id,
        ),
        payload=payload,
        runtime=runtime,
    )


def _emit_flowchart_run_event(
    event_type: str,
    *,
    run: FlowchartRun,
    flowchart_id: int,
    payload: dict[str, Any] | None = None,
) -> None:
    event_payload = {
        "flowchart_id": flowchart_id,
        "flowchart_run_id": int(run.id),
        "status": str(run.status),
        "started_at": _resolve_updated_at_version(run.started_at),
        "finished_at": _resolve_updated_at_version(run.finished_at),
        "updated_at": _resolve_updated_at_version(run.updated_at),
    }
    if payload:
        event_payload.update(payload)
    emit_contract_event(
        event_type=event_type,
        entity_kind="flowchart_run",
        entity_id=run.id,
        room_keys=flowchart_scope_rooms(
            flowchart_id=flowchart_id,
            flowchart_run_id=run.id,
        ),
        payload=event_payload,
        runtime=None,
    )


def _download_job_status_from_task_state(
    *,
    phase: str,
    state: str,
) -> str:
    normalized_state = str(state or "").strip().upper()
    normalized_phase = str(phase or "").strip().lower()
    if normalized_state in {"FAILURE", "REVOKED"} or normalized_phase == "failed":
        return "failed"
    if normalized_state == "SUCCESS" or normalized_phase == "succeeded":
        return "succeeded"
    if normalized_state in {"PENDING", "RECEIVED"}:
        return "queued"
    if normalized_phase in {"queued", "preparing"}:
        return "queued"
    return "running"


def _emit_download_job_event(
    *,
    job_id: str,
    kind: str,
    model_id: str,
    target_dir: str,
    phase: str,
    summary: str,
    state: str,
    log_lines: list[str],
    percent: float | None = None,
) -> None:
    status = _download_job_status_from_task_state(phase=phase, state=state)
    payload = {
        "download_job": {
            "id": job_id,
            "kind": kind,
            "status": status,
            "phase": phase,
            "model_id": model_id,
            "target_dir": target_dir,
            "summary": summary,
            "error": summary if status == "failed" else "",
            "percent": percent,
            "log_lines": list(log_lines),
        }
    }
    emit_contract_event(
        event_type=(
            "download.job.completed"
            if status in {"failed", "succeeded"}
            else "download.job.updated"
        ),
        entity_kind="download_job",
        entity_id=job_id,
        room_keys=download_scope_rooms(job_id=job_id),
        payload=payload,
        runtime=None,
    )


def _serialize_materialized_paths(paths: list[str]) -> str | None:
    if not paths:
        return None
    return _json_dumps([str(path) for path in paths])


def _parse_feature_flag(
    settings: dict[str, str],
    *,
    key: str,
    default: bool,
) -> bool:
    raw = settings.get(key)
    if raw is None:
        return default
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    return default


def _instruction_native_enabled(
    provider: str,
    llm_settings: dict[str, str],
) -> bool:
    normalized = str(provider or "").strip().lower()
    default_enabled = INSTRUCTION_NATIVE_ENABLED_DEFAULTS.get(normalized, False)
    return _parse_feature_flag(
        llm_settings,
        key=f"instruction_native_enabled_{normalized}",
        default=default_enabled,
    )


def _instruction_fallback_enabled(
    provider: str,
    llm_settings: dict[str, str],
) -> bool:
    normalized = str(provider or "").strip().lower()
    default_enabled = INSTRUCTION_FALLBACK_ENABLED_DEFAULTS.get(normalized, True)
    return _parse_feature_flag(
        llm_settings,
        key=f"instruction_fallback_enabled_{normalized}",
        default=default_enabled,
    )


def _is_subpath(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_instruction_materialized_paths(
    *,
    paths: list[str],
    workspace: Path,
    runtime_home: Path | None,
    codex_home: Path | None = None,
) -> None:
    allowed_roots = [workspace.resolve()]
    if runtime_home is not None:
        allowed_roots.append(runtime_home.resolve())
    if codex_home is not None:
        allowed_roots.append(codex_home.resolve())
    for raw_path in paths:
        candidate = Path(str(raw_path)).resolve()
        if any(_is_subpath(candidate, root) for root in allowed_roots):
            continue
        raise RuntimeError(
            "Instruction materialization path escapes run-local roots: "
            f"{candidate} (allowed roots: {allowed_roots})."
        )


def _log_instruction_package_observability(
    *,
    compiled_instruction_package,
    on_log: Callable[[str], None],
) -> None:
    manifest = dict(compiled_instruction_package.manifest or {})
    instruction_size = int(manifest.get("instruction_size_bytes") or 0)
    total_size = int(manifest.get("total_size_bytes") or 0)
    includes_priorities = bool(manifest.get("includes_priorities"))
    on_log(
        "Instruction package sizes: "
        f"instructions={instruction_size} bytes, total={total_size} bytes, "
        f"includes_priorities={'yes' if includes_priorities else 'no'}."
    )
    if instruction_size >= INSTRUCTION_SIZE_WARNING_BYTES:
        on_log(
            "Instruction size warning: instructions markdown is "
            f"{instruction_size} bytes (warning threshold {INSTRUCTION_SIZE_WARNING_BYTES})."
        )
    if total_size >= INSTRUCTION_TOTAL_SIZE_WARNING_BYTES:
        on_log(
            "Instruction size warning: total package is "
            f"{total_size} bytes (warning threshold {INSTRUCTION_TOTAL_SIZE_WARNING_BYTES})."
        )


def _log_instruction_reference_risk(
    *,
    compiled_instruction_package,
    on_log: Callable[[str], None],
) -> None:
    markdown = str(compiled_instruction_package.artifacts.get("INSTRUCTIONS.md") or "")
    if not markdown:
        return
    matches = re.findall(r"(?<!\w)@([^\s`]+)", markdown)
    flagged: list[str] = []
    for token in matches:
        candidate = str(token).strip()
        if not candidate:
            continue
        if (
            "/" in candidate
            or candidate.startswith((".", "~", "$"))
            or candidate.endswith(
                (".md", ".txt", ".json", ".yaml", ".yml", ".py", ".sh", ".cfg", ".toml")
            )
        ):
            if candidate not in flagged:
                flagged.append(candidate)
        if len(flagged) >= 5:
            break
    if not flagged:
        return
    on_log(
        "Instruction safety note: detected @file-style references in compiled instructions "
        "(accepted in phase 1): "
        + ", ".join(flagged)
    )


def _apply_instruction_adapter_policy(
    *,
    provider: str,
    llm_settings: dict[str, str],
    compiled_instruction_package,
    configured_agent_markdown_filename: str | None,
    workspace: Path,
    runtime_home: Path,
    codex_home: Path | None,
    payload: str,
    task_kind: str,
    on_log: Callable[[str], None],
) -> tuple[str, str, str, list[str]]:
    instruction_adapter = resolve_instruction_adapter(
        provider,
        agent_markdown_filename=configured_agent_markdown_filename,
    )
    descriptor = instruction_adapter.describe()
    native_enabled = _instruction_native_enabled(provider, llm_settings)
    fallback_enabled = _instruction_fallback_enabled(provider, llm_settings)
    on_log(
        "Instruction adapter flags: "
        f"native={'on' if native_enabled else 'off'}, "
        f"fallback={'on' if fallback_enabled else 'off'}."
    )

    def _apply_fallback(reason: str) -> tuple[str, str, str, list[str]]:
        if not fallback_enabled:
            raise RuntimeError(f"{reason} Fallback is disabled for provider '{provider}'.")
        on_log(f"{reason} Downgrading to prompt-envelope fallback.")
        downgraded_payload = _inject_instruction_fallback(
            payload,
            instruction_adapter.fallback_payload(compiled_instruction_package),
            task_kind,
        )
        return downgraded_payload, "fallback", descriptor.adapter, []

    if descriptor.supports_native and not native_enabled:
        return _apply_fallback(
            f"Native instruction adapter disabled for provider '{provider}'."
        )

    try:
        materialized = instruction_adapter.materialize(
            compiled_instruction_package,
            workspace=workspace,
            runtime_home=runtime_home,
            codex_home=codex_home,
        )
    except Exception as exc:
        return _apply_fallback(
            f"Instruction adapter materialization failed ({provider}): {exc}"
        )

    materialized_paths = list(materialized.materialized_paths)
    _validate_instruction_materialized_paths(
        paths=materialized_paths,
        workspace=workspace,
        runtime_home=runtime_home,
        codex_home=codex_home,
    )

    mode = str(materialized.mode or "").strip().lower() or "fallback"
    if mode == "fallback":
        if not fallback_enabled:
            raise RuntimeError(
                f"Instruction adapter returned fallback mode but fallback is disabled for '{provider}'."
            )
        downgraded_payload = _inject_instruction_fallback(
            payload,
            instruction_adapter.fallback_payload(compiled_instruction_package),
            task_kind,
        )
        return downgraded_payload, mode, materialized.adapter, materialized_paths
    return payload, mode, materialized.adapter, materialized_paths


def _validate_runtime_isolation_env(
    *,
    llm_env: dict[str, str],
    runtime_home: Path,
    codex_home: Path | None = None,
    on_log: Callable[[str], None] | None = None,
) -> None:
    resolved_runtime_home = runtime_home.resolve()
    configured_home = Path(str(llm_env.get("HOME") or "")).resolve()
    if configured_home != resolved_runtime_home:
        raise RuntimeError(
            "Runtime isolation failure: HOME is not run-local "
            f"({configured_home} != {resolved_runtime_home})."
        )
    if codex_home is not None:
        configured_codex_home = Path(str(llm_env.get("CODEX_HOME") or "")).resolve()
        resolved_codex_home = codex_home.resolve()
        if configured_codex_home != resolved_codex_home:
            raise RuntimeError(
                "Runtime isolation failure: CODEX_HOME is not run-local "
                f"({configured_codex_home} != {resolved_codex_home})."
            )
    if on_log is not None:
        on_log(
            "Runtime isolation paths: "
            f"HOME={resolved_runtime_home}"
            + (
                f", CODEX_HOME={codex_home.resolve()}"
                if codex_home is not None
                else ""
            )
            + "."
        )


def _provider_label(provider: str) -> str:
    return LLM_PROVIDER_LABELS.get(provider, provider)


def _build_mcp_config_map(
    servers: list[MCPServer],
) -> dict[str, dict[str, Any]]:
    configs: dict[str, dict[str, Any]] = {}
    for server in servers:
        if server.server_key in configs:
            raise ValueError(f"Duplicate MCP server key: {server.server_key}")
        configs[server.server_key] = parse_mcp_config(
            server.config_json, server_key=server.server_key
        )
    return configs


def _build_mcp_overrides_from_configs(
    configs: dict[str, dict[str, Any]],
) -> list[str]:
    overrides: list[str] = []
    for server_key in sorted(configs):
        overrides.extend(build_mcp_overrides(server_key, configs[server_key]))
    return overrides


_CODEX_KEY_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value)
    if isinstance(value, str):
        escaped = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        return f"\"{escaped}\""
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise ValueError("Codex config values must be scalars or arrays.")


def _format_codex_key_path(segments: list[str]) -> str:
    rendered = []
    for segment in segments:
        if _CODEX_KEY_SEGMENT_RE.fullmatch(segment):
            rendered.append(segment)
            continue
        escaped = segment.replace("\\", "\\\\").replace('"', '\\"')
        rendered.append(f"\"{escaped}\"")
    return ".".join(rendered)


def _codex_override(key_path: list[str], value: Any) -> str:
    return f"{_format_codex_key_path(key_path)}={_toml_value(value)}"


def _load_codex_auth_key() -> str:
    settings = load_integration_settings("llm")
    return (settings.get("codex_api_key") or "").strip()


def _load_gemini_auth_key() -> str:
    settings = load_integration_settings("llm")
    return (settings.get("gemini_api_key") or "").strip()


def _load_claude_auth_key() -> str:
    settings = load_integration_settings("llm")
    return (settings.get("claude_api_key") or "").strip()


def _resolve_claude_auth_key(
    env: dict[str, str] | None = None,
) -> tuple[str, str]:
    settings_key = _load_claude_auth_key()
    if settings_key:
        return settings_key, "integration_settings"
    source_env = env or os.environ
    env_key = str(source_env.get("ANTHROPIC_API_KEY") or "").strip()
    if env_key:
        return env_key, "environment"
    return "", ""


def _resolve_claude_install_script() -> Path:
    raw = str(Config.CLAUDE_CLI_INSTALL_SCRIPT or "").strip()
    candidate = Path(raw) if raw else Path("scripts/install/install-claude-cli.sh")
    if candidate == Path("app/llmctl-studio-backend/scripts/install-claude.sh"):
        candidate = Path("scripts/install/install-claude-cli.sh")
    if candidate.is_absolute():
        return candidate
    return (REPO_ROOT / candidate).resolve()


def _claude_cli_diagnostics(
    env: dict[str, str] | None = None,
) -> dict[str, object]:
    source_env = env or os.environ
    command = str(Config.CLAUDE_CMD or "claude").strip() or "claude"
    path = shutil.which(command, path=source_env.get("PATH"))
    diagnostics: dict[str, object] = {
        "command": command,
        "path": path or "",
        "installed": bool(path),
        "version": "",
        "error": "",
    }
    if not path:
        diagnostics["error"] = (
            f"Command '{command}' is not on PATH. "
            "Install Claude CLI or set CLAUDE_CMD to an absolute path."
        )
        return diagnostics
    try:
        result = subprocess.run(
            [command, "--version"],
            capture_output=True,
            text=True,
            env=source_env,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        diagnostics["error"] = f"Failed to read Claude CLI version: {exc}"
        return diagnostics
    version_text = (result.stdout or "").strip() or (result.stderr or "").strip()
    if result.returncode != 0:
        diagnostics["error"] = (
            "Claude CLI returned a non-zero exit code while checking version: "
            f"{version_text or 'unknown error'}"
        )
        return diagnostics
    if not version_text:
        diagnostics["error"] = "Claude CLI did not return a version string."
        return diagnostics
    diagnostics["version"] = version_text.splitlines()[0].strip()
    return diagnostics


def _ensure_claude_cli_ready(
    *,
    on_log: Callable[[str], None] | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, object]:
    diagnostics = _claude_cli_diagnostics(env=env)
    if diagnostics["installed"] and diagnostics["version"]:
        if on_log:
            on_log(
                "Claude runtime ready: "
                f"{diagnostics['command']} ({diagnostics['version']})."
            )
        return diagnostics

    install_script = _resolve_claude_install_script()
    should_install = bool(Config.CLAUDE_CLI_AUTO_INSTALL)
    if should_install:
        if on_log:
            on_log(
                "Claude CLI not ready; attempting install via "
                f"{install_script}."
            )
        if not install_script.exists():
            if on_log:
                on_log(
                    "Claude install script is missing: "
                    f"{install_script}."
                )
        else:
            install_result = subprocess.run(
                ["bash", str(install_script)],
                capture_output=True,
                text=True,
                env=env or os.environ,
                check=False,
            )
            if on_log and install_result.stdout.strip():
                on_log(install_result.stdout.strip().splitlines()[-1])
            if on_log and install_result.stderr.strip():
                on_log(install_result.stderr.strip().splitlines()[-1])
            diagnostics = _claude_cli_diagnostics(env=env)
            if diagnostics["installed"] and diagnostics["version"]:
                if on_log:
                    on_log(
                        "Claude install succeeded: "
                        f"{diagnostics['command']} ({diagnostics['version']})."
                    )
                return diagnostics

    error = str(diagnostics.get("error") or "Claude CLI is not ready.").strip()
    message = (
        "Claude runtime CLI check failed. "
        f"{error} "
        f"auto_install={'true' if should_install else 'false'} "
        f"require_ready={'true' if Config.CLAUDE_CLI_REQUIRE_READY else 'false'}."
    )
    if Config.CLAUDE_CLI_REQUIRE_READY:
        raise RuntimeError(message)
    if on_log:
        on_log(message)
    return diagnostics


def claude_runtime_diagnostics(
    *,
    env: dict[str, str] | None = None,
) -> dict[str, object]:
    cli = _claude_cli_diagnostics(env=env)
    auth_key, auth_source = _resolve_claude_auth_key(env=env)
    auth_required = bool(Config.CLAUDE_AUTH_REQUIRE_API_KEY)
    auth_ready = bool(auth_key)
    auth_status = "ready"
    if auth_required and not auth_ready:
        auth_status = "missing"
    elif not auth_required and not auth_ready:
        auth_status = "optional"
    return {
        "command": str(cli.get("command") or "claude"),
        "cli_installed": bool(cli.get("installed")),
        "cli_path": str(cli.get("path") or ""),
        "cli_version": str(cli.get("version") or ""),
        "cli_error": str(cli.get("error") or ""),
        "cli_ready": bool(cli.get("installed")) and bool(cli.get("version")),
        "auth_required": auth_required,
        "auth_ready": auth_ready,
        "auth_source": auth_source,
        "auth_status": auth_status,
        "auto_install_enabled": bool(Config.CLAUDE_CLI_AUTO_INSTALL),
        "require_cli_ready": bool(Config.CLAUDE_CLI_REQUIRE_READY),
    }


def _load_vllm_remote_auth_key() -> str:
    settings = load_integration_settings("llm")
    return (settings.get("vllm_remote_api_key") or "").strip() or Config.VLLM_REMOTE_API_KEY


def _load_vllm_remote_base_url() -> str:
    settings = load_integration_settings("llm")
    return (settings.get("vllm_remote_base_url") or "").strip() or Config.VLLM_REMOTE_BASE_URL


def _load_vllm_default_model(provider: str) -> str:
    settings = load_integration_settings("llm")
    key_name = "vllm_local_model" if provider == "vllm_local" else "vllm_remote_model"
    fallback = Config.VLLM_LOCAL_FALLBACK_MODEL if provider == "vllm_local" else Config.VLLM_REMOTE_DEFAULT_MODEL
    return (settings.get(key_name) or "").strip() or fallback


def _load_legacy_codex_model_config() -> dict[str, Any]:
    settings = load_integration_settings("llm")
    ignore_excludes_raw = settings.get("codex_shell_env_ignore_default_excludes")
    notice_hide_enabled_raw = settings.get("codex_notice_hide_enabled")
    return {
        "model": (settings.get("codex_model") or "").strip(),
        "approval_policy": (settings.get("codex_approval_policy") or "").strip(),
        "sandbox_mode": (settings.get("codex_sandbox_mode") or "").strip(),
        "network_access": (settings.get("codex_network_access") or "").strip(),
        "model_reasoning_effort": (
            (settings.get("codex_model_reasoning_effort") or "").strip()
        ),
        "shell_env_inherit": (settings.get("codex_shell_env_inherit") or "").strip(),
        "shell_env_ignore_default_excludes": None
        if ignore_excludes_raw is None
        else ignore_excludes_raw.strip().lower() == "true",
        "notice_hide_key": (settings.get("codex_notice_hide_key") or "").strip(),
        "notice_hide_enabled": None
        if notice_hide_enabled_raw is None
        else notice_hide_enabled_raw.strip().lower() == "true",
        "notice_migration_from": (
            (settings.get("codex_notice_migration_from") or "").strip()
        ),
        "notice_migration_to": (settings.get("codex_notice_migration_to") or "").strip(),
    }


def _parse_model_config(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_runtime_payload(
    provider: str,
    model_config: dict[str, Any] | None,
) -> dict[str, object]:
    model_name = ""
    if provider == "codex":
        config = model_config or _load_legacy_codex_model_config()
        model_name = str(config.get("model") or "").strip()
        if not model_name:
            model_name = Config.CODEX_MODEL or ""
    elif provider == "gemini":
        model_name = str((model_config or {}).get("model") or "").strip()
        if not model_name:
            model_name = Config.GEMINI_MODEL or ""
    elif provider == "claude":
        model_name = str((model_config or {}).get("model") or "").strip()
        if not model_name:
            model_name = Config.CLAUDE_MODEL or ""
    elif provider in {"vllm_local", "vllm_remote"}:
        model_name = str((model_config or {}).get("model") or "").strip()
        if not model_name:
            model_name = _load_vllm_default_model(provider)
    payload: dict[str, object] = {"provider": provider}
    if model_name:
        payload["model"] = model_name
    return payload


def _inject_runtime_metadata(
    prompt: str,
    runtime: dict[str, object] | None,
) -> str:
    if not runtime:
        return prompt
    payload = _load_prompt_dict(prompt)
    if payload is None:
        return prompt
    if is_prompt_envelope(payload):
        task_context = _ensure_task_context(payload)
        task_context["runtime"] = runtime
    else:
        payload["runtime"] = runtime
    return serialize_prompt_envelope(payload)


def _as_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


def _codex_settings_from_model_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": str(config.get("model") or "").strip(),
        "approval_policy": str(config.get("approval_policy") or "").strip(),
        "sandbox_mode": str(config.get("sandbox_mode") or "").strip(),
        "network_access": str(config.get("network_access") or "").strip(),
        "model_reasoning_effort": str(
            config.get("model_reasoning_effort") or ""
        ).strip(),
        "shell_env_inherit": str(config.get("shell_env_inherit") or "").strip(),
        "shell_env_ignore_default_excludes": _as_optional_bool(
            config.get("shell_env_ignore_default_excludes")
        ),
        "notice_hide_key": str(config.get("notice_hide_key") or "").strip(),
        "notice_hide_enabled": _as_optional_bool(config.get("notice_hide_enabled")),
        "notice_migration_from": str(
            config.get("notice_migration_from") or ""
        ).strip(),
        "notice_migration_to": str(config.get("notice_migration_to") or "").strip(),
    }


def _parse_gemini_extra_args(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        return shlex.split(raw)
    return [str(value)]


def _gemini_settings_from_model_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": str(config.get("model") or "").strip(),
        "approval_mode": str(config.get("approval_mode") or "").strip(),
        "sandbox": _as_optional_bool(config.get("sandbox")),
        "extra_args": _parse_gemini_extra_args(config.get("extra_args")),
    }


def _gemini_sandbox_available() -> bool:
    return bool(shutil.which("docker") or shutil.which("podman"))


def _build_codex_overrides(settings: dict[str, Any]) -> list[str]:
    overrides: list[str] = []
    if settings.get("approval_policy"):
        overrides.append(_codex_override(["approval_policy"], settings["approval_policy"]))
    if settings.get("sandbox_mode"):
        overrides.append(_codex_override(["sandbox_mode"], settings["sandbox_mode"]))
    if settings.get("network_access"):
        overrides.append(_codex_override(["network_access"], settings["network_access"]))
    if settings.get("model_reasoning_effort"):
        overrides.append(
            _codex_override(
                ["model_reasoning_effort"],
                settings["model_reasoning_effort"],
            )
        )
    if settings.get("shell_env_inherit"):
        overrides.append(
            _codex_override(
                ["shell_environment_policy", "inherit"],
                settings["shell_env_inherit"],
            )
        )
    if settings.get("shell_env_ignore_default_excludes") is not None:
        overrides.append(
            _codex_override(
                ["shell_environment_policy", "ignore_default_excludes"],
                bool(settings.get("shell_env_ignore_default_excludes")),
            )
        )
    notice_key = settings.get("notice_hide_key")
    if notice_key and settings.get("notice_hide_enabled") is not None:
        overrides.append(
            _codex_override(
                ["notice", notice_key],
                bool(settings.get("notice_hide_enabled")),
            )
        )
    migration_from = settings.get("notice_migration_from")
    migration_to = settings.get("notice_migration_to")
    if migration_from and migration_to:
        overrides.append(
            _codex_override(
                ["notice", "model_migrations", migration_from],
                migration_to,
            )
        )
    return overrides


def _build_codex_cmd(
    mcp_overrides: list[str] | None = None,
    codex_overrides: list[str] | None = None,
    model: str | None = None,
) -> list[str]:
    cmd = [Config.CODEX_CMD, "exec"]
    selected_model = model or Config.CODEX_MODEL
    if selected_model:
        cmd.extend(["--model", selected_model])
    cmd.append("--skip-git-repo-check")
    if codex_overrides:
        for override in codex_overrides:
            cmd.extend(["-c", override])
    if mcp_overrides:
        for override in mcp_overrides:
            cmd.extend(["-c", override])
    return cmd


def _build_gemini_cmd(
    mcp_server_names: list[str],
    model: str | None = None,
    approval_mode: str | None = None,
    extra_args: list[str] | None = None,
) -> list[str]:
    cmd = [Config.GEMINI_CMD]
    selected_model = model or Config.GEMINI_MODEL
    if selected_model:
        cmd.extend(["--model", selected_model])
    if approval_mode:
        cmd.extend(["--approval-mode", approval_mode])
    if extra_args:
        cmd.extend(extra_args)
    if mcp_server_names:
        cmd.append("--allowed-mcp-server-names")
        cmd.extend(mcp_server_names)
    return cmd


def _build_claude_cmd(
    mcp_config: str | None = None,
    model: str | None = None,
) -> list[str]:
    cmd = [Config.CLAUDE_CMD, "--print"]
    selected_model = model or Config.CLAUDE_MODEL
    if selected_model:
        cmd.extend(["--model", selected_model])
    if mcp_config:
        cmd.extend(["--mcp-config", mcp_config, "--strict-mcp-config"])
    return cmd


def _build_claude_mcp_config(
    configs: dict[str, dict[str, Any]],
) -> str | None:
    if not configs:
        return None
    payload = {"mcpServers": {key: configs[key] for key in sorted(configs)}}
    return json.dumps(payload, separators=(",", ":"))


def _safe_float(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int) -> int:
    if value is None:
        return default
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _normalize_vllm_base_url(base_url: str) -> str:
    normalized = (base_url or "").strip().rstrip("/")
    if not normalized:
        return ""
    if normalized.endswith("/v1"):
        return normalized
    return f"{normalized}/v1"


def _vllm_local_settings_from_model_config(config: dict[str, Any]) -> dict[str, Any]:
    model = str(config.get("model") or "").strip() or _load_vllm_default_model("vllm_local")
    return {
        "model": model,
        "temperature": _safe_float(config.get("temperature"), 0.2),
        "max_tokens": _safe_int(config.get("max_tokens"), 2048),
        "request_timeout_seconds": _safe_float(
            config.get("request_timeout_seconds"),
            180.0,
        ),
    }


def _vllm_remote_settings_from_model_config(config: dict[str, Any]) -> dict[str, Any]:
    base_url = _load_vllm_remote_base_url()
    override = str(config.get("base_url_override") or config.get("base_url") or "").strip()
    if override:
        base_url = override
    model = str(config.get("model") or "").strip() or _load_vllm_default_model("vllm_remote")
    return {
        "base_url": _normalize_vllm_base_url(base_url),
        "model": model,
        "api_key": _load_vllm_remote_auth_key(),
        "temperature": _safe_float(config.get("temperature"), 0.2),
        "max_tokens": _safe_int(config.get("max_tokens"), 4096),
        "request_timeout_seconds": _safe_float(
            config.get("request_timeout_seconds"),
            240.0,
        ),
    }


def _extract_vllm_message_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        segments: list[str] = []
        for item in content:
            if isinstance(item, str):
                segments.append(item)
                continue
            if isinstance(item, dict):
                text_value = item.get("text")
                if isinstance(text_value, str):
                    segments.append(text_value)
        return "\n".join(segment for segment in segments if segment)
    return ""


def _parse_cmd_with_fallback(raw: str, fallback: list[str]) -> list[str]:
    cleaned = (raw or "").strip()
    if not cleaned:
        return fallback
    try:
        parsed = shlex.split(cleaned)
    except ValueError:
        return [cleaned]
    return parsed or fallback


def _run_vllm_local_cli_completion(
    settings: dict[str, Any],
    prompt: str | None,
    on_update: Callable[[str, str], None] | None = None,
    on_log: Callable[[str], None] | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    model = str(settings.get("model") or "").strip()
    if not model:
        raise ValueError("vLLM local model is not configured.")
    temperature = settings.get("temperature")
    max_tokens = settings.get("max_tokens")
    timeout = max(1.0, _safe_float(settings.get("request_timeout_seconds"), 180.0))
    request_payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt or ""}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    cmd_prefix = _parse_cmd_with_fallback(
        Config.VLLM_LOCAL_CMD,
        ["vllm"],
    )
    with tempfile.TemporaryDirectory(prefix="llmctl-vllm-local-") as tmp_dir:
        input_path = Path(tmp_dir) / "batch-input.jsonl"
        output_path = Path(tmp_dir) / "batch-output.jsonl"
        input_line = {
            "custom_id": "llmctl-vllm-local",
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": request_payload,
        }
        input_path.write_text(
            json.dumps(input_line, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        cmd = list(cmd_prefix)
        if "run-batch" not in cmd:
            cmd.append("run-batch")
        cmd.extend(
            [
                "-i",
                str(input_path),
                "-o",
                str(output_path),
                "--model",
                model,
            ]
        )
        if on_log:
            on_log(f"Running vLLM Local CLI: {_format_cmd_for_log(cmd)}")
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                errors="replace",
                cwd=str(cwd) if cwd is not None else None,
                env=env,
                timeout=timeout,
            )
        except FileNotFoundError:
            message = (
                f"vLLM local command not found: {cmd_prefix[0]}. "
                "Install vLLM in the Studio container or set VLLM_LOCAL_CMD."
            )
            if on_update:
                on_update("", message)
            return subprocess.CompletedProcess(cmd, 127, "", message)
        except subprocess.TimeoutExpired:
            message = f"Timed out after {int(timeout)}s waiting for vLLM local CLI."
            if on_update:
                on_update("", message)
            return subprocess.CompletedProcess(cmd, 124, "", message)
        if result.returncode != 0:
            error_output = (
                (result.stderr or "").strip()
                or (result.stdout or "").strip()
                or f"vLLM local CLI exited with code {result.returncode}."
            )
            if on_update:
                on_update("", error_output)
            return subprocess.CompletedProcess(
                cmd,
                result.returncode,
                result.stdout or "",
                result.stderr or error_output,
            )
        if not output_path.exists():
            message = "vLLM local CLI did not produce a batch output file."
            if on_update:
                on_update("", message)
            return subprocess.CompletedProcess(
                cmd,
                1,
                result.stdout or "",
                message,
            )
        lines = [
            line.strip()
            for line in output_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not lines:
            message = "vLLM local CLI returned an empty batch output file."
            if on_update:
                on_update("", message)
            return subprocess.CompletedProcess(
                cmd,
                1,
                result.stdout or "",
                message,
            )
        try:
            payload = json.loads(lines[0])
        except json.JSONDecodeError as exc:
            message = f"Failed to parse vLLM local output JSON: {exc}"
            if on_update:
                on_update("", message)
            return subprocess.CompletedProcess(
                cmd,
                1,
                result.stdout or "",
                message,
            )
        if not isinstance(payload, dict):
            message = "vLLM local output payload must be a JSON object."
            if on_update:
                on_update("", message)
            return subprocess.CompletedProcess(
                cmd,
                1,
                result.stdout or "",
                message,
            )
        error_payload = payload.get("error")
        if error_payload:
            message = (
                error_payload
                if isinstance(error_payload, str)
                else json.dumps(error_payload, ensure_ascii=False)
            )
            if on_update:
                on_update("", message)
            return subprocess.CompletedProcess(
                cmd,
                1,
                result.stdout or "",
                message,
            )
        response_payload = payload.get("response")
        content = ""
        if isinstance(response_payload, dict):
            content = _extract_vllm_message_content(response_payload)
            if not content:
                body_payload = response_payload.get("body")
                if isinstance(body_payload, dict):
                    content = _extract_vllm_message_content(body_payload)
        if not content:
            content = result.stdout or json.dumps(payload, ensure_ascii=False)
        if on_update:
            on_update(content, "")
        return subprocess.CompletedProcess(cmd, 0, content, result.stderr or "")


def _run_vllm_remote_chat_completion(
    provider: str,
    settings: dict[str, Any],
    prompt: str | None,
    on_update: Callable[[str, str], None] | None = None,
) -> subprocess.CompletedProcess[str]:
    base_url = str(settings.get("base_url") or "").strip()
    model = str(settings.get("model") or "").strip()
    if not base_url:
        raise ValueError(f"{provider} base URL is not configured.")
    if not model:
        raise ValueError(f"{provider} model is not configured.")
    endpoint = f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt or "",
            }
        ],
        "temperature": settings.get("temperature"),
        "max_tokens": settings.get("max_tokens"),
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    api_key = str(settings.get("api_key") or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request_obj = Request(endpoint, data=data, headers=headers, method="POST")
    cmd = [provider, endpoint]
    timeout = _safe_float(settings.get("request_timeout_seconds"), 180.0)
    try:
        with urlopen(request_obj, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
        try:
            decoded = json.loads(body)
        except json.JSONDecodeError:
            decoded = {}
        output = _extract_vllm_message_content(decoded) or body
        if on_update:
            on_update(output, "")
        return subprocess.CompletedProcess(cmd, 0, output, "")
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        message = error_body or str(exc)
        if on_update:
            on_update("", message)
        return subprocess.CompletedProcess(cmd, exc.code or 1, "", message)
    except URLError as exc:
        message = str(exc)
        if on_update:
            on_update("", message)
        return subprocess.CompletedProcess(cmd, 1, "", message)


def _extract_list_config(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [value]
    raise ValueError(f"{label} must be a string or list.")


def _extract_mapping_config(value: Any, label: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a table of key/value pairs.")
    return {str(key): str(val) for key, val in value.items()}


def _redact_value(label: str, value: Any) -> Any:
    lowered = str(label).lower()
    if any(token in lowered for token in ("token", "secret", "password", "key", "authorization")):
        return "***"
    return value


def _redact_object(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {key: _redact_object(_redact_value(key, val)) for key, val in payload.items()}
    if isinstance(payload, list):
        return [_redact_object(item) for item in payload]
    return payload


def _format_cmd_for_log(cmd: list[str]) -> str:
    # Redact values following -e/--env and -H/--header to avoid leaking secrets.
    redacted: list[str] = []
    skip_next = False
    for idx, part in enumerate(cmd):
        if skip_next:
            redacted.append("***")
            skip_next = False
            continue
        if part in {"-e", "--env", "-H", "--header"}:
            redacted.append(part)
            skip_next = True
            continue
        redacted.append(part)
    return " ".join(redacted)


def _build_gemini_mcp_add_cmd(
    server_key: str,
    config: dict[str, Any],
    scope: str,
) -> list[str]:
    cmd = [Config.GEMINI_CMD, "mcp", "add", "--scope", scope]
    url = config.get("url")
    command = config.get("command")
    gemini_transport = config.get("gemini_transport")
    transport = config.get("transport")
    transport_value = str(transport).lower() if transport is not None else ""
    if gemini_transport is not None:
        transport_value = str(gemini_transport).lower()
    if transport_value in {"streamable-http", "streamable_http", "streamablehttp"}:
        transport_value = "http"
    if transport_value:
        cmd.extend(["--transport", transport_value])
    elif url:
        cmd.extend(["--transport", "http"])
    if _as_optional_bool(config.get("debug")):
        cmd.append("--debug")
    timeout = config.get("timeout")
    if timeout is not None:
        cmd.extend(["--timeout", str(timeout)])
    if config.get("trust") is True:
        cmd.append("--trust")
    description = config.get("description")
    if description:
        cmd.extend(["--description", str(description)])
    env = _extract_mapping_config(config.get("env"), "env")
    for key, value in env.items():
        cmd.extend(["-e", f"{key}={value}"])
    headers = _extract_mapping_config(config.get("headers"), "headers")
    if url and transport_value in {"", "http", "sse"}:
        if not any(key.lower() == "accept" for key in headers):
            headers["Accept"] = "application/json, text/event-stream"
    for key, value in headers.items():
        cmd.extend(["-H", f"{key}: {value}"])
    include_tools = _extract_list_config(config.get("include_tools"), "include_tools")
    for tool in include_tools:
        cmd.extend(["--include-tools", tool])
    exclude_tools = _extract_list_config(config.get("exclude_tools"), "exclude_tools")
    for tool in exclude_tools:
        cmd.extend(["--exclude-tools", tool])
    if url and command:
        raise ValueError(
            f"Gemini MCP config for {server_key} cannot include both url and command."
        )
    if url:
        cmd.append(server_key)
        cmd.append(str(url))
        return cmd
    if command:
        cmd.append(server_key)
        cmd.append(str(command))
        args = _extract_list_config(config.get("args"), "args")
        if args:
            cmd.append("--")
            cmd.extend(args)
        return cmd
    raise ValueError(
        f"Gemini MCP config for {server_key} must include url or command."
    )


def _run_config_cmd(
    cmd: list[str],
    on_log: Callable[[str], None] | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    ignore_failure: bool = False,
) -> None:
    result = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        env=dict(env) if env is not None else os.environ.copy(),
        cwd=str(cwd) if cwd is not None else None,
    )
    if result.stdout.strip() and on_log:
        on_log(result.stdout.rstrip())
    if result.stderr.strip() and on_log:
        on_log(result.stderr.rstrip())
    if result.returncode != 0 and not ignore_failure:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(message or f"Command failed: {' '.join(cmd)}")


def _log_gemini_settings(
    server_key: str,
    scope: str,
    cwd: str | Path | None,
    on_log: Callable[[str], None],
) -> None:
    settings_path = (
        Path(cwd) / ".gemini" / "settings.json"
        if scope == "project" and cwd is not None
        else Path.home() / ".gemini" / "settings.json"
    )
    if not settings_path.exists():
        on_log(f"Gemini settings not found at {settings_path}.")
        return
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception as exc:
        on_log(f"Failed to read Gemini settings: {exc}")
        return
    servers = (
        payload.get("mcpServers")
        or payload.get("mcp_servers")
        or payload.get("mcpServers".lower())
        or {}
    )
    if not isinstance(servers, dict):
        on_log("Gemini settings mcpServers is not a dict.")
        return
    entry = servers.get(server_key)
    if entry is None:
        on_log(f"Gemini settings missing MCP server '{server_key}'.")
        return
    on_log(
        "Gemini settings entry:\n"
        + json.dumps(_redact_object(entry), indent=2, sort_keys=True)
    )


def _ensure_gemini_mcp_servers(
    configs: dict[str, dict[str, Any]],
    on_log: Callable[[str], None] | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> None:
    if not configs:
        return
    scope = "project" if cwd is not None else "user"
    for server_key in sorted(configs):
        remove_cmd = [
            Config.GEMINI_CMD,
            "mcp",
            "remove",
            "--scope",
            scope,
            server_key,
        ]
        _run_config_cmd(
            remove_cmd,
            on_log=on_log,
            cwd=cwd,
            env=env,
            ignore_failure=True,
        )
        add_cmd = _build_gemini_mcp_add_cmd(server_key, configs[server_key], scope)
        debug_enabled = _as_optional_bool(configs[server_key].get("debug"))
        if on_log and debug_enabled:
            on_log(f"Gemini MCP add: {_format_cmd_for_log(add_cmd)}")
        _run_config_cmd(add_cmd, on_log=on_log, cwd=cwd, env=env)
        if on_log and debug_enabled:
            _log_gemini_settings(server_key, scope, cwd, on_log)


def _build_task_workspace(task_id: int) -> Path:
    return Path(Config.WORKSPACES_DIR) / f"task-{task_id}"


def _codex_homes_root() -> Path:
    return Path(Config.DATA_DIR) / "codex-homes"


def _build_task_codex_home(task_id: int) -> Path:
    return _codex_homes_root() / f"task-{task_id}"


def _build_task_runtime_home(task_id: int) -> Path:
    return Path(Config.WORKSPACES_DIR) / f"task-{task_id}-home"


def _prepare_task_runtime_home(task_id: int) -> Path:
    runtime_home = _build_task_runtime_home(task_id)
    _cleanup_workspace(task_id, runtime_home, label="runtime home")
    runtime_home.mkdir(parents=True, exist_ok=True)
    (runtime_home / ".config").mkdir(parents=True, exist_ok=True)
    (runtime_home / ".cache").mkdir(parents=True, exist_ok=True)
    (runtime_home / ".local" / "share").mkdir(parents=True, exist_ok=True)
    return runtime_home


def _apply_run_local_home_env(env: dict[str, str], runtime_home: Path) -> None:
    env["HOME"] = str(runtime_home)
    env["XDG_CONFIG_HOME"] = str(runtime_home / ".config")
    env["XDG_CACHE_HOME"] = str(runtime_home / ".cache")
    env["XDG_DATA_HOME"] = str(runtime_home / ".local" / "share")


def _resolve_codex_home_from_env(env: dict[str, str]) -> Path:
    configured = (env.get("CODEX_HOME") or "").strip()
    if configured:
        return Path(configured)
    home = (env.get("HOME") or "").strip()
    if home:
        return Path(home) / ".codex"
    return Path.home() / ".codex"


def _cleanup_codex_home(task_id: int, codex_home: Path | None) -> None:
    if codex_home is None:
        return
    root = _codex_homes_root()
    try:
        root_resolved = root.resolve()
    except FileNotFoundError:
        root_resolved = root
    try:
        codex_home_resolved = codex_home.resolve()
    except FileNotFoundError:
        codex_home_resolved = codex_home
    if (
        codex_home_resolved == root_resolved
        or root_resolved not in codex_home_resolved.parents
    ):
        logger.warning(
            "Skipping codex home cleanup for task %s; path outside codex home root: %s",
            task_id,
            codex_home,
        )
        return
    try:
        shutil.rmtree(codex_home)
        logger.info("Removed codex home %s for task %s", codex_home, task_id)
    except FileNotFoundError:
        return
    except Exception:
        logger.exception("Failed to remove codex home %s for task %s", codex_home, task_id)


def _prepare_task_codex_home(task_id: int, seed_home: Path | None = None) -> Path:
    codex_home = _build_task_codex_home(task_id)
    codex_home.parent.mkdir(parents=True, exist_ok=True)
    _cleanup_codex_home(task_id, codex_home)
    codex_home.mkdir(parents=True, exist_ok=True)
    if seed_home is not None:
        for file_name in ("auth.json", "config.toml", "config.toml.bak"):
            source = seed_home / file_name
            if not source.is_file():
                continue
            try:
                shutil.copy2(source, codex_home / file_name)
            except Exception:
                logger.exception(
                    "Failed to seed %s into codex home for task %s", file_name, task_id
                )
    return codex_home


SCRIPTS_DIRNAME = "agent-scripts"
_WORKSPACE_DIR_RE = re.compile(r"^task-(\d+)(-pre-init)?$")
_ACTIVE_TASK_STATUSES = {"pending", "queued", "running"}


def _build_script_staging_dir(task_id: int) -> Path:
    return Path(Config.WORKSPACES_DIR) / f"task-{task_id}-pre-init"


def _safe_script_filename(file_name: str, fallback: str) -> str:
    cleaned = Path(file_name).name if file_name else ""
    if not cleaned or cleaned in {".", ".."}:
        return fallback
    return cleaned


def _materialize_scripts(
    scripts: list[Script],
    target_dir: Path,
    on_log: Callable[[str], None] | None = None,
) -> list[dict[str, str]]:
    if not scripts:
        return []
    target_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, str]] = []
    used_names: set[str] = set()
    seen_ids: set[int] = set()
    for script in scripts:
        if script.id in seen_ids:
            continue
        seen_ids.add(script.id)
        if not script.file_path:
            raise RuntimeError(f"Script file missing for {script.file_name}.")
        source_path = Path(script.file_path)
        if not source_path.is_file():
            raise RuntimeError(f"Script file missing for {script.file_name}.")
        fallback = f"script-{script.id}"
        base_name = _safe_script_filename(script.file_name, fallback)
        file_name = base_name
        if file_name in used_names:
            file_name = f"{script.id}-{base_name}"
        used_names.add(file_name)
        runtime_path = target_dir / file_name
        shutil.copy2(source_path, runtime_path)
        try:
            runtime_path.chmod(0o755)
        except OSError:
            pass
        entries.append(
            {
                "id": str(script.id),
                "file_name": script.file_name,
                "path": str(source_path),
                "runtime_path": str(runtime_path),
                "description": script.description or "",
                "script_type": script.script_type,
            }
        )
    if on_log:
        on_log(f"Prepared {len(entries)} script(s) in {target_dir}.")
    return entries


def _run_script(
    path: Path,
    label: str,
    on_log: Callable[[str], None],
) -> None:
    on_log(f"Running script: {label}")
    process = subprocess.Popen(
        [str(path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=os.environ.copy(),
        cwd=str(path.parent),
        bufsize=1,
    )
    if process.stdout is not None:
        for line in iter(process.stdout.readline, ""):
            trimmed = line.rstrip("\r\n")
            if trimmed:
                on_log(trimmed)
    returncode = process.wait()
    if returncode != 0:
        raise RuntimeError(f"Script {label} exited with code {returncode}.")


def _run_stage_scripts(
    stage_label: str,
    scripts: list[Script],
    entries: list[dict[str, str]],
    on_log: Callable[[str], None],
) -> None:
    if not scripts:
        on_log(f"No {stage_label.lower()} scripts configured.")
        return
    entries_by_id = {entry["id"]: entry for entry in entries}
    for script in scripts:
        entry = entries_by_id.get(str(script.id))
        if entry is None:
            raise RuntimeError(f"Script file missing for {script.file_name}.")
        runtime_path = entry.get("runtime_path") or entry.get("path")
        if not runtime_path:
            raise RuntimeError(f"Script file missing for {script.file_name}.")
        _run_script(Path(runtime_path), script.file_name, on_log)


def _clone_github_repo(
    repo: str,
    dest: Path,
    on_log: Callable[[str], None] | None = None,
    pat: str | None = None,
    ssh_key_path: str | None = None,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if on_log:
        on_log(f"Cloning GitHub repo {repo} into {dest}...")
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    repo_url: str | None = None
    ssh_key = (ssh_key_path or "").strip()
    if ssh_key:
        key_path = Path(ssh_key)
        if key_path.is_file():
            ssh_binary = shutil.which("ssh") or shutil.which("ssh", path=os.defpath)
            if not ssh_binary:
                if on_log:
                    on_log(
                        "SSH client not found in runtime; falling back to HTTPS for GitHub clone."
                    )
            else:
                known_hosts_path = Path(Config.DATA_DIR) / "known_hosts"
                ssh_cmd = [
                    ssh_binary,
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "StrictHostKeyChecking=accept-new",
                    "-o",
                    f"UserKnownHostsFile={known_hosts_path}",
                    "-i",
                    str(key_path),
                    "-o",
                    "IdentitiesOnly=yes",
                ]
                env["GIT_SSH_COMMAND"] = shlex.join(ssh_cmd)
                repo_url = f"git@github.com:{repo}.git"
                if on_log:
                    on_log("Using uploaded SSH key for GitHub clone.")
        elif on_log:
            on_log("Configured SSH key not found; falling back to HTTPS.")
    if repo_url is None:
        token = (pat or "").strip()
        if token:
            repo_url = f"https://x-access-token:{token}@github.com/{repo}.git"
        else:
            repo_url = f"https://github.com/{repo}.git"
        if on_log:
            on_log("Using HTTPS for GitHub clone.")
    result = subprocess.run(
        ["git", "clone", repo_url, str(dest)],
        text=True,
        capture_output=True,
        env=env,
        cwd=str(dest.parent),
    )
    if result.stdout.strip() and on_log:
        on_log(result.stdout.rstrip())
    if result.stderr.strip() and on_log:
        on_log(result.stderr.rstrip())
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(message or "Git clone failed.")
    if on_log:
        on_log("GitHub clone completed.")
    if on_log:
        on_log("Fetching latest refs...")
    fetch_result = subprocess.run(
        ["git", "fetch"],
        text=True,
        capture_output=True,
        env=env,
        cwd=str(dest),
    )
    if fetch_result.stdout.strip() and on_log:
        on_log(fetch_result.stdout.rstrip())
    if fetch_result.stderr.strip() and on_log:
        on_log(fetch_result.stderr.rstrip())
    if fetch_result.returncode != 0:
        message = fetch_result.stderr.strip() or fetch_result.stdout.strip()
        raise RuntimeError(message or "Git fetch failed.")
    if on_log:
        on_log("Git fetch completed.")


def _maybe_checkout_repo(
    task_id: int, on_log: Callable[[str], None] | None = None
) -> Path | None:
    settings = load_integration_settings("github")
    repo = (settings.get("repo") or "").strip()
    if not repo:
        logger.warning("GitHub integration is connected but no repo is selected.")
        if on_log:
            on_log("GitHub integration has no repo selected; skipping checkout.")
        return None
    pat = (settings.get("pat") or "").strip()
    ssh_key_path = (settings.get("ssh_key_path") or "").strip()
    if not ssh_key_path and on_log:
        on_log("No GitHub SSH key uploaded; using HTTPS clone.")
    workspace = _build_task_workspace(task_id)
    if workspace.exists():
        if workspace.is_dir() and (workspace / ".git").is_dir():
            if on_log:
                on_log(f"Using existing workspace {workspace}.")
            return workspace
        raise RuntimeError(
            f"Workspace path exists but is not a git checkout: {workspace}"
        )
    logger.info("Cloning GitHub repo %s for task %s", repo, task_id)
    _clone_github_repo(
        repo,
        workspace,
        on_log=on_log,
        pat=pat,
        ssh_key_path=ssh_key_path,
    )
    return workspace


def _cleanup_workspace(task_id: int, workspace: Path | None, label: str = "workspace") -> None:
    if workspace is None:
        return
    root = Path(Config.WORKSPACES_DIR)
    try:
        root_resolved = root.resolve()
    except FileNotFoundError:
        root_resolved = root
    try:
        workspace_resolved = workspace.resolve()
    except FileNotFoundError:
        workspace_resolved = workspace
    if workspace_resolved == root_resolved or root_resolved not in workspace_resolved.parents:
        logger.warning(
            "Skipping %s cleanup for task %s; path outside workspace root: %s",
            label,
            task_id,
            workspace,
        )
        return
    try:
        shutil.rmtree(workspace)
        logger.info("Removed %s %s for task %s", label, workspace, task_id)
    except FileNotFoundError:
        return
    except Exception:
        logger.exception("Failed to remove workspace %s for task %s", workspace, task_id)


def _parse_workspace_entry(entry: Path) -> tuple[int, str] | None:
    match = _WORKSPACE_DIR_RE.match(entry.name)
    if not match:
        return None
    task_id = int(match.group(1))
    label = "script staging" if match.group(2) else "workspace"
    return task_id, label


@celery_app.task(bind=True)
def cleanup_workspaces(self) -> dict[str, int]:
    init_engine(Config.SQLALCHEMY_DATABASE_URI)
    init_db()

    root = Path(Config.WORKSPACES_DIR)
    if not root.exists():
        logger.info("Workspace cleanup skipped; root not found: %s", root)
        return {"scanned": 0, "deleted": 0, "skipped_active": 0, "missing_tasks": 0}

    entries: list[tuple[Path, int, str]] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        parsed = _parse_workspace_entry(entry)
        if parsed is None:
            continue
        task_id, label = parsed
        entries.append((entry, task_id, label))

    if not entries:
        return {"scanned": 0, "deleted": 0, "skipped_active": 0, "missing_tasks": 0}

    task_ids = {task_id for _, task_id, _ in entries}
    with session_scope() as session:
        rows = session.execute(
            select(AgentTask.id, AgentTask.status).where(AgentTask.id.in_(task_ids))
        ).all()
    status_by_task_id = {row[0]: row[1] for row in rows}

    deleted = 0
    skipped_active = 0
    missing_tasks = 0

    for entry, task_id, label in entries:
        status = status_by_task_id.get(task_id)
        if status in _ACTIVE_TASK_STATUSES:
            skipped_active += 1
            continue
        if status is None:
            missing_tasks += 1
        _cleanup_workspace(task_id, entry, label=label)
        deleted += 1

    logger.info(
        "Workspace cleanup scanned %s entries; deleted=%s skipped_active=%s missing_tasks=%s",
        len(entries),
        deleted,
        skipped_active,
        missing_tasks,
    )
    return {
        "scanned": len(entries),
        "deleted": deleted,
        "skipped_active": skipped_active,
        "missing_tasks": missing_tasks,
    }


@celery_app.task(bind=True, name="services.tasks.run_huggingface_download_task")
def run_huggingface_download_task(
    self,
    *,
    kind: str,
    model_id: str,
    model_dir_name: str,
    token: str,
    model_container_path: str,
) -> dict[str, object]:
    job_id = str(self.request.id or "")
    target_dir = str(vllm_local_model_directory(model_dir_name))
    log_lines: deque[str] = deque(maxlen=24)

    def _task_update(
        *,
        phase: str,
        summary: str,
        percent: float | None = None,
        raw_line: str = "",
        state: str = "PROGRESS",
    ) -> None:
        if raw_line:
            log_lines.append(raw_line[:240])
        meta: dict[str, object] = {
            "kind": kind,
            "model_id": model_id,
            "target_dir": target_dir,
            "phase": phase,
            "summary": summary,
            "log_lines": list(log_lines),
        }
        if percent is not None:
            meta["percent"] = max(0.0, min(100.0, float(percent)))
        self.update_state(state=state, meta=meta)
        if job_id:
            _emit_download_job_event(
                job_id=job_id,
                kind=kind,
                model_id=model_id,
                target_dir=target_dir,
                phase=phase,
                summary=summary,
                state=state,
                log_lines=list(log_lines),
                percent=(meta.get("percent") if percent is not None else None),
            )

    _task_update(
        phase="preparing",
        summary=f"Preparing download for {model_id}.",
        percent=1.0,
        state="STARTED",
    )
    try:
        run_huggingface_model_download(
            model_id,
            model_dir_name,
            token=token,
            model_container_path=model_container_path,
            progress_callback=lambda payload: _task_update(
                phase=str(payload.get("phase") or "downloading"),
                summary=str(payload.get("summary") or "Downloading..."),
                percent=(
                    float(payload["percent"])
                    if payload.get("percent") is not None
                    else None
                ),
                raw_line=str(payload.get("raw_line") or ""),
            ),
        )
    except FileNotFoundError as exc:
        message = str(exc)
        _task_update(phase="failed", summary=message, state="FAILURE")
        raise RuntimeError(message) from exc
    except ValueError as exc:
        message = str(exc)
        _task_update(phase="failed", summary=message, state="FAILURE")
        raise RuntimeError(message) from exc
    except subprocess.CalledProcessError as exc:
        message = summarize_subprocess_error(exc)
        _task_update(phase="failed", summary=message, state="FAILURE")
        raise RuntimeError(message) from exc
    except Exception as exc:  # pragma: no cover - defensive path
        logger.exception("Unexpected HuggingFace download failure.")
        message = "Download failed due to an unexpected error."
        _task_update(phase="failed", summary=message, state="FAILURE")
        raise RuntimeError(message) from exc

    _task_update(
        phase="succeeded",
        summary=f"Downloaded {model_id} to {target_dir}.",
        percent=100.0,
        state="SUCCESS",
    )

    return {
        "kind": kind,
        "model_id": model_id,
        "target_dir": target_dir,
        "phase": "succeeded",
        "summary": f"Downloaded {model_id} to {target_dir}.",
        "percent": 100.0,
        "log_lines": list(log_lines),
    }


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


def _build_role_markdown(role: Role | None) -> str:
    if role is None:
        return ""
    lines = [
        "# Role",
        "",
        f"Name: {role.name}",
        "",
        "## Description",
        "",
        role.description or "No role description provided.",
    ]
    details = _load_role_details(role)
    if details:
        lines.extend(
            [
                "",
                "## Details",
                "",
                "```json",
                json.dumps(details, indent=2, sort_keys=True),
                "```",
            ]
        )
    return "\n".join(lines)


def _build_agent_markdown(agent: Agent) -> str:
    lines = [
        "# Agent",
        "",
        f"ID: {agent.id}",
        f"Name: {agent.name}",
        "",
        "## Description",
        "",
        agent.description or "No agent description provided.",
    ]
    prompt_payload = _load_prompt_payload(agent.prompt_json, agent.prompt_text)
    if isinstance(prompt_payload, dict) and prompt_payload:
        prompt_payload = dict(prompt_payload)
        prompt_payload.pop("autoprompt", None)
    if isinstance(prompt_payload, dict) and prompt_payload:
        lines.extend(
            [
                "",
                "## Prompt Payload",
                "",
                "```json",
                json.dumps(prompt_payload, indent=2, sort_keys=True),
                "```",
            ]
        )
    elif isinstance(prompt_payload, str) and prompt_payload.strip():
        lines.extend(
            [
                "",
                "## Prompt Text",
                "",
                prompt_payload.strip(),
            ]
        )
    return "\n".join(lines)


def _serialize_agent_priorities(agent: Agent | None) -> tuple[str, ...]:
    if agent is None:
        return tuple()
    ordered = sorted(
        list(agent.priorities or []),
        key=lambda item: (
            int(item.position) if item.position is not None else 2**31 - 1,
            int(item.id),
        ),
    )
    serialized: list[str] = []
    for entry in ordered:
        content = str(entry.content or "").strip()
        if content:
            serialized.append(content)
    return tuple(serialized)


def _build_attachment_entries(
    attachments: list[Attachment],
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for attachment in attachments:
        path = attachment.file_path or attachment.file_name
        entry: dict[str, object] = {
            "id": attachment.id,
            "file_name": attachment.file_name,
            "path": path,
        }
        try:
            entry["path_stem"] = Path(str(path)).stem
        except (TypeError, ValueError):
            pass
        if attachment.content_type:
            entry["content_type"] = attachment.content_type
        if attachment.size_bytes:
            entry["size_bytes"] = attachment.size_bytes
        entries.append(entry)
    return entries


def _merge_attachment_entries(
    first: list[dict[str, object]],
    second: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not second:
        return list(first)
    combined: list[dict[str, object]] = []
    seen: set[object] = set()
    for entry in list(first) + list(second):
        if entry is None:
            continue
        if isinstance(entry, dict):
            key = entry.get("path") or entry.get("id") or entry.get("file_name")
            if key in seen:
                continue
            seen.add(key)
            combined.append(entry)
        else:
            key = str(entry)
            if key in seen:
                continue
            seen.add(key)
            combined.append({"path": key})
    return combined


def _format_attachment_prompt(
    prompt: str,
    attachments: list[dict[str, object]],
) -> str:
    if not attachments:
        return prompt
    if "Attachments:" in prompt:
        return prompt
    lines = ["Attachments:"]
    for entry in attachments:
        path = entry.get("path") or entry.get("file_name") or "attachment"
        content_type = entry.get("content_type")
        if isinstance(content_type, str) and content_type:
            lines.append(f"- {path} ({content_type})")
        else:
            lines.append(f"- {path}")
    block = "\n".join(lines)
    if not prompt.strip():
        return block
    return f"{block}\n\n{prompt}"


def _inject_attachments(
    prompt: str,
    attachments: list[dict[str, object]],
    replace_existing: bool = False,
) -> str:
    payload = _load_prompt_dict(prompt)
    if payload is not None and is_prompt_envelope(payload):
        task_context = _ensure_task_context(payload)
        if not attachments:
            if replace_existing:
                task_context.pop("attachments", None)
                return serialize_prompt_envelope(payload)
            return prompt
        existing = task_context.get("attachments")
        if isinstance(existing, list):
            task_context["attachments"] = (
                attachments
                if replace_existing
                else _merge_attachment_entries(existing, attachments)
            )
        else:
            task_context["attachments"] = attachments
        return serialize_prompt_envelope(payload)
    if not attachments:
        if not replace_existing:
            return prompt
        if payload is None:
            return prompt
        payload.pop("attachments", None)
        return json.dumps(payload, indent=2, sort_keys=True)
    if payload is None:
        return _format_attachment_prompt(prompt, attachments)
    existing = payload.get("attachments")
    if isinstance(existing, list):
        if replace_existing:
            payload["attachments"] = attachments
        else:
            merged = _merge_attachment_entries(existing, attachments)
            payload["attachments"] = merged
    elif "attachments" not in payload:
        payload["attachments"] = attachments
    return json.dumps(payload, indent=2, sort_keys=True)


def _attach_task_attachments(task: AgentTask, attachments: list[Attachment]) -> None:
    if not attachments:
        return
    existing_ids = {item.id for item in task.attachments}
    for attachment in attachments:
        if attachment.id in existing_ids:
            continue
        task.attachments.append(attachment)


def _merge_attachments(
    first: list[Attachment],
    second: list[Attachment],
) -> list[Attachment]:
    merged: list[Attachment] = []
    seen: set[int] = set()
    for attachment in list(first) + list(second):
        attachment_id = int(getattr(attachment, "id", 0) or 0)
        if attachment_id <= 0 or attachment_id in seen:
            continue
        seen.add(attachment_id)
        merged.append(attachment)
    return merged


def _build_agent_payload(agent: Agent) -> dict[str, object]:
    description = agent.description or agent.name or ""
    return {
        "id": agent.id,
        "name": agent.name,
        "description": description,
    }


def _build_agent_prompt_payload(agent: Agent) -> dict[str, object]:
    agent_payload = _build_agent_payload(agent)
    role = agent.role
    if agent.role_id and role is not None:
        agent_payload["role"] = _build_role_payload(role)
    return agent_payload


def _build_system_contract(agent: Agent | None) -> dict[str, object]:
    if agent is None or not agent.role_id or agent.role is None:
        return {}
    return {"role": _build_role_payload(agent.role)}


def build_one_off_output_contract() -> dict[str, object]:
    return {
        "mode": "one_off",
        "no_followups": True,
        "format": {
            "name": "markdown",
            "dialect": "commonmark",
            "when": "if_needed_or_used",
            "valid_syntax_required": True,
        },
        "instructions": [
            OUTPUT_INSTRUCTIONS_ONE_OFF,
            OUTPUT_INSTRUCTIONS_MARKDOWN,
        ],
    }


def _build_output_contract() -> dict[str, object]:
    return build_one_off_output_contract()


def _build_autorun_user_request(agent: Agent) -> str:
    priorities = _serialize_agent_priorities(agent)
    if priorities:
        return (
            "Execute work for this agent based on the configured priority order. "
            "Start from the highest priority and continue making concrete progress."
        )
    return (
        "Execute work for this agent based on its role and description, and continue "
        "making concrete progress."
    )


def _build_default_task_user_request(agent: Agent) -> str:
    description = str(agent.description or "").strip()
    if description:
        return description
    name = str(agent.name or "").strip()
    if name:
        return f"Execute work for agent '{name}' based on the configured role."
    return "Execute work for the configured agent based on the role."


def _build_run_prompt_payload(agent: Agent) -> str:
    envelope = build_prompt_envelope(
        user_request=_build_autorun_user_request(agent),
        system_contract=_build_system_contract(agent),
        agent_profile=_build_agent_payload(agent),
        task_context={"kind": "autorun"},
        output_contract=_build_output_contract(),
    )
    return serialize_prompt_envelope(envelope)


def _render_prompt(agent: Agent) -> str:
    envelope = build_prompt_envelope(
        user_request=_build_default_task_user_request(agent),
        system_contract=_build_system_contract(agent),
        agent_profile=_build_agent_payload(agent),
        task_context={"kind": "task"},
        output_contract=_build_output_contract(),
    )
    return serialize_prompt_envelope(envelope)


def _format_repo_prompt(prompt: str, repo: str, workspace: str | None = None) -> str:
    repo_line = f"Default GitHub repository: {repo}"
    workspace_line = (
        f"Workspace path (checked out from default repo): {workspace}"
        if workspace
        else None
    )
    if repo_line in prompt and (workspace_line is None or workspace_line in prompt):
        return prompt
    if not prompt.strip():
        lines = [repo_line]
        if workspace_line:
            lines.append(workspace_line)
        return "\n".join(lines)
    prefix_lines = []
    if repo_line not in prompt:
        prefix_lines.append(repo_line)
    if workspace_line and workspace_line not in prompt:
        prefix_lines.append(workspace_line)
    if not prefix_lines:
        return prompt
    prefix = "\n".join(prefix_lines)
    return f"{prefix}\n\n{prompt}"


def _format_instruction_fallback_prompt(
    prompt: str,
    instruction_payload: dict[str, object] | str,
) -> str:
    marker = "Runtime instructions (fallback context):"
    if marker in prompt:
        return prompt
    if isinstance(instruction_payload, dict):
        markdown = str(instruction_payload.get("instructions_markdown") or "").strip()
        file_name = str(instruction_payload.get("materialized_filename") or "").strip()
    else:
        markdown = str(instruction_payload or "").strip()
        file_name = ""
    if not markdown:
        return prompt
    lines = [marker]
    if file_name:
        lines.append(f"- materialized_filename: {file_name}")
    lines.append(markdown)
    block = "\n".join(lines).strip()
    if not prompt.strip():
        return block
    return f"{block}\n\n{prompt}"


def _inject_instruction_fallback(
    prompt: str,
    instruction_payload: dict[str, object] | str,
    task_kind: str | None,
) -> str:
    payload = _load_prompt_dict(prompt)
    if payload is not None and is_prompt_envelope(payload):
        task_context = _ensure_task_context(payload)
        task_context["kind"] = task_kind or task_context.get("kind") or "task"
        if isinstance(instruction_payload, dict):
            task_context["instructions"] = instruction_payload
        else:
            task_context["instructions"] = {
                "instructions_markdown": str(instruction_payload or "")
            }
        return serialize_prompt_envelope(payload)
    stripped = prompt.strip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            prompt_value = payload.get("prompt")
            if isinstance(prompt_value, str):
                payload["prompt"] = _format_instruction_fallback_prompt(
                    prompt_value,
                    instruction_payload,
                )
            else:
                payload["instructions"] = instruction_payload
            return json.dumps(payload, indent=2, sort_keys=True)
    return _format_instruction_fallback_prompt(prompt, instruction_payload)


def _should_use_prompt_payload(task_kind: str | None) -> bool:
    return is_quick_task_kind(task_kind)


def _load_prompt_dict(prompt: str) -> dict[str, object] | None:
    stripped = prompt.strip()
    if not stripped.startswith("{"):
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _ensure_task_context(payload: dict[str, object]) -> dict[str, object]:
    task_context = payload.get("task_context")
    if isinstance(task_context, dict):
        return task_context
    task_context = {}
    payload["task_context"] = task_context
    return task_context


def _inject_github_repo(
    prompt: str,
    repo: str,
    task_kind: str | None,
    workspace: Path | str | None = None,
) -> str:
    payload = _load_prompt_dict(prompt)
    if payload is not None and is_prompt_envelope(payload):
        task_context = _ensure_task_context(payload)
        task_context["kind"] = task_kind or task_context.get("kind") or "task"
        integrations = task_context.get("integrations")
        integrations_payload: dict[str, object]
        if isinstance(integrations, dict):
            integrations_payload = integrations
        else:
            integrations_payload = {}
            task_context["integrations"] = integrations_payload
        github_payload = integrations_payload.get("github")
        if not isinstance(github_payload, dict):
            github_payload = {}
            integrations_payload["github"] = github_payload
        github_payload["repo"] = repo
        github_payload["note"] = (
            "All instructions in the prompt relate to the GitHub repo and its local workspace. "
            "Do not use any other repo or local workspace."
        )
        if workspace:
            workspace_path = str(workspace)
            github_payload["workspace"] = workspace_path
            task_context["workspace"] = {
                "path": workspace_path,
                "note": "Workspace path is a local git clone of the configured GitHub repo.",
            }
        return serialize_prompt_envelope(payload)
    if _should_use_prompt_payload(task_kind):
        return prompt
    workspace_path = str(workspace) if workspace else None
    stripped = prompt.strip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            prompt_value = payload.get("prompt")
            if isinstance(prompt_value, str):
                payload["prompt"] = _format_repo_prompt(
                    prompt_value,
                    repo,
                    workspace_path,
                )
                return json.dumps(payload, indent=2, sort_keys=True)
            if _should_use_prompt_payload(task_kind):
                return _format_repo_prompt(prompt, repo, workspace_path)
            existing_repo = payload.get("github_repo")
            if not isinstance(existing_repo, str) or not existing_repo.strip():
                payload["github_repo"] = repo
            if workspace_path:
                existing_workspace = payload.get("workspace_path")
                if (
                    not isinstance(existing_workspace, str)
                    or not existing_workspace.strip()
                ):
                    payload["workspace_path"] = workspace_path
                existing_note = payload.get("workspace_note")
                if not isinstance(existing_note, str) or not existing_note.strip():
                    payload["workspace_note"] = (
                        "workspace_path is a git checkout of github_repo."
                    )
            return json.dumps(payload, indent=2, sort_keys=True)
    return _format_repo_prompt(prompt, repo, workspace_path)


def _format_skill_fallback_prompt(
    prompt: str,
    skill_entries: list[dict[str, str]],
) -> str:
    if not skill_entries:
        return prompt
    if "Available skills (fallback context):" in prompt:
        return prompt
    lines = ["Available skills (fallback context):"]
    for entry in skill_entries:
        label = entry.get("display_name") or entry.get("name") or "skill"
        version = entry.get("version") or "unknown"
        description = entry.get("description") or ""
        lines.append(f"- {label} @ {version}")
        if description:
            lines.append(f"  Description: {description}")
        content = (entry.get("content") or "").strip()
        if content:
            lines.append("  SKILL.md excerpt:")
            for content_line in content.splitlines():
                lines.append(f"  {content_line}")
    block = "\n".join(lines)
    if not prompt.strip():
        return block
    return f"{block}\n\n{prompt}"


def _inject_skill_fallback(
    prompt: str,
    skill_entries: list[dict[str, str]],
    task_kind: str | None,
) -> str:
    if not skill_entries:
        return prompt
    payload = _load_prompt_dict(prompt)
    if payload is not None and is_prompt_envelope(payload):
        task_context = _ensure_task_context(payload)
        task_context["kind"] = task_kind or task_context.get("kind") or "task"
        task_context["skills"] = skill_entries
        return serialize_prompt_envelope(payload)
    stripped = prompt.strip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            prompt_value = payload.get("prompt")
            if isinstance(prompt_value, str):
                payload["prompt"] = _format_skill_fallback_prompt(
                    prompt_value,
                    skill_entries,
                )
                return json.dumps(payload, indent=2, sort_keys=True)
            payload["skills"] = skill_entries
            return json.dumps(payload, indent=2, sort_keys=True)
    return _format_skill_fallback_prompt(prompt, skill_entries)


def _build_integrations_payload(
    workspace: Path | str | None = None,
    selected_keys: set[str] | None = None,
) -> dict[str, object] | None:
    integrations: dict[str, object] = {}
    if is_task_integration_selected("github", selected_keys):
        github_settings = load_integration_settings("github")
        repo = (github_settings.get("repo") or "").strip()
        github_payload: dict[str, object] = {"configured": bool(repo)}
        if repo:
            github_payload["repo"] = repo
        if workspace:
            github_payload["workspace"] = str(workspace)
        if workspace:
            github_payload["note"] = (
                "Workspace is a local git clone of the GitHub repo. "
                "All instructions in the prompt relate to the repo and its local "
                "workspace. Do not use any other repo or local workspace."
            )
        else:
            github_payload["note"] = (
                "All instructions in the prompt relate to the GitHub repo and its local workspace."
                "Do not use any other repo or local workspace."
            )
        integrations["github"] = github_payload

    if is_task_integration_selected("jira", selected_keys):
        jira_settings = load_integration_settings("jira")
        email = (jira_settings.get("email") or "").strip()
        site = (jira_settings.get("site") or "").strip()
        board = (jira_settings.get("board") or "").strip()
        project_key = (jira_settings.get("project_key") or "").strip()
        jira_payload: dict[str, object] = {
            "configured": bool(email or site or board or project_key)
        }
        if email:
            jira_payload["email"] = email
        if site:
            jira_payload["site"] = site
        if board:
            jira_payload["board"] = board
        if project_key:
            jira_payload["project_key"] = project_key
        jira_payload["note"] = (
            "All instructions in the prompt relate to the Jira project board."
            "Do not use or work on any issues outside of the board."
            "If a DNS lookup fails, retry until it succeeds."
        )
        integrations["jira"] = jira_payload

    if is_task_integration_selected("confluence", selected_keys):
        confluence_settings = load_integration_settings("confluence")
        site = (confluence_settings.get("site") or "").strip()
        space = (confluence_settings.get("space") or "").strip()
        confluence_payload: dict[str, object] = {"configured": bool(site or space)}
        if site:
            confluence_payload["site"] = site
        if space:
            confluence_payload["space"] = space
        confluence_payload["note"] = (
            "Use configured Confluence settings for workspace documentation context."
        )
        integrations["confluence"] = confluence_payload

    if is_task_integration_selected("google_cloud", selected_keys):
        google_cloud_settings = load_integration_settings("google_cloud")
        project_id = (google_cloud_settings.get("google_cloud_project_id") or "").strip()
        service_account_json = (google_cloud_settings.get("service_account_json") or "").strip()
        google_cloud_payload: dict[str, object] = {
            "configured": bool(project_id or service_account_json)
        }
        if project_id:
            google_cloud_payload["project_id"] = project_id
        google_cloud_payload["note"] = (
            "Use configured Google Cloud settings as the default project context."
        )
        integrations["google_cloud"] = google_cloud_payload

    if is_task_integration_selected("google_workspace", selected_keys):
        google_workspace_settings = load_integration_settings("google_workspace")
        delegated_user = (
            google_workspace_settings.get("workspace_delegated_user_email") or ""
        ).strip()
        service_account_json = (
            google_workspace_settings.get("service_account_json") or ""
        ).strip()
        google_workspace_payload: dict[str, object] = {
            "configured": bool(delegated_user or service_account_json)
        }
        if delegated_user:
            google_workspace_payload["delegated_user_email"] = delegated_user
        google_workspace_payload["note"] = (
            "Use configured Google Workspace settings for delegated-user context."
        )
        integrations["google_workspace"] = google_workspace_payload

    if is_task_integration_selected("chroma", selected_keys):
        chroma_settings = load_integration_settings("chroma")
        host = (chroma_settings.get("host") or "").strip() or (
            Config.CHROMA_HOST or ""
        ).strip()
        port = (chroma_settings.get("port") or "").strip() or str(
            Config.CHROMA_PORT or ""
        ).strip()
        ssl = (chroma_settings.get("ssl") or "").strip() or str(
            Config.CHROMA_SSL or ""
        ).strip()
        chroma_payload: dict[str, object] = {"configured": bool(host and port)}
        if host:
            chroma_payload["host"] = host
        if port:
            chroma_payload["port"] = port
        if ssl:
            chroma_payload["ssl"] = ssl.strip().lower() == "true"
        chroma_payload["note"] = (
            "Use configured ChromaDB connection settings for vector memory lookups."
        )
        integrations["chroma"] = chroma_payload

    return integrations or None


def _strip_integrations_block(prompt: str) -> str:
    lines = prompt.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == "Integrations:":
            start = index
            break
    if start is None:
        return prompt
    end = start + 1
    while end < len(lines) and lines[end].strip() != "":
        end += 1
    while end < len(lines) and lines[end].strip() == "":
        end += 1
    remaining = lines[:start] + lines[end:]
    return "\n".join(remaining).lstrip("\n")


def _format_integrations_prompt(
    prompt: str,
    integrations: dict[str, object],
) -> str:
    if not integrations:
        return prompt
    cleaned = _strip_integrations_block(prompt)
    lines = ["Integrations:"]
    for key in sorted(integrations):
        value = integrations[key]
        if isinstance(value, dict):
            parts = []
            for entry_key in sorted(value):
                entry_value = value[entry_key]
                if entry_value is None or entry_value == "":
                    continue
                parts.append(f"{entry_key}={entry_value}")
            if parts:
                lines.append(f"- {key}: " + ", ".join(parts))
            else:
                lines.append(f"- {key}")
        else:
            lines.append(f"- {key}: {value}")
    block = "\n".join(lines)
    if not cleaned.strip():
        return block
    return f"{block}\n\n{cleaned}"


def _inject_integrations(
    prompt: str,
    integrations: dict[str, object] | None,
) -> str:
    payload = _load_prompt_dict(prompt)
    if payload is not None and is_prompt_envelope(payload):
        task_context = _ensure_task_context(payload)
        if integrations:
            task_context["integrations"] = integrations
        else:
            task_context.pop("integrations", None)
        return serialize_prompt_envelope(payload)
    if payload is None:
        if not integrations:
            return prompt
        return _format_integrations_prompt(prompt, integrations)
    if integrations:
        payload["integrations"] = integrations
    else:
        payload.pop("integrations", None)
    return json.dumps(payload, indent=2, sort_keys=True)


def _build_task_payload(kind: str | None, prompt: str) -> str:
    user_request, source_payload = parse_prompt_input(prompt)
    envelope = build_prompt_envelope(
        user_request=user_request,
        task_context={"kind": kind or "task"},
        output_contract=_build_output_contract(),
        source_payload=source_payload,
    )
    return serialize_prompt_envelope(envelope)


def _inject_envelope_core_sections(
    prompt: str,
    *,
    system_contract: dict[str, object] | None = None,
    agent_profile: dict[str, object] | None = None,
    task_kind: str | None = None,
) -> str:
    payload = _load_prompt_dict(prompt)
    if payload is None or not is_prompt_envelope(payload):
        return prompt
    if system_contract:
        existing = payload.get("system_contract")
        if isinstance(existing, dict):
            existing.update(system_contract)
        else:
            payload["system_contract"] = system_contract
    if agent_profile:
        payload["agent_profile"] = agent_profile
    task_context = _ensure_task_context(payload)
    if task_kind:
        task_context["kind"] = task_kind
    return serialize_prompt_envelope(payload)


def _build_task_mcp_configs(
    task: AgentTask,
) -> dict[str, dict[str, Any]]:
    return _build_mcp_config_map(list(task.mcp_servers))


def _first_available_model_id(session) -> int | None:
    return session.execute(
        select(LLMModel.id).order_by(LLMModel.created_at.desc()).limit(1)
    ).scalar_one_or_none()


def _run_llm_process(
    cmd: list[str],
    prompt: str | None,
    on_update: Callable[[str, str], None] | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        errors="replace",
        cwd=str(cwd) if cwd is not None else None,
        env=env,
    )
    if process.stdin:
        if prompt:
            process.stdin.write(prompt)
        process.stdin.close()

    selector = selectors.DefaultSelector()
    if process.stdout:
        selector.register(process.stdout, selectors.EVENT_READ, data="stdout")
    if process.stderr:
        selector.register(process.stderr, selectors.EVENT_READ, data="stderr")

    output_chunks: list[str] = []
    error_chunks: list[str] = []
    output_len = 0
    error_len = 0
    last_emit_output_len = 0
    last_emit_error_len = 0
    last_emit = time.monotonic()
    emit_interval = 2.0

    def emit_update(force: bool = False) -> None:
        nonlocal last_emit, last_emit_output_len, last_emit_error_len
        if on_update is None:
            return
        has_new_output = output_len != last_emit_output_len
        has_new_error = error_len != last_emit_error_len
        if force or (
            time.monotonic() - last_emit >= emit_interval and (has_new_output or has_new_error)
        ):
            on_update("".join(output_chunks), "".join(error_chunks))
            last_emit = time.monotonic()
            last_emit_output_len = output_len
            last_emit_error_len = error_len

    while selector.get_map():
        for key, _ in selector.select(timeout=0.5):
            chunk = key.fileobj.read(4096)
            if chunk == "":
                selector.unregister(key.fileobj)
                key.fileobj.close()
                continue
            if key.data == "stdout":
                output_chunks.append(chunk)
                output_len += len(chunk)
            else:
                error_chunks.append(chunk)
                error_len += len(chunk)
        emit_update()

    returncode = process.wait()
    stdout = "".join(output_chunks)
    stderr = "".join(error_chunks)
    emit_update(force=True)
    return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)


def _is_upstream_500(stdout: str, stderr: str) -> bool:
    haystack = f"{stdout}\n{stderr}".lower()
    markers = (
        "status: internal",
        "\"status\":\"internal\"",
        "internal error encountered",
        "status: 500",
        "code\":500",
        "error code: 500",
        "http 500",
        "internal server error",
    )
    return any(marker in haystack for marker in markers)


def _run_llm(
    provider: str,
    prompt: str | None,
    mcp_configs: dict[str, dict[str, Any]],
    model_config: dict[str, Any] | None = None,
    on_update: Callable[[str, str], None] | None = None,
    on_log: Callable[[str], None] | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    if model_config is None and provider == "codex":
        model_config = _load_legacy_codex_model_config()
    provider_label = _provider_label(provider)
    cmd: list[str] | None = None
    if provider == "codex":
        env = dict(env or os.environ.copy())
        codex_api_key = _load_codex_auth_key()
        if codex_api_key:
            env["OPENAI_API_KEY"] = codex_api_key
            env["CODEX_API_KEY"] = codex_api_key
        codex_settings = _codex_settings_from_model_config(model_config or {})
        mcp_overrides = _build_mcp_overrides_from_configs(mcp_configs)
        codex_overrides = _build_codex_overrides(codex_settings)
        cmd = _build_codex_cmd(
            mcp_overrides=mcp_overrides,
            codex_overrides=codex_overrides,
            model=codex_settings.get("model"),
        )
    elif provider == "gemini":
        env = dict(env or os.environ.copy())
        gemini_api_key = _load_gemini_auth_key()
        if gemini_api_key:
            env["GEMINI_API_KEY"] = gemini_api_key
            env["GOOGLE_API_KEY"] = gemini_api_key
        gemini_settings = _gemini_settings_from_model_config(model_config or {})
        _ensure_gemini_mcp_servers(mcp_configs, on_log=on_log, cwd=cwd, env=env)
        if gemini_settings.get("sandbox") is not None:
            sandbox_enabled = bool(gemini_settings.get("sandbox"))
            sandbox_value = str(env.get("GEMINI_SANDBOX", "")).strip()
            if sandbox_enabled:
                if sandbox_value and sandbox_value.lower() not in {"true", "false"}:
                    pass
                elif _gemini_sandbox_available():
                    env["GEMINI_SANDBOX"] = "true"
                else:
                    if on_log:
                        on_log(
                            "Gemini sandbox requested but docker/podman not found; "
                            "running without sandbox."
                        )
                    env["GEMINI_SANDBOX"] = "false"
            else:
                env["GEMINI_SANDBOX"] = "false"
        cmd = _build_gemini_cmd(
            sorted(mcp_configs),
            model=gemini_settings.get("model"),
            approval_mode=gemini_settings.get("approval_mode"),
            extra_args=gemini_settings.get("extra_args"),
        )
    elif provider == "claude":
        env = dict(env or os.environ.copy())
        claude_api_key, auth_source = _resolve_claude_auth_key(env)
        if claude_api_key:
            env["ANTHROPIC_API_KEY"] = claude_api_key
        elif Config.CLAUDE_AUTH_REQUIRE_API_KEY:
            raise RuntimeError(
                "Claude runtime requires ANTHROPIC_API_KEY. "
                "Set it in Settings -> Provider -> Claude or via environment."
            )
        elif on_log:
            on_log(
                "Claude auth key not set. Continuing because "
                "CLAUDE_AUTH_REQUIRE_API_KEY=false."
            )
        if claude_api_key and on_log:
            on_log(f"Claude auth source: {auth_source}.")
        _ensure_claude_cli_ready(on_log=on_log, env=env)
        mcp_config = _build_claude_mcp_config(mcp_configs)
        model_name = str((model_config or {}).get("model") or "").strip()
        cmd = _build_claude_cmd(mcp_config, model=model_name)
    elif provider == "vllm_local":
        local_settings = _vllm_local_settings_from_model_config(model_config or {})
        if mcp_configs and on_log:
            on_log(
                "vLLM providers currently run without MCP transport wiring; "
                "MCP servers are ignored for this run."
            )
        logger.info(
            "Running %s: CLI run-batch model=%s",
            provider_label,
            local_settings.get("model"),
        )
        return _run_vllm_local_cli_completion(
            local_settings,
            prompt,
            on_update=on_update,
            on_log=on_log,
            cwd=cwd,
            env=env,
        )
    elif provider == "vllm_remote":
        remote_settings = _vllm_remote_settings_from_model_config(model_config or {})
        if mcp_configs and on_log:
            on_log(
                "vLLM providers currently run without MCP transport wiring; "
                "MCP servers are ignored for this run."
            )
        logger.info(
            "Running %s: POST %s/chat/completions model=%s",
            provider_label,
            remote_settings.get("base_url"),
            remote_settings.get("model"),
        )
        result = _run_vllm_remote_chat_completion(
            provider,
            remote_settings,
            prompt,
            on_update=on_update,
        )
        if result.returncode != 0 and (
            result.returncode >= 500
            or _is_upstream_500(result.stdout, result.stderr)
        ):
            if on_log:
                on_log(f"{provider_label} returned upstream 500; retrying once.")
            time.sleep(1.0)
            result = _run_vllm_remote_chat_completion(
                provider,
                remote_settings,
                prompt,
                on_update=on_update,
            )
        return result
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
    logger.info("Running %s: %s", provider_label, " ".join(cmd))
    result = _run_llm_process(cmd, prompt, on_update=on_update, cwd=cwd, env=env)
    if result.returncode != 0 and _is_upstream_500(result.stdout, result.stderr):
        if on_log:
            on_log(f"{provider_label} returned upstream 500; retrying once.")
        time.sleep(1.0)
        result = _run_llm_process(cmd, prompt, on_update=on_update, cwd=cwd, env=env)
    return result


def _update_task_logs(
    task_id: int,
    output: str,
    error: str,
    stage: str | None = None,
    stage_logs: str | None = None,
) -> None:
    with session_scope() as session:
        task = session.get(AgentTask, task_id)
        if task is None:
            return
        previous_stage = task.current_stage
        task.output = output
        task.error = error
        if stage is not None:
            task.current_stage = stage
        if stage_logs is not None:
            task.stage_logs = stage_logs
        if stage is not None and stage != previous_stage:
            _emit_task_event(
                "node.task.stage.updated",
                task=task,
                payload={
                    "current_stage": task.current_stage,
                },
            )


@celery_app.task(bind=True)
def run_agent(self, run_id: int) -> None:
    init_engine(Config.SQLALCHEMY_DATABASE_URI)
    init_db()

    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            logger.warning("Autorun %s not found", run_id)
            return
        agent = session.get(Agent, run.agent_id)
        if agent is None:
            now = _utcnow()
            run.status = "error"
            run.last_error = "Agent not found."
            run.task_id = None
            run.last_stopped_at = now
            run.run_end_requested = False
            logger.warning(
                "Agent %s not found for run %s", run.agent_id, run_id
            )
            return
        if run.status not in RUN_ACTIVE_STATUSES:
            logger.info("Autorun %s is not active before start; skipping", run_id)
            return
        end_requested = run.run_end_requested or run.status == "stopping"
        run.status = "stopping" if end_requested else "running"
        run.task_id = self.request.id
        run.last_started_at = _utcnow()
        run.run_end_requested = end_requested
        agent.task_id = self.request.id
        agent.last_started_at = run.last_started_at
        agent.run_end_requested = end_requested
        session.flush()

    poll_seconds = Config.AGENT_POLL_SECONDS

    while True:
        with session_scope() as session:
            run = session.get(Run, run_id)
            if run is None:
                logger.warning("Autorun %s disappeared", run_id)
                return
            agent = session.get(Agent, run.agent_id)
            if agent is None:
                now = _utcnow()
                run.status = "error"
                run.last_error = "Agent not found."
                run.task_id = None
                run.last_stopped_at = now
                run.run_end_requested = False
                logger.warning(
                    "Agent %s disappeared for run %s", run.agent_id, run_id
                )
                return
            if run.status not in RUN_ACTIVE_STATUSES:
                if run.status != "error":
                    run.status = "stopped"
                run.task_id = None
                run.last_stopped_at = _utcnow()
                run.last_run_task_id = self.request.id
                run.run_end_requested = False
                agent.task_id = None
                agent.last_stopped_at = run.last_stopped_at
                agent.last_run_task_id = self.request.id
                agent.run_end_requested = False
                return
            pending = session.execute(
                select(AgentTask.id).where(
                    AgentTask.agent_id == agent.id,
                    AgentTask.status.in_(["queued", "running"]),
                )
            ).first()
            run_max_loops = run.run_max_loops or 0
            if run_max_loops > 0:
                completed_loops = session.execute(
                    select(func.count(AgentTask.id)).where(
                        AgentTask.run_task_id == self.request.id
                    )
                ).scalar_one()
                if completed_loops >= run_max_loops:
                    run.run_end_requested = True
                    if run.status in {"running", "starting"}:
                        run.status = "stopping"
                    agent.run_end_requested = True
            if run.run_end_requested:
                if pending is None:
                    if run.status != "error":
                        run.status = "stopped"
                    run.task_id = None
                    run.last_stopped_at = _utcnow()
                    run.last_run_task_id = self.request.id
                    run.run_end_requested = False
                    agent.task_id = None
                    agent.last_stopped_at = run.last_stopped_at
                    agent.last_run_task_id = self.request.id
                    agent.run_end_requested = False
                    return
                task_id = None
            elif pending is not None:
                task_id = None
            else:
                task = AgentTask.create(
                    session,
                    agent_id=agent.id,
                    run_id=run_id,
                    run_task_id=self.request.id,
                    status="queued",
                    prompt=_build_run_prompt_payload(agent),
                )
                task_id = task.id

        if task_id is None:
            time.sleep(poll_seconds)
            continue

        result = run_agent_task.delay(task_id)

        with session_scope() as session:
            task = session.get(AgentTask, task_id)
            if task is not None:
                task.celery_task_id = result.id

        time.sleep(poll_seconds)


@celery_app.task(bind=True)
def run_quick_rag_task(self, task_id: int) -> None:
    init_engine(Config.SQLALCHEMY_DATABASE_URI)
    init_db()

    quick_context: dict[str, Any] = {}
    with session_scope() as session:
        task = session.get(AgentTask, task_id)
        if task is None:
            logger.warning("Quick RAG task %s not found", task_id)
            return
        if task.kind not in QUICK_RAG_TASK_KINDS:
            logger.warning("Task %s is not a Quick RAG task (kind=%s)", task_id, task.kind)
            return
        if task.status not in {"queued", "running"}:
            return
        task.celery_task_id = self.request.id or task.celery_task_id
        task.status = "running"
        task.started_at = task.started_at or _utcnow()
        quick_context = _quick_rag_context_from_prompt(task.prompt)
        _emit_task_event(
            "node.task.updated",
            task=task,
            payload={"transition": "started"},
        )

    mode = _normalize_quick_rag_mode(quick_context.get("mode"))
    collection = str(quick_context.get("collection") or "").strip()
    source_name = str(quick_context.get("source_name") or "").strip()
    model_provider = _normalize_quick_rag_model_provider(
        quick_context.get("model_provider")
    )
    task_error: str | None = None
    output_payload: dict[str, Any] | None = None
    runtime_payload: dict[str, Any] | None = None
    runtime_evidence: dict[str, Any] = {}
    if mode is None:
        task_error = "Quick RAG mode is required."
    elif not collection:
        task_error = "Quick RAG collection is required."
    else:
        try:
            execution_router = ExecutionRouter(
                runtime_settings=load_node_executor_runtime_settings()
            )
            source_id = _parse_optional_int(
                quick_context.get("source_id"),
                default=task_id,
                minimum=1,
            )
            execution_request = ExecutionRequest(
                node_id=int(source_id),
                node_type=FLOWCHART_NODE_TYPE_RAG,
                node_ref_id=None,
                node_config={
                    "mode": mode,
                    "collections": [collection],
                    "model_provider": model_provider,
                },
                input_context={
                    "kind": "rag_quick_run",
                    "task_id": int(task_id),
                    "rag_quick_run": {
                        "source_id": int(source_id),
                        "source_name": source_name,
                        "collection": collection,
                        "mode": mode,
                        "model_provider": model_provider,
                    },
                },
                execution_id=int(task_id),
                execution_task_id=int(task_id),
                execution_index=1,
                enabled_providers={model_provider},
                default_model_id=None,
                mcp_server_keys=[],
            )
            routed_execution_request = execution_router.route_request(execution_request)
            runtime_payload = routed_execution_request.run_metadata_payload()
            with session_scope() as session:
                task = session.get(AgentTask, task_id)
                if task is not None:
                    _apply_flowchart_node_task_run_metadata(task, runtime_payload)
                    _emit_task_event(
                        "node.task.updated",
                        task=task,
                        payload={"transition": "routed"},
                        runtime_override=runtime_payload,
                    )
            execution_result = execution_router.execute_routed(
                routed_execution_request,
                _quick_rag_worker_compute_disabled,
            )
            runtime_payload = (
                execution_result.run_metadata
                if isinstance(execution_result.run_metadata, dict)
                else runtime_payload
            )
            runtime_evidence = _runtime_evidence_payload(
                run_metadata=runtime_payload,
                provider_metadata=(
                    execution_result.provider_metadata
                    if isinstance(execution_result.provider_metadata, dict)
                    else None
                ),
                error=execution_result.error if isinstance(execution_result.error, dict) else None,
                terminal_status=execution_result.status,
            )
            if execution_result.status != "success":
                failure_error = execution_result.error
                failure_message = (
                    str(failure_error.get("message") or "").strip()
                    if isinstance(failure_error, dict)
                    else ""
                )
                task_error = (
                    failure_message
                    or f"Quick RAG execution failed with status '{execution_result.status}'."
                )
            else:
                output_payload = (
                    dict(execution_result.output_state)
                    if isinstance(execution_result.output_state, dict)
                    else {}
                )
                quick_payload = output_payload.get("quick_rag")
                if not isinstance(quick_payload, dict):
                    quick_payload = {}
                quick_payload.update(
                    {
                        "source_name": source_name,
                        "collection": collection,
                        "model_provider": model_provider,
                        "mode": mode,
                    }
                )
                output_payload["quick_rag"] = quick_payload
                output_payload["runtime_evidence"] = runtime_evidence
        except Exception as exc:
            task_error = str(exc) or "Quick RAG run failed."
            runtime_evidence = _runtime_evidence_payload(
                run_metadata=runtime_payload,
                provider_metadata=None,
                error={"message": task_error},
                terminal_status="failed",
            )

    now = _utcnow()
    with session_scope() as session:
        task = session.get(AgentTask, task_id)
        if task is None:
            return
        if isinstance(runtime_payload, dict):
            _apply_flowchart_node_task_run_metadata(task, runtime_payload)
        task.finished_at = now
        if task_error:
            task.status = "failed"
            task.error = task_error
            task.output = _json_dumps(
                {
                    "quick_rag": {
                        "source_name": source_name,
                        "collection": collection,
                        "model_provider": model_provider,
                        "mode": mode,
                    },
                    "runtime_evidence": runtime_evidence,
                }
            )
            _emit_task_event(
                "node.task.completed",
                task=task,
                payload={
                    "terminal_status": "failed",
                    "failure_message": task_error,
                    "runtime_evidence": runtime_evidence,
                },
                runtime_override=runtime_payload,
            )
            return
        task.status = "succeeded"
        task.error = None
        task.output = _json_dumps(output_payload or {})
        _emit_task_event(
            "node.task.completed",
            task=task,
            payload={
                "terminal_status": "succeeded",
                "runtime_evidence": runtime_evidence,
            },
            runtime_override=runtime_payload,
        )


@celery_app.task(bind=True)
def run_agent_task(self, task_id: int) -> None:
    if _execute_quick_task_via_execution_router(task_id, celery_task_id=self.request.id):
        return
    _execute_agent_task(task_id, celery_task_id=self.request.id)


def _execute_quick_task_via_execution_router(
    task_id: int,
    *,
    celery_task_id: str | None = None,
) -> bool:
    init_engine(Config.SQLALCHEMY_DATABASE_URI)
    init_db()

    llm_settings = load_integration_settings("llm")
    enabled_providers = resolve_enabled_llm_providers(llm_settings)
    default_model_id = resolve_default_model_id(llm_settings)

    routed_execution_request: ExecutionRequest | None = None
    execution_router: ExecutionRouter | None = None
    runtime_payload: dict[str, Any] | None = None
    runtime_evidence: dict[str, Any] = {}

    with session_scope() as session:
        task = session.get(AgentTask, task_id)
        if task is None:
            logger.warning("Task %s not found", task_id)
            return True
        if not is_quick_task_kind(task.kind):
            return False
        if task.status not in {"queued", "running"}:
            return True

        task.celery_task_id = celery_task_id or task.celery_task_id
        task.status = "running"
        task.started_at = task.started_at or _utcnow()
        _emit_task_event(
            "node.task.updated",
            task=task,
            payload={"transition": "started"},
        )

        execution_router = ExecutionRouter(
            runtime_settings=load_node_executor_runtime_settings()
        )
        selected_mcp_server_keys = [
            str(server.server_key)
            for server in list(task.mcp_servers)
            if str(server.server_key or "").strip()
        ]
        execution_request = ExecutionRequest(
            node_id=int(task.id),
            node_type=EXECUTOR_NODE_TYPE_AGENT_TASK,
            node_ref_id=None,
            node_config={
                "agent_task_id": int(task.id),
                "task_kind": str(task.kind or ""),
            },
            input_context={
                "kind": "agent_task",
                "task_id": int(task.id),
                "task_kind": str(task.kind or ""),
            },
            execution_id=int(task.id),
            execution_task_id=int(task.id),
            execution_index=1,
            enabled_providers=set(enabled_providers),
            default_model_id=default_model_id,
            mcp_server_keys=selected_mcp_server_keys,
        )
        routed_execution_request = execution_router.route_request(execution_request)
        runtime_payload = routed_execution_request.run_metadata_payload()
        _apply_flowchart_node_task_run_metadata(task, runtime_payload)
        _emit_task_event(
            "node.task.updated",
            task=task,
            payload={"transition": "routed"},
            runtime_override=runtime_payload,
        )

    if execution_router is None or routed_execution_request is None:
        return True

    task_error: str | None = None
    terminal_status = "failed"
    provider_metadata: dict[str, Any] | None = None
    error_payload: dict[str, Any] | None = None
    try:
        execution_result = execution_router.execute_routed(
            routed_execution_request,
            _agent_task_worker_compute_disabled,
        )
        runtime_payload = (
            execution_result.run_metadata
            if isinstance(execution_result.run_metadata, dict)
            else runtime_payload
        )
        provider_metadata = (
            execution_result.provider_metadata
            if isinstance(execution_result.provider_metadata, dict)
            else None
        )
        error_payload = execution_result.error if isinstance(execution_result.error, dict) else None
        terminal_status = str(execution_result.status or "").strip().lower() or "failed"
        if execution_result.status != "success":
            task_error = (
                str(error_payload.get("message") or "").strip()
                if isinstance(error_payload, dict)
                else ""
            )
            if not task_error:
                task_error = (
                    "Quick task execution failed with status "
                    f"'{execution_result.status}'."
                )
    except Exception as exc:
        task_error = str(exc) or "Quick task dispatch failed."
        terminal_status = "failed"
        provider_metadata = None
        error_payload = {"message": task_error}

    runtime_evidence = _runtime_evidence_payload(
        run_metadata=runtime_payload,
        provider_metadata=provider_metadata,
        error=error_payload,
        terminal_status=terminal_status,
    )

    with session_scope() as session:
        task = session.get(AgentTask, task_id)
        if task is None:
            return True
        if isinstance(runtime_payload, dict):
            _apply_flowchart_node_task_run_metadata(task, runtime_payload)
        if not task_error:
            return True
        task_was_active = task.status in {"queued", "running"}
        if task_was_active:
            now = _utcnow()
            task.status = "failed"
            task.finished_at = now
            task.error = task_error
            _emit_task_event(
                "node.task.completed",
                task=task,
                payload={
                    "terminal_status": "failed",
                    "failure_message": task_error,
                    "runtime_evidence": runtime_evidence,
                },
                runtime_override=runtime_payload,
            )
    return True


def _execute_agent_task(task_id: int, celery_task_id: str | None = None) -> None:
    init_engine(Config.SQLALCHEMY_DATABASE_URI)
    init_db()

    llm_settings = load_integration_settings("llm")
    enabled_providers = resolve_enabled_llm_providers(llm_settings)
    provider = resolve_llm_provider(
        settings=llm_settings, enabled_providers=enabled_providers
    )
    default_model_id = resolve_default_model_id(llm_settings)
    model_config: dict[str, Any] | None = None
    mcp_configs: dict[str, dict[str, Any]] = {}
    agent_id: int | None = None
    run_id: int | None = None
    payload = ""
    task_kind: str | None = None
    github_repo = ""
    selected_integration_keys: set[str] | None = None
    task_scripts: list[Script] = []
    task_attachments: list[Attachment] = []
    compiled_instruction_package = None
    configured_agent_markdown_filename: str | None = None
    resolved_role_id: int | None = None
    resolved_role_version: str | None = None
    resolved_agent_id: int | None = None
    resolved_agent_version: str | None = None
    resolved_instruction_manifest_hash: str | None = None
    resolved_skills = None
    resolved_skill_ids: list[int] = []
    resolved_skill_versions: list[dict[str, Any]] = []
    resolved_skill_manifest_hash: str | None = None
    with session_scope() as session:
        task = session.get(AgentTask, task_id)
        if task is None:
            logger.warning("Task %s not found", task_id)
            return
        if task.status not in {"queued", "running"}:
            return
        run: Run | None = None
        if task.run_id is not None:
            run = session.get(Run, task.run_id)
            if run is None:
                now = _utcnow()
                task.status = "canceled"
                task.error = "Autorun not found."
                task.started_at = now
                task.finished_at = now
                return
            if run.status not in RUN_ACTIVE_STATUSES:
                now = _utcnow()
                task.status = "canceled"
                task.error = "Autorun is inactive."
                task.started_at = now
                task.finished_at = now
                return
            run_id = run.id
        is_run_task = task.run_id is not None
        agent: Agent | None = None
        if task.agent_id is None:
            if not is_quick_task_kind(task.kind):
                now = _utcnow()
                task.status = "failed"
                task.error = "Agent required."
                task.started_at = now
                task.finished_at = now
                return
        else:
            agent = session.get(Agent, task.agent_id)
            if agent is None and not is_quick_task_kind(task.kind):
                now = _utcnow()
                task.status = "failed"
                task.error = "Agent not found."
                task.started_at = now
                task.finished_at = now
                if run is not None:
                    run.last_run_at = now
                    run.last_error = "Agent not found."
                    run.status = "error"
                    run.task_id = None
                    run.last_stopped_at = now
                return
            if agent is None:
                logger.warning(
                    "Quick node %s references missing agent %s; using default quick profile.",
                    task.id,
                    task.agent_id,
                )
        model: LLMModel | None = None
        selected_model_id: int | None = None
        if task.model_id is not None:
            selected_model_id = task.model_id
        elif default_model_id is not None:
            selected_model_id = default_model_id
        elif is_quick_task_kind(task.kind):
            selected_model_id = _first_available_model_id(session)

        if selected_model_id is not None:
            model = session.get(LLMModel, selected_model_id)
            if model is None:
                now = _utcnow()
                task.status = "failed"
                task.error = "Model not found."
                task.started_at = now
                task.finished_at = now
                if agent is not None:
                    agent.last_run_at = now
                    agent.last_error = task.error
                    agent.task_id = None
                    agent.last_stopped_at = now
                if run is not None:
                    run.last_run_at = now
                    run.last_error = task.error
                    run.status = "error"
                    run.task_id = None
                    run.last_stopped_at = now
                return
        if model is None:
            now = _utcnow()
            task.status = "failed"
            task.error = "Model required."
            task.started_at = now
            task.finished_at = now
            if agent is not None:
                agent.last_run_at = now
                agent.last_error = task.error
                agent.task_id = None
                agent.last_stopped_at = now
            if run is not None:
                run.last_run_at = now
                run.last_error = task.error
                run.status = "error"
                run.task_id = None
                run.last_stopped_at = now
            return
        if model.provider not in LLM_PROVIDERS:
            now = _utcnow()
            task.status = "failed"
            task.error = f"Unknown model provider: {model.provider}."
            task.started_at = now
            task.finished_at = now
            if agent is not None:
                agent.last_run_at = now
                agent.last_error = task.error
                agent.task_id = None
                agent.last_stopped_at = now
            if run is not None:
                run.last_run_at = now
                run.last_error = task.error
                run.status = "error"
                run.task_id = None
                run.last_stopped_at = now
            return
        if model.provider not in enabled_providers:
            now = _utcnow()
            task.status = "failed"
            task.error = f"Provider disabled: {model.provider}."
            task.started_at = now
            task.finished_at = now
            if agent is not None:
                agent.last_run_at = now
                agent.last_error = task.error
                agent.task_id = None
                agent.last_stopped_at = now
            if run is not None:
                run.last_run_at = now
                run.last_error = task.error
                run.status = "error"
                run.task_id = None
                run.last_stopped_at = now
            return
        provider = model.provider
        model_config = _parse_model_config(model.config_json)
        configured_agent_markdown_filename = str(
            model_config.get("agent_markdown_filename") or ""
        ).strip() or None
        if provider is None:
            now = _utcnow()
            task.status = "failed"
            task.error = "No default provider or model configured."
            task.started_at = now
            task.finished_at = now
            if agent is not None:
                agent.last_run_at = now
                agent.last_error = task.error
                agent.task_id = None
                agent.last_stopped_at = now
            if run is not None:
                run.last_run_at = now
                run.last_error = task.error
                run.status = "error"
                run.task_id = None
                run.last_stopped_at = now
            return
        agent_id = agent.id if agent is not None else None
        task_scripts = list(task.scripts)
        task_attachments = list(task.attachments)
        ordered_scripts: list[Script] = []
        seen_script_ids: set[int] = set()
        for script in task_scripts:
            if script.id in seen_script_ids:
                continue
            seen_script_ids.add(script.id)
            path = ensure_script_file(
                script.id,
                script.file_name,
                script.content,
                script.file_path,
            )
            if script.file_path != str(path):
                script.file_path = str(path)
            ordered_scripts.append(script)
        task.celery_task_id = celery_task_id or task.celery_task_id
        task.status = "running"
        task.started_at = _utcnow()
        _emit_task_event(
            "node.task.updated",
            task=task,
            payload={
                "transition": "started",
            },
        )
        selected_integration_keys = parse_task_integration_keys(
            task.integration_keys_json
        )
        prompt = task.prompt
        task_kind = task.kind
        if agent is not None and not prompt and not is_quick_task_kind(task.kind):
            prompt = _render_prompt(agent)
        if prompt is None:
            prompt = ""
        runtime_payload = _build_runtime_payload(provider, model_config)
        if is_task_integration_selected("github", selected_integration_keys):
            github_settings = load_integration_settings("github")
            github_repo = (github_settings.get("repo") or "").strip()
        payload = _build_task_payload(task.kind, prompt)
        system_contract = _build_system_contract(agent)
        agent_profile = _build_agent_payload(agent) if agent is not None else None
        if agent is None and is_quick_task_kind(task_kind):
            system_contract = build_quick_node_system_contract()
            agent_profile = build_quick_node_agent_profile()
        payload = _inject_envelope_core_sections(
            payload,
            system_contract=system_contract,
            agent_profile=agent_profile,
            task_kind=task_kind,
        )
        if (
            is_task_integration_selected("github", selected_integration_keys)
            and github_repo
            and not is_run_task
        ):
            payload = _inject_github_repo(payload, github_repo, task_kind)
        payload = _inject_integrations(
            payload,
            _build_integrations_payload(selected_keys=selected_integration_keys),
        )
        payload = _inject_runtime_metadata(payload, runtime_payload)
        attachment_entries = _build_attachment_entries(task_attachments)
        payload = _inject_attachments(
            payload,
            attachment_entries,
            replace_existing=False,
        )
        if agent is not None:
            role_id = agent.role_id if agent.role_id is not None else None
            role_markdown = _build_role_markdown(agent.role)
            run_mode = "autorun" if is_run_task else "task"
            serialized_priorities = (
                _serialize_agent_priorities(agent) if is_run_task else tuple()
            )
            runtime_overrides: tuple[str, ...] = tuple()
            if task.prompt and task.prompt.strip():
                runtime_overrides = (task.prompt.strip(),)
            resolved_agent_id = agent.id
            resolved_role_id = role_id
            resolved_agent_version = _resolve_updated_at_version(agent.updated_at)
            resolved_role_version = _resolve_updated_at_version(
                agent.role.updated_at if agent.role is not None else None
            )
            compiled_instruction_package = compile_instruction_package(
                InstructionCompileInput(
                    run_mode=run_mode,
                    provider=provider,
                    role_markdown=role_markdown,
                    agent_markdown=_build_agent_markdown(agent),
                    priorities=serialized_priorities,
                    runtime_overrides=runtime_overrides,
                    source_ids={
                        "agent_id": agent.id,
                        "role_id": role_id,
                    },
                    source_versions={
                        "agent_version": resolved_agent_version,
                        "role_version": resolved_role_version,
                    },
                )
            )
            resolved_instruction_manifest_hash = compiled_instruction_package.manifest_hash
            try:
                resolved_skills = resolve_agent_skills(session, agent.id)
            except ValueError as exc:
                now = _utcnow()
                task.status = "failed"
                task.error = f"Skill resolution failed for agent {agent.id}: {exc}"
                task.finished_at = now
                agent.last_run_at = now
                agent.last_error = task.error
                agent.task_id = None
                agent.last_stopped_at = now
                if run is not None:
                    run.last_run_at = now
                    run.last_error = task.error
                    run.status = "error"
                    run.task_id = None
                    run.last_stopped_at = now
                    run.run_end_requested = False
                return
            resolved_skill_ids = skill_ids_payload(resolved_skills)
            resolved_skill_versions = skill_versions_payload(resolved_skills)
            resolved_skill_manifest_hash = resolved_skills.manifest_hash
        task.resolved_role_id = resolved_role_id
        task.resolved_role_version = resolved_role_version
        task.resolved_agent_id = resolved_agent_id
        task.resolved_agent_version = resolved_agent_version
        task.resolved_skill_ids_json = _json_dumps(resolved_skill_ids)
        task.resolved_skill_versions_json = _json_dumps(resolved_skill_versions)
        task.resolved_skill_manifest_hash = resolved_skill_manifest_hash
        task.skill_adapter_mode = None
        task.resolved_instruction_manifest_hash = resolved_instruction_manifest_hash
        task.instruction_adapter_mode = None
        task.instruction_materialized_paths_json = None
        task.prompt = payload
        try:
            mcp_configs = _build_task_mcp_configs(task)
        except ValueError as exc:
            now = _utcnow()
            task.status = "failed"
            task.error = str(exc)
            task.finished_at = now
            if agent is not None:
                agent.last_run_at = now
                agent.last_error = str(exc)
                agent.task_id = None
                agent.last_stopped_at = now
            if run is not None:
                run.last_run_at = now
                run.last_error = str(exc)
                run.status = "error"
                run.task_id = None
                run.last_stopped_at = now
                run.run_end_requested = False
            logger.error("Invalid MCP config for task %s: %s", task.id, exc)
            return

    provider_label = _provider_label(provider)

    def _split_scripts(
        scripts: list[Script],
    ) -> tuple[
        list[Script],
        list[Script],
        list[Script],
        list[Script],
        list[Script],
    ]:
        pre_init: list[Script] = []
        init: list[Script] = []
        post_init: list[Script] = []
        post_run: list[Script] = []
        unknown: list[Script] = []
        for script in scripts:
            if script.script_type == SCRIPT_TYPE_PRE_INIT:
                pre_init.append(script)
            elif script.script_type == SCRIPT_TYPE_INIT:
                init.append(script)
            elif script.script_type == SCRIPT_TYPE_POST_INIT:
                post_init.append(script)
            elif script.script_type == SCRIPT_TYPE_POST_RUN:
                post_run.append(script)
            else:
                unknown.append(script)
        return pre_init, init, post_init, post_run, unknown

    (
        pre_init_scripts,
        init_scripts,
        post_init_scripts,
        post_run_scripts,
        unknown_scripts,
    ) = _split_scripts(ordered_scripts)
    combined_scripts = pre_init_scripts + init_scripts + post_init_scripts + post_run_scripts

    log_prefix_chunks: list[str] = []
    last_output = ""
    last_error = ""
    last_llm_error = ""
    stage_log_chunks: dict[str, list[str]] = {}
    current_stage: str | None = None
    stage_index = {
        stage_key: index + 1 for index, (stage_key, _) in enumerate(TASK_STAGE_ORDER)
    }
    total_stages = len(TASK_STAGE_ORDER)

    def _persist_logs(output: str, error: str) -> None:
        nonlocal last_output, last_error, last_llm_error
        last_output = output
        last_error = error
        if current_stage:
            if error.startswith(last_llm_error):
                delta = error[len(last_llm_error):]
            else:
                delta = error
            if delta:
                stage_log_chunks.setdefault(current_stage, []).append(delta)
                last_llm_error = error
        _update_task_logs(
            task_id,
            output,
            "".join(log_prefix_chunks) + error,
            stage=current_stage,
            stage_logs=_serialize_stage_logs(),
        )

    def _append_task_log(message: str) -> None:
        nonlocal log_prefix_chunks
        line = message.rstrip("\n") + "\n"
        log_prefix_chunks.append(line)
        if current_stage:
            stage_log_chunks.setdefault(current_stage, []).append(line)
        _update_task_logs(
            task_id,
            last_output,
            "".join(log_prefix_chunks) + last_error,
            stage=current_stage,
            stage_logs=_serialize_stage_logs(),
        )

    def _serialize_stage_logs() -> str:
        return json.dumps(
            {
                stage_key: "".join(chunks)
                for stage_key, chunks in stage_log_chunks.items()
                if chunks
            },
            sort_keys=True,
        )

    def _set_stage(stage_key: str) -> None:
        nonlocal current_stage, last_llm_error
        current_stage = stage_key
        last_llm_error = ""
        stage_log_chunks.setdefault(stage_key, [])
        label = TASK_STAGE_LABELS.get(stage_key, stage_key)
        index = stage_index.get(stage_key, 0)
        _append_task_log(f"Stage {index}/{total_stages}: {label}")

    workspace: Path | None = None
    staging_dir: Path | None = None
    runtime_home: Path | None = None
    codex_home: Path | None = None
    script_entries: list[dict[str, str]] = []
    instruction_manifest_hash = resolved_instruction_manifest_hash or ""
    instruction_materialized_paths: list[str] = []
    instructions_materialized = False
    instruction_adapter_mode: str | None = None
    instruction_adapter_name: str | None = None
    skill_adapter_mode: str | None = None
    skill_adapter_name: str | None = None
    skill_materialized_paths: list[str] = []
    llm_failed = False
    llm_message = ""
    post_run_failed = False
    post_run_message = ""
    workspace_ready_logged = False

    def _finalize_failure(message: str) -> None:
        now = _utcnow()
        with session_scope() as session:
            task = session.get(AgentTask, task_id)
            agent = session.get(Agent, agent_id) if agent_id is not None else None
            run = session.get(Run, run_id) if run_id is not None else None
            if task is not None:
                task.status = "failed"
                task.error = "".join(log_prefix_chunks) + last_error
                task.current_stage = current_stage
                task.stage_logs = _serialize_stage_logs()
                task.resolved_role_id = resolved_role_id
                task.resolved_role_version = resolved_role_version
                task.resolved_agent_id = resolved_agent_id
                task.resolved_agent_version = resolved_agent_version
                task.resolved_skill_ids_json = _json_dumps(resolved_skill_ids)
                task.resolved_skill_versions_json = _json_dumps(
                    resolved_skill_versions
                )
                task.resolved_skill_manifest_hash = resolved_skill_manifest_hash
                task.skill_adapter_mode = skill_adapter_mode
                task.resolved_instruction_manifest_hash = (
                    instruction_manifest_hash or resolved_instruction_manifest_hash
                )
                task.instruction_adapter_mode = instruction_adapter_mode
                task.instruction_materialized_paths_json = _serialize_materialized_paths(
                    instruction_materialized_paths
                )
                task.finished_at = now
                _emit_task_event(
                    "node.task.completed",
                    task=task,
                    payload={
                        "terminal_status": "failed",
                        "failure_message": message,
                    },
                )
            if agent is not None:
                agent.last_run_at = now
                agent.last_error = message
                agent.task_id = None
                agent.last_stopped_at = now
            if run is not None:
                run.last_run_at = now
                run.last_error = message
                run.status = "error"
                run.task_id = None
                run.last_stopped_at = now
                run.run_end_requested = False

    try:
        _set_stage("integration")
        if mcp_configs:
            _append_task_log(
                "Selected MCP servers: " + ", ".join(sorted(mcp_configs)) + "."
            )
        else:
            _append_task_log("No MCP servers selected for this task.")
        if unknown_scripts:
            _append_task_log(
                f"Skipping {len(unknown_scripts)} script(s) with unknown type."
            )
        if is_task_integration_selected("github", selected_integration_keys):
            try:
                workspace = _maybe_checkout_repo(task_id, on_log=_append_task_log)
            except Exception as exc:
                _append_task_log(str(exc))
                _finalize_failure(str(exc))
                logger.exception("GitHub checkout failed for task %s", task_id)
                _cleanup_workspace(task_id, _build_task_workspace(task_id))
                return

        if workspace is None:
            _append_task_log("No integration actions required.")
        else:
            logger.info("Using workspace %s for task %s", workspace, task_id)
            _append_task_log(f"Workspace ready: {workspace}.")
            workspace_ready_logged = True

        _set_stage("pre_init")
        if pre_init_scripts:
            staging_dir = _build_script_staging_dir(task_id)
            try:
                pre_init_entries = _materialize_scripts(
                    pre_init_scripts,
                    staging_dir,
                    on_log=_append_task_log,
                )
                _run_stage_scripts(
                    "pre-init",
                    pre_init_scripts,
                    pre_init_entries,
                    _append_task_log,
                )
            except Exception as exc:
                _append_task_log(str(exc))
                _finalize_failure(str(exc))
                return
        else:
            _append_task_log("No pre-init scripts configured.")

        _set_stage("init")
        try:
            if workspace is None and (
                combined_scripts
                or compiled_instruction_package is not None
                or (resolved_skills is not None and resolved_skills.skills)
            ):
                workspace = _build_task_workspace(task_id)
                workspace.mkdir(parents=True, exist_ok=True)
                _append_task_log(f"Workspace created: {workspace}.")
                logger.info("Using workspace %s for task %s", workspace, task_id)
                _append_task_log(f"Workspace ready: {workspace}.")
                workspace_ready_logged = True

            if workspace is not None and not workspace_ready_logged:
                logger.info("Using workspace %s for task %s", workspace, task_id)
                _append_task_log(f"Workspace ready: {workspace}.")
                workspace_ready_logged = True
            if (
                workspace is not None
                and compiled_instruction_package is not None
                and not instructions_materialized
            ):
                _log_instruction_package_observability(
                    compiled_instruction_package=compiled_instruction_package,
                    on_log=_append_task_log,
                )
                _log_instruction_reference_risk(
                    compiled_instruction_package=compiled_instruction_package,
                    on_log=_append_task_log,
                )
                materialized = materialize_instruction_package(
                    workspace,
                    compiled_instruction_package,
                )
                instruction_manifest_hash = materialized.manifest_hash
                instruction_materialized_paths = list(materialized.materialized_paths)
                _validate_instruction_materialized_paths(
                    paths=instruction_materialized_paths,
                    workspace=workspace,
                    runtime_home=None,
                    codex_home=None,
                )
                _append_task_log(
                    f"Instruction package manifest: {instruction_manifest_hash}."
                )
                _append_task_log(
                    f"Instruction package path: {materialized.package_dir}."
                )
                instructions_materialized = True
                with session_scope() as session:
                    task = session.get(AgentTask, task_id)
                    if task is not None:
                        task.resolved_instruction_manifest_hash = (
                            instruction_manifest_hash
                        )
                        task.instruction_materialized_paths_json = (
                            _serialize_materialized_paths(instruction_materialized_paths)
                        )
            if workspace is not None and combined_scripts and not script_entries:
                scripts_dir = workspace / SCRIPTS_DIRNAME
                script_entries = _materialize_scripts(
                    combined_scripts,
                    scripts_dir,
                    on_log=_append_task_log,
                )

            _run_stage_scripts(
                "init",
                init_scripts,
                script_entries,
                _append_task_log,
            )

            if workspace is not None:
                if (
                    is_task_integration_selected("github", selected_integration_keys)
                    and github_repo
                    and not is_run_task
                ):
                    updated_payload = _inject_github_repo(
                        payload,
                        github_repo,
                        task_kind,
                        workspace,
                    )
                    if updated_payload != payload:
                        payload = updated_payload
                        with session_scope() as session:
                            task = session.get(AgentTask, task_id)
                            if task is not None:
                                task.prompt = payload

            updated_payload = _inject_integrations(
                payload,
                _build_integrations_payload(
                    workspace,
                    selected_keys=selected_integration_keys,
                ),
            )
            if updated_payload != payload:
                payload = updated_payload
                with session_scope() as session:
                    task = session.get(AgentTask, task_id)
                    if task is not None:
                        task.prompt = payload
        except Exception as exc:
            _append_task_log(str(exc))
            _finalize_failure(str(exc))
            return

        _set_stage("post_init")
        try:
            _run_stage_scripts(
                "post-init",
                post_init_scripts,
                script_entries,
                _append_task_log,
            )
        except Exception as exc:
            _append_task_log(str(exc))
            _finalize_failure(str(exc))
            return

        _set_stage("llm_query")
        result = None
        try:
            llm_env = os.environ.copy()
            seed_codex_home = _resolve_codex_home_from_env(llm_env)
            runtime_home = _prepare_task_runtime_home(task_id)
            _apply_run_local_home_env(llm_env, runtime_home)
            llm_cwd = workspace if workspace is not None else runtime_home
            if workspace is not None:
                llm_env["WORKSPACE_PATH"] = str(workspace)
                llm_env["LLMCTL_STUDIO_WORKSPACE"] = str(workspace)
            if provider == "codex":
                codex_home = _prepare_task_codex_home(task_id, seed_home=seed_codex_home)
                llm_env["CODEX_HOME"] = str(codex_home)
                codex_api_key = _load_codex_auth_key()
                if codex_api_key:
                    llm_env["OPENAI_API_KEY"] = codex_api_key
                    llm_env["CODEX_API_KEY"] = codex_api_key
            elif provider == "gemini":
                gemini_api_key = _load_gemini_auth_key()
                if gemini_api_key:
                    llm_env["GEMINI_API_KEY"] = gemini_api_key
                    llm_env["GOOGLE_API_KEY"] = gemini_api_key
            elif provider == "claude":
                claude_api_key, _ = _resolve_claude_auth_key(llm_env)
                if claude_api_key:
                    llm_env["ANTHROPIC_API_KEY"] = claude_api_key
            _validate_runtime_isolation_env(
                llm_env=llm_env,
                runtime_home=runtime_home,
                codex_home=codex_home,
                on_log=_append_task_log,
            )
            if (
                workspace is not None
                and runtime_home is not None
                and compiled_instruction_package is not None
            ):
                payload, instruction_adapter_mode, instruction_adapter_name, adapter_paths = (
                    _apply_instruction_adapter_policy(
                        provider=provider,
                        llm_settings=llm_settings,
                        compiled_instruction_package=compiled_instruction_package,
                        configured_agent_markdown_filename=configured_agent_markdown_filename,
                        workspace=workspace,
                        runtime_home=runtime_home,
                        codex_home=codex_home,
                        payload=payload,
                        task_kind=task_kind or "task",
                        on_log=_append_task_log,
                    )
                )
                for path in adapter_paths:
                    if path not in instruction_materialized_paths:
                        instruction_materialized_paths.append(path)
                _append_task_log(
                    "Instruction adapter mode: "
                    f"{instruction_adapter_mode} ({instruction_adapter_name})."
                )
                for path in adapter_paths:
                    _append_task_log(f"Instruction materialized path: {path}")
                with session_scope() as session:
                    task = session.get(AgentTask, task_id)
                    if task is not None:
                        task.instruction_adapter_mode = instruction_adapter_mode
                        task.resolved_instruction_manifest_hash = (
                            instruction_manifest_hash
                            or resolved_instruction_manifest_hash
                        )
                        task.instruction_materialized_paths_json = (
                            _serialize_materialized_paths(instruction_materialized_paths)
                        )
                if instruction_adapter_mode == "fallback":
                    with session_scope() as session:
                        task = session.get(AgentTask, task_id)
                        if task is not None:
                            task.prompt = payload
            if resolved_skills is not None and resolved_skills.skills:
                assert workspace is not None
                assert runtime_home is not None
                fallback_entries: list[dict[str, str]] = []
                adapter_result = materialize_skill_set(
                    resolved_skills,
                    provider=provider,
                    workspace=workspace,
                    runtime_home=runtime_home,
                    codex_home=codex_home,
                )
                skill_adapter_mode = adapter_result.mode
                skill_adapter_name = adapter_result.adapter
                skill_materialized_paths = list(adapter_result.materialized_paths)
                fallback_entries = list(adapter_result.fallback_entries)
                with session_scope() as session:
                    task = session.get(AgentTask, task_id)
                    if task is not None:
                        task.skill_adapter_mode = skill_adapter_mode
                resolved_summary = ", ".join(
                    f"{entry.name}@{entry.version}" for entry in resolved_skills.skills
                )
                _append_task_log(f"Resolved skills: {resolved_summary}.")
                _append_task_log(
                    f"Skill adapter mode: {skill_adapter_mode} ({skill_adapter_name})."
                )
                for path in skill_materialized_paths:
                    _append_task_log(f"Skill materialized path: {path}")
                if skill_adapter_mode == "fallback" and fallback_entries:
                    payload = _inject_skill_fallback(
                        payload,
                        fallback_entries,
                        task_kind or "task",
                    )
                    with session_scope() as session:
                        task = session.get(AgentTask, task_id)
                        if task is not None:
                            task.prompt = payload
                elif skill_adapter_mode == "fallback":
                    _append_task_log(
                        "Fallback mode selected but no SKILL.md excerpts were available."
                    )
            _append_task_log(f"Launching {provider_label}...")
            result = _run_llm(
                provider,
                payload,
                mcp_configs=mcp_configs,
                model_config=model_config,
                on_update=_persist_logs,
                on_log=_append_task_log,
                cwd=llm_cwd,
                env=llm_env,
            )
        except FileNotFoundError as exc:
            llm_failed = True
            llm_message = str(exc)
            _append_task_log(str(exc))
            logger.exception("%s command not found", provider_label)
        except Exception as exc:
            llm_failed = True
            llm_message = str(exc)
            _append_task_log(str(exc))
            logger.exception("%s run failed", provider_label)

        if result is not None:
            last_output = result.stdout
            last_error = result.stderr
            now = _utcnow()
            with session_scope() as session:
                task = session.get(AgentTask, task_id)
                agent = session.get(Agent, agent_id) if agent_id is not None else None
                run = session.get(Run, run_id) if run_id is not None else None
                if task is None:
                    return
                task.output = result.stdout
                task.error = "".join(log_prefix_chunks) + result.stderr
                task.current_stage = current_stage
                task.stage_logs = _serialize_stage_logs()
                if agent is not None:
                    agent.last_run_at = now
                    agent.last_error = result.stderr
                if run is not None:
                    run.last_run_at = now
                    run.last_output = result.stdout
                    run.last_error = result.stderr
            if result.returncode != 0:
                llm_failed = True
                llm_message = (
                    result.stderr.strip()
                    or f"{provider_label} exited with code {result.returncode}."
                )
                if agent_id is not None:
                    logger.error(
                        "Agent %s exited with code %s", agent_id, result.returncode
                    )
                else:
                    logger.error(
                        "Agent task %s exited with code %s", task_id, result.returncode
                    )

        _set_stage("post_run")
        try:
            _run_stage_scripts(
                "post-run",
                post_run_scripts,
                script_entries,
                _append_task_log,
            )
        except Exception as exc:
            post_run_failed = True
            post_run_message = str(exc)
            _append_task_log(str(exc))

        final_failed = llm_failed or post_run_failed
        failure_message = llm_message or post_run_message
        now = _utcnow()
        with session_scope() as session:
            task = session.get(AgentTask, task_id)
            agent = session.get(Agent, agent_id) if agent_id is not None else None
            run = session.get(Run, run_id) if run_id is not None else None
            if task is None:
                return
            if task.status == "canceled":
                task.finished_at = task.finished_at or now
                if not task.error:
                    task.error = "Canceled by user."
                task.current_stage = current_stage
                task.stage_logs = _serialize_stage_logs()
                task.resolved_role_id = resolved_role_id
                task.resolved_role_version = resolved_role_version
                task.resolved_agent_id = resolved_agent_id
                task.resolved_agent_version = resolved_agent_version
                task.resolved_skill_ids_json = _json_dumps(resolved_skill_ids)
                task.resolved_skill_versions_json = _json_dumps(
                    resolved_skill_versions
                )
                task.resolved_skill_manifest_hash = resolved_skill_manifest_hash
                task.skill_adapter_mode = skill_adapter_mode
                task.resolved_instruction_manifest_hash = (
                    instruction_manifest_hash or resolved_instruction_manifest_hash
                )
                task.instruction_adapter_mode = instruction_adapter_mode
                task.instruction_materialized_paths_json = _serialize_materialized_paths(
                    instruction_materialized_paths
                )
                _emit_task_event(
                    "node.task.completed",
                    task=task,
                    payload={
                        "terminal_status": "canceled",
                    },
                )
                return
            task.status = "failed" if final_failed else "succeeded"
            task.finished_at = now
            task.error = "".join(log_prefix_chunks) + last_error
            task.current_stage = current_stage
            task.stage_logs = _serialize_stage_logs()
            task.resolved_role_id = resolved_role_id
            task.resolved_role_version = resolved_role_version
            task.resolved_agent_id = resolved_agent_id
            task.resolved_agent_version = resolved_agent_version
            task.resolved_skill_ids_json = _json_dumps(resolved_skill_ids)
            task.resolved_skill_versions_json = _json_dumps(resolved_skill_versions)
            task.resolved_skill_manifest_hash = resolved_skill_manifest_hash
            task.skill_adapter_mode = skill_adapter_mode
            task.resolved_instruction_manifest_hash = (
                instruction_manifest_hash or resolved_instruction_manifest_hash
            )
            task.instruction_adapter_mode = instruction_adapter_mode
            task.instruction_materialized_paths_json = _serialize_materialized_paths(
                instruction_materialized_paths
            )
            _emit_task_event(
                "node.task.completed",
                task=task,
                payload={
                    "terminal_status": str(task.status),
                    "failure_message": failure_message if final_failed else None,
                },
            )
            if agent is not None:
                agent.last_run_at = now
                if final_failed:
                    agent.last_error = failure_message or agent.last_error or "Task failed."
                    agent.task_id = None
                    agent.last_stopped_at = now
            if run is not None:
                run.last_run_at = now
                if final_failed:
                    run.last_error = failure_message or run.last_error or "Task failed."
                    run.status = "error"
                    run.task_id = None
                    run.last_stopped_at = now
                    run.run_end_requested = False
    finally:
        _cleanup_codex_home(task_id, codex_home)
        _cleanup_workspace(task_id, runtime_home, label="runtime home")
        _cleanup_workspace(task_id, staging_dir, label="script staging")
        _cleanup_workspace(task_id, workspace)


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _json_dumps(value: Any) -> str:
    return json.dumps(_json_safe(value), sort_keys=True)


def _parse_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _extract_path_value(payload: Any, path: str) -> Any:
    cleaned_path = (path or "").strip()
    if not cleaned_path:
        return None
    current = payload
    for token in cleaned_path.split("."):
        segment = token.strip()
        if not segment:
            continue
        if isinstance(current, dict):
            if segment not in current:
                return None
            current = current[segment]
            continue
        if isinstance(current, list):
            if not segment.isdigit():
                return None
            index = int(segment)
            if index < 0 or index >= len(current):
                return None
            current = current[index]
            continue
        return None
    return current


def _parse_optional_int(
    value: Any,
    *,
    default: int = 0,
    minimum: int | None = None,
) -> int:
    parsed = default
    if isinstance(value, bool):
        parsed = int(value)
    elif isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        raw = value.strip()
        if raw:
            try:
                parsed = int(raw)
            except ValueError:
                parsed = default
    if minimum is not None and parsed < minimum:
        return minimum
    return parsed


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _allow_skill_adapter_fallback(node_config: dict[str, Any]) -> bool:
    mode_raw = node_config.get("skill_adapter_failure_mode")
    if isinstance(mode_raw, str):
        normalized = mode_raw.strip().lower()
        if normalized in {"fallback", "prompt_fallback", "downgrade_to_fallback"}:
            return True
        if normalized in {"fail", "strict", "required"}:
            return False
    if "skill_fallback_on_adapter_error" in node_config:
        return _coerce_bool(node_config.get("skill_fallback_on_adapter_error"))
    if "allow_skill_adapter_fallback" in node_config:
        return _coerce_bool(node_config.get("allow_skill_adapter_fallback"))
    return False


def _split_scripts_by_stage(
    scripts: list[Script],
) -> tuple[
    list[Script],
    list[Script],
    list[Script],
    list[Script],
    list[Script],
]:
    pre_init: list[Script] = []
    init: list[Script] = []
    post_init: list[Script] = []
    post_run: list[Script] = []
    unknown: list[Script] = []
    for script in scripts:
        if script.script_type == SCRIPT_TYPE_PRE_INIT:
            pre_init.append(script)
        elif script.script_type == SCRIPT_TYPE_INIT:
            init.append(script)
        elif script.script_type == SCRIPT_TYPE_POST_INIT:
            post_init.append(script)
        elif script.script_type == SCRIPT_TYPE_POST_RUN:
            post_run.append(script)
        else:
            unknown.append(script)
    return pre_init, init, post_init, post_run, unknown


def _serialize_memory_for_node(memory: Memory) -> dict[str, Any]:
    return {
        "id": memory.id,
        "description": memory.description,
        "created_at": _json_safe(memory.created_at),
        "updated_at": _json_safe(memory.updated_at),
    }


def _serialize_milestone_for_node(milestone: Milestone) -> dict[str, Any]:
    return {
        "id": milestone.id,
        "name": milestone.name,
        "description": milestone.description,
        "status": milestone.status,
        "priority": milestone.priority,
        "owner": milestone.owner,
        "completed": milestone.completed,
        "start_date": _json_safe(milestone.start_date),
        "due_date": _json_safe(milestone.due_date),
        "progress_percent": milestone.progress_percent,
        "health": milestone.health,
        "success_criteria": milestone.success_criteria,
        "dependencies": milestone.dependencies,
        "links": milestone.links,
        "latest_update": milestone.latest_update,
        "created_at": _json_safe(milestone.created_at),
        "updated_at": _json_safe(milestone.updated_at),
    }


def _serialize_plan_for_node(plan: Plan) -> dict[str, Any]:
    stages = sorted(
        list(plan.stages or []),
        key=lambda item: (item.position, item.id),
    )
    return {
        "id": plan.id,
        "name": plan.name,
        "description": plan.description,
        "completed_at": _json_safe(plan.completed_at),
        "created_at": _json_safe(plan.created_at),
        "updated_at": _json_safe(plan.updated_at),
        "stages": [
            {
                "id": stage.id,
                "plan_id": stage.plan_id,
                "name": stage.name,
                "description": stage.description,
                "position": stage.position,
                "completed_at": _json_safe(stage.completed_at),
                "created_at": _json_safe(stage.created_at),
                "updated_at": _json_safe(stage.updated_at),
                "tasks": [
                    {
                        "id": task.id,
                        "plan_stage_id": task.plan_stage_id,
                        "name": task.name,
                        "description": task.description,
                        "position": task.position,
                        "completed_at": _json_safe(task.completed_at),
                        "created_at": _json_safe(task.created_at),
                        "updated_at": _json_safe(task.updated_at),
                    }
                    for task in sorted(
                        list(stage.tasks or []),
                        key=lambda item: (item.position, item.id),
                    )
                ],
            }
            for stage in stages
        ],
    }


def _parse_structured_output(raw_output: str) -> Any:
    cleaned = (raw_output or "").strip()
    if not cleaned:
        return {}
    if cleaned.startswith("{") or cleaned.startswith("["):
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
    fenced_match = re.search(
        r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```",
        cleaned,
        flags=re.DOTALL,
    )
    if fenced_match:
        try:
            return json.loads(fenced_match.group(1))
        except json.JSONDecodeError:
            pass
    return {"text": cleaned}


def _build_flowchart_input_context(
    *,
    flowchart_id: int,
    run_id: int,
    node_id: int,
    node_type: str,
    execution_index: int,
    total_execution_count: int,
    incoming_edges: list[dict[str, Any]] | None = None,
    latest_results: dict[int, dict[str, Any]] | None = None,
    upstream_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    upstream_nodes: list[dict[str, Any]] = []
    latest_upstream: dict[str, Any] | None = None

    # Preserve existing trigger-context behavior for solid activations.
    if upstream_results is not None:
        for upstream in upstream_results:
            source_node_id_raw = _parse_optional_int(
                upstream.get("source_node_id"),
                default=0,
                minimum=0,
            )
            source_node_id = source_node_id_raw if source_node_id_raw > 0 else None
            entry = {
                "node_id": source_node_id,
                "source_edge_id": _parse_optional_int(
                    upstream.get("source_edge_id"),
                    default=0,
                    minimum=0,
                )
                or None,
                "node_type": upstream.get("node_type"),
                "condition_key": upstream.get("condition_key"),
                "execution_index": upstream.get("execution_index"),
                "output_state": upstream.get("output_state") or {},
                "routing_state": upstream.get("routing_state") or {},
                "sequence": upstream.get("sequence"),
                "edge_mode": _normalize_flowchart_edge_mode(upstream.get("edge_mode")),
            }
            upstream_nodes.append(entry)
            if latest_upstream is None or (
                _parse_optional_int(entry.get("sequence"), default=0)
                > _parse_optional_int(latest_upstream.get("sequence"), default=0)
            ):
                latest_upstream = entry
    else:
        for edge in incoming_edges or []:
            if not _edge_is_solid(edge):
                continue
            source_node_id = int(edge["source_node_id"])
            previous = (latest_results or {}).get(source_node_id)
            if previous is None:
                continue
            entry = {
                "node_id": source_node_id,
                "source_edge_id": int(edge["id"]),
                "node_type": previous.get("node_type"),
                "condition_key": edge.get("condition_key"),
                "execution_index": previous.get("execution_index"),
                "output_state": previous.get("output_state") or {},
                "routing_state": previous.get("routing_state") or {},
                "sequence": previous.get("sequence"),
                "edge_mode": FLOWCHART_EDGE_MODE_SOLID,
            }
            upstream_nodes.append(entry)
            if latest_upstream is None or (
                _parse_optional_int(entry.get("sequence"), default=0)
                > _parse_optional_int(latest_upstream.get("sequence"), default=0)
            ):
                latest_upstream = entry

    dotted_upstream_nodes: list[dict[str, Any]] = []
    for edge in incoming_edges or []:
        if not _edge_is_dotted(edge):
            continue
        source_node_id = int(edge["source_node_id"])
        previous = (latest_results or {}).get(source_node_id)
        if previous is None:
            # Dotted sources are optional in v1; missing output contributes no payload.
            continue
        dotted_upstream_nodes.append(
            {
                "node_id": source_node_id,
                "source_edge_id": int(edge["id"]),
                "node_type": previous.get("node_type"),
                "condition_key": edge.get("condition_key"),
                "execution_index": previous.get("execution_index"),
                "output_state": previous.get("output_state") or {},
                "routing_state": previous.get("routing_state") or {},
                "sequence": previous.get("sequence"),
                "edge_mode": FLOWCHART_EDGE_MODE_DOTTED,
            }
        )

    if logger.isEnabledFor(logging.DEBUG):
        incoming_dotted_edge_count = sum(
            1 for edge in (incoming_edges or []) if _edge_is_dotted(edge)
        )
        pulled_sources = [
            {
                "source_edge_id": item.get("source_edge_id"),
                "source_node_id": item.get("node_id"),
            }
            for item in dotted_upstream_nodes
        ]
        logger.debug(
            "Flowchart run %s node %s execution %s pulled dotted context %s/%s (available/declared): %s",
            run_id,
            node_id,
            execution_index,
            len(dotted_upstream_nodes),
            incoming_dotted_edge_count,
            pulled_sources,
        )

    trigger_sources = [
        {
            "source_edge_id": entry.get("source_edge_id"),
            "source_node_id": entry.get("node_id"),
            "source_node_type": entry.get("node_type"),
            "condition_key": entry.get("condition_key"),
            "execution_index": entry.get("execution_index"),
            "sequence": entry.get("sequence"),
            "edge_mode": FLOWCHART_EDGE_MODE_SOLID,
        }
        for entry in upstream_nodes
        if _normalize_flowchart_edge_mode(entry.get("edge_mode"))
        == FLOWCHART_EDGE_MODE_SOLID
    ]
    pulled_dotted_sources = [
        {
            "source_edge_id": entry.get("source_edge_id"),
            "source_node_id": entry.get("node_id"),
            "source_node_type": entry.get("node_type"),
            "condition_key": entry.get("condition_key"),
            "execution_index": entry.get("execution_index"),
            "sequence": entry.get("sequence"),
            "edge_mode": FLOWCHART_EDGE_MODE_DOTTED,
        }
        for entry in dotted_upstream_nodes
    ]

    return {
        "flowchart": {
            "id": flowchart_id,
            "run_id": run_id,
            "total_execution_count": total_execution_count,
        },
        "node": {
            "id": node_id,
            "type": node_type,
            "execution_index": execution_index,
        },
        "upstream_nodes": upstream_nodes,
        "latest_upstream": latest_upstream,
        "dotted_upstream_nodes": dotted_upstream_nodes,
        "trigger_sources": trigger_sources,
        "pulled_dotted_sources": pulled_dotted_sources,
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
    node_id: int,
    node_type: str,
    execution_index: int,
    input_context: dict[str, Any],
) -> str:
    return _json_dumps(
        {
            "kind": "flowchart_node_activity",
            "flowchart_id": flowchart_id,
            "flowchart_run_id": run_id,
            "flowchart_node_id": node_id,
            "flowchart_node_type": node_type,
            "execution_index": execution_index,
            "input_context": input_context,
        }
    )


def _apply_flowchart_node_task_run_metadata(
    task: AgentTask,
    run_metadata: dict[str, Any] | None,
) -> None:
    if not isinstance(run_metadata, dict):
        return

    provider = str(run_metadata.get("selected_provider") or "").strip().lower()
    if provider in {"kubernetes"}:
        task.selected_provider = provider

    final_provider = str(run_metadata.get("final_provider") or "").strip().lower()
    if final_provider in {"kubernetes"}:
        task.final_provider = final_provider

    provider_dispatch_id_raw = run_metadata.get("provider_dispatch_id")
    if provider_dispatch_id_raw is None:
        task.provider_dispatch_id = None
    else:
        provider_dispatch_id = str(provider_dispatch_id_raw).strip()
        task.provider_dispatch_id = provider_dispatch_id or None

    workspace_identity = str(run_metadata.get("workspace_identity") or "").strip()
    if workspace_identity:
        task.workspace_identity = workspace_identity

    dispatch_status = str(run_metadata.get("dispatch_status") or "").strip().lower()
    if dispatch_status in {
        "dispatch_pending",
        "dispatch_submitted",
        "dispatch_confirmed",
        "dispatch_failed",
    }:
        task.dispatch_status = dispatch_status

    task.fallback_attempted = _coerce_bool(run_metadata.get("fallback_attempted"))

    fallback_reason_raw = run_metadata.get("fallback_reason")
    if fallback_reason_raw is None:
        task.fallback_reason = None
    else:
        fallback_reason = str(fallback_reason_raw).strip().lower()
        task.fallback_reason = fallback_reason or None

    task.dispatch_uncertain = _coerce_bool(run_metadata.get("dispatch_uncertain"))

    api_failure_category_raw = run_metadata.get("api_failure_category")
    if api_failure_category_raw is None:
        task.api_failure_category = None
    else:
        api_failure_category = str(api_failure_category_raw).strip().lower()
        task.api_failure_category = api_failure_category or None

    task.cli_fallback_used = _coerce_bool(run_metadata.get("cli_fallback_used"))
    cli_preflight_raw = run_metadata.get("cli_preflight_passed")
    if cli_preflight_raw is None:
        task.cli_preflight_passed = None
    else:
        task.cli_preflight_passed = _coerce_bool(cli_preflight_raw)


def _create_flowchart_node_task(
    session,
    *,
    flowchart_id: int,
    run_id: int,
    node_id: int,
    node_type: str,
    node_ref_id: int | None,
    agent_id: int | None = None,
    execution_index: int,
    input_context: dict[str, Any],
    status: str,
    started_at: datetime | None,
    finished_at: datetime | None = None,
    output_state: dict[str, Any] | None = None,
    error: str | None = None,
    run_metadata: dict[str, Any] | None = None,
) -> AgentTask:
    task = AgentTask.create(
        session,
        agent_id=agent_id,
        flowchart_id=flowchart_id,
        flowchart_run_id=run_id,
        flowchart_node_id=node_id,
        status=status,
        kind=_flowchart_node_task_kind(node_type),
        prompt=_flowchart_node_task_prompt(
            flowchart_id=flowchart_id,
            run_id=run_id,
            node_id=node_id,
            node_type=node_type,
            execution_index=execution_index,
            input_context=input_context,
        ),
        output=_json_dumps(output_state) if output_state is not None else None,
        error=error,
        started_at=started_at,
        finished_at=finished_at,
    )
    _apply_flowchart_node_task_run_metadata(task, run_metadata)
    return task


def _update_flowchart_node_task(
    session,
    *,
    node_run: FlowchartRunNode | None,
    status: str,
    output_state: dict[str, Any] | None = None,
    error: str | None = None,
    finished_at: datetime | None = None,
    run_metadata: dict[str, Any] | None = None,
) -> None:
    if node_run is None or node_run.agent_task_id is None:
        return
    task = session.get(AgentTask, node_run.agent_task_id)
    if task is None:
        return
    _apply_flowchart_node_task_run_metadata(task, run_metadata)
    task.status = status
    if task.started_at is None and node_run.started_at is not None:
        task.started_at = node_run.started_at
    if output_state is not None:
        task.output = _flowchart_task_output_display(output_state)
        output_agent_id = _parse_optional_int(
            output_state.get("agent_id"),
            default=0,
            minimum=0,
        )
        if output_agent_id > 0:
            task.agent_id = output_agent_id
        resolved_agent_id = _parse_optional_int(
            output_state.get("resolved_agent_id"),
            default=0,
            minimum=0,
        )
        if resolved_agent_id > 0:
            task.resolved_agent_id = resolved_agent_id
        resolved_agent_version = output_state.get("resolved_agent_version")
        if isinstance(resolved_agent_version, str) and resolved_agent_version.strip():
            task.resolved_agent_version = resolved_agent_version
        resolved_role_id = output_state.get("resolved_role_id")
        if isinstance(resolved_role_id, int):
            task.resolved_role_id = resolved_role_id
        resolved_role_version = output_state.get("resolved_role_version")
        if isinstance(resolved_role_version, str) and resolved_role_version.strip():
            task.resolved_role_version = resolved_role_version
        resolved_skill_ids = output_state.get("resolved_skill_ids")
        if isinstance(resolved_skill_ids, list):
            task.resolved_skill_ids_json = _json_dumps(resolved_skill_ids)
        resolved_skill_versions = output_state.get("resolved_skill_versions")
        if isinstance(resolved_skill_versions, list):
            task.resolved_skill_versions_json = _json_dumps(resolved_skill_versions)
        resolved_skill_manifest_hash = output_state.get("resolved_skill_manifest_hash")
        if (
            isinstance(resolved_skill_manifest_hash, str)
            and resolved_skill_manifest_hash.strip()
        ):
            task.resolved_skill_manifest_hash = resolved_skill_manifest_hash
        adapter_mode = output_state.get("skill_adapter_mode")
        if isinstance(adapter_mode, str) and adapter_mode.strip():
            task.skill_adapter_mode = adapter_mode
        instruction_manifest_hash = output_state.get("instruction_manifest_hash")
        if isinstance(instruction_manifest_hash, str) and instruction_manifest_hash.strip():
            task.resolved_instruction_manifest_hash = instruction_manifest_hash
        instruction_adapter_mode = output_state.get("instruction_adapter_mode")
        if isinstance(instruction_adapter_mode, str) and instruction_adapter_mode.strip():
            task.instruction_adapter_mode = instruction_adapter_mode
        instruction_materialized_paths = output_state.get("instruction_materialized_paths")
        if isinstance(instruction_materialized_paths, list):
            task.instruction_materialized_paths_json = _json_dumps(
                instruction_materialized_paths
            )
        stage_raw = output_state.get("task_current_stage")
        if isinstance(stage_raw, str) and stage_raw.strip():
            task.current_stage = stage_raw.strip()
        logs_raw = output_state.get("task_stage_logs")
        if isinstance(logs_raw, dict):
            task.stage_logs = json.dumps(
                {
                    str(stage_key): str(stage_logs)
                    for stage_key, stage_logs in logs_raw.items()
                },
                sort_keys=True,
            )
    if error is not None:
        task.error = error
    elif status == "succeeded":
        task.error = None
    if finished_at is not None:
        task.finished_at = finished_at


def _flowchart_task_output_display(output_state: dict[str, Any]) -> str:
    node_type = str(output_state.get("node_type") or "").strip()
    if node_type != FLOWCHART_NODE_TYPE_TASK:
        if node_type == FLOWCHART_NODE_TYPE_RAG:
            answer = output_state.get("answer")
            if isinstance(answer, str) and answer.strip():
                return answer
        if node_type == FLOWCHART_NODE_TYPE_FLOWCHART:
            run_id = _parse_optional_int(
                output_state.get("triggered_flowchart_run_id"),
                default=0,
                minimum=0,
            )
            target_id = _parse_optional_int(
                output_state.get("triggered_flowchart_id"),
                default=0,
                minimum=0,
            )
            if run_id > 0 and target_id > 0:
                return f"Queued flowchart {target_id} run {run_id}."
        return _json_dumps(output_state)

    raw_output = output_state.get("raw_output")
    if isinstance(raw_output, str) and raw_output.strip():
        return raw_output

    structured_output = output_state.get("structured_output")
    if isinstance(structured_output, str) and structured_output.strip():
        return structured_output
    if isinstance(structured_output, dict):
        text_value = structured_output.get("text")
        if isinstance(text_value, str) and text_value.strip():
            return text_value

    return _json_dumps(output_state)


def _normalize_flowchart_edge_mode(value: Any) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned == FLOWCHART_EDGE_MODE_DOTTED:
        return FLOWCHART_EDGE_MODE_DOTTED
    return FLOWCHART_EDGE_MODE_SOLID


def _edge_is_solid(edge: dict[str, Any]) -> bool:
    return _normalize_flowchart_edge_mode(edge.get("edge_mode")) == FLOWCHART_EDGE_MODE_SOLID


def _edge_is_dotted(edge: dict[str, Any]) -> bool:
    return _normalize_flowchart_edge_mode(edge.get("edge_mode")) == FLOWCHART_EDGE_MODE_DOTTED


def _resolve_flowchart_outgoing_edges(
    *,
    node_type: str,
    node_config: dict[str, Any],
    outgoing_edges: list[dict[str, Any]],
    routing_state: dict[str, Any],
) -> list[dict[str, Any]]:
    if not outgoing_edges:
        return []

    solid_edges = [edge for edge in outgoing_edges if _edge_is_solid(edge)]
    route_key_raw = routing_state.get("route_key")
    route_key = str(route_key_raw).strip() if route_key_raw is not None else ""

    if node_type == FLOWCHART_NODE_TYPE_DECISION:
        if not solid_edges:
            raise ValueError("Decision node has no solid outgoing edges.")
        if not route_key:
            raise ValueError("Decision node did not produce a route_key.")
        for edge in solid_edges:
            condition_key = str(edge.get("condition_key") or "").strip()
            if condition_key == route_key:
                return [edge]
        fallback_key = str(node_config.get("fallback_condition_key") or "").strip()
        if fallback_key:
            for edge in solid_edges:
                condition_key = str(edge.get("condition_key") or "").strip()
                if condition_key == fallback_key:
                    return [edge]
        default_edges = [
            edge
            for edge in solid_edges
            if not str(edge.get("condition_key") or "").strip()
        ]
        if len(default_edges) == 1:
            return default_edges
        raise ValueError(
            f"Decision route '{route_key}' has no matching outgoing edge and no fallback."
        )

    if route_key:
        for edge in solid_edges:
            condition_key = str(edge.get("condition_key") or "").strip()
            if condition_key == route_key:
                return [edge]
    return list(solid_edges)


def _record_flowchart_guardrail_failure(
    *,
    flowchart_id: int,
    run_id: int,
    node_id: int,
    node_type: str,
    node_ref_id: int | None = None,
    execution_index: int,
    total_execution_count: int,
    incoming_edges: list[dict[str, Any]],
    latest_results: dict[int, dict[str, Any]],
    upstream_results: list[dict[str, Any]],
    message: str,
) -> None:
    input_context = _build_flowchart_input_context(
        flowchart_id=flowchart_id,
        run_id=run_id,
        node_id=node_id,
        node_type=node_type,
        execution_index=execution_index,
        total_execution_count=total_execution_count,
        incoming_edges=incoming_edges,
        latest_results=latest_results,
        upstream_results=upstream_results,
    )
    now = _utcnow()
    with session_scope() as session:
        node_task = _create_flowchart_node_task(
            session,
            flowchart_id=flowchart_id,
            run_id=run_id,
            node_id=node_id,
            node_type=node_type,
            node_ref_id=node_ref_id,
            execution_index=execution_index,
            input_context=input_context,
            status="failed",
            started_at=now,
            finished_at=now,
            error=message,
        )
        node_run = FlowchartRunNode.create(
            session,
            flowchart_run_id=run_id,
            flowchart_node_id=node_id,
            execution_index=execution_index,
            agent_task_id=node_task.id,
            status="failed",
            input_context_json=_json_dumps(input_context),
            error=message,
            started_at=now,
            finished_at=now,
        )
        _emit_task_event(
            "node.task.completed",
            task=node_task,
            payload={
                "terminal_status": "failed",
                "failure_message": message,
                "guardrail_failure": True,
            },
        )
        _emit_flowchart_node_event(
            "flowchart.node.updated",
            flowchart_id=flowchart_id,
            flowchart_run_id=run_id,
            flowchart_node_id=node_id,
            node_type=node_type,
            status="failed",
            execution_index=execution_index,
            node_run_id=node_run.id,
            agent_task_id=node_task.id,
            error=message,
            started_at=now,
            finished_at=now,
            runtime=None,
        )


def _resolve_node_model(
    session,
    *,
    node: FlowchartNode,
    default_model_id: int | None = None,
) -> LLMModel:
    model_id: int | None = node.model_id
    if model_id is None:
        model_id = default_model_id
    if model_id is None:
        raise ValueError("No model configured for flowchart task node.")
    model = session.get(LLMModel, model_id)
    if model is None:
        raise ValueError(f"Model {model_id} was not found.")
    return model


def _execute_optional_llm_transform(
    *,
    prompt: str,
    model: LLMModel,
    enabled_providers: set[str],
    mcp_configs: dict[str, dict[str, Any]],
    attachments: list[Attachment] | None = None,
) -> Any:
    provider = model.provider
    if provider not in LLM_PROVIDERS:
        raise ValueError(f"Unknown model provider: {provider}.")
    if provider not in enabled_providers:
        raise ValueError(f"Provider disabled: {provider}.")
    model_config = _parse_model_config(model.config_json)
    transform_prompt = prompt
    if attachments:
        transform_prompt = _inject_attachments(
            transform_prompt,
            _build_attachment_entries(attachments),
            replace_existing=False,
        )
    llm_env = os.environ.copy()
    with tempfile.TemporaryDirectory(prefix="llmctl-flowchart-transform-home-") as tmp_home:
        runtime_home = Path(tmp_home)
        _apply_run_local_home_env(llm_env, runtime_home)
        result = _run_llm(
            provider,
            transform_prompt,
            mcp_configs=mcp_configs,
            model_config=model_config,
            on_update=None,
            on_log=None,
            cwd=runtime_home,
            env=llm_env,
        )
    if result.returncode != 0:
        message = result.stderr.strip() or f"LLM transform failed with code {result.returncode}."
        raise RuntimeError(message)
    return _parse_structured_output(result.stdout)


def _execute_flowchart_task_node(
    *,
    node_id: int,
    node_ref_id: int | None,
    node_config: dict[str, Any],
    input_context: dict[str, Any],
    execution_id: int,
    execution_task_id: int | None,
    enabled_providers: set[str],
    default_model_id: int | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    selected_agent_id: int | None = None
    selected_agent_role_id: int | None = None
    selected_agent_role_version: str | None = None
    selected_agent_version: str | None = None
    selected_agent_name: str | None = None
    selected_agent_profile: dict[str, object] | None = None
    selected_system_contract: dict[str, object] | None = None
    selected_agent_source: str | None = None
    selected_agent_role_markdown = ""
    selected_agent_markdown = ""
    compiled_instruction_package = None
    resolved_skills = None
    with session_scope() as session:
        node = (
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
        if node is None:
            raise ValueError(f"Flowchart node {node_id} was not found.")
        model = _resolve_node_model(
            session,
            node=node,
            default_model_id=default_model_id,
        )
        configured_agent_id = _parse_optional_int(
            node_config.get("agent_id"),
            default=0,
            minimum=0,
        )
        if configured_agent_id > 0:
            selected_agent_id = configured_agent_id
            selected_agent_source = "config"
        if selected_agent_id is not None:
            selected_agent = session.get(Agent, selected_agent_id)
            if selected_agent is None:
                raise ValueError(f"Agent {selected_agent_id} was not found.")
            selected_agent_name = selected_agent.name
            selected_agent_role_id = selected_agent.role_id
            selected_agent_version = _resolve_updated_at_version(selected_agent.updated_at)
            selected_agent_role_version = _resolve_updated_at_version(
                selected_agent.role.updated_at if selected_agent.role is not None else None
            )
            selected_agent_profile = _build_agent_payload(selected_agent)
            selected_system_contract = _build_system_contract(selected_agent)
            selected_agent_role_markdown = _build_role_markdown(selected_agent.role)
            selected_agent_markdown = _build_agent_markdown(selected_agent)
        if "skill_ids" in node_config:
            logger.warning(
                "Flowchart node %s supplied legacy node-level skill_ids payload; "
                "runtime ignores this and resolves skills from agent bindings only.",
                node_id,
            )
        legacy_binding_count = int(
            session.execute(
                select(func.count())
                .select_from(flowchart_node_skills)
                .where(flowchart_node_skills.c.flowchart_node_id == node_id)
            ).scalar_one()
            or 0
        )
        if legacy_binding_count > 0:
            logger.warning(
                "Flowchart node %s has %s legacy node-level skill binding(s); "
                "runtime ignores node bindings and resolves skills from agent %s.",
                node_id,
                legacy_binding_count,
                selected_agent_id,
            )
        mcp_servers = list(node.mcp_servers)
        node_scripts = list(node.scripts)
        node_attachments = list(node.attachments)
        attachments = list(node_attachments)
        if selected_agent_id is not None:
            try:
                resolved_skills = resolve_agent_skills(session, selected_agent_id)
            except ValueError as exc:
                raise ValueError(
                    f"Skill resolution failed for agent {selected_agent_id}: {exc}"
                ) from exc
    attachment_ids = [attachment.id for attachment in attachments]
    attachment_entries = _build_attachment_entries(attachments)

    provider = model.provider
    llm_settings = load_integration_settings("llm")
    if provider not in LLM_PROVIDERS:
        raise ValueError(f"Unknown model provider: {provider}.")
    if provider not in enabled_providers:
        raise ValueError(f"Provider disabled: {provider}.")
    model_config = _parse_model_config(model.config_json)
    configured_agent_markdown_filename = str(
        model_config.get("agent_markdown_filename") or ""
    ).strip() or None
    mcp_configs = _build_mcp_config_map(mcp_servers)

    ordered_scripts: list[Script] = []
    seen_script_ids: set[int] = set()
    for script in node_scripts:
        if script.id in seen_script_ids:
            continue
        seen_script_ids.add(script.id)
        path = ensure_script_file(
            script.id,
            script.file_name,
            script.content,
            script.file_path,
        )
        script.file_path = str(path)
        ordered_scripts.append(script)

    (
        pre_init_scripts,
        init_scripts,
        post_init_scripts,
        post_run_scripts,
        unknown_scripts,
    ) = _split_scripts_by_stage(ordered_scripts)
    runnable_scripts = pre_init_scripts + init_scripts + post_init_scripts + post_run_scripts

    script_logs: list[str] = []
    stage_log_chunks: dict[str, list[str]] = {}
    current_stage: str | None = None
    last_llm_error = ""
    last_llm_output = ""
    progress_flush_interval = 0.4
    last_progress_flush = 0.0
    progress_dirty = False
    stage_index = {
        stage_key: index + 1 for index, (stage_key, _) in enumerate(TASK_STAGE_ORDER)
    }
    total_stages = len(TASK_STAGE_ORDER)

    def _serialize_stage_logs() -> dict[str, str]:
        return {
            stage_key: "".join(chunks)
            for stage_key, chunks in stage_log_chunks.items()
            if chunks
        }

    def _persist_progress(force: bool = False) -> None:
        nonlocal last_progress_flush, progress_dirty
        if execution_task_id is None:
            return
        if not force and not progress_dirty:
            return
        now = time.monotonic()
        if not force and now - last_progress_flush < progress_flush_interval:
            return
        stage_logs_payload = _serialize_stage_logs()
        with session_scope() as session:
            task = session.get(AgentTask, execution_task_id)
            if task is None:
                return
            if task.status in {"queued", "pending"}:
                task.status = "running"
            task.current_stage = current_stage
            task.stage_logs = (
                json.dumps(stage_logs_payload, sort_keys=True)
                if stage_logs_payload
                else None
            )
            if last_llm_output:
                task.output = last_llm_output
        last_progress_flush = now
        progress_dirty = False

    def _append_script_log(message: str) -> None:
        nonlocal progress_dirty
        script_logs.append(message)
        if current_stage:
            line = message.rstrip("\n") + "\n"
            stage_log_chunks.setdefault(current_stage, []).append(line)
            progress_dirty = True
            _persist_progress()

    def _capture_llm_updates(output: str, error: str) -> None:
        nonlocal last_llm_error, last_llm_output, progress_dirty
        if current_stage != "llm_query":
            return
        output_delta = ""
        if output.startswith(last_llm_output):
            output_delta = output[len(last_llm_output):]
        else:
            output_delta = output
        if output_delta:
            stage_log_chunks.setdefault(current_stage, []).append(output_delta)
            last_llm_output = output
            progress_dirty = True
        if error.startswith(last_llm_error):
            delta = error[len(last_llm_error):]
        else:
            delta = error
        if delta:
            stage_log_chunks.setdefault(current_stage, []).append(delta)
            last_llm_error = error
            progress_dirty = True
        if progress_dirty:
            _persist_progress()

    def _set_stage(stage_key: str) -> None:
        nonlocal current_stage, last_llm_error
        current_stage = stage_key
        last_llm_error = ""
        stage_log_chunks.setdefault(stage_key, [])
        label = TASK_STAGE_LABELS.get(stage_key, stage_key)
        index = stage_index.get(stage_key, 0)
        _append_script_log(f"Stage {index}/{total_stages}: {label}")

    inline_task_name = str(node_config.get("task_name") or "").strip() or None
    inline_task_prompt_raw = node_config.get("task_prompt")
    inline_task_prompt = (
        str(inline_task_prompt_raw)
        if isinstance(inline_task_prompt_raw, str)
        else ""
    )
    if inline_task_prompt.strip():
        base_prompt = inline_task_prompt
        prompt_source = "config"
    else:
        raise ValueError("Task node requires config.task_prompt.")
    if not base_prompt.strip():
        raise ValueError("Task node prompt is empty. Provide config.task_prompt.")

    resolved_task_name = (
        inline_task_name
        or f"Flowchart task node {node_id}"
    )
    selected_integration_keys: set[str] | None = None
    raw_integration_keys = node_config.get("integration_keys")
    if raw_integration_keys is not None:
        if not isinstance(raw_integration_keys, list):
            raise ValueError("Task node config.integration_keys must be an array.")
        valid_integration_keys, invalid_integration_keys = validate_task_integration_keys(
            raw_integration_keys
        )
        if invalid_integration_keys:
            raise ValueError(
                "Task node config.integration_keys contains invalid key(s): "
                + ", ".join(invalid_integration_keys)
                + "."
            )
        selected_integration_keys = set(valid_integration_keys)
    resolved_instruction_manifest_hash: str | None = None
    if selected_agent_id is not None:
        compiled_instruction_package = compile_instruction_package(
            InstructionCompileInput(
                run_mode="flowchart",
                provider=provider,
                role_markdown=selected_agent_role_markdown,
                agent_markdown=selected_agent_markdown,
                priorities=tuple(),
                runtime_overrides=(base_prompt,),
                source_ids={
                    "agent_id": selected_agent_id,
                    "role_id": selected_agent_role_id,
                },
                source_versions={
                    "agent_version": selected_agent_version,
                    "role_version": selected_agent_role_version,
                },
            )
        )
        resolved_instruction_manifest_hash = compiled_instruction_package.manifest_hash

    payload = _build_task_payload("flowchart", base_prompt)
    payload_dict = _load_prompt_dict(payload)
    if payload_dict is not None and is_prompt_envelope(payload_dict):
        task_context = _ensure_task_context(payload_dict)
        task_context["kind"] = "flowchart"
        flowchart_context: dict[str, Any] = {
            "node_id": node_id,
            "input_context": input_context,
        }
        flowchart_context["task_name"] = resolved_task_name
        flowchart_context["task_prompt_source"] = prompt_source
        if selected_agent_id is not None:
            flowchart_context["agent_id"] = selected_agent_id
            flowchart_context["agent_name"] = selected_agent_name
            if selected_agent_source is not None:
                flowchart_context["agent_source"] = selected_agent_source
        task_context["flowchart"] = flowchart_context
        payload = serialize_prompt_envelope(payload_dict)
    else:
        payload = (
            f"{base_prompt}\n\nFlowchart input context:\n"
            + json.dumps(_json_safe(input_context), indent=2, sort_keys=True)
        )
    if selected_agent_profile is not None:
        payload = _inject_envelope_core_sections(
            payload,
            system_contract=selected_system_contract,
            agent_profile=selected_agent_profile,
            task_kind="flowchart",
        )
    payload = _inject_attachments(payload, attachment_entries)
    payload = _inject_runtime_metadata(payload, _build_runtime_payload(provider, model_config))

    resolved_skill_ids = (
        skill_ids_payload(resolved_skills) if resolved_skills is not None else []
    )
    resolved_skill_versions = (
        skill_versions_payload(resolved_skills) if resolved_skills is not None else []
    )
    resolved_skill_manifest_hash = (
        resolved_skills.manifest_hash if resolved_skills is not None else None
    )
    with session_scope() as session:
        node_run = session.get(FlowchartRunNode, execution_id)
        if node_run is not None:
            node_run.resolved_skill_ids_json = _json_dumps(resolved_skill_ids)
            node_run.resolved_skill_versions_json = _json_dumps(resolved_skill_versions)
            node_run.resolved_skill_manifest_hash = resolved_skill_manifest_hash
            node_run.resolved_role_id = selected_agent_role_id
            node_run.resolved_role_version = selected_agent_role_version
            node_run.resolved_agent_id = selected_agent_id
            node_run.resolved_agent_version = selected_agent_version
            node_run.resolved_instruction_manifest_hash = resolved_instruction_manifest_hash
            node_run.instruction_adapter_mode = None
            node_run.instruction_materialized_paths_json = None
        if execution_task_id is not None:
            task = session.get(AgentTask, execution_task_id)
            if task is not None:
                if attachment_ids:
                    task_attachments = (
                        session.execute(
                            select(Attachment).where(Attachment.id.in_(attachment_ids))
                        )
                        .scalars()
                        .all()
                    )
                    _attach_task_attachments(task, task_attachments)
                task.resolved_role_id = selected_agent_role_id
                task.resolved_role_version = selected_agent_role_version
                task.resolved_agent_id = selected_agent_id
                task.resolved_agent_version = selected_agent_version
                task.resolved_skill_ids_json = _json_dumps(resolved_skill_ids)
                task.resolved_skill_versions_json = _json_dumps(
                    resolved_skill_versions
                )
                task.resolved_skill_manifest_hash = resolved_skill_manifest_hash
                task.skill_adapter_mode = None
                task.resolved_instruction_manifest_hash = (
                    resolved_instruction_manifest_hash
                )
                task.instruction_adapter_mode = None
                task.instruction_materialized_paths_json = None

    workspace: Path | None = None
    staging_dir: Path | None = None
    runtime_home: Path | None = None
    codex_home: Path | None = None
    script_entries: list[dict[str, str]] = []
    instruction_manifest_hash = resolved_instruction_manifest_hash or ""
    instruction_materialized_paths: list[str] = []
    instructions_materialized = False
    llm_result: subprocess.CompletedProcess[str] | None = None
    instruction_adapter_mode: str | None = None
    instruction_adapter_name: str | None = None
    skill_adapter_mode: str | None = None
    skill_adapter_name: str | None = None
    skill_materialized_paths: list[str] = []

    try:
        _set_stage("integration")
        if selected_integration_keys is None:
            _append_script_log("Using default integration context (all integrations).")
        elif selected_integration_keys:
            _append_script_log(
                "Using selected integrations: "
                + ", ".join(sorted(selected_integration_keys))
                + "."
            )
        else:
            _append_script_log("No integrations selected for this task node.")
        if unknown_scripts:
            _append_script_log(
                f"Skipping {len(unknown_scripts)} script(s) with unknown type."
            )

        _set_stage("pre_init")
        if pre_init_scripts:
            staging_dir = _build_script_staging_dir(execution_id)
            pre_init_entries = _materialize_scripts(
                pre_init_scripts,
                staging_dir,
                on_log=_append_script_log,
            )
            _run_stage_scripts(
                "pre-init",
                pre_init_scripts,
                pre_init_entries,
                _append_script_log,
            )
        else:
            _append_script_log("No pre-init scripts configured.")

        _set_stage("init")
        if (
            runnable_scripts
            or (resolved_skills is not None and resolved_skills.skills)
            or compiled_instruction_package is not None
        ):
            workspace = _build_task_workspace(execution_id)
            workspace.mkdir(parents=True, exist_ok=True)
            if runnable_scripts:
                scripts_dir = workspace / SCRIPTS_DIRNAME
                script_entries = _materialize_scripts(
                    runnable_scripts,
                    scripts_dir,
                    on_log=_append_script_log,
                )
        if (
            workspace is not None
            and compiled_instruction_package is not None
            and not instructions_materialized
        ):
            _log_instruction_package_observability(
                compiled_instruction_package=compiled_instruction_package,
                on_log=_append_script_log,
            )
            _log_instruction_reference_risk(
                compiled_instruction_package=compiled_instruction_package,
                on_log=_append_script_log,
            )
            materialized = materialize_instruction_package(
                workspace,
                compiled_instruction_package,
            )
            instruction_manifest_hash = materialized.manifest_hash
            instruction_materialized_paths = list(materialized.materialized_paths)
            _validate_instruction_materialized_paths(
                paths=instruction_materialized_paths,
                workspace=workspace,
                runtime_home=None,
                codex_home=None,
            )
            _append_script_log(
                f"Instruction package manifest: {instruction_manifest_hash}."
            )
            _append_script_log(
                f"Instruction package path: {materialized.package_dir}."
            )
            instructions_materialized = True
            with session_scope() as session:
                node_run = session.get(FlowchartRunNode, execution_id)
                if node_run is not None:
                    node_run.resolved_instruction_manifest_hash = instruction_manifest_hash
                    node_run.instruction_materialized_paths_json = (
                        _serialize_materialized_paths(instruction_materialized_paths)
                    )
                if execution_task_id is not None:
                    task = session.get(AgentTask, execution_task_id)
                    if task is not None:
                        task.resolved_instruction_manifest_hash = instruction_manifest_hash
                        task.instruction_materialized_paths_json = (
                            _serialize_materialized_paths(instruction_materialized_paths)
                        )

        _run_stage_scripts(
            "init",
            init_scripts,
            script_entries,
            _append_script_log,
        )

        _set_stage("post_init")
        _run_stage_scripts(
            "post-init",
            post_init_scripts,
            script_entries,
            _append_script_log,
        )

        payload = _inject_integrations(
            payload,
            _build_integrations_payload(
                workspace,
                selected_keys=selected_integration_keys,
            ),
        )

        llm_env = os.environ.copy()
        seed_codex_home = _resolve_codex_home_from_env(llm_env)
        runtime_home = _prepare_task_runtime_home(execution_id)
        _apply_run_local_home_env(llm_env, runtime_home)
        llm_cwd = workspace if workspace is not None else runtime_home
        if workspace is not None:
            llm_env["WORKSPACE_PATH"] = str(workspace)
            llm_env["LLMCTL_STUDIO_WORKSPACE"] = str(workspace)
        if provider == "codex":
            codex_home = _prepare_task_codex_home(
                execution_id,
                seed_home=seed_codex_home,
            )
            llm_env["CODEX_HOME"] = str(codex_home)
            codex_api_key = _load_codex_auth_key()
            if codex_api_key:
                llm_env["OPENAI_API_KEY"] = codex_api_key
                llm_env["CODEX_API_KEY"] = codex_api_key
        elif provider == "gemini":
            gemini_api_key = _load_gemini_auth_key()
            if gemini_api_key:
                llm_env["GEMINI_API_KEY"] = gemini_api_key
                llm_env["GOOGLE_API_KEY"] = gemini_api_key
        elif provider == "claude":
            claude_api_key, _ = _resolve_claude_auth_key(llm_env)
            if claude_api_key:
                llm_env["ANTHROPIC_API_KEY"] = claude_api_key
        _validate_runtime_isolation_env(
            llm_env=llm_env,
            runtime_home=runtime_home,
            codex_home=codex_home,
            on_log=_append_script_log,
        )

        if (
            workspace is not None
            and runtime_home is not None
            and compiled_instruction_package is not None
        ):
            payload, instruction_adapter_mode, instruction_adapter_name, adapter_paths = (
                _apply_instruction_adapter_policy(
                    provider=provider,
                    llm_settings=llm_settings,
                    compiled_instruction_package=compiled_instruction_package,
                    configured_agent_markdown_filename=configured_agent_markdown_filename,
                    workspace=workspace,
                    runtime_home=runtime_home,
                    codex_home=codex_home,
                    payload=payload,
                    task_kind="flowchart",
                    on_log=_append_script_log,
                )
            )
            for path in adapter_paths:
                if path not in instruction_materialized_paths:
                    instruction_materialized_paths.append(path)
            _append_script_log(
                "Instruction adapter mode: "
                f"{instruction_adapter_mode} ({instruction_adapter_name})."
            )
            for path in adapter_paths:
                _append_script_log(f"Instruction materialized path: {path}")
            with session_scope() as session:
                node_run = session.get(FlowchartRunNode, execution_id)
                if node_run is not None:
                    node_run.instruction_adapter_mode = instruction_adapter_mode
                    node_run.resolved_instruction_manifest_hash = (
                        instruction_manifest_hash or resolved_instruction_manifest_hash
                    )
                    node_run.instruction_materialized_paths_json = (
                        _serialize_materialized_paths(instruction_materialized_paths)
                    )
                if execution_task_id is not None:
                    task = session.get(AgentTask, execution_task_id)
                    if task is not None:
                        task.instruction_adapter_mode = instruction_adapter_mode
                        task.resolved_instruction_manifest_hash = (
                            instruction_manifest_hash
                            or resolved_instruction_manifest_hash
                        )
                        task.instruction_materialized_paths_json = (
                            _serialize_materialized_paths(instruction_materialized_paths)
                        )

        if resolved_skills is not None and resolved_skills.skills:
            assert workspace is not None
            assert runtime_home is not None
            fallback_on_adapter_error = _allow_skill_adapter_fallback(node_config)
            fallback_entries: list[dict[str, str]] = []
            try:
                adapter_result = materialize_skill_set(
                    resolved_skills,
                    provider=provider,
                    workspace=workspace,
                    runtime_home=runtime_home,
                    codex_home=codex_home,
                )
                skill_adapter_mode = adapter_result.mode
                skill_adapter_name = adapter_result.adapter
                skill_materialized_paths = list(adapter_result.materialized_paths)
                fallback_entries = list(adapter_result.fallback_entries)
            except Exception as exc:
                if not fallback_on_adapter_error:
                    raise
                _append_script_log(f"Skill adapter materialization failed: {exc}")
                _append_script_log(
                    "Downgrading skill adapter to prompt fallback due node policy."
                )
                skill_adapter_mode = "fallback"
                skill_adapter_name = "prompt_fallback"
                skill_materialized_paths = []
                fallback_entries = build_skill_fallback_entries(resolved_skills)
            with session_scope() as session:
                node_run = session.get(FlowchartRunNode, execution_id)
                if node_run is not None:
                    node_run.skill_adapter_mode = skill_adapter_mode
                if execution_task_id is not None:
                    task = session.get(AgentTask, execution_task_id)
                    if task is not None:
                        task.skill_adapter_mode = skill_adapter_mode
            resolved_summary = ", ".join(
                f"{entry.name}@{entry.version}" for entry in resolved_skills.skills
            )
            _append_script_log(f"Resolved skills: {resolved_summary}.")
            _append_script_log(
                f"Skill adapter mode: {skill_adapter_mode} ({skill_adapter_name})."
            )
            for path in skill_materialized_paths:
                _append_script_log(f"Skill materialized path: {path}")
            if skill_adapter_mode == "fallback" and fallback_entries:
                payload = _inject_skill_fallback(
                    payload,
                    fallback_entries,
                    "flowchart",
                )
            elif skill_adapter_mode == "fallback":
                _append_script_log(
                    "Fallback mode selected but no SKILL.md excerpts were available."
                )

        _set_stage("llm_query")
        _append_script_log(f"Launching {_provider_label(provider)}...")
        llm_result = _run_llm(
            provider,
            payload,
            mcp_configs=mcp_configs,
            model_config=model_config,
            on_update=_capture_llm_updates,
            on_log=_append_script_log,
            cwd=llm_cwd,
            env=llm_env,
        )

        _set_stage("post_run")
        _run_stage_scripts(
            "post-run",
            post_run_scripts,
            script_entries,
            _append_script_log,
        )
    finally:
        _cleanup_codex_home(execution_id, codex_home)
        _cleanup_workspace(execution_id, runtime_home, label="runtime home")
        _cleanup_workspace(execution_id, staging_dir, label="script staging")
        _cleanup_workspace(execution_id, workspace)
        _persist_progress(force=True)

    if llm_result is None:
        raise RuntimeError("Task node did not execute an LLM query.")
    if llm_result.returncode != 0:
        message = llm_result.stderr.strip() or f"LLM exited with code {llm_result.returncode}."
        raise RuntimeError(message)

    structured_output = _parse_structured_output(llm_result.stdout)
    route_key = _extract_path_value(structured_output, "route_key")

    stage_logs = _serialize_stage_logs()
    output_state = {
        "node_type": FLOWCHART_NODE_TYPE_TASK,
        "task_name": resolved_task_name,
        "task_prompt_source": prompt_source,
        "agent_id": selected_agent_id,
        "agent_name": selected_agent_name,
        "agent_source": selected_agent_source,
        "resolved_role_id": selected_agent_role_id,
        "resolved_role_version": selected_agent_role_version,
        "resolved_agent_id": selected_agent_id,
        "resolved_agent_version": selected_agent_version,
        "provider": provider,
        "model_id": model.id,
        "model_name": model.name,
        "mcp_server_keys": [server.server_key for server in mcp_servers],
        "attachments": attachment_entries,
        "integration_keys": (
            sorted(selected_integration_keys)
            if selected_integration_keys is not None
            else None
        ),
        "script_ids": [script.id for script in runnable_scripts],
        "resolved_skill_ids": resolved_skill_ids,
        "resolved_skill_versions": resolved_skill_versions,
        "resolved_skill_manifest_hash": resolved_skill_manifest_hash,
        "skill_adapter_mode": skill_adapter_mode,
        "skill_adapter": skill_adapter_name,
        "skill_materialized_paths": skill_materialized_paths,
        "instruction_adapter_mode": instruction_adapter_mode,
        "instruction_adapter": instruction_adapter_name,
        "instruction_manifest_hash": instruction_manifest_hash or None,
        "instruction_materialized_paths": instruction_materialized_paths,
        "structured_output": structured_output,
        "raw_output": llm_result.stdout,
        "raw_error": "",
        "script_logs": script_logs,
        "task_current_stage": current_stage,
        "task_stage_logs": stage_logs,
    }
    routing_state: dict[str, Any] = {}
    if route_key is not None and str(route_key).strip():
        routing_state["route_key"] = str(route_key).strip()
    return output_state, routing_state


def _execute_flowchart_decision_node(
    *,
    node_config: dict[str, Any],
    input_context: dict[str, Any],
    mcp_server_keys: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    route_field_path = str(node_config.get("route_field_path") or "").strip()
    if not route_field_path:
        route_field_path = "latest_upstream.output_state.structured_output.route_key"
    route_value = _extract_path_value(input_context, route_field_path)
    if route_value is None:
        route_value = _extract_path_value(input_context, "latest_upstream.routing_state.route_key")
    if route_value is None or not str(route_value).strip():
        raise ValueError(
            f"Decision node could not resolve route key from '{route_field_path}'."
        )
    route_key = str(route_value).strip()
    output_state = {
        "node_type": FLOWCHART_NODE_TYPE_DECISION,
        "resolved_route_path": route_field_path,
        "resolved_route_key": route_key,
        "mcp_server_keys": list(mcp_server_keys),
    }
    return output_state, {"route_key": route_key}


def _apply_plan_completion_patch(
    *,
    plan: Plan,
    patch: dict[str, Any],
    action_results: list[str],
    now: datetime,
) -> None:
    if _coerce_bool(patch.get("mark_plan_complete")):
        plan.completed_at = now
        action_results.append("Marked plan as completed.")

    stage_ids_raw = patch.get("complete_stage_ids") or patch.get("stage_ids") or []
    stage_ids = {
        _parse_optional_int(value, default=0, minimum=1) for value in stage_ids_raw
    }
    stages_by_id = {stage.id: stage for stage in list(plan.stages or [])}
    for stage_id in sorted(stage_ids):
        stage = stages_by_id.get(stage_id)
        if stage is None:
            continue
        stage.completed_at = now
        action_results.append(f"Marked stage {stage_id} as completed.")

    task_ids_raw = patch.get("complete_task_ids") or patch.get("task_ids") or []
    task_ids = {_parse_optional_int(value, default=0, minimum=1) for value in task_ids_raw}
    tasks_by_id: dict[int, PlanTask] = {}
    for stage in list(plan.stages or []):
        for task in list(stage.tasks or []):
            tasks_by_id[task.id] = task
    for task_id in sorted(task_ids):
        task = tasks_by_id.get(task_id)
        if task is None:
            continue
        task.completed_at = now
        action_results.append(f"Marked task {task_id} as completed.")


def _execute_flowchart_plan_node(
    *,
    node_id: int,
    node_ref_id: int | None,
    node_config: dict[str, Any],
    input_context: dict[str, Any],
    enabled_providers: set[str],
    default_model_id: int | None,
    mcp_server_keys: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    with session_scope() as session:
        node = (
            session.execute(
                select(FlowchartNode)
                .options(
                    selectinload(FlowchartNode.mcp_servers),
                    selectinload(FlowchartNode.model),
                    selectinload(FlowchartNode.attachments),
                )
                .where(FlowchartNode.id == node_id)
            )
            .scalars()
            .first()
        )
        if node is None:
            raise ValueError(f"Flowchart node {node_id} was not found.")
        plan = (
            session.execute(
                select(Plan)
                .options(selectinload(Plan.stages).selectinload(PlanStage.tasks))
                .where(Plan.id == node_ref_id)
            )
            .scalars()
            .first()
        )
        if plan is None:
            raise ValueError(f"Plan {node_ref_id} was not found.")

        action = str(node_config.get("action") or "read").strip().lower()
        now = _utcnow()
        action_results: list[str] = []
        if action in {"update", "update_completion", "complete"}:
            direct_patch = node_config.get("patch")
            if isinstance(direct_patch, dict):
                _apply_plan_completion_patch(
                    plan=plan,
                    patch=direct_patch,
                    action_results=action_results,
                    now=now,
                )
            completion_source_path = str(
                node_config.get("completion_source_path") or ""
            ).strip()
            if completion_source_path:
                completion_patch = _extract_path_value(input_context, completion_source_path)
                if isinstance(completion_patch, dict):
                    _apply_plan_completion_patch(
                        plan=plan,
                        patch=completion_patch,
                        action_results=action_results,
                        now=now,
                    )
                else:
                    action_results.append(
                        f"No completion patch found at '{completion_source_path}'."
                    )

        if _coerce_bool(node_config.get("transform_with_llm")):
            transform_prompt = str(node_config.get("transform_prompt") or "").strip()
            if transform_prompt:
                model = _resolve_node_model(
                    session,
                    node=node,
                    default_model_id=default_model_id,
                )
                llm_patch = _execute_optional_llm_transform(
                    prompt=transform_prompt,
                    model=model,
                    enabled_providers=enabled_providers,
                    mcp_configs=_build_mcp_config_map(list(node.mcp_servers)),
                    attachments=list(node.attachments),
                )
                if isinstance(llm_patch, dict):
                    _apply_plan_completion_patch(
                        plan=plan,
                        patch=llm_patch,
                        action_results=action_results,
                        now=now,
                    )
                    action_results.append("Applied LLM transform patch to plan.")

        output_state = {
            "node_type": FLOWCHART_NODE_TYPE_PLAN,
            "action": action,
            "action_results": action_results,
            "mcp_server_keys": list(mcp_server_keys),
            "attachments": _build_attachment_entries(list(node.attachments)),
            "plan": _serialize_plan_for_node(plan),
        }

    route_key = str(node_config.get("route_key") or "").strip()
    route_key_on_complete = str(node_config.get("route_key_on_complete") or "").strip()
    if route_key_on_complete and output_state["plan"].get("completed_at"):
        route_key = route_key_on_complete
    routing_state: dict[str, Any] = {}
    if route_key:
        routing_state["route_key"] = route_key
    return output_state, routing_state


def _execute_flowchart_milestone_node(
    *,
    node_id: int,
    node_ref_id: int | None,
    node_config: dict[str, Any],
    input_context: dict[str, Any],
    execution_index: int,
    enabled_providers: set[str],
    default_model_id: int | None,
    mcp_server_keys: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    with session_scope() as session:
        node = (
            session.execute(
                select(FlowchartNode)
                .options(
                    selectinload(FlowchartNode.mcp_servers),
                    selectinload(FlowchartNode.model),
                    selectinload(FlowchartNode.attachments),
                )
                .where(FlowchartNode.id == node_id)
            )
            .scalars()
            .first()
        )
        if node is None:
            raise ValueError(f"Flowchart node {node_id} was not found.")
        milestone = session.get(Milestone, node_ref_id)
        if milestone is None:
            raise ValueError(f"Milestone {node_ref_id} was not found.")

        action = str(node_config.get("action") or "read").strip().lower()
        now = _utcnow()
        action_results: list[str] = []

        if action in {"update", "checkpoint", "complete"}:
            patch = node_config.get("patch")
            if isinstance(patch, dict):
                if "name" in patch:
                    milestone.name = str(patch.get("name") or "").strip() or milestone.name
                if "description" in patch:
                    milestone.description = str(patch.get("description") or "")
                if "status" in patch:
                    milestone.status = str(patch.get("status") or milestone.status)
                if "priority" in patch:
                    milestone.priority = str(patch.get("priority") or milestone.priority)
                if "owner" in patch:
                    milestone.owner = str(patch.get("owner") or "").strip() or None
                if "progress_percent" in patch:
                    milestone.progress_percent = _parse_optional_int(
                        patch.get("progress_percent"),
                        default=milestone.progress_percent,
                        minimum=0,
                    )
                    if milestone.progress_percent > 100:
                        milestone.progress_percent = 100
                if "health" in patch:
                    milestone.health = str(patch.get("health") or milestone.health)
                if "latest_update" in patch:
                    milestone.latest_update = str(patch.get("latest_update") or "")
                action_results.append("Applied milestone patch.")

            completion_source_path = str(
                node_config.get("completion_source_path") or ""
            ).strip()
            if completion_source_path:
                completion_patch = _extract_path_value(input_context, completion_source_path)
                if isinstance(completion_patch, dict):
                    if "status" in completion_patch:
                        milestone.status = str(completion_patch.get("status") or milestone.status)
                    if "progress_percent" in completion_patch:
                        progress = _parse_optional_int(
                            completion_patch.get("progress_percent"),
                            default=milestone.progress_percent,
                            minimum=0,
                        )
                        milestone.progress_percent = min(progress, 100)
                    if _coerce_bool(completion_patch.get("completed")):
                        milestone.completed = True
                    action_results.append("Applied upstream completion patch.")

            if _coerce_bool(node_config.get("mark_complete")):
                milestone.completed = True
                milestone.status = MILESTONE_STATUS_DONE
                milestone.progress_percent = 100
                action_results.append("Marked milestone complete.")

        if _coerce_bool(node_config.get("transform_with_llm")):
            transform_prompt = str(node_config.get("transform_prompt") or "").strip()
            if transform_prompt:
                model = _resolve_node_model(
                    session,
                    node=node,
                    default_model_id=default_model_id,
                )
                llm_patch = _execute_optional_llm_transform(
                    prompt=transform_prompt,
                    model=model,
                    enabled_providers=enabled_providers,
                    mcp_configs=_build_mcp_config_map(list(node.mcp_servers)),
                    attachments=list(node.attachments),
                )
                if isinstance(llm_patch, dict):
                    if "latest_update" in llm_patch:
                        milestone.latest_update = str(llm_patch.get("latest_update") or "")
                    if "health" in llm_patch:
                        milestone.health = str(llm_patch.get("health") or milestone.health)
                    action_results.append("Applied LLM semantic patch.")

        if milestone.status == MILESTONE_STATUS_DONE:
            milestone.completed = True
            milestone.progress_percent = max(milestone.progress_percent, 100)

        checkpoint_every = _parse_optional_int(
            node_config.get("loop_checkpoint_every"),
            default=0,
            minimum=0,
        )
        checkpoint_hit = checkpoint_every > 0 and execution_index % checkpoint_every == 0
        if checkpoint_hit:
            action_results.append(
                f"Checkpoint reached at execution #{execution_index} (every {checkpoint_every})."
            )

        output_state = {
            "node_type": FLOWCHART_NODE_TYPE_MILESTONE,
            "action": action,
            "execution_index": execution_index,
            "checkpoint_hit": checkpoint_hit,
            "action_results": action_results,
            "mcp_server_keys": list(mcp_server_keys),
            "attachments": _build_attachment_entries(list(node.attachments)),
            "milestone": _serialize_milestone_for_node(milestone),
        }

    terminate_run = _coerce_bool(node_config.get("terminate_always"))
    if _coerce_bool(node_config.get("terminate_on_complete")) and output_state["milestone"].get(
        "completed"
    ):
        terminate_run = True
    if checkpoint_hit and _coerce_bool(node_config.get("terminate_on_checkpoint")):
        terminate_run = True
    loop_exit_after_runs = _parse_optional_int(
        node_config.get("loop_exit_after_runs"),
        default=0,
        minimum=0,
    )
    if loop_exit_after_runs > 0 and execution_index >= loop_exit_after_runs:
        terminate_run = True

    route_key = str(node_config.get("route_key") or "").strip()
    if terminate_run:
        route_key = str(node_config.get("route_key_on_terminate") or route_key).strip()
    routing_state: dict[str, Any] = {}
    if route_key:
        routing_state["route_key"] = route_key
    if terminate_run:
        routing_state["terminate_run"] = True
    return output_state, routing_state


def _execute_flowchart_memory_node(
    *,
    node_id: int,
    node_ref_id: int | None,
    node_config: dict[str, Any],
    input_context: dict[str, Any],
    mcp_server_keys: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    action = str(node_config.get("action") or "fetch").strip().lower()
    limit = _parse_optional_int(node_config.get("limit"), default=10, minimum=1)
    retrieved: list[dict[str, Any]] = []
    stored_memory: dict[str, Any] | None = None
    action_results: list[str] = []
    attachment_entries: list[dict[str, object]] = []

    with session_scope() as session:
        node = (
            session.execute(
                select(FlowchartNode)
                .options(selectinload(FlowchartNode.attachments))
                .where(FlowchartNode.id == node_id)
            )
            .scalars()
            .first()
        )
        if node is None:
            raise ValueError(f"Flowchart node {node_id} was not found.")
        attachment_entries = _build_attachment_entries(list(node.attachments))
        if action == "fetch":
            if node_ref_id is not None:
                memory = session.get(Memory, node_ref_id)
                if memory is None:
                    raise ValueError(f"Memory {node_ref_id} was not found.")
                retrieved = [_serialize_memory_for_node(memory)]
                action_results.append(f"Fetched memory {node_ref_id}.")
            else:
                query_text = str(node_config.get("query") or "").strip()
                query_path = str(node_config.get("query_source_path") or "").strip()
                if query_path:
                    query_value = _extract_path_value(input_context, query_path)
                    if isinstance(query_value, str) and query_value.strip():
                        query_text = query_value.strip()
                stmt = select(Memory).order_by(Memory.updated_at.desc(), Memory.id.desc())
                if query_text:
                    stmt = stmt.where(Memory.description.ilike(f"%{query_text}%"))
                items = session.execute(stmt.limit(limit)).scalars().all()
                retrieved = [_serialize_memory_for_node(item) for item in items]
                action_results.append(f"Fetched {len(retrieved)} memory item(s).")
        elif action in {"store", "upsert", "append"}:
            text = str(node_config.get("text") or "").strip()
            source_path = str(node_config.get("text_source_path") or "").strip()
            if source_path:
                source_value = _extract_path_value(input_context, source_path)
                if source_value is not None:
                    if isinstance(source_value, str):
                        text = source_value.strip()
                    else:
                        text = json.dumps(_json_safe(source_value), sort_keys=True)
            if not text:
                raise ValueError("Memory store action requires text or text_source_path.")
            if node_ref_id is not None:
                memory = session.get(Memory, node_ref_id)
                if memory is None:
                    raise ValueError(f"Memory {node_ref_id} was not found.")
                store_mode = str(node_config.get("store_mode") or "replace").strip().lower()
                if store_mode == "append":
                    prefix = memory.description.rstrip()
                    memory.description = f"{prefix}\n\n{text}" if prefix else text
                else:
                    memory.description = text
                stored_memory = _serialize_memory_for_node(memory)
                action_results.append(f"Updated memory {node_ref_id}.")
            else:
                created = Memory.create(session, description=text)
                stored_memory = _serialize_memory_for_node(created)
                action_results.append(f"Created memory {created.id}.")
        else:
            raise ValueError(f"Unsupported memory node action '{action}'.")

    output_state = {
        "node_type": FLOWCHART_NODE_TYPE_MEMORY,
        "action": action,
        "action_results": action_results,
        "mcp_server_keys": list(mcp_server_keys),
        "attachments": attachment_entries,
        "retrieved_memories": retrieved,
        "stored_memory": stored_memory,
    }
    route_key = str(node_config.get("route_key") or "").strip()
    routing_state: dict[str, Any] = {}
    if route_key:
        routing_state["route_key"] = route_key
    return output_state, routing_state


def _execute_flowchart_flowchart_node(
    *,
    node_ref_id: int | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    target_flowchart_id = _parse_optional_int(node_ref_id, default=0, minimum=0)
    if target_flowchart_id <= 0:
        raise ValueError("Flowchart node requires ref_id.")

    target_flowchart_name = f"Flowchart {target_flowchart_id}"
    queued_run_id: int | None = None
    with session_scope() as session:
        target_flowchart = session.get(Flowchart, target_flowchart_id)
        if target_flowchart is None:
            raise ValueError(f"Flowchart {target_flowchart_id} was not found.")
        target_flowchart_name = target_flowchart.name or target_flowchart_name
        queued_run = FlowchartRun.create(
            session,
            flowchart_id=target_flowchart_id,
            status="queued",
        )
        queued_run_id = queued_run.id

    try:
        async_result = run_flowchart.delay(target_flowchart_id, int(queued_run_id))
    except Exception as exc:
        logger.exception(
            "Failed to queue flowchart %s from flowchart node",
            target_flowchart_id,
        )
        with session_scope() as session:
            queued_run = session.get(FlowchartRun, queued_run_id)
            if queued_run is not None:
                queued_run.status = "failed"
                queued_run.finished_at = _utcnow()
        raise ValueError(
            f"Failed to queue flowchart {target_flowchart_id}: {exc}"
        ) from exc

    with session_scope() as session:
        queued_run = session.get(FlowchartRun, queued_run_id)
        if queued_run is not None:
            queued_run.celery_task_id = async_result.id

    return (
        {
            "node_type": FLOWCHART_NODE_TYPE_FLOWCHART,
            "triggered_flowchart_id": target_flowchart_id,
            "triggered_flowchart_name": target_flowchart_name,
            "triggered_flowchart_run_id": queued_run_id,
            "triggered_flowchart_celery_task_id": async_result.id,
            "message": f"Queued flowchart {target_flowchart_id}.",
        },
        {},
    )


def _rag_context_text(entries: object, *, edge_label: str) -> str:
    if not isinstance(entries, list):
        return ""
    context_lines: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        output_state = entry.get("output_state")
        text = ""
        if isinstance(output_state, dict):
            for key in ("answer", "raw_output", "message"):
                value = output_state.get(key)
                if isinstance(value, str) and value.strip():
                    text = value.strip()
                    break
            if not text:
                text = _json_dumps(_json_safe(output_state))
        elif isinstance(output_state, str):
            text = output_state.strip()
        elif output_state is not None:
            text = _json_dumps(_json_safe(output_state))
        if not text:
            continue
        node_id = _parse_optional_int(
            entry.get("node_id"),
            default=0,
            minimum=0,
        )
        prefix = f"[node {node_id}] " if node_id > 0 else ""
        context_lines.append(f"{prefix}{text[:2000]}")
    if not context_lines:
        return ""
    return f"{edge_label} connector context:\n" + "\n\n".join(context_lines)


def _build_flowchart_rag_query_prompt(
    *,
    question_prompt: str,
    input_context: dict[str, Any],
) -> str:
    parts: list[str] = [question_prompt.strip()]
    solid_text = _rag_context_text(
        input_context.get("upstream_nodes"),
        edge_label="Solid",
    )
    if solid_text:
        parts.append(solid_text)
    dotted_text = _rag_context_text(
        input_context.get("dotted_upstream_nodes"),
        edge_label="Dotted",
    )
    if dotted_text:
        parts.append(dotted_text)
    return "\n\n".join(part for part in parts if part).strip()


def _execute_flowchart_rag_node(
    *,
    node_id: int,
    node_config: dict[str, Any],
    input_context: dict[str, Any],
    execution_id: int,
    default_model_id: int | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    mode = str(node_config.get("mode") or "").strip().lower()
    if mode not in {
        RAG_FLOWCHART_MODE_FRESH_INDEX,
        RAG_FLOWCHART_MODE_DELTA_INDEX,
        RAG_FLOWCHART_MODE_QUERY,
    }:
        raise ValueError(
            "RAG node config.mode must be fresh_index, delta_index, or query."
        )

    collections = normalize_rag_collection_selection(node_config.get("collections"))
    if not collections:
        raise ValueError("RAG node requires at least one selected collection.")

    model = None
    is_quick_rag_run = str(input_context.get("kind") or "").strip().lower() == "rag_quick_run"
    if is_quick_rag_run:
        model_provider = _normalize_quick_rag_model_provider(node_config.get("model_provider"))
    else:
        with session_scope() as session:
            node = session.get(FlowchartNode, node_id)
            if node is None:
                raise ValueError(f"Flowchart node {node_id} was not found.")
            model = _resolve_node_model(
                session,
                node=node,
                default_model_id=default_model_id,
            )
        model_provider = str(model.provider or "").strip().lower()
    model_id = getattr(model, "id", None)
    model_name = str(getattr(model, "name", "") or "")
    if mode in {RAG_FLOWCHART_MODE_FRESH_INDEX, RAG_FLOWCHART_MODE_DELTA_INDEX}:
        if model_provider not in {"codex", "gemini"}:
            raise ValueError(
                "RAG index modes require an embedding-capable model provider (codex or gemini)."
            )
        index_summary = run_index_for_collections(
            mode=mode,
            collections=collections,
            model_provider=model_provider,
        )
        output_state = {
            "node_type": FLOWCHART_NODE_TYPE_RAG,
            "answer": None,
            "retrieval_context": [],
            "retrieval_stats": {
                "provider": "chroma",
                "retrieved_count": 0,
                "top_k": 0,
                "source_count": int(index_summary.get("source_count") or 0),
                "total_files": int(index_summary.get("total_files") or 0),
                "total_chunks": int(index_summary.get("total_chunks") or 0),
            },
            "synthesis_error": None,
            "mode": mode,
            "collections": collections,
            "index_summary": index_summary,
            "model_id": model_id,
            "model_name": model_name,
            "model_provider": model_provider,
        }
        return output_state, {}

    question_prompt = str(node_config.get("question_prompt") or "").strip()
    if not question_prompt:
        raise ValueError("RAG query mode requires config.question_prompt.")
    query_text = _build_flowchart_rag_query_prompt(
        question_prompt=question_prompt,
        input_context=input_context,
    )
    top_k = _parse_optional_int(
        node_config.get("top_k"),
        default=5,
        minimum=1,
    )
    if top_k is None:
        top_k = 5
    top_k = min(top_k, 20)

    flowchart_payload = (
        input_context.get("flowchart")
        if isinstance(input_context.get("flowchart"), dict)
        else {}
    )
    flowchart_run_id = _parse_optional_int(
        flowchart_payload.get("run_id"),
        default=0,
        minimum=0,
    )
    if flowchart_run_id <= 0:
        flowchart_run_id = None
    request_id = (
        f"flowchart-{flowchart_run_id}-node-{node_id}-run-{execution_id}"
        if flowchart_run_id is not None
        else f"flowchart-node-{node_id}-run-{execution_id}"
    )

    def _synthesize_answer(
        question: str,
        retrieval_context: list[dict[str, Any]],
    ) -> str | None:
        config = load_rag_config()
        if not rag_has_chat_api_key(config):
            raise RuntimeError(
                rag_missing_api_key_message(
                    rag_get_chat_provider(config),
                    "RAG query synthesis",
                )
            )
        context_text = "\n\n".join(
            str(item.get("text") or "").strip()
            for item in retrieval_context
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        )
        max_context_chars = int(getattr(config, "chat_max_context_chars", 12000) or 12000)
        if max_context_chars > 0 and len(context_text) > max_context_chars:
            context_text = context_text[:max_context_chars]
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a helpful assistant for flowchart RAG query synthesis. "
                    "Use retrieval context when available and be explicit when uncertain."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Answer the question using retrieval context.\n\n"
                    f"Question: {question}\n\n"
                    "Retrieval Context:\n"
                    f"{context_text or '(no retrieval context)'}"
                ),
            },
        ]
        return rag_call_chat_completion(config, messages)

    query_result = execute_query_contract(
        question=query_text,
        collections=collections,
        top_k=top_k,
        request_id=request_id,
        runtime_kind="flowchart",
        flowchart_run_id=flowchart_run_id,
        flowchart_node_run_id=execution_id,
        synthesize_answer=_synthesize_answer,
    )
    output_state = {
        "node_type": FLOWCHART_NODE_TYPE_RAG,
        **query_result,
        "model_id": model_id,
        "model_name": model_name,
        "model_provider": model_provider,
    }
    return output_state, {}


def _execute_executor_agent_task_node(
    *,
    node_config: dict[str, Any],
    execution_task_id: int | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    explicit_task_id = _parse_optional_int(
        node_config.get("agent_task_id"),
        default=0,
        minimum=0,
    )
    target_task_id = explicit_task_id if explicit_task_id > 0 else int(execution_task_id or 0)
    if target_task_id <= 0:
        raise ValueError("Executor agent task payload is missing task_id.")

    _execute_agent_task(target_task_id, celery_task_id=None)

    with session_scope() as session:
        task = session.get(AgentTask, target_task_id)
        if task is None:
            raise ValueError(f"Agent task {target_task_id} was not found.")
        task_status = str(task.status or "").strip().lower()
        task_kind = str(task.kind or "").strip()
        task_output = str(task.output or "")
        task_error = str(task.error or "").strip()
        task_stage = str(task.current_stage or "").strip()

    if task_status != "succeeded":
        raise RuntimeError(
            task_error or f"Agent task {target_task_id} failed with status '{task_status}'."
        )

    return (
        {
            "node_type": EXECUTOR_NODE_TYPE_AGENT_TASK,
            "task_id": int(target_task_id),
            "task_kind": task_kind,
            "task_status": task_status,
            "task_output": task_output,
            "task_stage": task_stage,
        },
        {},
    )


def _execute_flowchart_node(
    *,
    node_id: int,
    node_type: str,
    node_ref_id: int | None,
    node_config: dict[str, Any],
    input_context: dict[str, Any],
    execution_id: int,
    execution_task_id: int | None,
    execution_index: int,
    enabled_providers: set[str],
    default_model_id: int | None,
    mcp_server_keys: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    # Node config contract is documented in docs/guides/flowchart-node-config.md.
    if node_type == FLOWCHART_NODE_TYPE_START:
        return (
            {
                "node_type": FLOWCHART_NODE_TYPE_START,
                "message": "Start node executed.",
            },
            {},
        )
    if node_type == FLOWCHART_NODE_TYPE_END:
        return (
            {
                "node_type": FLOWCHART_NODE_TYPE_END,
                "message": "End node reached. Flowchart run completed.",
            },
            {"terminate_run": True},
        )
    if node_type == FLOWCHART_NODE_TYPE_FLOWCHART:
        return _execute_flowchart_flowchart_node(
            node_ref_id=node_ref_id,
        )
    if node_type == FLOWCHART_NODE_TYPE_TASK:
        return _execute_flowchart_task_node(
            node_id=node_id,
            node_ref_id=node_ref_id,
            node_config=node_config,
            input_context=input_context,
            execution_id=execution_id,
            execution_task_id=execution_task_id,
            enabled_providers=enabled_providers,
            default_model_id=default_model_id,
        )
    if node_type == EXECUTOR_NODE_TYPE_AGENT_TASK:
        return _execute_executor_agent_task_node(
            node_config=node_config,
            execution_task_id=execution_task_id,
        )
    if node_type == FLOWCHART_NODE_TYPE_RAG:
        return _execute_flowchart_rag_node(
            node_id=node_id,
            node_config=node_config,
            input_context=input_context,
            execution_id=execution_id,
            default_model_id=default_model_id,
        )
    if node_type == FLOWCHART_NODE_TYPE_DECISION:
        return _execute_flowchart_decision_node(
            node_config=node_config,
            input_context=input_context,
            mcp_server_keys=mcp_server_keys,
        )
    if node_type == FLOWCHART_NODE_TYPE_PLAN:
        return _execute_flowchart_plan_node(
            node_id=node_id,
            node_ref_id=node_ref_id,
            node_config=node_config,
            input_context=input_context,
            enabled_providers=enabled_providers,
            default_model_id=default_model_id,
            mcp_server_keys=mcp_server_keys,
        )
    if node_type == FLOWCHART_NODE_TYPE_MILESTONE:
        return _execute_flowchart_milestone_node(
            node_id=node_id,
            node_ref_id=node_ref_id,
            node_config=node_config,
            input_context=input_context,
            execution_index=execution_index,
            enabled_providers=enabled_providers,
            default_model_id=default_model_id,
            mcp_server_keys=mcp_server_keys,
        )
    if node_type == FLOWCHART_NODE_TYPE_MEMORY:
        return _execute_flowchart_memory_node(
            node_id=node_id,
            node_ref_id=node_ref_id,
            node_config=node_config,
            input_context=input_context,
            mcp_server_keys=mcp_server_keys,
        )
    raise ValueError(f"Unsupported flowchart node type '{node_type}'.")


def _execute_flowchart_node_request(
    request: ExecutionRequest,
) -> tuple[dict[str, Any], dict[str, Any]]:
    init_engine(Config.SQLALCHEMY_DATABASE_URI)
    init_db()
    return _execute_flowchart_node(
        node_id=request.node_id,
        node_type=request.node_type,
        node_ref_id=request.node_ref_id,
        node_config=request.node_config,
        input_context=request.input_context,
        execution_id=request.execution_id,
        execution_task_id=request.execution_task_id,
        execution_index=request.execution_index,
        enabled_providers=request.enabled_providers,
        default_model_id=request.default_model_id,
        mcp_server_keys=request.mcp_server_keys,
    )


def _queue_followup_flowchart_run(
    *,
    flowchart_id: int,
    source_run_id: int,
) -> tuple[int | None, bool]:
    skipped_for_stop = False
    with session_scope() as session:
        source_run = session.get(FlowchartRun, source_run_id)
        if source_run is not None and source_run.status in {"stopping", "stopped", "canceled"}:
            skipped_for_stop = True
            return None, skipped_for_stop
        next_run = FlowchartRun.create(
            session,
            flowchart_id=flowchart_id,
            status="queued",
        )
        next_run_id = next_run.id
    try:
        run_flowchart.delay(flowchart_id, next_run_id)
    except Exception:
        logger.exception(
            "Flowchart run %s failed queuing follow-up run for flowchart %s",
            source_run_id,
            flowchart_id,
        )
        with session_scope() as session:
            queued_run = session.get(FlowchartRun, next_run_id)
            if queued_run is not None and queued_run.status == "queued":
                queued_run.status = "failed"
                queued_run.finished_at = _utcnow()
        return None, skipped_for_stop
    return next_run_id, skipped_for_stop


@celery_app.task(bind=True)
def run_flowchart(self, flowchart_id: int, run_id: int) -> None:
    init_engine(Config.SQLALCHEMY_DATABASE_URI)
    init_db()

    rag_precheck_failure: tuple[int, str] | None = None
    with session_scope() as session:
        run = session.get(FlowchartRun, run_id)
        if run is None:
            logger.warning("Flowchart run %s not found", run_id)
            return
        if run.flowchart_id != flowchart_id:
            logger.warning(
                "Flowchart run %s does not belong to flowchart %s",
                run_id,
                flowchart_id,
            )
            run.status = "failed"
            run.finished_at = _utcnow()
            return
        if run.status == "canceled":
            run.finished_at = run.finished_at or _utcnow()
            return
        if run.status == "stopped":
            run.finished_at = run.finished_at or _utcnow()
            return
        if run.status == "stopping":
            run.status = "stopped"
            run.finished_at = run.finished_at or _utcnow()
            return
        flowchart = (
            session.execute(
                select(Flowchart)
                .options(
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.mcp_servers),
                    selectinload(Flowchart.edges),
                )
                .where(Flowchart.id == flowchart_id)
            )
            .scalars()
            .first()
        )
        if flowchart is None:
            run.status = "failed"
            run.finished_at = _utcnow()
            return
        run.celery_task_id = self.request.id
        run.status = "running"
        run.started_at = run.started_at or _utcnow()
        _emit_flowchart_run_event(
            "flowchart.run.updated",
            run=run,
            flowchart_id=flowchart_id,
            payload={"transition": "started"},
        )

        node_specs: dict[int, dict[str, Any]] = {}
        for node in list(flowchart.nodes):
            node_specs[node.id] = {
                "id": node.id,
                "node_type": node.node_type,
                "ref_id": node.ref_id,
                "config": _parse_json_object(node.config_json),
                "mcp_server_keys": [server.server_key for server in list(node.mcp_servers)],
            }

        outgoing_by_source: dict[int, list[dict[str, Any]]] = {}
        incoming_by_target: dict[int, list[dict[str, Any]]] = {}
        for edge in sorted(list(flowchart.edges), key=lambda item: item.id):
            edge_mode = _normalize_flowchart_edge_mode(edge.edge_mode)
            outgoing_by_source.setdefault(edge.source_node_id, []).append(
                {
                    "id": edge.id,
                    "source_node_id": edge.source_node_id,
                    "target_node_id": edge.target_node_id,
                    "edge_mode": edge_mode,
                    "condition_key": edge.condition_key,
                }
            )
            incoming_by_target.setdefault(edge.target_node_id, []).append(
                {
                    "id": edge.id,
                    "source_node_id": edge.source_node_id,
                    "target_node_id": edge.target_node_id,
                    "edge_mode": edge_mode,
                    "condition_key": edge.condition_key,
                }
            )

        start_nodes = [
            node_id
            for node_id, spec in node_specs.items()
            if spec["node_type"] == FLOWCHART_NODE_TYPE_START
        ]
        if len(start_nodes) != 1:
            run.status = "failed"
            run.finished_at = _utcnow()
            return
        start_node_id = start_nodes[0]
        max_node_executions = flowchart.max_node_executions
        max_runtime_minutes = flowchart.max_runtime_minutes
        max_parallel_nodes = _parse_optional_int(
            flowchart.max_parallel_nodes,
            default=1,
            minimum=1,
        )
        rag_node_ids = sorted(
            node_id
            for node_id, spec in node_specs.items()
            if str(spec.get("node_type") or "").strip().lower()
            == FLOWCHART_NODE_TYPE_RAG
        )
        if rag_node_ids:
            rag_health = rag_runtime_health_snapshot()
            rag_health_state = str(rag_health.get("state") or "").strip().lower()
            if rag_health_state != RAG_HEALTH_CONFIGURED_HEALTHY:
                message = (
                    "RAG pre-run validation failed: integration state is "
                    f"'{rag_health_state or 'unknown'}'."
                )
                run.status = "failed"
                run.finished_at = _utcnow()
                _emit_flowchart_run_event(
                    "flowchart.run.updated",
                    run=run,
                    flowchart_id=flowchart_id,
                    payload={
                        "transition": "failed_precheck",
                        "failure_message": message,
                    },
                )
                rag_precheck_failure = (int(rag_node_ids[0]), message)

    if rag_precheck_failure is not None:
        failed_node_id, failure_message = rag_precheck_failure
        _record_flowchart_guardrail_failure(
            flowchart_id=flowchart_id,
            run_id=run_id,
            node_id=failed_node_id,
            node_type=FLOWCHART_NODE_TYPE_RAG,
            node_ref_id=None,
            execution_index=1,
            total_execution_count=0,
            incoming_edges=incoming_by_target.get(failed_node_id, []),
            latest_results={},
            upstream_results=[],
            message=failure_message,
        )
        return

    llm_settings = load_integration_settings("llm")
    enabled_providers = resolve_enabled_llm_providers(llm_settings)
    default_model_id = resolve_default_model_id(llm_settings)
    node_executor_runtime_settings = load_node_executor_runtime_settings()
    execution_router = ExecutionRouter(runtime_settings=node_executor_runtime_settings)

    node_execution_counts: dict[int, int] = {}
    latest_results: dict[int, dict[str, Any]] = {}
    total_execution_count = 0
    incoming_parent_ids: dict[int, list[int]] = {}
    parent_tokens_by_target: dict[int, dict[int, deque[dict[str, Any]]]] = {}
    for node_id in node_specs:
        parent_ids = sorted(
            {
                int(edge["source_node_id"])
                for edge in incoming_by_target.get(node_id, [])
                if _edge_is_solid(edge)
            }
        )
        incoming_parent_ids[node_id] = parent_ids
        parent_tokens_by_target[node_id] = {
            parent_id: deque() for parent_id in parent_ids
        }
    ready_queue: deque[dict[str, Any]] = deque(
        [{"node_id": start_node_id, "upstream_results": []}]
    )
    started_monotonic = time.monotonic()
    final_status = "completed"
    failure_message: str | None = None
    terminate_run = False

    while ready_queue:
        with session_scope() as session:
            run = session.get(FlowchartRun, run_id)
            if run is None:
                return
            if run.status == "canceled":
                run.finished_at = run.finished_at or _utcnow()
                return
            if run.status == "stopping":
                final_status = "stopped"
                break

        if max_runtime_minutes is not None:
            elapsed_minutes = (time.monotonic() - started_monotonic) / 60.0
            if elapsed_minutes > float(max_runtime_minutes):
                next_activation = ready_queue[0]
                next_node_id_raw = _parse_optional_int(
                    next_activation.get("node_id"),
                    default=0,
                    minimum=0,
                )
                next_node_id = next_node_id_raw if next_node_id_raw > 0 else None
                next_node_spec = node_specs.get(next_node_id)
                if next_node_spec is not None:
                    execution_index = node_execution_counts.get(next_node_id, 0) + 1
                    failure_message = (
                        f"Flowchart exceeded max_runtime_minutes ({max_runtime_minutes})."
                    )
                    _record_flowchart_guardrail_failure(
                        flowchart_id=flowchart_id,
                        run_id=run_id,
                        node_id=next_node_id,
                        node_type=str(next_node_spec["node_type"]),
                        node_ref_id=_parse_optional_int(
                            next_node_spec.get("ref_id"), default=0, minimum=0
                        )
                        or None,
                        execution_index=execution_index,
                        total_execution_count=total_execution_count,
                        incoming_edges=incoming_by_target.get(next_node_id, []),
                        latest_results=latest_results,
                        upstream_results=list(next_activation.get("upstream_results") or []),
                        message=failure_message,
                    )
                final_status = "failed"
                break

        batch_size = min(max_parallel_nodes, len(ready_queue))
        batch: list[dict[str, Any]] = [
            ready_queue.popleft() for _ in range(batch_size)
        ]

        for activation in batch:
            with session_scope() as session:
                run = session.get(FlowchartRun, run_id)
                if run is None:
                    return
                if run.status == "canceled":
                    run.finished_at = run.finished_at or _utcnow()
                    return
                if run.status == "stopping":
                    final_status = "stopped"
                    break

            node_id = _parse_optional_int(
                activation.get("node_id"),
                default=0,
                minimum=0,
            )
            if node_id <= 0:
                failure_message = "Flowchart activation referenced an invalid node id."
                final_status = "failed"
                break
            node_spec = node_specs.get(node_id)
            if node_spec is None:
                failure_message = f"Flowchart referenced missing node id {node_id}."
                final_status = "failed"
                break

            execution_index = node_execution_counts.get(node_id, 0) + 1
            if max_node_executions is not None and total_execution_count >= max_node_executions:
                failure_message = (
                    f"Flowchart exceeded max_node_executions ({max_node_executions})."
                )
                _record_flowchart_guardrail_failure(
                    flowchart_id=flowchart_id,
                    run_id=run_id,
                    node_id=node_id,
                    node_type=str(node_spec["node_type"]),
                    node_ref_id=_parse_optional_int(
                        node_spec.get("ref_id"), default=0, minimum=0
                    )
                    or None,
                    execution_index=execution_index,
                    total_execution_count=total_execution_count,
                    incoming_edges=incoming_by_target.get(node_id, []),
                    latest_results=latest_results,
                    upstream_results=list(activation.get("upstream_results") or []),
                    message=failure_message,
                )
                final_status = "failed"
                break
            if total_execution_count >= 10000:
                failure_message = "Flowchart exceeded hard safety limit (10000 node executions)."
                _record_flowchart_guardrail_failure(
                    flowchart_id=flowchart_id,
                    run_id=run_id,
                    node_id=node_id,
                    node_type=str(node_spec["node_type"]),
                    node_ref_id=_parse_optional_int(
                        node_spec.get("ref_id"), default=0, minimum=0
                    )
                    or None,
                    execution_index=execution_index,
                    total_execution_count=total_execution_count,
                    incoming_edges=incoming_by_target.get(node_id, []),
                    latest_results=latest_results,
                    upstream_results=list(activation.get("upstream_results") or []),
                    message=failure_message,
                )
                final_status = "failed"
                break

            total_execution_count += 1
            node_execution_counts[node_id] = execution_index

            input_context = _build_flowchart_input_context(
                flowchart_id=flowchart_id,
                run_id=run_id,
                node_id=node_id,
                node_type=str(node_spec["node_type"]),
                execution_index=execution_index,
                total_execution_count=total_execution_count,
                incoming_edges=incoming_by_target.get(node_id, []),
                latest_results=latest_results,
                upstream_results=list(activation.get("upstream_results") or []),
            )
            node_config = node_spec.get("config") or {}
            node_agent_id: int | None = None
            if str(node_spec["node_type"]) == FLOWCHART_NODE_TYPE_TASK:
                parsed_agent_id = _parse_optional_int(
                    node_config.get("agent_id"),
                    default=0,
                    minimum=0,
                )
                if parsed_agent_id > 0:
                    node_agent_id = parsed_agent_id

            routed_execution_request: ExecutionRequest | None = None
            execution_result = None
            node_task_id: int | None = None
            runtime_evidence: dict[str, Any] = {}
            with session_scope() as session:
                node_run_started_at = _utcnow()
                node_task = _create_flowchart_node_task(
                    session,
                    flowchart_id=flowchart_id,
                    run_id=run_id,
                    node_id=node_id,
                    node_type=str(node_spec["node_type"]),
                    node_ref_id=_parse_optional_int(
                        node_spec.get("ref_id"), default=0, minimum=0
                    )
                    or None,
                    agent_id=node_agent_id,
                    execution_index=execution_index,
                    input_context=input_context,
                    status="running",
                    started_at=node_run_started_at,
                )
                node_task_id = node_task.id
                node_run = FlowchartRunNode.create(
                    session,
                    flowchart_run_id=run_id,
                    flowchart_node_id=node_id,
                    execution_index=execution_index,
                    agent_task_id=node_task.id,
                    status="running",
                    input_context_json=_json_dumps(input_context),
                    started_at=node_run_started_at,
                )
                node_run_id = node_run.id
                execution_request = ExecutionRequest(
                    node_id=node_id,
                    node_type=str(node_spec["node_type"]),
                    node_ref_id=node_spec.get("ref_id"),
                    node_config=node_config,
                    input_context=input_context,
                    execution_id=node_run_id,
                    execution_task_id=node_task_id,
                    execution_index=execution_index,
                    enabled_providers=enabled_providers,
                    default_model_id=default_model_id,
                    mcp_server_keys=list(node_spec.get("mcp_server_keys") or []),
                )
                routed_execution_request = execution_router.route_request(execution_request)
                _apply_flowchart_node_task_run_metadata(
                    node_task,
                    routed_execution_request.run_metadata_payload(),
                )
                runtime_payload = routed_execution_request.run_metadata_payload()
                _emit_task_event(
                    "node.task.updated",
                    task=node_task,
                    payload={
                        "transition": "started",
                        "execution_index": execution_index,
                        "flowchart_node_run_id": node_run_id,
                    },
                    runtime_override=runtime_payload,
                )
                _emit_flowchart_node_event(
                    "flowchart.node.updated",
                    flowchart_id=flowchart_id,
                    flowchart_run_id=run_id,
                    flowchart_node_id=node_id,
                    node_type=str(node_spec["node_type"]),
                    status="running",
                    execution_index=execution_index,
                    node_run_id=node_run_id,
                    agent_task_id=node_task_id,
                    started_at=node_run_started_at,
                    runtime=runtime_payload,
                )

            try:
                if routed_execution_request is None:
                    raise RuntimeError("Execution request routing did not initialize.")
                execution_result = execution_router.execute_routed(
                    routed_execution_request,
                    _execute_flowchart_node_request,
                )
                runtime_payload = (
                    execution_result.run_metadata
                    if isinstance(execution_result.run_metadata, dict)
                    else routed_execution_request.run_metadata_payload()
                )
                runtime_evidence = _runtime_evidence_payload(
                    run_metadata=runtime_payload,
                    provider_metadata=(
                        execution_result.provider_metadata
                        if isinstance(execution_result.provider_metadata, dict)
                        else None
                    ),
                    error=execution_result.error if isinstance(execution_result.error, dict) else None,
                    terminal_status=execution_result.status,
                )
                if execution_result.status != "success":
                    failure_error = execution_result.error
                    failure_message = (
                        str(failure_error.get("message") or "").strip()
                        if isinstance(failure_error, dict)
                        else ""
                    )
                    if not failure_message:
                        failure_message = (
                            f"Execution failed with status '{execution_result.status}'."
                        )
                    raise RuntimeError(failure_message)
                output_state = (
                    dict(execution_result.output_state)
                    if isinstance(execution_result.output_state, dict)
                    else {}
                )
                routing_state = (
                    dict(execution_result.routing_state)
                    if isinstance(execution_result.routing_state, dict)
                    else {}
                )
                if runtime_evidence:
                    routing_state["runtime_evidence"] = runtime_evidence
                    output_state["runtime_evidence"] = runtime_evidence
            except Exception as exc:
                logger.exception(
                    "Flowchart run %s failed in node %s (%s)",
                    run_id,
                    node_id,
                    node_spec.get("node_type"),
                )
                with session_scope() as session:
                    finished_at = _utcnow()
                    failed_node_run = session.get(FlowchartRunNode, node_run_id)
                    if failed_node_run is not None:
                        failed_node_run.status = "failed"
                        failed_node_run.error = str(exc)
                        failed_node_run.finished_at = finished_at
                    runtime_payload = (
                        execution_result.run_metadata
                        if execution_result is not None
                        else (
                            routed_execution_request.run_metadata_payload()
                            if routed_execution_request is not None
                            else None
                        )
                    )
                    runtime_evidence = _runtime_evidence_payload(
                        run_metadata=runtime_payload,
                        provider_metadata=(
                            execution_result.provider_metadata
                            if execution_result is not None
                            and isinstance(execution_result.provider_metadata, dict)
                            else None
                        ),
                        error=(
                            execution_result.error
                            if execution_result is not None
                            and isinstance(execution_result.error, dict)
                            else {"message": str(exc)}
                        ),
                        terminal_status="failed",
                    )
                    if failed_node_run is not None:
                        failed_node_run.routing_state_json = _json_dumps(
                            {"runtime_evidence": runtime_evidence}
                        )
                    _update_flowchart_node_task(
                        session,
                        node_run=failed_node_run,
                        status="failed",
                        error=str(exc),
                        finished_at=finished_at,
                        run_metadata=runtime_payload,
                    )
                    failed_task = None
                    if (
                        failed_node_run is not None
                        and failed_node_run.agent_task_id is not None
                    ):
                        failed_task = session.get(AgentTask, failed_node_run.agent_task_id)
                    if failed_task is not None:
                        _emit_task_event(
                            "node.task.completed",
                            task=failed_task,
                            payload={
                                "terminal_status": "failed",
                                "failure_message": str(exc),
                                "flowchart_node_run_id": node_run_id,
                                "execution_index": failed_node_run.execution_index
                                if failed_node_run is not None
                                else execution_index,
                                "runtime_evidence": runtime_evidence,
                            },
                            runtime_override=runtime_payload,
                        )
                    _emit_flowchart_node_event(
                        "flowchart.node.updated",
                        flowchart_id=flowchart_id,
                        flowchart_run_id=run_id,
                        flowchart_node_id=node_id,
                        node_type=str(node_spec["node_type"]),
                        status="failed",
                        execution_index=(
                            failed_node_run.execution_index
                            if failed_node_run is not None
                            else execution_index
                        ),
                        node_run_id=node_run_id,
                        agent_task_id=(
                            failed_node_run.agent_task_id
                            if failed_node_run is not None
                            else node_task_id
                        ),
                        error=str(exc),
                        started_at=(
                            failed_node_run.started_at
                            if failed_node_run is not None
                            else None
                        ),
                        finished_at=finished_at,
                        routing_state={"runtime_evidence": runtime_evidence},
                        runtime=runtime_payload,
                    )
                    run = session.get(FlowchartRun, run_id)
                    if run is not None and run.status != "canceled":
                        run.status = "failed"
                        run.finished_at = _utcnow()
                        _emit_flowchart_run_event(
                            "flowchart.run.updated",
                            run=run,
                            flowchart_id=flowchart_id,
                            payload={
                                "transition": "failed",
                                "failure_message": str(exc),
                            },
                        )
                return

            latest_results[node_id] = {
                "node_type": node_spec.get("node_type"),
                "execution_index": execution_index,
                "sequence": total_execution_count,
                "output_state": output_state,
                "routing_state": routing_state,
            }

            with session_scope() as session:
                finished_at = _utcnow()
                succeeded_node_run = session.get(FlowchartRunNode, node_run_id)
                if succeeded_node_run is not None:
                    succeeded_node_run.status = "succeeded"
                    succeeded_node_run.output_state_json = _json_dumps(output_state)
                    succeeded_node_run.routing_state_json = _json_dumps(routing_state)
                    skill_ids = output_state.get("resolved_skill_ids")
                    if isinstance(skill_ids, list):
                        succeeded_node_run.resolved_skill_ids_json = _json_dumps(skill_ids)
                    skill_versions = output_state.get("resolved_skill_versions")
                    if isinstance(skill_versions, list):
                        succeeded_node_run.resolved_skill_versions_json = _json_dumps(
                            skill_versions
                        )
                    manifest_hash = output_state.get("resolved_skill_manifest_hash")
                    if isinstance(manifest_hash, str) and manifest_hash.strip():
                        succeeded_node_run.resolved_skill_manifest_hash = manifest_hash
                    adapter_mode = output_state.get("skill_adapter_mode")
                    if isinstance(adapter_mode, str) and adapter_mode.strip():
                        succeeded_node_run.skill_adapter_mode = adapter_mode
                    resolved_role_id = output_state.get("resolved_role_id")
                    if isinstance(resolved_role_id, int):
                        succeeded_node_run.resolved_role_id = resolved_role_id
                    resolved_role_version = output_state.get("resolved_role_version")
                    if (
                        isinstance(resolved_role_version, str)
                        and resolved_role_version.strip()
                    ):
                        succeeded_node_run.resolved_role_version = resolved_role_version
                    resolved_agent_id = output_state.get("resolved_agent_id")
                    if isinstance(resolved_agent_id, int):
                        succeeded_node_run.resolved_agent_id = resolved_agent_id
                    resolved_agent_version = output_state.get("resolved_agent_version")
                    if (
                        isinstance(resolved_agent_version, str)
                        and resolved_agent_version.strip()
                    ):
                        succeeded_node_run.resolved_agent_version = resolved_agent_version
                    instruction_manifest_hash = output_state.get("instruction_manifest_hash")
                    if (
                        isinstance(instruction_manifest_hash, str)
                        and instruction_manifest_hash.strip()
                    ):
                        succeeded_node_run.resolved_instruction_manifest_hash = (
                            instruction_manifest_hash
                        )
                    instruction_adapter_mode = output_state.get("instruction_adapter_mode")
                    if (
                        isinstance(instruction_adapter_mode, str)
                        and instruction_adapter_mode.strip()
                    ):
                        succeeded_node_run.instruction_adapter_mode = (
                            instruction_adapter_mode
                        )
                    instruction_materialized_paths = output_state.get(
                        "instruction_materialized_paths"
                    )
                    if isinstance(instruction_materialized_paths, list):
                        succeeded_node_run.instruction_materialized_paths_json = _json_dumps(
                            instruction_materialized_paths
                        )
                    succeeded_node_run.finished_at = finished_at
                _update_flowchart_node_task(
                    session,
                    node_run=succeeded_node_run,
                    status="succeeded",
                    output_state=output_state,
                    finished_at=finished_at,
                    run_metadata=(
                        execution_result.run_metadata
                        if execution_result is not None
                        else (
                            routed_execution_request.run_metadata_payload()
                            if routed_execution_request is not None
                            else None
                        )
                    ),
                )
                runtime_payload = (
                    execution_result.run_metadata
                    if execution_result is not None
                    else (
                        routed_execution_request.run_metadata_payload()
                        if routed_execution_request is not None
                        else None
                    )
                )
                succeeded_task = None
                if (
                    succeeded_node_run is not None
                    and succeeded_node_run.agent_task_id is not None
                ):
                    succeeded_task = session.get(
                        AgentTask, succeeded_node_run.agent_task_id
                    )
                if succeeded_task is not None:
                    _emit_task_event(
                        "node.task.completed",
                        task=succeeded_task,
                        payload={
                            "terminal_status": "succeeded",
                            "flowchart_node_run_id": node_run_id,
                            "execution_index": succeeded_node_run.execution_index,
                            "runtime_evidence": runtime_evidence,
                        },
                        runtime_override=runtime_payload,
                    )
                _emit_flowchart_node_event(
                    "flowchart.node.updated",
                    flowchart_id=flowchart_id,
                    flowchart_run_id=run_id,
                    flowchart_node_id=node_id,
                    node_type=str(node_spec["node_type"]),
                    status="succeeded",
                    execution_index=(
                        succeeded_node_run.execution_index
                        if succeeded_node_run is not None
                        else execution_index
                    ),
                    node_run_id=node_run_id,
                    agent_task_id=(
                        succeeded_node_run.agent_task_id
                        if succeeded_node_run is not None
                        else node_task_id
                    ),
                    output_state=output_state,
                    routing_state=routing_state,
                    started_at=(
                        succeeded_node_run.started_at
                        if succeeded_node_run is not None
                        else None
                    ),
                    finished_at=finished_at,
                    runtime=runtime_payload,
                )

            if _coerce_bool(routing_state.get("terminate_run")):
                terminate_run = True
                break

            try:
                selected_edges = _resolve_flowchart_outgoing_edges(
                    node_type=str(node_spec["node_type"]),
                    node_config=node_spec.get("config") or {},
                    outgoing_edges=outgoing_by_source.get(node_id, []),
                    routing_state=routing_state,
                )
            except Exception as exc:
                logger.exception(
                    "Flowchart route resolution failed for run %s node %s",
                    run_id,
                    node_id,
                )
                with session_scope() as session:
                    run = session.get(FlowchartRun, run_id)
                    if run is not None and run.status != "canceled":
                        run.status = "failed"
                        run.finished_at = _utcnow()
                    failed_node_run = (
                        session.execute(
                            select(FlowchartRunNode)
                            .where(
                                FlowchartRunNode.flowchart_run_id == run_id,
                                FlowchartRunNode.flowchart_node_id == node_id,
                            )
                            .order_by(FlowchartRunNode.id.desc())
                        )
                        .scalars()
                        .first()
                    )
                    if failed_node_run is not None:
                        failed_node_run.error = str(exc)
                    _update_flowchart_node_task(
                        session,
                        node_run=failed_node_run,
                        status=failed_node_run.status if failed_node_run is not None else "failed",
                        error=str(exc),
                        finished_at=failed_node_run.finished_at if failed_node_run is not None else None,
                    )
                    failed_task = None
                    if (
                        failed_node_run is not None
                        and failed_node_run.agent_task_id is not None
                    ):
                        failed_task = session.get(AgentTask, failed_node_run.agent_task_id)
                    if failed_task is not None:
                        _emit_task_event(
                            "node.task.completed",
                            task=failed_task,
                            payload={
                                "terminal_status": str(failed_task.status),
                                "failure_message": str(exc),
                                "flowchart_node_run_id": failed_node_run.id
                                if failed_node_run is not None
                                else None,
                                "execution_index": failed_node_run.execution_index
                                if failed_node_run is not None
                                else execution_index,
                            },
                        )
                    _emit_flowchart_node_event(
                        "flowchart.node.updated",
                        flowchart_id=flowchart_id,
                        flowchart_run_id=run_id,
                        flowchart_node_id=node_id,
                        node_type=str(node_spec["node_type"]),
                        status=(
                            failed_node_run.status
                            if failed_node_run is not None
                            else "failed"
                        ),
                        execution_index=(
                            failed_node_run.execution_index
                            if failed_node_run is not None
                            else execution_index
                        ),
                        node_run_id=(
                            failed_node_run.id if failed_node_run is not None else None
                        ),
                        agent_task_id=(
                            failed_node_run.agent_task_id
                            if failed_node_run is not None
                            else node_task_id
                        ),
                        error=str(exc),
                        started_at=(
                            failed_node_run.started_at
                            if failed_node_run is not None
                            else None
                        ),
                        finished_at=(
                            failed_node_run.finished_at
                            if failed_node_run is not None
                            else None
                        ),
                        runtime=(
                            _task_runtime_metadata(failed_task)
                            if failed_task is not None
                            else None
                        ),
                    )
                    if run is not None:
                        _emit_flowchart_run_event(
                            "flowchart.run.updated",
                            run=run,
                            flowchart_id=flowchart_id,
                            payload={
                                "transition": "failed",
                                "failure_message": str(exc),
                            },
                        )
                return

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Flowchart run %s node %s (%s) selected %s solid trigger edge(s): %s",
                    run_id,
                    node_id,
                    node_spec.get("node_type"),
                    len(selected_edges),
                    [
                        {
                            "edge_id": int(edge.get("id") or 0),
                            "target_node_id": int(edge.get("target_node_id") or 0),
                            "edge_mode": _normalize_flowchart_edge_mode(edge.get("edge_mode")),
                        }
                        for edge in selected_edges
                    ],
                )

            emitted = {
                "source_node_id": node_id,
                "node_type": node_spec.get("node_type"),
                "execution_index": execution_index,
                "sequence": total_execution_count,
                "output_state": output_state,
                "routing_state": routing_state,
            }
            for edge in selected_edges:
                target_node_id = int(edge["target_node_id"])
                if target_node_id == start_node_id:
                    next_run_id, skipped_followup = _queue_followup_flowchart_run(
                        flowchart_id=flowchart_id,
                        source_run_id=run_id,
                    )
                    if skipped_followup:
                        logger.info(
                            "Flowchart run %s reached Start with stop requested; skipped follow-up run.",
                            run_id,
                        )
                        terminate_run = True
                    elif next_run_id is None:
                        failure_message = (
                            "Flowchart reached Start node but failed to queue a follow-up run."
                        )
                        final_status = "failed"
                    else:
                        logger.info(
                            "Flowchart run %s reached Start; queued follow-up run %s.",
                            run_id,
                            next_run_id,
                        )
                        terminate_run = True
                    break
                parent_ids = incoming_parent_ids.get(target_node_id, [])
                token = {
                    **emitted,
                    "source_edge_id": int(edge["id"]),
                    "condition_key": edge.get("condition_key"),
                    "edge_mode": _normalize_flowchart_edge_mode(edge.get("edge_mode")),
                }
                if not parent_ids:
                    ready_queue.append(
                        {
                            "node_id": target_node_id,
                            "upstream_results": [token],
                        }
                    )
                    continue
                parent_tokens = parent_tokens_by_target.setdefault(target_node_id, {})
                for parent_id in parent_ids:
                    parent_tokens.setdefault(parent_id, deque())
                parent_tokens.setdefault(node_id, deque()).append(token)
                while all(len(parent_tokens[parent_id]) > 0 for parent_id in parent_ids):
                    upstream_results = [
                        parent_tokens[parent_id].popleft() for parent_id in parent_ids
                    ]
                    ready_queue.append(
                        {
                            "node_id": target_node_id,
                            "upstream_results": upstream_results,
                        }
                    )
            if final_status == "failed" or terminate_run:
                break

        if final_status in {"failed", "stopped"}:
            break
        if terminate_run:
            final_status = "completed"
            break

    with session_scope() as session:
        run = session.get(FlowchartRun, run_id)
        if run is None:
            return
        if run.status == "canceled":
            run.finished_at = run.finished_at or _utcnow()
            return
        if run.status == "stopping" and final_status == "completed":
            final_status = "stopped"
        if final_status == "failed" and failure_message:
            logger.error(
                "Flowchart run %s failed: %s",
                run_id,
                failure_message,
            )
        run.status = final_status
        run.finished_at = _utcnow()
        _emit_flowchart_run_event(
            "flowchart.run.updated",
            run=run,
            flowchart_id=flowchart_id,
            payload={
                "transition": "completed",
                "failure_message": failure_message if final_status == "failed" else None,
            },
        )
