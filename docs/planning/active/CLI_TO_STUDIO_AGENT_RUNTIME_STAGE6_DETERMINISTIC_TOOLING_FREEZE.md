# CLI To Studio Agent Runtime Migration - Stage 6 Deterministic Tooling Freeze

Date: 2026-02-20
Source stage: `docs/planning/active/CLI_TO_STUDIO_AGENT_RUNTIME_MIGRATION_SEQUENTIAL_PLAN.md` (Stage 6)

## Stage 6 Completion Checklist

- [x] Implement shared internal tool invocation framework with schema validation, idempotency, retry controls, and artifact persistence hooks.
- [x] Implement standard fallback contract (`success_with_warning`, `fallback_used`) when required deterministic tools fail/conflict.
- [x] Implement shared tracing/audit envelope for tool calls, errors, and correlation propagation.
- [x] Deliver cutover-critical base tool scaffolding required before domain fan-out implementation begins.

## 1) Shared Internal Tool Invocation Framework

Implemented module:

- `app/llmctl-studio-backend/src/services/execution/tooling.py`

Delivered components:

- `ToolInvocationConfig` + `ToolInvocationOutcome` contracts for deterministic internal tools.
- `invoke_deterministic_tool(...)` execution wrapper with:
  - schema validation hook (`validate`)
  - artifact persistence hook (`artifact_hook`) for final-state persistence integration points
  - bounded retries (`max_attempts`, `retry_backoff_seconds`)
  - runtime idempotency gate (`idempotency_scope`, `idempotency_key`)
- deterministic scaffolding registry (`DETERMINISTIC_BASE_TOOLS`) for `decision`, `memory`, `milestone`, and `plan`.

Idempotency plumbing:

- `app/llmctl-studio-backend/src/services/execution/idempotency.py`
  - Added generic runtime key registration (`register_runtime_idempotency_key`)
  - Keeps DB-backed key registry (`runtime_idempotency_keys`) with in-memory fallback.

## 2) Standard Fallback Contract

Fallback contract implementation:

- `apply_fallback_contract(...)` in `services/execution/tooling.py`
  - `execution_status = success_with_warning`
  - `fallback_used = true`
  - standardized warning envelope in `warnings[]`

Runtime integration:

- `app/llmctl-studio-backend/src/services/tasks.py`
  - Special nodes (`decision`, `plan`, `milestone`, `memory`) now route through `_execute_deterministic_special_node_with_framework(...)` from `_execute_flowchart_node(...)`.
  - Optional per-node fallback activation via `tool_fallback_enabled`.
  - Fallback payload builder `_build_special_node_tool_fallback_payload(...)` ensures contract-safe output/routing shapes for specialized node types.

## 3) Shared Tracing/Audit Envelope + Correlation Propagation

Trace envelope:

- Attached under `output_state["deterministic_tooling"]`.
- Includes contract version, node/tool metadata, execution status, warnings, request/correlation IDs, idempotency scope/key, and per-attempt call traces (timings + error metadata).

Runtime propagation:

- `tasks.py` now augments runtime metadata with deterministic tooling fields via `_augment_runtime_payload_with_deterministic_tooling(...)`.
- `runtime_contracts.py` degraded marker resolver now recognizes:
  - `deterministic_fallback_used`
  - `deterministic_execution_status == success_with_warning`

This ensures fallback/warning outcomes are reflected in persisted node-run degraded markers and downstream event/runtime evidence paths.

## 4) Cutover-Critical Base Tool Scaffolding

Base scaffolding delivered in `services/execution/tooling.py`:

- Canonical base mappings:
  - `deterministic.decision`
  - `deterministic.memory`
  - `deterministic.milestone`
  - `deterministic.plan`
- Operation normalization + default operation selection with `resolve_base_tool_scaffold(...)`.
- Per-domain artifact hook keys reserved for fan-out-stage domain implementations.

## 5) Automated Evidence

Executed suites:

1. `./.venv/bin/python3 -m pytest app/llmctl-studio-backend/tests/test_deterministic_tooling_stage6.py app/llmctl-studio-backend/tests/test_runtime_contracts_stage3.py`
2. `./.venv/bin/python3 -m pytest app/llmctl-studio-backend/tests/test_flowchart_stage9.py -k "runtime_decision_no_match_without_fallback_fails_run or runtime_decision_no_match_uses_fallback_connector"`
