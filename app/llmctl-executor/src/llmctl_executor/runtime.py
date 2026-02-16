from __future__ import annotations

import json
import os
import signal
import subprocess
import time
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


def execute_single_run(payload: ExecutionPayload) -> ExecutionResult:
    started_at = utcnow()
    started_monotonic = time.monotonic()
    cwd = payload.cwd
    if not os.path.isabs(cwd):
        cwd = os.path.abspath(cwd)
    if not os.path.exists(cwd):
        os.makedirs(cwd, exist_ok=True)

    env = os.environ.copy()
    env.update(payload.env)
    if payload.emit_start_markers:
        emit_start_markers()

    try:
        completed = subprocess.run(
            payload.command,
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

        provider_metadata: dict[str, Any] = {
            "executor": "llmctl-executor",
            "provider": payload.provider,
            "request_id": payload.request_id,
            "command": payload.command,
            "cwd": cwd,
            "emit_start_markers": payload.emit_start_markers,
        }
        if payload.metadata:
            provider_metadata["request_metadata"] = payload.metadata

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
            provider_metadata={
                "executor": "llmctl-executor",
                "provider": payload.provider,
                "request_id": payload.request_id,
                "command": payload.command,
                "cwd": cwd,
                "emit_start_markers": payload.emit_start_markers,
            },
            metrics={"duration_seconds": duration_seconds},
        )
