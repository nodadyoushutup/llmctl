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
- [ ] Confirm Stage 0 completion and approval to begin Stage 1.

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

- [ ] Define implementation boundaries between mode dispatch, deterministic path reuse, LLM-guided inference, persistence, and observability.
- [ ] Freeze memory-node config contract updates (`mode` + defaults + normalization) across backend and frontend.
- [ ] Freeze migration strategy details (schema/defaulting/data backfill behavior and fail-fast semantics).
- [ ] Freeze per-mode failure/degraded semantics and runtime contract expectations.
- [ ] Define Stage 2 through Stage X execution order based on Stage 0 decisions.
- [ ] Ensure final two stages are `Automated Testing` and `Docs Updates`.

## Stage 2 - Scope-Specific Planning

- [ ] Define exact `mode` contract in backend sanitization and frontend inspector payloads.
- [ ] Define deterministic-mode output contract parity with existing behavior.
- [ ] Define LLM-guided `add` inference contract (prompt shape, expected output, validation, normalization).
- [ ] Define LLM-guided `retrieve` inference contract (intent/query/filter schema and bounds).
- [ ] Define per-mode failure behavior matrix and status mapping.
- [ ] Define migration implementation details and acceptance criteria.

## Stage 3 - Execution: Config Contract + Migration

- [ ] Add backend config normalization/validation for memory-node `mode`.
- [ ] Add frontend inspector mode selector with explicit options and defaults.
- [ ] Implement startup/deployment DB migration to set existing memory nodes to `llm_guided`.
- [ ] Add fail-fast migration error behavior for malformed/unmigratable rows.

## Stage 4 - Execution: Runtime Mode Dispatch

- [ ] Add mode-based branching in memory node runtime execution.
- [ ] Keep deterministic branch codepath behavior-equivalent to current implementation.
- [ ] Route `llm_guided` mode to new inference-based execution helpers.
- [ ] Preserve action selector semantics (`add`/`retrieve`) across both modes.

## Stage 5 - Execution: LLM-Guided Add

- [ ] Implement LLM inference for memory `add` using input context + additive prompt guidance.
- [ ] Validate and normalize inferred add payload before persistence.
- [ ] Persist inferred memory text via existing deterministic DB write path.
- [ ] Emit runtime trace/evidence metadata for inferred add decisions.

## Stage 6 - Execution: LLM-Guided Retrieve

- [ ] Implement LLM inference for memory `retrieve` using input context + additive prompt guidance.
- [ ] Validate and normalize inferred retrieval query/filter payload.
- [ ] Resolve inferred retrieval to concrete DB query behavior and enforce limits.
- [ ] Emit runtime trace/evidence metadata and downstream-compatible retrieved payload.

## Stage 7 - Execution: Failure Semantics + Degraded Markers

- [ ] Implement mode-aware failure and degraded marker behavior from Stage 0/2 decisions.
- [ ] Apply agreed fallback policy for `llm_guided` mode.
- [ ] Ensure deterministic mode failure behavior remains unchanged.
- [ ] Surface consistent `execution_status`/`fallback_used`/`fallback_reason` semantics in output and artifacts.

## Stage 8 - Automated Testing

- [ ] Add/extend tests for mode selector normalization and API/inspector contract behavior.
- [ ] Add migration tests for existing-node backfill to `llm_guided` and fail-fast behavior.
- [ ] Add runtime tests for deterministic parity and llm-guided add/retrieve paths.
- [ ] Add tests for agreed per-mode failure/degraded behavior.
- [ ] Run targeted backend/frontend suites and record evidence.

## Stage 9 - Docs Updates

- [ ] Update Sphinx/RTD docs for memory-node `mode` semantics, defaults, and migration behavior.
- [ ] Update flowchart node configuration guide and inspector documentation.
- [ ] Update planning artifact with final decisions, test evidence, and rollout notes.
