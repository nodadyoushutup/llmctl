# Plan Node Store Modes And Functionality Plan

Goal: add explicit Plan write modes (`append`, `replace`, `update`) parallel to Memory store-mode behavior and define end-to-end Plan node functionality so it is as robust and operable as Memory nodes.

## Stage 0 - Requirements Gathering

- [x] Confirm Plan node action model and whether write modes apply only to create/update flows.
- [x] Confirm whether `complete_plan_item` becomes a new `store_mode` value or is removed from Plan node scope.
- [x] Confirm canonical mode values and naming for Plan node write behavior (`replace`, `append`, others if any).
- [x] Confirm default mode for newly created Plan nodes.
- [x] Confirm whether targeted stage/task edits require a third mode (`update`) or a separate action/patch contract.
- [x] Confirm UI placement for Plan mode selector in node inspector.
- [x] Confirm backend API/runtime contract shape for Plan mode and any migration/backfill needs.
- [x] Confirm behavior semantics for append vs replace vs update when a plan already exists.
- [x] Confirm whether append/update should preserve stage/task status and metadata unchanged unless explicitly updated.
- [x] Confirm failure behavior when write-mode output is malformed, partial, or semantically conflicting.
- [x] Confirm whether Plan node execution should include interactive interviewing loop controls.
- [x] Confirm artifact retention expectations for Plan outputs and revision history.
- [x] Confirm observability requirements (trace payloads, artifact fields, status markers).
- [x] Confirm Stage 0 completion and approval to begin Stage 1.

## Stage 0 - Interview Notes (Captured)

- [x] User requested immediate focus on adding Plan `append` mode similar to Memory store behavior.
- [x] User requested starting planning interview now for broader Plan-node functionality.
- [x] Confirmed config contract key is `store_mode` (selected in Stage 0 Q1 on 2026-02-22).
- [x] Confirmed default `store_mode` for new Plan nodes is `append` (selected in Stage 0 Q2 on 2026-02-22).
- [x] Confirmed canonical Plan write modes are `append | replace | update` (selected in Stage 0 Q3 on 2026-02-22).
- [x] Confirmed targeted stage/task edits are modeled as `store_mode=update` (selected in Stage 0 Q3 on 2026-02-22).
- [x] Confirmed hard-cut migration: remove legacy Plan `action` path and use new mode-based contract only (decided on 2026-02-22).
- [x] Confirmed `complete_plan_item` mode is removed from Plan node scope; completion should be handled via `store_mode=update` semantics (selected in Stage 0 Q5 on 2026-02-22).
- [x] Confirmed Plan `store_mode` is a required top-level inspector field, positioned like Memory `store_mode` control (selected in Stage 0 Q6 on 2026-02-22).
- [x] Confirmed hard-cut startup DB migration strategy for existing Plan-node configs:
- [x] map legacy `action` contract to `store_mode`,
- [x] default missing/unknown legacy action values to `store_mode=append`,
- [x] fail fast on malformed non-object config payloads (selected in Stage 0 Q7 on 2026-02-22).
- [x] Confirmed legacy `action=complete_plan_item` maps to `store_mode=update` during migration (selected in Stage 0 Q8 on 2026-02-22).
- [x] Confirmed mode semantics when plan already exists (selected in Stage 0 Q9 on 2026-02-22):
- [x] `append`: add new stages/tasks only; do not mutate existing items.
- [x] `replace`: fully overwrite plan structure from payload.
- [x] `update`: mutate matched existing stages/tasks only; do not implicitly create missing items.
- [x] Confirmed `store_mode=update` target resolution order (selected in Stage 0 Q10 on 2026-02-22):
- [x] match by stable ids first (`stage_id`, `task_id`),
- [x] fallback to normalized keys (`stage_key`, `task_key`) when ids are not provided,
- [x] fail on ambiguous matches.
- [x] Confirmed `store_mode=update` missing-target behavior (selected in Stage 0 Q11 on 2026-02-22):
- [x] skip missing targets, apply valid updates, and emit warning details (no hard failure on missing targets alone).
- [x] Confirmed malformed/semantically conflicting payload behavior (selected in Stage 0 Q12 on 2026-02-22):
- [x] fail fast and reject the whole operation when payload structure/semantics are invalid.
- [x] Confirmed preservation semantics for `append`/`update` (selected in Stage 0 Q13 on 2026-02-22):
- [x] preserve existing stage/task status and metadata by default; mutate only fields explicitly provided by payload.
- [x] Confirmed runtime interaction model (selected in Stage 0 Q14 on 2026-02-22):
- [x] Plan node execution remains single-pass with no built-in interviewing loop controls in this phase.
- [x] Confirmed artifact retention/revision policy (selected in Stage 0 Q15 on 2026-02-22):
- [x] keep existing retention controls (`retention_mode`, TTL, max-count),
- [x] always include selected `store_mode` plus merge/update summary in artifact metadata.
- [x] Confirmed observability payload requirements (selected in Stage 0 Q16 on 2026-02-22):
- [x] include `store_mode`, operation counts (`created`, `updated`, `replaced`, `skipped_missing`),
- [x] include touched identifiers, and warning/error detail list in runtime output and artifact metadata.
- [x] User approved Stage 1 kickoff on 2026-02-22 (`Proceed to Stage 1 Code Planning`).

