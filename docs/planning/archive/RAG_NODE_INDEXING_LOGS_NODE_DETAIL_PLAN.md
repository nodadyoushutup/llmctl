# RAG Node Indexing Logs In Node Detail Plan

Goal: restore and harden RAG indexing visibility in Node Detail so `Quick RAG` and `RAG` indexing runs show meaningful stage labels and logs, while query-mode RAG keeps the existing `LLM Query` experience.

## Stage 0 - Requirements Gathering

- [x] Run Stage 0 interview one question per turn with explicit options.
- [x] Confirm node-type scope for indexing logs in Node Detail.
- [x] Confirm stage-label behavior for indexing vs query mode.
- [x] Confirm trigger source for label switching (`execution_mode` driven).
- [x] Confirm log scope (current run only).
- [x] Confirm empty-state behavior when logs have not arrived.
- [x] Confirm fallback behavior when execution mode is missing.
- [x] Confirm live and historical coverage.
- [x] Confirm backend contract hardening requirement for API and socket payloads.
- [x] Confirm raw-log presentation (no structured grouping in this pass).
- [x] Confirm Stage 0 completion and proceed to Stage 1.

## Stage 0 - Interview Notes

- [x] Scope: apply to `Quick RAG` and `RAG` only.
- [x] `LLM Query` remains for query-mode RAG behavior.
- [x] Replace `LLM Query` label with `RAG Indexing` or `RAG Delta Indexing` for indexing modes.
- [x] Label switching is triggered only when execution mode is explicitly indexing/delta-indexing.
- [x] Log scope is current run only.
- [x] Empty state for indexing stages should render a waiting message.
- [x] Missing/unknown mode falls back to current `LLM Query` behavior.
- [x] Behavior must apply to both live and historical Node Detail views.
- [x] Backend API + socket contracts should explicitly and stably expose execution mode.
- [x] Show raw indexing log stream only in this pass.

## Stage 1 - Code Planning

- [x] Define Stage 2 through Stage X implementation stages from approved requirements.
- [x] Freeze file-level scope for backend contracts, stage assembly, RAG execution logging, and Node Detail rendering.
- [x] Define acceptance criteria for label switching, log visibility, and fallback behavior.
- [x] Ensure final two stages are `Automated Testing` and `Docs Updates`.

## Stage 1 - Output (Frozen Scope And Acceptance)

- [x] Frozen backend scope:
- [x] `app/llmctl-studio-backend/src/services/tasks.py` for RAG execution-mode propagation and RAG indexing stage log persistence.
- [x] `app/llmctl-studio-backend/src/rag/domain/contracts.py` for indexing log callback plumbing.
- [x] `app/llmctl-studio-backend/src/web/views.py` for Node Detail and node-status API stage-entry labeling plus execution-mode serialization.
- [x] `app/llmctl-studio-backend/src/core/task_stages.py` for stage-label mapping support.
- [x] `app/llmctl-studio-backend/src/services/realtime_events.py` and execution runtime metadata producers for stable socket contract exposure of execution mode.
- [x] Frozen frontend scope:
- [x] `app/llmctl-studio-frontend/src/pages/NodeDetailPage.jsx` for indexing-stage empty-state message behavior.
- [x] Frozen test scope:
- [x] `app/llmctl-studio-backend/tests/test_rag_stage9.py` for RAG mode/log/stage assertions.
- [x] `app/llmctl-studio-backend/tests/test_node_executor_stage8.py` (and related runtime contract tests) for API/socket execution-mode contract checks.
- [x] Frontend Node Detail tests will be added/updated if a suitable test file exists or introduced if missing.
- [x] Acceptance criteria:
- [x] `Quick RAG` and `RAG` indexing runs show `RAG Indexing` or `RAG Delta Indexing` at the `llm_query` stage slot.
- [x] Query-mode RAG continues showing `LLM Query`.
- [x] Indexing labels appear only when explicit execution mode indicates indexing or delta indexing.
- [x] Node Detail stage panel shows raw indexing logs for current run when available.
- [x] Node Detail shows indexing waiting-state text when indexing stage is active but logs are empty.
- [x] Missing/unknown execution mode retains existing `LLM Query` behavior.
- [x] API and socket payloads expose stable execution-mode metadata for relevant runs.

## Stage 2 - Execution Mode Contract Hardening

