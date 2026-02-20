# CLI To Studio Agent Runtime Migration - Stage 15 Automated Testing Freeze

Date: 2026-02-20
Source stage: `docs/planning/archive/CLI_TO_STUDIO_AGENT_RUNTIME_MIGRATION_SEQUENTIAL_PLAN.md` (Stage 15)

## Stage 15 Completion Checklist

- [x] Run backend contract/integration test suites for API, socket events, routing determinism, and special-node tooling.
- [x] Run frontend unit/integration tests for model management and routing inspector behavior.
- [x] Run end-to-end migration and execution regression tests, including degraded/fallback scenarios.
- [x] Record automated test evidence and unresolved failures for cutover sign-off.

## 1) Backend Contract/Integration Test Evidence

Passing targeted backend contract/integration suite:

1. `./.venv/bin/python3 -m pytest -q app/llmctl-studio-backend/tests/test_react_stage7_api_routes.py app/llmctl-studio-backend/tests/test_react_stage8_api_routes.py app/llmctl-studio-backend/tests/test_realtime_events_stage6.py app/llmctl-studio-backend/tests/test_special_node_tooling_stage10.py app/llmctl-studio-backend/tests/test_flowchart_stage9.py::FlowchartStage9UnitTests::test_decision_route_resolution_supports_multi_match app/llmctl-studio-backend/tests/test_flowchart_stage9.py::FlowchartStage9UnitTests::test_decision_route_resolution_requires_connector_matches_when_cutover_enabled`
   - Result: `29 passed in 22.25s`

Failure-inventory run for Stage 9 coverage gap visibility:

1. `./.venv/bin/python3 -m pytest -q app/llmctl-studio-backend/tests/test_flowchart_stage9.py`
   - Result: `32 failed, 61 passed in 106.55s`
   - Failures are captured in Section 4 as unresolved sign-off blockers.

## 2) Frontend Unit/Integration Test Evidence

Executed targeted frontend suites for model management and routing inspector behavior:

1. `npm test -- src/pages/ModelsPage.test.jsx src/components/FlowchartWorkspaceEditor.test.jsx`
   - Result: `2 passed`, `27 passed`

## 3) End-to-End Migration + Execution Regression Evidence

Executed migration/execution regression suites with deterministic fallback coverage:

1. `./.venv/bin/python3 -m unittest app/llmctl-studio-backend/tests/test_flow_migration_stage13.py app/llmctl-studio-backend/tests/test_node_executor_stage2.py app/llmctl-studio-backend/tests/test_node_executor_stage4.py app/llmctl-studio-backend/tests/test_node_executor_stage6.py app/llmctl-studio-backend/tests/test_node_executor_stage8.py app/llmctl-studio-backend/tests/test_deterministic_tooling_stage6.py app/llmctl-studio-backend/tests/test_flowchart_stage12.py`
   - Result: `Ran 51 tests in 18.092s`, `OK`

## 4) Unresolved Failures For Cutover Sign-Off

Stage 9 routing/API suite has unresolved blockers in the current test environment:

- `System-managed LLMCTL MCP server is missing. Sync integrations and retry.` returned on graph-save API paths expected to validate Stage 9 graph contracts.
- Memory-node execution failures requiring system-managed MCP (`Memory nodes require the system-managed LLMCTL MCP server (llmctl-mcp).`) drive multiple run-status regressions to `failed`.
- UI/API history detail path missing template dependency (`TemplateNotFound: flowchart_history_run_detail.html`).
- Routing execution mismatch in node-type behavior test (`Route key 'continue' has no matching solid outgoing edge.`).
- Repeated Redis publish warnings (`Cannot publish to redis...`) indicate missing realtime broker wiring in local test context.

These unresolved failures are explicitly recorded for Stage 16 documentation/runbook follow-up before final cutover approval.
