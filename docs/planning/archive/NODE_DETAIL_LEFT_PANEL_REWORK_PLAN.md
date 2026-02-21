# Node Detail Left Panel Rework Plan

Goal: redesign the Node Detail left panel information architecture so each section has a clear purpose, incoming connector context is first-class, and execution data is easier to scan.

## Stage 0 - Requirements Gathering

- [x] Confirm target user workflow(s) for the Node Detail left panel.
- [x] Confirm final section taxonomy (which sections exist and in what order).
- [x] Confirm exactly what belongs in `Context` (connector context scope and detail level).
- [x] Confirm exactly what belongs in `Output` vs `Details` vs `Raw JSON`.
- [x] Confirm display style preferences per section (table, prose, code blocks, collapsible behavior).
- [x] Confirm defaults for expanded/collapsed sections.
- [x] Confirm handling of empty/missing data in each section.
- [x] Confirm whether resource metadata (integrations/MCP/scripts/attachments) stays in `Context` or moves to a dedicated section.
- [x] Confirm Stage 0 completion and approval to start Stage 1.

## Stage 0 - Interview Notes (Captured)

- [x] User requested planning-first workflow with interactive interviewing before implementation.
- [x] User requested `Context` to show info captured by incoming connectors.
- [x] User wants a dedicated `Raw JSON` section kept for debugging.
- [x] User wants a dedicated `Input` section sourced from connector-fed input only.
- [x] Terminology preference for connector inputs:
  - [x] Use `trigger + context` (do not use `solid`).
  - [x] Use `context only` (do not use `dotted`).
- [x] In `Input`, each connector input should render as its own collapsible table block.
- [x] User wants dedicated `MCP Servers` and `Collections` sections.
- [x] User wants a dedicated `Agent` section showing which agent the node used.
- [x] User wants a dedicated `Results` section with plain-English results.
- [x] User wants a dedicated `Prompt` section showing inferred/additional prompt context.
- [x] Deterministic prompt behavior decision:
  - [x] Show `Prompt` section for deterministic nodes.
  - [x] Show provided prompt fields only.
  - [x] Show explicit notice: `No inferred prompt in deterministic mode.`
- [x] Section order baseline selected from Option 1:
  - [x] `Input`, `Results`, `Prompt`, `MCP Servers`, `Collections`, `Raw JSON`, `Details`.
  - [x] User requested `Agent` be included in this ordered set.
- [x] Final section order (with Agent placement):
  - [x] `Input`, `Results`, `Prompt`, `Agent`, `MCP Servers`, `Collections`, `Raw JSON`, `Details`.
- [x] Default expanded/collapsed state:
  - [x] `Results` expanded by default.
  - [x] All other sections collapsed by default.
- [x] Empty-state behavior:
  - [x] Show a short explicit empty message inside each section body.

## Stage 1 - Code Planning

- [x] Define backend contract changes required for left-panel data model.
- [x] Define frontend view model for section composition and ordering.
- [x] Define reusable rendering primitives for metadata rows/tables and structured context blocks.
- [x] Define migration strategy for existing payload consumers/tests.
- [x] Define testing strategy (backend contract tests + frontend rendering tests).

### Stage 1 Decisions (2026-02-21)

- Backend contract target (`app/llmctl-studio-backend/src/web/views/chat_nodes.py`):
  - Add a canonical `left_panel` object on `GET /nodes/<id>?format=json` with fixed section keys:
    - `input`, `results`, `prompt`, `agent`, `mcp_servers`, `collections`, `raw_json`, `details`.
  - Keep existing top-level payload fields used outside left-panel rendering (`task`, `stage_entries`, `attachments`, status fields) unchanged.
  - Normalize connector context naming to match approved terminology:
    - `trigger_*` for trigger-path connectors.
    - `context_only_*` for pulled context connectors (no `dotted_*` labels in UI-facing fields).
  - Include pre-shaped connector input blocks for per-connector rendering (each block includes connector metadata and its `output_state` table payload).
  - Include deterministic prompt metadata so UI can always render:
    - provided prompt fields
    - explicit `no_inferred_prompt_in_deterministic_mode` notice flag/message
  - Include collections payload independent of quick-task-only context so both quick RAG and flowchart RAG nodes can populate the `Collections` section from canonical node/task context.

