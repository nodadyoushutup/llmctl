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
- [x] `ExecutionResult` required core selected (`Strict Core`): `contract_version`, `status`, `exit_code`, `started_at`, `finished_at`, `stdout`, `stderr`, `error`, `provider_metadata` required; `usage`, `artifacts`, `warnings`, `metrics` optional.
- [x] `ExecutionResult.status` enum selected (`Detailed`): `success|failed|cancelled|timeout|dispatch_failed|dispatch_uncertain|infra_error`.
- [x] `ExecutionResult.error` behavior selected (`Typed Error Object`): required when `status != success`, `null` on success; object shape includes `code`, `message`, optional `details`, optional `retryable`.
- [x] `ExecutionResult.error.code` enum selected (`Compact`): `validation_error|provider_error|dispatch_error|timeout|cancelled|execution_error|infra_error|unknown`.
- [x] `ExecutionResult.error.retryable` policy selected (`Fixed Mapping`): `true` for `provider_error|dispatch_error|timeout|infra_error|unknown`; `false` for `validation_error|cancelled|execution_error`.
- [x] `ExecutionResult` optional-field serialization selected: omit optional rich fields (`usage`, `artifacts`, `warnings`, `metrics`) when unavailable.
- [x] `ExecutionResult.contract_version` policy selected: exact match required (`v1` only); mismatch is `infra_error`.
- [x] Dispatch confirmation protocol direction selected: explicit executor startup log marker.
- [x] Dispatch marker format selected: accept either exact literal marker line or JSON startup event line.
- [x] Dispatch marker contract selected (`Simple Dual Contract`): literal `LLMCTL_EXECUTOR_STARTED`, or JSON `{\"event\":\"executor_started\",\"contract_version\":\"v1\",\"ts\":\"<iso8601>\"}`; first valid marker wins.
- [x] Dispatch marker timeout/invalid handling selected (`Strict + fail closed`): use `dispatch_timeout_seconds`; ignore malformed marker lines; if no valid marker before timeout, treat as dispatch-not-confirmed and follow fallback eligibility rules.
- [x] Ambiguous dispatch policy selected: fail closed (`dispatch_uncertain=true`), no auto-fallback, manual retry only.
- [x] Run-history metadata indexing scope selected: `Extended` (essential + `provider_dispatch_id` + `fallback_reason`).
- [x] Run-history index set selected (`Balanced`): `(created_at DESC)`, `(final_provider, created_at DESC)`, `(dispatch_status, created_at DESC)`, `(dispatch_uncertain, created_at DESC)`, `(provider_dispatch_id)`, `(fallback_reason, created_at DESC)`.
- [x] `k8s_kubeconfig` encryption-at-rest direction selected: reuse existing secrets/encryption mechanism.
- [x] `k8s_kubeconfig` key-management boundary selected: runtime-only decrypt/read path; settings/UI APIs are write/rotate-only and never return plaintext.
- [x] `k8s_kubeconfig` redaction/audit policy selected (`Strict no-plaintext`): never expose plaintext in logs/APIs; return metadata only; redact validation/errors; audit actor+action without secret content.
- [x] `k8s_kubeconfig` storage/API contract selected: store encrypted secret blob in DB and expose metadata-only reads (`is_set`, `updated_at`, `fingerprint`); runtime resolves plaintext via internal runtime-only service method.
- [x] Image reference policy selected: allow tag-only and digest-pinned references; runtime must support both formats.
- [x] Image reference validation contract selected (`Balanced`): accept `repo[:tag]`, `repo@sha256:<64hex>`, and `repo:tag@sha256:<64hex>`; reject malformed refs with validation errors before dispatch.
- [x] Fallback-transition cancellation policy selected: best-effort cancel both active and remote-dispatch handles.
- [x] Fallback-transition cancel ordering selected: parallel cancel both paths immediately, share one `cancel_grace_timeout_seconds` window, then force-kill remaining handles when enabled.
- [x] Risk register scope selected: include orphaned remote resource risk (Docker containers/K8s Jobs) with explicit cleanup/reaper mitigation ownership.
- [x] Stage sequencing decision selected: implement remote providers `docker` first, then `kubernetes`.
- [x] Docker control path selected: Docker Engine API/SDK as primary with Docker CLI subprocess fallback for compatibility.
- [x] Docker CLI fallback trigger selected: activate fallback only when API path is unavailable (connection/init/auth/unreachable), not for normal container runtime failures.
- [x] Docker CLI fallback command surface selected (`Expanded parity`): include lifecycle commands plus diagnostics (`create/start/logs/wait/stop/rm` + `inspect/ps` and basic network checks as needed).
- [x] Docker CLI fallback precondition selected: fallback is permitted only when Docker socket/path is explicitly mounted/configured and reachability preflight succeeds.
- [x] Docker API-down + failed CLI-preflight classification selected: mark as `provider_unavailable` (fallback-eligible to `workspace` when fallback is enabled).
- [x] Docker dispatch retry profile selected: `1 API attempt + 1 CLI attempt` before fallback decision.
- [x] Docker dispatch-timeout budgeting selected: API+CLI attempts share one total `dispatch_timeout_seconds` budget.
- [x] Docker shared-timeout reserve selected: reserve minimum 20% of dispatch budget for CLI attempt.
- [x] Docker timeout enforcement mode selected: `Soft cap` (prefer API attempt continuity; switch to CLI when API is judged stalled and reserved CLI budget is still available).
- [x] Docker stall-threshold policy selected: runtime setting with allowed values `5|10|15` seconds controls soft-cap stall detection.
- [x] Docker stall-threshold default selected: `docker_api_stall_seconds=10`.
- [x] Docker stall-threshold source selected: DB-only (no env fallback override); initialize to default `10` during settings bootstrap.
- [x] Docker API->CLI fallback metadata scope selected (`Compact`): persist `api_failure_category`, `cli_fallback_used=true`, and `cli_preflight_passed`.
- [x] Docker API->CLI fallback metadata storage selected: dedicated DB columns (not provider_metadata JSON).
- [x] API->CLI fallback index selected: add `(cli_fallback_used, created_at DESC)` for fast fallback-activated run filtering.
- [x] API failure-category index selected: add `(api_failure_category, created_at DESC)` for failure-triage filtering.
- [x] `api_failure_category` type selected: constrained string enum (app-validated allowed values) for readable storage with low migration complexity.
- [x] `api_failure_category` enum set selected (`Detailed`): `socket_missing|socket_unreachable|api_unreachable|auth_error|tls_error|timeout|preflight_failed|unknown`.
- [x] API->CLI fallback column nullability/defaults selected (`Pragmatic`): `cli_fallback_used BOOLEAN NOT NULL DEFAULT false`; `cli_preflight_passed BOOLEAN NULL`; `api_failure_category TEXT NULL`.
- [x] API->CLI semantic validation behavior selected: reject inconsistent payloads (`cli_fallback_used=false` with non-null `cli_preflight_passed`) with `validation_error`.
- [x] API->CLI DB integrity enforcement selected: add DB CHECK constraint requiring `cli_preflight_passed IS NULL` when `cli_fallback_used=false`.
- [x] API->CLI DB CHECK constraint name selected: `ck_node_runs_cli_preflight_requires_fallback`.
- [x] Historical run backfill policy selected: migration baseline sets `cli_fallback_used=false`; leaves `api_failure_category` and `cli_preflight_passed` as `NULL` for pre-existing rows.
- [x] Stage 2 migration rollout safety selected: split into two migrations (A: columns/backfill, B: indexes).
- [x] Migration B index creation mode selected: use online/non-blocking index creation when supported; otherwise fall back to standard index creation.
- [x] Migration A operation order selected: add columns first, run baseline backfill second, then enforce constraints/default guarantees.
- [x] `dispatch_status` type selected: constrained string enum (app-validated) for readable filtering and safe schema evolution.
- [x] `dispatch_status` enum set selected (`State-machine`): `dispatch_pending|dispatch_submitted|dispatch_confirmed|dispatch_failed|fallback_started`.
- [x] `dispatch_status` nullability selected: `NOT NULL` for all rows (legacy rows backfilled during Migration A before NOT NULL enforcement).
- [x] Legacy `dispatch_status` backfill value selected: `dispatch_confirmed`.
- [x] `dispatch_status` DB integrity enforcement selected: add DB CHECK constraint for allowed state-machine values.
- [x] `provider_dispatch_id` requirement selected: require non-null when `dispatch_status` is `dispatch_submitted` or `dispatch_confirmed`.
- [x] Provider DB integrity enforcement selected: add DB CHECK constraints for both `selected_provider` and `final_provider` (`workspace|docker|kubernetes`).
- [x] Provider column nullability selected: `selected_provider` and `final_provider` are both `NOT NULL` with legacy backfill to `workspace`.
- [x] `provider_dispatch_id` semantics selected: `TEXT NULL` with uniqueness enforced for non-null values.
- [x] `provider_dispatch_id` namespace policy selected: store as `<provider>:<native_id>` to avoid cross-provider collisions under global uniqueness.
- [x] Legacy runtime-assumption backfill selected: treat pre-existing rows as historical `workspace` runtime executions and populate runtime fields accordingly.
- [x] Legacy synthetic dispatch-id format selected: `legacy-workspace-<row_id>`.
- [x] New workspace dispatch-id policy selected: generate and persist `provider_dispatch_id` for new workspace runs (do not leave it null).
- [x] Workspace identity representation selected: keep workspace identity in a separate metadata field (do not encode in `provider_dispatch_id`).
- [x] Workspace identity storage selected: dedicated DB column (not provider-metadata JSON).
- [x] Workspace identity value format selected: stable logical key (non-path identifier).
- [x] Legacy workspace identity backfill value selected: `default`.
- [x] New workspace identity source selected: canonical runtime setting key (`workspace_identity_key`) drives `workspace_identity` on new runs.
- [x] `workspace_identity_key` mutability policy selected: future-runs-only (setting changes do not rewrite historical run rows).
- [x] `workspace_identity_key` access policy selected: admin-only once auth/RBAC exists; no permission enforcement required in current no-login environment.
- [x] `workspace_identity` scope selected: required on all runs (not workspace-only).
- [x] Workspace identity index selected: add `(workspace_identity, created_at DESC)` for workspace-scoped run filtering.
- [x] `fallback_reason` schema selected: constrained string enum (not free text).
- [x] `fallback_reason` enum set selected (`Compact`): `provider_unavailable|preflight_failed|dispatch_timeout|create_failed|image_pull_failed|config_error|unknown`.
- [x] `fallback_reason` null semantics selected: store `NULL` when fallback was not attempted.
- [x] `fallback_reason` requirement rule selected: require non-null when `dispatch_status=fallback_started`.
- [x] `fallback_reason` DB integrity enforcement selected: add DB CHECK linking `dispatch_status=fallback_started` to non-null `fallback_reason`.
- [x] Fallback-failed audit rule selected: when fallback was attempted and final dispatch state is `dispatch_failed` (with `dispatch_uncertain=false`), require non-null `fallback_reason`.
- [x] Fallback-attempt tracking selected: add `fallback_attempted BOOLEAN NOT NULL DEFAULT false` for deterministic cross-field enforcement.
- [x] Fallback-attempt index selected: add `(fallback_attempted, created_at DESC)` for fallback-attempt filtering.
- [x] `dispatch_uncertain` schema selected: `BOOLEAN NOT NULL DEFAULT false`.
- [x] Uncertain-state consistency rule selected: when `dispatch_uncertain=true`, enforce `fallback_attempted=false` and `fallback_reason=NULL`.
- [x] Fallback terminal-provider rule selected: when `fallback_attempted=true`, terminal `final_provider` is `workspace`.
- [x] Fallback terminal-provider DB integrity enforcement selected: add DB CHECK requiring `final_provider='workspace'` when `fallback_attempted=true`.
- [x] Final-provider switch timing selected: set `final_provider=workspace` immediately when `dispatch_status` transitions to `fallback_started`.
- [x] Initial dispatch state selected: new run rows start as `dispatch_pending`.
- [x] Remote dispatch transition selected: `dispatch_pending -> dispatch_submitted` when provider create/submit API returns success.
- [x] Workspace dispatch handling selected: workspace path stays on the same state machine with provider-specific mapping (no remote API submit step).
- [x] Workspace state transition selected: `dispatch_pending -> dispatch_confirmed` when local workspace process start is observed.
- [x] Remote confirm transition selected: `dispatch_submitted -> dispatch_confirmed` only when valid executor startup marker is observed.
- [x] `dispatch_failed` transition selected: apply only to pre-confirm dispatch failures; post-confirm failures use execution/result status paths.
- [x] `fallback_started` transition selected: set when fallback decision is made and workspace fallback dispatch attempt begins.
- [x] Ambiguous dispatch-state mapping selected: set `dispatch_status=dispatch_failed` and `dispatch_uncertain=true`; no auto-fallback.

