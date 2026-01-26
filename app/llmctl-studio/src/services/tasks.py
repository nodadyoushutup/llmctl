from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import selectors
import subprocess
import time
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
from core.models import (
    Agent,
    AgentTask,
    Attachment,
    IntegrationSetting,
    LLMModel,
    MCPServer,
    Pipeline,
    PipelineRun,
    PipelineStep,
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

logger = logging.getLogger(__name__)

OUTPUT_INSTRUCTIONS_ONE_OFF = "Do not ask follow-up questions. This is a one-off task."


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
    stripped = prompt.strip()
    if not stripped.startswith("{"):
        return prompt
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return prompt
    if not isinstance(payload, dict):
        return prompt
    payload["runtime"] = runtime
    return json.dumps(payload, indent=2, sort_keys=True)


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
    if Config.CODEX_SKIP_GIT_REPO_CHECK:
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


def _build_agent_scripts_payload(scripts: list[Script]) -> dict[str, object] | None:
    if not scripts:
        return None
    grouped = {
        "pre_init": [],
        "init": [],
        "post_init": [],
        "post_run": [],
        "skill": [],
    }
    for script in scripts:
        path = script.file_path or script.file_name
        entry = {
            "description": script.description or "",
            "path": path,
        }
        if script.script_type == SCRIPT_TYPE_PRE_INIT:
            grouped["pre_init"].append(entry)
        elif script.script_type == SCRIPT_TYPE_INIT:
            grouped["init"].append(entry)
        elif script.script_type == SCRIPT_TYPE_POST_INIT:
            grouped["post_init"].append(entry)
        elif script.script_type == SCRIPT_TYPE_POST_RUN:
            grouped["post_run"].append(entry)
        elif script.script_type == SCRIPT_TYPE_SKILL:
            grouped["skill"].append(entry)
    payload: dict[str, object] = {
        "description": (
            "Scripts attached to this agent. Skill scripts are available to the LLM as needed; "
            "other scripts are for reference."
        ),
    }
    payload.update(grouped)
    return payload


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
    stripped = prompt.strip()
    payload: dict[str, object] | None = None
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            payload = parsed
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
    payload: dict[str, object] = {"description": description}
    if include_autoprompt and agent.autonomous_prompt:
        payload["autoprompt"] = agent.autonomous_prompt
    scripts_payload = _build_agent_scripts_payload(list(agent.scripts))
    if scripts_payload:
        payload["scripts"] = scripts_payload
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


def _build_run_prompt_payload(agent: Agent) -> str:
    payload: dict[str, object] = {
        "prompt": agent.autonomous_prompt or "",
        "output_instructions": OUTPUT_INSTRUCTIONS_ONE_OFF,
        "agent": _build_agent_prompt_payload(agent, include_autoprompt=False),
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _render_prompt(agent: Agent) -> str:
    if agent.autonomous_prompt:
        return agent.autonomous_prompt
    if agent.role_id:
        role = agent.role
        if role is not None:
            combined = {
                "role": _build_role_payload(role),
                "agent": _build_agent_payload(agent),
            }
            return json.dumps(combined, indent=2, sort_keys=True)
    return json.dumps(_build_agent_payload(agent), indent=2, sort_keys=True)


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
    return is_quick_task_kind(task_kind) or task_kind == "pipeline"


def _inject_github_repo(
    prompt: str,
    repo: str,
    task_kind: str | None,
    workspace: Path | str | None = None,
) -> str:
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


def _inject_agent_payload(
    prompt: str,
    agent_payload: dict[str, object] | None,
    task_kind: str | None,
) -> str:
    if task_kind != "pipeline" or not agent_payload:
        return prompt
    stripped = prompt.strip()
    if not stripped.startswith("{"):
        return prompt
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return prompt
    if not isinstance(payload, dict) or "agent" in payload:
        return prompt
    payload["agent"] = agent_payload
    return json.dumps(payload, indent=2, sort_keys=True)


def _build_pipeline_prompt_payload(
    session,
    pipeline_id: int,
    pipeline_run_id: int,
    pipeline_step_id: int | None,
) -> dict[str, object] | None:
    pipeline = session.get(Pipeline, pipeline_id)
    if pipeline is None:
        return None
    steps = (
        session.execute(
            select(PipelineStep, TaskTemplate)
            .join(TaskTemplate, PipelineStep.task_template_id == TaskTemplate.id)
            .where(PipelineStep.pipeline_id == pipeline_id)
            .order_by(PipelineStep.step_order.asc(), PipelineStep.id.asc())
            .options(
                selectinload(PipelineStep.attachments),
                selectinload(TaskTemplate.attachments),
            )
        )
        .all()
    )
    if not steps:
        return None
    tasks = (
        session.execute(
            select(AgentTask)
            .options(selectinload(AgentTask.attachments))
            .where(
                AgentTask.pipeline_run_id == pipeline_run_id,
                AgentTask.pipeline_id == pipeline_id,
                AgentTask.pipeline_step_id.is_not(None),
            )
            .order_by(AgentTask.created_at.asc(), AgentTask.id.asc())
        )
        .scalars()
        .all()
    )
    latest_by_step: dict[int, AgentTask] = {}
    attachments_by_step: dict[int, list[dict[str, object]]] = {}
    for task in tasks:
        if task.pipeline_step_id is None:
            continue
        latest_by_step[task.pipeline_step_id] = task
        attachments_by_step[task.pipeline_step_id] = _build_attachment_entries(
            list(task.attachments)
        )
    steps_payload: list[dict[str, object]] = []
    current_step = None
    pipeline_attachments: list[dict[str, object]] = []
    for index, (step, template) in enumerate(steps, start=1):
        task = latest_by_step.get(step.id)
        combined_prompt = _combine_step_prompt(
            template.prompt,
            step.additional_prompt,
        )
        step_attachments = attachments_by_step.get(step.id, [])
        step_attachments = _merge_attachment_entries(
            step_attachments,
            _build_attachment_entries(list(step.attachments)),
        )
        step_attachments = _merge_attachment_entries(
            step_attachments,
            _build_attachment_entries(list(template.attachments)),
        )
        if step_attachments:
            pipeline_attachments = _merge_attachment_entries(
                pipeline_attachments,
                step_attachments,
            )
        step_payload: dict[str, object] = {
            "step_id": step.id,
            "step_order": step.step_order,
            "task_template_id": template.id,
            "prompt": combined_prompt,
            "template_prompt": template.prompt,
            "additional_prompt": step.additional_prompt,
            "output": task.output if task is not None else None,
            "status": task.status if task is not None else "pending",
        }
        if step_attachments:
            step_payload["attachments"] = step_attachments
        steps_payload.append(step_payload)
        if step.id == pipeline_step_id:
            current_step = {
                "step_id": step.id,
                "step_order": step.step_order,
                "index": index,
                "task_template_id": template.id,
            }
    payload: dict[str, object] = {
        "id": pipeline.id,
        "name": pipeline.name,
        "run_id": pipeline_run_id,
        "current_step": current_step,
        "steps": steps_payload,
        "note": (
            "Pipeline steps are included for reference. Each step includes the "
            "template prompt, any additional prompt, and the output from the task "
            "run for that step."
        ),
    }
    if pipeline_attachments:
        payload["attachments"] = pipeline_attachments
    if pipeline.description:
        payload["description"] = pipeline.description
    return payload


def _inject_pipeline_payload(
    prompt: str,
    pipeline_payload: dict[str, object] | None,
    task_kind: str | None,
) -> str:
    if task_kind != "pipeline" or not pipeline_payload:
        return prompt
    stripped = prompt.strip()
    if not stripped.startswith("{"):
        return prompt
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return prompt
    if not isinstance(payload, dict) or "pipeline" in payload:
        return prompt
    payload["pipeline"] = pipeline_payload
    return json.dumps(payload, indent=2, sort_keys=True)


def _append_additional_prompt(prompt: str, additional_prompt: str) -> str:
    addition = additional_prompt.strip()
    if not addition:
        return prompt
    if not prompt:
        return addition
    if prompt.endswith((" ", "\n", "\t")):
        return f"{prompt}{addition}"
    return f"{prompt} {addition}"


def _combine_step_prompt(template_prompt: str, additional_prompt: str | None) -> str:
    if not additional_prompt or not additional_prompt.strip():
        return template_prompt
    stripped = template_prompt.strip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            prompt_value = payload.get("prompt")
            if isinstance(prompt_value, str):
                payload["prompt"] = _append_additional_prompt(
                    prompt_value,
                    additional_prompt,
                )
                return json.dumps(payload, indent=2, sort_keys=True)
    return _append_additional_prompt(template_prompt, additional_prompt)


def _build_integrations_payload(
    workspace: Path | str | None = None,
) -> dict[str, object] | None:
    github_settings = load_integration_settings("github")
    jira_settings = load_integration_settings("jira")
    integrations: dict[str, object] = {}
    repo = (github_settings.get("repo") or "").strip()
    if repo:
        github_payload: dict[str, object] = {"repo": repo}
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
    email = (jira_settings.get("email") or "").strip()
    site = (jira_settings.get("site") or "").strip()
    board = (jira_settings.get("board") or "").strip()
    project_key = (jira_settings.get("project_key") or "").strip()
    if email or site or board or project_key:
        jira_payload: dict[str, object] = {}
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
    stripped = prompt.strip()
    payload: dict[str, object] | None = None
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            payload = parsed
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
    if _should_use_prompt_payload(kind):
        stripped = prompt.strip()
        if stripped.startswith("{"):
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                payload = None
            if (
                isinstance(payload, dict)
                and isinstance(payload.get("prompt"), str)
            ):
                if "output_instructions" not in payload:
                    payload["output_instructions"] = OUTPUT_INSTRUCTIONS_ONE_OFF
                    return json.dumps(payload, indent=2, sort_keys=True)
                return stripped
        return json.dumps(
            {
                "prompt": prompt,
                "output_instructions": OUTPUT_INSTRUCTIONS_ONE_OFF,
            },
            indent=2,
            sort_keys=True,
        )
    return prompt


def _build_agent_mcp_configs(agent: Agent) -> dict[str, dict[str, Any]]:
    return _build_mcp_config_map(agent.mcp_servers)


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
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
    logger.info("Running %s: %s", provider_label, " ".join(cmd))
    return _run_llm_process(cmd, prompt, on_update=on_update, cwd=cwd, env=env)


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
    agent_scripts: list[Script] = []
    task_scripts: list[Script] = []
    task_attachments: list[Attachment] = []
    with session_scope() as session:
        task = session.get(AgentTask, task_id)
        if task is None:
            logger.warning("Task %s not found", task_id)
            return
        if task.status not in {"queued", "running"}:
            return
        if task.pipeline_run_id is not None:
            pipeline_run = session.get(PipelineRun, task.pipeline_run_id)
            if pipeline_run is None:
                now = _utcnow()
                task.status = "canceled"
                task.error = "Pipeline run not found."
                task.started_at = task.started_at or now
                task.finished_at = now
                return
            if pipeline_run.status == "canceled":
                now = _utcnow()
                task.status = "canceled"
                if not task.error:
                    task.error = "Pipeline run canceled."
                task.started_at = task.started_at or now
                task.finished_at = now
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
            if run.status not in RUN_ACTIVE_STATUSES and task.pipeline_run_id is None:
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
            now = _utcnow()
            task.status = "failed"
            task.error = "Agent required."
            task.started_at = now
            task.finished_at = now
            return
        agent = session.get(Agent, task.agent_id)
        if agent is None:
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
        model: LLMModel | None = None
        if agent.model_id is not None:
            model = session.get(LLMModel, agent.model_id)
            if model is None:
                now = _utcnow()
                task.status = "failed"
                task.error = "Model not found."
                task.started_at = now
                task.finished_at = now
                agent.last_run_at = now
                agent.last_error = "Model not found."
                agent.task_id = None
                agent.last_stopped_at = now
                if run is not None:
                    run.last_run_at = now
                    run.last_error = "Model not found."
                    run.status = "error"
                    run.task_id = None
                    run.last_stopped_at = now
                return
        elif default_model_id is not None:
            model = session.get(LLMModel, default_model_id)
            if model is None:
                now = _utcnow()
                task.status = "failed"
                task.error = "Default model not found."
                task.started_at = now
                task.finished_at = now
                agent.last_run_at = now
                agent.last_error = "Default model not found."
                agent.task_id = None
                agent.last_stopped_at = now
                if run is not None:
                    run.last_run_at = now
                    run.last_error = "Default model not found."
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
        if model is not None:
            if model.provider not in LLM_PROVIDERS:
                now = _utcnow()
                task.status = "failed"
                task.error = f"Unknown model provider: {model.provider}."
                task.started_at = now
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
                return
            if model.provider not in enabled_providers:
                now = _utcnow()
                task.status = "failed"
                task.error = f"Provider disabled: {model.provider}."
                task.started_at = now
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
                return
            provider = model.provider
            model_config = _parse_model_config(model.config_json)
        if provider is None:
            now = _utcnow()
            task.status = "failed"
            task.error = "No default provider or model configured."
            task.started_at = now
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
            return
        agent_id = agent.id
        agent_scripts = list(agent.scripts)
        task_scripts = list(task.scripts)
        task_attachments = list(task.attachments)
        for script in agent_scripts + task_scripts:
            path = ensure_script_file(
                script.id,
                script.file_name,
                script.content,
                script.file_path,
            )
            if script.file_path != str(path):
                script.file_path = str(path)
        task.celery_task_id = celery_task_id or task.celery_task_id
        task.status = "running"
        task.started_at = _utcnow()
        prompt = task.prompt
        task_kind = task.kind
        if agent is not None and not prompt and not is_quick_task_kind(task.kind):
            prompt = _render_prompt(agent)
        if prompt is None:
            prompt = ""
        runtime_payload = _build_runtime_payload(provider, model_config)
        repo_value = session.execute(
            select(IntegrationSetting.value).where(
                IntegrationSetting.provider == "github",
                IntegrationSetting.key == "repo",
            )
        ).scalar_one_or_none()
        github_repo = (repo_value or "").strip()
        if github_repo and not is_run_task:
            prompt = _inject_github_repo(prompt, github_repo, task_kind)
        payload = _build_task_payload(task.kind, prompt)
        agent_payload = None
        if task_kind == "pipeline" and agent is not None:
            agent_payload = _build_agent_prompt_payload(
                agent,
                include_autoprompt=False,
            )
        payload = _inject_agent_payload(payload, agent_payload, task_kind)
        pipeline_payload = None
        if (
            task_kind == "pipeline"
            and task.pipeline_id is not None
            and task.pipeline_run_id is not None
        ):
            pipeline_payload = _build_pipeline_prompt_payload(
                session,
                task.pipeline_id,
                task.pipeline_run_id,
                task.pipeline_step_id,
            )
        payload = _inject_pipeline_payload(payload, pipeline_payload, task_kind)
        payload = _inject_integrations(
            payload,
            _build_integrations_payload(),
        )
        payload = _inject_runtime_metadata(payload, runtime_payload)
        attachment_entries = _build_attachment_entries(task_attachments)
        if task_kind == "pipeline" and isinstance(pipeline_payload, dict):
            pipeline_entries = pipeline_payload.get("attachments")
            if isinstance(pipeline_entries, list):
                attachment_entries = _merge_attachment_entries(
                    attachment_entries,
                    pipeline_entries,
                )
        payload = _inject_attachments(
            payload,
            attachment_entries,
            replace_existing=task_kind == "pipeline",
        )
        task.prompt = payload
        if agent is not None:
            try:
                mcp_configs = _build_agent_mcp_configs(agent)
            except ValueError as exc:
                now = _utcnow()
                task.status = "failed"
                task.error = str(exc)
                task.finished_at = now
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
                logger.error("Invalid MCP config for agent %s: %s", agent.id, exc)
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
        task_pre_init,
        task_init,
        task_post_init,
        task_post_run,
        task_skill,
        task_unknown,
    ) = _split_scripts(task_scripts)
    (
        agent_pre_init,
        agent_init,
        agent_post_init,
        agent_post_run,
        agent_skill,
        agent_unknown,
    ) = _split_scripts(agent_scripts)

    pre_init_scripts = task_pre_init + agent_pre_init
    init_scripts = task_init + agent_init
    post_init_scripts = task_post_init + agent_post_init
    post_run_scripts = task_post_run + agent_post_run
    skill_scripts = task_skill + agent_skill
    unknown_scripts = task_unknown + agent_unknown
    combined_scripts = task_scripts + agent_scripts

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
                if github_repo and not is_run_task:
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
                _build_integrations_payload(workspace),
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
            _append_task_log(f"Launching {provider_label}...")
            llm_env = os.environ.copy()
            if workspace is not None:
                llm_env["WORKSPACE_PATH"] = str(workspace)
                llm_env["LLMCTL_STUDIO_WORKSPACE"] = str(workspace)
            if provider == "codex":
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
            if task.pipeline_run_id is not None:
                pipeline_run = session.get(PipelineRun, task.pipeline_run_id)
                if pipeline_run is not None and pipeline_run.status == "canceled":
                    task.status = "canceled"
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
        _cleanup_workspace(task_id, staging_dir, label="script staging")
        _cleanup_workspace(task_id, workspace)


@celery_app.task(bind=True)
def run_pipeline(self, pipeline_id: int, run_id: int | None = None) -> None:
    init_engine(Config.SQLALCHEMY_DATABASE_URI)
    init_db()

    tasks_by_step_id: dict[int, int] = {}

    def _cancel_pipeline_tasks(session, run_id: int, now: datetime) -> None:
        tasks = (
            session.execute(
                select(AgentTask).where(AgentTask.pipeline_run_id == run_id)
            )
            .scalars()
            .all()
        )
        for task in tasks:
            if task.status in {"pending", "queued", "running"}:
                task.status = "canceled"
                if not task.error:
                    task.error = "Canceled by user."
                task.finished_at = now

    with session_scope() as session:
        pipeline = session.get(Pipeline, pipeline_id)
        if pipeline is None:
            logger.warning("Pipeline %s not found", pipeline_id)
            if run_id is not None:
                run = session.get(PipelineRun, run_id)
                if run is not None:
                    run.status = "failed"
                    run.finished_at = _utcnow()
            return
        steps = (
            session.execute(
                select(PipelineStep)
                .options(selectinload(PipelineStep.attachments))
                .where(PipelineStep.pipeline_id == pipeline_id)
                .order_by(PipelineStep.step_order.asc(), PipelineStep.id.asc())
            )
            .scalars()
            .all()
        )
        if not steps:
            logger.warning("Pipeline %s has no steps", pipeline_id)
            if run_id is not None:
                run = session.get(PipelineRun, run_id)
                if run is not None:
                    run.status = "failed"
                    run.finished_at = _utcnow()
            return
        if run_id is None:
            run = PipelineRun.create(
                session,
                pipeline_id=pipeline_id,
                celery_task_id=self.request.id,
                status="running",
                started_at=_utcnow(),
            )
            run_id = run.id
        else:
            run = session.get(PipelineRun, run_id)
            if run is not None:
                if run.status == "canceled":
                    run.finished_at = run.finished_at or _utcnow()
                    return
                run.celery_task_id = self.request.id
                run.status = "running"
                run.started_at = _utcnow()
        step_ids = [step.id for step in steps]
        if step_ids:
            existing_tasks = (
                session.execute(
                    select(AgentTask).where(
                        AgentTask.pipeline_run_id == run_id,
                        AgentTask.pipeline_step_id.in_(step_ids),
                    )
                )
                .scalars()
                .all()
            )
        else:
            existing_tasks = []
        for task in existing_tasks:
            if task.pipeline_step_id is None:
                continue
            tasks_by_step_id[task.pipeline_step_id] = task.id
            if task.run_task_id is None:
                task.run_task_id = self.request.id
        for step in steps:
            if step.id in tasks_by_step_id:
                continue
            template = session.get(TaskTemplate, step.task_template_id)
            prompt = None
            agent_id = None
            if template is not None:
                prompt = _combine_step_prompt(
                    template.prompt,
                    step.additional_prompt,
                )
                agent_id = template.agent_id
            task = AgentTask.create(
                session,
                agent_id=agent_id,
                run_task_id=self.request.id,
                pipeline_id=pipeline_id,
                pipeline_run_id=run_id,
                pipeline_step_id=step.id,
                task_template_id=step.task_template_id,
                status="pending",
                prompt=prompt,
                kind="pipeline",
            )
            if template is not None:
                _attach_task_attachments(
                    task,
                    list(step.attachments) + list(template.attachments),
                )
            tasks_by_step_id[step.id] = task.id

    for step in steps:
        task_id = tasks_by_step_id.get(step.id)
        with session_scope() as session:
            run = session.get(PipelineRun, run_id)
            if run is None:
                return
            if run.status == "canceled":
                now = _utcnow()
                _cancel_pipeline_tasks(session, run_id, now)
                run.finished_at = run.finished_at or now
                return
            template = session.get(TaskTemplate, step.task_template_id)
            if template is None:
                now = _utcnow()
                run = session.get(PipelineRun, run_id)
                if run is not None:
                    run.status = "failed"
                    run.finished_at = now
                if task_id is not None:
                    task = session.get(AgentTask, task_id)
                    if task is not None:
                        task.status = "failed"
                        task.error = "Task template not found."
                        task.started_at = now
                        task.finished_at = now
                return
            if template.agent_id is None:
                now = _utcnow()
                run = session.get(PipelineRun, run_id)
                if run is not None:
                    run.status = "failed"
                    run.finished_at = now
                if task_id is not None:
                    task = session.get(AgentTask, task_id)
                    if task is not None:
                        task.status = "failed"
                        task.error = "Task template missing agent."
                        task.started_at = now
                        task.finished_at = now
                logger.warning(
                    "Task template %s missing agent for pipeline %s step %s",
                    template.id,
                    pipeline_id,
                    step.id,
                )
                return
            step_agent = session.get(Agent, template.agent_id)
            if step_agent is None:
                now = _utcnow()
                run = session.get(PipelineRun, run_id)
                if run is not None:
                    run.status = "failed"
                    run.finished_at = now
                if task_id is not None:
                    task = session.get(AgentTask, task_id)
                    if task is not None:
                        task.status = "failed"
                        task.error = "Agent not found."
                        task.started_at = now
                        task.finished_at = now
                logger.warning(
                    "Agent %s not found for pipeline %s step %s",
                    template.agent_id,
                    pipeline_id,
                    step.id,
                )
                return
            task = session.get(AgentTask, task_id) if task_id is not None else None
            if task is None:
                task = AgentTask.create(
                    session,
                    agent_id=template.agent_id,
                    run_task_id=self.request.id,
                    pipeline_id=pipeline_id,
                    pipeline_run_id=run_id,
                    pipeline_step_id=step.id,
                    task_template_id=template.id,
                    status="queued",
                    prompt=_combine_step_prompt(
                        template.prompt,
                        step.additional_prompt,
                    ),
                    kind="pipeline",
                )
            else:
                if task.agent_id is None:
                    task.agent_id = template.agent_id
                if task.task_template_id is None:
                    task.task_template_id = template.id
                if task.prompt is None:
                    task.prompt = _combine_step_prompt(
                        template.prompt,
                        step.additional_prompt,
                    )
                if task.run_task_id is None:
                    task.run_task_id = self.request.id
                if task.status == "pending":
                    task.status = "queued"
            _attach_task_attachments(
                task,
                list(step.attachments) + list(template.attachments),
            )
            task_id = task.id

        _execute_agent_task(task_id)

        with session_scope() as session:
            task = session.get(AgentTask, task_id)
            run = session.get(PipelineRun, run_id)
            if task is None or run is None:
                return
            if run.status == "canceled":
                now = _utcnow()
                _cancel_pipeline_tasks(session, run_id, now)
                run.finished_at = run.finished_at or now
                return
            if task.status == "failed":
                run.status = "failed"
                run.finished_at = _utcnow()
                return

    should_loop = False
    with session_scope() as session:
        run = session.get(PipelineRun, run_id)
        if run is not None:
            if run.status == "canceled":
                run.finished_at = run.finished_at or _utcnow()
                return
            run.status = "succeeded"
            run.finished_at = _utcnow()
        pipeline = session.get(Pipeline, pipeline_id)
        should_loop = bool(pipeline.loop_enabled) if pipeline is not None else False

    if should_loop:
        with session_scope() as session:
            next_run = PipelineRun.create(
                session,
                pipeline_id=pipeline_id,
                status="queued",
            )
            next_run_id = next_run.id
        run_pipeline.delay(pipeline_id, next_run_id)
