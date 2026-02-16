# Skills Agent-Level Binding Plan

**Work checklist instructions**
- Check off each subtask as it is completed.
- Use `- [x]` for done and `- [ ]` for not done.
- Update this file in place as work progresses.
- Keep this plan aligned with `AGENTS.md` planning workflow requirements.

Goal: ensure all skill binding is Agent-scoped and enforced consistently across schema, runtime resolution, and UI/API. Nodes must not own skill bindings; nodes may only inherit skills from their resolved Agent.

## Decision log (captured on 2026-02-16)

- [x] Skills are assigned to Agents, not to nodes.
- [x] Node execution resolves skills from the selected/resolved Agent only.
- [x] Any existing node-level skill binding paths must be deprecated and removed or hard-disabled.
- [x] Skill assignment management belongs in Agent create/edit/detail surfaces.
- [x] For template/pipeline updates, treat as DB updates unless explicitly asked to update seed data.
- [x] Legacy node-level bindings are soft-deprecated first, then removed after cutover hardening.
- [x] Legacy migration mapping is deterministic:
  - [x] first `node.config.agent_id`
  - [x] then `task_template.agent_id`
  - [x] else archive as unmapped
- [x] Agent skill ordering is manual and stored via explicit position.
- [x] Nodes that resolve an Agent inherit that Agent's skills with no per-node opt-out.
- [x] Node `skill_ids` API compatibility uses a short transition window with warnings, then hard reject.

## Non-negotiable constraints

- [ ] Do not regress existing Agent task or flowchart node execution paths.
- [ ] Prevent node-level skill binding through both UI and backend validation.
- [ ] Preserve deterministic skill resolution order for Agent-bound skills.
- [ ] Ensure migration/backfill path for legacy node-bound skill data (if present).
- [ ] Keep runtime/audit metadata explicit so resolved Agent skills are traceable per run.

## Definition of done

- [ ] Data model supports Agent-level skill bindings as the only active binding model.
- [ ] All node-level skill-binding write paths are removed or rejected server-side.
- [ ] Runtime skill resolution for tasks and nodes uses Agent-bound skills only.
- [ ] Agent UI/API supports assigning, reordering, and removing skills.
- [ ] Legacy node-bound skill records are migrated or archived with no runtime ambiguity.
- [ ] Automated tests cover regressions, validation rules, and runtime resolution behavior.
- [ ] Sphinx and Read the Docs docs are updated to reflect Agent-only skill assignment.

## Stage 0 - Requirements Gathering

- [x] Capture baseline requirement from stakeholder request:
  - [x] "Assign skills to an Agent; do not bind skills at node level."
- [x] Interview and close requirement questions before implementation planning:
  - [x] Confirm whether node-level skill records should be hard-deleted or soft-deprecated.
  - [x] Confirm legacy data policy:
    - [x] migrate node-bound skills into owning Agent bindings where deterministic
    - [x] archive/unmapped records when ownership is ambiguous
  - [x] Confirm Agent skill ordering contract (manual order vs name/id sort).
  - [x] Confirm whether different node types may opt out of inherited Agent skills.
  - [x] Confirm API compatibility window for clients currently sending node-level skill payloads.
- [x] Gather current-state inventory:
  - [x] schema tables/columns for skill bindings
  - [x] runtime resolution callsites
  - [x] UI/API endpoints for node skill configuration

Deliverables:
- [x] Locked requirements and migration policy recorded in this file.
- [x] Open questions resolved and checked off.

### Stage 0 inventory findings (2026-02-16)

- Data model (current state):
  - Skills are currently node-bound through `flowchart_node_skills` with `position`.
  - `FlowchartNode.skills` and `Skill.flowchart_nodes` are wired as many-to-many.
  - There is no `agent_skill_bindings` table and no `Agent.skills` relationship.
  - Existing run snapshots persist resolved skill ids/versions/manifest on `flowchart_run_nodes`.
- Runtime (current state):
  - `_execute_flowchart_task_node` resolves skills via `resolve_flowchart_node_skills(session, node_id)`.
  - `resolve_flowchart_node_skills` loads from `FlowchartNode.skills` and orders by `flowchart_node_skills.position`.
  - Skill adapter materialization and fallback are driven from this node-resolved skill set.
