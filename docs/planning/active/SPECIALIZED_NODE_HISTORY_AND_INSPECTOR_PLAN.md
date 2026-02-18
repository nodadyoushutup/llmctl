# Specialized Node History And Inspector Plan

Goal: design and implement durable, queryable run history plus specialized inspector behavior for `Memory`, `Plan`, `Milestone`, and `Decision` nodes, including MCP defaults, prebaked action prompts, and detail views that expose node-specific historical artifacts.
Git workflow constraint: execute all work directly on `main` (no feature branches for this plan).

## Stage 0 - Requirements Gathering

- [x] Run Stage 0 interview one question per turn with explicit options.
- [x] Confirm data retention scope for node artifacts (what is persisted per node type, and how long).
- [x] Confirm canonical database model and ownership links (`flowchart`, `node`, `run`, `variant`, `artifact`).
- [x] Confirm UX scope for `Workflow > Memories` detail view and artifact history browsing.
- [x] Confirm required Memory node inspector controls (locked MCP server, action selector, additive prompt behavior).
- [x] Confirm behavior when Memory node prompt is empty (best-effort add/retrieve from incoming context).
- [x] Confirm Plan node inspector controls and execution semantics (including stage/task completion behavior).
- [x] Confirm Milestone and Decision node inspector controls, action options, and output storage behavior.
- [x] Confirm Decision no-match behavior and routing payload contract for downstream launches.
- [x] Confirm Plan completion-target identification and conflict behavior.
- [x] Confirm selector-option taxonomy and whether to hide/disable generic options for specialized nodes.
- [x] Confirm API/socket contract requirements and required event names for persisted artifact updates.
- [x] Confirm MCP server alignment scope for specialized artifact CRUD and execution usage boundaries.
- [x] Confirm migration/backfill requirements for existing runs and existing Memory nodes.
- [x] Confirm default retention setting for specialized node artifacts.
- [x] Confirm delivery orchestration: sequential shared-baseline stages, then A/B/C/D fan-out stages, with explicit fan-out alert and prepared agent prompts.
- [x] Confirm Stage 0 completeness and ask whether to proceed to Stage 1.

## Stage 0 - Interview Notes

- [x] Scope split: `Two-wave` selected.
- [x] Delivery model requirement: plan must support `A/B/C/D` parallel agents, with shared prerequisites completed sequentially before fan-out.
- [x] At fan-out boundary, provide explicit alert plus ready-to-run agent prompts for each agent.
- [x] Shared prerequisite gate: `Medium baseline` selected (`schema+migration+shared services` + `shared inspector plumbing` + `shared API/socket envelopes`) before fan-out.
- [x] Retention policy: configurable per specialized node via runtime settings with options `forever`, `TTL`, or `max-count` (and combinable where supported).
- [x] Data model: use a unified `node_artifacts` table with `artifact_type` discriminator and shared ownership links (`flowchart_id`, `node_id`, `run_id`, optional variant key).
- [x] Wave 1 UX scope: ship `Workflow > Memories` detail/history UI now; Plan history persists in backend but Plan UI is deferred.
- [x] Memory inspector MCP behavior: `LLMCTL MCP server` is hard-locked enabled (visible and non-uncheckable).
- [x] Memory action control: required dropdown selection between `Add memory` and `Retrieve memory` (no auto mode).
- [x] Memory prompting: selected action determines prebaked internal prompt; user prompt is optional additive instructions.
- [x] Empty user prompt behavior: infer add/retrieve target from incoming connected-node context and execute via forced `LLMCTL MCP`.
- [x] Plan node actions in Wave 1: required action selector with `Create or update plan` and `Complete plan item`; prompt remains optional additive instructions.
- [x] Milestone node actions: support `Create/Update milestone` and `Mark milestone complete`.
- [x] Decision node behavior: focus on one explicit decision evaluation that drives downstream connector routing.
- [x] Decision conditions: conditions are auto-derived from solid output connectors (`N` solid outputs => `N` conditions) and user supplies condition text per condition.
- [x] Decision execution: do not use MCP; use incoming contexts + condition text to produce programmatic routing output for launching connected nodes.
- [x] Decision routing mode: multi-path allowed; launch all connector paths with satisfied conditions.
- [x] Decision no-match behavior: end naturally with no downstream launches (equivalent to a node with no target connectors).
- [x] Decision routing payload contract (for run records/API/socket): include `matched_connector_ids` (launch list), `evaluations` (per connector: `connector_id`, `condition_text`, `matched`, `reason`), and `no_match`.
- [x] Inspector taxonomy: specialized nodes use curated-only inspector controls (hide irrelevant generic options).
- [x] Contract scope: deliver stable REST + socket contracts now for specialized artifact history with standardized error envelope and request/correlation IDs.
- [x] Plan completion targeting: `Complete plan item` resolves by canonical `plan_item_id` when present, else deterministic fallback (`stage_key` + normalized `task_key`); ambiguous matches fail with explicit validation error.
- [x] MCP alignment: implement/align MCP CRUD coverage for specialized node artifacts (`memory`, `plan`, `milestone`, `decision`), while keeping Decision execution path MCP-free.
- [x] Migration/backfill: no historical backfill; begin artifact persistence from deployment forward.
- [x] Retention defaults: default mode is TTL with `1 hour`; node runtime settings may switch to `forever`, `max-count`, or combined policy where supported.

