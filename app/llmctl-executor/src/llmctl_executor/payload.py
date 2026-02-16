from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import CONTRACT_VERSION, ERROR_INFRA, ERROR_VALIDATION

DEFAULT_TIMEOUT_SECONDS = 1800
DEFAULT_CAPTURE_LIMIT_BYTES = 1_000_000


class PayloadError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str = ERROR_VALIDATION,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _as_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    raw = str(value or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _coerce_timeout(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_TIMEOUT_SECONDS
    return max(1, min(parsed, 24 * 60 * 60))


def _coerce_capture_limit(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_CAPTURE_LIMIT_BYTES
    return max(1024, min(parsed, 10_000_000))


def _normalize_env(raw: Any) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise PayloadError("payload.env must be a JSON object map.")
    normalized: dict[str, str] = {}
    for key, value in raw.items():
        cleaned_key = str(key).strip()
        if not cleaned_key:
            raise PayloadError("payload.env keys must be non-empty strings.")
        normalized[cleaned_key] = str(value)
    return normalized


def _resolve_command(payload: dict[str, Any]) -> list[str]:
    command_raw = payload.get("command")
    shell_command = str(payload.get("shell_command") or "").strip()

    if command_raw is not None:
        if not isinstance(command_raw, list) or not command_raw:
            raise PayloadError("payload.command must be a non-empty array of strings.")
        command = [str(part) for part in command_raw]
        if any(not part.strip() for part in command):
            raise PayloadError("payload.command entries must be non-empty strings.")
        return command

    if shell_command:
        return ["/bin/bash", "-lc", shell_command]

    raise PayloadError("payload must include command[] or shell_command.")


@dataclass(frozen=True)
class ExecutionPayload:
    contract_version: str
    request_id: str
    provider: str
    command: list[str]
    cwd: str
    env: dict[str, str]
    stdin: str
    timeout_seconds: int
    capture_limit_bytes: int
    emit_start_markers: bool
    metadata: dict[str, Any]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExecutionPayload":
        if not isinstance(payload, dict):
            raise PayloadError("payload must be a JSON object.")

        contract_version = str(payload.get("contract_version") or "").strip()
        if contract_version != CONTRACT_VERSION:
            raise PayloadError(
                "payload.contract_version must be exactly 'v1'.",
                code=ERROR_INFRA,
                details={"expected": CONTRACT_VERSION, "received": contract_version},
            )

        result_contract_version = str(payload.get("result_contract_version") or "").strip()
        if result_contract_version and result_contract_version != CONTRACT_VERSION:
            raise PayloadError(
                "payload.result_contract_version must be exactly 'v1' when provided.",
                code=ERROR_INFRA,
                details={
                    "expected": CONTRACT_VERSION,
                    "received": result_contract_version,
                },
            )

        provider = str(payload.get("provider") or "workspace").strip().lower() or "workspace"
        if provider not in {"workspace", "docker", "kubernetes"}:
            raise PayloadError(
                "payload.provider must be one of workspace|docker|kubernetes."
            )

        command = _resolve_command(payload)
        default_cwd = os.getenv("LLMCTL_EXECUTOR_DEFAULT_CWD", "/tmp/llmctl-workspace")
        cwd = str(payload.get("cwd") or default_cwd).strip() or default_cwd
        env = _normalize_env(payload.get("env"))
        stdin = str(payload.get("stdin") or "")
        timeout_seconds = _coerce_timeout(payload.get("timeout_seconds"))
        capture_limit_bytes = _coerce_capture_limit(payload.get("capture_limit_bytes"))
        emit_start_markers = _as_bool(
            payload.get("emit_start_markers"),
            default=True,
        )
        metadata_raw = payload.get("metadata")
        metadata = metadata_raw if isinstance(metadata_raw, dict) else {}
        request_id = str(payload.get("request_id") or "").strip()
        if not request_id:
            request_id = "executor-run"

        return cls(
            contract_version=contract_version,
            request_id=request_id,
            provider=provider,
            command=command,
            cwd=cwd,
            env=env,
            stdin=stdin,
            timeout_seconds=timeout_seconds,
            capture_limit_bytes=capture_limit_bytes,
            emit_start_markers=emit_start_markers,
            metadata=metadata,
        )


def load_payload_input(
    *,
    payload_file: str | None = None,
    payload_json: str | None = None,
) -> dict[str, Any]:
    file_candidate = (payload_file or "").strip() or os.getenv(
        "LLMCTL_EXECUTOR_PAYLOAD_FILE", ""
    ).strip()
    json_candidate = (payload_json or "").strip() or os.getenv(
        "LLMCTL_EXECUTOR_PAYLOAD_JSON", ""
    ).strip()

    if file_candidate:
        source_path = Path(file_candidate)
        if not source_path.exists():
            raise PayloadError(
                f"payload file '{source_path}' does not exist.",
                code=ERROR_INFRA,
            )
        try:
            return json.loads(source_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PayloadError(
                f"payload file JSON is invalid: {exc.msg}.",
                details={"path": str(source_path)},
            ) from exc

    if json_candidate:
        try:
            return json.loads(json_candidate)
        except json.JSONDecodeError as exc:
            raise PayloadError(
                f"payload JSON is invalid: {exc.msg}.",
                details={"source": "LLMCTL_EXECUTOR_PAYLOAD_JSON/--payload-json"},
            ) from exc

    if not os.isatty(0):
        stdin_text = os.read(0, 10_000_000).decode("utf-8", errors="replace").strip()
        if stdin_text:
            try:
                return json.loads(stdin_text)
            except json.JSONDecodeError as exc:
                raise PayloadError(
                    f"stdin payload JSON is invalid: {exc.msg}.",
                    details={"source": "stdin"},
                ) from exc

    raise PayloadError(
        "No payload provided. Set --payload-file, --payload-json, "
        "LLMCTL_EXECUTOR_PAYLOAD_FILE, LLMCTL_EXECUTOR_PAYLOAD_JSON, or pipe JSON to stdin.",
        code=ERROR_INFRA,
    )
