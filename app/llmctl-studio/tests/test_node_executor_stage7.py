from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

from services.execution.contracts import (
    EXECUTION_DISPATCH_CONFIRMED,
    EXECUTION_DISPATCH_FALLBACK_STARTED,
    EXECUTION_DISPATCH_FAILED,
    ExecutionRequest,
)
from services.execution.docker_executor import (
    DockerExecutor,
    _DockerDispatchFailure,
    _DockerDispatchOutcome,
)
from services.execution.kubernetes_executor import (
    KubernetesExecutor,
    _KubernetesDispatchOutcome,
)
from services.execution.idempotency import clear_dispatch_registry
from services.execution.workspace_executor import WorkspaceExecutor


def _request(execution_id: int = 9101) -> ExecutionRequest:
    return ExecutionRequest(
        node_id=77,
        node_type="start",
        node_ref_id=None,
        node_config={},
        input_context={},
        execution_id=execution_id,
        execution_task_id=1000 + execution_id,
        execution_index=1,
        enabled_providers=set(),
        default_model_id=None,
        mcp_server_keys=[],
    )


class NodeExecutorStage7Tests(unittest.TestCase):
    def setUp(self) -> None:
        clear_dispatch_registry()

    def test_docker_ambiguous_dispatch_no_auto_fallback(self) -> None:
        executor = DockerExecutor(
            {
                "fallback_enabled": "true",
                "fallback_on_dispatch_error": "true",
                "fallback_provider": "workspace",
            }
        )
        executor._dispatch_via_docker = lambda **_kwargs: _DockerDispatchOutcome(  # type: ignore[method-assign]
            dispatch_id="abc123",
            stdout="no marker",
            stderr="",
            api_failure_category=None,
            cli_fallback_used=False,
            cli_preflight_passed=None,
            dispatch_submitted=True,
            startup_marker_seen=False,
            executor_result=None,
        )
        callback_called = {"value": False}

        def _callback(_request: ExecutionRequest):
            callback_called["value"] = True
            return {"ok": True}, {}

        result = executor.execute(_request(9101), _callback)
        self.assertFalse(callback_called["value"])
        self.assertEqual("failed", result.status)
        self.assertEqual(EXECUTION_DISPATCH_FAILED, result.run_metadata.get("dispatch_status"))
        self.assertTrue(bool(result.run_metadata.get("dispatch_uncertain")))
        self.assertFalse(bool(result.run_metadata.get("fallback_attempted")))

    def test_docker_post_confirm_failure_keeps_dispatch_confirmed(self) -> None:
        executor = DockerExecutor({"fallback_enabled": "true"})
        executor._dispatch_via_docker = lambda **_kwargs: _DockerDispatchOutcome(  # type: ignore[method-assign]
            dispatch_id="abc456",
            stdout="LLMCTL_EXECUTOR_STARTED\nLLMCTL_EXECUTOR_RESULT_JSON={\"status\":\"failed\"}",
            stderr="",
            api_failure_category=None,
            cli_fallback_used=False,
            cli_preflight_passed=None,
            dispatch_submitted=True,
            startup_marker_seen=True,
            executor_result={"status": "failed"},
        )
        callback_called = {"value": False}

        def _callback(_request: ExecutionRequest):
            callback_called["value"] = True
            return {"ok": True}, {}

        result = executor.execute(_request(9102), _callback)
        self.assertFalse(callback_called["value"])
        self.assertEqual("failed", result.status)
        self.assertEqual(
            EXECUTION_DISPATCH_CONFIRMED,
            result.run_metadata.get("dispatch_status"),
        )
        self.assertFalse(bool(result.run_metadata.get("dispatch_uncertain")))

    def test_docker_fallback_callback_receives_fallback_started_state(self) -> None:
        executor = DockerExecutor(
            {
                "fallback_enabled": "true",
                "fallback_on_dispatch_error": "true",
                "fallback_provider": "workspace",
            }
        )

        def _dispatch_failure(**_kwargs):
            raise _DockerDispatchFailure(
                fallback_reason="provider_unavailable",
                message="docker down",
                dispatch_submitted=False,
            )

        executor._dispatch_via_docker = _dispatch_failure  # type: ignore[method-assign]
        observed = {"status": "", "fallback_attempted": False}

        def _callback(fallback_request: ExecutionRequest):
            observed["status"] = fallback_request.dispatch_status
            observed["fallback_attempted"] = fallback_request.fallback_attempted
            return {"ok": True}, {}

        result = executor.execute(_request(9103), _callback)
        self.assertEqual(EXECUTION_DISPATCH_FALLBACK_STARTED, observed["status"])
        self.assertTrue(observed["fallback_attempted"])
        self.assertEqual("success", result.status)
        self.assertEqual(
            EXECUTION_DISPATCH_CONFIRMED,
            result.run_metadata.get("dispatch_status"),
        )

    def test_kubernetes_ambiguous_dispatch_no_auto_fallback(self) -> None:
        executor = KubernetesExecutor(
            {
                "fallback_enabled": "true",
                "fallback_on_dispatch_error": "true",
                "fallback_provider": "workspace",
            }
        )
        executor._dispatch_via_kubernetes = lambda **_kwargs: _KubernetesDispatchOutcome(  # type: ignore[method-assign]
            job_name="job-1",
            pod_name="pod-1",
            stdout="",
            stderr="",
            startup_marker_seen=False,
            executor_result=None,
        )
        callback_called = {"value": False}

        def _callback(_request: ExecutionRequest):
            callback_called["value"] = True
            return {"ok": True}, {}

        result = executor.execute(_request(9104), _callback)
        self.assertFalse(callback_called["value"])
        self.assertEqual("failed", result.status)
        self.assertEqual(EXECUTION_DISPATCH_FAILED, result.run_metadata.get("dispatch_status"))
        self.assertTrue(bool(result.run_metadata.get("dispatch_uncertain")))
        self.assertFalse(bool(result.run_metadata.get("fallback_attempted")))

    def test_workspace_idempotency_blocks_duplicate_dispatch_key(self) -> None:
        executor = WorkspaceExecutor()
        request = _request(9300)
        callback_count = {"value": 0}

        def _callback(_request: ExecutionRequest):
            callback_count["value"] += 1
            return {"ok": True}, {}

        first = executor.execute(request, _callback)
        second = executor.execute(request, _callback)
        self.assertEqual("success", first.status)
        self.assertEqual("failed", second.status)
        self.assertEqual(1, callback_count["value"])

    def test_fallback_is_not_attempted_twice(self) -> None:
        executor = DockerExecutor(
            {
                "fallback_enabled": "true",
                "fallback_on_dispatch_error": "true",
                "fallback_provider": "workspace",
            }
        )

        def _dispatch_failure(**_kwargs):
            raise _DockerDispatchFailure(
                fallback_reason="provider_unavailable",
                message="docker down",
                dispatch_submitted=False,
            )

        executor._dispatch_via_docker = _dispatch_failure  # type: ignore[method-assign]
        callback_called = {"value": False}

        def _callback(_request: ExecutionRequest):
            callback_called["value"] = True
            return {"ok": True}, {}

        prior_fallback_request = replace(
            _request(9105),
            fallback_attempted=True,
            fallback_reason="provider_unavailable",
        )
        result = executor.execute(prior_fallback_request, _callback)
        self.assertFalse(callback_called["value"])
        self.assertEqual("failed", result.status)
        self.assertTrue(bool(result.run_metadata.get("fallback_attempted")))
        self.assertEqual(
            "provider_unavailable",
            result.run_metadata.get("fallback_reason"),
        )


if __name__ == "__main__":
    unittest.main()
