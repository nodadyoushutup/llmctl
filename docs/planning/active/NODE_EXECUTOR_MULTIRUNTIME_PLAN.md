# Node Executor Multi-Runtime Plan

**Work checklist instructions**
- Check off each subtask as it is completed.
- Use `- [x]` for done and `- [ ]` for not done.
- Update this file in place as implementation progresses.
- Keep fallback behavior explicit to avoid duplicate node execution.

Goal: add a pluggable node execution system that supports `workspace`, `docker`, and `kubernetes` runtimes behind one Studio control plane, with DB-backed runtime settings and safe fallback to workspace execution when remote dispatch fails.

## Plan correction pass (2026-02-16)

- [x] Restored workflow gate: Stage 0 must be fully complete before Stage 1 is marked complete.
- [x] Converted Stage 1 completion checks back to pending until Stage 0 deliverables are locked.
- [x] Added explicit DB migration/index tasks for node run provider metadata.
- [x] Mapped kubeconfig security controls to concrete execution stages.
- [x] Added explicit execution contract versioning and compatibility acceptance criteria.
- [x] Added a focused Stage 0 interview queue to clear remaining blockers.

## Decision log (updated 2026-02-16)

- [x] Support three runtime providers:
  - [x] `workspace` (current in-process baseline).
  - [x] `docker` (ephemeral container runs; docker socket mount allowed for internal deployments).
  - [x] `kubernetes` (ephemeral Job/Pod runs via Kubernetes API).
- [x] Primary executor settings live in the database.
- [x] Default provider is `workspace`.
- [x] Provider selection is global-only for v1.
- [x] Fallback policy is global-only for v1.
- [x] Remote-provider dispatch failures (`docker`/`kubernetes`) fall back to `workspace` when fallback-eligible.
- [x] Create a dedicated executor image/app: `llmctl-executor`.
- [x] Keep env vars as bootstrap/fallback overrides, but DB is source-of-truth at runtime.
- [x] `k8s_kubeconfig` is stored in DB for v1.
- [x] Timeouts are configurable in runtime settings.
- [x] Cancellation model is two-step: best effort stop, then force kill after grace timeout.
- [x] Rollout model for now is dev-only; no production phased rollout required in this plan.
- [x] `ExecutionResult` contract shape selected: `Rich` (minimum core + usage/artifacts/provider metadata/warnings/metrics).
- [x] Dispatch confirmation protocol direction selected: explicit executor startup log marker.
- [x] Ambiguous dispatch policy selected: fail closed (`dispatch_uncertain=true`), no auto-fallback, manual retry only.
- [x] Run-history metadata indexing scope selected: `Extended` (essential + `provider_dispatch_id` + `fallback_reason`).
- [x] `k8s_kubeconfig` encryption-at-rest direction selected: reuse existing secrets/encryption mechanism.
- [x] Image reference policy selected: allow tag-only and digest-pinned references; runtime must support both formats.

## Non-negotiable constraints

- [ ] Existing node execution behavior must remain functional while rollout is in progress.
- [ ] Fallback must be idempotent and must not create duplicate successful runs.
- [ ] Workspace provider remains always available as last-resort runtime.
- [ ] Provider selection and effective settings must be observable in run history/logs.
- [ ] For template/pipeline updates, treat as DB updates unless explicitly asked to update seed data.

## Definition of done

- [ ] Studio can execute nodes through `workspace`, `docker`, or `kubernetes` providers via one runtime contract.
- [ ] Studio runtime settings UI/API can configure provider + provider-specific options in DB.
- [ ] `docker` and `kubernetes` providers can launch `llmctl-executor` containers/jobs successfully.
- [ ] Fallback to `workspace` is automatic for eligible remote dispatch failures.
- [ ] Node run detail clearly shows selected provider, dispatch status, fallback decisions, and final provider used.
- [ ] Regression suite covers provider selection, fallback rules, and cancellation/cleanup semantics.

## Target architecture

### Control plane (Studio)