## Stage 1 - Code Planning

- [x] Stage 0 requirements are complete and approved to proceed.
- [x] Define Stage 2 through Stage X implementation stages from approved requirements.
- [x] Freeze sequential baseline vs A/B/C/D fan-out ordering.
- [x] Prepare explicit fan-out alert and copy/paste-ready prompts for four agents.
- [x] Ensure final two stages are `Automated Testing` and `Docs Updates`.

## Stage 1 - Output (Execution Stages, Ordering, And Agent Mapping)

- [x] Stage 2-4 are sequential shared-baseline gates and must complete before any specialization fan-out.
- [x] Stage 5 is an explicit fan-out readiness checkpoint that pauses and alerts operator before parallel work starts.
- [x] Stage 6A-6D are parallel specialization tracks mapped to one agent per node family.
- [x] Stage 6A = Agent A (`Memory`) and Stage 6B = Agent B (`Plan`) are Wave 1 implementation tracks.
- [x] Stage 6C = Agent C (`Milestone`) and Stage 6D = Agent D (`Decision`) are Wave 2 implementation tracks.
- [x] Stage 7 merges and reconciles all fan-out workstreams on `main` against shared contracts.
- [x] Final order is fixed: Stage 8 `Automated Testing`, then Stage 9 `Docs Updates`.

## Stage 2 - Shared Baseline Schema And Retention Runtime Settings (Sequential)

- [x] Add unified `node_artifacts` persistence model and migration with ownership links: `flowchart_id`, `flowchart_node_id`, `flowchart_run_id`, optional variant key, and `artifact_type`.
- [x] Add artifact payload/version metadata and timestamps to support audit history and evolution.
- [x] Add specialized node runtime retention settings in `FlowchartNode.config_json` contract (`retention_mode`, `retention_ttl_seconds`, `retention_max_count`) with defaults (`TTL=3600` seconds).
- [x] Implement retention pruning policy service with deterministic precedence when multiple constraints are enabled.
- [x] Add DB/service tests for create/list/prune behavior and no-backfill migration policy.

## Stage 3 - Shared Baseline API, Socket, And MCP Contract Layer (Sequential)

- [x] Add backend API endpoints for specialized artifact history list/detail with pagination/filter/sort and consistent error envelope (`code`, `message`, `details`, `request_id`).
- [x] Add backend serialization contract for decision routing payload (`matched_connector_ids`, `evaluations`, `no_match`) and plan item targeting metadata.
- [x] Add/extend realtime events for specialized artifact persistence updates after commit, including `request_id` and `correlation_id`.
- [x] Align MCP server CRUD contracts for specialized artifact entities (`memory`, `plan`, `milestone`, `decision`) in `app/llmctl-mcp/src/tools.py` while preserving Decision execution as MCP-free.
- [x] Add backend and MCP contract tests for request/response payloads and socket envelope stability.