## Interview closure (2026-02-16)

- [x] Stage 0 (Requirements Gathering) is complete.
- [x] Stage 1 (Code Planning) is complete.
- [x] Open questions for v1 scope are resolved and locked in the decision log.
- [x] This plan is now execution-ready; implementation starts at Stage 2.

Execution handoff notes:
1. Start directly at Stage 2 and execute stages in order through Stage 10.
2. Treat the current decision log as locked scope unless a new blocker is discovered.
3. If scope changes are required, append them to the decision log with date before implementation.

## Non-negotiable constraints

- [x] Existing node execution behavior must remain functional while rollout is in progress.
- [x] Fallback must be idempotent and must not create duplicate successful runs.
- [x] Workspace provider remains always available as last-resort runtime.
- [x] Provider selection and effective settings must be observable in run history/logs.
- [x] For template/pipeline updates, treat as DB updates unless explicitly asked to update seed data.

## Definition of done

- [x] Studio can execute nodes through `workspace`, `docker`, or `kubernetes` providers via one runtime contract.
- [x] Studio runtime settings UI/API can configure provider + provider-specific options in DB.
- [x] `docker` and `kubernetes` providers can launch `llmctl-executor` containers/jobs successfully.
- [x] Fallback to `workspace` is automatic for eligible remote dispatch failures.
- [x] Node run detail clearly shows selected provider, dispatch status, fallback decisions, and final provider used.
- [x] Regression suite covers provider selection, fallback rules, and cancellation/cleanup semantics.

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
- `workspace_identity_key` (default `default`)

