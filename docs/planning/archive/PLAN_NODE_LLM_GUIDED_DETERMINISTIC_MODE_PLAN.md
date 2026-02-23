# Plan Node LLM-Guided / Deterministic Mode Plan

Goal: add explicit Plan node execution modes (`llm_guided`, `deterministic`) with safe deterministic application semantics, aligned with Memory-node operating patterns.

## Stage 0 - Requirements Gathering

- [x] Confirm canonical config key for Plan execution mode (`mode` vs `execution_mode`).
- [x] Confirm canonical mode values and aliases for Plan execution (`llm_guided`, `deterministic`).
- [x] Confirm default mode for newly created Plan nodes.
- [x] Confirm mode interaction contract with `store_mode` (`append`, `replace`, `update`).
- [x] Confirm strict JSON patch schema expected from `llm_guided` Plan execution.
- [x] Confirm retry and fallback behavior between Plan execution modes.
- [x] Confirm inspector placement and required-field behavior for Plan mode selector.
- [x] Confirm backend graph validation and migration behavior for existing Plan nodes.
- [x] Confirm runtime observability and artifact payload additions for Plan mode execution.
- [x] Confirm Stage 0 completion and approval to start Stage 1.

## Stage 0 - Interview Notes (Captured)

- [x] User requested a planning doc for adding Plan node `llm_guided`/`deterministic` functionality.
- [x] Confirmed canonical Plan execution mode key is `mode` (selected in Stage 0 Q1 on 2026-02-22).
- [x] Confirmed canonical-only Plan mode values: `llm_guided` and `deterministic` (no alias normalization) (selected in Stage 0 Q2 on 2026-02-22).
- [x] Confirmed default Plan mode is `deterministic` for new Plan nodes (selected in Stage 0 Q3 on 2026-02-22).
- [x] Confirmed interaction contract: `mode` selects patch source and `store_mode` selects apply semantics (`append|replace|update`) through shared deterministic applier (selected in Stage 0 Q4 on 2026-02-22).
- [x] Confirmed Plan mode behavior should mirror Memory patterns as closely as possible, including fallback controls and degraded-path semantics where applicable (captured in Stage 0 Q4 on 2026-02-22).
- [x] Confirmed Plan should reuse Memory-style failure controls and behavior (`retry_count`, `fallback_enabled`, primary retries, one fallback hop, degraded markers on fallback success) (selected in Stage 0 Q5 on 2026-02-22).
- [x] Confirmed `llm_guided` output must be strict JSON patch object in canonical Plan patch schema; non-object/invalid output fails the attempt (selected in Stage 0 Q6 on 2026-02-22).
- [x] Confirmed graph-save requires Plan `config.mode`, with startup migration/backfill setting missing legacy Plan-node mode to `deterministic` (selected in Stage 0 Q7 on 2026-02-22).
- [x] Confirmed Plan inspector should mirror Memory layout with required `mode` and Failure controls (`retry_count`, `fallback_enabled`) (selected in Stage 0 Q8 on 2026-02-22).
- [x] Confirmed Plan runtime/artifact observability should mirror Memory degraded/fallback evidence fields while preserving existing Plan observability payloads (`store_mode`, `operation_counts`, `warnings`, `errors`, `touched`) (selected in Stage 0 Q9 on 2026-02-22).

## Stage 1 - Code Planning

- [x] Define frontend, backend sanitizer, runtime, tooling, and artifact boundaries.
- [x] Frontend boundary: `app/llmctl-studio-frontend/src/components/FlowchartWorkspaceEditor.jsx` (+ related tests).
- [x] Backend sanitizer/graph validation boundary: `app/llmctl-studio-backend/src/web/views/shared.py`.
- [x] Runtime execution boundary: `app/llmctl-studio-backend/src/services/tasks.py`.
- [x] Deterministic tooling boundary: `app/llmctl-studio-backend/src/services/execution/tooling.py`.
- [x] Runtime/output contract boundary: `app/llmctl-studio-backend/src/services/runtime_contracts.py`.
- [x] Startup migration boundary: `app/llmctl-studio-backend/src/core/db.py`.
- [x] Freeze canonical Plan config contract (required keys, defaults, aliases, removed keys).
- [x] Required Plan config keys after this initiative:
- [x] `mode`, `store_mode`.
- [x] Canonical `mode` values: `llm_guided | deterministic` (no alias normalization).
- [x] Canonical `store_mode` values remain: `append | replace | update`.
- [x] Default mode for new Plan nodes: `deterministic`.
- [x] Plan Failure controls (mirroring Memory): `retry_count`, `fallback_enabled`.
- [x] Existing Plan patch inputs preserved: `patch`, `patch_source_path`, optional transform prompt controls as applicable.
- [x] Existing retention controls preserved: `retention_mode`, `retention_ttl_seconds`, `retention_max_count`.
- [x] Removed/unsupported for new Plan-mode contract: legacy action-style Plan keys (`action`, `plan_item_id`, `stage_key`, `task_key`, `completion_source_path`).
- [x] Define execution-stage breakdown and acceptance criteria by stage.
- [x] Stage 2: Scope-specific planning freeze for mode semantics, fallback rules, observability, and migration behavior.
- [x] Stage 3: UI/config execution (`mode` selector + failure controls + payload normalization).
- [x] Stage 4: Backend validation/migration execution (required mode, startup backfill, fail-fast malformed configs).
- [x] Stage 5: Runtime/artifact execution (primary mode path + fallback hop + degraded markers + artifact payload updates).
- [x] Stage 6: Automated testing gates across frontend/backend/runtime/tooling.
- [x] Stage 7: Docs updates (Sphinx/RTD + implementation notes).

