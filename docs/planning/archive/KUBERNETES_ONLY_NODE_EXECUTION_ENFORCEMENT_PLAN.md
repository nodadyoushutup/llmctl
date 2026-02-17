# Kubernetes-Only Node Execution Enforcement Plan

Goal: enforce Kubernetes-only node execution end-to-end so node workloads run in ephemeral executor pods, with no workspace fallback and no non-Kubernetes node execution path.

## Stage 0 - Requirements Gathering
- [x] Confirm target direction: Kubernetes-only node execution with no workspace fallback.
- [x] Confirm exact execution scope that must move to executor pods (flowchart nodes, Quick RAG, quick task, other task kinds).
- [x] Confirm what Celery remains responsible for vs what must dispatch to Kubernetes executor Jobs.
- [x] Confirm execution contract expectations for executor pod behavior (full node logic in pod vs dispatch/probe only).
- [x] Confirm rollout constraints (hard cutover vs phased toggle), including acceptable temporary behavior.
- [x] Confirm failure-handling policy (retry behavior, duplicate suppression, timeout semantics, cancellation behavior).
- [x] Confirm observability and acceptance criteria (required evidence in Node Activity, logs, and Kubernetes resources).
- [x] Confirm requirements are complete and approved to start Stage 1.

## Stage 0 - Interview Notes
- [x] User intent captured: this is a Kubernetes app; node execution should be Kubernetes-only.
- [x] User intent captured: keep Celery, but prefer node execution in ephemeral executor pods.
- [x] Scope decision recorded.
- [x] Scope decision detail: all node-like behavior executes in executor pods; chat remains the only non-node execution path.
- [x] Celery responsibility boundary recorded.
- [x] Celery decision detail: control-plane only for node-like workloads (queueing/orchestration/status/events); node compute executes in executor pods.
- [x] Execution contract decision recorded.
- [x] Execution contract detail: full node execution runs inside executor pods (LLM/RAG/tool work and output assembly), not dispatch-only probes.
- [x] Rollout decision recorded.
- [x] Rollout detail: hard cutover in one release; no phased fallback mode.
- [x] Failure-handling decision recorded.
- [x] Failure-handling detail: no fallback and fail fast; no automatic retry by default; rerun is explicit/user-initiated with pod/job diagnostics persisted to task/run metadata.
- [x] Observability/acceptance decision recorded.
- [x] Observability/acceptance detail: Node Activity/runtime metadata must include `k8s_job_name`, `k8s_pod_name`, `provider_dispatch_id`, and terminal pod/job reason, plus docs/tests proving node-like compute is not executed in worker process.

## Stage 1 - Code Planning
- [x] Convert approved Stage 0 requirements into Stage 2 through Stage X implementation stages.
- [x] Define file-level change scope and execution order.
- [x] Define acceptance criteria per stage.
- [x] Ensure final two stages are `Automated Testing` and `Docs Updates`.
- [x] Define two-agent execution model with explicit file ownership to avoid merge collisions.

## Multi-Agent Coordination Model
- [x] Agent A owns execution-plane/runtime internals only:
  - `app/llmctl-studio-backend/src/services/execution/*`
  - `app/llmctl-executor/src/llmctl_executor/*`
  - `app/llmctl-executor/tests/*`
  - backend execution tests that do not modify task orchestration behavior.
- [x] Agent B owns control-plane orchestration and node-like task migration:
  - `app/llmctl-studio-backend/src/services/tasks.py`
  - `app/llmctl-studio-backend/src/rag/web/views.py`
  - `app/llmctl-studio-backend/src/web/views.py` (only if Node Activity/runtime payload shaping is required)
  - backend task/rag tests and activity metadata tests.
- [x] Shared-file rule: Agent A does not edit `services/tasks.py`; Agent B does not edit `services/execution/*` unless integrating final agreed contract wiring.
- [x] Parallelization rule: Stage 3 and Stage 4 execute in parallel; Stage 5 is merge/integration after both are complete.

## Stage 2 - Contract Freeze And Integration Guardrails
- [x] Define and freeze the executor payload/result contract for full in-pod node execution (input schema, output schema, error envelope, metadata keys).
- [x] Freeze required runtime metadata keys: `provider_dispatch_id`, `k8s_job_name`, `k8s_pod_name`, terminal job/pod reason.
- [x] Document handoff contract in this plan so Agent A and Agent B can implement independently.
- [x] Acceptance criteria: both agents can implement against the same contract without touching each other's owned files.