Docker keys:
- `docker_host` (example: `unix:///var/run/docker.sock`)
- `docker_image` (default `llmctl-executor:latest`)
- `docker_network` (optional)
- `docker_pull_policy` (`always|if_not_present|never`)
- `docker_env_json` (optional JSON map)
- `docker_api_stall_seconds` (`5|10|15`, default `10`, DB-only source)

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

## Locked runtime contract (v1)

- `ExecutionResult.contract_version` must be exact `v1`; mismatch is `infra_error`.
- Required `ExecutionResult` fields: `contract_version`, `status`, `exit_code`, `started_at`, `finished_at`, `stdout`, `stderr`, `error`, `provider_metadata`.
- Optional fields (`usage`, `artifacts`, `warnings`, `metrics`) are omitted when unavailable.
- `ExecutionResult.status` enum: `success|failed|cancelled|timeout|dispatch_failed|dispatch_uncertain|infra_error`.
- `ExecutionResult.error` is `null` only for `success`; otherwise required object with `code`, `message`, optional `details`, optional `retryable`.
- `ExecutionResult.error.code` enum: `validation_error|provider_error|dispatch_error|timeout|cancelled|execution_error|infra_error|unknown`.
- Dispatch-confirmed signal accepts either:
  - literal line `LLMCTL_EXECUTOR_STARTED`, or
  - JSON line `{"event":"executor_started","contract_version":"v1","ts":"<iso8601>"}`.
- Invalid marker lines are ignored; if no valid marker appears before `dispatch_timeout_seconds`, dispatch is not confirmed.

## Locked fallback decision table (v1)

| Condition | Dispatch confirmed? | Auto-fallback to `workspace`? | Outcome |
| --- | --- | --- | --- |
| Provider unavailable/misconfigured before remote start | No | Yes (if fallback enabled) | Route to `workspace`; record fallback reason |
| Image pull/auth failure before remote start | No | Yes (if fallback enabled) | Route to `workspace`; record fallback reason |
| Container/Job create API failure before remote start | No | Yes (if fallback enabled) | Route to `workspace`; record fallback reason |
| Dispatch timeout with no valid start marker | No | Yes (if fallback enabled) | Route to `workspace`; record fallback reason |
| Remote execution started and then failed | Yes | No | Return remote failure; no fallback |
| Ambiguous remote state (may have started) | Unknown | No | Mark `dispatch_uncertain=true`; fail closed; manual retry only |
| Any fallback-eligible error while fallback disabled | No | No | Return `dispatch_failed`; no fallback |

## Stage 0 - Requirements Gathering

- [x] Interview stakeholder on unresolved requirements.
- [x] Confirm how kubeconfig is stored (`k8s_kubeconfig` in DB for v1).
- [x] Confirm provider selection scope (global-only for v1).
- [x] Confirm fallback policy scope (global-only for v1).
- [x] Confirm timeout direction (settings-configurable).
- [x] Confirm cancellation strategy (best effort then force kill).
- [x] Confirm rollout expectation (dev-only, no prod phased rollout).
- [x] Confirm execution result contract between Studio and `llmctl-executor`.
  - [x] Select schema shape (`Rich`).
  - [x] Lock required/optional field set (`Strict Core` required + rich optional extensions).
  - [x] Lock value semantics/enums (especially `error` and nullable behavior).
    - [x] Lock `status` enum (`Detailed`: `success|failed|cancelled|timeout|dispatch_failed|dispatch_uncertain|infra_error`).
    - [x] Lock `error` envelope behavior (`Typed Error Object`; `error=null` only for `success`).
    - [x] Lock canonical `error.code` enum (`Compact` set).
    - [x] Lock retryability guidance by `error.code` (`Fixed Mapping`).
    - [x] Lock optional-field serialization behavior (omit unavailable optional rich fields).
    - [x] Lock `contract_version` value/compatibility rules (exact `v1` match required).