- Current orchestrator remains in `app/llmctl-studio/src/services/tasks.py`.
- Introduce provider-agnostic executor service layer (example: `app/llmctl-studio/src/services/execution/`):
  - `contracts.py` (`submit`, `poll`, `cancel`, `collect_logs`, `cleanup`)
  - `workspace_executor.py`
  - `docker_executor.py`
  - `kubernetes_executor.py`
  - `router.py` (provider selection + fallback policy)

### Execution plane (`llmctl-executor`)

- New app at `app/llmctl-executor/` with its own Docker image and entrypoint.
- Purpose: run one node execution payload in an isolated runtime and return structured result.
- Initial scope:
  - materialize workspace/scripts/skills inside container filesystem
  - run provider CLI (`codex`, `gemini`, `claude`, `vllm_*`) using existing prompt/runtime contract
  - emit structured output/error metadata for Studio to persist

### Runtime providers

- `workspace`: run using existing local workspace path behavior.
- `docker`: launch ephemeral container from Studio with `llmctl-executor` image.
- `kubernetes`: launch ephemeral `Job` from Studio with `llmctl-executor` image.

## Settings contract (DB-first with env fallback)

Provider namespace proposal: `integration_settings.provider = "node_executor"`.

Core keys:
- `provider` = `workspace|docker|kubernetes`
- `fallback_provider` = `workspace`
- `fallback_enabled` = `true|false` (default `true`)
- `fallback_on_dispatch_error` = `true|false` (default `true`)
- `dispatch_timeout_seconds`
- `execution_timeout_seconds`
- `log_collection_timeout_seconds`
- `cancel_grace_timeout_seconds`
- `cancel_force_kill_enabled` = `true|false` (default `true`)

Workspace keys:
- `workspace_root` (default to `Config.WORKSPACES_DIR`)

Docker keys:
- `docker_host` (example: `unix:///var/run/docker.sock`)
- `docker_image` (default `llmctl-executor:latest`)
- `docker_network` (optional)
- `docker_pull_policy` (`always|if_not_present|never`)
- `docker_env_json` (optional JSON map)

Kubernetes keys:
- `k8s_namespace`
- `k8s_job_image` (default `llmctl-executor:latest`)
- `k8s_service_account`
- `k8s_in_cluster` (`true|false`)
- `k8s_kubeconfig` (stored in DB for v1)
- `k8s_job_ttl_seconds_after_finished`
- `k8s_active_deadline_seconds`
- `k8s_backoff_limit`
- `k8s_env_json` (optional JSON map)

Environment fallback keys (for bootstrap/no-DB mode):
- `LLMCTL_EXECUTOR_PROVIDER`
- `LLMCTL_EXECUTOR_WORKSPACE_ROOT`
- `LLMCTL_EXECUTOR_DOCKER_HOST`
- `LLMCTL_EXECUTOR_DOCKER_IMAGE`
- `LLMCTL_EXECUTOR_K8S_NAMESPACE`
- `LLMCTL_EXECUTOR_K8S_IN_CLUSTER`

## Fallback policy (must be deterministic)

- Fallback is allowed only when remote execution is not started yet.
- Dispatch start signal:
  - remote execution is considered started only after first executor health signal is observed (health endpoint/heartbeat/log marker).
- Eligible fallback errors:
  - provider unavailable/misconfigured
  - image pull/auth failure before execution start
  - create container/job API failure
  - dispatch timeout with no health signal received
- Non-eligible fallback errors:
  - remote run has started and then failed
  - ambiguous state where remote execution may have started
- Required behavior for ambiguous state:
  - mark node run failed with `dispatch_uncertain=true`
  - do not auto-fallback (manual retry only)

## Stage 0 - Requirements Gathering

