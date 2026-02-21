# Memory Node Mode-Selectable Behavior Plan

Goal: implement explicit memory-node mode selection (`llm_guided` vs `deterministic`) so users can choose behavior per node, with new nodes defaulting to `llm_guided`, existing nodes migrated to `llm_guided`, and deterministic mode preserved exactly as current behavior.

## Stage 0 - Requirements Gathering

- [x] Confirm node mode selector requirement and supported values.
- [x] Confirm where mode is configured (inspector and API contract).
- [x] Confirm default mode for newly created memory nodes.
- [x] Confirm migration requirement for existing memory-node configs/data.
- [x] Confirm mode granularity (single node-level mode vs per-action mode).
- [x] Confirm deterministic mode compatibility policy.
- [x] Confirm rollout/cutover preference.
- [x] Confirm failure behavior matrix by mode and action (`add`/`retrieve`).
- [x] Confirm LLM-guided fallback policy on inference/validation/runtime failure.
- [x] Confirm deterministic-mode fallback policy on runtime failure.
- [x] Confirm degraded marker behavior and error envelope behavior by mode.
- [x] Confirm strictness defaults for retrieval limits and confidence gating.
- [x] Confirm failure-control defaults (`retry_count`, `fallback_enabled`) and max bounds.
- [x] Confirm Stage 0 completion and approval to begin Stage 1.
  - [x] User approved Stage 1 kickoff on 2026-02-21 via: "execute stage 1 of our memory plan".

## Stage 0 - Interview Notes (Captured)

- [x] Mode selector is explicit and user-visible in inspector/API: `llm_guided` or `deterministic`.
- [x] New memory nodes default to `llm_guided`.
- [x] Existing memory-node records are migrated to `llm_guided` via startup/deployment DB migration.
- [x] Migration policy is fail-fast if any row cannot be safely migrated.
- [x] Mode is single node-level setting (applies to both `add` and `retrieve`); action selector remains separate.
- [x] Deterministic primary execution remains current behavior; fallback to `llm_guided` is allowed only after deterministic retries are exhausted and fallback is enabled.
- [x] No rollout/cutover switch is requested.
- [x] Inspector includes a dedicated `Failure` section for memory nodes.
- [x] `Failure` section must include configurable retry count.
- [x] `Failure` section must include a toggle for fallback enablement.
- [x] Fallback target is opposite mode:
- [x] `llm_guided` failure fallback target is `deterministic`.
- [x] `deterministic` failure fallback target is `llm_guided`.
- [x] If fallback attempt also fails, fail node hard (no second fallback hop/looping).
- [x] Retry policy: retries apply to primary mode only; fallback mode gets one attempt.
- [x] Deterministic failure signals include runtime error, empty result, and invalid result; these count toward deterministic retry exhaustion before fallback to `llm_guided`.
- [x] If fallback succeeds, mark degraded success: `execution_status=success_with_warning`, `fallback_used=true`, and include `fallback_reason` plus `failed_mode`.
- [x] Failure controls defaults/bounds: `retry_count` default is `1`, allowed range `0..5` (UI/backend clamp to max `5`).
- [x] `fallback_enabled` default is `true` for new memory nodes.
- [x] Failure semantics are identical for `add` and `retrieve` actions (same retry/fallback/degraded rules).
- [x] Strictness baseline: validation-strict and confidence-advisory (schema validity is required; confidence is recorded but does not block execution).

## Stage 1 - Code Planning

- [x] Define implementation boundaries between mode dispatch, deterministic path reuse, LLM-guided inference, persistence, and observability.
  - [x] Backend config boundary: update memory config sanitization in `app/llmctl-studio-backend/src/web/views/shared.py` (`_sanitize_memory_node_config`) and all flowchart save paths that already call it.
  - [x] Frontend config boundary: update memory defaults + normalization + inspector controls in `app/llmctl-studio-frontend/src/components/FlowchartWorkspaceEditor.jsx`.
  - [x] Runtime dispatch boundary: keep memory-node branch in `app/llmctl-studio-backend/src/services/tasks.py` as the single mode dispatcher, routing to deterministic vs llm-guided execution helpers.
  - [x] Deterministic reuse boundary: deterministic mode must reuse current `_execute_flowchart_memory_node` behavior and existing deterministic tooling scaffolding.
  - [x] LLM-guided boundary: add dedicated helpers for llm-guided `add`/`retrieve` inference while reusing current persistence/query plumbing.
  - [x] Persistence boundary: continue using existing `Memory` ORM read/write paths and `NodeArtifact` persistence (`_persist_memory_node_artifact`) with no new memory storage table.
  - [x] Observability boundary: preserve `validate_special_node_output_contract`, deterministic tooling trace envelopes, and runtime degraded marker plumbing in `services/runtime_contracts.py`.
