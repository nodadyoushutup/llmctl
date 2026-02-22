# MCP Server-Driven Integration Auto-Apply Plan

Goal: remove manual integration selection by deriving and auto-applying valid integration context from selected MCP server(s) across Nodes, Quick Nodes, and Chat runs.

## Stage 0 - Requirements Gathering

- [x] Capture user objective for MCP server-driven integration auto-apply behavior.
- [x] Capture initial target surfaces from request (`Nodes`, `Quick Nodes`, `Chat`).
- [x] Confirm authoritative mapping model from MCP server selection to integration payload(s).
- [x] Confirm behavior when mapped integrations are missing, invalid, or partially configured.
- [x] Confirm whether auto-apply should be implicit-only or user-visible/overridable in UI.
- [x] Confirm Stage 0 completion and approval to proceed to Stage 1.

## Stage 0 - Interview Notes (Captured)

- [x] User wants manual integration selection removed from runtime setup flows.
- [x] User wants selecting an MCP server to automatically apply matching integration data.
- [x] User expects provider-specific mapping examples:
- [x] `GitHub MCP server -> GitHub integration context (for example repository context)`.
- [x] `Atlassian MCP server -> Jira and Confluence integrations when configured and valid`.
- [x] User expects this behavior across `Nodes`, `Quick Nodes`, and `Chat`.
- [x] Mapping model locked for this implementation: backend static map (code-defined rules).
- [x] Missing/invalid mapped integrations behavior locked: soft warning + continue execution without unavailable integrations.
- [x] Auto-apply UI behavior locked: fully implicit from MCP selection (no manual override UI).

## Stage 1 - Code Planning

- [x] Identify current MCP selection surfaces and integration selection/storage flow across backend + frontend.
- [x] Define canonical mapping contract (`mcp_server_key -> required/optional integration keys + validation rules`).
- [x] Define data flow/ownership for resolving effective integrations at execution time.
- [x] Define removal or deprecation path for manual integration selectors.
- [x] Define Stage 3+ execution sequence and acceptance criteria.

### Stage 1 Findings (2026-02-22)

- Regular node creation currently uses manual `integration_keys` and does not expose MCP selection in the create payload/UI:
  - `app/llmctl-studio-backend/src/web/views/chat_nodes.py`
  - `app/llmctl-studio-frontend/src/pages/NodeNewPage.jsx`
  - `app/llmctl-studio-frontend/src/lib/studioApi.js`
- Quick node creation currently carries both MCP and manual integration selectors/defaults:
  - `app/llmctl-studio-backend/src/web/views/agents_runs.py`
  - `app/llmctl-studio-frontend/src/pages/QuickTaskPage.jsx`
  - `app/llmctl-studio-frontend/src/lib/studioApi.js`
- Chat already selects MCP servers; integration guidance is derived ad-hoc from selected MCP keys via chat-only logic:
  - `app/llmctl-studio-backend/src/chat/runtime.py`
  - `app/llmctl-studio-frontend/src/pages/ChatPage.jsx`
- Runtime integration payload assembly is centralized in tasks and keyed by selected integration keys:
  - `app/llmctl-studio-backend/src/services/tasks.py`
  - `app/llmctl-studio-backend/src/core/task_integrations.py`
- Integrated MCP server keys already exist as a stable static set and align with a backend-static-map approach:
  - `app/llmctl-studio-backend/src/core/integrated_mcp.py`

### Stage 1 Decisions (Locked)

- Authoritative resolver model:
  - Add one backend-owned resolver for `selected_mcp_server_keys -> effective integration keys + warnings + payload hints`.
  - Use static mapping in code for this phase.
- Canonical static mapping (phase 1):
  - `github -> [github]`
  - `atlassian -> [jira, confluence]`
  - `jira (legacy key) -> [jira, confluence]`
  - `google-cloud -> [google_cloud]`
  - `google-workspace -> [google_workspace]`
  - `chroma -> [chroma]`
  - `llmctl-mcp -> []`
  - Unknown/custom MCP keys -> no integration mapping in this phase.
- Validation behavior:
  - Resolve mapped integrations as `configured` vs `missing/invalid` using existing integration settings loaders.
  - Soft-warning policy applies: continue execution with valid integrations, skip unavailable mappings.
- Ownership/data flow:
  - Backend computes effective integrations from MCP selection at mutation/runtime boundaries.
  - Frontend no longer submits manual integration selection.
  - Persist derived `integration_keys_json` for created tasks as an execution snapshot.
- Acceptance criteria baseline:
  - Node and Quick creation paths derive integrations from selected MCP servers only.
  - Chat MCP context and integration defaults come from the same resolver contract.
  - Manual integration selectors are removed from Node and Quick UX.
  - Missing/invalid mapped integrations produce warnings (not hard failures).

## Stage 2 - Scope-Specific Planning