- [x] Interview stakeholder on unresolved requirements.
- [x] Confirm how kubeconfig is stored (`k8s_kubeconfig` in DB for v1).
- [x] Confirm provider selection scope (global-only for v1).
- [x] Confirm fallback policy scope (global-only for v1).
- [x] Confirm timeout direction (settings-configurable).
- [x] Confirm cancellation strategy (best effort then force kill).
- [x] Confirm rollout expectation (dev-only, no prod phased rollout).
- [ ] Confirm execution result contract between Studio and `llmctl-executor`.
  - [x] Select schema shape (`Rich`).
  - [ ] Lock required/optional field set and value semantics.
- [ ] Confirm precise health/heartbeat protocol that defines "execution started" per provider.
  - [x] Select protocol family (`log marker`).
  - [ ] Lock marker text contract and parsing behavior for docker/kubernetes.
- [x] Confirm ambiguous dispatch handling policy (always manual retry vs limited operator override).
- [ ] Confirm cancellation semantics during fallback attempts.
- [x] Confirm provider image pinning policy (`tag` vs `digest`).
  - [x] Policy selected: support both mutable tags and digest-pinned images.
  - [ ] Lock validation rules/examples for accepted Docker/K8s image reference forms.
- [ ] Confirm query-critical metadata fields for run-history filtering/indexing.
  - [x] Select indexing scope (`Extended`).
  - [ ] Lock exact index definitions (single/composite) and expected query patterns.
- [ ] Confirm encryption-at-rest mechanism for `k8s_kubeconfig` in v1.
  - [x] Select mechanism direction (`existing secrets/encryption path`).
  - [ ] Lock exact storage/read interfaces and key management boundary.
- [ ] Write risk register with mitigation owners.

Deliverables:
- [ ] Locked runtime contract.
- [ ] Locked fallback decision table.
- [ ] Risk register section in this doc.

Interview queue to clear Stage 0 blockers:
- [ ] `ExecutionResult` v1 schema: required fields, optional fields, and version key.
  - [x] Choose high-level schema shape (`Rich`).
  - [ ] Lock exact required/optional fields and enum semantics.
- [ ] Dispatch confirmation protocol by provider (`docker`, `kubernetes`) and exact signal source.
  - [x] Select signal source family (`executor startup log marker`).
  - [ ] Lock exact marker text and timeout/parsing rules.
- [ ] Ambiguous dispatch policy and whether any operator-forced override exists.
  - [x] Policy selected: always fail + manual retry; no operator-forced fallback in uncertain state.
- [ ] Metadata persistence and indexing requirements for run detail/list views.
  - [x] Index scope selected: `Extended` (`selected_provider`, `final_provider`, `dispatch_status`, `dispatch_uncertain`, `created_at`, `provider_dispatch_id`, `fallback_reason`).
  - [ ] Lock concrete index set and query mappings.
- [ ] Kubeconfig protection requirements (encryption + redaction + access boundaries).
  - [x] Encryption-at-rest approach selected (`existing secrets/encryption mechanism`).
  - [ ] Lock exact API/storage contract and log-redaction rules.
- [x] Image immutability policy (allow mutable tags or require digests).
  - [x] Decision: allow mutable tags and digest-pinned references; both must work.
  - [ ] Lock validation behavior and error messages for malformed image refs.
- [ ] Cancellation behavior when fallback has started.

## Stage 1 - Code Planning

- [ ] Define execution stages for implementation work (Stages 2-8).
- [ ] Ensure final two stages are `Automated Testing` then `Docs Updates`.
- [ ] Remove manual/rollout stages from execution workflow for this dev-only plan.
- [ ] Map each stage to concrete files/modules before implementation starts.
- [ ] Sequence dependencies for DB settings, router, and remote executors.
- [ ] Freeze implementation start until all Stage 0 deliverables are checked complete.

Deliverables:
- [ ] Implementation stage map with file-level touchpoints.
- [ ] Ordered dependency plan for safe incremental merges.

## Stage 2 - Data model and settings plumbing

- [ ] Add `node_executor` settings read/write helpers in `services/integrations.py`.
- [ ] Add defaults bootstrap for `node_executor` settings.
- [ ] Add DB migration for node run metadata fields:
  - [ ] `selected_provider`
  - [ ] `final_provider`
  - [ ] `provider_dispatch_id`
  - [ ] `dispatch_status`
  - [ ] `fallback_reason`
  - [ ] `dispatch_uncertain`
