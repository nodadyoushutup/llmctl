# Attachments Cross-Node Propagation And Connector Plan

## Goal
Define and execute a consistent attachment model across Chat, Quick, and Flowchart nodes, including list UX, connector semantics, and runtime propagation behavior.

## Stage 0 - Requirements Gathering
- [x] Capture the initial requested outcome and constraints.
- [x] Confirm execution mode for this effort (plan-only vs plan + implementation in this workstream).
- [x] Confirm Attachments list IA and left-nav node-type taxonomy.
- [x] Confirm exact node eligibility rules for attachment binding (including flowchart start/end exclusions).
- [x] Confirm cross-node attachment propagation semantics (reference vs copy, mutation/immutability, dedupe behavior).
- [x] Confirm connector taxonomy and naming migration.
- [x] Confirm visual encoding requirements for each connector type.
- [x] Confirm node output/input contract for attachments (node produces attachment, downstream node consumes attachment).
- [x] Confirm acceptance criteria and sign-off conditions for behavior parity.
- [x] Confirm Stage 0 completion and approval to proceed to Stage 1.

## Stage 0 - Interview Notes
- [x] User requested Attachments page migration to two-column shell with node-type left nav similar to Artifact-style grouping.
- [x] User requested attachment applicability across Chat, Quick, and Flowchart nodes, with flowchart start/end nodes excluded from binding.
- [x] User requested connector model update:
  - rename `Trigger + Context` to `Trigger + Context + Attachments`
  - keep `Context Only`
  - add `Attachments Only`
- [x] User requested dotted visual style for `Attachments Only` connectors and existing dashed style retained for `Context Only`.
- [x] User requested planning artifact focused on correctness of attachment behavior across all nodes and node-to-node attachment passing.
- [x] Execution mode selected: plan + implementation now.
- [x] Attachments left-nav taxonomy selected: three groups (`Chat`, `Quick`, `Flowchart`).
- [x] Propagation semantics selected: immutable references; downstream nodes receive attachment references, and transforms should emit new attachments.
- [x] Connector migration selected: auto-migrate existing `Trigger + Context` connectors to `Trigger + Context + Attachments` behavior.
- [x] Eligibility selected: bindings allowed on Chat, Quick, and Flowchart nodes except Start/End; Start/End do not consume or produce attachments.
- [x] Visual encoding selected: mixed connector style unchanged; `Context Only` dashed; `Attachments Only` dotted.
- [x] Produce/consume capability selected: all eligible node types can both produce and consume attachments by default.
- [x] Acceptance criteria selected: full stack delivery in this pass (Attachments page UX + connector taxonomy/rendering + runtime propagation + automated tests).
- [x] Pending Stage 0 interview clarifications resolved.

## Stage 1 - Code Planning
- [x] Define execution stages from Stage 2 onward using finalized Stage 0 requirements.
- [x] Freeze impacted surfaces (frontend pages/components, flowchart canvas/connector rendering, backend APIs/contracts, runtime propagation code, persistence).
- [x] Define test strategy and data fixtures needed for connector + propagation behavior.

## Stage 2 - Scope-Specific Planning
- [x] Finalize Attachments list UX contract (two-column shell, node-type nav, header actions, pagination placement, empty/error states).
- [x] Finalize attachment lifecycle contract (bind, unbind, produce, consume, and pass-through rules).
- [x] Finalize connector behavior matrix and migration strategy for existing flows.

## Stage 3 - Attachments List UX Implementation
- [x] Migrate `Attachments` list screen to shared two-column list shell with node-type nav sections.
- [x] Implement node-type filtered listing behavior and keep row-to-detail navigation behavior consistent.
- [x] Ensure header controls and pagination are rendered in standardized header action area.

## Stage 4 - Attachment Domain/API Contract Updates
- [x] Update backend list/filter contracts to support node-type segmented attachment views.
- [x] Ensure API responses support pagination/filter/sort conventions used by React list shell.
- [x] Add/adjust contract tests for list/read/mutation paths affected by node-type segmentation.

## Stage 5 - Flowchart Connector Model And Rendering
- [x] Add connector type `Attachments Only`.
- [x] Rename connector type label from `Trigger + Context` to `Trigger + Context + Attachments`.
- [x] Keep `Context Only` and align persisted/displayed enum labels safely.
- [x] Implement connector line-style rendering: dashed for `Context Only`, dotted for `Attachments Only`.

## Stage 6 - Runtime Propagation Semantics
- [x] Implement attachment propagation semantics for connector types across node execution transitions.
- [x] Enforce node eligibility constraints (Chat, Quick, and valid Flowchart nodes; exclude Start/End).
- [x] Ensure deterministic handling of attachment references and resolution across node boundaries.

## Stage 7 - Node Produce/Consume Attachment Behaviors
- [x] Implement node output capability to emit attachment artifacts/files.
- [x] Implement node input capability to consume bound and propagated attachments.
- [x] Validate coexistence of context propagation and attachment propagation by connector type.

## Stage 8 - Automated Testing
- [x] Add/update frontend tests for Attachments two-column layout, node-type nav filtering, and pagination/header behavior.
- [x] Add/update backend/runtime tests for connector semantics and attachment propagation across node types.
- [x] Run targeted and relevant full-suite checks for touched areas; record outcomes.

## Stage 9 - Docs Updates
- [x] Update Sphinx/Read the Docs docs for attachment behavior model, connector semantics, and UI interaction expectations.
- [x] Move this plan from `docs/planning/active/` to `docs/planning/archive/` when implementation is complete.

## Execution Evidence (2026-02-22)
- [x] Frontend tests passed:
  - `npm test -- src/pages/AttachmentsPage.test.jsx src/App.routing.test.jsx src/lib/studioApi.test.js src/components/FlowchartWorkspaceEditor.test.jsx src/pages/NodeDetailPage.test.jsx`
- [x] Backend targeted tests passed for updated behavior:
  - `test_flowchart_stage9.py` targeted cases for edge-mode validation and context/attachment propagation
  - `test_react_stage7_api_routes.py -k attachments_json_list_detail_and_delete`
- [x] Runtime deployment refresh completed:
  - `kubectl -n llmctl rollout restart deploy/llmctl-studio-frontend`
  - `kubectl -n llmctl rollout status deploy/llmctl-studio-frontend`
  - `kubectl -n llmctl rollout restart deploy/llmctl-studio-backend`
  - `kubectl -n llmctl rollout status deploy/llmctl-studio-backend`
- [x] Frontend visual verification screenshot captured and reviewed:
  - `docs/screenshots/2026-02-22-18-17-33--attachments-flowchart--two-column-nav-and-header-pagination--1920x1080--26d1dfb--6e0245.png`
