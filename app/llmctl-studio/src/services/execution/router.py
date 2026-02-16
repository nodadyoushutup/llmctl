from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from services.execution.contracts import (
    EXECUTION_CONTRACT_VERSION,
    EXECUTION_DISPATCH_PENDING,
    EXECUTION_PROVIDER_DOCKER,
    EXECUTION_PROVIDER_KUBERNETES,
    EXECUTION_PROVIDER_WORKSPACE,
    EXECUTION_STATUS_FAILED,
    ExecutionRequest,
    ExecutionResult,
)
from services.execution.docker_executor import DockerExecutor
from services.execution.kubernetes_executor import KubernetesExecutor
from services.execution.workspace_executor import WorkspaceExecutor
from services.integrations import (
    load_node_executor_runtime_settings,
    normalize_node_executor_provider,
    normalize_workspace_identity_key,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ExecutionRouter:
    def __init__(
        self,
        *,
        runtime_settings: dict[str, str] | None = None,
        workspace_executor: WorkspaceExecutor | None = None,
        docker_executor: DockerExecutor | None = None,
        kubernetes_executor: KubernetesExecutor | None = None,
    ) -> None:
        self._runtime_settings = runtime_settings or load_node_executor_runtime_settings()
        self._workspace_executor = workspace_executor or WorkspaceExecutor()
        self._docker_executor = docker_executor or DockerExecutor(self._runtime_settings)
        self._kubernetes_executor = (
            kubernetes_executor or KubernetesExecutor(self._runtime_settings)
        )

    def route_request(self, request: ExecutionRequest) -> ExecutionRequest:
        configured_provider = normalize_node_executor_provider(
            self._runtime_settings.get("provider")
        )
        if not configured_provider:
            configured_provider = EXECUTION_PROVIDER_WORKSPACE
        workspace_identity = normalize_workspace_identity_key(
            self._runtime_settings.get("workspace_identity_key")
        )
        logger.info(
            "Node executor route selected provider=%s node_id=%s execution_id=%s workspace_identity=%s",
            configured_provider,
            request.node_id,
            request.execution_id,
            workspace_identity,
        )

        return replace(
            request,
            selected_provider=configured_provider,
            final_provider=configured_provider,
            provider_dispatch_id=None,
            workspace_identity=workspace_identity,
            dispatch_status=EXECUTION_DISPATCH_PENDING,
            fallback_attempted=False,
            fallback_reason=None,
            dispatch_uncertain=False,
            api_failure_category=None,
            cli_fallback_used=False,
            cli_preflight_passed=None,
        )

    def execute(
        self,
        request: ExecutionRequest,
        execute_callback: Callable[[ExecutionRequest], tuple[dict[str, Any], dict[str, Any]]],
    ) -> ExecutionResult:
        routed = self.route_request(request)
        return self.execute_routed(routed, execute_callback)

    def execute_routed(
        self,
        request: ExecutionRequest,
        execute_callback: Callable[[ExecutionRequest], tuple[dict[str, Any], dict[str, Any]]],
    ) -> ExecutionResult:
        logger.info(
            "Node executor dispatch starting provider=%s node_id=%s execution_id=%s dispatch_status=%s",
            request.selected_provider,
            request.node_id,
            request.execution_id,
            request.dispatch_status,
        )
        result: ExecutionResult | None = None
        if request.selected_provider == EXECUTION_PROVIDER_WORKSPACE:
            result = self._workspace_executor.execute(request, execute_callback)
        elif request.selected_provider == EXECUTION_PROVIDER_DOCKER:
            result = self._docker_executor.execute(request, execute_callback)
        elif request.selected_provider == EXECUTION_PROVIDER_KUBERNETES:
            result = self._kubernetes_executor.execute(request, execute_callback)
        else:
            now = _utcnow()
            result = ExecutionResult(
                contract_version=EXECUTION_CONTRACT_VERSION,
                status=EXECUTION_STATUS_FAILED,
                exit_code=1,
                started_at=now,
                finished_at=now,
                stdout="",
                stderr="",
                error={
                    "code": "provider_error",
                    "message": f"Unsupported provider '{request.final_provider}'.",
                    "retryable": False,
                },
                provider_metadata={
                    "selected_provider": request.selected_provider,
                    "final_provider": request.final_provider,
                },
                output_state={},
                routing_state={},
                run_metadata=request.run_metadata_payload(),
            )
        run_metadata = result.run_metadata if isinstance(result.run_metadata, dict) else {}
        logger.info(
            "Node executor dispatch finished provider=%s node_id=%s execution_id=%s status=%s dispatch_status=%s final_provider=%s fallback_attempted=%s fallback_reason=%s",
            request.selected_provider,
            request.node_id,
            request.execution_id,
            result.status,
            run_metadata.get("dispatch_status"),
            run_metadata.get("final_provider"),
            run_metadata.get("fallback_attempted"),
            run_metadata.get("fallback_reason"),
        )
        return result