- Web/UI/API (current state):
  - Flowchart payloads and serializers include `skill_ids` at the node level.
  - Node utility endpoints support attach/detach/reorder for `/flowcharts/<id>/nodes/<id>/skills`.
  - Flowchart editor UI exposes per-node skill selection/reordering in `flowchart_detail.html`.
  - Agent create/edit/detail surfaces currently manage role/priorities only (no skill assignment UI).
  - Skills pages describe and count bindings as flowchart-node bindings.

### Stage 0 closed requirement log (2026-02-16)

- [x] Node-level skill binding records are soft-deprecated first; destructive cleanup is deferred to post-cutover hardening.
- [x] Legacy node-bound skill migration policy is locked:
  - [x] map to Agent via `flowchart_node.config.agent_id` when present
  - [x] otherwise map via referenced `task_template.agent_id` when present
  - [x] otherwise archive as unmapped legacy binding
- [x] Agent skill ordering is user-controlled manual order (`position`), not name/id sorting.
- [x] Nodes with resolved Agent inherit skills from Agent with no node-level opt-out.
- [x] Compatibility window for incoming node `skill_ids` is short and explicit:
  - [x] transition phase accepts payload but logs warnings/deprecation signals
  - [x] enforcement phase rejects node `skill_ids` writes server-side

## Stage 1 - Code Planning

- [x] Define Stage 2 through Stage 6 implementation sequence with file-level touchpoints.
- [x] Define canonical resolution contract:
  - [x] Agent skills are sole source-of-truth
  - [x] node runtime path consumes resolved Agent skills only
  - [x] deterministic ordering rules
- [x] Define migration contract for legacy node-bound skill data.
- [x] Define API/UI deprecation strategy for node-level skill configuration paths.
- [x] Define observability/audit fields to persist resolved Agent skill snapshot per run.

Deliverables:
- [x] Finalized Stage 2-6 breakdown with acceptance criteria.
- [x] File-level architecture map and migration order.

### Stage 1 output (2026-02-16)

#### Stage 2-6 implementation sequence with file-level touchpoints

- Stage 2: Data model and migration
  - `app/llmctl-studio/src/core/models.py`
    - add `agent_skill_bindings` association table (`agent_id`, `skill_id`, `position`)
    - add `Agent.skills` relationship ordered by `agent_skill_bindings.position ASC, skill_id ASC`
    - add `Skill.agents` relationship
    - keep `flowchart_node_skills` and `FlowchartNode.skills` for soft-deprecation window (read-only migration source)
  - `app/llmctl-studio/src/core/db.py`
    - ensure `agent_skill_bindings` schema + indexes + additive column checks
    - add migration routine to backfill node-bound skills to agent-bound skills using locked mapping:
      - first `flowchart_nodes.config_json.agent_id`
      - then referenced `task_templates.agent_id`
      - else archive unmapped
    - add archive table for unmapped bindings (for example `legacy_unmapped_node_skills`) with reason + source snapshot
    - keep `flowchart_node_skills` table intact during transition
  - `app/llmctl-studio/scripts/` (new migration utility script)
    - add idempotent operational script for audit/re-run of migration if needed
  - Stage 2 acceptance criteria
    - agent-skill association is persistent and ordered
    - migration is deterministic and idempotent
    - unmapped legacy records are archived, not dropped

- Stage 3: Runtime resolution enforcement
  - `app/llmctl-studio/src/services/skill_adapters.py`
    - add agent-scoped resolver (`resolve_agent_skills(session, agent_id)`)
    - keep ordering contract: `position ASC`, tie-break `skill.name ASC` (or `skill_id ASC` where name missing)
    - keep adapter/materialization contract unchanged, only input source changes
  - `app/llmctl-studio/src/services/tasks.py`
    - `_execute_agent_task`: resolve skills from `task.agent_id` (when present), materialize/inject fallback with same adapter policy used for flowchart task nodes
    - `_execute_flowchart_task_node`: resolve skills from resolved Agent id, remove node-based resolver dependency
    - remove runtime dependency on `resolve_flowchart_node_skills(session, node_id)` for execution paths
    - persist resolved skill snapshots on both node run and task records
  - `app/llmctl-studio/src/core/models.py`
    - add `AgentTask` skill snapshot fields parallel to `FlowchartRunNode`:
      - `resolved_skill_ids_json`
      - `resolved_skill_versions_json`
      - `resolved_skill_manifest_hash`
      - `skill_adapter_mode`
  - `app/llmctl-studio/src/core/db.py`
    - additive `_ensure_columns` migration for new `agent_tasks` skill snapshot fields
  - Stage 3 acceptance criteria
    - runtime execution paths use Agent-bound skills only
    - no node-level skill resolver is required for task execution
    - run/task snapshots reflect resolved Agent skill set + adapter mode