- [x] Confirm precise health/heartbeat protocol that defines "execution started" per provider.
  - [x] Select protocol family (`log marker`).
  - [x] Lock marker text contract and parsing behavior for docker/kubernetes.
    - [x] Marker format policy: accept either literal marker or JSON event marker.
    - [x] Lock exact literal text + JSON schema + parsing precedence rules (`Simple Dual Contract`; first valid marker wins).
    - [x] Lock dispatch-confirmation timeout value and invalid-marker handling (`Strict + fail closed`).
- [x] Confirm ambiguous dispatch handling policy (always manual retry vs limited operator override).
- [x] Confirm cancellation semantics during fallback attempts.
  - [x] Policy selected: best-effort cancel both active execution and any known remote dispatch handle.
  - [x] Lock ordering/timeout semantics for dual-path cancellation (`Parallel cancel`: one shared grace window, then force-kill if enabled).
- [x] Confirm provider image pinning policy (`tag` vs `digest`).
  - [x] Policy selected: support both mutable tags and digest-pinned images.
  - [x] Lock validation rules/examples for accepted Docker/K8s image reference forms (`Balanced`: allow `repo[:tag]`, `repo@sha256:<64hex>`, `repo:tag@sha256:<64hex>`; fail fast on malformed refs).
- [x] Confirm query-critical metadata fields for run-history filtering/indexing.
  - [x] Select indexing scope (`Extended`).
  - [x] Lock exact index definitions (single/composite) and expected query patterns.
    - [x] Index set locked (`Balanced`).
    - [x] Query mappings locked:
      - [x] chronological run list (`created_at`)
      - [x] provider-filtered list (`final_provider`, `created_at`)
      - [x] status-filtered list (`dispatch_status`, `created_at`)
      - [x] uncertain-dispatch triage (`dispatch_uncertain`, `created_at`)
      - [x] direct remote-id lookup (`provider_dispatch_id`)
      - [x] fallback-reason audit (`fallback_reason`, `created_at`)
- [x] Confirm encryption-at-rest mechanism for `k8s_kubeconfig` in v1.
  - [x] Select mechanism direction (`existing secrets/encryption path`).
  - [x] Lock exact storage/read interfaces and key management boundary.
    - [x] Key-management boundary selected: runtime-only decrypt/read; settings/UI write/rotate only.
    - [x] Storage/read interface selected: encrypted DB secret + metadata-only read API; runtime-only internal decrypt/read path.
- [x] Write risk register with mitigation owners.

Deliverables:
- [x] Locked runtime contract.
- [x] Locked fallback decision table.
- [x] Risk register section in this doc.

Interview queue to clear Stage 0 blockers:
- [x] `ExecutionResult` v1 schema: required fields, optional fields, and version key.
  - [x] Choose high-level schema shape (`Rich`).
  - [x] Lock exact required/optional field set (`Strict Core` required + rich optional extensions).
  - [x] Lock enum semantics and field-level nullability/constraints.
    - [x] Lock `status` enum (`Detailed` set).
    - [x] Lock `error` nullability/shape baseline.
    - [x] Lock canonical `error.code` enum set (`Compact`).
    - [x] Lock retryability matrix (`Fixed Mapping`).
    - [x] Lock optional-field omission behavior for unavailable rich fields.
    - [x] Lock `contract_version` value and compatibility policy (exact `v1` match).
- [x] Dispatch confirmation protocol by provider (`docker`, `kubernetes`) and exact signal source.
  - [x] Select signal source family (`executor startup log marker`).
  - [x] Lock exact marker text and timeout/parsing rules.
    - [x] Format policy selected: literal or JSON marker is valid.
    - [x] Lock exact accepted literal/JSON forms and conflict handling (`first valid marker wins`).
    - [x] Lock timeout value and invalid-marker behavior (`Strict + fail closed`).
- [x] Ambiguous dispatch policy and whether any operator-forced override exists.
  - [x] Policy selected: always fail + manual retry; no operator-forced fallback in uncertain state.
- [x] Metadata persistence and indexing requirements for run detail/list views.
  - [x] Index scope selected: `Extended` (`selected_provider`, `final_provider`, `dispatch_status`, `dispatch_uncertain`, `created_at`, `provider_dispatch_id`, `fallback_reason`).
  - [x] Lock concrete index set and query mappings (`Balanced` set + query mapping matrix).
- [x] Kubeconfig protection requirements (encryption + redaction + access boundaries).
  - [x] Encryption-at-rest approach selected (`existing secrets/encryption mechanism`).
  - [x] Access boundary selected: runtime-only decrypt/read; no plaintext reveal via settings APIs/UI.
  - [x] Lock exact API/storage contract and log-redaction rules.
    - [x] Log/API redaction + audit behavior selected (`Strict no-plaintext`).
    - [x] Storage/read API contract selected (`encrypted secret + metadata-only read API + runtime-only internal decrypt`).
- [x] Image immutability policy (allow mutable tags or require digests).
  - [x] Decision: allow mutable tags and digest-pinned references; both must work.
  - [x] Lock validation behavior and error messages for malformed image refs (return `validation_error` with message naming accepted formats and digest requirements).
- [x] Cancellation behavior when fallback has started.
  - [x] Decision: best-effort cancel both local active path and remote candidate path.
  - [x] Lock exact cancel ordering and timeout strategy (`Parallel cancel` with shared grace timeout, then force-kill if enabled).

## Stage 1 - Code Planning

