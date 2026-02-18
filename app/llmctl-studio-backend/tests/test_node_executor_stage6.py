from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault(
    "LLMCTL_STUDIO_DATABASE_URI",
    "postgresql+psycopg://llmctl:llmctl@127.0.0.1:15432/llmctl_studio",
)

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

from services.execution.contracts import ExecutionRequest
from services.execution.kubernetes_executor import (
    KubernetesExecutor,
    _KubernetesDispatchFailure,
    _KubernetesDispatchOutcome,
    _utcnow,
)
from services.execution.idempotency import clear_dispatch_registry
from services.execution.router import ExecutionRouter


def _request() -> ExecutionRequest:
    return ExecutionRequest(
        node_id=12,
        node_type="start",
        node_ref_id=None,
        node_config={},
        input_context={},
        execution_id=111,
        execution_task_id=222,
        execution_index=1,
        enabled_providers=set(),
        default_model_id=None,
        mcp_server_keys=[],
    )


class _StubKubernetesExecutor:
    def __init__(self, result) -> None:
        self.called = False
        self.last_request: ExecutionRequest | None = None
        self._result = result

    def execute(self, request: ExecutionRequest, execute_callback):
        self.called = True
        self.last_request = request
        return self._result(request, execute_callback)


class NodeExecutorStage6Tests(unittest.TestCase):
    def setUp(self) -> None:
        clear_dispatch_registry()

    def test_kubernetes_executor_dispatch_failure_returns_failed(self) -> None:
        executor = KubernetesExecutor({})

        def _dispatch_failure(**_kwargs):
            raise _KubernetesDispatchFailure(
                fallback_reason="provider_unavailable",
                message="kubernetes unavailable",
            )

        executor._dispatch_via_kubernetes = _dispatch_failure  # type: ignore[method-assign]

        callback_called = {"value": False}

        def _callback(_request: ExecutionRequest):
            callback_called["value"] = True
            return {"node_type": "start", "message": "ok"}, {}

        result = executor.execute(_request(), _callback)
        self.assertFalse(callback_called["value"])
        self.assertEqual("failed", result.status)
        self.assertEqual("kubernetes", result.run_metadata.get("selected_provider"))
        self.assertEqual("kubernetes", result.run_metadata.get("final_provider"))
        self.assertEqual("dispatch_failed", result.run_metadata.get("dispatch_status"))
        self.assertFalse(bool(result.run_metadata.get("fallback_attempted")))
        self.assertIsNone(result.run_metadata.get("fallback_reason"))

    def test_router_uses_kubernetes_executor_when_provider_is_kubernetes(self) -> None:
        settings = {
            "provider": "kubernetes",
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
                provider_metadata={"provider": "kubernetes"},
                output_state=output_state,
                routing_state=routing_state,
                run_metadata={
                    "selected_provider": "kubernetes",
                    "final_provider": "kubernetes",
                    "provider_dispatch_id": "kubernetes:default/job-x",
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

        stub = _StubKubernetesExecutor(_stub_result)
        router = ExecutionRouter(runtime_settings=settings, kubernetes_executor=stub)  # type: ignore[arg-type]
        request = router.route_request(_request())
        self.assertEqual("kubernetes", request.selected_provider)
        self.assertEqual("dispatch_pending", request.dispatch_status)
        self.assertEqual("workspace-main", request.workspace_identity)

        result = router.execute_routed(request, lambda _request: ({"ok": True}, {}))
        self.assertTrue(stub.called)
        self.assertEqual("success", result.status)
        self.assertEqual("kubernetes", result.run_metadata.get("final_provider"))

    def test_router_coerces_unknown_provider_to_kubernetes(self) -> None:
        router = ExecutionRouter(runtime_settings={"provider": "workspace"})
        routed = router.route_request(_request())
        self.assertEqual("kubernetes", routed.selected_provider)
        self.assertEqual("kubernetes", routed.final_provider)

    def test_kubernetes_executor_requires_kubeconfig_when_not_in_cluster(self) -> None:
        settings = {
            "k8s_in_cluster": "false",
            "k8s_kubeconfig": "",
        }
        executor = KubernetesExecutor(settings)
        callback_called = {"value": False}

        def _callback(_request: ExecutionRequest):
            callback_called["value"] = True
            return {"ok": True}, {}

        result = executor.execute(_request(), _callback)
        self.assertFalse(callback_called["value"])
        self.assertEqual("failed", result.status)
        self.assertEqual("dispatch_failed", result.run_metadata.get("dispatch_status"))
        self.assertIn("requires kubeconfig", str(result.error.get("message") if result.error else ""))

    def test_kubernetes_executor_uses_runtime_image_tag_for_spawned_job_image(self) -> None:
        settings = {
            "k8s_in_cluster": "true",
            "k8s_image": "ghcr.io/acme/llmctl-executor:latest",
            "k8s_image_tag": "v2026.02.18",
        }
        executor = KubernetesExecutor(settings)
        captured = {"image": ""}
        executor._dispatch_via_kubernetes = (  # type: ignore[method-assign]
            lambda **kwargs: captured.update({"image": str(kwargs.get("image") or "")})
            or _KubernetesDispatchOutcome(
                job_name="job-tag-1",
                pod_name="pod-tag-1",
                stdout="",
                stderr="",
                startup_marker_seen=True,
                executor_result={
                    "status": "success",
                    "output_state": {"node_type": "start"},
                    "routing_state": {},
                },
                terminal_reason="Complete",
            )
        )
        result = executor.execute(_request(), lambda _request: ({"local": True}, {}))
        self.assertEqual("success", result.status)
        self.assertEqual(
            "ghcr.io/acme/llmctl-executor:v2026.02.18",
            captured["image"],
        )

    def test_job_name_differs_for_same_node_and_execution_across_task_domains(self) -> None:
        executor = KubernetesExecutor({})
        flowchart_request = ExecutionRequest(
            node_id=1,
            node_type="start",
            node_ref_id=None,
            node_config={},
            input_context={},
            execution_id=25,
            execution_task_id=88,
            execution_index=1,
            enabled_providers=set(),
            default_model_id=None,
            mcp_server_keys=[],
        )
        quick_request = ExecutionRequest(
            node_id=1,
            node_type="rag",
            node_ref_id=None,
            node_config={},
            input_context={},
            execution_id=25,
            execution_task_id=25,
            execution_index=1,
            enabled_providers=set(),
            default_model_id=None,
            mcp_server_keys=[],
        )

        flowchart_job = executor._job_name(flowchart_request)
        quick_job = executor._job_name(quick_request)

        self.assertNotEqual(flowchart_job, quick_job)
        self.assertTrue(flowchart_job.startswith("llmctl-exec-"))
        self.assertTrue(quick_job.startswith("llmctl-exec-"))

    def test_cancel_job_uses_grace_then_force(self) -> None:
        executor = KubernetesExecutor({})
        commands: list[list[str]] = []

        def _record_command(*args, **kwargs):
            command = list(args[0])
            commands.append(command)

            class _Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return _Result()

        with patch("services.execution.kubernetes_executor.subprocess.run", side_effect=_record_command):
            executor._cancel_job(
                ["--namespace", "default"],
                job_name="job-x",
                cancel_grace_timeout=7,
                cancel_force_kill=True,
            )

        self.assertEqual(2, len(commands))
        self.assertIn("--grace-period", commands[0])
        self.assertIn("7", commands[0])
        self.assertIn("--force", commands[1])
        self.assertIn("0", commands[1])

    def test_prune_completed_jobs_deletes_old_jobs(self) -> None:
        executor = KubernetesExecutor({})
        old_completion = (_utcnow() - timedelta(hours=30)).isoformat().replace("+00:00", "Z")
        recent_completion = (_utcnow() - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        deleted: list[str] = []

        executor._list_executor_jobs = lambda _args: [  # type: ignore[method-assign]
            {
                "metadata": {"name": "job-old"},
                "status": {"completionTime": old_completion},
            },
            {
                "metadata": {"name": "job-recent"},
                "status": {"completionTime": recent_completion},
            },
        ]
        executor._delete_job = lambda _args, *, job_name: deleted.append(job_name)  # type: ignore[method-assign]

        executor._prune_completed_jobs(
            ["--namespace", "default"],
            job_ttl_seconds=7200,
        )
        self.assertEqual(["job-old"], deleted)

    def test_build_job_manifest_includes_gpu_limit_when_configured(self) -> None:
        executor = KubernetesExecutor({})
        manifest = executor._build_job_manifest(
            request=_request(),
            job_name="job-gpu",
            namespace="default",
            image="llmctl-executor:latest",
            payload_json="{}",
            service_account="",
            image_pull_secrets=[],
            k8s_gpu_limit=2,
            execution_timeout=120,
            job_ttl_seconds=1200,
        )
        limits = (
            manifest["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"]
        )
        self.assertEqual("2", limits.get("nvidia.com/gpu"))

    def test_build_job_manifest_omits_gpu_limit_when_disabled(self) -> None:
        executor = KubernetesExecutor({})
        manifest = executor._build_job_manifest(
            request=_request(),
            job_name="job-cpu",
            namespace="default",
            image="llmctl-executor:latest",
            payload_json="{}",
            service_account="",
            image_pull_secrets=[],
            k8s_gpu_limit=0,
            execution_timeout=120,
            job_ttl_seconds=1800,
        )
        limits = (
            manifest["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"]
        )
        container = manifest["spec"]["template"]["spec"]["containers"][0]
        self.assertNotIn("nvidia.com/gpu", limits)
        self.assertEqual("IfNotPresent", container.get("imagePullPolicy"))
        self.assertEqual(1800, manifest["spec"]["ttlSecondsAfterFinished"])

    def test_build_job_manifest_adds_project_mount_when_live_code_enabled(self) -> None:
        executor = KubernetesExecutor({})
        manifest = executor._build_job_manifest(
            request=_request(),
            job_name="job-live-code",
            namespace="default",
            image="llmctl-executor:latest",
            payload_json="{}",
            service_account="",
            image_pull_secrets=[],
            k8s_gpu_limit=0,
            execution_timeout=120,
            job_ttl_seconds=1800,
            live_code_enabled=True,
            live_code_host_path="/workspace/llmctl",
        )
        pod_spec = manifest["spec"]["template"]["spec"]
        self.assertEqual(
            "/workspace/llmctl",
            pod_spec["volumes"][0]["hostPath"]["path"],
        )
        self.assertEqual(
            "/app",
            pod_spec["containers"][0]["volumeMounts"][0]["mountPath"],
        )

    def test_build_job_manifest_includes_runtime_env_passthrough(self) -> None:
        executor = KubernetesExecutor({})
        with patch.dict(
            os.environ,
            {
                "LLMCTL_STUDIO_DATABASE_URI": "postgresql+psycopg://user:pw@db:5432/studio",
                "OPENAI_API_KEY": "test-key",
            },
            clear=False,
        ):
            manifest = executor._build_job_manifest(
                request=_request(),
                job_name="job-env-pass",
                namespace="default",
                image="llmctl-executor:latest",
                payload_json="{}",
                service_account="",
                image_pull_secrets=[],
                k8s_gpu_limit=0,
                execution_timeout=120,
                job_ttl_seconds=1800,
            )
        env_entries = manifest["spec"]["template"]["spec"]["containers"][0]["env"]
        env_map = {entry.get("name"): entry.get("value") for entry in env_entries}
        self.assertEqual("{}", env_map.get("LLMCTL_EXECUTOR_PAYLOAD_JSON"))
        self.assertEqual(
            "postgresql+psycopg://user:pw@db:5432/studio",
            env_map.get("LLMCTL_STUDIO_DATABASE_URI"),
        )
        self.assertEqual("test-key", env_map.get("OPENAI_API_KEY"))

    def test_build_job_manifest_includes_argocd_tracking_metadata(self) -> None:
        executor = KubernetesExecutor({})
        manifest = executor._build_job_manifest(
            request=_request(),
            job_name="job-argocd",
            namespace="llmctl",
            image="llmctl-executor:latest",
            payload_json="{}",
            service_account="",
            image_pull_secrets=[],
            k8s_gpu_limit=0,
            execution_timeout=120,
            job_ttl_seconds=1800,
            argocd_app_name="llmctl-studio",
        )
        metadata = manifest.get("metadata") or {}
        labels = metadata.get("labels") or {}
        annotations = metadata.get("annotations") or {}
        self.assertEqual("llmctl-studio", labels.get("app.kubernetes.io/instance"))
        self.assertEqual(
            "llmctl-studio:batch/Job:llmctl/job-argocd",
            annotations.get("argocd.argoproj.io/tracking-id"),
        )
        self.assertEqual(
            "IgnoreExtraneous",
            annotations.get("argocd.argoproj.io/compare-options"),
        )

    def test_build_executor_payload_contains_full_node_request(self) -> None:
        executor = KubernetesExecutor({})
        payload_json = executor._build_executor_payload_json(
            request=_request(),
            execution_timeout=900,
        )
        payload = json.loads(payload_json)
        self.assertEqual("v1", payload.get("contract_version"))
        self.assertNotIn("command", payload)
        node_execution = payload.get("node_execution") or {}
        self.assertEqual(
            "services.tasks:_execute_flowchart_node_request",
            node_execution.get("entrypoint"),
        )
        node_request = node_execution.get("request") or {}
        self.assertEqual(12, node_request.get("node_id"))
        self.assertEqual("start", node_request.get("node_type"))
        self.assertEqual([], node_request.get("enabled_providers"))
        self.assertEqual([], node_request.get("mcp_server_keys"))

    def test_kubernetes_executor_uses_remote_output_state_and_metadata(self) -> None:
        executor = KubernetesExecutor({})
        executor._dispatch_via_kubernetes = (  # type: ignore[method-assign]
            lambda **_kwargs: _KubernetesDispatchOutcome(
                job_name="job-remote-1",
                pod_name="pod-remote-1",
                stdout="executor stdout",
                stderr="",
                startup_marker_seen=True,
                executor_result={
                    "status": "success",
                    "output_state": {"node_type": "start", "message": "remote"},
                    "routing_state": {"route_key": "next"},
                },
                terminal_reason="Complete",
            )
        )
        callback_called = {"value": False}

        def _callback(_request: ExecutionRequest):
            callback_called["value"] = True
            return {"node_type": "start", "message": "local"}, {}

        result = executor.execute(_request(), _callback)
        self.assertFalse(callback_called["value"])
        self.assertEqual("success", result.status)
        self.assertEqual("remote", result.output_state.get("message"))
        self.assertEqual("next", result.routing_state.get("route_key"))
        self.assertEqual(
            "kubernetes:default/job-remote-1",
            result.run_metadata.get("provider_dispatch_id"),
        )
        self.assertEqual("job-remote-1", result.run_metadata.get("k8s_job_name"))
        self.assertEqual("pod-remote-1", result.run_metadata.get("k8s_pod_name"))
        self.assertEqual("Complete", result.run_metadata.get("k8s_terminal_reason"))
        self.assertEqual("job-remote-1", result.provider_metadata.get("k8s_job_name"))
        self.assertEqual("pod-remote-1", result.provider_metadata.get("k8s_pod_name"))
        self.assertEqual("Complete", result.provider_metadata.get("k8s_terminal_reason"))

    def test_kubernetes_executor_fails_when_remote_output_state_missing(self) -> None:
        executor = KubernetesExecutor({})
        executor._dispatch_via_kubernetes = (  # type: ignore[method-assign]
            lambda **_kwargs: _KubernetesDispatchOutcome(
                job_name="job-remote-2",
                pod_name="pod-remote-2",
                stdout="executor stdout",
                stderr="",
                startup_marker_seen=True,
                executor_result={
                    "status": "success",
                    "routing_state": {"route_key": "next"},
                },
                terminal_reason="Complete",
            )
        )

        result = executor.execute(_request(), lambda _request: ({"local": True}, {}))
        self.assertEqual("failed", result.status)
        self.assertEqual("execution_error", (result.error or {}).get("code"))
        self.assertIn(
            "missing output_state",
            str((result.error or {}).get("message") or ""),
        )
        self.assertEqual("job-remote-2", result.run_metadata.get("k8s_job_name"))
        self.assertEqual("pod-remote-2", result.run_metadata.get("k8s_pod_name"))
        self.assertEqual("Complete", result.run_metadata.get("k8s_terminal_reason"))

    def test_kubernetes_executor_surfaces_remote_failure_message(self) -> None:
        executor = KubernetesExecutor({})
        executor._dispatch_via_kubernetes = (  # type: ignore[method-assign]
            lambda **_kwargs: _KubernetesDispatchOutcome(
                job_name="job-remote-3",
                pod_name="pod-remote-3",
                stdout="",
                stderr="",
                startup_marker_seen=True,
                executor_result={
                    "status": "failed",
                    "error": {
                        "message": "Node execution failed: No module named 'sqlalchemy'",
                    },
                },
                terminal_reason="BackoffLimitExceeded",
            )
        )

        result = executor.execute(_request(), lambda _request: ({"local": True}, {}))
        self.assertEqual("failed", result.status)
        self.assertEqual("execution_error", (result.error or {}).get("code"))
        message = str((result.error or {}).get("message") or "")
        self.assertIn("non-success status 'failed'", message)
        self.assertIn("No module named 'sqlalchemy'", message)


if __name__ == "__main__":
    unittest.main()