- [x] Freeze memory-node config contract updates (`mode` + defaults + normalization) across backend and frontend.
  - [x] Canonical config keys for memory nodes: `action`, `mode`, `additive_prompt`, `retry_count`, `fallback_enabled`, `retention_mode`, `retention_ttl_seconds`, `retention_max_count`.
  - [x] `mode` allowed values: `llm_guided` and `deterministic`; default `llm_guided` for new memory nodes in frontend and backend sanitization.
  - [x] Failure controls: `retry_count` default `1`, clamp to `0..5`; `fallback_enabled` default `true`.
  - [x] Backend sanitizer stores canonical values only; invalid `mode` or malformed failure controls raise validation errors.
  - [x] Frontend inspector exposes explicit mode selector plus dedicated Failure controls section for memory nodes only.
  - [x] API payload contract for flowchart nodes continues to return `config` JSON; memory node config must include normalized canonical values after save.
- [x] Freeze migration strategy details (schema/defaulting/data backfill behavior and fail-fast semantics).
  - [x] Migration implementation target: startup/deployment schema path in `app/llmctl-studio-backend/src/core/db.py` so migration runs before runtime execution.
  - [x] Backfill scope: all `flowchart_nodes` rows where `node_type='memory'`.
  - [x] Backfill behavior: parse `config_json` object, set missing/invalid `mode` to `llm_guided`, and set missing failure-control defaults to canonical defaults.
  - [x] Fail-fast semantics: if any memory-node `config_json` row is malformed/unmigratable, raise and abort migration transaction/startup.
  - [x] No compatibility toggle or soft-skip path; migration is authoritative and blocking on error.
- [x] Freeze per-mode failure/degraded semantics and runtime contract expectations.
  - [x] Primary attempts: execute primary mode for `1 + retry_count` attempts; retries apply only to primary mode.
  - [x] Fallback attempts: at most one fallback attempt in opposite mode when `fallback_enabled=true` and primary attempts are exhausted.
  - [x] Deterministic primary failure signals: runtime error, empty result, or invalid result count toward retry exhaustion.
  - [x] LLM-guided primary failure signals: inference failure, validation failure, or runtime failure count toward retry exhaustion.
  - [x] On fallback success: return degraded success with `execution_status=success_with_warning`, `fallback_used=true`, plus `failed_mode` and `fallback_reason`.
  - [x] On fallback failure: fail node hard; no second fallback hop/loop.
  - [x] Semantics are identical for memory `add` and `retrieve`.
  - [x] Deterministic primary path remains behavior-equivalent before fallback decisioning.
- [x] Define Stage 2 through Stage X execution order based on Stage 0 decisions.
  - [x] Stage 2: finalize scope-level contracts (mode/action/failure/migration acceptance).
  - [x] Stage 3: land config contract + DB migration.
  - [x] Stage 4: implement runtime mode dispatch.
  - [x] Stage 5: implement llm-guided `add`.
  - [x] Stage 6: implement llm-guided `retrieve`.
  - [x] Stage 7: implement failure semantics + degraded markers/fallback metadata.
  - [x] Stage 8: automated tests for contract/migration/runtime/failure semantics.
  - [x] Stage 9: docs updates (Sphinx/RTD + planning evidence).
- [x] Ensure final two stages are `Automated Testing` and `Docs Updates`.
  - [x] Confirmed: Stage 8 is `Automated Testing`; Stage 9 is `Docs Updates`.

## Stage 2 - Scope-Specific Planning