- [x] Freeze rollout scope for `Nodes`, `Quick Nodes`, and `Chat`.
- [x] Freeze UX behavior for valid, invalid, and missing integration states.
- [x] Freeze API/socket contract updates and backward compatibility decisions.
- [x] Freeze observability/audit fields (effective integration resolution traces and request IDs).

### Stage 2 Scope Freeze (Locked)

- In scope:
  - Node create flow (`/nodes/new` web + API) gains MCP selection and MCP-driven integration resolution.
  - Quick create/defaults flow (`/quick`, `/quick/settings` web + API) removes manual integration selection and derives from selected MCP servers.
  - Chat runtime/session flow uses the shared MCP-to-integration resolver for integration-context guidance.
- Out of scope:
  - Dynamic/custom MCP integration mapping configuration (captured separately in `docs/planning/pending/CUSTOM_MCP_INTEGRATION_SETTINGS_FUTURE_NOTE.md`).
  - New DB schema for configurable mapping tables.
- UX behavior:
  - Manual integration selection UI is removed where present.
  - Auto-apply stays implicit (no override controls).
  - Missing/invalid mapped integrations surface as operation/runtime warnings only.
- API behavior:
  - Node/Quick endpoints stop requiring manual `integration_keys` from frontend payloads.
  - Response payloads include derived integration/warning metadata where needed for UX messaging.
  - Existing task detail remains readable via stored or computed integration labels.
- Observability:
  - Task/chat logs include selected MCP keys, resolved integration keys, and skipped-integration warnings.
  - Runtime output metadata carries effective integration keys plus warning summaries.

## Stage 3 - Execution: Backend Mapping and Resolution

- [x] Implement MCP-to-integration mapping model and validation logic.
- [x] Implement runtime resolution of effective integrations from selected MCP server(s).
- [x] Enforce soft-warning behavior for missing/invalid mapped integrations while continuing execution.
- [x] Target backend files:
  - [x] `app/llmctl-studio-backend/src/services/mcp_integrations.py` (new shared resolver module).
  - [x] `app/llmctl-studio-backend/src/chat/runtime.py` (chat integration context now uses shared resolver).
  - [x] `app/llmctl-studio-backend/src/services/tasks.py` (execution logs + output state now include resolver-driven integration warnings/keys).

## Stage 4 - Execution: API and Runtime Wiring

- [x] Update Node and Quick API mutation/read paths to persist or derive MCP-driven integration selections.
- [x] Ensure node execution and chat execution paths consume shared resolved-integration results consistently.
- [x] Ensure socket/event payloads reflect authoritative resolved integration state.
- [x] Node + Quick API route updates:
  - [x] `app/llmctl-studio-backend/src/web/views/chat_nodes.py`:
    - [x] Add MCP selection parsing/validation for `/nodes/new`.
    - [x] Remove manual integration parsing from `/nodes/new`.
    - [x] Return derived integration warnings/metadata for JSON callers.
  - [x] `app/llmctl-studio-backend/src/web/views/agents_runs.py`:
    - [x] Remove manual integration parsing from `/quick`.
    - [x] Remove `default_integration_keys` mutation handling from `/quick/settings`.
    - [x] Return derived integration warnings/metadata for JSON callers.
- [x] Shared view/helper updates:
  - [x] `app/llmctl-studio-backend/src/web/views/shared.py` (`_resolved_quick_default_settings` now derives integrations from selected MCP defaults).
- [x] Runtime consistency:
  - [x] Ensure task creation stores derived `integration_keys_json`.
  - [x] Ensure retry/copy paths preserve derived integration snapshot + MCP selections.
  - [x] Ensure chat session/runtime execution context uses resolver-based integration defaults/warnings.

## Stage 5 - Execution: Frontend UX Updates

- [x] Remove or replace manual integration selectors where MCP selection is authoritative.
- [x] Surface clear UI states for `auto-applied`, `missing configuration`, and `invalid credentials`.
- [x] Keep operation-level outcomes routed through shared flash message area.
- [x] Target frontend files:
  - [x] `app/llmctl-studio-frontend/src/pages/NodeNewPage.jsx`:
    - [x] Add MCP server picker.
    - [x] Remove manual integration checklist.
  - [x] `app/llmctl-studio-frontend/src/pages/QuickTaskPage.jsx`:
    - [x] Remove manual integrations group from controls.
    - [x] Keep MCP picker as authoritative selection source.
  - [x] `app/llmctl-studio-frontend/src/lib/studioApi.js`:
    - [x] Remove `integration_keys` payload emission for node/quick create.
    - [x] Remove `default_integration_keys` payload emission for quick defaults.
  - [x] `app/llmctl-studio-frontend/src/pages/ChatPage.jsx`:
    - [x] Keep MCP controls.
    - [x] Surface backend warning messages via flash area when returned.

## Stage 6 - Automated Testing

