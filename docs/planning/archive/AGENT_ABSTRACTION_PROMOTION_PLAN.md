# Agent Abstraction Promotion Plan

Date: 2026-02-20
Status: Complete
Owner: Codex + User
Audit Mode: Disabled for this plan (explicitly requested)

## Stage 0 - Requirements Gathering

- [x] Confirm objective: promote experiment agent abstraction into production runtime paths.
- [x] Confirm scope includes Studio backend, executor runtime paths, and cleanup of `experiment/` artifacts.
- [x] Confirm audit/inventory workflow is not required for this plan.
- [x] Confirm target ownership split for shared runtime abstraction location (`studio-backend only` vs `shared across backend+executor`).
- [x] Confirm desired `experiment/` end-state (`delete`, `archive minimal docs`, or `retain with explicit deprecated marker`).
- [x] Confirm Stage 0 completion and approval to proceed to Stage 1 execution.

Stage 0 decision notes:

- Ownership model selected: `studio-backend only` (backend modules remain the runtime source executed both in backend service context and inside executor pod entrypoint context).
- `experiment/` end-state selected: `delete experiment runtime code` after production abstraction promotion and test validation.

## Stage 1 - Code Planning

- [x] Define production module layout for typed runtime abstractions (`Agent`, `AgentInfo`, request/response/contracts).
- [x] Define compatibility boundary with existing prompt envelope (`agent_profile`, `system_contract`) and persistence fields.
- [x] Define import boundaries to avoid circular dependencies across `services/tasks.py`, executor payload/runtime code, and chat/runtime entry points.
- [x] Define migration sequence to keep runtime behavior stable while replacing dict-first paths with typed classes.

## Stage 2 - Runtime Abstraction Implementation

- [x] Add production Python classes for agent runtime abstraction (ported/adapted from `experiment/agent.py`, SDK-only behavior).
- [x] Add typed `AgentInfo` representation and serialization helpers for envelope/runtime payload usage.
- [x] Integrate abstraction into frontier SDK execution path in `services/tasks.py` and related runtime entry points.
- [x] Wire abstraction through executor node-execution request handling where agent metadata is assembled/consumed.
- [x] Remove duplicated inline agent payload shaping logic superseded by the new abstraction.

## Stage 3 - Integration Hardening

- [x] Update existing code paths that currently rely on ad-hoc dict payloads to use shared abstraction adapters.
- [x] Keep external API/prompt envelope contracts stable unless explicitly changed and documented.
- [x] Ensure no legacy CLI runtime fallback is introduced during integration.
- [x] Add guardrails/tests to prevent regression to dict-only unmanaged agent metadata assembly in runtime-critical paths.

## Stage 4 - Experiment Cleanup

- [x] Remove or archive `experiment/` runtime code after production abstraction is in place per approved Stage 0 policy.
- [x] Remove stale references to experiment-only runtime classes from planning/docs/comments where applicable.
- [x] Ensure repo state reflects `experiment/` as non-authoritative (or removed), with production modules as source of truth.

## Stage 5 - Automated Testing

- [x] Run backend unit tests covering tasks/runtime/executor paths touched by abstraction migration.
- [x] Run targeted regression tests for frontier provider SDK execution and agent-profile propagation.
- [x] Run any executor/runtime smoke tests needed to prove end-to-end typed abstraction usage.

## Stage 6 - Docs Updates

- [x] Update runtime documentation to reference production abstraction modules and remove experiment-first guidance.
- [x] Update planning notes/status for completed stages and final outcomes.
- [x] Move this plan to `docs/planning/archive/` when all stages complete.

Execution notes:

- Added `app/llmctl-studio-backend/src/services/agent_runtime.py` with typed `AgentInfo` and `FrontierAgent` SDK runtime abstraction classes.
- Updated runtime callsites to use typed payload shaping in `services/tasks.py` and `web/views.py`.
- Removed experiment runtime implementation files: `experiment/agent.py`, `experiment/run.py`, `experiment/requirements.txt`.
- Validation run:
  - `python3 -m py_compile app/llmctl-studio-backend/src/services/agent_runtime.py app/llmctl-studio-backend/src/services/tasks.py app/llmctl-studio-backend/src/web/views.py`
  - `.venv/bin/python3 -m pytest -q app/llmctl-studio-backend/tests/test_flowchart_stage9.py::FlowchartStage9UnitTests::test_run_llm_frontier_executor_context_uses_sdk_without_cli_subprocess app/llmctl-studio-backend/tests/test_flowchart_stage9.py::FlowchartStage9UnitTests::test_run_frontier_llm_sdk_codex_includes_mcp_tools_in_openai_request app/llmctl-studio-backend/tests/test_flowchart_stage9.py::FlowchartStage9UnitTests::test_run_frontier_llm_sdk_codex_rejects_non_http_mcp_config app/llmctl-studio-backend/tests/test_flowchart_stage9.py::FlowchartStage9UnitTests::test_task_node_uses_selected_agent_from_config app/llmctl-studio-backend/tests/test_claude_provider_stage8.py::ClaudeProviderRuntimeStage8UnitTests::test_run_llm_claude_executor_context_uses_frontier_sdk_path`
  - `.venv/bin/python3 -m pytest -q app/llmctl-studio-backend/tests/test_flowchart_stage9.py::FlowchartStage9UnitTests::test_frontier_executor_smoke_llm_call_and_task_node_succeed_without_cli_binaries`