- [x] Define exact `mode` contract in backend sanitization and frontend inspector payloads.
  - [x] Backend config canonicalization target: `app/llmctl-studio-backend/src/web/views/shared.py` (`_sanitize_memory_node_config`).
  - [x] Memory `config.mode` canonical values are only `llm_guided` and `deterministic`.
  - [x] Missing/blank `config.mode` defaults to `llm_guided`; non-empty invalid values fail validation.
  - [x] Memory failure controls contract:
    - [x] `config.retry_count`: integer, default `1`, clamped to `0..5`.
    - [x] `config.fallback_enabled`: boolean, default `true`.
  - [x] Frontend contract target: `app/llmctl-studio-frontend/src/components/FlowchartWorkspaceEditor.jsx`.
  - [x] New memory node defaults include `mode=llm_guided`, `retry_count=1`, `fallback_enabled=true`.
  - [x] Inspector renders explicit memory-mode selector and dedicated Failure controls section.
  - [x] Frontend normalization emits only canonical mode/failure-control values in `onGraphChange` payloads.
- [x] Define deterministic-mode output contract parity with existing behavior.
  - [x] Deterministic mode reuses existing `_execute_flowchart_memory_node` implementation in `app/llmctl-studio-backend/src/services/tasks.py` without behavior drift.
  - [x] Deterministic output-state shape remains parity with current memory contract:
    - [x] `node_type`, `action`, `action_prompt_template`, `internal_action_prompt`, `action_results`,
    - [x] `additive_prompt`, `inferred_prompt`, `effective_prompt`,
    - [x] `memory_id`, `mcp_server_keys`, `attachments`, `retrieved_memories`, `stored_memory`, `execution_index`.
  - [x] Deterministic contract validation remains through `validate_special_node_output_contract` in `app/llmctl-studio-backend/src/services/runtime_contracts.py`.
  - [x] Deterministic persistence/query semantics remain unchanged (existing `Memory` ORM fetch/create/update + existing `limit` handling).
- [x] Define LLM-guided `add` inference contract (prompt shape, expected output, validation, normalization).
  - [x] LLM-guided add uses prompt envelope flow (`_build_task_payload`) and LLM runtime dispatch (`_run_llm`) in `app/llmctl-studio-backend/src/services/tasks.py`.
  - [x] Inference prompt includes: memory action template, additive prompt, inferred upstream context, and flowchart input context.
  - [x] LLM output parsing is strict JSON object via `_parse_strict_json_object_output` (no prose/fenced text accepted).
  - [x] LLM-guided add expected JSON shape:
    - [x] required: `text` (string, non-empty after trim).
    - [x] optional: `store_mode` (`append` or `replace`), `confidence` (numeric advisory).
  - [x] Normalization:
    - [x] `text` trimmed and required.
    - [x] `store_mode` normalized to `append|replace` with default `append`.
    - [x] `confidence` normalized to `0..1` when parseable; omitted otherwise (non-blocking advisory).
  - [x] Persistence path for llm-guided add remains current deterministic DB write behavior (existing create/update logic).
- [x] Define LLM-guided `retrieve` inference contract (intent/query/filter schema and bounds).
  - [x] LLM-guided retrieve uses same prompt envelope + dispatch path as llm-guided add.
  - [x] LLM output parsing is strict JSON object via `_parse_strict_json_object_output`.
  - [x] LLM-guided retrieve expected JSON shape:
    - [x] optional: `query_text` (string), `memory_id` (positive integer), `limit` (integer), `confidence` (numeric advisory).
  - [x] Normalization/bounds:
    - [x] `query_text` trimmed; empty string means no text filter.
    - [x] `memory_id` must be positive when supplied, else omitted.
    - [x] `limit` defaults to node-config/default retrieval limit; clamp inferred values to `1..50`.
    - [x] `confidence` normalized to `0..1` when parseable; never blocks execution.
  - [x] Execution precedence:
    - [x] If `node_ref_id` is set, retrieve that memory directly (existing deterministic behavior preserved).
    - [x] Else if inferred `memory_id` is present, retrieve by id.
    - [x] Else execute query-based retrieval using `query_text` + limit.
