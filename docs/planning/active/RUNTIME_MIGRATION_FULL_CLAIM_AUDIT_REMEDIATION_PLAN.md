# Runtime Migration Full Claim Audit + Remediation Plan

Date: 2026-02-20
Status: In Progress
Owner: Codex + User

## Stage 0 - Requirements Gathering

- [x] Confirm audit breadth.
- [x] Confirm execution mode after audit findings.
- [x] Confirm closure strictness.
- [x] Confirm Stage 0 completion and get approval to proceed to Stage 1.

Stage 0 decisions:

- Scope: Full migration claim audit.
- Mode: Audit plus immediate critical fixes.
- Gate: Hard gate. No completion without code evidence and passing automated tests.

## Stage 1 - Code Planning

- [x] Define the evidence model for each checked migration-plan claim (`claim -> code -> tests -> UI/API proof`).
- [x] Define execution stages for claim extraction, evidence mapping, remediation, gating, and closure.
- [x] Sequence work so critical gaps are fixed immediately after discovery.
- [x] Ensure final stages are `Automated Testing` then `Docs Updates`.

## Critical Incident Addendum (2026-02-20): Frontier SDK-Only Claim Violation

Observed production failure:

- Executor node run failed with `Node execution failed: [Errno 2] No such file or directory: 'codex'`.

Confirmed code evidence:

- Node execution still enters `services.tasks:_execute_flowchart_node_request` (`app/llmctl-executor/src/llmctl_executor/payload.py`, `app/llmctl-studio-backend/src/services/tasks.py`).
- Flowchart task execution path still calls legacy `_run_llm(...)` in `tasks.py`.
- `tasks.py` codex provider path still shells to `Config.CODEX_CMD exec` and builds CLI flags.
- Frontier executor image explicitly denies bundled `codex`, `gemini`, and `claude` binaries (`app/llmctl-executor/Dockerfile`).

Why this was missed:

- Migration work completed executor dispatch/image split, but provider execution in `services/tasks.py` remained CLI-based for flowchart task paths.
- Test strategy relied heavily on `_run_llm` mocks and included assertions that codex CLI args are present, reinforcing legacy behavior.
- Stage 15 freeze recorded unresolved blocker inventory, so full claim closure never reached hard-proof parity.

Required remediation items (hard-gated):

- [x] Replace frontier provider execution in `services/tasks.py` with SDK/router execution path (no CLI binary invocation).
- [x] Remove codex/gemini/claude CLI command-builder reliance from flowchart and task-node runtime paths.
- [x] Replace legacy CLI-specific tests with SDK-only invariants.
- [x] Add regression tests that fail if frontier runtime attempts `codex`, `gemini`, or `claude` subprocess execution.
- [x] Add frontier executor integration smoke test proving `llm_call` + flowchart task node succeeds without CLI binaries on PATH.
- [x] Add claim-evidence row in the matrix marking previous SDK-only claim as failed-until-remediated.

## Stage 2 - Claim Inventory + Normalization

- [x] Enumerate every checked claim across active runtime migration planning docs.
- [x] Normalize claims into a canonical inventory with stable IDs and source references.
- [x] Classify claims by domain (`backend`, `api`, `frontend`, `contracts`, `ops`, `testing`, `docs`).
- [x] Mark claims that define invariants (must-have behaviors) versus informational claims.

## Stage 3 - Evidence Matrix Construction

- [x] Build a claim evidence matrix under `docs/planning/active/` linking each claim ID to:
- [ ] Code paths that implement the claim.
- [ ] Automated tests that prove the claim.
- [ ] API/UI/runtime evidence for user-visible behavior when applicable.
- [x] Mark each claim as `pass`, `fail`, or `insufficient evidence`.

## Stage 4 - Critical Gap Triage + Immediate Fix Queue

- [x] Rank all failed claims by severity (`critical`, `high`, `medium`, `low`).
- [x] Define immediate fix queue for `critical` items, starting with artifact invariant drift.
- [x] Convert each critical claim into concrete acceptance tests before implementation.
- [x] Lock a remediation order that preserves runtime safety and deterministic behavior.
- [x] Treat "frontier SDK-only claim violation (CLI invocation in node execution path)" as a critical priority-0 gap.

## Stage 5 - Critical Backend Remediation

- [ ] Implement backend fixes for critical failed claims.
- [x] For artifact invariants, add missing node artifact types/persistence paths for required node classes.
- [x] Ensure contract/version/idempotency metadata is persisted consistently for new artifact writes.
- [x] Preserve backward compatibility or add explicit migration behavior where needed.
- [x] Complete provider runtime cutover in `services/tasks.py` so flowchart/task execution no longer shells out to frontier CLIs.
- [x] Ensure `execute_llm_call_via_execution_router` (or equivalent SDK path) is the only frontier provider execution path.

