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
from core.config import Config
from core.db import init_db, init_engine, session_scope
from services.integrations import (
    LLM_PROVIDER_LABELS,
    LLM_PROVIDERS,
    load_integration_settings,
    resolve_default_model_id,
    resolve_enabled_llm_providers,
    resolve_llm_provider,
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
    SCRIPT_TYPE_SKILL,
    TaskTemplate,
)
from storage.script_storage import ensure_script_file
from core.task_stages import TASK_STAGE_LABELS, TASK_STAGE_ORDER
from core.task_kinds import is_quick_task_kind
from core.quick_node import (
    build_quick_node_agent_profile,
    build_quick_node_system_contract,
)

logger = logging.getLogger(__name__)

OUTPUT_INSTRUCTIONS_ONE_OFF = "Do not ask follow-up questions. This is a one-off task."
OUTPUT_INSTRUCTIONS_MARKDOWN = (
    "If Markdown is used, ensure it is valid CommonMark "
    "(for example: balanced code fences and valid link syntax)."
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
    ignore_failure: bool = False,
) -> None:
    result = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        env=os.environ.copy(),
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
            ignore_failure=True,
        )
        add_cmd = _build_gemini_mcp_add_cmd(server_key, configs[server_key], scope)
        debug_enabled = _as_optional_bool(configs[server_key].get("debug"))
        if on_log and debug_enabled:
            on_log(f"Gemini MCP add: {_format_cmd_for_log(add_cmd)}")
        _run_config_cmd(add_cmd, on_log=on_log, cwd=cwd)
        if on_log and debug_enabled:
            _log_gemini_settings(server_key, scope, cwd, on_log)


def _build_task_workspace(task_id: int) -> Path:
    return Path(Config.WORKSPACES_DIR) / f"task-{task_id}"


def _codex_homes_root() -> Path:
    return Path(Config.DATA_DIR) / "codex-homes"