- Stage 4: UI and API updates
  - `app/llmctl-studio/src/web/views.py`
    - add Agent skill management helpers/routes:
      - attach, detach, reorder Agent skills
    - remove node skill mutation from flowchart save/update routes
    - deprecate node skill endpoints (`/flowcharts/<id>/nodes/<id>/skills*`) per Stage 5 policy
    - update serializers/catalog payloads to stop advertising node-level `skill_ids` as editable utility
    - update skill detail/list binding counts from node bindings to agent bindings
  - `app/llmctl-studio/src/web/templates/agent_edit.html`
    - add Agent skill assignment/reorder UI (icon-only actions, ordered list/table)
  - `app/llmctl-studio/src/web/templates/agent_detail.html`
    - display resolved/assigned Agent skills
  - `app/llmctl-studio/src/web/templates/flowchart_detail.html`
    - remove node skill controls and inspector sections
  - `app/llmctl-studio/src/web/templates/skills.html`
    - update copy and bindings column semantics to Agent bindings
  - `app/llmctl-studio/src/web/templates/skill_detail.html`
    - replace "Flowchart Node Bindings" with "Agent Bindings"
  - Stage 4 acceptance criteria
    - all skill assignment UX is Agent-scoped
    - node skill controls are absent from flowchart UI
    - backend rejects or deprecates node-level writes consistently

- Stage 5: Compatibility, rollout, and safeguards
  - `app/llmctl-studio/src/services/integrations.py`
    - add settings helper for node-skill payload mode (`warn` -> `reject`)
  - `app/llmctl-studio/src/web/views.py`
    - enforce transition mode behavior in flowchart endpoints:
      - `warn`: accept request shape but ignore node `skill_ids` writes and emit deprecation warnings
      - `reject`: return validation errors for node `skill_ids` writes
    - add structured logging/event hooks for deprecated payload usage
  - `app/llmctl-studio/src/web/templates/settings_runtime.html`
    - add runtime flag control for compatibility mode cutover (short transition window)
  - Stage 5 acceptance criteria
    - deprecated payload usage is visible in logs/telemetry
    - reject mode cleanly blocks node skill writes without ambiguity

- Stage 6: Automated testing
  - `app/llmctl-studio/tests/test_skills_stage3.py`
    - resolver ordering + Agent-scoped resolution tests
  - `app/llmctl-studio/tests/test_skills_stage4.py`
    - runtime materialization/fallback tests using Agent-bound skills
  - `app/llmctl-studio/tests/test_skills_stage5.py`
    - Agent skill web/API CRUD + reorder; node endpoint deprecation/reject behavior
  - `app/llmctl-studio/tests/test_skills_stage6.py`
    - migration idempotency + unmapped archive behavior + no cross-run skill bleed
  - `app/llmctl-studio/tests/test_flowchart_stage9.py`
    - flowchart utilities contract updated for no node skill editing path
  - `app/llmctl-studio/tests/test_agent_role_markdown_stage4.py`
    - ensure agent task + flowchart task instruction path coexists with Agent skill snapshots
  - Stage 6 acceptance criteria
    - regression suite passes with Agent-only binding semantics
    - legacy node payload behavior is explicitly covered in both transition and reject modes

#### Canonical resolution contract (locked)

- Source of truth is `agent_skill_bindings` only.
- Runtime skill resolution uses resolved Agent id:
  - autorun/task path: `AgentTask.agent_id`
  - flowchart task node path: resolved agent from node config/template logic
- No resolved Agent id means no skill set materialization.
- Ordering contract:
  - primary: `agent_skill_bindings.position ASC`
  - tie-break: deterministic stable key (skill name, then id)
- Archived skills cannot be newly assigned; existing archived assignments remain readable for audit until removed.

#### Migration contract (locked)