- [x] Define per-mode failure behavior matrix and status mapping.
  - [x] Failure semantics apply identically for both actions (`add`, `retrieve`).
  - [x] Primary-attempt policy: `1 + retry_count` attempts in selected mode; fallback mode gets exactly one attempt.
  - [x] Failure matrix:
    | primary mode | primary result | fallback_enabled | fallback result | node outcome |
    | --- | --- | --- | --- | --- |
    | `deterministic` or `llm_guided` | success | any | n/a | success |
    | `deterministic` or `llm_guided` | fail | false | n/a | hard failure |
    | `deterministic` or `llm_guided` | fail | true | success | degraded success |
    | `deterministic` or `llm_guided` | fail | true | fail | hard failure |
  - [x] Degraded success status mapping:
    - [x] `execution_status=success_with_warning`
    - [x] `fallback_used=true`
    - [x] include `failed_mode` (`deterministic|llm_guided`) and `fallback_reason`.
  - [x] Hard-failure mapping:
    - [x] raise node execution error after final allowed attempt.
    - [x] no second fallback hop.
  - [x] Canonical fallback reasons to emit: `primary_runtime_error`, `primary_empty_result`, `primary_invalid_result`, `llm_inference_error`, `llm_validation_error`, `fallback_runtime_error`.
- [x] Define migration implementation details and acceptance criteria.
  - [x] Migration location: `app/llmctl-studio-backend/src/core/db.py` within `_ensure_schema()` startup migration flow.
  - [x] Add migration helper to backfill memory-node config defaults in `flowchart_nodes.config_json` rows where `node_type='memory'`.
  - [x] Migration algorithm:
    - [x] Select memory-node rows ordered by id.
    - [x] Parse `config_json` as JSON object; fail on malformed/non-object payload.
    - [x] Apply canonical defaults/normalization for `mode`, `retry_count`, and `fallback_enabled`.
    - [x] Persist updated canonical JSON only when payload changed.
  - [x] Fail-fast policy: first malformed/unmigratable row raises a migration error that aborts startup transaction.
  - [x] Acceptance criteria:
    - [x] Existing memory rows missing `mode` are backfilled to `llm_guided`.
    - [x] Existing valid `mode=deterministic` is preserved.
    - [x] Missing failure controls are backfilled to `retry_count=1` and `fallback_enabled=true`.
    - [x] Non-memory flowchart node rows are untouched.
    - [x] Migration is idempotent on repeated startup runs.

## Stage 3 - Execution: Config Contract + Migration

- [x] Add backend config normalization/validation for memory-node `mode`.
  - [x] Implemented in `app/llmctl-studio-backend/src/web/views/shared.py`:
    - [x] `config.mode` normalization + validation (`llm_guided|deterministic`).
    - [x] failure controls normalization (`retry_count`, `fallback_enabled`) with defaults/bounds.
- [x] Add frontend inspector mode selector with explicit options and defaults.
  - [x] Implemented in `app/llmctl-studio-frontend/src/components/FlowchartWorkspaceEditor.jsx`:
    - [x] memory defaults now include `mode=llm_guided`, `retry_count=1`, `fallback_enabled=true`.
    - [x] inspector adds memory `mode` selector and dedicated `Failure` controls section.
    - [x] memory config normalization emits canonical values for `mode`, `retry_count`, `fallback_enabled`.
- [x] Implement startup/deployment DB migration to set existing memory nodes to `llm_guided`.
  - [x] Implemented startup migration hook in `app/llmctl-studio-backend/src/core/db.py` via `_migrate_memory_node_mode_defaults(connection)`.
  - [x] Backfill applies to `flowchart_nodes` where `node_type='memory'` and normalizes `mode`, `retry_count`, `fallback_enabled`.
- [x] Add fail-fast migration error behavior for malformed/unmigratable rows.
  - [x] Migration now raises runtime errors when memory-node `config_json` is malformed JSON or non-object payload.
  - [x] Added migration-helper unit tests in `app/llmctl-studio-backend/tests/test_memory_node_mode_migration_stage3.py`.
  - [x] Added flowchart API coverage for memory defaults/invalid mode in `app/llmctl-studio-backend/tests/test_flowchart_stage9.py`.

## Stage 4 - Execution: Runtime Mode Dispatch

- [x] Add mode-based branching in memory node runtime execution.
  - [x] Added `mode` normalization + runtime dispatch in `app/llmctl-studio-backend/src/services/tasks.py` (`_execute_flowchart_memory_node`).
- [x] Keep deterministic branch codepath behavior-equivalent to current implementation.
  - [x] Existing deterministic implementation moved intact to `_execute_flowchart_memory_node_deterministic` with no behavioral drift.
