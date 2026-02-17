from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
from typing import Any

from .contracts import (
    CONTRACT_VERSION,
    ERROR_CANCELLED,
    ERROR_EXECUTION,
    ERROR_TIMEOUT,
    ExecutionResult,
    ResultError,
    START_MARKER_EVENT,
    START_MARKER_LITERAL,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_SUCCESS,
    STATUS_TIMEOUT,
    utcnow,
)
from .payload import ExecutionPayload


def _truncate_text(raw: str, *, max_bytes: int) -> str:
    data = (raw or "").encode("utf-8", errors="replace")
    if len(data) <= max_bytes:
        return raw or ""
    clipped = data[:max_bytes].decode("utf-8", errors="ignore")
    return f"{clipped}\n[llmctl-executor] output truncated to {max_bytes} bytes."


def emit_start_markers() -> None:
    now = utcnow().isoformat()
    print(START_MARKER_LITERAL, flush=True)
    print(
        json.dumps(
            {
                "event": START_MARKER_EVENT,
                "contract_version": CONTRACT_VERSION,
                "ts": now,
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        flush=True,
    )


def _provider_metadata_base(
    payload: ExecutionPayload,
    *,
    cwd: str,
    execution_mode: str,
) -> dict[str, Any]:
    provider_metadata: dict[str, Any] = {
        "executor": "llmctl-executor",
        "provider": payload.provider,
        "request_id": payload.request_id,
        "cwd": cwd,
        "emit_start_markers": payload.emit_start_markers,
        "execution_mode": execution_mode,
    }
    if payload.metadata:
        provider_metadata["request_metadata"] = payload.metadata
    return provider_metadata


def _resolve_entrypoint(entrypoint: str) -> Any:
    module_name, _, callable_name = entrypoint.partition(":")
    if not module_name or not callable_name:
        raise ValueError(
            "node_execution.entrypoint must use '<module>:<callable>' format."
        )
    module = importlib.import_module(module_name)
    target = getattr(module, callable_name, None)
    if target is None or not callable(target):
        raise ValueError(f"Entrypoint '{entrypoint}' is not callable.")
    return target


def _normalize_node_request(raw: dict[str, Any]) -> dict[str, Any]:
    payload = dict(raw)
    enabled = payload.get("enabled_providers")
    if isinstance(enabled, list):
        payload["enabled_providers"] = {
            str(item).strip().lower()
            for item in enabled
            if str(item).strip()
        }
    elif not isinstance(enabled, set):
        payload["enabled_providers"] = set()
    mcp_keys = payload.get("mcp_server_keys")
    if isinstance(mcp_keys, set):
        payload["mcp_server_keys"] = sorted(str(item) for item in mcp_keys if str(item).strip())
    elif not isinstance(mcp_keys, list):
        payload["mcp_server_keys"] = []
    return payload


def _execute_node_payload(
    payload: ExecutionPayload,
    *,
    cwd: str,
) -> ExecutionResult:
    started_at = utcnow()
    started_monotonic = time.monotonic()
    node_execution = payload.node_execution
    if node_execution is None:
        raise RuntimeError("node_execution payload is required for in-process mode.")

    previous_dir = os.getcwd()
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    previous_env: dict[str, str | None] = {}
    added_paths: list[str] = []
    output_state: dict[str, Any] | None = None
    routing_state: dict[str, Any] | None = None
    try:
        os.chdir(cwd)
        for key, value in payload.env.items():
            previous_env[key] = os.environ.get(key)
            os.environ[key] = value
        for candidate in node_execution.python_paths:
            if candidate and candidate not in sys.path:
                sys.path.insert(0, candidate)
                added_paths.append(candidate)

        callable_target = _resolve_entrypoint(node_execution.entrypoint)
        request_payload = _normalize_node_request(node_execution.request)
        request_obj = SimpleNamespace(**request_payload)
        with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
            result_value = callable_target(request_obj)
        if not isinstance(result_value, tuple) or len(result_value) != 2:
            raise ValueError(
                "Node execution callable must return (output_state, routing_state)."
            )
        output_raw, routing_raw = result_value
        if not isinstance(output_raw, dict):
            raise ValueError("Node execution output_state must be a JSON object.")
        if not isinstance(routing_raw, dict):
            raise ValueError("Node execution routing_state must be a JSON object.")
        output_state = output_raw
        routing_state = routing_raw
        status = STATUS_SUCCESS
        exit_code = 0
        error: ResultError | None = None
    except Exception as exc:
        status = STATUS_FAILED
        exit_code = 1
        error = ResultError(
            code=ERROR_EXECUTION,
            message=f"Node execution failed: {exc}",
        )
    finally:
        for item in added_paths:
            try:
                sys.path.remove(item)
            except ValueError:
                pass
        for key, previous in previous_env.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous
        os.chdir(previous_dir)

    finished_at = utcnow()
    duration_seconds = round(time.monotonic() - started_monotonic, 3)
    stdout = _truncate_text(stdout_buffer.getvalue(), max_bytes=payload.capture_limit_bytes)
    stderr = _truncate_text(stderr_buffer.getvalue(), max_bytes=payload.capture_limit_bytes)
    provider_metadata = _provider_metadata_base(
        payload,
        cwd=cwd,
        execution_mode="node_execution",
    )
    provider_metadata["node_execution_entrypoint"] = node_execution.entrypoint
    if node_execution.request_context:
        provider_metadata["node_execution_context"] = node_execution.request_context

    return ExecutionResult(
        status=status,
        exit_code=exit_code,
        started_at=started_at,
        finished_at=finished_at,
        stdout=stdout,
        stderr=stderr,
        error=error,
        provider_metadata=provider_metadata,
        metrics={"duration_seconds": duration_seconds},
        output_state=output_state,
        routing_state=routing_state,
    )


def _execute_command_payload(
    payload: ExecutionPayload,
    *,
    cwd: str,
    env: dict[str, str],
) -> ExecutionResult:
    started_at = utcnow()
    started_monotonic = time.monotonic()
    command = payload.command
    if not command:
        raise RuntimeError("command payload is required for command execution mode.")

    try:
        completed = subprocess.run(
            command,
            input=payload.stdin,
            capture_output=True,
            text=True,
            cwd=cwd,
            env=env,
            timeout=payload.timeout_seconds,
            check=False,
        )
        finished_at = utcnow()
        duration_seconds = round(time.monotonic() - started_monotonic, 3)
        stdout = _truncate_text(
            completed.stdout or "",
            max_bytes=payload.capture_limit_bytes,
        )
        stderr = _truncate_text(
            completed.stderr or "",
            max_bytes=payload.capture_limit_bytes,
        )

        status = STATUS_SUCCESS
        error: ResultError | None = None
        if completed.returncode == 0:
            status = STATUS_SUCCESS
        elif completed.returncode in {-signal.SIGTERM, -signal.SIGINT}:
            status = STATUS_CANCELLED
            error = ResultError(
                code=ERROR_CANCELLED,
                message=f"Command was cancelled (exit code {completed.returncode}).",
            )
        else:
            status = STATUS_FAILED
            error = ResultError(
                code=ERROR_EXECUTION,
                message=f"Command exited with non-zero code {completed.returncode}.",
                details={"returncode": completed.returncode},
            )

        provider_metadata = _provider_metadata_base(
            payload,
            cwd=cwd,
            execution_mode="command",
        )
        provider_metadata["command"] = command

        return ExecutionResult(
            status=status,
            exit_code=int(completed.returncode),
            started_at=started_at,
            finished_at=finished_at,
            stdout=stdout,
            stderr=stderr,
            error=error,
            provider_metadata=provider_metadata,
            metrics={"duration_seconds": duration_seconds},
        )
    except subprocess.TimeoutExpired as exc:
        finished_at = utcnow()
        duration_seconds = round(time.monotonic() - started_monotonic, 3)
        stdout = _truncate_text(
            (exc.stdout or "") if isinstance(exc.stdout, str) else "",
            max_bytes=payload.capture_limit_bytes,
        )
        stderr = _truncate_text(
            (exc.stderr or "") if isinstance(exc.stderr, str) else "",
            max_bytes=payload.capture_limit_bytes,
        )
        provider_metadata = _provider_metadata_base(
            payload,
            cwd=cwd,
            execution_mode="command",
        )
        provider_metadata["command"] = command
        return ExecutionResult(
            status=STATUS_TIMEOUT,
            exit_code=124,
            started_at=started_at,
            finished_at=finished_at,
            stdout=stdout,
            stderr=stderr,
            error=ResultError(
                code=ERROR_TIMEOUT,
                message=f"Execution timed out after {payload.timeout_seconds} seconds.",
                details={"timeout_seconds": payload.timeout_seconds},
            ),
            provider_metadata=provider_metadata,
            metrics={"duration_seconds": duration_seconds},
        )


def execute_single_run(payload: ExecutionPayload) -> ExecutionResult:
    cwd = payload.cwd
    if not os.path.isabs(cwd):
        cwd = os.path.abspath(cwd)
    if not os.path.exists(cwd):
        os.makedirs(cwd, exist_ok=True)

    env = os.environ.copy()
    env.update(payload.env)
    if payload.emit_start_markers:
        emit_start_markers()

    if payload.node_execution is not None:
        return _execute_node_payload(payload, cwd=cwd)
    return _execute_command_payload(payload, cwd=cwd, env=env)
