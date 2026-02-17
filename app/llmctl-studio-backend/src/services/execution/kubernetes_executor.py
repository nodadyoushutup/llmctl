from __future__ import annotations

import json
import logging
import os
import shutil
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from services.execution.contracts import (
    EXECUTION_CONTRACT_VERSION,
    EXECUTION_DISPATCH_CONFIRMED,
    EXECUTION_DISPATCH_FAILED,
    EXECUTION_STATUS_FAILED,
    EXECUTION_STATUS_SUCCESS,
    ExecutionRequest,
    ExecutionResult,
)
from services.execution.idempotency import register_dispatch_key

logger = logging.getLogger(__name__)

_EXECUTOR_LABEL_KEY = "llmctl.executor"
_EXECUTOR_LABEL_VALUE = "true"
_RESULT_PREFIX = "LLMCTL_EXECUTOR_RESULT_JSON="
_START_MARKER_LITERAL = "LLMCTL_EXECUTOR_STARTED"
_DEFAULT_JOB_TTL_SECONDS = 1800
_EXECUTOR_LIVE_CODE_ENABLED_ENV = "LLMCTL_NODE_EXECUTOR_K8S_LIVE_CODE_ENABLED"
_EXECUTOR_LIVE_CODE_HOST_PATH_ENV = "LLMCTL_NODE_EXECUTOR_K8S_LIVE_CODE_HOST_PATH"
_EXECUTOR_LIVE_CODE_HOST_PATH_DEFAULT = "/workspace/llmctl"
_EXECUTOR_ARGOCD_APP_NAME_ENV = "LLMCTL_NODE_EXECUTOR_K8S_ARGOCD_APP_NAME"
_EXECUTOR_ARGOCD_APP_NAME_DEFAULT = "llmctl-studio"
_ARGOCD_INSTANCE_LABEL_KEY = "app.kubernetes.io/instance"
_ARGOCD_TRACKING_ID_ANNOTATION_KEY = "argocd.argoproj.io/tracking-id"
_ARGOCD_COMPARE_OPTIONS_ANNOTATION_KEY = "argocd.argoproj.io/compare-options"
_ARGOCD_IGNORE_EXTRANEOUS_COMPARE_OPTION = "IgnoreExtraneous"
_POD_ENV_ALLOWLIST = {
    "LLMCTL_STUDIO_DATABASE_URI",
    "LLMCTL_POSTGRES_HOST",
    "LLMCTL_POSTGRES_PORT",
    "LLMCTL_POSTGRES_DB",
    "LLMCTL_POSTGRES_USER",
    "LLMCTL_POSTGRES_PASSWORD",
    "LLMCTL_STUDIO_DATA_DIR",
    "LLMCTL_STUDIO_WORKSPACES_DIR",
}
_POD_ENV_PREFIX_ALLOWLIST = (
    "LLMCTL_",
    "FLASK_",
    "OPENAI_",
    "ANTHROPIC_",
    "GOOGLE_",
    "GEMINI_",
    "CLAUDE_",
    "CODEX_",
    "VLLM_",
    "CHROMA_",
    "HF_",
    "HUGGINGFACE_",
    "GITHUB_",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_bool(value: str | None, *, default: bool = False) -> bool:
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _as_int(
    value: str | None,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(str(value or "").strip())
    except ValueError:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _sanitize_k8s_name(value: str) -> str:
    lowered = str(value or "").strip().lower()
    safe = "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in lowered)
    safe = safe.strip("-")
    if not safe:
        safe = "llmctl-executor"
    if len(safe) > 63:
        safe = safe[:63].rstrip("-")
    return safe or "llmctl-executor"


def _parse_iso8601(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_image_pull_secrets(value: str | None) -> list[dict[str, str]]:
    raw = str(value or "").strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    secrets: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in payload:
        name = ""
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            name = str(item.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        secrets.append({"name": name})
    return secrets


@dataclass
class _KubernetesDispatchOutcome:
    job_name: str
    pod_name: str | None
    stdout: str
    stderr: str
    startup_marker_seen: bool
    executor_result: dict[str, Any] | None
    terminal_reason: str | None


class _KubernetesDispatchFailure(Exception):
    def __init__(
        self,
        *,
        fallback_reason: str,
        message: str,
        job_name: str | None = None,
        pod_name: str | None = None,
        dispatch_submitted: bool = False,
        dispatch_uncertain: bool = False,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        super().__init__(message)
        self.fallback_reason = fallback_reason
        self.message = message
        self.job_name = job_name
        self.pod_name = pod_name
        self.dispatch_submitted = dispatch_submitted
        self.dispatch_uncertain = dispatch_uncertain
        self.stdout = stdout
        self.stderr = stderr


class KubernetesExecutor:
    provider = "kubernetes"

    def __init__(self, runtime_settings: dict[str, str] | None = None) -> None:
        self._settings = runtime_settings or {}

    def execute(
        self,
        request: ExecutionRequest,
        execute_callback,
    ) -> ExecutionResult:
        del execute_callback
        started_at = _utcnow()
        settings = self._settings
        namespace = str(settings.get("k8s_namespace") or "default").strip() or "default"
        image = str(settings.get("k8s_image") or "llmctl-executor:latest")
        in_cluster = _as_bool(settings.get("k8s_in_cluster"), default=False)
        service_account = str(settings.get("k8s_service_account") or "").strip()
        kubeconfig = str(settings.get("k8s_kubeconfig") or "")
        image_pull_secrets = _parse_image_pull_secrets(
            settings.get("k8s_image_pull_secrets_json")
        )
        k8s_gpu_limit = _as_int(
            settings.get("k8s_gpu_limit"),
            default=0,
            minimum=0,
            maximum=8,
        )
        job_ttl_seconds = _as_int(
            settings.get("k8s_job_ttl_seconds"),
            default=_DEFAULT_JOB_TTL_SECONDS,
            minimum=60,
            maximum=24 * 3600,
        )
        dispatch_timeout = _as_int(
            settings.get("dispatch_timeout_seconds"),
            default=300,
            minimum=5,
            maximum=3600,
        )
        execution_timeout = _as_int(
            settings.get("execution_timeout_seconds"),
            default=1800,
            minimum=5,
            maximum=24 * 3600,
        )
        log_collection_timeout = _as_int(
            settings.get("log_collection_timeout_seconds"),
            default=30,
            minimum=1,
            maximum=600,
        )
        cancel_grace_timeout = _as_int(
            settings.get("cancel_grace_timeout_seconds"),
            default=15,
            minimum=1,
            maximum=600,
        )
        cancel_force_kill = _as_bool(
            settings.get("cancel_force_kill_enabled"),
            default=True,
        )
        live_code_enabled = _as_bool(
            os.getenv(
                _EXECUTOR_LIVE_CODE_ENABLED_ENV,
                settings.get("k8s_live_code_enabled"),
            ),
            default=False,
        )
        live_code_host_path = str(
            os.getenv(
                _EXECUTOR_LIVE_CODE_HOST_PATH_ENV,
                settings.get("k8s_live_code_host_path")
                or _EXECUTOR_LIVE_CODE_HOST_PATH_DEFAULT,
            )
            or ""
        ).strip()
        argocd_app_name = str(
            settings.get("k8s_argocd_app_name")
            or os.getenv(_EXECUTOR_ARGOCD_APP_NAME_ENV)
            or _EXECUTOR_ARGOCD_APP_NAME_DEFAULT
        ).strip()

        try:
            outcome = self._dispatch_via_kubernetes(
                request=request,
                namespace=namespace,
                image=image,
                in_cluster=in_cluster,
                service_account=service_account,
                kubeconfig=kubeconfig,
                image_pull_secrets=image_pull_secrets,
                k8s_gpu_limit=k8s_gpu_limit,
                dispatch_timeout=dispatch_timeout,
                execution_timeout=execution_timeout,
                log_collection_timeout=log_collection_timeout,
                cancel_grace_timeout=cancel_grace_timeout,
                cancel_force_kill=cancel_force_kill,
                job_ttl_seconds=job_ttl_seconds,
                live_code_enabled=live_code_enabled,
                live_code_host_path=live_code_host_path,
                argocd_app_name=argocd_app_name,
            )
        except _KubernetesDispatchFailure as exc:
            provider_dispatch_id = (
                f"kubernetes:{namespace}/{exc.job_name}" if exc.job_name else None
            )
            return self._dispatch_failed_result(
                request=request,
                started_at=started_at,
                message=exc.message,
                provider_dispatch_id=provider_dispatch_id,
                dispatch_submitted=exc.dispatch_submitted,
                dispatch_uncertain=exc.dispatch_uncertain,
                fallback_attempted=request.fallback_attempted,
                fallback_reason=request.fallback_reason,
                stdout=exc.stdout,
                stderr=exc.stderr,
                job_name=exc.job_name,
                pod_name=exc.pod_name,
                terminal_reason=exc.message,
            )

        provider_dispatch_id = f"kubernetes:{namespace}/{outcome.job_name}"
        if not outcome.startup_marker_seen:
            message = "Kubernetes execution did not emit a valid startup marker."
            # Ambiguous remote state is fail-closed and never auto-falls back.
            return self._dispatch_failed_result(
                request=request,
                started_at=started_at,
                message=message,
                provider_dispatch_id=provider_dispatch_id,
                dispatch_submitted=True,
                dispatch_uncertain=True,
                fallback_attempted=request.fallback_attempted,
                fallback_reason=request.fallback_reason,
                stdout=outcome.stdout,
                stderr=outcome.stderr,
                job_name=outcome.job_name,
                pod_name=outcome.pod_name,
                terminal_reason=outcome.terminal_reason,
            )

        remote_status = str((outcome.executor_result or {}).get("status") or "").strip().lower()
        if remote_status and remote_status != EXECUTION_STATUS_SUCCESS:
            remote_error_message = ""
            remote_error = (outcome.executor_result or {}).get("error")
            if isinstance(remote_error, dict):
                remote_error_message = str(remote_error.get("message") or "").strip()
            message = (
                "Kubernetes executor returned non-success status "
                f"'{remote_status or 'unknown'}'."
            )
            if remote_error_message:
                message = f"{message} {remote_error_message}"
            return self._execution_failed_after_confirmed_result(
                request=request,
                started_at=started_at,
                message=message,
                provider_dispatch_id=provider_dispatch_id,
                fallback_attempted=request.fallback_attempted,
                fallback_reason=request.fallback_reason,
                stdout=outcome.stdout,
                stderr=outcome.stderr,
                job_name=outcome.job_name,
                pod_name=outcome.pod_name,
                terminal_reason=outcome.terminal_reason,
            )

        if not register_dispatch_key(request.execution_id, provider_dispatch_id):
            return self._dispatch_failed_result(
                request=request,
                started_at=started_at,
                message=(
                    "Duplicate dispatch detected for this node run/provider dispatch id; "
                    "refusing to execute callback twice."
                ),
                provider_dispatch_id=provider_dispatch_id,
                dispatch_submitted=True,
                dispatch_uncertain=True,
                fallback_attempted=request.fallback_attempted,
                fallback_reason=request.fallback_reason,
                stdout=outcome.stdout,
                stderr=outcome.stderr,
                job_name=outcome.job_name,
                pod_name=outcome.pod_name,
                terminal_reason=outcome.terminal_reason,
            )

        output_state, routing_state, parse_error = self._extract_remote_node_states(
            outcome.executor_result
        )
        if parse_error:
            return self._execution_failed_after_confirmed_result(
                request=request,
                started_at=started_at,
                message=parse_error,
                provider_dispatch_id=provider_dispatch_id,
                fallback_attempted=request.fallback_attempted,
                fallback_reason=request.fallback_reason,
                stdout=outcome.stdout,
                stderr=outcome.stderr,
                job_name=outcome.job_name,
                pod_name=outcome.pod_name,
                terminal_reason=outcome.terminal_reason,
            )

        finished_at = _utcnow()
        run_metadata = {
            "selected_provider": self.provider,
            "final_provider": self.provider,
            "provider_dispatch_id": provider_dispatch_id,
            "k8s_job_name": outcome.job_name,
            "k8s_pod_name": outcome.pod_name or "",
            "k8s_terminal_reason": outcome.terminal_reason or "",
            "workspace_identity": request.workspace_identity,
            "dispatch_status": EXECUTION_DISPATCH_CONFIRMED,
            "fallback_attempted": False,
            "fallback_reason": None,
            "dispatch_uncertain": False,
            "api_failure_category": None,
            "cli_fallback_used": False,
            "cli_preflight_passed": None,
        }
        provider_metadata = {
            "executor_provider": self.provider,
            "selected_provider": request.selected_provider,
            "final_provider": self.provider,
            "provider_dispatch_id": provider_dispatch_id,
            "workspace_identity": request.workspace_identity,
            "k8s_namespace": namespace,
            "k8s_gpu_limit": str(k8s_gpu_limit),
            "k8s_live_code_enabled": "true" if live_code_enabled else "false",
            "k8s_live_code_host_path": live_code_host_path if live_code_enabled else "",
            "k8s_job_name": outcome.job_name,
            "k8s_pod_name": outcome.pod_name or "",
            "k8s_terminal_reason": outcome.terminal_reason or "",
            "startup_marker_seen": outcome.startup_marker_seen,
        }
        if outcome.executor_result is not None:
            provider_metadata["executor_result"] = outcome.executor_result
        return ExecutionResult(
            contract_version=EXECUTION_CONTRACT_VERSION,
            status=EXECUTION_STATUS_SUCCESS,
            exit_code=0,
            started_at=started_at,
            finished_at=finished_at,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            error=None,
            provider_metadata=provider_metadata,
            output_state=output_state,
            routing_state=routing_state,
            run_metadata=run_metadata,
            metrics={
                "dispatch_mode": "kubernetes_api",
            },
        )

    def _dispatch_via_kubernetes(
        self,
        *,
        request: ExecutionRequest,
        namespace: str,
        image: str,
        in_cluster: bool,
        service_account: str,
        kubeconfig: str,
        image_pull_secrets: list[dict[str, str]],
        k8s_gpu_limit: int,
        dispatch_timeout: int,
        execution_timeout: int,
        log_collection_timeout: int,
        cancel_grace_timeout: int,
        cancel_force_kill: bool,
        job_ttl_seconds: int,
        live_code_enabled: bool,
        live_code_host_path: str,
        argocd_app_name: str,
    ) -> _KubernetesDispatchOutcome:
        kubeconfig_path: str | None = None
        try:
            kubectl_args, kubeconfig_path = self._kubectl_context_args(
                namespace=namespace,
                in_cluster=in_cluster,
                kubeconfig=kubeconfig,
            )
            self._kubectl_preflight(kubectl_args, dispatch_timeout=dispatch_timeout)
            self._prune_completed_jobs(
                kubectl_args,
                job_ttl_seconds=job_ttl_seconds,
            )
            job_name = self._job_name(request)
            payload_json = self._build_executor_payload_json(
                request=request,
                execution_timeout=execution_timeout,
            )
            manifest = self._build_job_manifest(
                request=request,
                job_name=job_name,
                namespace=namespace,
                image=image,
                payload_json=payload_json,
                service_account=service_account,
                image_pull_secrets=image_pull_secrets,
                k8s_gpu_limit=k8s_gpu_limit,
                execution_timeout=execution_timeout,
                job_ttl_seconds=job_ttl_seconds,
                live_code_enabled=live_code_enabled,
                live_code_host_path=live_code_host_path,
                argocd_app_name=argocd_app_name,
            )
            self._kubectl_apply_manifest(
                kubectl_args,
                manifest=manifest,
                timeout=dispatch_timeout,
            )
            return self._wait_for_job_completion(
                kubectl_args,
                job_name=job_name,
                dispatch_timeout=dispatch_timeout,
                execution_timeout=execution_timeout,
                log_collection_timeout=log_collection_timeout,
                cancel_grace_timeout=cancel_grace_timeout,
                cancel_force_kill=cancel_force_kill,
            )
        finally:
            if kubeconfig_path:
                try:
                    os.remove(kubeconfig_path)
                except OSError:
                    pass

    def _kubectl_context_args(
        self,
        *,
        namespace: str,
        in_cluster: bool,
        kubeconfig: str,
    ) -> tuple[list[str], str | None]:
        args = ["--namespace", namespace]
        if in_cluster:
            return args, None
        kubeconfig_text = str(kubeconfig or "").strip()
        if not kubeconfig_text:
            raise _KubernetesDispatchFailure(
                fallback_reason="config_error",
                message=(
                    "Kubernetes out-of-cluster mode requires kubeconfig. "
                    "Set Runtime -> Node Runtime -> Kubernetes Kubeconfig."
                ),
            )
        fd, path = tempfile.mkstemp(prefix="llmctl-kubeconfig-", suffix=".yaml")
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(kubeconfig_text)
        except OSError as exc:
            try:
                os.close(fd)
            except OSError:
                pass
            raise _KubernetesDispatchFailure(
                fallback_reason="config_error",
                message=f"Failed to prepare kubeconfig for runtime use: {exc}",
            ) from exc
        args.extend(["--kubeconfig", path])
        return args, path

    def _kubectl_preflight(self, kubectl_args: list[str], *, dispatch_timeout: int) -> None:
        if shutil.which("kubectl") is None:
            raise _KubernetesDispatchFailure(
                fallback_reason="provider_unavailable",
                message="kubectl command is not installed or not available on PATH.",
            )
        version = subprocess.run(
            ["kubectl", *kubectl_args, "version", "--client=true", "--output=json"],
            capture_output=True,
            text=True,
            timeout=max(5, dispatch_timeout),
            check=False,
        )
        if version.returncode != 0:
            message = (version.stderr or version.stdout or "").strip()
            raise _KubernetesDispatchFailure(
                fallback_reason=self._categorize_kubectl_failure(message),
                message=f"Kubernetes client preflight failed: {message}",
            )
        cluster = subprocess.run(
            ["kubectl", *kubectl_args, "cluster-info"],
            capture_output=True,
            text=True,
            timeout=max(5, dispatch_timeout),
            check=False,
        )
        if cluster.returncode != 0:
            message = (cluster.stderr or cluster.stdout or "").strip()
            raise _KubernetesDispatchFailure(
                fallback_reason=self._categorize_kubectl_failure(message),
                message=f"Kubernetes cluster preflight failed: {message}",
            )

    def _categorize_kubectl_failure(self, message: str) -> str:
        lowered = str(message or "").lower()
        if "no configuration has been provided" in lowered or "kubeconfig" in lowered:
            return "config_error"
        if "forbidden" in lowered or "unauthorized" in lowered:
            return "config_error"
        if "timed out" in lowered:
            return "dispatch_timeout"
        if "connection refused" in lowered or "no such host" in lowered:
            return "provider_unavailable"
        return "provider_unavailable"

    def _job_name(self, request: ExecutionRequest) -> str:
        return _sanitize_k8s_name(
            f"llmctl-exec-{request.node_id}-{request.execution_id}"
        )

    def _job_labels(self, request: ExecutionRequest) -> dict[str, str]:
        return {
            _EXECUTOR_LABEL_KEY: _EXECUTOR_LABEL_VALUE,
            "llmctl.provider": self.provider,
            "llmctl.flowchart.node_id": str(request.node_id),
            "llmctl.flowchart.execution_id": str(request.execution_id),
            "llmctl.workspace_identity": request.workspace_identity,
        }

    def _executor_runtime_env_entries(self) -> list[dict[str, str]]:
        env_entries: list[dict[str, str]] = []
        for key in sorted(os.environ):
            if key == "LLMCTL_EXECUTOR_PAYLOAD_JSON":
                continue
            if key in _POD_ENV_ALLOWLIST or any(
                key.startswith(prefix) for prefix in _POD_ENV_PREFIX_ALLOWLIST
            ):
                value = str(os.environ.get(key) or "")
                env_entries.append({"name": key, "value": value})
        return env_entries

    def _build_job_manifest(
        self,
        *,
        request: ExecutionRequest,
        job_name: str,
        namespace: str,
        image: str,
        payload_json: str,
        service_account: str,
        image_pull_secrets: list[dict[str, str]],
        k8s_gpu_limit: int,
        execution_timeout: int,
        job_ttl_seconds: int,
        live_code_enabled: bool = False,
        live_code_host_path: str = "",
        argocd_app_name: str = "",
    ) -> dict[str, Any]:
        labels = dict(self._job_labels(request))
        metadata_annotations: dict[str, str] = {}
        if argocd_app_name:
            labels[_ARGOCD_INSTANCE_LABEL_KEY] = argocd_app_name
            metadata_annotations[_ARGOCD_TRACKING_ID_ANNOTATION_KEY] = (
                f"{argocd_app_name}:batch/Job:{namespace}/{job_name}"
            )
            metadata_annotations[_ARGOCD_COMPARE_OPTIONS_ANNOTATION_KEY] = (
                _ARGOCD_IGNORE_EXTRANEOUS_COMPARE_OPTION
            )
        resources: dict[str, dict[str, str]] = {
            "requests": {"cpu": "100m", "memory": "128Mi"},
            "limits": {"cpu": "1", "memory": "1Gi"},
        }
        if k8s_gpu_limit > 0:
            resources["limits"]["nvidia.com/gpu"] = str(k8s_gpu_limit)
        container_spec: dict[str, Any] = {
            "name": "executor",
            "image": image,
            "imagePullPolicy": "IfNotPresent",
            "env": [
                {
                    "name": "LLMCTL_EXECUTOR_PAYLOAD_JSON",
                    "value": payload_json,
                }
            ]
            + self._executor_runtime_env_entries(),
            "resources": resources,
        }
        template_spec: dict[str, Any] = {
            "restartPolicy": "Never",
            "containers": [container_spec],
            "activeDeadlineSeconds": max(5, min(execution_timeout, 24 * 3600)),
        }
        if live_code_enabled and live_code_host_path:
            container_spec["volumeMounts"] = [
                {"name": "project-code", "mountPath": "/app"}
            ]
            template_spec["volumes"] = [
                {
                    "name": "project-code",
                    "hostPath": {
                        "path": live_code_host_path,
                        "type": "Directory",
                    },
                }
            ]
        if service_account:
            template_spec["serviceAccountName"] = service_account
        if image_pull_secrets:
            template_spec["imagePullSecrets"] = image_pull_secrets
        return {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {
                "name": job_name,
                "namespace": namespace,
                "labels": labels,
                "annotations": metadata_annotations,
            },
            "spec": {
                "backoffLimit": 0,
                "ttlSecondsAfterFinished": max(60, min(job_ttl_seconds, 24 * 3600)),
                "template": {
                    "metadata": {"labels": labels},
                    "spec": template_spec,
                },
            },
        }

    def _build_executor_payload_json(
        self,
        *,
        request: ExecutionRequest,
        execution_timeout: int,
    ) -> str:
        node_request_payload = {
            "node_id": int(request.node_id),
            "node_type": str(request.node_type or ""),
            "node_ref_id": int(request.node_ref_id) if request.node_ref_id is not None else None,
            "node_config": request.node_config if isinstance(request.node_config, dict) else {},
            "input_context": (
                request.input_context if isinstance(request.input_context, dict) else {}
            ),
            "execution_id": int(request.execution_id),
            "execution_task_id": (
                int(request.execution_task_id)
                if request.execution_task_id is not None
                else None
            ),
            "execution_index": int(request.execution_index),
            "enabled_providers": sorted(
                str(item).strip().lower()
                for item in request.enabled_providers
                if str(item).strip()
            ),
            "default_model_id": (
                int(request.default_model_id) if request.default_model_id is not None else None
            ),
            "mcp_server_keys": [
                str(item).strip()
                for item in request.mcp_server_keys
                if str(item).strip()
            ],
        }
        execution_mode = "flowchart_node_in_pod"
        request_id = f"flowchart-node-{request.node_id}-run-{request.execution_id}"
        if str(request.node_type or "").strip().lower() == "agent_task":
            execution_mode = "agent_task_in_pod"
            task_id = int(request.execution_task_id or request.execution_id)
            request_id = f"agent-task-{task_id}"

        payload = {
            "contract_version": "v1",
            "result_contract_version": "v1",
            "provider": self.provider,
            "request_id": request_id,
            "timeout_seconds": max(5, min(execution_timeout, 3600)),
            "emit_start_markers": True,
            "node_execution": {
                "entrypoint": "services.tasks:_execute_flowchart_node_request",
                "python_paths": ["/app/app/llmctl-studio-backend/src"],
                "request": node_request_payload,
                "request_context": {
                    "execution_contract_version": EXECUTION_CONTRACT_VERSION,
                },
            },
            "metadata": {
                "flowchart_node_id": request.node_id,
                "execution_id": request.execution_id,
                "execution_mode": execution_mode,
            },
        }
        return json.dumps(payload, separators=(",", ":"))

    def _kubectl_apply_manifest(
        self,
        kubectl_args: list[str],
        *,
        manifest: dict[str, Any],
        timeout: int,
    ) -> None:
        completed = subprocess.run(
            ["kubectl", *kubectl_args, "apply", "-f", "-"],
            capture_output=True,
            text=True,
            input=json.dumps(manifest),
            timeout=max(5, timeout),
            check=False,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "").strip()
            raise _KubernetesDispatchFailure(
                fallback_reason=self._categorize_kubectl_failure(message),
                message=f"Kubernetes job create/apply failed: {message}",
                job_name=str(manifest.get("metadata", {}).get("name") or ""),
                dispatch_submitted=False,
            )

    def _wait_for_job_completion(
        self,
        kubectl_args: list[str],
        *,
        job_name: str,
        dispatch_timeout: int,
        execution_timeout: int,
        log_collection_timeout: int,
        cancel_grace_timeout: int,
        cancel_force_kill: bool,
    ) -> _KubernetesDispatchOutcome:
        started_monotonic = time.monotonic()
        dispatch_deadline = started_monotonic + float(dispatch_timeout)
        execution_deadline = started_monotonic + float(execution_timeout)
        latest_stdout = ""
        latest_stderr = ""
        pod_name: str | None = None

        try:
            while True:
                now = time.monotonic()
                if now > execution_deadline:
                    self._cancel_job(
                        kubectl_args,
                        job_name=job_name,
                        cancel_grace_timeout=cancel_grace_timeout,
                        cancel_force_kill=cancel_force_kill,
                    )
                    raise _KubernetesDispatchFailure(
                        fallback_reason="dispatch_timeout",
                        message=f"Kubernetes job timed out after {execution_timeout} seconds.",
                        job_name=job_name,
                        pod_name=pod_name,
                        dispatch_submitted=True,
                        stdout=latest_stdout,
                        stderr=latest_stderr,
                    )

                pod_name = self._resolve_job_pod_name(kubectl_args, job_name=job_name)
                terminal_status, terminal_reason = self._job_terminal_status_with_reason(
                    kubectl_args,
                    job_name=job_name,
                    pod_name=pod_name,
                )
                if pod_name:
                    logs = self._read_pod_logs(
                        kubectl_args,
                        pod_name=pod_name,
                        timeout=log_collection_timeout,
                    )
                    if logs:
                        latest_stdout = logs
                    startup_seen, executor_result = self._parse_executor_logs(
                        latest_stdout,
                        latest_stderr,
                    )
                    if terminal_status == "complete":
                        return _KubernetesDispatchOutcome(
                            job_name=job_name,
                            pod_name=pod_name,
                            stdout=latest_stdout,
                            stderr=latest_stderr,
                            startup_marker_seen=startup_seen,
                            executor_result=executor_result,
                            terminal_reason=terminal_reason,
                        )
                    if terminal_status == "failed":
                        if executor_result is not None:
                            return _KubernetesDispatchOutcome(
                                job_name=job_name,
                                pod_name=pod_name,
                                stdout=latest_stdout,
                                stderr=latest_stderr,
                                startup_marker_seen=startup_seen,
                                executor_result=executor_result,
                                terminal_reason=terminal_reason,
                            )
                        raise _KubernetesDispatchFailure(
                            fallback_reason="create_failed",
                            message=(
                                f"Kubernetes job '{job_name}' failed before completion. "
                                f"{terminal_reason or ''}"
                            ).strip(),
                            job_name=job_name,
                            pod_name=pod_name,
                            dispatch_submitted=True,
                            stdout=latest_stdout,
                            stderr=latest_stderr,
                        )

                if now > dispatch_deadline:
                    self._cancel_job(
                        kubectl_args,
                        job_name=job_name,
                        cancel_grace_timeout=cancel_grace_timeout,
                        cancel_force_kill=cancel_force_kill,
                    )
                    raise _KubernetesDispatchFailure(
                        fallback_reason="dispatch_timeout",
                        message=(
                            f"Kubernetes job '{job_name}' did not confirm startup within "
                            f"{dispatch_timeout} seconds."
                        ),
                        job_name=job_name,
                        pod_name=pod_name,
                        dispatch_submitted=True,
                        stdout=latest_stdout,
                        stderr=latest_stderr,
                    )

                if terminal_status == "failed":
                    raise _KubernetesDispatchFailure(
                        fallback_reason="create_failed",
                        message=(
                            f"Kubernetes job '{job_name}' failed before completion. "
                            f"{terminal_reason or ''}"
                        ).strip(),
                        job_name=job_name,
                        pod_name=pod_name,
                        dispatch_submitted=True,
                        stdout=latest_stdout,
                        stderr=latest_stderr,
                    )
                if terminal_status == "complete":
                    startup_seen, executor_result = self._parse_executor_logs(
                        latest_stdout,
                        latest_stderr,
                    )
                    return _KubernetesDispatchOutcome(
                        job_name=job_name,
                        pod_name=pod_name,
                        stdout=latest_stdout,
                        stderr=latest_stderr,
                        startup_marker_seen=startup_seen,
                        executor_result=executor_result,
                        terminal_reason=terminal_reason,
                    )

                time.sleep(1.0)
        except _KubernetesDispatchFailure as exc:
            if exc.dispatch_submitted:
                raise
            raise _KubernetesDispatchFailure(
                fallback_reason=exc.fallback_reason,
                message=exc.message,
                job_name=exc.job_name or job_name,
                pod_name=exc.pod_name,
                dispatch_submitted=True,
                dispatch_uncertain=exc.dispatch_uncertain,
                stdout=exc.stdout or latest_stdout,
                stderr=exc.stderr or latest_stderr,
            ) from exc

    def _kubectl_json(
        self,
        kubectl_args: list[str],
        command: list[str],
    ) -> dict[str, Any]:
        completed = subprocess.run(
            ["kubectl", *kubectl_args, *command, "-o", "json"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "").strip()
            raise _KubernetesDispatchFailure(
                fallback_reason=self._categorize_kubectl_failure(message),
                message=f"Kubernetes API query failed: {message}",
            )
        text = str(completed.stdout or "").strip()
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise _KubernetesDispatchFailure(
                fallback_reason="provider_unavailable",
                message=f"Kubernetes API returned invalid JSON: {exc}",
            ) from exc
        if not isinstance(payload, dict):
            return {}
        return payload

    def _resolve_job_pod_name(self, kubectl_args: list[str], *, job_name: str) -> str | None:
        payload = self._kubectl_json(
            kubectl_args,
            ["get", "pods", "-l", f"job-name={job_name}"],
        )
        items = payload.get("items")
        if not isinstance(items, list):
            return None
        best_name = ""
        best_started = datetime.min.replace(tzinfo=timezone.utc)
        for item in items:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            status = item.get("status") if isinstance(item.get("status"), dict) else {}
            name = str(metadata.get("name") or "").strip()
            if not name:
                continue
            started = _parse_iso8601(status.get("startTime"))
            if started is None:
                started = datetime.min.replace(tzinfo=timezone.utc)
            if started >= best_started:
                best_started = started
                best_name = name
        return best_name or None

    def _read_pod_logs(
        self,
        kubectl_args: list[str],
        *,
        pod_name: str,
        timeout: int,
    ) -> str:
        completed = subprocess.run(
            ["kubectl", *kubectl_args, "logs", pod_name],
            capture_output=True,
            text=True,
            timeout=max(1, timeout),
            check=False,
        )
        if completed.returncode != 0:
            return ""
        return str(completed.stdout or "")

    def _job_terminal_status(self, kubectl_args: list[str], *, job_name: str) -> str:
        status, _ = self._job_terminal_status_with_reason(
            kubectl_args,
            job_name=job_name,
            pod_name=None,
        )
        return status

    def _job_terminal_status_with_reason(
        self,
        kubectl_args: list[str],
        *,
        job_name: str,
        pod_name: str | None,
    ) -> tuple[str, str | None]:
        payload = self._kubectl_json(kubectl_args, ["get", "job", job_name])
        status = payload.get("status")
        if not isinstance(status, dict):
            return "", None
        if int(status.get("succeeded") or 0) > 0:
            return "complete", self._normalize_terminal_reason(
                kubectl_args=kubectl_args,
                job_name=job_name,
                pod_name=pod_name,
                job_status=status,
            )
        if int(status.get("failed") or 0) > 0:
            return "failed", self._normalize_terminal_reason(
                kubectl_args=kubectl_args,
                job_name=job_name,
                pod_name=pod_name,
                job_status=status,
            )
        conditions = status.get("conditions")
        if not isinstance(conditions, list):
            return "", None
        for condition in conditions:
            if not isinstance(condition, dict):
                continue
            if str(condition.get("status") or "").lower() != "true":
                continue
            condition_type = str(condition.get("type") or "").strip().lower()
            if condition_type == "complete":
                return "complete", self._normalize_terminal_reason(
                    kubectl_args=kubectl_args,
                    job_name=job_name,
                    pod_name=pod_name,
                    job_status=status,
                )
            if condition_type == "failed":
                return "failed", self._normalize_terminal_reason(
                    kubectl_args=kubectl_args,
                    job_name=job_name,
                    pod_name=pod_name,
                    job_status=status,
                )
        return "", None

    def _normalize_terminal_reason(
        self,
        *,
        kubectl_args: list[str],
        job_name: str,
        pod_name: str | None,
        job_status: dict[str, Any],
    ) -> str | None:
        conditions = job_status.get("conditions")
        if isinstance(conditions, list):
            for condition in conditions:
                if not isinstance(condition, dict):
                    continue
                if str(condition.get("status") or "").lower() != "true":
                    continue
                condition_type = str(condition.get("type") or "").strip()
                reason = str(condition.get("reason") or "").strip()
                message = str(condition.get("message") or "").strip()
                parts = [part for part in [condition_type, reason, message] if part]
                if parts:
                    return " | ".join(parts)
        pod_reason = self._pod_terminal_reason(kubectl_args, pod_name)
        if pod_reason:
            return pod_reason
        if int(job_status.get("succeeded") or 0) > 0:
            return "Complete"
        if int(job_status.get("failed") or 0) > 0:
            return "Failed"
        return None

    def _pod_terminal_reason(
        self,
        kubectl_args: list[str],
        pod_name: str | None,
    ) -> str | None:
        if not pod_name:
            return None
        try:
            payload = self._kubectl_json(kubectl_args, ["get", "pod", pod_name])
        except _KubernetesDispatchFailure:
            return None
        status = payload.get("status")
        if not isinstance(status, dict):
            return None
        phase = str(status.get("phase") or "").strip()
        reason = str(status.get("reason") or "").strip()
        message = str(status.get("message") or "").strip()
        for key in ["containerStatuses", "initContainerStatuses"]:
            entries = status.get(key)
            if not isinstance(entries, list):
                continue
            for item in entries:
                if not isinstance(item, dict):
                    continue
                state = item.get("state")
                if not isinstance(state, dict):
                    continue
                for state_name in ["terminated", "waiting"]:
                    state_payload = state.get(state_name)
                    if not isinstance(state_payload, dict):
                        continue
                    state_reason = str(state_payload.get("reason") or "").strip()
                    state_message = str(state_payload.get("message") or "").strip()
                    if state_reason or state_message:
                        parts = [part for part in [phase, state_reason, state_message] if part]
                        return " | ".join(parts)
        parts = [part for part in [phase, reason, message] if part]
        if parts:
            return " | ".join(parts)
        return None

    def _cancel_job(
        self,
        kubectl_args: list[str],
        *,
        job_name: str,
        cancel_grace_timeout: int,
        cancel_force_kill: bool,
    ) -> None:
        subprocess.run(
            [
                "kubectl",
                *kubectl_args,
                "delete",
                "job",
                job_name,
                "--ignore-not-found=true",
                "--wait=true",
                "--grace-period",
                str(max(1, cancel_grace_timeout)),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if cancel_force_kill:
            subprocess.run(
                [
                    "kubectl",
                    *kubectl_args,
                    "delete",
                    "job",
                    job_name,
                    "--ignore-not-found=true",
                    "--wait=false",
                    "--grace-period",
                    "0",
                    "--force",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

    def _list_executor_jobs(self, kubectl_args: list[str]) -> list[dict[str, Any]]:
        payload = self._kubectl_json(
            kubectl_args,
            ["get", "jobs", "-l", f"{_EXECUTOR_LABEL_KEY}={_EXECUTOR_LABEL_VALUE}"],
        )
        items = payload.get("items")
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    def _delete_job(self, kubectl_args: list[str], *, job_name: str) -> None:
        subprocess.run(
            [
                "kubectl",
                *kubectl_args,
                "delete",
                "job",
                job_name,
                "--ignore-not-found=true",
                "--wait=false",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def _prune_completed_jobs(
        self,
        kubectl_args: list[str],
        *,
        job_ttl_seconds: int,
    ) -> None:
        try:
            jobs = self._list_executor_jobs(kubectl_args)
        except _KubernetesDispatchFailure:
            return
        cutoff = _utcnow() - timedelta(seconds=max(60, int(job_ttl_seconds)))
        for job in jobs:
            metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
            status = job.get("status") if isinstance(job.get("status"), dict) else {}
            job_name = str(metadata.get("name") or "").strip()
            if not job_name:
                continue
            completed_at = _parse_iso8601(status.get("completionTime"))
            if completed_at is None:
                continue
            if completed_at <= cutoff:
                self._delete_job(kubectl_args, job_name=job_name)

    def _parse_executor_logs(
        self,
        stdout: str,
        stderr: str,
    ) -> tuple[bool, dict[str, Any] | None]:
        startup_seen = False
        executor_result: dict[str, Any] | None = None
        for line in [*(stdout or "").splitlines(), *(stderr or "").splitlines()]:
            cleaned = line.strip()
            if not cleaned:
                continue
            if cleaned == _START_MARKER_LITERAL:
                startup_seen = True
                continue
            if cleaned.startswith("{") and '"event"' in cleaned:
                try:
                    payload = json.loads(cleaned)
                except json.JSONDecodeError:
                    payload = {}
                if (
                    str(payload.get("event") or "").strip() == "executor_started"
                    and str(payload.get("contract_version") or "").strip() == "v1"
                ):
                    startup_seen = True
                continue
            if cleaned.startswith(_RESULT_PREFIX):
                raw_payload = cleaned[len(_RESULT_PREFIX) :]
                try:
                    executor_result = json.loads(raw_payload)
                except json.JSONDecodeError:
                    executor_result = None
        return startup_seen, executor_result

    def _extract_remote_node_states(
        self,
        executor_result: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any], str | None]:
        if not isinstance(executor_result, dict):
            return {}, {}, "Kubernetes executor did not return a structured result payload."
        output_state = executor_result.get("output_state")
        routing_state = executor_result.get("routing_state")
        if not isinstance(output_state, dict) or not isinstance(routing_state, dict):
            artifacts = executor_result.get("artifacts")
            if isinstance(artifacts, dict):
                node_execution = artifacts.get("node_execution")
                if isinstance(node_execution, dict):
                    if not isinstance(output_state, dict):
                        nested_output = node_execution.get("output_state")
                        if isinstance(nested_output, dict):
                            output_state = nested_output
                    if not isinstance(routing_state, dict):
                        nested_routing = node_execution.get("routing_state")
                        if isinstance(nested_routing, dict):
                            routing_state = nested_routing
        if not isinstance(output_state, dict):
            return {}, {}, "Kubernetes executor result is missing output_state."
        if not isinstance(routing_state, dict):
            return {}, {}, "Kubernetes executor result is missing routing_state."
        return output_state, routing_state, None

    def _dispatch_failed_result(
        self,
        *,
        request: ExecutionRequest,
        started_at: datetime,
        message: str,
        provider_dispatch_id: str | None,
        dispatch_submitted: bool,
        dispatch_uncertain: bool,
        fallback_attempted: bool,
        fallback_reason: str | None,
        stdout: str,
        stderr: str,
        job_name: str | None = None,
        pod_name: str | None = None,
        terminal_reason: str | None = None,
    ) -> ExecutionResult:
        finished_at = _utcnow()
        dispatch_status = EXECUTION_DISPATCH_FAILED
        if dispatch_submitted:
            dispatch_status = EXECUTION_DISPATCH_FAILED
        if dispatch_uncertain:
            fallback_attempted = False
            fallback_reason = None
        return ExecutionResult(
            contract_version=EXECUTION_CONTRACT_VERSION,
            status=EXECUTION_STATUS_FAILED,
            exit_code=1,
            started_at=started_at,
            finished_at=finished_at,
            stdout=stdout,
            stderr=stderr,
            error={
                "code": "dispatch_error",
                "message": message,
                "retryable": True,
            },
            provider_metadata={
                "executor_provider": self.provider,
                "selected_provider": self.provider,
                "final_provider": self.provider,
                "provider_dispatch_id": provider_dispatch_id,
                "k8s_job_name": job_name or "",
                "k8s_pod_name": pod_name or "",
                "k8s_terminal_reason": terminal_reason or "",
            },
            output_state={},
            routing_state={},
            run_metadata={
                "selected_provider": self.provider,
                "final_provider": self.provider,
                "provider_dispatch_id": provider_dispatch_id,
                "k8s_job_name": job_name or "",
                "k8s_pod_name": pod_name or "",
                "k8s_terminal_reason": terminal_reason or "",
                "workspace_identity": request.workspace_identity,
                "dispatch_status": dispatch_status,
                "fallback_attempted": fallback_attempted,
                "fallback_reason": fallback_reason if fallback_attempted else None,
                "dispatch_uncertain": dispatch_uncertain,
                "api_failure_category": None,
                "cli_fallback_used": False,
                "cli_preflight_passed": None,
            },
        )

    def _execution_failed_after_confirmed_result(
        self,
        *,
        request: ExecutionRequest,
        started_at: datetime,
        message: str,
        provider_dispatch_id: str,
        fallback_attempted: bool,
        fallback_reason: str | None,
        stdout: str,
        stderr: str,
        job_name: str | None = None,
        pod_name: str | None = None,
        terminal_reason: str | None = None,
    ) -> ExecutionResult:
        finished_at = _utcnow()
        return ExecutionResult(
            contract_version=EXECUTION_CONTRACT_VERSION,
            status=EXECUTION_STATUS_FAILED,
            exit_code=1,
            started_at=started_at,
            finished_at=finished_at,
            stdout=stdout,
            stderr=stderr,
            error={
                "code": "execution_error",
                "message": message,
                "retryable": False,
            },
            provider_metadata={
                "executor_provider": self.provider,
                "selected_provider": self.provider,
                "final_provider": self.provider,
                "provider_dispatch_id": provider_dispatch_id,
                "k8s_job_name": job_name or "",
                "k8s_pod_name": pod_name or "",
                "k8s_terminal_reason": terminal_reason or "",
            },
            output_state={},
            routing_state={},
            run_metadata={
                "selected_provider": self.provider,
                "final_provider": self.provider,
                "provider_dispatch_id": provider_dispatch_id,
                "k8s_job_name": job_name or "",
                "k8s_pod_name": pod_name or "",
                "k8s_terminal_reason": terminal_reason or "",
                "workspace_identity": request.workspace_identity,
                "dispatch_status": EXECUTION_DISPATCH_CONFIRMED,
                "fallback_attempted": fallback_attempted,
                "fallback_reason": fallback_reason if fallback_attempted else None,
                "dispatch_uncertain": False,
                "api_failure_category": None,
                "cli_fallback_used": False,
                "cli_preflight_passed": None,
            },
        )