- [x] Route `llm_guided` mode to new inference-based execution helpers.
  - [x] Added llm-guided helper entry points in `app/llmctl-studio-backend/src/services/tasks.py`:
    - [x] `_execute_flowchart_memory_node_llm_guided`
    - [x] `_execute_flowchart_memory_node_llm_guided_add`
    - [x] `_execute_flowchart_memory_node_llm_guided_retrieve`
- [x] Preserve action selector semantics (`add`/`retrieve`) across both modes.
  - [x] Added action-based llm-guided dispatch with explicit validation for unsupported actions.
  - [x] Added unit coverage in `app/llmctl-studio-backend/tests/test_memory_node_mode_dispatch_stage4.py`.

## Stage 5 - Execution: LLM-Guided Add

- [x] Implement LLM inference for memory `add` using input context + additive prompt guidance.
  - [x] Implemented llm-guided add runtime in `app/llmctl-studio-backend/src/services/tasks.py` via `_execute_flowchart_memory_node_llm_guided_add`.
  - [x] Inference prompt now includes memory action template, additive prompt, inferred upstream prompt, and flowchart input context.
  - [x] Inference now uses prompt-envelope flow (`_build_task_payload`) and runtime dispatch (`_run_llm` + `_llm_dispatch_scope`).
- [x] Validate and normalize inferred add payload before persistence.
  - [x] Added strict parsing (`_parse_strict_json_object_output`) and payload normalization (`_normalize_memory_llm_guided_add_payload`) with:
    - [x] required non-empty `text`
    - [x] normalized `store_mode` (`append|replace`)
    - [x] advisory `confidence` normalization to `0..1` when parseable
- [x] Persist inferred memory text via existing deterministic DB write path.
  - [x] LLM-guided add now forwards normalized `text`/`store_mode` into `_execute_flowchart_memory_node_deterministic` for unchanged persistence semantics.
- [x] Emit runtime trace/evidence metadata for inferred add decisions.
  - [x] LLM-guided add output now includes `llm_guided_add` metadata (provider/model/inference payload/raw output excerpt) and appends an inference action result note.
  - [x] Added Stage 5 unit coverage in `app/llmctl-studio-backend/tests/test_memory_node_llm_guided_add_stage5.py`.

## Stage 6 - Execution: LLM-Guided Retrieve

- [x] Implement LLM inference for memory `retrieve` using input context + additive prompt guidance.
  - [x] Implemented llm-guided retrieve runtime in `app/llmctl-studio-backend/src/services/tasks.py` via `_execute_flowchart_memory_node_llm_guided_retrieve`.
  - [x] Inference prompt now includes memory action template, additive prompt, inferred upstream prompt, effective prompt guidance, retrieval limit baseline, and flowchart input context.
  - [x] Inference now uses prompt-envelope flow (`_build_task_payload`) and runtime dispatch (`_run_llm` + `_llm_dispatch_scope`).
- [x] Validate and normalize inferred retrieval query/filter payload.
  - [x] Added strict parsing (`_parse_strict_json_object_output`) and retrieval normalization (`_normalize_memory_llm_guided_retrieve_payload`) with:
    - [x] optional `query_text` (trimmed, empty string preserved),
    - [x] optional positive `memory_id`,
    - [x] `limit` normalization with clamp to `1..50`,
    - [x] advisory `confidence` normalization to `0..1` when parseable.
- [x] Resolve inferred retrieval to concrete DB query behavior and enforce limits.
  - [x] Added precedence resolution:
    - [x] explicit `node_ref_id` first,
    - [x] then inferred `memory_id`,
    - [x] else query-based retrieval.
  - [x] LLM-guided retrieve now executes deterministic retrieval with normalized `limit`/`query`.
  - [x] Empty inferred `query_text` now maps to unfiltered query path (no prompt-derived filter fallback).
- [x] Emit runtime trace/evidence metadata and downstream-compatible retrieved payload.
  - [x] LLM-guided retrieve output now includes `llm_guided_retrieve` metadata (provider/model/inference payload/resolution/raw output excerpt).
  - [x] Added Stage 6 unit coverage in `app/llmctl-studio-backend/tests/test_memory_node_llm_guided_retrieve_stage6.py`.

## Stage 7 - Execution: Failure Semantics + Degraded Markers

