# Flowchart Connector Execution Semantics Plan

**Work checklist instructions**
- Check off each subtask as it is completed.
- Use `- [x]` for done and `- [ ]` for not done.
- Update this file in-place as implementation progresses.
- Keep scope focused on Studio flowchart editor/runtime unless explicitly expanded.

Goal: replace the current limited outgoing-connector model with explicit connector behavior modes so connectors can either trigger execution (`Solid`) or provide pull-only context (`Dotted`).

## Problem and target behavior

Current behavior (to replace):
- [ ] Most nodes are limited to a single outgoing edge.
- [ ] Edge semantics are mostly execution-routing only.
- [ ] Runtime treats each run as a tightly chained traversal.

Target behavior (proposal):
- [ ] Unlimited outgoing edges for all non-End nodes (Decision rules still explicitly defined below).
- [ ] Edge mode is set in edge inspector.
- [ ] Connector direction contract:
  - [ ] Arrow direction is always `source -> target` for both solid and dotted edges.
  - [ ] Dotted source->target means "target may pull source context when target executes".
  - [ ] Do not describe dotted behavior as push in UI/docs; use "pull-only context dependency".
- [ ] `Solid` edge:
  - [ ] passes output/context to target node.
  - [ ] triggers target node execution.
- [ ] `Dotted` edge:
  - [ ] does not trigger target node execution.
  - [ ] exposes source output/context as pullable input when target node executes via another trigger.
- [ ] No color-coded connector semantics in v1 (line style + inspector labels only).
- [ ] Runtime is treated as event-driven branching from trigger points, not only a single linear chain.
- [ ] Running nodes remain visibly highlighted in the UI.

## Key decisions to lock before implementation

- [x] Confirm semantic source of truth fields:
  - [x] `edge_mode` enum in DB/API (`solid`, `dotted`).
  - [x] Rendering style derived from `edge_mode`.
  - [x] Direction semantics are shared across modes (`source -> target`).
  - [x] No color-only semantic encoding in v1.
- [x] Confirm migration behavior:
  - [x] Existing edges default to `solid`.
  - [x] No behavior change for existing graphs until users opt into `dotted`.
- [x] Confirm trigger policy when multiple `solid` edges converge on one target:
  - [x] Queue one execution per trigger event.
  - [ ] Or dedupe/coalesce triggers in-flight.
- [x] Confirm dotted-input readiness policy:
  - [x] Dotted sources are optional; missing source output is ignored.
  - [x] When a dotted source has not executed yet in the current run, target receives no payload from that source.
  - [ ] Or dotted sources are required; node blocks/fails until all dotted sources have outputs.
- [x] Confirm snapshot semantics for dotted pull:
  - [x] Pull latest successful output from each dotted source in current flowchart run.
  - [ ] Or pull only outputs causally tied to the triggering branch/token.
- [x] Confirm Decision node rule set:
  - [x] Keep `condition_key` routing only for `solid` edges from Decision nodes (recommended).
  - [x] Dotted edges from Decision nodes allowed but ignored for route matching.
- [x] Confirm run-history UX expectations:
  - [x] Node run detail should show trigger edge(s) vs pulled dotted context edges.

## Stage 0 - Spec lock and acceptance criteria

- [x] Write a short technical spec section (in this file or linked doc) with:
  - [x] event model (`solid` = trigger + context, `dotted` = context-only).
  - [x] deterministic ordering guarantees for queued triggers.
  - [x] failure behavior when pulled dotted context is unavailable/invalid.
  - [x] connector-direction wording and glossary (`source -> target`, "pull-only dependency").
- [x] Define acceptance criteria:
  - [x] fan-out: one node can trigger N downstream nodes via `solid`.
  - [x] fan-in context: one node can read M dotted sources without those sources triggering it.
  - [x] existing flowcharts run unchanged after migration.
  - [x] no deadlocks/starvation introduced by mixed `solid`/`dotted` graphs.

Deliverables:
- [x] Finalized behavior contract for edge modes.
- [x] Explicit non-goals list for v1 of this change.

### Stage 0 technical spec (locked 2026-02-16)

Event model:
- `solid` edge: carries source output/context and enqueues one target execution event.
- `dotted` edge: never enqueues execution; target may pull source context only when target is executed by another trigger.