def _build_task_codex_home(task_id: int) -> Path:
    return _codex_homes_root() / f"task-{task_id}"


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
            known_hosts_path = Path(Config.DATA_DIR) / "known_hosts"
            ssh_cmd = [
                "ssh",
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
            env["GIT_SSH_COMMAND"] = " ".join(ssh_cmd)
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


def _build_agent_payload(
    agent: Agent,
    include_autoprompt: bool = True,
) -> dict[str, object]:
    description = agent.description or agent.name or ""
    payload: dict[str, object] = {
        "id": agent.id,
        "name": agent.name,
        "description": description,
    }
    if include_autoprompt and agent.autonomous_prompt:
        payload["autoprompt"] = agent.autonomous_prompt
    return payload


def _build_agent_prompt_payload(
    agent: Agent,
    include_autoprompt: bool = True,
) -> dict[str, object]:
    agent_payload = _build_agent_payload(
        agent,
        include_autoprompt=include_autoprompt,
    )
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


def _build_run_prompt_payload(agent: Agent) -> str:
    envelope = build_prompt_envelope(
        user_request=agent.autonomous_prompt or "",
        system_contract=_build_system_contract(agent),
        agent_profile=_build_agent_payload(agent, include_autoprompt=False),
        task_context={"kind": "autorun"},
        output_contract=_build_output_contract(),
    )
    return serialize_prompt_envelope(envelope)


def _render_prompt(agent: Agent) -> str:
    envelope = build_prompt_envelope(
        user_request=agent.autonomous_prompt or "",
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


def _format_script_prompt(prompt: str, script_entries: list[dict[str, str]]) -> str:
    if not script_entries:
        return prompt
    if "Available helper scripts:" in prompt:
        return prompt
    lines = ["Available helper scripts:"]
    for entry in script_entries:
        path = entry.get("path") or entry.get("file_name") or "script"
        description = entry.get("description") or "No description provided."
        lines.append(f"- {path}: {description}")
    block = "\n".join(lines)
    if not prompt.strip():
        return block
    return f"{block}\n\n{prompt}"


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


def _inject_script_map(
    prompt: str,
    script_entries: list[dict[str, str]],
    task_kind: str | None,
) -> str:
    if not script_entries:
        return prompt
    payload = _load_prompt_dict(prompt)
    if payload is not None and is_prompt_envelope(payload):
        task_context = _ensure_task_context(payload)
        task_context["kind"] = task_kind or task_context.get("kind") or "task"
        existing = task_context.get("skill_scripts")
        if isinstance(existing, list):
            merged = _merge_attachment_entries(existing, script_entries)
            task_context["skill_scripts"] = merged
        else:
            task_context["skill_scripts"] = script_entries
        return serialize_prompt_envelope(payload)
    stripped = prompt.strip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            agent_payload = payload.get("agent")
            has_agent_scripts = (
                isinstance(agent_payload, dict) and "scripts" in agent_payload
            )
            has_scripts_field = "scripts" in payload
            prompt_value = payload.get("prompt")
            if isinstance(prompt_value, str):
                if has_agent_scripts or has_scripts_field:
                    return prompt
                payload["prompt"] = _format_script_prompt(
                    prompt_value,
                    script_entries,
                )
                return json.dumps(payload, indent=2, sort_keys=True)
            if has_agent_scripts or has_scripts_field:
                return prompt
            payload["scripts"] = script_entries
            return json.dumps(payload, indent=2, sort_keys=True)
    return _format_script_prompt(prompt, script_entries)


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
    task_template: TaskTemplate | None,
) -> dict[str, dict[str, Any]]:
    task_servers = list(task.mcp_servers)
    template_servers = list(task_template.mcp_servers) if task_template else []
    selected_servers = task_servers if task_servers else template_servers
    configs = _build_mcp_config_map(selected_servers)
    configs["llmctl-mcp"] = _build_builtin_llmctl_mcp_config()
    return configs


def _first_available_model_id(session) -> int | None:
    return session.execute(
        select(LLMModel.id).order_by(LLMModel.created_at.desc()).limit(1)
    ).scalar_one_or_none()


def _builtin_llmctl_mcp_run_path() -> Path:
    return Path(__file__).resolve().parents[4] / "app" / "llmctl-mcp" / "run.py"


def _build_builtin_llmctl_mcp_config() -> dict[str, Any]:
    run_path = _builtin_llmctl_mcp_run_path()
    if not run_path.is_file():
        raise ValueError(f"Required llmctl-mcp runner is missing: {run_path}")
    return {
        "command": "python3",
        "args": [str(run_path)],
        "env": {"LLMCTL_MCP_TRANSPORT": "stdio"},
    }


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
        codex_settings = _codex_settings_from_model_config(model_config or {})
        mcp_overrides = _build_mcp_overrides_from_configs(mcp_configs)
        codex_overrides = _build_codex_overrides(codex_settings)
        cmd = _build_codex_cmd(
            mcp_overrides=mcp_overrides,
            codex_overrides=codex_overrides,
            model=codex_settings.get("model"),
        )
    elif provider == "gemini":
        gemini_settings = _gemini_settings_from_model_config(model_config or {})
        _ensure_gemini_mcp_servers(mcp_configs, on_log=on_log, cwd=cwd)
        if gemini_settings.get("sandbox") is not None:
            env = dict(env or os.environ)
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


def _run_llmctl_mcp_stdio_preflight(
    mcp_configs: dict[str, dict[str, Any]],
    on_log: Callable[[str], None] | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> None:
    config = mcp_configs.get("llmctl-mcp")
    if not config:
        return
    command = config.get("command")
    if not command:
        if on_log:
            on_log("MCP preflight skipped: llmctl-mcp has no command configured.")
        return
    args = _extract_list_config(config.get("args"), "args")
    repo_root = Path(__file__).resolve().parents[4]
    smoke_test = repo_root / "app" / "llmctl-mcp" / "scripts" / "stdio_smoke_test.py"
    if not smoke_test.exists():
        raise RuntimeError(f"MCP preflight missing: {smoke_test}")
    tool_args = json.dumps({"limit": 1, "order_by": "id"})
    cmd = [
        "python3",
        str(smoke_test),
        "--timeout",
        "8",
        "--tool-name",
        "llmctl_get_flowchart",
        "--tool-args",
        tool_args,
        "--",
        str(command),
        *args,
    ]
    if on_log:
        on_log(f"MCP preflight (llmctl-mcp): {_format_cmd_for_log(cmd)}")
    result = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        env=env or os.environ.copy(),
        cwd=str(cwd) if cwd is not None else None,
    )
    if result.stdout.strip() and on_log:
        on_log(result.stdout.rstrip())
    if result.stderr.strip() and on_log:
        on_log(result.stderr.rstrip())
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(
            message or f"MCP preflight failed with code {result.returncode}."
        )


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
        task.output = output
        task.error = error
        if stage is not None:
            task.current_stage = stage
        if stage_logs is not None:
            task.stage_logs = stage_logs


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
def run_agent_task(self, task_id: int) -> None:
    _execute_agent_task(task_id, celery_task_id=self.request.id)


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
    template_scripts: list[Script] = []
    task_scripts: list[Script] = []
    task_attachments: list[Attachment] = []
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
        task_template: TaskTemplate | None = None
        if task.task_template_id is not None:
            task_template = (
                session.execute(
                    select(TaskTemplate)
                    .options(
                        selectinload(TaskTemplate.mcp_servers),
                        selectinload(TaskTemplate.scripts),
                    )
                    .where(TaskTemplate.id == task.task_template_id)
                )
                .scalars()
                .first()
            )
            if task_template is None:
                now = _utcnow()
                task.status = "failed"
                task.error = "Task template not found."
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

        model: LLMModel | None = None
        selected_model_id: int | None = None
        if task.model_id is not None:
            selected_model_id = task.model_id
        elif task_template is not None and task_template.model_id is not None:
            selected_model_id = task_template.model_id
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
        template_scripts = list(task_template.scripts) if task_template else []
        task_scripts = list(task.scripts)
        task_attachments = list(task.attachments)
        ordered_scripts: list[Script] = []
        seen_script_ids: set[int] = set()
        for script in template_scripts + task_scripts:
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
        agent_profile = (
            _build_agent_payload(agent, include_autoprompt=False)
            if agent is not None
            else None
        )
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
        task.prompt = payload
        try:
            mcp_configs = _build_task_mcp_configs(task, task_template)
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
        list[Script],
    ]:
        pre_init: list[Script] = []
        init: list[Script] = []
        post_init: list[Script] = []
        post_run: list[Script] = []
        skill: list[Script] = []
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
            elif script.script_type == SCRIPT_TYPE_SKILL:
                skill.append(script)
            else:
                unknown.append(script)
        return pre_init, init, post_init, post_run, skill, unknown

    (
        pre_init_scripts,
        init_scripts,
        post_init_scripts,
        post_run_scripts,
        skill_scripts,
        unknown_scripts,
    ) = _split_scripts(ordered_scripts)
    combined_scripts = ordered_scripts

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
    codex_home: Path | None = None
    script_entries: list[dict[str, str]] = []
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
                task.finished_at = now
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
            if workspace is None and combined_scripts:
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
                if skill_scripts:
                    skill_entries = [
                        {
                            "path": entry["path"],
                            "description": entry["description"],
                            "file_name": entry["file_name"],
                        }
                        for entry in script_entries
                        if entry.get("script_type") == SCRIPT_TYPE_SKILL
                    ]
                    if skill_entries:
                        updated_payload = _inject_script_map(
                            payload,
                            skill_entries,
                            task_kind,
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
            if workspace is not None:
                llm_env["WORKSPACE_PATH"] = str(workspace)
                llm_env["LLMCTL_STUDIO_WORKSPACE"] = str(workspace)
            if provider == "codex":
                seed_codex_home = _resolve_codex_home_from_env(llm_env)
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
                claude_api_key = _load_claude_auth_key()
                if claude_api_key:
                    llm_env["ANTHROPIC_API_KEY"] = claude_api_key
            if provider == "gemini" and "llmctl-mcp" in mcp_configs:
                _append_task_log("Running MCP stdio preflight for llmctl-mcp...")
                _run_llmctl_mcp_stdio_preflight(
                    mcp_configs,
                    on_log=_append_task_log,
                    cwd=workspace,
                    env=llm_env,
                )
            _append_task_log(f"Launching {provider_label}...")
            result = _run_llm(
                provider,
                payload,
                mcp_configs=mcp_configs,
                model_config=model_config,
                on_update=_persist_logs,
                on_log=_append_task_log,
                cwd=workspace,
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
                return
            task.status = "failed" if final_failed else "succeeded"
            task.finished_at = now
            task.error = "".join(log_prefix_chunks) + last_error
            task.current_stage = current_stage
            task.stage_logs = _serialize_stage_logs()
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


def _split_scripts_by_stage(
    scripts: list[Script],
) -> tuple[
    list[Script],
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
    skill: list[Script] = []
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
        elif script.script_type == SCRIPT_TYPE_SKILL:
            skill.append(script)
        else:
            unknown.append(script)
    return pre_init, init, post_init, post_run, skill, unknown


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
) -> AgentTask:
    parsed_ref_id = _parse_optional_int(node_ref_id, default=0, minimum=0)
    task_template_id: int | None = None
    if node_type == FLOWCHART_NODE_TYPE_TASK and parsed_ref_id > 0:
        task_template_id = parsed_ref_id
    return AgentTask.create(
        session,
        agent_id=agent_id,
        task_template_id=task_template_id,
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


def _update_flowchart_node_task(
    session,
    *,
    node_run: FlowchartRunNode | None,
    status: str,
    output_state: dict[str, Any] | None = None,
    error: str | None = None,
    finished_at: datetime | None = None,
) -> None:
    if node_run is None or node_run.agent_task_id is None:
        return
    task = session.get(AgentTask, node_run.agent_task_id)
    if task is None:
        return
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
        FlowchartRunNode.create(
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


def _resolve_node_model(
    session,
    *,
    node: FlowchartNode,
    template: TaskTemplate | None = None,
    default_model_id: int | None = None,
) -> LLMModel:
    model_id: int | None = node.model_id
    if model_id is None and template is not None:
        model_id = template.model_id
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
) -> Any:
    provider = model.provider
    if provider not in LLM_PROVIDERS:
        raise ValueError(f"Unknown model provider: {provider}.")
    if provider not in enabled_providers:
        raise ValueError(f"Provider disabled: {provider}.")
    model_config = _parse_model_config(model.config_json)
    result = _run_llm(
        provider,
        prompt,
        mcp_configs=mcp_configs,
        model_config=model_config,
        on_update=None,
        on_log=None,
        cwd=None,
        env=os.environ.copy(),
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
    selected_agent_name: str | None = None
    selected_agent_profile: dict[str, object] | None = None
    selected_system_contract: dict[str, object] | None = None
    selected_agent_source: str | None = None
    with session_scope() as session:
        node = (
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
        if node is None:
            raise ValueError(f"Flowchart node {node_id} was not found.")
        task_template: TaskTemplate | None = None
        if node_ref_id is not None:
            task_template = (
                session.execute(
                    select(TaskTemplate)
                    .options(
                        selectinload(TaskTemplate.attachments),
                        selectinload(TaskTemplate.scripts),
                    )
                    .where(TaskTemplate.id == node_ref_id)
                )
                .scalars()
                .first()
            )
            if task_template is None:
                raise ValueError(f"Task template {node_ref_id} was not found.")
        model = _resolve_node_model(
            session,
            node=node,
            template=task_template,
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
        elif task_template is not None and task_template.agent_id is not None:
            selected_agent_id = int(task_template.agent_id)
            selected_agent_source = "template"
        if selected_agent_id is not None:
            selected_agent = session.get(Agent, selected_agent_id)
            if selected_agent is None:
                raise ValueError(f"Agent {selected_agent_id} was not found.")
            selected_agent_name = selected_agent.name
            selected_agent_profile = _build_agent_payload(
                selected_agent,
                include_autoprompt=False,
            )
            selected_system_contract = _build_system_contract(selected_agent)
        mcp_servers = list(node.mcp_servers)
        template_scripts = list(task_template.scripts) if task_template is not None else []
        node_scripts = list(node.scripts)
        attachments = list(task_template.attachments) if task_template is not None else []

    provider = model.provider
    if provider not in LLM_PROVIDERS:
        raise ValueError(f"Unknown model provider: {provider}.")
    if provider not in enabled_providers:
        raise ValueError(f"Provider disabled: {provider}.")
    model_config = _parse_model_config(model.config_json)
    mcp_configs = _build_mcp_config_map(mcp_servers)
    mcp_configs["llmctl-mcp"] = _build_builtin_llmctl_mcp_config()

    ordered_scripts: list[Script] = []
    seen_script_ids: set[int] = set()
    for script in template_scripts + node_scripts:
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
        _skill_scripts,
        unknown_scripts,
    ) = _split_scripts_by_stage(ordered_scripts)

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
    elif task_template is not None:
        base_prompt = task_template.prompt or ""
        prompt_source = "template"
    else:
        raise ValueError(
            "Task node requires either config.task_prompt or ref_id to a task template."
        )
    if not base_prompt.strip():
        raise ValueError(
            "Task node prompt is empty. Provide config.task_prompt or select a template with a prompt."
        )

    resolved_task_name = (
        inline_task_name
        or (task_template.name if task_template is not None else None)
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
    task_template_id = task_template.id if task_template is not None else None
    task_template_name = task_template.name if task_template is not None else None

    payload = _build_task_payload("flowchart", base_prompt)
    payload_dict = _load_prompt_dict(payload)
    if payload_dict is not None and is_prompt_envelope(payload_dict):
        task_context = _ensure_task_context(payload_dict)
        task_context["kind"] = "flowchart"
        flowchart_context: dict[str, Any] = {
            "node_id": node_id,
            "input_context": input_context,
        }
        if task_template_id is not None:
            flowchart_context["task_template_id"] = task_template_id
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
    payload = _inject_attachments(payload, _build_attachment_entries(attachments))
    payload = _inject_runtime_metadata(payload, _build_runtime_payload(provider, model_config))

    workspace: Path | None = None
    staging_dir: Path | None = None
    codex_home: Path | None = None
    script_entries: list[dict[str, str]] = []
    llm_result: subprocess.CompletedProcess[str] | None = None

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
        if ordered_scripts:
            workspace = _build_task_workspace(execution_id)
            workspace.mkdir(parents=True, exist_ok=True)
            scripts_dir = workspace / SCRIPTS_DIRNAME
            script_entries = _materialize_scripts(
                ordered_scripts,
                scripts_dir,
                on_log=_append_script_log,
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
        if workspace is not None:
            llm_env["WORKSPACE_PATH"] = str(workspace)
            llm_env["LLMCTL_STUDIO_WORKSPACE"] = str(workspace)
        if provider == "codex":
            seed_codex_home = _resolve_codex_home_from_env(llm_env)
            codex_home = _prepare_task_codex_home(execution_id, seed_home=seed_codex_home)
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
            claude_api_key = _load_claude_auth_key()
            if claude_api_key:
                llm_env["ANTHROPIC_API_KEY"] = claude_api_key

        _set_stage("llm_query")
        _append_script_log(f"Launching {_provider_label(provider)}...")
        llm_result = _run_llm(
            provider,
            payload,
            mcp_configs=mcp_configs,
            model_config=model_config,
            on_update=_capture_llm_updates,
            on_log=_append_script_log,
            cwd=workspace,
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
        "task_template_id": task_template_id,
        "task_template_name": task_template_name,
        "agent_id": selected_agent_id,
        "agent_name": selected_agent_name,
        "agent_source": selected_agent_source,
        "provider": provider,
        "model_id": model.id,
        "model_name": model.name,
        "mcp_server_keys": [server.server_key for server in mcp_servers],
        "integration_keys": (
            sorted(selected_integration_keys)
            if selected_integration_keys is not None
            else None
        ),
        "script_ids": [script.id for script in ordered_scripts],
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
                    template=None,
                    default_model_id=default_model_id,
                )
                llm_patch = _execute_optional_llm_transform(
                    prompt=transform_prompt,
                    model=model,
                    enabled_providers=enabled_providers,
                    mcp_configs=_build_mcp_config_map(list(node.mcp_servers)),
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
                    template=None,
                    default_model_id=default_model_id,
                )
                llm_patch = _execute_optional_llm_transform(
                    prompt=transform_prompt,
                    model=model,
                    enabled_providers=enabled_providers,
                    mcp_configs=_build_mcp_config_map(list(node.mcp_servers)),
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

    with session_scope() as session:
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
    # Node config contract is documented in planning/guides/flowchart-node-config.md.
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
            node_ref_id=node_ref_id,
            node_config=node_config,
            input_context=input_context,
            mcp_server_keys=mcp_server_keys,
        )
    raise ValueError(f"Unsupported flowchart node type '{node_type}'.")


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

    llm_settings = load_integration_settings("llm")
    enabled_providers = resolve_enabled_llm_providers(llm_settings)
    default_model_id = resolve_default_model_id(llm_settings)

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

            try:
                output_state, routing_state = _execute_flowchart_node(
                    node_id=node_id,
                    node_type=str(node_spec["node_type"]),
                    node_ref_id=node_spec.get("ref_id"),
                    node_config=node_config,
                    input_context=input_context,
                    execution_id=node_run_id,
                    execution_task_id=node_task.id,
                    execution_index=execution_index,
                    enabled_providers=enabled_providers,
                    default_model_id=default_model_id,
                    mcp_server_keys=list(node_spec.get("mcp_server_keys") or []),
                )
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
                    _update_flowchart_node_task(
                        session,
                        node_run=failed_node_run,
                        status="failed",
                        error=str(exc),
                        finished_at=finished_at,
                    )
                    run = session.get(FlowchartRun, run_id)
                    if run is not None and run.status != "canceled":
                        run.status = "failed"
                        run.finished_at = _utcnow()
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
                    succeeded_node_run.finished_at = finished_at
                _update_flowchart_node_task(
                    session,
                    node_run=succeeded_node_run,
                    status="succeeded",
                    output_state=output_state,
                    finished_at=finished_at,
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