## Stage 4 - Shared Baseline Inspector Framework And Curated Control Registry (Sequential)

- [x] Refactor flowchart inspector rendering to a specialized-node control registry in `app/llmctl-studio-frontend/src/components/FlowchartWorkspaceEditor.jsx`.
- [x] Enforce curated-only inspector controls for specialized nodes; hide irrelevant generic controls.
- [x] Implement shared specialized controls: required action selector, optional additive prompt field, retention runtime settings, and validation/error wiring.
- [x] Enforce hard-locked `LLMCTL MCP` selection behavior for node types that require it.
- [x] Add frontend tests for inspector rendering rules and locked/required input behavior.

## Stage 5 - Fan-Out Readiness Gate (Sequential Stop Point)

- [x] Verify Stage 2-4 are merged and green before specialization continuation.
- [x] Confirm shared contracts are frozen (`node_artifacts`, API envelope, socket payload keys, inspector config schema).
- [x] Record operator decision: skip fan-out/parallel branch workflow and execute remaining stages serially on `main`.
- [x] Proceed with Stage 6+ implementation directly on `main` (no fan-out launch).

## Stage 6A - Agent A: Memory Specialization (Wave 1, Parallel)

- [x] Implement Memory-node execution semantics: required `Add/Retrieve` action, internal action prompt templates, optional additive prompt behavior.
- [x] Implement empty additive prompt inference from incoming upstream contexts.
- [x] Force and validate `LLMCTL MCP` usage for Memory execution path.
- [x] Persist per-run Memory artifacts into `node_artifacts` and expose in `Workflow > Memories` detail history UI.
- [x] Update Memory list/detail UX to show artifact history variants without redundant ID/updated columns in clickable row views.
- [x] Add backend/frontend tests for Memory action behavior, persistence, and detail rendering.

## Stage 6B - Agent B: Plan Specialization (Wave 1, Parallel)

- [x] Implement Plan-node required action selector (`Create or update plan`, `Complete plan item`) with optional additive prompt.
- [x] Implement plan completion target resolution (`plan_item_id`, fallback `stage_key + task_key`, ambiguity => validation error).
- [x] Persist Plan run artifacts to `node_artifacts` with stable references for stages/tasks touched per run.
- [x] Keep Plan history UI deferred in Wave 1 while ensuring API/MCP contract supports retrieval now.
- [x] Add tests covering action selection, targeting resolution, artifact persistence, and contract serialization.

## Stage 6C - Agent C: Milestone Specialization (Wave 2, Parallel)

- [x] Implement Milestone-node required action selector (`Create/Update milestone`, `Mark milestone complete`) with optional additive prompt.
- [x] Persist Milestone run artifacts and state transitions to `node_artifacts`.
- [x] Apply curated inspector behavior and retention settings for Milestone node type.
- [x] Align MCP CRUD semantics for milestone artifact history retrieval/update paths.
- [x] Add backend/frontend tests for Milestone execution behavior and artifact contracts.

## Stage 6D - Agent D: Decision Specialization (Wave 2, Parallel)

- [x] Implement Decision-node condition management driven by solid outgoing connectors (`N connectors => N conditions`) in inspector UX.
- [x] Implement Decision execution without MCP using incoming context + condition text evaluation.
- [x] Update routing engine to multi-match semantics (launch all matched connectors) and no-match natural terminal behavior.
- [x] Persist Decision evaluation artifact in `node_artifacts` with `matched_connector_ids`, per-connector `evaluations`, and `no_match`.
- [x] Add tests for connector-condition synchronization, multi-route launch, no-match behavior, and decision payload contract.

## Stage 7 - Cross-Agent Merge, Integration, And Fan-In (Sequential)

