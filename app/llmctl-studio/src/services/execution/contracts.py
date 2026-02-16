from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

EXECUTION_CONTRACT_VERSION = "v1"
EXECUTION_STATUS_SUCCESS = "success"
EXECUTION_STATUS_FAILED = "failed"

EXECUTION_PROVIDER_WORKSPACE = "workspace"
EXECUTION_PROVIDER_DOCKER = "docker"
EXECUTION_PROVIDER_KUBERNETES = "kubernetes"
EXECUTION_PROVIDER_CHOICES = (
    EXECUTION_PROVIDER_WORKSPACE,
    EXECUTION_PROVIDER_DOCKER,
    EXECUTION_PROVIDER_KUBERNETES,
)

EXECUTION_DISPATCH_PENDING = "dispatch_pending"
EXECUTION_DISPATCH_SUBMITTED = "dispatch_submitted"
EXECUTION_DISPATCH_CONFIRMED = "dispatch_confirmed"
EXECUTION_DISPATCH_FAILED = "dispatch_failed"
EXECUTION_DISPATCH_FALLBACK_STARTED = "fallback_started"
EXECUTION_DISPATCH_STATUS_CHOICES = (
    EXECUTION_DISPATCH_PENDING,
    EXECUTION_DISPATCH_SUBMITTED,
    EXECUTION_DISPATCH_CONFIRMED,
    EXECUTION_DISPATCH_FAILED,
    EXECUTION_DISPATCH_FALLBACK_STARTED,
)


@dataclass(frozen=True)
class ExecutionRequest:
    node_id: int
    node_type: str
    node_ref_id: int | None
    node_config: dict[str, Any]
    input_context: dict[str, Any]
    execution_id: int
    execution_task_id: int | None
    execution_index: int
    enabled_providers: set[str]
    default_model_id: int | None
    mcp_server_keys: list[str]
    selected_provider: str = EXECUTION_PROVIDER_WORKSPACE
    final_provider: str = EXECUTION_PROVIDER_WORKSPACE
    provider_dispatch_id: str | None = None
    workspace_identity: str = "default"
    dispatch_status: str = EXECUTION_DISPATCH_PENDING
    fallback_attempted: bool = False
    fallback_reason: str | None = None
    dispatch_uncertain: bool = False
    api_failure_category: str | None = None
    cli_fallback_used: bool = False
    cli_preflight_passed: bool | None = None

    def run_metadata_payload(self) -> dict[str, Any]:
        return {
            "selected_provider": self.selected_provider,
            "final_provider": self.final_provider,
            "provider_dispatch_id": self.provider_dispatch_id,
            "workspace_identity": self.workspace_identity,
            "dispatch_status": self.dispatch_status,
            "fallback_attempted": self.fallback_attempted,
            "fallback_reason": self.fallback_reason,
            "dispatch_uncertain": self.dispatch_uncertain,
            "api_failure_category": self.api_failure_category,
            "cli_fallback_used": self.cli_fallback_used,
            "cli_preflight_passed": self.cli_preflight_passed,
        }


@dataclass
class ExecutionResult:
    contract_version: str
    status: str
    exit_code: int
    started_at: datetime | None
    finished_at: datetime | None
    stdout: str
    stderr: str
    error: dict[str, Any] | None
    provider_metadata: dict[str, Any]
    output_state: dict[str, Any]
    routing_state: dict[str, Any]
    run_metadata: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] | None = None
    artifacts: dict[str, Any] | None = None
    warnings: list[str] | None = None
    metrics: dict[str, Any] | None = None
