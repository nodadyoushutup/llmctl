# Specialized Node History And Inspector Plan

Goal: design and implement durable, queryable run history plus specialized inspector behavior for `Memory`, `Plan`, `Milestone`, and `Decision` nodes, including MCP defaults, prebaked action prompts, and detail views that expose node-specific historical artifacts.

## Stage 0 - Requirements Gathering

- [x] Run Stage 0 interview one question per turn with explicit options.
- [x] Confirm data retention scope for node artifacts (what is persisted per node type, and how long).
- [x] Confirm canonical database model and ownership links (`flowchart`, `node`, `run`, `variant`, `artifact`).
- [x] Confirm UX scope for `Workflow > Memories` detail view and artifact history browsing.
- [x] Confirm required Memory node inspector controls (locked MCP server, action selector, additive prompt behavior).
- [x] Confirm behavior when Memory node prompt is empty (best-effort add/retrieve from incoming context).
- [x] Confirm Plan node inspector controls and execution semantics (including stage/task completion behavior).
- [x] Confirm Milestone and Decision node inspector controls, action options, and output storage behavior.
- [x] Confirm selector-option taxonomy and whether to hide/disable generic options for specialized nodes.
- [x] Confirm API/socket contract requirements and required event names for persisted artifact updates.
- [x] Confirm migration/backfill requirements for existing runs and existing Memory nodes.
- [x] Confirm delivery orchestration: sequential shared-baseline stages, then A/B/C/D fan-out stages, with explicit fan-out alert and prepared agent prompts.
- [ ] Confirm Stage 0 completeness and ask whether to proceed to Stage 1.

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
- [x] Inspector taxonomy: specialized nodes use curated-only inspector controls (hide irrelevant generic options).
- [x] Contract scope: deliver stable REST + socket contracts now for specialized artifact history with standardized error envelope and request/correlation IDs.
- [x] Migration/backfill: no historical backfill; begin artifact persistence from deployment forward.

## Stage 1 - Code Planning

- [ ] Blocked until Stage 0 is complete.
- [ ] Define Stage 2 through Stage X implementation stages from approved requirements.
- [ ] Ensure final two stages are `Automated Testing` and `Docs Updates`.
