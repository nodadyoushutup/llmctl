Node Executor Runtime
=====================

Overview
--------

Node execution supports three providers behind one Studio control plane:

- ``workspace``: in-process/local execution path (default).
- ``docker``: ephemeral container execution via Docker Engine API with CLI fallback.
- ``kubernetes``: ephemeral Job execution via Kubernetes API (``kubectl`` control path).

Runtime settings are DB-backed (``integration_settings(provider='node_executor')``)
with bootstrap environment defaults only for first-run initialization.

Runtime Settings Contract
-------------------------

Global keys:

- ``provider``: ``workspace|docker|kubernetes``.
- ``fallback_provider``: ``workspace`` (v1).
- ``fallback_enabled`` and ``fallback_on_dispatch_error``.
- ``dispatch_timeout_seconds``.
- ``execution_timeout_seconds``.
- ``log_collection_timeout_seconds``.
- ``cancel_grace_timeout_seconds``.
- ``cancel_force_kill_enabled``.
- ``workspace_identity_key`` (stable logical key, persisted per run as ``workspace_identity``).

Docker keys:

- ``docker_host`` (for example ``unix:///var/run/docker.sock``).
- ``docker_image``.
- ``docker_network``.
- ``docker_pull_policy``: ``always|if_not_present|never``.
- ``docker_env_json``.
- ``docker_api_stall_seconds``: ``5|10|15`` (DB-only source, default ``10``).

Kubernetes keys:

- ``k8s_namespace``.
- ``k8s_image``.
- ``k8s_in_cluster``.
- ``k8s_service_account``.
- ``k8s_kubeconfig`` (encrypted at rest; runtime-only plaintext access).
- ``k8s_image_pull_secrets_json``.

Architecture
------------

Studio control-plane modules:

- ``services/execution/router.py``: provider routing + fallback decisioning.
- ``services/execution/workspace_executor.py``.
- ``services/execution/docker_executor.py``.
- ``services/execution/kubernetes_executor.py``.
- ``services/tasks.py``: flowchart/node orchestration and run metadata persistence.

Execution plane:

- ``app/llmctl-executor`` image runs one request payload and emits structured
  startup/result markers consumed by Studio.

Execution Contract (v1)
-----------------------

``llmctl-executor`` and Studio enforce ``ExecutionResult.contract_version='v1'``.
Version mismatch is treated as ``infra_error``.

Required fields:

- ``contract_version``
- ``status``
- ``exit_code``
- ``started_at``
- ``finished_at``
- ``stdout``
- ``stderr``
- ``error`` (``null`` only for ``success``)
- ``provider_metadata``

Optional fields (omitted when unavailable):

- ``usage``
- ``artifacts``
- ``warnings``
- ``metrics``

Status enum:

- ``success|failed|cancelled|timeout|dispatch_failed|dispatch_uncertain|infra_error``

Error code enum:

- ``validation_error|provider_error|dispatch_error|timeout|cancelled|execution_error|infra_error|unknown``

Dispatch Confirmation and State Machine
---------------------------------------

Dispatch start confirmation accepts either:

- literal marker line ``LLMCTL_EXECUTOR_STARTED``, or
- JSON marker ``{"event":"executor_started","contract_version":"v1","ts":"..."}``.

Dispatch state progression:

- ``dispatch_pending``
- ``dispatch_submitted``
- ``dispatch_confirmed``
- ``dispatch_failed``
- ``fallback_started``

Ambiguous dispatch is fail-closed:

- ``dispatch_status=dispatch_failed``
- ``dispatch_uncertain=true``
- no automatic fallback.

Fallback and Cancellation Semantics
-----------------------------------

Fallback eligibility applies only to pre-confirm dispatch failures
(``provider_unavailable``, ``dispatch_timeout``, ``create_failed``,
``image_pull_failed``, ``config_error``, ``unknown``).

If fallback starts:

- ``fallback_attempted=true``
- ``final_provider=workspace``
- ``fallback_reason`` is required.

Cancellation policy is two-step:

- best-effort graceful stop using ``cancel_grace_timeout_seconds``.
- force-kill/delete when ``cancel_force_kill_enabled=true``.

Observability and Run History
-----------------------------

Node run metadata persisted for audit/filtering includes:

- ``selected_provider`` and ``final_provider``.
- ``provider_dispatch_id``.
- ``workspace_identity``.
- ``dispatch_status`` and ``dispatch_uncertain``.
- ``fallback_attempted`` and ``fallback_reason``.
- Docker API/CLI fallback fields:
  ``api_failure_category``, ``cli_fallback_used``, ``cli_preflight_passed``.

Run detail APIs and templates expose dispatch/fallback timeline data so operators
can audit provider routing decisions per node run.

Operator Notes
--------------

- Docker CLI fallback requires a mounted/reachable Docker socket/path preflight.
- If Docker API is unavailable and CLI preflight fails, dispatch is classified
  ``provider_unavailable`` and workspace fallback is used when enabled.
- Kubernetes out-of-cluster mode requires ``k8s_kubeconfig``; missing kubeconfig
  fails preflight with ``config_error`` classification.
- ``k8s_kubeconfig`` is write-only in settings responses (metadata-only read:
  set flag, timestamp, fingerprint) and plaintext is restricted to runtime paths.