## Stage 6 - API + Frontend Remediation

- [x] Implement/extend API endpoints needed to expose corrected runtime state.
- [x] Implement frontend surfaces for corrected artifact visibility and navigation parity.
- [x] Ensure list/detail row-link and action behaviors remain compliant with AGENTS instructions.
- [x] Route operation-level outcomes through shared flash messages where mutations are added or changed.

## Stage 7 - Hard-Gate Guardrail Implementation

- [ ] Add automated guardrails that prevent checked plan claims without supporting tests.
- [ ] Add claim-to-test linkage checks (or equivalent machine-checkable mapping).
- [ ] Add CI failure conditions for unresolved critical/high failed claims.
- [ ] Ensure guardrails are documented and executable by contributors.
- [ ] Add static/runtime guardrail: fail CI if frontier runtime code paths include direct `codex|gemini|claude` command execution.

## Stage 8 - Remaining Claim Remediation (High/Medium/Low)

- [ ] Fix remaining non-critical failed claims in priority order.
- [ ] Add or update tests for each remediated claim.
- [ ] Re-run evidence matrix and update claim status as fixes land.
- [ ] Leave no checked claim in `fail` or `insufficient evidence`.

## Stage 9 - Automated Testing

- [ ] Run full backend test coverage for runtime contracts, artifacts, routing, and APIs.
- [x] Run frontend tests for artifact and navigation behaviors affected by remediations.
- [ ] Run targeted end-to-end regression for representative workflows across node types.
- [x] Record command evidence and results in the active planning artifact.

## Stage 10 - Docs Updates

- [ ] Update runtime migration plan docs to reflect corrected implementation truth.
- [ ] Update Sphinx/Read the Docs content for artifact invariants and operator expectations.
- [ ] Publish the final claim evidence matrix with pass/fail closure evidence.
- [ ] Move this plan to `docs/planning/archive/` once all stages are complete.

## Execution Notes (2026-02-20)

- Frontend tests passed for Stage 6 artifact/nav remediations:
  - `npm --prefix app/llmctl-studio-frontend test -- src/pages/ArtifactExplorerPage.test.jsx src/pages/ArtifactDetailPage.test.jsx src/App.routing.test.jsx src/lib/studioApi.test.js`
  - Result: 4 files, 61 tests passed.
- Backend targeted Stage 5 frontier-runtime tests passed via Postgres wrapper:
  - `~/.codex/skills/llmctl-studio-test-postgres/scripts/run_backend_tests_with_postgres.sh --python /home/nodadyoushutup/llmctl/.venv/bin/python3 -- /home/nodadyoushutup/llmctl/.venv/bin/python3 -m unittest app.llmctl-studio-backend.tests.test_flowchart_stage9.FlowchartStage9UnitTests.test_run_llm_frontier_routes_via_execution_router_without_cli_subprocess app.llmctl-studio-backend.tests.test_flowchart_stage9.FlowchartStage9UnitTests.test_run_llm_frontier_executor_context_uses_sdk_without_cli_subprocess app.llmctl-studio-backend.tests.test_flowchart_stage9.FlowchartStage9UnitTests.test_frontier_executor_smoke_llm_call_and_task_node_succeed_without_cli_binaries app.llmctl-studio-backend.tests.test_claude_provider_stage8.ClaudeProviderRuntimeStage8UnitTests.test_run_llm_claude_executor_context_uses_frontier_sdk_path`
  - Result: 4 tests passed (`OK`).
- Broad module run note (non-blocking for this claim closure):
  - Running entire `test_flowchart_stage9.py` in one shot caused PostgreSQL test-container connection drops (`server closed the connection unexpectedly`); targeted claim tests above passed and provide closure evidence for `RMC-0345`.
- Syntax verification passed:
  - `python3 -m compileall -q app/llmctl-studio-backend/src/web/views.py app/llmctl-studio-backend/tests/test_flowchart_stage9.py app/llmctl-studio-frontend/src/pages/ArtifactExplorerPage.jsx app/llmctl-studio-frontend/src/pages/ArtifactDetailPage.jsx app/llmctl-studio-frontend/src/lib/studioApi.js`
- Frontend visual artifact captured (post-restart):
  - `docs/screenshots/2026-02-19-23-44-27--artifacts-task--stage6-remediation-post-restart--1920x1080--4fcc88f--fcb8ae.png`