- [x] Define execution stages for implementation work (Stages 2-10; implementation execution in Stages 2-8, then `Automated Testing`, then `Docs Updates`).
- [x] Ensure final two stages are `Automated Testing` then `Docs Updates`.
- [x] Remove manual/rollout stages from execution workflow for this dev-only plan.
- [x] Map each stage to concrete files/modules before implementation starts.
- [x] Sequence dependencies for DB settings, router, and remote executors.
  - [x] Docker control-path strategy locked: SDK/API primary, CLI fallback secondary.
  - [x] Docker fallback trigger locked: API-unavailability only.
  - [x] Docker CLI fallback scope locked: expanded lifecycle+diagnostic command set with socket/preflight gate.
  - [x] Docker API-down + failed-preflight outcome locked: classify as `provider_unavailable` and follow fallback-eligible dispatch failure path.
  - [x] Docker retry sequence locked: one API dispatch attempt, then one CLI dispatch attempt, then fallback decision.
  - [x] Docker timeout budgeting locked: both attempts must fit within one shared `dispatch_timeout_seconds` window.
  - [x] Docker budget split locked: hold 20% minimum budget for CLI fallback attempt.
  - [x] Docker timeout enforcement locked: soft cap (not hard preemption at 80%).
  - [x] Docker stall threshold locked as configurable runtime setting (`docker_api_stall_seconds`: `5|10|15`).
- [x] Freeze implementation start until all Stage 0 deliverables are checked complete.
  - [x] Remote provider order locked: `docker` implementation precedes `kubernetes`.
  - [x] Stage 0 deliverables confirmed complete before Stage 1 closure.

Stage map (file-level touchpoints):
- Stage 2: `app/llmctl-studio/src/services/integrations.py`, `app/llmctl-studio/src/core/models.py`, `app/llmctl-studio/src/core/migrations.py`, `app/llmctl-studio/src/web/views.py`, `app/llmctl-studio/src/web/templates/settings_provider.html`.
- Stage 3: `app/llmctl-studio/src/services/tasks.py`, `app/llmctl-studio/src/services/execution/contracts.py` (new), `app/llmctl-studio/src/services/execution/workspace_executor.py` (new), `app/llmctl-studio/src/services/execution/router.py` (new).
- Stage 4: `app/llmctl-executor/run.py` (new), `app/llmctl-executor/src/` (new), `app/llmctl-executor/requirements.txt` (new), `app/llmctl-executor/Dockerfile` (new).
- Stage 5: `app/llmctl-studio/src/services/execution/docker_executor.py` (new), `app/llmctl-studio/src/services/execution/router.py`, `app/llmctl-studio/src/services/tasks.py`, `app/llmctl-studio/src/core/config.py` (if provider config helpers are needed).
- Stage 6: `app/llmctl-studio/src/services/execution/kubernetes_executor.py` (new), `app/llmctl-studio/src/services/execution/router.py`, `app/llmctl-studio/src/services/tasks.py`.
- Stage 7: `app/llmctl-studio/src/services/execution/router.py`, `app/llmctl-studio/src/services/execution/contracts.py`, `app/llmctl-studio/src/services/tasks.py`, `app/llmctl-studio/src/core/models.py`.
- Stage 8: `app/llmctl-studio/src/web/views.py`, `app/llmctl-studio/src/web/templates/run_detail.html`, `app/llmctl-studio/src/web/templates/flowchart_history_run_detail.html`, `app/llmctl-studio/src/web/templates/runs.html`.
- Stage 9: `app/llmctl-studio/tests/` (new/updated unit + integration + failure-injection tests for executor routing/fallback).
- Stage 10: `docs/sphinx/provider_runtime.rst`, `docs/sphinx/changelog.rst`, `docs/sphinx/index.rst` (if TOC/link updates are required).

Ordered dependency plan:
1. Stage 2 must land first (settings + schema + indexes) to unblock router/provider persistence.
2. Stage 3 depends on Stage 2 contracts/settings and establishes workspace baseline parity.
3. Stage 4 depends on Stage 3 contract lock and must be buildable before remote providers are integrated.
4. Stage 5 depends on Stages 2-4; Docker is first remote milestone.
5. Stage 6 depends on Stages 2-4 and follows Stage 5 patterns (`docker` before `kubernetes`).
6. Stage 7 depends on Stages 5-6 to harden retry/fallback/idempotency across both remotes.
7. Stage 8 depends on Stages 2 and 7 so UI/logs reflect final dispatch semantics and persisted metadata.
8. Stage 9 runs after Stages 2-8 are implementation-complete.
9. Stage 10 runs last, after Stage 9, and updates Sphinx/Read the Docs/operator documentation.

Deliverables:
- [x] Implementation stage map with file-level touchpoints.
- [x] Ordered dependency plan for safe incremental merges.

## Stage 2 - Data model and settings plumbing

- [x] Add `node_executor` settings read/write helpers in `services/integrations.py`.
- [x] Add defaults bootstrap for `node_executor` settings.
  - [x] Seed `docker_api_stall_seconds=10` on first bootstrap when missing.
  - [x] Seed `workspace_identity_key=default` on first bootstrap when missing.