## Stage 2 - Scope-Specific Planning

- [x] Define deterministic-mode behavior and error handling.
- [x] `mode=deterministic` consumes canonical patch inputs (`patch`, `patch_source_path`, optional existing transform path if configured) and routes through the same deterministic Plan patch applier used by all modes.
- [x] Deterministic-mode malformed/non-object/semantically conflicting patches fail the primary attempt with explicit validation errors.
- [x] Deterministic-mode preserves existing Plan store semantics (`store_mode=append|replace|update`) exactly as currently implemented.
- [x] Define llm-guided prompt/output contract and strict patch validation flow.
- [x] `mode=llm_guided` requires strict JSON object output representing canonical Plan patch schema (no freeform mutation output path).
- [x] LLM output is validated before apply; invalid/non-object output fails the current primary attempt (eligible for retry/fallback policy).
- [x] Valid llm-guided patch payloads are applied only through the shared deterministic Plan patch applier with existing `store_mode` semantics.
- [x] Define retry/fallback/degraded semantics and observability markers.
- [x] Plan mode failure behavior mirrors Memory contract: primary mode retries (`1 + retry_count` attempts), then one optional fallback hop to opposite mode when `fallback_enabled=true`.
- [x] Fallback success marks degraded execution with explicit markers (`execution_status=success_with_warning`, `fallback_used`, `failed_mode`, `fallback_mode`, `fallback_reason`).
- [x] Fallback failure is hard-fail; no second fallback hop.
- [x] Observability payload preserves existing Plan fields (`store_mode`, `operation_counts`, `warnings`, `errors`, `touched`) and adds mode/fallback evidence fields.
- [x] Define migration strategy and idempotency requirements.
- [x] Graph-save contract requires Plan `config.mode`; missing/invalid values are rejected.
- [x] Startup backfill migration sets missing Plan `mode` to `deterministic` for existing rows and remains idempotent across repeated startups.
- [x] Malformed/non-object Plan config payloads fail-fast during startup migration.
- [x] Define test matrix for UI contract, API validation, runtime semantics, and artifacts.
- [x] Frontend tests: Plan inspector emits required `mode`; failure controls rendered/serialized; defaults set to `deterministic`, `retry_count=1`, `fallback_enabled=true` (or canonical defaults if adjusted in execution).
- [x] Backend validation tests: graph-save rejects missing/invalid Plan `mode`; migration backfills mode and fails-fast on malformed configs.
- [x] Runtime tests: deterministic primary success, llm-guided primary success, retry exhaustion + fallback success (degraded), fallback failure hard-fail, strict llm output validation failures, and parity with existing `store_mode` behaviors.
- [x] Artifact/contract tests: mode and degraded/fallback markers included and validated alongside existing Plan artifact/runtime fields.

## Stage 3 - Execution: UI and Config Contract

- [x] Add Plan mode selector in inspector and defaults for new Plan nodes.
- [x] Normalize Plan mode in all frontend graph read/write paths.
- [x] Update frontend tests for Plan mode UI and payload emission.

## Stage 4 - Execution: Backend Validation and Migration

- [x] Add Plan mode sanitization and validation in graph-save/backend config paths.
- [x] Add startup migration/defaulting for existing Plan node configs.
- [x] Ensure migration is deterministic/idempotent and fail-fast on malformed configs.

## Stage 5 - Execution: Runtime and Artifact Semantics

- [x] Implement deterministic-mode path for Plan node execution.
- [x] Implement llm-guided Plan path that produces strict patch payloads only.
- [x] Apply shared deterministic patch applier after llm output validation.
- [x] Add mode-aware retry/fallback/degraded markers and runtime trace fields.
- [x] Update Plan artifact payload contract with mode and mode-specific evidence fields.

## Stage 6 - Automated Testing

- [x] Add/update backend tests for mode validation, migration, runtime semantics, and artifacts.
- [x] Add/update deterministic tooling tests for mode operation mapping and fallback behavior.
- [x] Add/update frontend tests for inspector, defaults, and graph payload normalization.
- [x] Run relevant backend/frontend test suites with `.venv` tooling.

## Stage 7 - Docs Updates

- [x] Update planning and implementation notes with final Plan mode behavior.
- [x] Update Sphinx/RTD docs for Plan node mode semantics, payloads, and operator guidance.