- Migration is additive and idempotent.
- Legacy mapping algorithm:
  - attempt owner Agent via `flowchart_nodes.config_json.agent_id`
  - fallback to `task_templates.agent_id` when node references a template
  - if neither yields an Agent, archive as unmapped
- Deduplicate target bindings by `(agent_id, skill_id)` and retain earliest deterministic position.
- During transition, `flowchart_node_skills` remains present as legacy source data and rollback fallback.

#### API/UI deprecation strategy (locked)

- Node-level write APIs are deprecated first, then hard-rejected.
- Transition mode (`warn`):
  - incoming node `skill_ids` payloads are ignored for persistence
  - response includes deprecation warning metadata
  - server logs structured deprecation events
- Enforcement mode (`reject`):
  - node `skill_ids` payloads fail validation with clear error
  - `/flowcharts/<id>/nodes/<id>/skills*` endpoints return explicit deprecation errors
- Agent endpoints become the only writable skill binding surface.

#### Observability and audit contract (locked)

- Persist resolved Agent skill snapshots on:
  - `flowchart_run_nodes` (existing fields, now Agent-derived)
  - `agent_tasks` (new parallel fields for non-flowchart task runs)
- Persist adapter mode (`native|fallback`) with resolved skill snapshot.
- Emit structured runtime logs:
  - resolved skill ids/count
  - resolver source (`agent`)
  - compatibility-mode warnings for deprecated node payloads

#### Migration ordering (locked)

- 1. Add new schema (`agent_skill_bindings`, archive table, `agent_tasks` snapshot columns).
- 2. Backfill legacy node bindings into Agent bindings and archive unmapped rows.
- 3. Switch runtime resolution to Agent bindings.
- 4. Cut UI/API write paths to Agent-only surfaces.
- 5. Run transition mode (`warn`) briefly, then move to enforcement mode (`reject`).
- 6. Complete Stage 6 automated tests.
- 7. Complete Stage 7 docs updates.

## Stage 2 - Data Model and Migration

- [x] Add/confirm `agent_skill_bindings` schema and constraints.
- [x] Add uniqueness/order constraints for Agent skill assignment.
- [x] Implement migration for legacy node-bound skill records.
- [x] Add DB guards preventing new node-level skill bindings.
- [x] Backfill metadata for migrated bindings (source, timestamp, notes).

Deliverables:
- [x] Agent-only binding schema active.
- [x] Legacy node-binding data migration completed with audit trail.

### Stage 2 execution log (2026-02-16)

- Added Agent-level binding model/table support:
  - `agent_skill_bindings` association table in `core/models.py`
  - `Agent.skills` and `Skill.agents` relationships with ordered binding position
- Implemented additive DB schema + indexes:
  - `agent_skill_bindings` table + indexes
  - `legacy_unmapped_node_skills` archive table + indexes
- Implemented deterministic idempotent migration in `core/db.py`:
  - source rows from `flowchart_node_skills`
  - mapping order: `node.config.agent_id` -> `task_templates.agent_id` -> archive unmapped
  - dedupe target `(agent_id, skill_id)` and assign stable incremental `position`
- Added DB-level guard mechanism for deprecation enforcement mode:
  - SQLite triggers block `flowchart_node_skills` INSERT/UPDATE only when
    `integration_settings(provider='llm', key='node_skill_binding_mode') == 'reject'`
  - default behavior remains non-blocking for transition window
- Added operational migration utility script:
  - `app/llmctl-studio/scripts/backfill_agent_skill_bindings.py`

## Stage 3 - Runtime Resolution Enforcement

- [x] Update task runtime to resolve skills from Agent bindings only.
- [x] Update flowchart/node runtime to inherit resolved Agent skills only.
- [x] Remove/disable node-level skill resolution branches.
- [x] Persist run snapshot fields for resolved Agent skill ids/order.
- [x] Add warning/error logging when legacy node-skill payloads are encountered.

Deliverables:
- [x] Runtime enforces Agent-only skill resolution for all execution modes.

### Stage 3 execution log (2026-02-16)

- Added `resolve_agent_skills(session, agent_id)` in `services/skill_adapters.py` with deterministic ordering (`position`, then name/id tie-break).
- Updated `_execute_agent_task` in `services/tasks.py` to:
  - resolve skills from `task.agent_id`
  - materialize/inject skill fallback via existing adapter path
  - persist `resolved_skill_ids_json`, `resolved_skill_versions_json`, `resolved_skill_manifest_hash`, and `skill_adapter_mode` on `agent_tasks`.