## Stage 1 - Code Planning

- [x] Define implementation boundaries for frontend inspector config, backend sanitization, runtime execution, and artifact persistence.
- [x] Frontend boundary: `app/llmctl-studio-frontend/src/components/FlowchartWorkspaceEditor.jsx`.
- [x] Remove Plan `action` constants/options and introduce Plan `store_mode` constants/options (`append`, `replace`, `update`).
- [x] Update Plan defaults + normalization paths (`defaultConfigForType`, `normalizeNodeConfig`, node-type change normalization) to emit canonical `store_mode`.
- [x] Replace Plan action-only inspector fields with top-level required Plan `store_mode` selector; keep retention controls and additive prompt.
- [x] Backend config boundary: `app/llmctl-studio-backend/src/web/views/shared.py`.
- [x] Replace Plan action constants/normalization with Plan `store_mode` constants/normalization in `_sanitize_plan_node_config`.
- [x] Update graph validation path in `_validate_flowchart_graph_snapshot` to validate new Plan config contract only.
- [x] Runtime execution boundary: `app/llmctl-studio-backend/src/services/tasks.py`.
- [x] Replace `action`-based Plan runtime branching in `_execute_flowchart_plan_node` with `store_mode`-based branching.
- [x] Replace/retire legacy completion helpers and introduce update matching helpers using id-first then key fallback.
- [x] Runtime contract boundary: `app/llmctl-studio-backend/src/services/runtime_contracts.py`.
- [x] Update Plan special-node and plan-artifact required keys from `action` to `store_mode` and new observability fields.
- [x] Artifact boundary: `app/llmctl-studio-backend/src/services/tasks.py` (`_persist_plan_node_artifact`).
- [x] Include mode + merge summary fields in plan artifact payload while preserving existing retention behavior.
- [x] Deterministic tooling boundary: `app/llmctl-studio-backend/src/services/tasks.py` (`_resolve_special_node_tool_operation`, fallback payload builders).
- [x] Ensure Plan operation/scaffold names are derived from `store_mode` and remove Plan action fallback assumptions.
- [x] Migration boundary: `app/llmctl-studio-backend/src/core/db.py`.
- [x] Add startup migration for Plan-node config hard cut (`action` -> `store_mode`) alongside existing schema migration flow.
- [x] Freeze contract updates for Plan node config schema and defaults.
- [x] Canonical Plan config keys after hard cut:
- [x] `store_mode`, `additive_prompt`, `patch`, `patch_source_path`, `retention_mode`, `retention_ttl_seconds`, `retention_max_count`, optional routing keys.
- [x] Removed legacy Plan config keys from canonical contract:
- [x] `action`, `plan_item_id`, `stage_key`, `task_key`, `completion_source_path`.
- [x] Canonical `store_mode` values: `append | replace | update`.
- [x] Default `store_mode` for new Plan nodes: `append`.
- [x] Freeze migration/defaulting strategy for existing Plan nodes (if needed).
- [x] Startup migration scope: all `flowchart_nodes` where `node_type='plan'`.
- [x] Mapping policy:
- [x] legacy `action=complete_plan_item` -> `store_mode=update`.
- [x] legacy `action=create_or_update_plan` -> `store_mode=append`.
- [x] missing/unknown legacy action -> `store_mode=append`.
- [x] malformed/non-object config -> fail-fast migration error and abort startup transaction.
- [x] Migration idempotent on repeated startup runs.
- [x] Define execution-stage sequence for implementation.
- [x] Stage 2: Scope-Specific Planning freeze (mode semantics, merge rules, validation, observability).
- [x] Stage 3: Execution - Frontend Plan `store_mode` contract and inspector updates.
- [x] Stage 4: Execution - Backend Plan config sanitization and DB migration hard cut.
- [x] Stage 5: Execution - Plan runtime mode semantics + artifact/runtime contract updates.
- [x] Stage 6: Automated Testing.
- [x] Stage 7: Docs Updates.
- [x] Ensure final two stages are `Automated Testing` and `Docs Updates`.
- [x] Confirmed Stage 6 and Stage 7 are reserved as required final stages.

## Stage 2 - Scope-Specific Planning