- [x] Define and implement one canonical execution-mode value set for Node Detail (`query`, `indexing`, `delta_indexing`).
- [x] Populate execution mode for `Quick RAG` and `RAG` task payloads in both `/nodes/<id>` and `/nodes/<id>/status`.
- [x] Ensure socket event envelopes/runtime metadata include execution mode without breaking existing consumers.
- [x] Add/update backend contract tests to lock payload keys and values.

## Stage 3 - RAG Indexing Log Capture Into Task Stage Logs

- [x] Add log callback support in RAG indexing domain contract path so indexing progress lines can be captured by callers.
- [x] Wire RAG indexing execution to collect log lines into `task_stage_logs["llm_query"]` for both `Quick RAG` and flowchart `RAG` node runs.
- [x] Ensure stage progress can represent active indexing before logs arrive (for waiting-state rendering).
- [x] Preserve existing query-mode output behavior and avoid changing non-RAG node logging.

## Stage 4 - Dynamic Stage Label Mapping For Node Detail

- [x] Add stage-label override logic so `llm_query` maps to `RAG Indexing` or `RAG Delta Indexing` only for explicit indexing modes on `Quick RAG` and `RAG` runs.
- [x] Keep stage key ordering and status semantics unchanged.
- [x] Keep fallback label as `LLM Query` when mode is missing/unknown.
- [x] Ensure mapping applies in both initial node-detail payload and status refresh payload.

## Stage 5 - Node Detail Empty-State And UX Wiring

- [x] Update Node Detail stage log empty-state copy for indexing-labeled stages to show a waiting message.
- [x] Keep generic `No logs yet.` behavior for non-indexing stages.
- [x] Verify behavior for both live polling updates and historical completed runs.
- [x] Keep UI performance stable by limiting derived state churn in stage rendering.

## Stage 6 - Automated Testing

- [x] Run backend tests covering RAG indexing mode/log payload propagation and Node Detail stage-entry assembly.
- [x] Run backend tests covering API/socket execution-mode contract fields and regressions for non-RAG tasks.
- [x] Run frontend tests for Node Detail stage-label/empty-state behavior (or add targeted test coverage if missing).
- [x] Record pass/fail outcomes and any follow-up defects directly in this plan.

Stage 6 outcomes:

- [x] Backend targeted suite passed via Postgres wrapper:
  ``~/.codex/skills/llmctl-studio-test-postgres/scripts/run_backend_tests_with_postgres.sh --python /home/nodadyoushutup/llmctl/.venv/bin/python3 -- /home/nodadyoushutup/llmctl/.venv/bin/python3 -m unittest app.llmctl-studio-backend.tests.test_rag_stage9.RagStage9RuntimeTests.test_index_mode_uses_collection_index_runner app.llmctl-studio-backend.tests.test_rag_stage9.RagStage9RuntimeTests.test_index_mode_captures_stage_logs_for_execution_task app.llmctl-studio-backend.tests.test_rag_stage9.RagStage9RuntimeTests.test_quick_rag_run_uses_node_config_model_provider app.llmctl-studio-backend.tests.test_node_executor_stage8 app.llmctl-studio-backend.tests.test_realtime_events_stage6 app.llmctl-studio-backend.tests.test_socket_proxy_gunicorn_stage9``.
- [x] Added frontend coverage file ``app/llmctl-studio-frontend/src/pages/NodeDetailPage.test.jsx`` and verified:
  ``npm run test -- src/pages/NodeDetailPage.test.jsx``.
- [x] Follow-up note: full ``test_rag_stage9`` module contains unrelated runtime fixture failures (kubeconfig/flowchart runtime assumptions) and is outside this change scope; targeted RAG indexing tests for this feature pass.

## Stage 7 - Docs Updates

- [x] Update Sphinx/RTD documentation describing Node Detail stage behavior for RAG query vs indexing runs.
- [x] Document execution-mode contract fields for node APIs and realtime events.
- [x] Update changelog/release notes for restored RAG indexing stage logs in Node Detail.

Stage 7 outcomes:

- [x] Updated ``docs/sphinx/rag_flowchart_node.rst`` with Node Detail stage-label mapping and indexing log visibility behavior.
- [x] Updated ``docs/sphinx/studio_serving_runtime.rst`` with ``execution_mode`` API/realtime contract notes for node detail/status flows.
- [x] Updated ``docs/sphinx/changelog.rst`` with 2026-02-18 entries for restored RAG indexing logs + execution-mode contract exposure.
