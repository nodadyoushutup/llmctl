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
- ``agent_runtime_cutover_enabled`` (Stage 14+ unified runtime gate).
- ``dispatch_timeout_seconds``.
- ``execution_timeout_seconds``.
- ``log_collection_timeout_seconds``.
- ``cancel_grace_timeout_seconds``.
- ``cancel_force_kill_enabled``.
- ``workspace_identity_key`` (stable logical key, persisted per run as ``workspace_identity``).
- ``k8s_namespace``.
- ``k8s_frontier_image`` and ``k8s_frontier_image_tag``.
- ``k8s_vllm_image`` and ``k8s_vllm_image_tag``.
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

Runtime split:

- node-like workloads (flowchart nodes, quick-RAG/index node-like paths) run
  in ephemeral Kubernetes executor pods.
- chat turns dispatch LLM execution through executor ``llm_call`` payloads.
- RAG web chat synthesis/completion dispatches through executor
  ``rag_chat_completion`` payloads.

Tool-domain ownership boundary:

- ``services/execution/tooling.py`` owns deterministic invocation lifecycle
  (schema validation, retry/idempotency controls, trace envelope wiring).
- ``services/tasks.py`` owns node-type dispatch and domain operation selection.
- ``services/runtime_contracts.py`` owns event/payload shape validation and
  socket event-type normalization (``domain:entity:action`` canonical form).

Frontier SDK Tool Loop
----------------------

Frontier providers execute through the shared Python SDK runtime adapter
(``services/execution/agent_runtime.py``) with iterative tool calling:

1. provider returns assistant output
2. SDK tool calls are parsed into normalized calls
3. deterministic tool domains are dispatched
4. tool results are appended to the next cycle prompt
5. loop terminates on final assistant output or max-cycle guard

Provider capability matrix for this slice:

- ``codex``: SDK model output + MCP transport wiring + SDK tool loop
  (workspace/git/command).
- ``gemini``: SDK model output + SDK tool loop (no MCP transport wiring).
- ``claude``: SDK model output + SDK tool loop (no MCP transport wiring).

Unsupported behavior is explicit and fail-fast:

- non-codex providers reject MCP transport configs with deterministic errors
- unknown tool names/domains return normalized error envelopes and terminate
  execution
- max-cycle guard defaults to ``24`` and is hard-capped at ``64``

SDK tool domains are dispatched to deterministic handlers:

- ``deterministic.workspace`` -> ``run_workspace_tool``
- ``deterministic.git`` -> ``run_git_tool``
- ``deterministic.command`` -> ``run_command_tool``

Executor-Local Workspace Provisioning
-------------------------------------

Each Kubernetes executor pod gets isolated ephemeral workspace storage.

- Job manifest mounts an ``emptyDir`` runtime volume at ``/tmp/llmctl/runtime``.
- Executor payload ``cwd`` is set to a per-request runtime root under that mount.
- Payload env sets:
  - ``LLMCTL_STUDIO_WORKSPACES_DIR=<runtime_root>/workspaces``
  - ``LLMCTL_STUDIO_DATA_DIR=<runtime_root>/data``
- Task runtime clone/edit/test flows run inside this pod-local workspace root,
  and SDK tool dispatch resolves workspace roots from the same runtime context.

Execution Contract
------------------

Executor payload to pod (``v1``):

- ``contract_version`` and ``result_contract_version``.
- ``provider='kubernetes'``.
- ``request_id``, ``timeout_seconds``, ``emit_start_markers``.
- ``node_execution`` with:
  - ``entrypoint='services.tasks:_execute_flowchart_node_request'``
  - ``python_paths`` (includes Studio backend source path)
  - full serialized node request payload.
- transport: per-job ConfigMap (``payload.json``) mounted into executor pod and
  passed as ``LLMCTL_EXECUTOR_PAYLOAD_FILE``.

Executor result from pod (``v1``):

- envelope fields: ``status``, ``exit_code``, timestamps, ``stdout``, ``stderr``,
  ``error``, ``provider_metadata``.
- node output contract fields: ``output_state`` and ``routing_state``.

Kubernetes dispatcher consumes ``output_state``/``routing_state`` from executor
result and does not execute worker-side node compute on the success path.

SDK Tooling Evidence
--------------------

Tool-loop evidence is persisted for node/task outputs:

- frontier runtime attaches per-call trace entries to completed results
  (``_llmctl_tool_trace`` internal payload).
- task/node outputs may include ``output_state.sdk_tooling`` containing:
  - provider
  - workspace root (when available)
  - request/correlation identifiers
  - tool call count and per-call operation/tool-domain trace data
- existing runtime evidence fields remain available in outputs/events:
  ``provider_dispatch_id``, ``k8s_job_name``, ``k8s_pod_name``,
  ``k8s_terminal_reason``.

Executor Split Images and Build/Release
---------------------------------------

Image classes:

- ``frontier`` image class (for non-vLLM providers): default image
  ``llmctl-executor-frontier:latest``.
- ``vllm`` image class: default image ``llmctl-executor-vllm:latest``.

Runtime settings support independent image + tag overrides per class:

- ``k8s_frontier_image`` / ``k8s_frontier_image_tag``
- ``k8s_vllm_image`` / ``k8s_vllm_image_tag``

Recommended Harbor build/push commands (from repo root):

.. code-block:: bash

   scripts/build/harbor.sh \
     --executor-frontier \
     --tag <tag> \
     --registry <registry-host:port>

   scripts/build/harbor.sh \
     --executor-vllm \
     --tag <tag> \
     --registry <registry-host:port>

To publish both split executor images together:

.. code-block:: bash

   scripts/build/harbor.sh \
     --executor-frontier \
     --executor-vllm \
     --tag <tag> \
     --registry <registry-host:port>

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
- ``k8s_job_name``.
- ``k8s_pod_name``.
- ``k8s_terminal_reason``.
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
- Backend service account requires namespace-scoped permissions for ``configmaps``
  in addition to ``jobs``/``pods`` because executor payloads are delivered via
  per-job ConfigMaps.