- Frontend view model target (`app/llmctl-studio-frontend/src/pages/NodeDetailPage.jsx`, `app/llmctl-studio-frontend/src/pages/NodeDetailPage.helpers.js`):
  - Move left-panel section composition into a helper-driven view model (`buildNodeLeftPanelSections(payload)`).
  - Enforce fixed section order:
    - `Input`, `Results`, `Prompt`, `Agent`, `MCP Servers`, `Collections`, `Raw JSON`, `Details`.
  - Set default expanded section to `Results`; all other sections default collapsed.
  - Render section-level explicit empty states from view-model values (avoid ad-hoc per-branch copy drift).

- Reusable rendering primitives target (`app/llmctl-studio-frontend/src/components/` + NodeDetail page-local subcomponents):
  - Extract a reusable metadata table renderer for plain label/value rows (no chips/cards for metadata fields).
  - Extract reusable collapsible section chrome used by each left-panel section card.
  - Extract reusable connector input block renderer to support one-collapsible-block-per-connector behavior.
  - Reuse existing status chip styles only for compact status indicators, not for metadata presentation.

- Migration strategy:
  - Single-cut migration within this repo: backend contract + NodeDetail UI + tests land together; do not preserve duplicate legacy left-panel rendering paths.
  - Keep API compatibility for non-left-panel consumers by leaving unrelated node detail fields in place.
  - Remove/replace old mixed `Context` resource rendering once dedicated `Agent` / `MCP Servers` / `Collections` sections are wired.

- Testing strategy:
  - Backend: extend node detail API contract coverage in `app/llmctl-studio-backend/tests/test_node_executor_stage8.py` for:
    - section payload shape under `left_panel`
    - terminology mapping (`context_only` vs legacy dotted internals)
    - deterministic prompt notice behavior
  - Frontend: expand `app/llmctl-studio-frontend/src/pages/NodeDetailPage.test.jsx` to cover:
    - section ordering/default expanded key
    - per-section empty-state text
    - connector input block rendering contract (one block per connector source)
    - metadata table rendering in `Agent` / `MCP Servers` / `Collections` / `Details`

## Stage 2 - Scope-Specific Planning

- [x] Freeze section-by-section field mapping and acceptance criteria.
- [x] Freeze context rendering contract (connector summaries + payload display rules).
- [x] Freeze interaction behavior (collapse state, default open section, sticky behavior if any).
- [x] Freeze copy/labels and empty-state language.

### Stage 2 Decisions (2026-02-21)

- Section field mapping (frozen):
  - `Input`:
    - `left_panel.input.source`
    - `left_panel.input.trigger_source_count`
    - `left_panel.input.context_only_source_count`
    - `left_panel.input.connector_blocks[]` (one block per connector source)
    - `left_panel.input.resolved_input_context`
  - `Results`:
    - `left_panel.results.summary_rows[]`
    - `left_panel.results.primary_text`
    - `left_panel.results.action_results[]`
  - `Prompt`:
    - `left_panel.prompt.provided_prompt_text`
    - `left_panel.prompt.provided_prompt_fields`
    - `left_panel.prompt.no_inferred_prompt_in_deterministic_mode` + `notice`
  - `Agent`:
    - `left_panel.agent.id`
    - `left_panel.agent.name`
    - `left_panel.agent.link_href`
  - `MCP Servers`:
    - `left_panel.mcp_servers.items[]` (`id`, `name`, `server_key`)
  - `Collections`:
    - `left_panel.collections.items[]` (`id_or_key`, `name`)
  - `Raw JSON`:
    - `left_panel.raw_json.formatted_output`
    - `left_panel.raw_json.is_json`
  - `Details`:
    - `left_panel.details.rows[]` (plain metadata rows)

- Acceptance criteria (frozen):
  - Section order is exactly: `Input`, `Results`, `Prompt`, `Agent`, `MCP Servers`, `Collections`, `Raw JSON`, `Details`.
  - Each section renders from its owned fields only (no cross-section duplication).
  - Metadata is rendered as rows/tables, not chips/cards.
  - `Input` renders each connector source as a separate collapsible table block.
  - `Raw JSON` always shows formatted JSON when parseable; otherwise raw text.