- Updated `_execute_flowchart_task_node` in `services/tasks.py` to:
  - resolve skills from resolved Agent (`config.agent_id` or template agent) only
  - stop using node-level skill resolution for execution
  - log warnings when legacy node `skill_ids` payloads or `flowchart_node_skills` bindings are encountered.
- Extended flowchart node task synchronization to persist resolved skill snapshot fields onto associated `agent_tasks`.
- Added `AgentTask` model fields + DB additive migration columns for task-level skill snapshots in `core/models.py` and `core/db.py`.
- Updated Stage 3/4 runtime tests to agent-bound skill fixtures and added Stage 3 assertions for:
  - agent resolver ordering
  - legacy node-skill warning behavior
  - agent task snapshot persistence.

## Stage 4 - UI and API Updates

- [x] Update Agent detail/edit pages to manage skill assignments and order.
- [x] Remove node-level skill assignment controls from node-related templates/views.
- [x] Update backend request validation to reject node-level skill binding payloads.
- [x] Update list/detail views to show resolved Agent skills where relevant.
- [x] Ensure row/detail navigation remains consistent with list-view conventions.

Deliverables:
- [x] UI/API expose Agent-level skill management only.
- [x] Node-level binding writes are blocked with clear validation errors.

### Stage 4 execution log (2026-02-16)

- Added Agent-level skill management routes in `web/views.py`:
  - attach (`POST /agents/<agent_id>/skills`)
  - detach (`POST /agents/<agent_id>/skills/<skill_id>/delete`)
  - reorder (`POST /agents/<agent_id>/skills/<skill_id>/move`)
- Updated Agent detail/edit pages to show ordered Agent skill bindings and manage ordering/removal through icon-only actions:
  - `web/templates/agent_detail.html`
  - `web/templates/agent_edit.html`
  - `web/templates/agent_detail_layout.html`
- Removed node-level skill editing from flowchart editor payload and inspector UI:
  - removed `skill_ids` handling from `web/templates/flowchart_detail.html`
  - removed `skill_ids` from serialized flowchart node payloads in `web/views.py`
- Enforced backend rejection for node-level skill writes:
  - `/flowcharts/<id>/nodes/<id>/skills*` endpoints now return explicit deprecation validation errors.
  - `/flowcharts/<id>/graph` rejects incoming node `skill_ids` payloads with clear validation messages.
- Updated Skills list/detail surfaces to reflect Agent bindings:
  - `web/templates/skills.html` copy/column semantics updated to Agent bindings.
  - `web/templates/skill_detail.html` now shows Agent bindings.
  - `web/views.py` now computes binding counts/detail relationships from `Skill.agents`.

## Stage 5 - Compatibility, Rollout, and Safeguards

- [ ] Add compatibility handling for stale clients sending node-level skill payloads.
- [ ] Add feature flag or guarded rollout path if needed for incremental deployment.
- [ ] Add operational metrics/logging for rejected node-level skill writes.
- [ ] Document rollback approach if migration uncovers ambiguous ownership.

Deliverables:
- [ ] Controlled rollout with observable enforcement signals.

## Stage 6 - Automated Testing

- [ ] Unit tests:
  - [ ] Agent binding CRUD + ordering constraints
  - [ ] validation rejects node-level binding payloads
  - [ ] runtime resolver returns Agent-bound skills only
- [ ] Integration tests:
  - [ ] Agent task execution uses Agent skills
  - [ ] flowchart node execution inherits Agent skills
  - [ ] legacy migration path produces deterministic results
- [ ] Regression tests for previously working task/node flows.

Deliverables:
- [ ] Test suite passing with Agent-only skill binding guarantees.

## Stage 7 - Docs Updates

- [ ] Update Sphinx docs for skill architecture and assignment workflow.
- [ ] Update Read the Docs pages describing Agent and node configuration.
- [ ] Update internal planning/docs index entries if new docs are added.
- [ ] Add migration/operator notes for environments with legacy node-bound skills.

Deliverables:
- [ ] Documentation reflects Agent-only skill binding model and migration behavior.