- [x] Add DB migration for node run metadata fields:
  - [x] Migration A (schema + backfill baseline; order: columns -> backfill -> constraints/default guarantees)
  - [x] `selected_provider` (`TEXT NOT NULL`, constrained enum)
  - [x] `final_provider` (`TEXT NOT NULL`, constrained enum)
  - [x] `provider_dispatch_id` (`TEXT NULL`, unique for non-null values, namespaced as `<provider>:<native_id>`)
  - [x] `workspace_identity` (`TEXT NOT NULL`, dedicated column, stable logical key)
  - [x] `dispatch_status` (`TEXT NOT NULL`, constrained enum)
  - [x] `fallback_attempted` (`BOOLEAN NOT NULL DEFAULT false`)
  - [x] `fallback_reason` (`TEXT NULL`, constrained enum)
  - [x] `dispatch_uncertain` (`BOOLEAN NOT NULL DEFAULT false`)
  - [x] `api_failure_category` (`TEXT NULL`)
  - [x] `cli_fallback_used` (`BOOLEAN NOT NULL DEFAULT false`)
  - [x] `cli_preflight_passed` (`BOOLEAN NULL`)
  - [x] Backfill existing rows with baseline policy (assume historical `workspace` runtime): `selected_provider=workspace`, `final_provider=workspace`, `dispatch_status=dispatch_confirmed`, `fallback_attempted=false`, `dispatch_uncertain=false`, `fallback_reason=NULL`, `provider_dispatch_id=workspace:legacy-workspace-<row_id>`, `workspace_identity=default`, `cli_fallback_used=false`, `api_failure_category=NULL`, `cli_preflight_passed=NULL`.
  - [x] Add DB CHECK constraint `ck_node_runs_selected_provider_allowed`: `selected_provider IN ('workspace','docker','kubernetes')`.
  - [x] Add DB CHECK constraint `ck_node_runs_final_provider_allowed`: `final_provider IN ('workspace','docker','kubernetes')`.
  - [x] Add DB CHECK constraint `ck_node_runs_dispatch_status_allowed`: `dispatch_status IN ('dispatch_pending','dispatch_submitted','dispatch_confirmed','dispatch_failed','fallback_started')`.
  - [x] Add DB CHECK constraint `ck_node_runs_provider_dispatch_required`: `dispatch_status NOT IN ('dispatch_submitted','dispatch_confirmed') OR provider_dispatch_id IS NOT NULL`.
  - [x] Add DB CHECK constraint `ck_node_runs_cli_preflight_requires_fallback`: `cli_fallback_used=true OR cli_preflight_passed IS NULL`.
  - [x] Add DB CHECK constraint `ck_node_runs_fallback_reason_required`: `dispatch_status != 'fallback_started' OR fallback_reason IS NOT NULL`.
  - [x] Add DB CHECK constraint `ck_node_runs_fallback_reason_consistency`: `fallback_attempted OR fallback_reason IS NULL`.
  - [x] Add DB CHECK constraint `ck_node_runs_uncertain_no_fallback`: `NOT dispatch_uncertain OR (fallback_attempted = false AND fallback_reason IS NULL)`.
  - [x] Add DB CHECK constraint `ck_node_runs_fallback_terminal_provider`: `NOT fallback_attempted OR final_provider = 'workspace'`.
  - [x] Add uniqueness constraint/index for `provider_dispatch_id` (non-null values).
- [x] Add DB indexes for provider/filter queries used by run history views.
  - [x] Migration B (indexes only after Migration A is complete; prefer online/non-blocking create where supported)
  - [x] Add `(workspace_identity, created_at DESC)` for workspace-scoped run filters.
  - [x] Add `(fallback_attempted, created_at DESC)` for fallback-attempt run filters.
  - [x] Add `(cli_fallback_used, created_at DESC)` for fallback-activated run filters.
  - [x] Add `(api_failure_category, created_at DESC)` for fallback failure-category triage filters.
- [x] Extend runtime settings page:
  - [x] provider selector
  - [x] provider-specific fields
  - [x] fallback toggles
  - [x] timeout fields
  - [x] cancellation fields
  - [x] docker stall-threshold selector (`docker_api_stall_seconds`: `5|10|15`)
- [x] Add server-side validation for provider-specific settings.
  - [x] Enforce `docker_api_stall_seconds` enum validation (`5|10|15`).
  - [x] Reject env-based override for `docker_api_stall_seconds` (DB-only).
  - [x] Validate `workspace_identity_key` as stable logical key (non-empty, non-path).
  - [x] Defer `workspace_identity_key` RBAC gate until auth system exists; mark future requirement as admin-only updates.
  - [x] Validate `workspace_identity` is present and stable logical key formatted (non-empty, no absolute filesystem paths).
  - [x] Validate `provider_dispatch_id` namespace format when non-null (`<provider>:<native_id>` with allowed provider prefix).
  - [x] Enforce `provider_dispatch_id IS NOT NULL` when `dispatch_status` is `dispatch_submitted` or `dispatch_confirmed`.
  - [x] Enforce non-retroactive semantics: updating `workspace_identity_key` affects new runs only.
  - [x] Validate `dispatch_status` against state-machine enum values at write-time (`dispatch_pending|dispatch_submitted|dispatch_confirmed|dispatch_failed|fallback_started`).
  - [x] Validate `fallback_reason` against compact enum values when non-null (`provider_unavailable|preflight_failed|dispatch_timeout|create_failed|image_pull_failed|config_error|unknown`).
  - [x] Enforce `fallback_reason IS NULL` when `fallback_attempted=false`.
  - [x] Enforce `fallback_attempted=true` when `dispatch_status=fallback_started`.
  - [x] Enforce `fallback_reason IS NOT NULL` when `dispatch_status=fallback_started`.
  - [x] Enforce `fallback_reason IS NOT NULL` when `fallback_attempted=true`, terminal `dispatch_status=dispatch_failed`, and `dispatch_uncertain=false`.
  - [x] Ensure `dispatch_uncertain` is always present (never null).
  - [x] Enforce uncertain-state consistency: if `dispatch_uncertain=true`, then `fallback_attempted=false` and `fallback_reason IS NULL`.
  - [x] Enforce fallback terminal-provider consistency: if `fallback_attempted=true`, terminal `final_provider` must be `workspace`.
  - [x] Validate `api_failure_category` against detailed enum values at write-time (`socket_missing|socket_unreachable|api_unreachable|auth_error|tls_error|timeout|preflight_failed|unknown`).
  - [x] Enforce semantic consistency: reject request when `cli_preflight_passed` is non-null and `cli_fallback_used=false` (`validation_error`).
- [x] Add secure handling path for `k8s_kubeconfig`:
  - [x] encryption-at-rest via existing secrets mechanism
  - [x] redaction in logs/API responses
  - [x] least-privilege read path in runtime service
- [x] Add effective-config summary endpoint/helper used by runtime.

Deliverables:
- [x] DB-backed executor settings with env fallback precedence.
- [x] UI/API to manage executor settings.

## Stage 3 - Execution abstraction in Studio