- [ ] Add DB indexes for provider/filter queries used by run history views.
- [ ] Extend runtime settings page:
  - [ ] provider selector
  - [ ] provider-specific fields
  - [ ] fallback toggles
  - [ ] timeout fields
  - [ ] cancellation fields
- [ ] Add server-side validation for provider-specific settings.
- [ ] Add secure handling path for `k8s_kubeconfig`:
  - [ ] encryption-at-rest via existing secrets mechanism
  - [ ] redaction in logs/API responses
  - [ ] least-privilege read path in runtime service
- [ ] Add effective-config summary endpoint/helper used by runtime.

Deliverables:
- [ ] DB-backed executor settings with env fallback precedence.
- [ ] UI/API to manage executor settings.

## Stage 3 - Execution abstraction in Studio

- [ ] Extract current workspace-based flowchart task execution into `WorkspaceExecutor`.
- [ ] Introduce runtime-agnostic `ExecutionRequest` and `ExecutionResult` models.
- [ ] Add executor router that chooses provider from settings.
- [ ] Keep existing behavior as default path through `WorkspaceExecutor`.
- [ ] Add structured run metadata fields (provider, dispatch ids, fallback reason).

Deliverables:
- [ ] Provider abstraction integrated without behavior regressions in workspace mode.

## Stage 4 - New `llmctl-executor` app + image

- [ ] Create `app/llmctl-executor/` skeleton:
  - [ ] `run.py`
  - [ ] `src/` runtime module(s)
  - [ ] `requirements.txt`
  - [ ] Dockerfile/build script
- [ ] Define execution payload input format (JSON/env/file).
- [ ] Implement single-run execution path and structured output format.
- [ ] Add explicit result contract versioning (`contract_version`) and compatibility checks.
- [ ] Ensure image includes required runtime CLIs already expected by Studio nodes.
- [ ] Add smoke test command for local validation.

Deliverables:
- [ ] Buildable/publishable `llmctl-executor` image.

## Stage 5 - Docker provider implementation

- [ ] Implement `DockerExecutor` in Studio:
  - [ ] container create/start/wait/remove
  - [ ] stdout/stderr capture
  - [ ] exit code and structured result parsing
- [ ] Add docker socket/path config support (`docker_host`).
- [ ] Support running Studio container with mounted docker socket for internal mode.
- [ ] Add cleanup and TTL safeguards for orphaned containers.
- [ ] Add fallback integration on eligible dispatch failures.
- [ ] Implement cancel flow: graceful stop then force kill after configured timeout.

Deliverables:
- [ ] End-to-end node execution through docker provider.

## Stage 6 - Kubernetes provider implementation

- [ ] Implement `KubernetesExecutor` in Studio using Kubernetes API client.
- [ ] Create Job template builder with resource limits and labels.
- [ ] Add in-cluster auth path and kubeconfig-based out-of-cluster path.
- [ ] Implement log streaming/polling and terminal status mapping.
- [ ] Implement cancel flow: delete/terminate with grace then force delete.
- [ ] Implement TTL cleanup policy.
- [ ] Add fallback integration on eligible dispatch failures.
- [ ] Enforce kubeconfig secret handling rules defined in Stage 0/2.

Deliverables:
- [ ] End-to-end node execution through kubernetes provider.

## Stage 7 - Fallback, retries, and idempotency hardening

- [ ] Implement explicit dispatch state machine:
  - [ ] `dispatch_pending`
  - [ ] `dispatch_submitted`
  - [ ] `dispatch_confirmed`
  - [ ] `dispatch_failed`
  - [ ] `fallback_started`
- [ ] Ensure fallback is attempted exactly once.
- [ ] Add retry policy with bounded attempts per provider.
- [ ] Add duplicate-run protection keyed by node run id + provider dispatch id.

Deliverables:
- [ ] Deterministic fallback behavior with no duplicate success paths.

