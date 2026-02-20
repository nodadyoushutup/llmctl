# CLI To Studio Agent Runtime Migration - Stage 10 Special Node Tooling Freeze

Date: 2026-02-20
Source stage: `docs/planning/active/CLI_TO_STUDIO_AGENT_RUNTIME_MIGRATION_PLAN.md` (Stage 10)

## Stage 10 Completion Checklist

- [x] Implement deterministic tool-first execution handlers for memory, plan, milestone, and decision node classes.
- [x] Implement required domain tool operations and conflict/failure fallback semantics.
- [x] Persist canonical structured outputs and node-type-specific final-state artifacts.
- [x] Add contract and behavior tests for deterministic outputs and degraded/fallback paths.

## Implementation Notes

Delivered runtime updates:

- `app/llmctl-studio-backend/src/services/tasks.py`
  - Added `_resolve_special_node_tool_operation(...)` so Stage 10 decision nodes resolve deterministic tool operations as:
    - `evaluate` when condition-based decision routing is configured.
    - `legacy_route` when using legacy route-key behavior.
  - Added fallback policy support with `_resolve_special_node_tool_fallback_mode(...)`:
    - `disabled` / `strict`
    - `all`
    - `conflict_only`
  - Added `_is_special_node_tool_conflict_error(...)` classification and integrated it into deterministic fallback flow so `conflict_only` only degrades on conflict-like failures.
  - Updated deterministic special-node fallback payloads to include operation-aware action defaults.

Existing Stage 10 artifact persistence remains active through node-type-specific writers in `tasks.py`:

- `_persist_memory_node_artifact(...)`
- `_persist_milestone_node_artifact(...)`
- `_persist_plan_node_artifact(...)`
- `_persist_decision_node_artifact(...)`

## Stage 10 Test Coverage

Added targeted behavior tests:

- `app/llmctl-studio-backend/tests/test_special_node_tooling_stage10.py`
  - Decision operation defaults to `legacy_route` when no decision conditions exist.
  - Decision operation resolves to `evaluate` when decision conditions are configured.
  - Memory node `conflict_only` fallback mode returns `success_with_warning` on conflict errors.
  - Memory node `conflict_only` fallback mode stays strict for non-conflict failures.

## Validation Evidence

Executed commands:

1. `./.venv/bin/python3 -m unittest app/llmctl-studio-backend/tests/test_deterministic_tooling_stage6.py app/llmctl-studio-backend/tests/test_special_node_tooling_stage10.py`
   - Passed (`Ran 9 tests ... OK`).
2. `python3 -m compileall -q app/llmctl-studio-backend/src/services/tasks.py app/llmctl-studio-backend/tests/test_special_node_tooling_stage10.py`
   - Passed.