Deterministic ordering guarantees:
- Outgoing edges are evaluated in stable `edge.id` ascending order.
- Trigger events are appended to a FIFO activation queue in that same order.
- Fan-in matching consumes one token per required solid parent in sorted `parent_node_id` order; per-parent token consumption is FIFO.
- No trigger dedupe/coalescing in v1: each solid trigger event queues one execution event.

Failure behavior for dotted pulls:
- If a dotted source has no successful output yet in the current run, that source contributes no payload.
- If a dotted source payload is unavailable/invalid at read time, drop that source payload, record diagnostics in run history, and continue execution with partial context.
- Only latest successful outputs are eligible dotted snapshots.

Connector direction glossary:
- `source -> target`: source node produces output; target node consumes output/context.
- `solid`: trigger + context.
- `dotted`: pull-only context dependency.
- UI/docs wording must avoid "push" phrasing for dotted edges.

### Stage 0 acceptance criteria (locked)

- Fan-out: any non-End node can trigger N downstream nodes via `solid` edges.
- Fan-in pull context: a node can consume M dotted sources without those sources triggering execution.
- Migration compatibility: existing flowcharts behave unchanged after migration because all pre-existing edges map to `solid`.
- Liveness: mixed `solid`/`dotted` graphs do not introduce deadlocks or starvation from dotted dependencies.

### Stage 0 explicit non-goals (v1)

- No trigger dedupe/coalescing across repeated solid trigger events.
- No causal branch-token pinning for dotted reads; dotted uses latest successful source output in the run.
- No dotted "required input" mode that blocks execution when dotted sources are missing.
- No color-only encoding for connector behavior semantics.
- No ordering guarantees based on canvas geometry; ordering is runtime queue + edge identity based.

## Stage 1 - Data model and migration

- [x] Add `edge_mode` column to `flowchart_edges`:
  - [x] type: `VARCHAR(16)` or equivalent.
  - [x] default: `"solid"`.
  - [x] non-null constraint.
- [x] Update ORM model:
  - [x] add `FlowchartEdge.edge_mode`.
  - [x] ensure serialization includes `edge_mode`.
- [x] Add DB migration/bootstrap logic:
  - [x] backfill existing rows to `solid`.
  - [x] safe for existing deployments.
- [x] Update graph import/export and API payload validation:
  - [x] accept only `solid|dotted`.
  - [x] normalize invalid/missing values to hard validation errors.

Deliverables:
- [x] Schema + model + serializer support landed.
- [x] Existing flowcharts load with `edge_mode=solid`.

## Stage 2 - Graph validation and backend rules

- [x] Remove legacy default outgoing-edge limit for non-End nodes.
- [x] Keep End node `0` outgoing edges rule.
- [x] Remove Decision node max-outgoing cap.
- [x] Keep Decision semantics focused on route selection, not fan-out limits.
- [x] Update graph validator to treat `condition_key` constraints as `solid` routing semantics.
- [x] Reject redundant duplicate semantic edges for same source->target pair:
  - [x] if a `solid` edge exists from source->target, disallow additional `dotted` edge source->target.
- [x] Validate that disconnected-node detection still works with dotted edges.
- [x] Add explicit validation error messages for mixed-mode misconfigurations.

Deliverables:
- [x] Validation reflects new semantics without breaking current graphs.

## Stage 3 - Flowchart editor (UI/UX)

- [x] Edge inspector updates:
  - [x] add `Connection mode` control with `Solid` / `Dotted`.
  - [x] preserve existing `condition_key` + `label` controls with rule-aware hints.
- [x] Edge rendering updates:
  - [x] solid line for `solid`.
  - [x] dotted/dashed line for `dotted`.
  - [x] keep directional arrowheads on target side for both modes.
  - [x] avoid color as behavior encoding in v1.
  - [x] maintain selection/hitbox/accessibility behavior.
- [x] Edge creation defaults:
  - [x] new edges default to `solid`.
  - [x] decision-edge auto-`condition_key` behavior only for `solid`.
