from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from services.execution.contracts import (
    EXECUTION_CONTRACT_VERSION,
    EXECUTION_DISPATCH_CONFIRMED,
    EXECUTION_DISPATCH_FAILED,
    EXECUTION_STATUS_SUCCESS,
    EXECUTION_STATUS_FAILED,
    ExecutionRequest,
    ExecutionResult,
)
from services.execution.idempotency import register_dispatch_key


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WorkspaceExecutor:
    provider = "workspace"

    def execute(
        self,
        request: ExecutionRequest,
        execute_callback: Callable[[ExecutionRequest], tuple[dict[str, Any], dict[str, Any]]],
    ) -> ExecutionResult:
        started_at = _utcnow()
        provider_metadata: dict[str, Any] = {
            "executor_provider": self.provider,
            "selected_provider": request.selected_provider,
            "final_provider": request.final_provider,
            "provider_dispatch_id": request.provider_dispatch_id,
            "workspace_identity": request.workspace_identity,
        }
        if request.fallback_attempted:
            provider_metadata["fallback_attempted"] = True
            provider_metadata["fallback_reason"] = request.fallback_reason or "unknown"
        run_metadata: dict[str, Any] = dict(request.run_metadata_payload())
        if str(run_metadata.get("final_provider") or "") == self.provider:
            if not str(run_metadata.get("provider_dispatch_id") or "").strip():
                run_metadata["provider_dispatch_id"] = (
                    f"workspace:workspace-{request.execution_id}"
                )
            if str(run_metadata.get("dispatch_status") or "").strip() in {"", "dispatch_pending"}:
                run_metadata["dispatch_status"] = EXECUTION_DISPATCH_CONFIRMED

        dispatch_id = str(run_metadata.get("provider_dispatch_id") or "").strip()
        if dispatch_id:
            if not register_dispatch_key(request.execution_id, dispatch_id):
                finished_at = _utcnow()
                return ExecutionResult(
                    contract_version=EXECUTION_CONTRACT_VERSION,
                    status=EXECUTION_STATUS_FAILED,
                    exit_code=1,
                    started_at=started_at,
                    finished_at=finished_at,
                    stdout="",
                    stderr="",
                    error={
                        "code": "dispatch_error",
                        "message": (
                            "Duplicate dispatch detected for this node run; "
                            "refusing to execute callback twice."
                        ),
                        "retryable": False,
                    },
                    provider_metadata={
                        **provider_metadata,
                        "provider_dispatch_id": dispatch_id,
                    },
                    output_state={},
                    routing_state={},
                    run_metadata={
                        **run_metadata,
                        "dispatch_status": EXECUTION_DISPATCH_FAILED,
                        "dispatch_uncertain": True,
                    },
                )

        output_state, routing_state = execute_callback(request)
        finished_at = _utcnow()
        provider_metadata["provider_dispatch_id"] = dispatch_id or provider_metadata.get(
            "provider_dispatch_id"
        )
        return ExecutionResult(
            contract_version=EXECUTION_CONTRACT_VERSION,
            status=EXECUTION_STATUS_SUCCESS,
            exit_code=0,
            started_at=started_at,
            finished_at=finished_at,
            stdout="",
            stderr="",
            error=None,
            provider_metadata=provider_metadata,
            output_state=output_state,
            routing_state=routing_state,
            run_metadata=run_metadata,
        )
