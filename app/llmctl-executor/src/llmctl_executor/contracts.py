from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

CONTRACT_VERSION = "v1"
START_MARKER_LITERAL = "LLMCTL_EXECUTOR_STARTED"
START_MARKER_EVENT = "executor_started"
RESULT_PREFIX = "LLMCTL_EXECUTOR_RESULT_JSON="

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_TIMEOUT = "timeout"
STATUS_DISPATCH_FAILED = "dispatch_failed"
STATUS_DISPATCH_UNCERTAIN = "dispatch_uncertain"
STATUS_INFRA_ERROR = "infra_error"
STATUS_CHOICES = {
    STATUS_SUCCESS,
    STATUS_FAILED,
    STATUS_CANCELLED,
    STATUS_TIMEOUT,
    STATUS_DISPATCH_FAILED,
    STATUS_DISPATCH_UNCERTAIN,
    STATUS_INFRA_ERROR,
}

ERROR_VALIDATION = "validation_error"
ERROR_PROVIDER = "provider_error"
ERROR_DISPATCH = "dispatch_error"
ERROR_TIMEOUT = "timeout"
ERROR_CANCELLED = "cancelled"
ERROR_EXECUTION = "execution_error"
ERROR_INFRA = "infra_error"
ERROR_UNKNOWN = "unknown"

RETRYABLE_BY_ERROR_CODE = {
    ERROR_VALIDATION: False,
    ERROR_PROVIDER: True,
    ERROR_DISPATCH: True,
    ERROR_TIMEOUT: True,
    ERROR_CANCELLED: False,
    ERROR_EXECUTION: False,
    ERROR_INFRA: True,
    ERROR_UNKNOWN: True,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso8601(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(timezone.utc).isoformat()


@dataclass
class ResultError:
    code: str
    message: str
    details: dict[str, Any] | None = None
    retryable: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": (
                self.retryable
                if self.retryable is not None
                else RETRYABLE_BY_ERROR_CODE.get(self.code, True)
            ),
        }
        if self.details:
            payload["details"] = self.details
        return payload


@dataclass
class ExecutionResult:
    status: str
    exit_code: int
    started_at: datetime
    finished_at: datetime
    stdout: str
    stderr: str
    provider_metadata: dict[str, Any]
    error: ResultError | None = None
    usage: dict[str, Any] | None = None
    artifacts: dict[str, Any] | None = None
    warnings: list[str] | None = None
    metrics: dict[str, Any] | None = None
    output_state: dict[str, Any] | None = None
    routing_state: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        if self.status not in STATUS_CHOICES:
            raise ValueError(f"Unsupported status '{self.status}'.")
        payload: dict[str, Any] = {
            "contract_version": CONTRACT_VERSION,
            "status": self.status,
            "exit_code": int(self.exit_code),
            "started_at": to_iso8601(self.started_at),
            "finished_at": to_iso8601(self.finished_at),
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error.as_dict() if self.error is not None else None,
            "provider_metadata": self.provider_metadata,
        }
        if self.usage is not None:
            payload["usage"] = self.usage
        if self.artifacts is not None:
            payload["artifacts"] = self.artifacts
        if self.warnings is not None:
            payload["warnings"] = self.warnings
        if self.metrics is not None:
            payload["metrics"] = self.metrics
        if self.output_state is not None:
            payload["output_state"] = self.output_state
        if self.routing_state is not None:
            payload["routing_state"] = self.routing_state
        return payload