- [x] Merge A/B/C/D outputs on top of shared baseline and resolve schema/API/inspector contract conflicts.
- [x] Run integration verification across flowchart execution paths that mix specialized nodes.
- [x] Ensure operation-level UI outcomes are routed through shared flash messages.
- [x] Capture frontend visual verification screenshot(s) using the `chromium-screenshot` skill and record artifact path(s) in this plan.

Stage 7 evidence:
- Fan-in/merge validated as satisfied by serialized implementation directly on `main` (no branch fan-out).
- Mixed-node integration verification passed: `~/.codex/skills/llmctl-studio-test-postgres/scripts/run_backend_tests_with_postgres.sh -- .venv/bin/python3 -m unittest app/llmctl-studio-backend/tests/test_flowchart_stage9.py -k test_node_type_behaviors_task_plan_milestone_memory_decision`.
- Flash-area routing hardened for operation outcomes by removing per-page inline operation banners in Flowchart/Plan/Milestone/Flowcharts pages.
- Screenshot captured via `chromium-screenshot`: `docs/screenshots/2026-02-18-01-21-26--flowcharts--stage7-flash-audit--1920x1080--9777ac1--05a1ef.png`.

## Stage 8 - Automated Testing

- [ ] Run backend unit/contract/integration tests for schema, API, socket events, execution routing, and retention pruning.
- [ ] Run MCP test coverage for specialized artifact CRUD contract alignment.
- [ ] Run frontend test suites for inspector controls and Memory history UI behavior.
- [ ] Record pass/fail outcomes and unresolved defects directly in this plan.

## Stage 9 - Docs Updates

- [ ] Update Sphinx/RTD docs for specialized node behavior, inspector controls, retention settings, and artifact history APIs.
- [ ] Document socket/MCP contracts and event payload schemas for specialized artifacts.
- [ ] Update changelog/release notes with Wave 1 and Wave 2 rollout boundaries.
- [ ] Include fan-out workflow guidance and operator checklist for Stage 5 parallel launch.

## Fan-Out Alert And Agent Prompt Pack (Use At Stage 5)

- [x] Agent A prompt prepared.
- [x] Agent B prompt prepared.
- [x] Agent C prompt prepared.
- [x] Agent D prompt prepared.

Agent A Prompt (Memory):
```text
Work on `main` only. Do not create a feature branch.

Goal:
Implement Memory-node specialized behavior end-to-end on top of merged Stage 2-4 baseline.

Required outcomes:
1) Memory inspector:
- Required action dropdown: Add memory | Retrieve memory (no auto mode).
- Optional additive prompt field.
- Retention settings surfaced (TTL/max-count/forever).
- LLMCTL MCP hard-locked ON and cannot be unchecked.

2) Execution behavior:
- If additive prompt is blank, infer from incoming upstream context + selected action.
- Always execute memory operations through LLMCTL MCP for Memory node path.
- Persist per-run memory artifact records into node_artifacts with run/node links.

3) Workflow > Memories UX:
- Memory detail page must show artifact history list for that memory node/ref and run variants.
- Keep list-view row-link behavior intact (table-row-link/data-href; ignore interactive clicks).
- Use icon-only actions and shared flash area for operation outcomes.

4) Contracts/tests:
- Add/extend backend + frontend tests for inspector validation, execution, persistence, and history API rendering.
- Keep API/socket envelopes stable; include request_id/correlation_id fields.

Primary files to inspect first:
- app/llmctl-studio-backend/src/services/tasks.py
- app/llmctl-studio-backend/src/web/views.py
- app/llmctl-studio-backend/src/core/models.py
- app/llmctl-studio-frontend/src/components/FlowchartWorkspaceEditor.jsx
- app/llmctl-studio-frontend/src/pages/MemoriesPage.jsx
- app/llmctl-studio-frontend/src/pages/MemoryDetailPage.jsx
- app/llmctl-studio-frontend/src/lib/studioApi.js
```