- [x] Extract current workspace-based flowchart task execution into `WorkspaceExecutor`.
- [x] Introduce runtime-agnostic `ExecutionRequest` and `ExecutionResult` models.
- [x] Add executor router that chooses provider from settings.
- [x] Keep existing behavior as default path through `WorkspaceExecutor`.
- [x] Add structured run metadata fields (provider, dispatch ids, fallback reason).
  - [x] Generate `provider_dispatch_id` for workspace runs (`workspace:workspace-<run_id>`) and persist it with run metadata.
  - [x] Populate `workspace_identity` for all providers from configured `workspace_identity_key` snapshot at run creation and persist it in dedicated DB column separate from `provider_dispatch_id`.

Deliverables:
- [x] Provider abstraction integrated without behavior regressions in workspace mode.

## Stage 4 - New `llmctl-executor` app + image

- [x] Create `app/llmctl-executor/` skeleton:
  - [x] `run.py`
  - [x] `src/` runtime module(s)
  - [x] `requirements.txt`
  - [x] Dockerfile/build script
- [x] Define execution payload input format (JSON/env/file).
- [x] Implement single-run execution path and structured output format.
- [x] Add explicit result contract versioning (`contract_version`) and compatibility checks.
- [x] Ensure image includes required runtime CLIs already expected by Studio nodes.
- [x] Add smoke test command for local validation.

Deliverables:
- [x] Buildable/publishable `llmctl-executor` image.

## Stage 5 - Docker provider implementation

- [x] Implement `DockerExecutor` in Studio:
  - [x] API/SDK control path as default execution path.
  - [x] CLI fallback path for expanded lifecycle+diagnostic flows (`create/start/logs/wait/stop/rm` + `inspect/ps`/network checks) when API path is unavailable (connection/init/auth/unreachable only).
  - [x] Enforce fallback precondition: require docker socket/path mount/config + successful preflight reachability check before CLI fallback can activate.
  - [x] If API path is unavailable and CLI preflight fails, classify dispatch outcome as `provider_unavailable` (fallback-eligible when enabled).
  - [x] container create/start/wait/remove
  - [x] stdout/stderr capture
  - [x] exit code and structured result parsing
- [x] Add docker socket/path config support (`docker_host`).
- [x] Support running Studio container with mounted docker socket for internal mode.
- [x] Add cleanup and TTL safeguards for orphaned containers.
- [x] Add fallback integration on eligible dispatch failures.
- [x] Implement cancel flow: graceful stop then force kill after configured timeout.

Deliverables:
- [x] End-to-end node execution through docker provider.

## Stage 6 - Kubernetes provider implementation

- [x] Implement `KubernetesExecutor` in Studio using Kubernetes API client.
- [x] Create Job template builder with resource limits and labels.
- [x] Add in-cluster auth path and kubeconfig-based out-of-cluster path.
- [x] Implement log streaming/polling and terminal status mapping.
- [x] Implement cancel flow: delete/terminate with grace then force delete.
- [x] Implement TTL cleanup policy.
- [x] Add fallback integration on eligible dispatch failures.
- [x] Enforce kubeconfig secret handling rules defined in Stage 0/2.

Deliverables:
- [x] End-to-end node execution through kubernetes provider.

## Stage 7 - Fallback, retries, and idempotency hardening

- [x] Implement explicit dispatch state machine:
  - [x] `dispatch_pending`
  - [x] `dispatch_submitted`
  - [x] `dispatch_confirmed`
  - [x] `dispatch_failed`
  - [x] `fallback_started`
  - [x] Initialize all new run rows to `dispatch_pending` before any provider dispatch attempt.
  - [x] Transition remote providers (`docker`/`kubernetes`) to `dispatch_submitted` only after successful provider API submit/create.
  - [x] Apply explicit workspace mapping: `dispatch_pending -> dispatch_confirmed` on local process start signal.
  - [x] Transition remote providers (`docker`/`kubernetes`) from `dispatch_submitted -> dispatch_confirmed` only on valid startup marker signal.
  - [x] Mark `dispatch_failed` only for failures before `dispatch_confirmed`; keep post-confirm failures out of dispatch-state failure transitions.
  - [x] Set `fallback_attempted=true`, `final_provider=workspace`, and transition to `fallback_started` immediately when fallback path is selected and workspace fallback dispatch begins.
  - [x] On ambiguous remote state, set `dispatch_status=dispatch_failed` and `dispatch_uncertain=true` with no auto-fallback.
- [x] Ensure fallback is attempted exactly once.
- [x] Add retry policy with bounded attempts per provider.
  - [x] Enforce Docker retry order: API attempt first, CLI attempt second, then fallback/no-fallback evaluation.
  - [x] Ensure Docker retry count in v1 is fixed to one API attempt and one CLI attempt (no extra loops).
  - [x] Enforce shared timeout budgeting: API+CLI combined execution may not exceed one `dispatch_timeout_seconds` window.
  - [x] Reserve minimum 20% of dispatch budget for CLI attempt to avoid starvation.
  - [x] Implement soft-cap switch rule: only move from API to CLI when API path is considered stalled for configured `docker_api_stall_seconds` and CLI reserved budget remains.
- [x] Add duplicate-run protection keyed by node run id + provider dispatch id.

Deliverables:
- [x] Deterministic fallback behavior with no duplicate success paths.

## Stage 8 - Observability and run history UX

- [x] Persist provider metadata on node runs:
  - [x] selected provider
  - [x] final provider
  - [x] remote id (container id / job name)
  - [x] workspace identity (`workspace_identity`)
  - [x] fallback reason
  - [x] API->CLI fallback columns (`api_failure_category`, `cli_fallback_used`, `cli_preflight_passed`)
- [x] Add provider/fallback fields to run detail APIs.
- [x] Update run detail templates to show dispatch and fallback timeline.
- [x] Add structured logs for provider selection and dispatch lifecycle.
- [x] Ensure run list/detail queries use new metadata indexes added in Stage 2.

Deliverables:
- [x] Operators can audit provider routing and fallback decisions.

## Stage 9 - Automated Testing