## Stage 8 - Observability and run history UX

- [ ] Persist provider metadata on node runs:
  - [ ] selected provider
  - [ ] final provider
  - [ ] remote id (container id / job name)
  - [ ] fallback reason
- [ ] Add provider/fallback fields to run detail APIs.
- [ ] Update run detail templates to show dispatch and fallback timeline.
- [ ] Add structured logs for provider selection and dispatch lifecycle.
- [ ] Ensure run list/detail queries use new metadata indexes added in Stage 2.

Deliverables:
- [ ] Operators can audit provider routing and fallback decisions.

## Stage 9 - Automated Testing

- [ ] Unit tests:
  - [ ] provider config parsing/validation
  - [ ] router selection precedence (DB vs env)
  - [ ] fallback decision matrix
  - [ ] timeout and cancellation config validation
  - [ ] execution contract version compatibility checks
- [ ] Integration tests:
  - [ ] workspace baseline remains green
  - [ ] docker dispatch success/failure + fallback
  - [ ] kubernetes dispatch success/failure + fallback
  - [ ] cancel behavior per provider
- [ ] Failure-injection tests:
  - [ ] provider unavailable
  - [ ] image pull fail
  - [ ] API timeout
  - [ ] ambiguous dispatch state
  - [ ] fallback-cancellation race handling

Deliverables:
- [ ] Automated confidence gates before merge.

## Stage 10 - Docs Updates

- [ ] Update runtime settings documentation for node executor providers.
- [ ] Update architecture docs for Studio control plane and `llmctl-executor`.
- [ ] Document execution contract versioning and compatibility guarantees.
- [ ] Update Sphinx docs and verify docs build.
- [ ] Update Read the Docs content/config if required.
- [ ] Add operator notes for fallback semantics and cancellation behavior.

Deliverables:
- [ ] Documentation reflects implementation and operational behavior.

## Risks and mitigations

- [ ] Risk: duplicate execution during fallback.
  - [ ] Mitigation: strict dispatch state machine and no fallback on ambiguous start.
  - [ ] Owner: Runtime router implementation (Stage 7).
- [ ] Risk: settings sprawl/invalid combinations.
  - [ ] Mitigation: provider-specific validation + effective-config preview.
  - [ ] Owner: Settings/data model work (Stage 2).
- [ ] Risk: docker socket dependency drift in containerized Studio deployments.
  - [ ] Mitigation: keep docker provider optional; prefer kubernetes provider in cluster.
  - [ ] Owner: Docker provider implementation/docs (Stages 5, 10).
- [ ] Risk: executor image and Studio runtime contract drift.
  - [ ] Mitigation: versioned execution contract with compatibility checks.
  - [ ] Owner: Executor app + contract tests (Stages 4, 9).
- [ ] Risk: insecure kubeconfig handling in DB.
  - [ ] Mitigation: encrypt-at-rest, redact in logs, and restrict read path to runtime service account.
  - [ ] Owner: Settings + k8s provider + docs (Stages 2, 6, 10).

## Open questions

- [ ] What exact `ExecutionResult` schema must `llmctl-executor` return (minimum required fields, optional fields, and version key)?
- [ ] What exact health signal format/protocol is required for dispatch confirmation across docker and kubernetes?
- [ ] For ambiguous dispatch state, is policy always fail + manual retry, or can operators force fallback?
- [ ] Which provider metadata fields are query-critical and must be indexed in run history?
- [ ] What encryption-at-rest mechanism is required for `k8s_kubeconfig` in v1?
  - [x] Direction selected: existing secrets/encryption mechanism.
  - [ ] Need exact implementation contract (where encrypted, who can decrypt, audit/redaction).
- [x] Are mutable image tags allowed in v1, or must provider images be pinned by digest?
  - [x] Decision: tags are allowed; digest references are also supported and valid.
  - [ ] Need exact validation contract for accepted reference syntaxes.
- [ ] During fallback transition, should cancellation target only active execution or both potential remote/local attempts?
