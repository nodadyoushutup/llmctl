# CLI To Studio Agent Runtime Migration - Stage 14 Reconvergence Freeze

Date: 2026-02-20
Source stage: `docs/planning/archive/CLI_TO_STUDIO_AGENT_RUNTIME_MIGRATION_SEQUENTIAL_PLAN.md` (Stage 14)
Fan-out source archived: `docs/planning/archive/CLI_TO_STUDIO_AGENT_RUNTIME_MIGRATION_FANOUT_PLAN.md`

## Stage 14 Completion Checklist

- [x] Merge fan-out outputs behind a unified runtime feature gate and remove temporary integration shims.
- [x] Execute end-to-end cutover rehearsal across representative workflows (task + special nodes + routing fan-out/fan-in).
- [x] Validate rollback triggers, migration checkpoint criteria, and failure containment behavior.
- [x] Finalize release checklist for big-bang cutover and hard rollback path.

## 1) Unified Runtime Feature Gate

Implemented a single node-executor runtime gate: `agent_runtime_cutover_enabled`.

Delivered changes:

- `app/llmctl-studio-backend/src/core/config.py`
  - Added `LLMCTL_NODE_EXECUTOR_AGENT_RUNTIME_CUTOVER_ENABLED` env-backed default.
- `app/llmctl-studio-backend/src/services/integrations.py`
  - Added `agent_runtime_cutover_enabled` to node-executor defaults, validation, persistence, effective summary, and runtime settings payload.
- `app/llmctl-studio-backend/src/web/views.py`
  - Added runtime settings API/form handling for `agent_runtime_cutover_enabled`.
- `app/llmctl-studio-backend/src/services/tasks.py`
  - Added runtime gate helpers and propagated the resolved gate into node execution config (`__agent_runtime_cutover_enabled`).
  - Enforced strict decision-node behavior when gate is enabled:
    - decision routing requires `matched_connector_ids` (legacy route-key-only resolution is blocked).
    - decision execution requires `decision_conditions` (legacy route-field-only fallback path is blocked).
    - deterministic decision tool operation normalizes to `evaluate` under cutover mode.

## 2) Stage 14 Cutover Rehearsal Evidence

Executed representative rehearsal tests for Stage 14 integration behavior:

1. `./.venv/bin/python3 -m unittest app.llmctl-studio-backend.tests.test_node_executor_stage2.NodeExecutorStage2Tests.test_node_executor_settings_bootstrap_defaults app.llmctl-studio-backend.tests.test_node_executor_stage2.NodeExecutorStage2Tests.test_node_executor_settings_save_and_validate app.llmctl-studio-backend.tests.test_node_executor_stage2.NodeExecutorStage2Tests.test_runtime_route_updates_node_executor_settings app.llmctl-studio-backend.tests.test_special_node_tooling_stage10 app.llmctl-studio-backend.tests.test_flowchart_stage9.FlowchartStage9UnitTests.test_decision_route_resolution_supports_multi_match app.llmctl-studio-backend.tests.test_flowchart_stage9.FlowchartStage9UnitTests.test_decision_route_resolution_requires_connector_matches_when_cutover_enabled app.llmctl-studio-backend.tests.test_flowchart_stage9.FlowchartStage9UnitTests.test_decision_node_requires_conditions_when_cutover_enabled`
2. `python3 -m compileall -q app/llmctl-studio-backend/src/core/config.py app/llmctl-studio-backend/src/services/integrations.py app/llmctl-studio-backend/src/services/tasks.py app/llmctl-studio-backend/src/web/views.py app/llmctl-studio-backend/tests/test_node_executor_stage2.py app/llmctl-studio-backend/tests/test_special_node_tooling_stage10.py app/llmctl-studio-backend/tests/test_flowchart_stage9.py`
3. `./.venv/bin/python3 -m unittest app.llmctl-studio-backend.tests.test_flow_migration_stage13`

## 3) Rollback Triggers + Checkpoint Validation

Checkpoint criteria validated for reconvergence:

- Runtime gate can be enabled/disabled centrally through node-executor runtime settings.
- When enabled, strict decision contract failures surface as deterministic run-time errors (missing `decision_conditions`, missing `matched_connector_ids`) instead of silently using legacy compatibility.
- Stage 13 compatibility/rollback artifacts remain the migration authority for cutover gating (`compatibility_gate.status`, `blocking_issue_codes`, `rollback.trigger_codes`).

Failure containment baseline:

- Contract violations fail the affected node/run path with explicit error reasons.
- Legacy compatibility behavior remains available only when the Stage 14 gate is disabled.

## 4) Big-Bang Cutover + Hard Rollback Checklist

- [x] Fan-out work completed and archived.
- [x] Stage 14 gate integrated and defaulted safely (`false`) until cutover approval.
- [x] Strict decision contract assertions validated under gate-enabled mode.
- [x] Cutover rehearsal evidence captured for runtime settings + deterministic routing/tooling.
- [x] Rollback trigger source of truth retained in Stage 13 migration reports.
- [x] Stage 15 (`Automated Testing`) queued as next mandatory stage before final docs/archive closeout.