- [x] Unit tests:
  - [x] provider config parsing/validation
  - [x] router selection precedence (DB vs env)
  - [x] fallback decision matrix
  - [x] timeout and cancellation config validation
  - [x] execution contract version compatibility checks
- [x] Integration tests:
  - [x] workspace baseline remains green
  - [x] docker dispatch success/failure + fallback
  - [x] kubernetes dispatch success/failure + fallback
  - [x] cancel behavior per provider
- [x] Failure-injection tests:
  - [x] provider unavailable
  - [x] image pull fail
  - [x] API timeout
  - [x] ambiguous dispatch state
  - [x] fallback-cancellation race handling

Deliverables:
- [x] Automated confidence gates before merge.

Progress notes (2026-02-16):
- [x] Runtime suite gate passed locally: `38` tests across node executor stages, realtime parity, and executor contract tests.
- [x] Kubernetes environment smoke checks passed against active context (`kubectl cluster-info`, node/pod listing, executor preflight).
- [x] Added targeted Stage 9 coverage for Docker API timeout fallback metadata, image-pull failure classification, Docker cancel-on-timeout behavior, and fallback dispatch race fail-closed semantics.
- [x] Added Sphinx operator guide `docs/sphinx/node_executor_runtime.rst` covering runtime settings, architecture, execution contract versioning, fallback semantics, cancellation semantics, and run-history observability.
- [x] Verified Sphinx build with `./.venv/bin/python3 -m sphinx -b html docs/sphinx docs/sphinx/_build/html` (build succeeded; existing autosummary cross-reference warnings in generated API docs remain non-blocking).
- [x] Read the Docs configuration remains valid; no `.readthedocs.yaml` changes were required for this update.

## Stage 10 - Docs Updates

- [x] Update runtime settings documentation for node executor providers.
- [x] Update architecture docs for Studio control plane and `llmctl-executor`.
- [x] Document execution contract versioning and compatibility guarantees.
- [x] Update Sphinx docs and verify docs build.
- [x] Update Read the Docs content/config if required.
- [x] Add operator notes for fallback semantics and cancellation behavior.

Deliverables:
- [x] Documentation reflects implementation and operational behavior.

## Risks and mitigations

- [x] Risk: duplicate execution during fallback.
  - [x] Mitigation: strict dispatch state machine and no fallback on ambiguous start.
  - [x] Owner: Runtime router implementation (Stage 7).
- [x] Risk: settings sprawl/invalid combinations.
  - [x] Mitigation: provider-specific validation + effective-config preview.
  - [x] Owner: Settings/data model work (Stage 2).
- [x] Risk: docker socket dependency drift in containerized Studio deployments.
  - [x] Mitigation: keep docker provider optional; prefer kubernetes provider in cluster.
  - [x] Owner: Docker provider implementation/docs (Stages 5, 10).
- [x] Risk: executor image and Studio runtime contract drift.
  - [x] Mitigation: versioned execution contract with compatibility checks.
  - [x] Owner: Executor app + contract tests (Stages 4, 9).
- [x] Risk: insecure kubeconfig handling in DB.
  - [x] Mitigation: encrypt-at-rest, redact in logs, and restrict read path to runtime service account.
  - [x] Owner: Settings + k8s provider + docs (Stages 2, 6, 10).
- [x] Risk: orphaned remote resources after Studio crash/network partition (`docker` containers or `kubernetes` Jobs).
  - [x] Mitigation: provider cleanup/reaper loop + startup reconciliation + TTL/label-based garbage collection.
  - [x] Owner: Docker + Kubernetes provider implementation (Stages 5, 6) and operator docs (Stage 10).

## Open questions

- [x] What exact `ExecutionResult` schema must `llmctl-executor` return (minimum required fields, optional fields, and version key)?
  - [x] Required core selected (`Strict Core`) + rich optional extension set.
  - [x] Need final enum/nullability/value constraints.
    - [x] `status` enum selected (`Detailed` set).
    - [x] `error` shape/nullability selected (`Typed Error Object`; null only on success).
    - [x] Canonical `error.code` enum selected (`Compact` set).
    - [x] Retryability semantics selected (`Fixed Mapping`).
    - [x] Optional-field serialization selected (omit unavailable optional rich fields).
    - [x] `contract_version` policy selected (exact `v1` match).
- [x] What exact health signal format/protocol is required for dispatch confirmation across docker and kubernetes?
  - [x] Startup signal format policy selected: accept literal marker line or JSON event line.
  - [x] Marker values/schema and parser precedence selected (`Simple Dual Contract`; first valid marker wins).
  - [x] Timeout and invalid-marker behavior selected (`Strict + fail closed`).
- [x] For ambiguous dispatch state, is policy always fail + manual retry, or can operators force fallback?
- [x] Which provider metadata fields are query-critical and must be indexed in run history?
  - [x] `Extended` field set confirmed as query-critical.
  - [x] Concrete index set selected (`Balanced`) with query mapping coverage.
- [x] What encryption-at-rest mechanism is required for `k8s_kubeconfig` in v1?
  - [x] Direction selected: existing secrets/encryption mechanism.
  - [x] Implementation contract selected: encrypted DB secret storage; metadata-only settings reads (`is_set`, `updated_at`, `fingerprint`); runtime-only internal decrypt/read; strict no-plaintext redaction/audit.
- [x] Are mutable image tags allowed in v1, or must provider images be pinned by digest?
  - [x] Decision: tags are allowed; digest references are also supported and valid.
  - [x] Validation contract selected (`Balanced`): accept `repo[:tag]`, `repo@sha256:<64hex>`, `repo:tag@sha256:<64hex>`; reject malformed refs pre-dispatch with explicit accepted-format guidance.
- [x] During fallback transition, should cancellation target only active execution or both potential remote/local attempts?
  - [x] Decision: target both paths with best-effort cancellation to prevent straggler execution.
  - [x] Ordering/timeout semantics selected: parallel cancel both paths, use one `cancel_grace_timeout_seconds` window, then force-kill remaining handles when enabled.