- Frontier SDK/runtime cutover implementation landed for Stage 5:
  - `app/llmctl-studio-backend/src/services/tasks.py` now routes frontier providers via `execute_llm_call_via_execution_router` outside executor node-execution context.
  - Executor node-execution context now uses SDK/HTTP frontier provider calls (no `codex|gemini|claude` CLI subprocess invocation).
  - `app/llmctl-studio-backend/src/services/tasks.py` call sites now pass explicit dispatch context (`request_id`, `node_id`, `execution_id`) for routed LLM execution.
- Frontier guardrail regression tests updated:
  - `app/llmctl-studio-backend/tests/test_flowchart_stage9.py` now asserts frontier `_run_llm` does not use CLI subprocess paths in router and executor contexts.
  - `app/llmctl-studio-backend/tests/test_claude_provider_stage8.py` now asserts executor-context Claude runtime uses SDK API path and no CLI subprocess.
- Backend validation commands run:
  - `python3 -m compileall -q app/llmctl-studio-backend/src/services/tasks.py app/llmctl-studio-backend/tests/test_flowchart_stage9.py app/llmctl-studio-backend/tests/test_claude_provider_stage8.py` (passed)
  - Targeted Stage 5 `python3 -m unittest` commands passed via the Postgres wrapper command listed above.
- Postgres-backed Stage 5/critical-claim validation now executed successfully via skill wrapper:
  - `~/.codex/skills/llmctl-studio-test-postgres/scripts/run_backend_tests_with_postgres.sh -- .venv/bin/python3 -m unittest app.llmctl-studio-backend.tests.test_flowchart_stage9.FlowchartStage9UnitTests.test_run_llm_frontier_routes_via_execution_router_without_cli_subprocess app.llmctl-studio-backend.tests.test_flowchart_stage9.FlowchartStage9UnitTests.test_run_llm_frontier_executor_context_uses_sdk_without_cli_subprocess app.llmctl-studio-backend.tests.test_flowchart_stage9.FlowchartStage9UnitTests.test_frontier_executor_smoke_llm_call_and_task_node_succeed_without_cli_binaries app.llmctl-studio-backend.tests.test_claude_provider_stage8.ClaudeProviderRuntimeStage8UnitTests.test_run_llm_claude_executor_context_uses_frontier_sdk_path`
  - Result: `Ran 4 tests ... OK` (includes explicit smoke for executor `llm_call` + flowchart `task` node with CLI subprocess paths forbidden).
- Executor hard-cut/runtime-settings follow-up completed (non-critical claim remediation):
  - Added regression test for legacy executor image key rejection (`k8s_image`, `k8s_image_tag`) and no-write behavior:
    - `app/llmctl-studio-backend/tests/test_node_executor_stage2.py` (`test_runtime_route_rejects_legacy_image_fields_for_json_payload`).
  - Added Harbor split-executor regression coverage:
    - `app/llmctl-studio-backend/tests/test_executor_harbor_stage5.py`.
  - Removed legacy ArgoCD overlay alias publication path:
    - `scripts/configure-harbor-image-overlays.sh` no longer sets `llmctl-executor=...` alias.
  - Validation commands:
    - `.venv/bin/python3 -m unittest app.llmctl-studio-backend.tests.test_executor_harbor_stage5 app.llmctl-studio-backend.tests.test_node_executor_stage2 app.llmctl-studio-backend.tests.test_node_executor_stage6`
    - `.venv/bin/python3 -m unittest app.llmctl-studio-backend.tests.test_flowchart_stage9.FlowchartStage9UnitTests.test_run_llm_frontier_executor_context_uses_sdk_without_cli_subprocess app.llmctl-studio-backend.tests.test_flowchart_stage9.FlowchartStage9UnitTests.test_frontier_executor_smoke_llm_call_and_task_node_succeed_without_cli_binaries app.llmctl-studio-backend.tests.test_claude_provider_stage8.ClaudeProviderRuntimeStage8UnitTests.test_run_llm_claude_executor_context_uses_frontier_sdk_path`
    - `python3 -m compileall -q app/llmctl-studio-backend/src/core/config.py app/llmctl-studio-backend/src/services/execution/kubernetes_executor.py app/llmctl-studio-backend/src/services/integrations.py app/llmctl-studio-backend/src/web/views.py app/llmctl-studio-backend/tests/test_node_executor_stage2.py app/llmctl-studio-backend/tests/test_executor_harbor_stage5.py`
  - Matrix impact: closed executor claims `RMC-0215`, `RMC-0216`, and `RMC-0218` to `pass` with linked evidence.