Agent B Prompt (Plan):
```text
Work on `main` only. Do not create a feature branch.

Goal:
Implement Plan-node specialized behavior on top of merged Stage 2-4 baseline.

Required outcomes:
1) Plan inspector:
- Required action dropdown: Create or update plan | Complete plan item.
- Optional additive prompt field.
- Curated-only controls for specialized node behavior.
- Retention settings surfaced from baseline schema.

2) Execution behavior:
- Implement completion targeting:
  - Prefer plan_item_id.
  - Fallback: stage_key + normalized task_key.
  - Ambiguous target => explicit validation error.
- Persist plan run artifacts to node_artifacts with touched stage/task references.

3) Wave boundary:
- Plan history UI is deferred in Wave 1; do not build a new Plan history screen now.
- Ensure backend/API/MCP contracts are fully queryable for plan artifacts now.

4) Contracts/tests:
- Add backend tests for targeting resolution, action semantics, persistence payloads.
- Keep standardized error envelope and request_id/correlation_id propagation.

Primary files:
- app/llmctl-studio-backend/src/services/tasks.py
- app/llmctl-studio-backend/src/web/views.py
- app/llmctl-studio-backend/src/core/models.py
- app/llmctl-studio-frontend/src/components/FlowchartWorkspaceEditor.jsx
- app/llmctl-studio-frontend/src/lib/studioApi.js
- app/llmctl-studio-frontend/src/pages/PlanDetailPage.jsx
```

Agent C Prompt (Milestone, Wave 2):
```text
Work on `main` only. Do not create a feature branch.

Goal:
Implement Milestone-node specialization after Wave 2 start, on top of merged Stage 2-4 baseline.

Required outcomes:
1) Milestone inspector:
- Required action dropdown: Create/Update milestone | Mark milestone complete.
- Optional additive prompt field.
- Curated-only specialized controls + retention settings.

2) Execution behavior:
- Apply action semantics to milestone state transitions.
- Persist milestone artifacts to node_artifacts per run/node execution.

3) MCP alignment:
- Ensure MCP CRUD paths expose milestone artifact history consistently.
- Keep Decision execution MCP-free (do not alter that rule).

4) Contracts/tests:
- Add backend/frontend tests for milestone action semantics and artifact serialization.
- Preserve standardized error envelope and request_id/correlation_id behavior.

Primary files:
- app/llmctl-studio-backend/src/services/tasks.py
- app/llmctl-studio-backend/src/web/views.py
- app/llmctl-studio-backend/src/core/models.py
- app/llmctl-studio-frontend/src/components/FlowchartWorkspaceEditor.jsx
- app/llmctl-mcp/src/tools.py
```

Agent D Prompt (Decision, Wave 2):
```text
Work on `main` only. Do not create a feature branch.

Goal:
Implement Decision-node specialization after Wave 2 start, on top of merged Stage 2-4 baseline.

Required outcomes:
1) Decision inspector:
- Conditions are auto-managed from solid outgoing connectors.
- N solid output connectors => N editable condition entries.
- Curated-only specialized controls; no MCP selection for decision execution.

2) Execution/routing behavior:
- Evaluate decision using incoming context + condition text only (no MCP).
- Multi-path routing: launch all matched connectors.
- No-match behavior: natural terminal end (launch none).
- Persist decision artifact payload with:
  - matched_connector_ids
  - evaluations[] (connector_id, condition_text, matched, reason)
  - no_match

3) Runtime integration:
- Update outgoing-edge resolution to support multi-match for decision nodes.
- Ensure downstream launch uses matched connector set programmatically.

4) Contracts/tests:
- Add tests for connector-condition sync, multi-route launch, and no-match terminal behavior.
- Keep API/socket contract stable and include request_id/correlation_id.

Primary files:
- app/llmctl-studio-backend/src/services/tasks.py
- app/llmctl-studio-backend/src/web/views.py
- app/llmctl-studio-backend/src/core/models.py
- app/llmctl-studio-frontend/src/components/FlowchartWorkspaceEditor.jsx
- app/llmctl-mcp/src/tools.py
```
