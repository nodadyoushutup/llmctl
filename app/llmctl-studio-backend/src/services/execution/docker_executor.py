from __future__ import annotations

import json
import logging
import os
import stat
import subprocess
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from services.execution.contracts import (
    EXECUTION_CONTRACT_VERSION,
    EXECUTION_DISPATCH_FALLBACK_STARTED,
    EXECUTION_DISPATCH_CONFIRMED,
    EXECUTION_DISPATCH_FAILED,
    EXECUTION_DISPATCH_SUBMITTED,
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


def _sanitize_container_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in value)
    cleaned = cleaned.strip("-_.")
    if not cleaned:
        cleaned = "llmctl-executor"
    return cleaned[:120]


def _extract_socket_path(docker_host: str) -> str:
    normalized = str(docker_host or "").strip()
    if not normalized:
        return "/var/run/docker.sock"
    if normalized.startswith("unix://"):
        return normalized[len("unix://") :]
    return ""


def _docker_host_args(docker_host: str) -> list[str]:
    host = str(docker_host or "").strip()
    if not host:
        return []
    return ["-H", host]


def _categorize_api_unavailable_error(message: str) -> str:
    lowered = (message or "").lower()
    if "no such file or directory" in lowered:
        return "socket_missing"
    if "permission denied" in lowered:
        return "auth_error"
    if "timed out" in lowered or "operation timed out" in lowered:
        return "timeout"
    if "tls" in lowered or "certificate" in lowered:
        return "tls_error"
    if "failed to connect" in lowered or "connection refused" in lowered:
        return "socket_unreachable"
    return "api_unreachable"


def _split_combined_logs(raw: str) -> tuple[str, str]:
    text = str(raw or "")
    if not text:
        return "", ""
    return text, ""


def _decode_docker_log_stream(raw: bytes) -> tuple[str, str]:
    if not raw:
        return "", ""
    stdout_parts: list[bytes] = []
    stderr_parts: list[bytes] = []
    index = 0
    total = len(raw)
    while index + 8 <= total:
        stream_type = raw[index]
        frame_size = int.from_bytes(raw[index + 4 : index + 8], "big")
        frame_start = index + 8
        frame_end = frame_start + frame_size
        if frame_end > total:
            break
        frame = raw[frame_start:frame_end]
        if stream_type == 2:
            stderr_parts.append(frame)
        else:
            stdout_parts.append(frame)
        index = frame_end
    if index == 0:
        plain = raw.decode("utf-8", errors="replace")
        return plain, ""
    stdout_text = b"".join(stdout_parts).decode("utf-8", errors="replace")
    stderr_text = b"".join(stderr_parts).decode("utf-8", errors="replace")
    return stdout_text, stderr_text


@dataclass
class _DockerDispatchOutcome:
    dispatch_id: str
    stdout: str
    stderr: str
    api_failure_category: str | None
    cli_fallback_used: bool
    cli_preflight_passed: bool | None
    dispatch_submitted: bool
    startup_marker_seen: bool
    executor_result: dict[str, Any] | None


class _DockerApiUnavailable(Exception):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.message = message


