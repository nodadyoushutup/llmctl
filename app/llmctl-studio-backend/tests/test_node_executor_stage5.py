from __future__ import annotations

import sys
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

from services.execution.contracts import ExecutionRequest
from services.execution.docker_executor import (
    DockerExecutor,
    _DockerApiUnavailable,
    _DockerDispatchFailure,
)
from services.execution.idempotency import clear_dispatch_registry
from services.execution.router import ExecutionRouter


def _request() -> ExecutionRequest:
    return ExecutionRequest(
        node_id=10,
        node_type="start",
        node_ref_id=None,
        node_config={},
        input_context={},
        execution_id=99,
        execution_task_id=101,
        execution_index=1,
        enabled_providers=set(),
        default_model_id=None,
        mcp_server_keys=[],
    )


class _StubDockerExecutor:
    def __init__(self, result) -> None:
        self.called = False
        self.last_request: ExecutionRequest | None = None
        self._result = result

    def execute(self, request: ExecutionRequest, execute_callback):
        self.called = True
        self.last_request = request
        return self._result(request, execute_callback)


class NodeExecutorStage5Tests(unittest.TestCase):
    def setUp(self) -> None:
        clear_dispatch_registry()

    def test_docker_executor_fallbacks_to_workspace_on_dispatch_failure(self) -> None:
        settings = {
            "fallback_enabled": "true",
            "fallback_on_dispatch_error": "true",
            "fallback_provider": "workspace",
        }
        executor = DockerExecutor(settings)

        def _dispatch_failure(**_kwargs):
            raise _DockerDispatchFailure(
                fallback_reason="provider_unavailable",
                message="docker unavailable",
                api_failure_category="socket_missing",
                cli_fallback_used=False,
                cli_preflight_passed=None,
            )

        executor._dispatch_via_docker = _dispatch_failure  # type: ignore[method-assign]

        callback_called = {"value": False}

        def _callback(_request: ExecutionRequest):
            callback_called["value"] = True
            return {"node_type": "start", "message": "ok"}, {}

        result = executor.execute(_request(), _callback)
        self.assertTrue(callback_called["value"])
        self.assertEqual("success", result.status)
        self.assertEqual("docker", result.run_metadata.get("selected_provider"))
        self.assertEqual("workspace", result.run_metadata.get("final_provider"))
        self.assertTrue(bool(result.run_metadata.get("fallback_attempted")))
        self.assertEqual("provider_unavailable", result.run_metadata.get("fallback_reason"))
        self.assertEqual("dispatch_confirmed", result.run_metadata.get("dispatch_status"))
        self.assertEqual(
            "workspace:workspace-99",
            result.run_metadata.get("provider_dispatch_id"),
        )

    def test_docker_executor_respects_no_fallback(self) -> None:
        settings = {
            "fallback_enabled": "false",
            "fallback_on_dispatch_error": "true",
            "fallback_provider": "workspace",
        }
        executor = DockerExecutor(settings)

        def _dispatch_failure(**_kwargs):
            raise _DockerDispatchFailure(
                fallback_reason="provider_unavailable",
                message="docker unavailable",
                api_failure_category="socket_unreachable",
                cli_fallback_used=False,
                cli_preflight_passed=None,
            )

        executor._dispatch_via_docker = _dispatch_failure  # type: ignore[method-assign]

        callback_called = {"value": False}

        def _callback(_request: ExecutionRequest):
            callback_called["value"] = True
            return {"node_type": "start", "message": "ok"}, {}

        result = executor.execute(_request(), _callback)
        self.assertFalse(callback_called["value"])
        self.assertEqual("failed", result.status)
        self.assertEqual("docker", result.run_metadata.get("selected_provider"))
        self.assertEqual("docker", result.run_metadata.get("final_provider"))
        self.assertEqual("dispatch_failed", result.run_metadata.get("dispatch_status"))
        self.assertFalse(bool(result.run_metadata.get("fallback_attempted")))
        self.assertIsNone(result.run_metadata.get("fallback_reason"))

    def test_router_uses_docker_executor_when_provider_is_docker(self) -> None:
        settings = {
            "provider": "docker",
            "workspace_identity_key": "workspace-main",
        }

        def _stub_result(request: ExecutionRequest, execute_callback):
            output_state, routing_state = execute_callback(request)
            from services.execution.contracts import ExecutionResult

            return ExecutionResult(
                contract_version="v1",
                status="success",
                exit_code=0,
                started_at=None,
                finished_at=None,
                stdout="",
                stderr="",
                error=None,
                provider_metadata={"provider": "docker"},
                output_state=output_state,
                routing_state=routing_state,
                run_metadata={
                    "selected_provider": "docker",
                    "final_provider": "docker",
                    "provider_dispatch_id": "docker:abc123",
                    "workspace_identity": request.workspace_identity,
                    "dispatch_status": "dispatch_confirmed",
                    "fallback_attempted": False,
                    "fallback_reason": None,
                    "dispatch_uncertain": False,
                    "api_failure_category": None,
                    "cli_fallback_used": False,
                    "cli_preflight_passed": None,
                },
            )

        stub = _StubDockerExecutor(_stub_result)
        router = ExecutionRouter(runtime_settings=settings, docker_executor=stub)  # type: ignore[arg-type]
        request = router.route_request(_request())
        self.assertEqual("docker", request.selected_provider)
        self.assertEqual("dispatch_pending", request.dispatch_status)
        self.assertEqual("workspace-main", request.workspace_identity)

        result = router.execute_routed(request, lambda _request: ({"ok": True}, {}))
        self.assertTrue(stub.called)
        self.assertEqual("success", result.status)
        self.assertEqual("docker", result.run_metadata.get("final_provider"))

    def test_cli_fallback_precondition_requires_socket_mount(self) -> None:
        settings = {
            "docker_host": "unix:///tmp/llmctl-missing-docker.sock",
        }
        executor = DockerExecutor(settings)
        self.assertFalse(executor._cli_fallback_precondition(settings["docker_host"]))

    def test_dispatch_via_cli_timeout_cancels_with_grace_then_force(self) -> None:
        executor = DockerExecutor({})
        commands: list[list[str]] = []

        def _run(command, **_kwargs):
            argv = [str(part) for part in command]
            commands.append(argv)

            class _Result:
                def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
                    self.returncode = returncode
                    self.stdout = stdout
                    self.stderr = stderr

            if "create" in argv:
                return _Result(0, stdout="container-123\n")
            if "start" in argv:
                return _Result(0, stdout="container-123\n")
            if "wait" in argv:
                raise subprocess.TimeoutExpired(command, timeout=1)
            return _Result(0)

        with patch("services.execution.docker_executor.subprocess.run", side_effect=_run):
            with self.assertRaises(_DockerDispatchFailure) as exc_info:
                executor._dispatch_via_cli(
                    request=_request(),
                    docker_host="unix:///var/run/docker.sock",
                    docker_image="llmctl-executor:latest",
                    docker_network="",
                    docker_pull_policy="never",
                    payload_json="{}",
                    execution_timeout=1,
                    cancel_grace_timeout=9,
                    cancel_force_kill=True,
                )

        self.assertEqual("dispatch_timeout", exc_info.exception.fallback_reason)
        flattened = [" ".join(argv) for argv in commands]
        self.assertTrue(any(" stop --time 9 container-123" in item for item in flattened))
        self.assertTrue(any(" kill container-123" in item for item in flattened))
        self.assertTrue(any(" rm -f container-123" in item for item in flattened))

    def test_api_ensure_image_reports_image_pull_failure(self) -> None:
        executor = DockerExecutor({})

        def _run(_command, **_kwargs):
            class _Result:
                returncode = 1
                stdout = ""
                stderr = "pull access denied"

            return _Result()

        with patch("services.execution.docker_executor.subprocess.run", side_effect=_run):
            with self.assertRaises(_DockerDispatchFailure) as exc_info:
                executor._api_ensure_image(
                    socket_path="/var/run/docker.sock",
                    image="llmctl-executor:latest",
                    pull_policy="always",
                    timeout=5,
                    docker_host="unix:///var/run/docker.sock",
                )
        self.assertEqual("image_pull_failed", exc_info.exception.fallback_reason)

    def test_execute_api_timeout_records_timeout_category_and_fallback(self) -> None:
        settings = {
            "fallback_enabled": "true",
            "fallback_on_dispatch_error": "true",
            "fallback_provider": "workspace",
        }
        executor = DockerExecutor(settings)
        executor._prune_stopped_executor_containers = (  # type: ignore[method-assign]
            lambda _docker_host: None
        )
        executor._dispatch_via_api = (  # type: ignore[method-assign]
            lambda **_kwargs: (_ for _ in ()).throw(
                _DockerApiUnavailable("timeout", "Docker API ping timed out.")
            )
        )
        executor._cli_fallback_precondition = lambda _docker_host: False  # type: ignore[method-assign]

        callback_called = {"value": False}

        def _callback(_request: ExecutionRequest):
            callback_called["value"] = True
            return {"node_type": "start", "message": "ok"}, {}

        result = executor.execute(_request(), _callback)
        self.assertTrue(callback_called["value"])
        self.assertEqual("success", result.status)
        self.assertEqual("workspace", result.run_metadata.get("final_provider"))
        self.assertEqual("provider_unavailable", result.run_metadata.get("fallback_reason"))
        self.assertEqual("timeout", result.run_metadata.get("api_failure_category"))


if __name__ == "__main__":
    unittest.main()