- [x] Finalize Plan node write-mode contract (`append`/`replace`/`update`) across UI, API, and runtime.
- [x] Flowchart graph API save contract for Plan nodes requires `config.store_mode`; legacy `config.action` is rejected after hard cut.
- [x] Plan runtime output and artifact payload use `store_mode` as canonical operation identifier.
- [x] Define deterministic append/replace/update merge rules for plan titles, stages, tasks, and status fields.
- [x] `append` semantics: add-only for stages/tasks; no edits to existing entities.
- [x] `replace` semantics: full plan structure overwrite from provided patch payload.
- [x] `update` semantics: mutate matched existing entities only; no implicit creates.
- [x] `update` matching order: id-first (`stage_id`, `task_id`), then normalized key fallback (`stage_key`, `task_key`), ambiguity fails.
- [x] `update` missing targets are skipped with warning accounting (`skipped_missing`) and warning entries.
- [x] Completion behavior is part of `update` (for example explicit `completed`/`completed_at` field mutation), not a standalone mode.
- [x] Unspecified status/metadata fields remain unchanged in `append` and `update`.
- [x] Define validation, error envelope, and fail-fast semantics for invalid write-mode payloads.
- [x] Malformed/non-object/semantically conflicting write payloads hard-fail and reject operation.
- [x] Ambiguous update target matches hard-fail operation.
- [x] Missing-target-only conditions do not hard-fail; they produce warnings and `skipped_missing` counts.
- [x] Define persistence and artifact metadata expectations for plan revisions.
- [x] Keep existing retention behavior (`retention_mode`, TTL, max count).
- [x] Persist plan artifact metadata with:
- [x] `store_mode`,
- [x] operation counts (`created`, `updated`, `replaced`, `skipped_missing`),
- [x] touched stage/task identifiers,
- [x] warning and error detail lists,
- [x] resulting serialized plan snapshot.
- [x] Define test matrix for mode defaults, contract validation, and runtime outcomes.
- [x] Frontend tests: Plan defaults include `store_mode=append`, normalization canonicalizes mode values, inspector emits required mode.
- [x] Backend graph validation tests: Plan node requires valid `config.store_mode`; legacy action-only configs rejected.
- [x] DB migration tests: Plan action->store_mode mapping, malformed config fail-fast, idempotency.
- [x] Runtime tests:
- [x] `append` add-only behavior,
- [x] `replace` overwrite behavior,
- [x] `update` id-first and key fallback matching,
- [x] ambiguous match failure,
- [x] missing-target warnings and counts,
- [x] malformed payload hard-failure.
- [x] Contract and artifact tests: runtime contract validation and plan artifact payload contain new `store_mode` + observability fields.

## Stage 3 - Execution: Config Contract + UI

- [x] Remove Plan `action` selector/constants and introduce Plan `store_mode` selector/constants (`append`, `replace`, `update`).
- [x] Set Plan default config to `store_mode=append` and remove legacy completion-only config keys from Plan defaults.
- [x] Implement frontend Plan `store_mode` normalization in all graph normalization/save paths.
- [x] Keep Plan `store_mode` as required top-level inspector control aligned with Memory store-mode layout.

## Stage 4 - Execution: Backend Contract + Migration

- [x] Replace Plan backend config sanitizer from `action` to `store_mode` contract and reject legacy action-only payloads.
- [x] Add startup migration in `_ensure_schema()` to hard-cut legacy Plan configs (`action` -> `store_mode` mapping).
- [x] Implement fail-fast migration behavior for malformed Plan config JSON payloads.
- [x] Keep migration idempotent and deterministic.

## Stage 5 - Execution: Runtime + Artifact + Trace

- [x] Implement `store_mode` runtime branching in `_execute_flowchart_plan_node` for `append`, `replace`, and `update`.
- [x] Implement update matcher helpers (id-first, key fallback, ambiguity fail, missing-target warnings).
- [x] Implement malformed/conflict payload hard-fail behavior for all modes.
- [x] Update plan output contract payloads (`store_mode`, operation counts, touched ids, warnings/errors).
- [x] Update deterministic tooling/fallback operation mapping to align with `store_mode`.
- [x] Update plan artifact payload fields with required mode/merge summary observability metadata.

## Stage 6 - Automated Testing

- [x] Add/update backend tests for Plan `store_mode` sanitizer/validation, migration mapping/fail-fast behavior, runtime mode semantics, and artifact/contract payloads.
- [x] Add/update deterministic tooling tests for Plan operation resolution under `store_mode`.
- [x] Add/update frontend tests for Plan inspector control, defaults, and graph payload normalization.
- [x] Run relevant backend and frontend suites with `.venv` tooling.

## Stage 7 - Docs Updates

- [x] Update planning docs and implementation notes with final Plan node behavior.
- [x] Update Sphinx / Read the Docs documentation for Plan node mode semantics.
