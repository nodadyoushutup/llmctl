# Specialized Node History And Inspector Plan

Goal: design and implement durable, queryable run history plus specialized inspector behavior for `Memory`, `Plan`, `Milestone`, and `Decision` nodes, including MCP defaults, prebaked action prompts, and detail views that expose node-specific historical artifacts.

## Stage 0 - Requirements Gathering

- [ ] Run Stage 0 interview one question per turn with explicit options.
- [ ] Confirm data retention scope for node artifacts (what is persisted per node type, and how long).
- [ ] Confirm canonical database model and ownership links (`flowchart`, `node`, `run`, `variant`, `artifact`).
- [ ] Confirm UX scope for `Workflow > Memories` detail view and artifact history browsing.
- [ ] Confirm required Memory node inspector controls (locked MCP server, action selector, additive prompt behavior).
- [ ] Confirm behavior when Memory node prompt is empty (best-effort add/retrieve from incoming context).
- [ ] Confirm Plan node inspector controls and execution semantics (including stage/task completion behavior).
- [ ] Confirm Milestone and Decision node inspector controls, action options, and output storage behavior.
- [ ] Confirm selector-option taxonomy and whether to hide/disable generic options for specialized nodes.
- [ ] Confirm API/socket contract requirements and required event names for persisted artifact updates.
- [ ] Confirm migration/backfill requirements for existing runs and existing Memory nodes.
- [ ] Confirm Stage 0 completeness and ask whether to proceed to Stage 1.

## Stage 0 - Interview Notes

- [ ] Pending interview responses.

## Stage 1 - Code Planning

- [ ] Blocked until Stage 0 is complete.
- [ ] Define Stage 2 through Stage X implementation stages from approved requirements.
- [ ] Ensure final two stages are `Automated Testing` and `Docs Updates`.