- Context rendering contract (frozen):
  - UI-facing terminology:
    - `trigger` for trigger-path incoming connectors.
    - `context only` for pulled context connectors.
  - Backend may retain internal `dotted` naming, but UI contract fields exposed to left panel use `context_only_*`.
  - Each `connector_blocks[]` entry includes:
    - connector identity metadata (source node id/type, connector id/condition key where present)
    - connector classification (`trigger` or `context_only`)
    - connector `output_state` payload (structured table + raw JSON fallback)
  - `resolved_input_context` is shown after connector blocks as the merged input snapshot for the node run.

- Interaction behavior (frozen):
  - `Results` is expanded by default on initial load.
  - All other sections are collapsed by default.
  - Section expansion uses single-open accordion behavior (opening one section closes prior open section).
  - No sticky header/section behavior in this slice.
  - Existing left-panel width expand/collapse toggle remains unchanged.

- Copy/labels and empty-state language (frozen):
  - Section labels are exactly:
    - `Input`, `Results`, `Prompt`, `Agent`, `MCP Servers`, `Collections`, `Raw JSON`, `Details`
  - Empty-state copy:
    - `Input`: `No incoming connector context captured for this node run.`
    - `Results`: `No results yet.`
    - `Prompt`: `No prompt recorded.` plus deterministic notice when applicable: `No inferred prompt in deterministic mode.`
    - `Agent`: `No agent recorded for this node.`
    - `MCP Servers`: `No MCP servers selected.`
    - `Collections`: `No collections selected.`
    - `Raw JSON`: `No output yet.`
    - `Details`: `No details yet.`

## Stage 3 - Execution: Backend Contract Alignment

- [x] Implement/adjust node detail API payload fields needed by the new left-panel structure.
- [x] Add/update backend tests for node detail response contract.

## Stage 4 - Execution: Frontend Left Panel IA

- [x] Implement final left-panel section structure and ordering.
- [x] Move fields into agreed section ownership (`Output`, `Details`, `Context`, etc.).
- [x] Ensure metadata presentation follows table/row rules.

## Stage 5 - Execution: Context Rendering

- [x] Implement finalized connector-context presentation in `Context`.
- [x] Implement connector summaries and structured payload rendering.
- [x] Add/update frontend tests for `Context` display behavior.

## Stage 6 - Execution: UX Polish + Empty States

- [x] Implement agreed defaults for section expansion/collapse.
- [x] Implement consistent empty/fallback states across all left-panel sections.
- [x] Validate mobile/desktop usability of the redesigned panel.

## Stage 7 - Automated Testing

- [x] Run targeted backend tests for node detail payload changes.
- [x] Run targeted frontend tests for Node Detail rendering changes.
- [x] Capture verification notes and resolve regressions.

### Stage 7 Verification Notes

- Backend targeted contract tests:
  - `.venv/bin/python3 -m pytest -q app/llmctl-studio-backend/tests/test_node_executor_stage8.py -k "node_detail_api_includes_runtime_evidence_metadata or node_detail_api_includes_incoming_connector_context or node_detail_api_includes_left_panel_contract"`
  - Result: `3 passed, 6 deselected`
- Frontend targeted Node Detail tests:
  - `cd app/llmctl-studio-frontend && npm test -- src/pages/NodeDetailPage.test.jsx`
  - Result: `11 passed`
- Frontend build verification:
  - `cd app/llmctl-studio-frontend && npm run build`
  - Result: successful production build
- Frontend visual verification artifacts:
  - `docs/screenshots/2026-02-21-15-30-33--nodes-node-detail--stage6-ux-polish-desktop--1920x1080--b1b1ed9--8a0d24.png`
  - `docs/screenshots/2026-02-21-15-30-33--nodes-node-detail--stage6-ux-polish-mobile--390x844--b1b1ed9--372d15.png`

## Stage 8 - Docs Updates

- [x] Update planning artifacts with final decisions and implementation notes.
- [x] Update any Studio docs/readme references that describe Node Detail left-panel behavior.