- [x] Remove UI-level outgoing-edge hard stop for non-End nodes.
- [x] Add inline helper text in inspector explaining trigger vs pull-only semantics.
- [x] Add terminology guardrail in UI copy:
  - [x] avoid "push" phrasing for dotted edges; use "pull-only context dependency".

Deliverables:
- [x] Users can set and see connector mode directly in inspector/canvas.

## Stage 4 - Runtime scheduling and context assembly

- [x] Split runtime edge handling into:
  - [x] trigger edges (`solid`) for queueing target execution.
  - [x] context edges (`solid` + `dotted`) for input-context assembly.
- [x] Update activation pipeline:
  - [x] only `solid` edges enqueue downstream executions.
  - [x] `dotted` edges never enqueue executions.
- [x] Update input context builder:
  - [x] include pulled data from dotted sources according to locked snapshot/readiness policy.
  - [x] preserve current upstream context contract for solid-triggered payloads.
- [x] Rework parent-token gating logic:
  - [x] avoid deadlocks from waiting on dotted parents that should not gate execution.
  - [x] keep deterministic behavior for solid fan-in.
- [x] Ensure guardrails still apply:
  - [x] `max_node_executions`
  - [x] `max_runtime_minutes`
  - [x] `max_parallel_nodes`
  - [x] hard safety limit.

Deliverables:
- [x] Runtime supports event-style fan-out plus pull-only fan-in context.

## Stage 5 - Run history, observability, and debugging

- [x] Extend node-run metadata to improve traceability:
  - [x] trigger source edge/node info.
  - [x] pulled dotted-source snapshots used at execution time.
- [x] Update run detail UI/API to distinguish:
  - [x] triggered-by-solid events.
  - [x] pulled-from-dotted context sources.
- [x] Add logs around edge-mode routing decisions and context pulls.

Deliverables:
- [x] Operators can explain why a node ran and what dotted context it consumed.

## Stage 6 - Tests and regressions

- [x] Unit tests:
  - [x] validator rules for `edge_mode`.
  - [x] validator rejects redundant solid+dotted same source->target pair.
  - [x] route resolution for decision + solid edges.
  - [x] dotted context pull assembly.
- [x] Integration tests:
  - [x] fan-out (1 -> N solid).
  - [x] fan-in pull-only (A dotted + B dotted -> C triggered by D solid).
  - [x] mixed loops with guardrails.
  - [x] migration compatibility for existing graphs.
- [x] UI tests:
  - [x] edge inspector mode toggle persistence.
  - [x] visual style changes for selected/unselected edges.
  - [x] graph save/load roundtrip with edge modes.

Deliverables:
- [x] Test coverage proves semantic correctness and backward compatibility.

## Stage 7 - Rollout and documentation

- [x] Update flowchart user docs:
  - [x] edge mode definitions.
  - [x] examples for branching and shared context.
  - [x] anti-patterns (unbounded fan-out, accidental loops).
- [x] Add release note/migration note:
  - [x] existing edges default to `solid`.
  - [x] no required manual migration for current flowcharts.
- [x] Optional feature flag rollout (if desired):
  - [x] enable in non-prod first.
  - [x] validate representative flowcharts before full rollout.

Deliverables:
- [x] Documentation and rollout notes are complete.

## Open questions (must answer before Stage 2+)

- [x] Target executes once per solid trigger event; coalescing/dedupe is deferred.
- [x] If dotted sources have no output yet, continue with partial context (no block/fail).
- [x] For repeated source executions, dotted pull uses latest successful output globally in the run.
- [x] Decision max-outgoing cap is removed.
- [x] Edge visuals and semantics stay coupled in v1 (`solid` trigger+context, `dotted` pull-only context).

## Risks and mitigations

- [ ] Risk: queue explosion from large solid fan-out.
  - [ ] Mitigation: preserve guardrails and add queue-depth monitoring.
- [ ] Risk: nondeterministic behavior in concurrent fan-in.
  - [x] Mitigation: define deterministic ordering and snapshot policy in Stage 0.
- [ ] Risk: silent missing-context bugs from dotted pulls.
  - [ ] Mitigation: explicit missing-source policy + run-time diagnostics in node-run records.
- [ ] Risk: regression for existing decision routing.
  - [ ] Mitigation: migration defaults + targeted decision-node regression tests.