- [x] Add/update backend contract tests for mapping/resolution and error envelopes.
- [x] Add/update frontend tests for selector behavior and state rendering.
- [x] Run targeted automated test suites and record command evidence.
- [x] Backend test targets:
  - [x] `app/llmctl-studio-backend/tests/test_react_stage8_api_routes.py`
  - [x] Focused integration-context subset in `app/llmctl-studio-backend/tests/test_chat_runtime_stage8.py`
  - [x] Add resolver-focused unit tests under `app/llmctl-studio-backend/tests/`.
- [x] Frontend test targets:
  - [x] `app/llmctl-studio-frontend/src/lib/studioApi.test.js`
  - [x] Add/update page-level tests for `NodeNewPage` and `QuickTaskPage` behavior.
- [x] Execute targeted test commands with repo venv:
  - [x] `.venv/bin/python3 -m pytest app/llmctl-studio-backend/tests/test_react_stage8_api_routes.py -q`
  - [x] `~/.codex/skills/llmctl-studio-test-postgres/scripts/run_backend_tests_with_postgres.sh -- .venv/bin/python3 -m pytest app/llmctl-studio-backend/tests/test_chat_runtime_stage8.py -k "includes_atlassian_defaults_for_selected_mcp or includes_github_and_chroma_defaults_for_selected_mcp or includes_google_tool_verification_guidance" -q`
  - [x] `cd app/llmctl-studio-frontend && npm test -- src/lib/studioApi.test.js`
  - [x] `.venv/bin/python3 -m pytest app/llmctl-studio-backend/tests/test_react_stage8_api_routes.py app/llmctl-studio-backend/tests/test_mcp_integrations.py -q`
  - [x] `cd app/llmctl-studio-frontend && npm test -- src/pages/NodeNewPage.test.jsx src/pages/QuickTaskPage.test.jsx src/pages/ChatPage.test.jsx src/lib/studioApi.test.js`

### Stage 6 Notes

- Full `test_chat_runtime_stage8.py` run is not fully green in this environment because multiple legacy template-render tests fail with `TemplateNotFound` (`chat_runtime.html`, `settings_runtime.html`, `settings_chat.html`). This is unrelated to the MCP-integration resolver path and persisted before targeted integration-context assertions.

## Stage 7 - Docs Updates

- [x] Update user/operator docs for MCP-driven integration behavior and constraints.
- [x] Update Sphinx/Read the Docs pages impacted by Nodes, Quick Nodes, and Chat configuration flow.
- [x] Update this plan with final evidence and move to `docs/planning/archive/` when complete.
- [x] Document static mapping table and soft-warning semantics.
- [x] Document known limitation for custom MCP server mapping (until pending future note is implemented).

### Final Evidence

- Backend route/runtime updates:
  - `app/llmctl-studio-backend/src/web/views/chat_nodes.py`
  - `app/llmctl-studio-backend/src/services/tasks.py`
- Frontend warning + MCP-authoritative page updates:
  - `app/llmctl-studio-frontend/src/pages/ChatPage.jsx`
  - `app/llmctl-studio-frontend/src/pages/NodeNewPage.test.jsx`
  - `app/llmctl-studio-frontend/src/pages/QuickTaskPage.test.jsx`
- New resolver documentation:
  - `docs/sphinx/mcp_integration_auto_apply.rst`
  - `docs/sphinx/chat_runtime.rst`
  - `docs/sphinx/index.rst`
- Runtime validation commands:
  - `.venv/bin/python3 -m py_compile app/llmctl-studio-backend/src/web/views/chat_nodes.py app/llmctl-studio-backend/src/services/tasks.py app/llmctl-studio-backend/src/services/mcp_integrations.py app/llmctl-studio-backend/tests/test_mcp_integrations.py app/llmctl-studio-backend/tests/test_react_stage8_api_routes.py`
  - `.venv/bin/python3 -m pytest app/llmctl-studio-backend/tests/test_react_stage8_api_routes.py app/llmctl-studio-backend/tests/test_mcp_integrations.py -q`
  - `cd app/llmctl-studio-frontend && npm test -- src/pages/NodeNewPage.test.jsx src/pages/QuickTaskPage.test.jsx src/pages/ChatPage.test.jsx src/lib/studioApi.test.js`
- Kubernetes rollout restarts:
  - `kubectl -n llmctl rollout restart deploy/llmctl-studio-frontend && kubectl -n llmctl rollout status deploy/llmctl-studio-frontend`
  - `kubectl -n llmctl rollout restart deploy/llmctl-studio-backend && kubectl -n llmctl rollout status deploy/llmctl-studio-backend`
- Frontend screenshot artifact:
  - `docs/screenshots/2026-02-22-14-43-45--chat-thread--mcp-integration-warning-flash-post-rollout--1920x1080--ad29731--bc67f6.png`