- [x] Implement mode-aware failure and degraded marker behavior from Stage 0/2 decisions.
  - [x] Added memory-mode retry + fallback orchestration in `app/llmctl-studio-backend/src/services/tasks.py` (`_execute_flowchart_memory_node`).
  - [x] Primary mode now attempts `1 + retry_count` before fallback decisioning.
  - [x] Fallback executes at most once in opposite mode and never chains to a second hop.
- [x] Apply agreed fallback policy for `llm_guided` mode.
  - [x] Added canonical failure-reason classification (`primary_runtime_error`, `primary_empty_result`, `primary_invalid_result`, `llm_inference_error`, `llm_validation_error`) and fallback decisioning helpers.
  - [x] `llm_guided` primary failures now fallback to deterministic only when `fallback_enabled=true`.
- [x] Ensure deterministic primary execution behavior remains unchanged before fallback decisioning.
  - [x] Deterministic execution remains in `_execute_flowchart_memory_node_deterministic`; Stage 7 wraps it with retry/fallback orchestration without altering core deterministic write/retrieve logic.
- [x] Surface consistent `execution_status`/`fallback_used`/`fallback_reason` semantics in output and artifacts.
  - [x] Fallback success now sets:
    - [x] `execution_status=success_with_warning`
    - [x] `fallback_used=true`
    - [x] `failed_mode=<primary mode>`
    - [x] `fallback_reason=<classified reason>`
  - [x] Routing state now mirrors fallback markers for downstream tracing.
  - [x] Added Stage 7 unit coverage in `app/llmctl-studio-backend/tests/test_memory_node_failure_semantics_stage7.py`.

## Stage 8 - Automated Testing

- [x] Add/extend tests for mode selector normalization and API/inspector contract behavior.
- [x] Add migration tests for existing-node backfill to `llm_guided` and fail-fast behavior.
- [x] Add runtime tests for deterministic parity and llm-guided add/retrieve paths.
- [x] Add tests for agreed per-mode failure/degraded behavior.
- [x] Run targeted backend/frontend suites and record evidence.
  - [x] Backend targeted suite passed:
    - `~/.codex/skills/llmctl-studio-test-postgres/scripts/run_backend_tests_with_postgres.sh --repo-root /home/nodadyoushutup/llmctl -- .venv/bin/python3 -m unittest -q app/llmctl-studio-backend/tests/test_flowchart_stage9.py app/llmctl-studio-backend/tests/test_memory_node_mode_migration_stage3.py app/llmctl-studio-backend/tests/test_memory_node_mode_dispatch_stage4.py app/llmctl-studio-backend/tests/test_memory_node_llm_guided_add_stage5.py app/llmctl-studio-backend/tests/test_memory_node_llm_guided_retrieve_stage6.py app/llmctl-studio-backend/tests/test_memory_node_failure_semantics_stage7.py`
    - Result: `Ran 135 tests in 118.034s` / `OK`.
  - [x] Frontend targeted suite passed:
    - `npm --prefix app/llmctl-studio-frontend run test -- src/components/FlowchartWorkspaceEditor.test.jsx`
    - Result: `1 passed file`, `30 passed tests`.

## Stage 9 - Docs Updates

- [x] Update Sphinx/RTD docs for memory-node `mode` semantics, defaults, and migration behavior.
  - [x] Updated `docs/sphinx/specialized_flowchart_nodes.rst` with:
    - [x] memory inspector contract (`mode`, `retry_count`, `fallback_enabled`)
    - [x] graph-save normalization/validation semantics
    - [x] startup migration backfill + fail-fast behavior
    - [x] runtime retry/fallback/degraded semantics
    - [x] llm-guided add/retrieve contract schemas
    - [x] memory artifact payload additions (`execution_status`, fallback markers, llm-guided metadata)
- [x] Update flowchart node configuration guide and inspector documentation.
  - [x] Added Stage 9 changelog entry in `docs/sphinx/changelog.rst`.
- [x] Update planning artifact with final decisions, test evidence, and rollout notes.
  - [x] Rollout note: no rollout/cutover switch is introduced; defaults are enforced directly (`llm_guided`, retry `1`, fallback enabled).
  - [x] Rollout note: migration remains startup-authoritative and fail-fast on malformed memory-node config rows.
  - [x] Validation note: Stage 8 targeted backend/frontend suites passed prior to Stage 9 closeout.
