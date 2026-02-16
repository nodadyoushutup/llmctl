# RAG Source Quick Runs Plan

**Work checklist instructions**
- Check off each subtask as it is completed.
- Use `- [x]` for done and `- [ ]` for not done.
- Keep this file updated in place during execution.

Goal: allow users to trigger `Index` and `Delta Index` manually from the Sources UI (list + detail) as quick runs, record them in Node Activity with clear quick-run labeling, and keep them out of workflow-only RAG node lists.

## Stage 0: Requirements Gathering

- [x] Stage 0 interview completed interactively.
- [x] Quick actions on Sources list selected: two icon-only actions (`Index`, `Delta Index`).
- [x] Trigger behavior selected: run immediately (no confirm modal).
- [x] Node Activity labeling selected: `Quick RAG • Index` / `Quick RAG • Delta Index` with source context.
- [x] Duplicate behavior selected: block duplicates while active run exists for that source.
- [x] Eligibility selected: show actions on every source row.
- [x] Persistence selected: keep lightweight history/origin in existing Node Activity metadata (no new table).
- [x] Permissions selected: no auth gating for now (open system).
- [x] Placement selected: show actions in both Sources list and Source detail.
- [x] Workflow RAG list behavior selected: never show quick runs there.

## Stage 1: Code Planning

- [x] Confirmed implementation boundaries:
  - Sources UI and source detail live in `app/llmctl-studio/src/web/templates/rag/sources.html` and `app/llmctl-studio/src/web/templates/rag/source_detail.html`.
  - Sources web routes live in `app/llmctl-studio/src/rag/web/views.py`.
  - Source indexing orchestration helpers are in `app/llmctl-studio/src/rag/worker/tasks.py`.
  - Node Activity list/detail rendering is in `app/llmctl-studio/src/web/views.py` and `app/llmctl-studio/src/web/templates/tasks.html`.
  - Workflow RAG list is flowchart-node-driven in `app/llmctl-studio/src/web/views.py` (`list_task_templates`).
- [x] Defined execution stages (Stage 2 through Stage 8).

## Stage 2: Quick-Run Metadata Contract

- [x] Add explicit task kind constants for quick RAG runs in `app/llmctl-studio/src/core/task_kinds.py`.
- [x] Extend `task_kind_label()` for user-facing labels (`Quick RAG • Index`, `Quick RAG • Delta Index`).
- [x] Define prompt-envelope `task_context` metadata for quick runs (origin, source id/name, mode, index job id).
- [x] Keep persistence on existing Node Activity record (`AgentTask`) metadata only; no new DB table.

## Stage 3: Backend Trigger + Status Endpoints

- [x] Add POST endpoints in `app/llmctl-studio/src/rag/web/views.py` for quick `Index` and `Delta Index` per source.
- [x] Trigger `start_source_index_job()` immediately using selected mode.
- [x] Enforce duplicate blocking by source when an active index job already exists.
- [x] Create a Node Activity record (`AgentTask`) for each quick trigger with quick-run metadata.
- [x] Add source-status API endpoint for quick-action button state (active/inactive per source).
- [x] Return lightweight success/error feedback suitable for toast/flash rendering.

## Stage 4: Sources UI Actions (List + Detail)

- [x] Update `app/llmctl-studio/src/web/templates/rag/sources.html` to add icon-only `Index` and `Delta Index` actions per row.
- [x] Update `app/llmctl-studio/src/web/templates/rag/source_detail.html` to add the same quick actions in detail view.
- [x] Keep row-link behavior compliant (`table-row-link` + `data-href`, ignore interactive targets).
- [x] Disable quick-action buttons when the source already has an active index job.

## Stage 5: Frontend Quick-Run UX + Polling

- [x] Extend `app/llmctl-studio/src/web/static/rag/app.js` to handle quick-action submissions and toasts/flash updates.
- [x] Poll quick-action source status for visible sources and update button disabled state dynamically.
- [x] Prevent duplicate in-flight clicks client-side while request is pending.
- [x] Keep compatibility with existing row-click interactive exclusion selector.

## Stage 6: Node Activity + Workflow List Semantics

- [x] Update Node Activity name/type mapping in `app/llmctl-studio/src/web/views.py` so quick RAG records render with the selected label format and source context.
- [x] Ensure quick RAG records remain independent of flowchart node ids.
- [x] Verify workflow node list (`/task-templates`) remains flowchart-only and excludes quick runs.
- [x] Ensure Node Activity detail view surfaces quick-run metadata clearly from existing record data.

## Stage 7: Automated Testing

- [x] Add/extend route tests for quick trigger success, duplicate-blocked behavior, and source-not-found handling.
- [x] Add template/static tests verifying quick actions appear on Sources list + detail and remain icon-only row-safe controls.
- [x] Add Node Activity rendering tests for quick RAG labels and workflow-list exclusion.
- [x] Run targeted tests with `python3 -m pytest ...` for touched modules.
  - Completed locally: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python3 -m pytest app/llmctl-studio/tests/rag/test_web_sources.py` (5 passed).
  - Completed locally: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python3 -m pytest app/llmctl-studio/tests/test_rag_stage7.py` (8 passed, 1 failed).
  - Remaining failure is pre-existing/unrelated to quick-run changes: `test_contract_retrieve_unavailable_reason_code` expects `rag_health_state=configured_unhealthy` but receives `unconfigured`.

## Stage 8: Docs Updates

- [x] Update Sphinx docs for Sources quick-run behavior (including Node Activity behavior and workflow-list exclusion).
- [x] Add changelog entry in `docs/sphinx/changelog.rst`.
- [x] Update Sphinx index/toc in `docs/sphinx/index.rst` if new doc page is added.
- [x] Confirm Read the Docs build inputs remain valid after docs edits.
  - Completed locally: `PYTHONPATH=app/llmctl-studio/src .venv/bin/python3 -m sphinx -b html docs/sphinx docs/_build/html` (build succeeded; existing unrelated warnings remain in docs tree).