### Stage 2 Contract Freeze (Locked)

- Executor payload to pod (`LLMCTL_EXECUTOR_PAYLOAD_JSON`):
  - `contract_version: "v1"`
  - `result_contract_version: "v1"`
  - `provider: "kubernetes"`
  - `request_id`
  - `timeout_seconds`
  - `emit_start_markers`
  - `node_execution`:
    - `entrypoint: "services.tasks:_execute_flowchart_node_request"`
    - `python_paths` (includes `/app/app/llmctl-studio-backend/src`)
    - `request` (full serialized node request: `node_id`, `node_type`, `node_ref_id`, `node_config`, `input_context`, `execution_id`, `execution_task_id`, `execution_index`, `enabled_providers`, `default_model_id`, `mcp_server_keys`)

- Executor result from pod (`LLMCTL_EXECUTOR_RESULT_JSON=...`):
  - Required contract envelope remains `v1` (`status`, `exit_code`, `started_at`, `finished_at`, `stdout`, `stderr`, `error`, `provider_metadata`)
  - Node compute outputs are returned in:
    - `output_state` (object)
    - `routing_state` (object)
  - `status != success` is treated as terminal execution failure (no fallback path).

- Runtime metadata keys (required for node activity/run persistence):
  - `provider_dispatch_id`
  - `k8s_job_name`
  - `k8s_pod_name`
  - `k8s_terminal_reason` (terminal diagnostic reason; job/pod terminal reason equivalent)

- Kubernetes-only behavior constraints:
  - No workspace/docker fallback path for node-like workloads.
  - Confirmed dispatch success path consumes pod-returned `output_state` / `routing_state` only (no worker-side node callback execution).

## Stage 3 - Agent A Workstream (Execution Plane)
- [x] Replace probe-style executor behavior with full node execution payload handling in `app/llmctl-executor`.
- [x] Update Kubernetes executor dispatch flow to submit full node execution payloads (not `echo` probes) and capture terminal reason diagnostics.
- [x] Ensure execution result contract includes output payload required by control-plane task persistence.
- [x] Keep Kubernetes-only behavior strict (no workspace/docker fallback paths).
- [x] Add/update tests for executor payload validation, runtime execution, Kubernetes executor result parsing, and metadata completeness.
- [x] Acceptance criteria: a dispatched executor pod can run full node logic and return structured success/failure output with required Kubernetes metadata.

## Stage 4 - Agent B Workstream (Control Plane Node Migration)
- [x] Migrate node-like workloads (`flowchart_*`, `rag_quick_*`, quick task path if node-like) to treat executor pods as compute runtime and Celery as orchestrator only.
- [x] Remove worker-side direct node compute for node-like paths (for example direct `run_index_for_collections(...)` execution in quick-rag worker task).
- [x] Preserve chat behavior as non-node execution path (no pod-per-chat-turn dispatch).
- [x] Persist executor runtime metadata into Node Activity/task/run records with required keys and terminal diagnostics.
- [x] Add/update tests proving node-like compute is not executed in worker process and that metadata is present.
- [x] Acceptance criteria: node-like tasks always dispatch to executor pods; chat remains unchanged; Node Activity shows Kubernetes runtime evidence.

## Stage 5 - Merge And End-To-End Integration
- [x] Integrate Agent A and Agent B branches on top of Stage 2 contract.
- [x] Resolve cross-workstream wiring points (payload builders, result decoders, task state transitions).
- [x] Verify no regression to probe-only behavior and no worker-side node compute remains.
- [x] Acceptance criteria: merged branch executes node-like workloads in executor pods end-to-end with fail-fast semantics and no fallback.

## Stage 6 - Automated Testing
- [x] Add/update automated tests that validate Kubernetes-only node execution behavior and failure modes.
- [x] Run targeted automated tests for execution routing, task orchestration, and runtime metadata.
- [x] Run agent-owned suites first (A then B), then merged end-to-end suites after Stage 5.
- [x] Acceptance criteria: all targeted tests pass for execution plane, control plane, and merged runtime behavior.

## Stage 7 - Docs Updates
- [x] Update Sphinx and operational docs to document Kubernetes-only node execution behavior and Celery role boundaries.
- [x] Update any runtime/operator guidance that still implies non-Kubernetes node execution paths.
- [x] Document the explicit architecture split: chat on Celery/service runtime, node-like workloads on executor pods.
- [x] Acceptance criteria: docs consistently state Kubernetes-only node execution and required runtime evidence fields.
