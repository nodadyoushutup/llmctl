# Draw.io And Lucidchart Flowchart Import Integration Idea Plan

Status: pending draft

## Goal
Define a lightweight implementation direction for integrating Draw.io and Lucidchart so users can browse available flowcharts, expose them through MCP tooling, and import selected diagrams into the internal flowchart system.

## Stage 0 - Requirements Gathering
- [x] Capture initial requested scope:
  - Add Draw.io integration.
  - Add Lucidchart integration.
  - Surface available provider flowcharts in product UI.
  - Add MCP server support for provider flowchart listing/import actions.
  - Support importing external flowcharts into the internal flowchart system.
  - Defer detailed node remapping/edit behavior until the full implementation plan.
- [ ] Confirm execution mode for this workstream (`plan-only` vs `plan + implementation`).
- [ ] Confirm initial provider auth approach for each integration (user OAuth vs workspace service account).
- [ ] Confirm first-pass import behavior expectations (structure-only import vs structure + metadata parity).
- [ ] Confirm Stage 0 completion and approval to proceed to Stage 1.

## Stage 0 - Interview Notes
- [x] User requested a pending planning doc that is a brief idea, not a full implementation plan.
- [x] User requested Draw.io and Lucidchart integrations with visibility into provider flowcharts.
- [x] User requested MCP server coverage for these integrations.
- [x] User requested import into internal flowcharts.
- [x] User explicitly deferred deep node-adjustment design until a later full plan.

## Stage 1 - Code Planning
- [ ] Define candidate architecture boundaries (frontend list/browse, backend integration adapters, MCP server endpoints/tools, import translator pipeline).
- [ ] Identify canonical domain models for external diagram metadata and internal flowchart graph representation.
- [ ] Define risk register and unknowns that must be closed before implementation.

## Stage 2 - Scope-Specific Planning
- [ ] Draft provider capability matrix (Draw.io vs Lucidchart API/auth/list/export constraints).
- [ ] Draft MCP contract surface for flowchart discovery/import operations.
- [ ] Draft import translation approach and unsupported-shape fallback behavior.

## Stage 3 - Provider Discovery And Adapter Implementation
- [ ] Implement backend provider adapters to list diagrams and fetch exportable definitions.
- [ ] Add standardized error handling and request/correlation IDs across integration calls.
- [ ] Add tests for provider adapter success/failure paths.

## Stage 4 - MCP Server Integration
- [ ] Implement MCP tools/resources to list provider flowcharts and trigger import workflows.
- [ ] Enforce idempotent import requests where practical via correlation/request keys.
- [ ] Add contract tests for MCP payloads and error envelopes.

## Stage 5 - Internal Import Pipeline
- [ ] Implement external-to-internal graph translation for a first-pass supported subset.
- [ ] Persist imported flowcharts in canonical internal schema.
- [ ] Record non-translatable elements as explicit import warnings.

## Stage 6 - UI Integration
- [ ] Add UI surface to browse external provider flowcharts and initiate import actions.
- [ ] Route operation outcomes through shared flash message area.
- [ ] Ensure list/detail behaviors align with shared list standards and row-link interaction rules.

## Stage 7 - Node Remapping And Post-Import Editing (Deferred For Full Plan)
- [ ] Define node remapping/edit UX and transformation rules after initial import.
- [ ] Define conflict-resolution flows for unsupported nodes/edges and schema mismatches.
- [ ] Add implementation tasks in the future full plan after Stage 0 interview closure.

## Stage 8 - Automated Testing
- [ ] Add/update backend tests for provider adapters, import pipeline, and MCP contracts.
- [ ] Add/update frontend tests for external-flowchart browse/import UX and flash outcomes.
- [ ] Run relevant automated suites and record results.

## Stage 9 - Docs Updates
- [ ] Update Sphinx/Read the Docs docs for provider integrations, MCP usage, and import constraints.
- [ ] Move this plan from `docs/planning/active/` to `docs/planning/archive/` when implementation work is complete.