class _DockerDispatchFailure(Exception):
    def __init__(
        self,
        *,
        fallback_reason: str,
        message: str,
        dispatch_id: str | None = None,
        api_failure_category: str | None = None,
        cli_fallback_used: bool = False,
        cli_preflight_passed: bool | None = None,
        startup_marker_seen: bool = False,
        dispatch_submitted: bool = False,
        dispatch_uncertain: bool = False,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        super().__init__(message)
        self.fallback_reason = fallback_reason
        self.message = message
        self.dispatch_id = dispatch_id
        self.api_failure_category = api_failure_category
        self.cli_fallback_used = cli_fallback_used
        self.cli_preflight_passed = cli_preflight_passed
        self.startup_marker_seen = startup_marker_seen
        self.dispatch_submitted = dispatch_submitted
        self.dispatch_uncertain = dispatch_uncertain
        self.stdout = stdout
        self.stderr = stderr


class DockerExecutor:
    provider = "docker"

    def __init__(self, runtime_settings: dict[str, str] | None = None) -> None:
        self._settings = runtime_settings or {}

    def execute(
        self,
        request: ExecutionRequest,
        execute_callback,
    ) -> ExecutionResult:
        started_at = _utcnow()
        settings = self._settings
        docker_host = str(settings.get("docker_host") or "unix:///var/run/docker.sock")
        docker_image = str(settings.get("docker_image") or "llmctl-executor:latest")
        docker_network = str(settings.get("docker_network") or "").strip()
        docker_pull_policy = str(settings.get("docker_pull_policy") or "if_not_present")
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
            outcome = self._dispatch_via_docker(
                request=request,
                docker_host=docker_host,
                docker_image=docker_image,
                docker_network=docker_network,
                docker_pull_policy=docker_pull_policy,
                dispatch_timeout=dispatch_timeout,
                execution_timeout=execution_timeout,
                cancel_grace_timeout=cancel_grace_timeout,
                cancel_force_kill=cancel_force_kill,
            )
        except _DockerDispatchFailure as exc:
            provider_dispatch_id = f"docker:{exc.dispatch_id}" if exc.dispatch_id else None
            if fallback_allowed and not exc.dispatch_uncertain:
                return self._execute_workspace_fallback(
                    request=request,
                    execute_callback=execute_callback,
                    started_at=started_at,
                    fallback_reason=exc.fallback_reason,
                    api_failure_category=exc.api_failure_category,
                    cli_fallback_used=exc.cli_fallback_used,
                    cli_preflight_passed=exc.cli_preflight_passed,
                    provider_dispatch_id=provider_dispatch_id,
                    dispatch_failure_message=exc.message,
                )
            return self._dispatch_failed_result(
                request=request,
                started_at=started_at,
                message=exc.message,
                provider_dispatch_id=provider_dispatch_id,
                api_failure_category=exc.api_failure_category,
                cli_fallback_used=exc.cli_fallback_used,
                cli_preflight_passed=exc.cli_preflight_passed,
                dispatch_submitted=exc.dispatch_submitted,
                dispatch_uncertain=exc.dispatch_uncertain,
                fallback_attempted=request.fallback_attempted,
                fallback_reason=request.fallback_reason,
                stdout=exc.stdout,
                stderr=exc.stderr,
            )

        if not outcome.startup_marker_seen:
            message = "Docker execution did not emit a valid startup marker."
            # Ambiguous remote state is fail-closed and never auto-falls back.
            return self._dispatch_failed_result(
                request=request,
                started_at=started_at,
                message=message,
                provider_dispatch_id=f"docker:{outcome.dispatch_id}",
                api_failure_category=outcome.api_failure_category,
                cli_fallback_used=outcome.cli_fallback_used,
                cli_preflight_passed=outcome.cli_preflight_passed,
                dispatch_submitted=outcome.dispatch_submitted,
                dispatch_uncertain=True,
                fallback_attempted=request.fallback_attempted,
                fallback_reason=request.fallback_reason,
                stdout=outcome.stdout,
                stderr=outcome.stderr,
            )

        remote_status = str((outcome.executor_result or {}).get("status") or "").strip().lower()
        if remote_status and remote_status != EXECUTION_STATUS_SUCCESS:
            message = (
                "Docker executor returned non-success status "
                f"'{remote_status or 'unknown'}'."
            )
            return self._execution_failed_after_confirmed_result(
                request=request,
                started_at=started_at,
                message=message,
                provider_dispatch_id=f"docker:{outcome.dispatch_id}",
                api_failure_category=outcome.api_failure_category,
                cli_fallback_used=outcome.cli_fallback_used,
                cli_preflight_passed=outcome.cli_preflight_passed,
                fallback_attempted=request.fallback_attempted,
                fallback_reason=request.fallback_reason,
                stdout=outcome.stdout,
                stderr=outcome.stderr,
            )

        provider_dispatch_id = f"docker:{outcome.dispatch_id}"
        if not register_dispatch_key(request.execution_id, provider_dispatch_id):
            return self._dispatch_failed_result(
                request=request,
                started_at=started_at,
                message=(
                    "Duplicate dispatch detected for this node run/provider dispatch id; "
                    "refusing to execute callback twice."
                ),
                provider_dispatch_id=provider_dispatch_id,
                api_failure_category=outcome.api_failure_category,
                cli_fallback_used=outcome.cli_fallback_used,
                cli_preflight_passed=outcome.cli_preflight_passed,
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
            "api_failure_category": outcome.api_failure_category,
            "cli_fallback_used": outcome.cli_fallback_used,
            "cli_preflight_passed": (
                outcome.cli_preflight_passed if outcome.cli_fallback_used else None
            ),
        }
        provider_metadata = {
            "executor_provider": self.provider,
            "selected_provider": request.selected_provider,
            "final_provider": self.provider,
            "provider_dispatch_id": provider_dispatch_id,
            "workspace_identity": request.workspace_identity,
            "docker_host": docker_host,
            "docker_image": docker_image,
            "docker_network": docker_network,
            "docker_pull_policy": docker_pull_policy,
            "api_failure_category": outcome.api_failure_category,
            "cli_fallback_used": outcome.cli_fallback_used,
            "cli_preflight_passed": (
                outcome.cli_preflight_passed if outcome.cli_fallback_used else None
            ),
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
                "dispatch_mode": "docker_cli" if outcome.cli_fallback_used else "docker_api",
            },
        )

    def _dispatch_via_docker(
        self,
        *,
        request: ExecutionRequest,
        docker_host: str,
        docker_image: str,
        docker_network: str,
        docker_pull_policy: str,
        dispatch_timeout: int,
        execution_timeout: int,
        cancel_grace_timeout: int,
        cancel_force_kill: bool,
    ) -> _DockerDispatchOutcome:
        dispatch_started_at = time.monotonic()
        self._prune_stopped_executor_containers(docker_host)
        payload_json = self._build_executor_payload_json(
            request=request,
            execution_timeout=execution_timeout,
        )
        api_failure_category: str | None = None
        stall_threshold = _as_int(
            self._settings.get("docker_api_stall_seconds"),
            default=10,
            minimum=5,
            maximum=15,
        )
        cli_reserved_budget = max(1, int(dispatch_timeout * 0.2))
        api_budget = max(1, dispatch_timeout - cli_reserved_budget)

        try:
            return self._dispatch_via_api(
                request=request,
                docker_host=docker_host,
                docker_image=docker_image,
                docker_network=docker_network,
                docker_pull_policy=docker_pull_policy,
                payload_json=payload_json,
                dispatch_timeout=api_budget,
                execution_timeout=min(execution_timeout, api_budget),
                cancel_grace_timeout=cancel_grace_timeout,
                cancel_force_kill=cancel_force_kill,
            )
        except _DockerDispatchFailure as exc:
            elapsed = max(0, int(time.monotonic() - dispatch_started_at))
            remaining_budget = max(0, dispatch_timeout - elapsed)
            if (
                exc.fallback_reason == "dispatch_timeout"
                and elapsed >= stall_threshold
                and remaining_budget >= cli_reserved_budget
            ):
                api_failure_category = "timeout"
                logger.warning(
                    "Docker API path stalled for node %s run %s after %ss; "
                    "switching to CLI fallback with %ss budget remaining.",
                    request.node_id,
                    request.execution_id,
                    elapsed,
                    remaining_budget,
                )
            else:
                raise
        except _DockerApiUnavailable as exc:
            api_failure_category = exc.category
            logger.warning(
                "Docker API path unavailable for node %s run %s: %s (%s).",
                request.node_id,
                request.execution_id,
                exc.message,
                exc.category,
            )

        elapsed_total = max(0, int(time.monotonic() - dispatch_started_at))
        remaining_budget = max(1, dispatch_timeout - elapsed_total)
        if not self._cli_fallback_precondition(docker_host):
            raise _DockerDispatchFailure(
                fallback_reason="provider_unavailable",
                message=(
                    "Docker API is unavailable and CLI fallback precondition failed "
                    "(socket mount/reachability missing)."
                ),
                api_failure_category=api_failure_category or "preflight_failed",
                cli_fallback_used=False,
                cli_preflight_passed=None,
                dispatch_submitted=False,
            )

        try:
            outcome = self._dispatch_via_cli(
                request=request,
                docker_host=docker_host,
                docker_image=docker_image,
                docker_network=docker_network,
                docker_pull_policy=docker_pull_policy,
                payload_json=payload_json,
                execution_timeout=min(execution_timeout, remaining_budget),
                cancel_grace_timeout=cancel_grace_timeout,
                cancel_force_kill=cancel_force_kill,
            )
            outcome.api_failure_category = api_failure_category
            outcome.cli_fallback_used = True
            outcome.cli_preflight_passed = True
            outcome.dispatch_submitted = True
            return outcome
        except _DockerDispatchFailure as exc:
            raise _DockerDispatchFailure(
                fallback_reason=exc.fallback_reason,
                message=exc.message,
                dispatch_id=exc.dispatch_id,
                api_failure_category=api_failure_category or exc.api_failure_category,
                cli_fallback_used=True,
                cli_preflight_passed=True,
                startup_marker_seen=exc.startup_marker_seen,
                dispatch_submitted=exc.dispatch_submitted,
                dispatch_uncertain=exc.dispatch_uncertain,
                stdout=exc.stdout,
                stderr=exc.stderr,
            ) from exc

    def _dispatch_via_api(
        self,
        *,
        request: ExecutionRequest,
        docker_host: str,
        docker_image: str,
        docker_network: str,
        docker_pull_policy: str,
        payload_json: str,
        dispatch_timeout: int,
        execution_timeout: int,
        cancel_grace_timeout: int,
        cancel_force_kill: bool,
    ) -> _DockerDispatchOutcome:
        socket_path = _extract_socket_path(docker_host)
        if not socket_path:
            raise _DockerApiUnavailable(
                "api_unreachable",
                f"Docker API path only supports unix sockets for now (received '{docker_host}').",
            )
        if not os.path.exists(socket_path):
            raise _DockerApiUnavailable(
                "socket_missing",
                f"Docker socket '{socket_path}' does not exist.",
            )
        if not stat_is_socket(socket_path):
            raise _DockerApiUnavailable(
                "socket_missing",
                f"Docker host '{socket_path}' is not a unix socket.",
            )

        self._api_ping(socket_path, timeout=dispatch_timeout)
        self._api_ensure_image(
            socket_path=socket_path,
            image=docker_image,
            pull_policy=docker_pull_policy,
            timeout=dispatch_timeout,
            docker_host=docker_host,
        )

        labels = self._container_labels(request)
        env_pairs = [f"LLMCTL_EXECUTOR_PAYLOAD_JSON={payload_json}"]
        env_pairs.extend(self._runtime_env_pairs())
        container_name = self._container_name(request)
        body: dict[str, Any] = {
            "Image": docker_image,
            "Env": env_pairs,
            "Labels": labels,
            "Tty": False,
            "HostConfig": {},
        }
        if docker_network:
            body["HostConfig"]["NetworkMode"] = docker_network

        create_response = self._api_request(
            socket_path=socket_path,
            method="POST",
            path=f"/containers/create?name={quote(container_name, safe='')}",
            body=body,
            timeout=dispatch_timeout,
        )
        container_id = str((create_response.get("Id") or "")).strip()
        if not container_id:
            raise _DockerDispatchFailure(
                fallback_reason="create_failed",
                message="Docker API create did not return a container id.",
                dispatch_submitted=False,
            )

        try:
            self._api_request(
                socket_path=socket_path,
                method="POST",
                path=f"/containers/{container_id}/start",
                body=None,
                timeout=dispatch_timeout,
            )

            self._api_wait(
                socket_path=socket_path,
                container_id=container_id,
                execution_timeout=execution_timeout,
                cancel_grace_timeout=cancel_grace_timeout,
                cancel_force_kill=cancel_force_kill,
            )
            stdout, stderr = self._api_logs(socket_path=socket_path, container_id=container_id)
            startup_seen, executor_result = self._parse_executor_logs(stdout, stderr)
            return _DockerDispatchOutcome(
                dispatch_id=container_id,
                stdout=stdout,
                stderr=stderr,
                api_failure_category=None,
                cli_fallback_used=False,
                cli_preflight_passed=None,
                dispatch_submitted=True,
                startup_marker_seen=startup_seen,
                executor_result=executor_result,
            )
        finally:
            self._api_remove(socket_path=socket_path, container_id=container_id)

    def _dispatch_via_cli(
        self,
        *,
        request: ExecutionRequest,
        docker_host: str,
        docker_image: str,
        docker_network: str,
        docker_pull_policy: str,
        payload_json: str,
        execution_timeout: int,
        cancel_grace_timeout: int,
        cancel_force_kill: bool,
    ) -> _DockerDispatchOutcome:
        self._cli_ensure_image(
            docker_host=docker_host,
            image=docker_image,
            pull_policy=docker_pull_policy,
        )

        labels = self._container_labels(request)
        container_name = self._container_name(request)
        create_command = ["docker", *_docker_host_args(docker_host), "create", "--name", container_name]
        for key, value in labels.items():
            create_command.extend(["--label", f"{key}={value}"])
        create_command.extend(["--env", f"LLMCTL_EXECUTOR_PAYLOAD_JSON={payload_json}"])
        for env_pair in self._runtime_env_pairs():
            create_command.extend(["--env", env_pair])
        if docker_network:
            create_command.extend(["--network", docker_network])
        create_command.append(docker_image)
        created = subprocess.run(
            create_command,
            capture_output=True,
            text=True,
            check=False,
        )
        if created.returncode != 0:
            diagnostics = self._cli_diagnostics(docker_host=docker_host, container_id=None)
            raise _DockerDispatchFailure(
                fallback_reason="create_failed",
                message=(
                    "Docker CLI create failed: "
                    f"{(created.stderr or created.stdout).strip()} {diagnostics}".strip()
                ),
                dispatch_submitted=False,
            )
        container_id = str(created.stdout or "").strip().splitlines()[0].strip()
        if not container_id:
            raise _DockerDispatchFailure(
                fallback_reason="create_failed",
                message="Docker CLI create returned an empty container id.",
                dispatch_submitted=False,
            )

        try:
            started = subprocess.run(
                ["docker", *_docker_host_args(docker_host), "start", container_id],
                capture_output=True,
                text=True,
                check=False,
            )
            if started.returncode != 0:
                diagnostics = self._cli_diagnostics(
                    docker_host=docker_host,
                    container_id=container_id,
                )
                raise _DockerDispatchFailure(
                    fallback_reason="create_failed",
                    message=(
                        "Docker CLI start failed: "
                        f"{(started.stderr or started.stdout).strip()} {diagnostics}"
                    ),
                    dispatch_id=container_id,
                    dispatch_submitted=True,
                )

            wait_result = subprocess.run(
                ["docker", *_docker_host_args(docker_host), "wait", container_id],
                capture_output=True,
                text=True,
                timeout=execution_timeout,
                check=False,
            )
            if wait_result.returncode != 0:
                diagnostics = self._cli_diagnostics(
                    docker_host=docker_host,
                    container_id=container_id,
                )
                raise _DockerDispatchFailure(
                    fallback_reason="dispatch_timeout",
                    message=(
                        "Docker CLI wait failed: "
                        f"{(wait_result.stderr or wait_result.stdout).strip()} {diagnostics}"
                    ),
                    dispatch_id=container_id,
                    dispatch_submitted=True,
                )

            logs_result = subprocess.run(
                ["docker", *_docker_host_args(docker_host), "logs", container_id],
                capture_output=True,
                text=True,
                check=False,
            )
            stdout, stderr = _split_combined_logs(logs_result.stdout or "")
            startup_seen, executor_result = self._parse_executor_logs(stdout, stderr)
            return _DockerDispatchOutcome(
                dispatch_id=container_id,
                stdout=stdout,
                stderr=stderr,
                api_failure_category=None,
                cli_fallback_used=True,
                cli_preflight_passed=True,
                dispatch_submitted=True,
                startup_marker_seen=startup_seen,
                executor_result=executor_result,
            )
        except subprocess.TimeoutExpired:
            self._cli_cancel_container(
                docker_host=docker_host,
                container_id=container_id,
                cancel_grace_timeout=cancel_grace_timeout,
                cancel_force_kill=cancel_force_kill,
            )
            raise _DockerDispatchFailure(
                fallback_reason="dispatch_timeout",
                message=f"Docker CLI wait timed out after {execution_timeout} seconds.",
                dispatch_id=container_id,
                dispatch_submitted=True,
            )
        finally:
            self._cli_remove_container(docker_host=docker_host, container_id=container_id)

    def _container_name(self, request: ExecutionRequest) -> str:
        return _sanitize_container_name(
            f"llmctl-exec-flowchart-{request.node_id}-{request.execution_id}"
        )

    def _container_labels(self, request: ExecutionRequest) -> dict[str, str]:
        return {
            _EXECUTOR_LABEL_KEY: _EXECUTOR_LABEL_VALUE,
            "llmctl.provider": self.provider,
            "llmctl.flowchart.node_id": str(request.node_id),
            "llmctl.flowchart.execution_id": str(request.execution_id),
            "llmctl.workspace_identity": request.workspace_identity,
        }

    def _runtime_env_pairs(self) -> list[str]:
        raw = str(self._settings.get("docker_env_json") or "").strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Ignoring invalid docker_env_json during docker execution.")
            return []
        if not isinstance(parsed, dict):
            return []
        return [f"{str(key)}={str(value)}" for key, value in parsed.items()]

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
            "command": ["/bin/bash", "-lc", "echo llmctl-docker-dispatch-ok"],
            "timeout_seconds": max(5, min(execution_timeout, 3600)),
            "emit_start_markers": True,
            "metadata": {
                "flowchart_node_id": request.node_id,
                "execution_id": request.execution_id,
            },
        }
        return json.dumps(payload, separators=(",", ":"))

    def _api_request(
        self,
        *,
        socket_path: str,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        timeout: int,
    ) -> dict[str, Any]:
        command = [
            "curl",
            "--silent",
            "--show-error",
            "--fail",
            "--max-time",
            str(timeout),
            "--unix-socket",
            socket_path,
            "-X",
            method,
            f"http://localhost{path}",
        ]
        if body is not None:
            command.extend(
                [
                    "-H",
                    "Content-Type: application/json",
                    "--data",
                    json.dumps(body),
                ]
            )
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "").strip()
            raise _DockerDispatchFailure(
                fallback_reason="create_failed",
                message=f"Docker API request failed for {path}: {message}",
                dispatch_submitted=False,
            )
        content = str(completed.stdout or "").strip()
        if not content:
            return {}
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {}

    def _api_ping(self, socket_path: str, *, timeout: int) -> None:
        command = [
            "curl",
            "--silent",
            "--show-error",
            "--fail",
            "--max-time",
            str(timeout),
            "--unix-socket",
            socket_path,
            "http://localhost/_ping",
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "").strip()
            category = _categorize_api_unavailable_error(message)
            raise _DockerApiUnavailable(
                category,
                f"Docker API ping failed: {message}",
            )

    def _api_ensure_image(
        self,
        *,
        socket_path: str,
        image: str,
        pull_policy: str,
        timeout: int,
        docker_host: str,
    ) -> None:
        policy = pull_policy.strip().lower()
        if policy == "never":
            return
        if policy == "if_not_present":
            inspect = subprocess.run(
                ["docker", *_docker_host_args(docker_host), "image", "inspect", image],
                capture_output=True,
                text=True,
                check=False,
            )
            if inspect.returncode == 0:
                return
        encoded = quote(image, safe="")
        pull = subprocess.run(
            [
                "curl",
                "--silent",
                "--show-error",
                "--fail",
                "--max-time",
                str(timeout),
                "--unix-socket",
                socket_path,
                "-X",
                "POST",
                f"http://localhost/images/create?fromImage={encoded}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if pull.returncode != 0:
            message = (pull.stderr or pull.stdout or "").strip()
            raise _DockerDispatchFailure(
                fallback_reason="image_pull_failed",
                message=f"Docker image pull failed: {message}",
                dispatch_submitted=False,
            )

    def _api_wait(
        self,
        *,
        socket_path: str,
        container_id: str,
        execution_timeout: int,
        cancel_grace_timeout: int,
        cancel_force_kill: bool,
    ) -> None:
        wait_command = [
            "curl",
            "--silent",
            "--show-error",
            "--fail",
            "--max-time",
            str(execution_timeout + 5),
            "--unix-socket",
            socket_path,
            "-X",
            "POST",
            f"http://localhost/containers/{container_id}/wait?condition=not-running",
        ]
        try:
            completed = subprocess.run(
                wait_command,
                capture_output=True,
                text=True,
                timeout=execution_timeout + 5,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self._api_cancel_container(
                socket_path=socket_path,
                container_id=container_id,
                cancel_grace_timeout=cancel_grace_timeout,
                cancel_force_kill=cancel_force_kill,
            )
            raise _DockerDispatchFailure(
                fallback_reason="dispatch_timeout",
                message=f"Docker API wait timed out after {execution_timeout} seconds.",
                dispatch_id=container_id,
                dispatch_submitted=True,
            )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "").strip()
            raise _DockerDispatchFailure(
                fallback_reason="dispatch_timeout",
                message=f"Docker API wait failed: {message}",
                dispatch_id=container_id,
                dispatch_submitted=True,
            )

    def _api_logs(self, *, socket_path: str, container_id: str) -> tuple[str, str]:
        logs_command = [
            "curl",
            "--silent",
            "--show-error",
            "--fail",
            "--unix-socket",
            socket_path,
            "-X",
            "GET",
            f"http://localhost/containers/{container_id}/logs?stdout=1&stderr=1&timestamps=0",
        ]
        completed = subprocess.run(
            logs_command,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or b"").decode(
                "utf-8",
                errors="replace",
            )
            raise _DockerDispatchFailure(
                fallback_reason="dispatch_timeout",
                message=f"Docker API logs failed: {message.strip()}",
                dispatch_id=container_id,
                dispatch_submitted=True,
            )
        return _decode_docker_log_stream(completed.stdout or b"")

    def _api_remove(self, *, socket_path: str, container_id: str) -> None:
        subprocess.run(
            [
                "curl",
                "--silent",
                "--show-error",
                "--fail",
                "--unix-socket",
                socket_path,
                "-X",
                "DELETE",
                f"http://localhost/containers/{container_id}?force=1",
            ],
            capture_output=True,
            check=False,
        )

    def _api_cancel_container(
        self,
        *,
        socket_path: str,
        container_id: str,
        cancel_grace_timeout: int,
        cancel_force_kill: bool,
    ) -> None:
        subprocess.run(
            [
                "curl",
                "--silent",
                "--show-error",
                "--fail",
                "--unix-socket",
                socket_path,
                "-X",
                "POST",
                f"http://localhost/containers/{container_id}/stop?t={cancel_grace_timeout}",
            ],
            capture_output=True,
            check=False,
        )
        if cancel_force_kill:
            subprocess.run(
                [
                    "curl",
                    "--silent",
                    "--show-error",
                    "--fail",
                    "--unix-socket",
                    socket_path,
                    "-X",
                    "POST",
                    f"http://localhost/containers/{container_id}/kill",
                ],
                capture_output=True,
                check=False,
            )

    def _cli_fallback_precondition(self, docker_host: str) -> bool:
        socket_path = _extract_socket_path(docker_host)
        if not socket_path:
            return False
        if not os.path.exists(socket_path):
            return False
        if not stat_is_socket(socket_path):
            return False
        probe = subprocess.run(
            ["docker", *_docker_host_args(docker_host), "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode != 0:
            return False
        network_probe = subprocess.run(
            ["docker", *_docker_host_args(docker_host), "network", "ls", "--format", "{{.Name}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return network_probe.returncode == 0

    def _cli_ensure_image(self, *, docker_host: str, image: str, pull_policy: str) -> None:
        policy = pull_policy.strip().lower()
        if policy == "never":
            return
        if policy == "if_not_present":
            inspect = subprocess.run(
                ["docker", *_docker_host_args(docker_host), "image", "inspect", image],
                capture_output=True,
                text=True,
                check=False,
            )
            if inspect.returncode == 0:
                return
        pulled = subprocess.run(
            ["docker", *_docker_host_args(docker_host), "pull", image],
            capture_output=True,
            text=True,
            check=False,
        )
        if pulled.returncode != 0:
            message = (pulled.stderr or pulled.stdout or "").strip()
            raise _DockerDispatchFailure(
                fallback_reason="image_pull_failed",
                message=f"Docker CLI pull failed: {message}",
                dispatch_submitted=False,
            )

    def _cli_cancel_container(
        self,
        *,
        docker_host: str,
        container_id: str,
        cancel_grace_timeout: int,
        cancel_force_kill: bool,
    ) -> None:
        subprocess.run(
            [
                "docker",
                *_docker_host_args(docker_host),
                "stop",
                "--time",
                str(cancel_grace_timeout),
                container_id,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if cancel_force_kill:
            subprocess.run(
                ["docker", *_docker_host_args(docker_host), "kill", container_id],
                capture_output=True,
                text=True,
                check=False,
            )

    def _cli_remove_container(self, *, docker_host: str, container_id: str) -> None:
        subprocess.run(
            ["docker", *_docker_host_args(docker_host), "rm", "-f", container_id],
            capture_output=True,
            text=True,
            check=False,
        )

    def _prune_stopped_executor_containers(self, docker_host: str) -> None:
        subprocess.run(
            [
                "docker",
                *_docker_host_args(docker_host),
                "container",
                "prune",
                "--force",
                "--filter",
                f"label={_EXECUTOR_LABEL_KEY}={_EXECUTOR_LABEL_VALUE}",
                "--filter",
                "until=24h",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def _cli_diagnostics(self, *, docker_host: str, container_id: str | None) -> str:
        ps = subprocess.run(
            [
                "docker",
                *_docker_host_args(docker_host),
                "ps",
                "-a",
                "--filter",
                f"label={_EXECUTOR_LABEL_KEY}={_EXECUTOR_LABEL_VALUE}",
                "--format",
                "{{.ID}} {{.Status}} {{.Names}}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        diagnostics_parts: list[str] = []
        ps_preview = " | ".join((ps.stdout or "").strip().splitlines()[:3]).strip()
        if ps_preview:
            diagnostics_parts.append(f"ps={ps_preview}")
        if container_id:
            inspect = subprocess.run(
                [
                    "docker",
                    *_docker_host_args(docker_host),
                    "inspect",
                    "--format",
                    "{{.Id}} {{.State.Status}} {{.State.ExitCode}}",
                    container_id,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            inspect_preview = str(inspect.stdout or "").strip()
            if inspect_preview:
                diagnostics_parts.append(f"inspect={inspect_preview}")
        if not diagnostics_parts:
            return ""
        return "diagnostics(" + ", ".join(diagnostics_parts) + ")"

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
        api_failure_category: str | None,
        cli_fallback_used: bool,
        cli_preflight_passed: bool | None,
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
            api_failure_category=api_failure_category,
            cli_fallback_used=cli_fallback_used,
            cli_preflight_passed=(
                cli_preflight_passed if cli_fallback_used else None
            ),
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
                api_failure_category=api_failure_category,
                cli_fallback_used=cli_fallback_used,
                cli_preflight_passed=cli_preflight_passed,
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
                    "api_failure_category": api_failure_category,
                    "cli_fallback_used": cli_fallback_used,
                    "cli_preflight_passed": (
                        cli_preflight_passed if cli_fallback_used else None
                    ),
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
                "api_failure_category": api_failure_category,
                "cli_fallback_used": cli_fallback_used,
                "cli_preflight_passed": (
                    cli_preflight_passed if cli_fallback_used else None
                ),
            },
        )

    def _dispatch_failed_result(
        self,
        *,
        request: ExecutionRequest,
        started_at: datetime,
        message: str,
        provider_dispatch_id: str | None,
        api_failure_category: str | None,
        cli_fallback_used: bool,
        cli_preflight_passed: bool | None,
        dispatch_submitted: bool,
        dispatch_uncertain: bool,
        fallback_attempted: bool,
        fallback_reason: str | None,
        stdout: str,
        stderr: str,
    ) -> ExecutionResult:
        finished_at = _utcnow()
        dispatch_status = (
            EXECUTION_DISPATCH_SUBMITTED if dispatch_submitted else EXECUTION_DISPATCH_FAILED
        )
        if dispatch_uncertain:
            dispatch_status = EXECUTION_DISPATCH_FAILED
            fallback_attempted = False
            fallback_reason = None
        elif dispatch_status == EXECUTION_DISPATCH_SUBMITTED:
            dispatch_status = EXECUTION_DISPATCH_FAILED
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
                "api_failure_category": api_failure_category,
                "cli_fallback_used": cli_fallback_used,
                "cli_preflight_passed": cli_preflight_passed if cli_fallback_used else None,
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
                "api_failure_category": api_failure_category,
                "cli_fallback_used": cli_fallback_used,
                "cli_preflight_passed": (
                    cli_preflight_passed if cli_fallback_used else None
                ),
            },
        )

    def _execution_failed_after_confirmed_result(
        self,
        *,
        request: ExecutionRequest,
        started_at: datetime,
        message: str,
        provider_dispatch_id: str,
        api_failure_category: str | None,
        cli_fallback_used: bool,
        cli_preflight_passed: bool | None,
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
                "api_failure_category": api_failure_category,
                "cli_fallback_used": cli_fallback_used,
                "cli_preflight_passed": (
                    cli_preflight_passed if cli_fallback_used else None
                ),
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
                "api_failure_category": api_failure_category,
                "cli_fallback_used": cli_fallback_used,
                "cli_preflight_passed": (
                    cli_preflight_passed if cli_fallback_used else None
                ),
            },
        )


def stat_is_socket(path: str) -> bool:
    try:
        mode = os.stat(path).st_mode
    except OSError:
        return False
    return stat.S_ISSOCK(mode)
