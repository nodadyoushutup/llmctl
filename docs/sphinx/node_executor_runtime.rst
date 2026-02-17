Node Executor Runtime
=====================

Overview
--------

Node execution is Kubernetes-only.

- ``kubernetes``: ephemeral Job/Pod execution via Kubernetes API (``kubectl`` control path).

Runtime settings are DB-backed (``integration_settings(provider='node_executor')``)
with bootstrap environment defaults only for first-run initialization.

Runtime Settings Contract
-------------------------

Keys:

- ``provider``: ``kubernetes``.
- ``dispatch_timeout_seconds``.
- ``execution_timeout_seconds``.
- ``log_collection_timeout_seconds``.
- ``cancel_grace_timeout_seconds``.
- ``cancel_force_kill_enabled``.
- ``workspace_identity_key`` (stable logical key, persisted per run as ``workspace_identity``).
- ``k8s_namespace``.
- ``k8s_image``.
- ``k8s_in_cluster``.
- ``k8s_service_account``.
- ``k8s_kubeconfig`` (encrypted at rest; runtime-only plaintext access).
- ``k8s_gpu_limit``.
- ``k8s_job_ttl_seconds`` (terminal Job/Pod retention before automatic cleanup).
- ``k8s_image_pull_secrets_json``.

Architecture
------------

Studio control-plane modules:

- ``services/execution/router.py``: Kubernetes dispatch routing.
- ``services/execution/kubernetes_executor.py``.
- ``services/tasks.py``: flowchart/node orchestration and run metadata persistence.

Execution plane:

- ``app/llmctl-executor`` image runs one request payload and emits structured
  startup/result markers consumed by Studio.

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

Ambiguous dispatch is fail-closed:

- ``dispatch_status=dispatch_failed``
- ``dispatch_uncertain=true``
- no automatic fallback.

Observability and Run History
-----------------------------

Node run metadata persisted for audit/filtering includes:

- ``selected_provider`` and ``final_provider`` (both ``kubernetes``).
- ``provider_dispatch_id``.
- ``workspace_identity``.
- ``dispatch_status`` and ``dispatch_uncertain``.
- fallback/CLI compatibility fields remain in payload shape for v1 parity but are
  non-routing fields in Kubernetes-only mode.

Operator Notes
--------------

- Kubernetes out-of-cluster mode requires ``k8s_kubeconfig``; missing kubeconfig
  fails preflight with ``config_error`` classification.
- ``k8s_kubeconfig`` is write-only in settings responses (metadata-only read:
  set flag, timestamp, fingerprint) and plaintext is restricted to runtime paths.
- Terminal executor jobs use ``ttlSecondsAfterFinished`` from ``k8s_job_ttl_seconds``
  so completed/failed jobs are auto-cleaned after short retention.
