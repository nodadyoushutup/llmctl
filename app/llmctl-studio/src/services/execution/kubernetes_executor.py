from __future__ import annotations

import json
import logging
import os
import shutil
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from services.execution.contracts import (
    EXECUTION_CONTRACT_VERSION,
    EXECUTION_DISPATCH_FALLBACK_STARTED,
    EXECUTION_DISPATCH_CONFIRMED,
    EXECUTION_DISPATCH_FAILED,
    EXECUTION_PROVIDER_WORKSPACE,
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
_DEFAULT_JOB_TTL_SECONDS = 24 * 3600


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
        dispatch_timeout = _as_int(
            settings.get("dispatch_timeout_seconds"),
            default=60,
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
        fallback_enabled = _as_bool(settings.get("fallback_enabled"), default=True)
        fallback_on_dispatch_error = _as_bool(
            settings.get("fallback_on_dispatch_error"),
            default=True,
        )
        fallback_provider = str(settings.get("fallback_provider") or "workspace").strip().lower()
        fallback_allowed = (
            fallback_enabled
            and fallback_on_dispatch_error
            and fallback_provider == "workspace"
            and not request.fallback_attempted
            and not request.dispatch_uncertain
        )

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
            )
        except _KubernetesDispatchFailure as exc:
            provider_dispatch_id = (
                f"kubernetes:{namespace}/{exc.job_name}" if exc.job_name else None
            )
            if fallback_allowed and not exc.dispatch_uncertain:
                return self._execute_workspace_fallback(
                    request=request,
                    execute_callback=execute_callback,
                    started_at=started_at,
                    fallback_reason=exc.fallback_reason,
                    provider_dispatch_id=provider_dispatch_id,
                    dispatch_failure_message=exc.message,
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
            )

        remote_status = str((outcome.executor_result or {}).get("status") or "").strip().lower()
        if remote_status and remote_status != EXECUTION_STATUS_SUCCESS:
            message = (
                "Kubernetes executor returned non-success status "
                f"'{remote_status or 'unknown'}'."
            )
            return self._execution_failed_after_confirmed_result(
                request=request,
                started_at=started_at,
                message=message,
                provider_dispatch_id=provider_dispatch_id,
                fallback_attempted=request.fallback_attempted,
                fallback_reason=request.fallback_reason,
                stdout=outcome.stdout,
                stderr=outcome.stderr,
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
            )

        output_state, routing_state = execute_callback(request)
        finished_at = _utcnow()
        run_metadata = {
            "selected_provider": self.provider,
            "final_provider": self.provider,
            "provider_dispatch_id": provider_dispatch_id,
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
            "k8s_job_name": outcome.job_name,
            "k8s_pod_name": outcome.pod_name or "",
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
    ) -> _KubernetesDispatchOutcome:
        kubeconfig_path: str | None = None
        try:
            kubectl_args, kubeconfig_path = self._kubectl_context_args(
                namespace=namespace,
                in_cluster=in_cluster,
                kubeconfig=kubeconfig,
            )
            self._kubectl_preflight(kubectl_args, dispatch_timeout=dispatch_timeout)
            self._prune_completed_jobs(kubectl_args)
            payload_json = self._build_executor_payload_json(
                request=request,
                execution_timeout=execution_timeout,
            )
            job_name = self._job_name(request)
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
    ) -> dict[str, Any]:
        labels = self._job_labels(request)
        resources: dict[str, dict[str, str]] = {
            "requests": {"cpu": "100m", "memory": "128Mi"},
            "limits": {"cpu": "1", "memory": "1Gi"},
        }
        if k8s_gpu_limit > 0:
            resources["limits"]["nvidia.com/gpu"] = str(k8s_gpu_limit)
        template_spec: dict[str, Any] = {
            "restartPolicy": "Never",
            "containers": [
                {
                    "name": "executor",
                    "image": image,
                    "env": [
                        {
                            "name": "LLMCTL_EXECUTOR_PAYLOAD_JSON",
                            "value": payload_json,
                        }
                    ],
                    "resources": resources,
                }
            ],
            "activeDeadlineSeconds": max(5, min(execution_timeout, 24 * 3600)),
        }
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
            },
            "spec": {
                "backoffLimit": 0,
                "ttlSecondsAfterFinished": _DEFAULT_JOB_TTL_SECONDS,
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
        payload = {
            "contract_version": "v1",
            "result_contract_version": "v1",
            "provider": self.provider,
            "request_id": f"flowchart-node-{request.node_id}-run-{request.execution_id}",
            "command": ["/bin/bash", "-lc", "echo llmctl-kubernetes-dispatch-ok"],
            "timeout_seconds": max(5, min(execution_timeout, 3600)),
            "emit_start_markers": True,
            "metadata": {
                "flowchart_node_id": request.node_id,
                "execution_id": request.execution_id,
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
                    terminal = self._job_terminal_status(kubectl_args, job_name=job_name)
                    if terminal == "complete":
                        return _KubernetesDispatchOutcome(
                            job_name=job_name,
                            pod_name=pod_name,
                            stdout=latest_stdout,
                            stderr=latest_stderr,
                            startup_marker_seen=startup_seen,
                            executor_result=executor_result,
                        )
                    if terminal == "failed":
                        raise _KubernetesDispatchFailure(
                            fallback_reason="create_failed",
                            message=f"Kubernetes job '{job_name}' failed before completion.",
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
        payload = self._kubectl_json(kubectl_args, ["get", "job", job_name])
        status = payload.get("status")
        if not isinstance(status, dict):
            return ""
        if int(status.get("succeeded") or 0) > 0:
            return "complete"
        if int(status.get("failed") or 0) > 0:
            return "failed"
        conditions = status.get("conditions")
        if not isinstance(conditions, list):
            return ""
        for condition in conditions:
            if not isinstance(condition, dict):
                continue
            if str(condition.get("status") or "").lower() != "true":
                continue
            condition_type = str(condition.get("type") or "").strip().lower()
            if condition_type == "complete":
                return "complete"
            if condition_type == "failed":
                return "failed"
        return ""

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

    def _prune_completed_jobs(self, kubectl_args: list[str]) -> None:
        try:
            jobs = self._list_executor_jobs(kubectl_args)
        except _KubernetesDispatchFailure:
            return
        cutoff = _utcnow() - timedelta(seconds=_DEFAULT_JOB_TTL_SECONDS)
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

    def _execute_workspace_fallback(
        self,
        *,
        request: ExecutionRequest,
        execute_callback,
        started_at: datetime,
        fallback_reason: str,
        provider_dispatch_id: str | None,
        dispatch_failure_message: str,
    ) -> ExecutionResult:
        fallback_request = replace(
            request,
            selected_provider=self.provider,
            final_provider=EXECUTION_PROVIDER_WORKSPACE,
            provider_dispatch_id=f"workspace:workspace-{request.execution_id}",
            dispatch_status=EXECUTION_DISPATCH_FALLBACK_STARTED,
            fallback_attempted=True,
            fallback_reason=fallback_reason,
            dispatch_uncertain=False,
            api_failure_category=None,
            cli_fallback_used=False,
            cli_preflight_passed=None,
        )
        fallback_dispatch_id = str(fallback_request.provider_dispatch_id or "").strip()
        if fallback_dispatch_id and not register_dispatch_key(
            request.execution_id,
            fallback_dispatch_id,
        ):
            return self._dispatch_failed_result(
                request=request,
                started_at=started_at,
                message=(
                    "Duplicate fallback dispatch detected for this node run; "
                    "refusing to execute callback twice."
                ),
                provider_dispatch_id=fallback_dispatch_id,
                dispatch_submitted=True,
                dispatch_uncertain=True,
                fallback_attempted=True,
                fallback_reason=fallback_reason,
                stdout="",
                stderr="",
            )
        try:
            output_state, routing_state = execute_callback(fallback_request)
        except Exception as exc:
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
                    "code": "execution_error",
                    "message": f"Workspace fallback execution failed: {exc}",
                    "retryable": False,
                },
                provider_metadata={
                    "executor_provider": self.provider,
                    "selected_provider": self.provider,
                    "final_provider": EXECUTION_PROVIDER_WORKSPACE,
                    "dispatch_failure": dispatch_failure_message,
                    "fallback_reason": fallback_reason,
                },
                output_state={},
                routing_state={},
                run_metadata={
                    "selected_provider": self.provider,
                    "final_provider": EXECUTION_PROVIDER_WORKSPACE,
                    "provider_dispatch_id": fallback_request.provider_dispatch_id,
                    "workspace_identity": request.workspace_identity,
                    "dispatch_status": EXECUTION_DISPATCH_FAILED,
                    "fallback_attempted": True,
                    "fallback_reason": fallback_reason,
                    "dispatch_uncertain": False,
                    "api_failure_category": None,
                    "cli_fallback_used": False,
                    "cli_preflight_passed": None,
                },
            )

        finished_at = _utcnow()
        return ExecutionResult(
            contract_version=EXECUTION_CONTRACT_VERSION,
            status=EXECUTION_STATUS_SUCCESS,
            exit_code=0,
            started_at=started_at,
            finished_at=finished_at,
            stdout="",
            stderr="",
            error=None,
            provider_metadata={
                "executor_provider": self.provider,
                "selected_provider": self.provider,
                "final_provider": EXECUTION_PROVIDER_WORKSPACE,
                "dispatch_failure": dispatch_failure_message,
                "fallback_reason": fallback_reason,
                "prior_provider_dispatch_id": provider_dispatch_id,
            },
            output_state=output_state,
            routing_state=routing_state,
            run_metadata={
                "selected_provider": self.provider,
                "final_provider": EXECUTION_PROVIDER_WORKSPACE,
                "provider_dispatch_id": fallback_request.provider_dispatch_id,
                "workspace_identity": request.workspace_identity,
                "dispatch_status": EXECUTION_DISPATCH_CONFIRMED,
                "fallback_attempted": True,
                "fallback_reason": fallback_reason,
                "dispatch_uncertain": False,
                "api_failure_category": None,
                "cli_fallback_used": False,
                "cli_preflight_passed": None,
            },
        )

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
            },
            output_state={},
            routing_state={},
            run_metadata={
                "selected_provider": self.provider,
                "final_provider": self.provider,
                "provider_dispatch_id": provider_dispatch_id,
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
            },
            output_state={},
            routing_state={},
            run_metadata={
                "selected_provider": self.provider,
                "final_provider": self.provider,
                "provider_dispatch_id": provider_dispatch_id,
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
