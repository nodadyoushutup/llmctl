# Skills System Migration Plan

**Work checklist instructions**
- Check off each subtask as it is completed.
- Use `- [x]` for done and `- [ ]` for not done.
- Update this file in-place as work progresses.

Goal: replace legacy `Skill Script` prompt-injection behavior with a first-class Skills system that supports add/install/attach workflows and maps to provider-native skills behavior (Codex, Claude Code, Gemini CLI).

## Why this migration

Current state in runtime and docs:
- [ ] `SCRIPT_TYPE_SKILL` is modeled as a script type in `app/llmctl-studio/src/core/models.py`.
- [ ] Skills are currently staged as script files and injected into prompts via `_inject_script_map` in `app/llmctl-studio/src/services/tasks.py`.
- [ ] Docs state that skill scripts are not executed, only exposed in prompt payloads (`docs/task-types/README.md`).

Target state:
- [ ] Skills are first-class records/packages, separate from stage scripts.
- [ ] Skills can be added from UI/API, attached to nodes/tasks/agents (as chosen), and resolved per run.
- [ ] Provider adapters materialize selected skills into provider-native directories/layouts.
- [ ] Non-native providers fall back to deterministic prompt/context injection generated from the same skill package.
- [ ] Legacy Skill Script runtime path is removed (one-time migration only, no ongoing compatibility mode).

## Principles

- [ ] Single canonical skill format internally (portable package, not provider-specific storage).
- [ ] Separate concerns:
  - [ ] Stage scripts handle deterministic execution hooks.
  - [ ] Skills handle reusable guidance/workflows/resources for the model.
- [ ] Provider compatibility via adapters, not duplicated skill content.
- [ ] DB is source of truth; generated workspace files are ephemeral runtime projections.
- [ ] Hard-cut migration: import legacy data once, then delete legacy execution/injection paths.
- [ ] Concurrent-run safety is a hard requirement, not best effort.

## Execution isolation contract (must hold before GA)

- [ ] Skills are resolved and snapshotted per node run, then treated as immutable for that run.
- [ ] Every node run gets a unique runtime root directory (workspace + generated skill files).
- [ ] Provider config homes are run-scoped (no shared mutable user/global home usage during execution).
- [ ] Runtime must never write skill state into shared global config paths.
- [ ] Cleanup routines remove run-local skill materialization after execution.
- [ ] Concurrency target: no skill/config cross-contamination with at least 100 simultaneous runs.

## Skill package contract (canonical)

- [ ] Required metadata:
  - [ ] `name` (stable slug/id)
  - [ ] `display_name`
  - [ ] `description` (trigger/use guidance)
  - [ ] `version`
  - [ ] `status` (`draft`, `active`, `archived`)
- [ ] Required content:
  - [ ] `SKILL.md` body
- [ ] Optional resources:
  - [ ] `scripts/*`
  - [ ] `references/*`
  - [ ] `assets/*`
- [ ] Optional compatibility metadata:
  - [ ] provider hints/capabilities (`codex`, `claude_code`, `gemini_cli`)
  - [ ] install strategy (`materialize`, `link`, `prompt_fallback`)

## Stage 0 - Product decisions and scope lock

- [ ] Confirm attachment model for v1:
  - [x] node-level skills only.
  - [ ] task template + node override, or
  - [ ] agent + node merge.
- [ ] Decide binding granularity:
  - [ ] bindings defined on reusable entities (node/task/agent), then snapshotted per run.
  - [ ] avoid manual per-run skill assignment except explicit override APIs.
- [ ] Confirm precedence/merge order:
  - [ ] system default skills
  - [ ] workspace/project skills
  - [ ] entity-attached skills.
- [ ] Confirm context-budget policy for skills:
  - [ ] max SKILL.md size
  - [ ] lazy-load references/assets
  - [ ] hard caps for injected fallback text.
- [ ] Confirm run isolation policy:
  - [ ] per-run workspace naming convention (`run-<flowchart_run_node_id>-<token>`).
  - [ ] per-run provider home env vars (`HOME`, `CODEX_HOME`, provider-specific dirs).
  - [ ] global settings are read-only during task execution.
- [ ] Confirm runtime mode:
  - [ ] process-isolated mode is v1 default.
  - [ ] optional containerized node executor deferred to v1.x unless explicitly pulled in.
- [ ] Confirm conflict behavior:
  - [ ] duplicate skill slug/version handling
  - [ ] deterministic order rules.
- [ ] Confirm initial provider targets for native support:
  - [ ] Codex
  - [ ] Claude Code
  - [ ] Gemini CLI
- [ ] Define GA success criteria (see Acceptance Criteria section).

Deliverables:
- [ ] Finalized architecture decision record in `docs/`.
- [ ] Published v1 scope with explicit non-goals.

## Stage 1 - Data model migration

- [x] Add first-class skill tables/models:
  - [x] `skills` (metadata)
  - [x] `skill_versions` (immutable content snapshots)
  - [x] `skill_files` (path + content/blob + checksum)
- [x] Add attachment tables (based on v1 scope decision):
  - [x] `node_skills` (ordered many-to-many)
- [x] Add provenance fields:
  - [x] `source_type` (`ui`, `seed`, `import`, `sync`)
  - [x] `source_ref`
  - [x] `created_by`/`updated_by` if available.
- [x] Add one-time legacy importer for `script_type=skill` records (migration only, not runtime).
- [x] Add migration to backfill legacy skill scripts into `skills` records.
- [x] Add node-run snapshot fields for resolved skills:
  - [x] resolved skill ids/versions
  - [x] resolved manifest hash
  - [x] adapter mode used (`native`/`fallback`).

Deliverables:
- [x] ORM updates in `app/llmctl-studio/src/core/models.py`.
- [x] DB migration logic in `app/llmctl-studio/src/core/db.py`.
- [x] Backfill command/script in `app/llmctl-studio/scripts/`.

## Stage 2 - Skill packaging and validation layer

- [ ] Create a skill package service:
  - [ ] parse/validate `SKILL.md`
  - [ ] validate allowed file tree (`scripts`, `references`, `assets`)
  - [ ] compute checksums and normalized manifests
  - [ ] enforce size limits and path safety.
- [ ] Add import/export format for skills:
  - [ ] tar/zip or JSON bundle
  - [ ] deterministic manifest for reproducible installs.
- [ ] Add static validation errors surfaced in UI/API.
- [ ] Add server-side normalization for names/slugs/versions.

Deliverables:
- [ ] `services/skills.py` (or equivalent) with unit tests.
- [ ] CLI/admin scripts for validate/import/export.

## Stage 3 - Provider adapter runtime

- [ ] Add provider-agnostic resolver:
  - [ ] compute effective skill set for each run
  - [ ] merge and order skills deterministically
  - [ ] select adapter by provider/runtime.
- [ ] Add run-local materialization contract:
  - [ ] materialize skills under run-local workspace only.
  - [ ] no shared mutable provider skill dirs during execution.
  - [ ] enforce read-only mount/copy semantics for source skill artifacts.
- [ ] Implement adapters:
  - [ ] Codex adapter: materialize/link skills in Codex-recognized location.
  - [ ] Claude Code adapter: materialize/link skills in Claude-recognized location.
  - [ ] Gemini CLI adapter: materialize/link skills in Gemini-recognized location.
- [ ] Add provider env/home isolation:
  - [ ] Codex: run-specific `CODEX_HOME`.
  - [ ] Gemini: force project/run scope; do not mutate user scope.
  - [ ] Claude: run-specific home/config paths when required by CLI behavior.
- [ ] Add fallback adapter:
  - [ ] build compact prompt/context injection when native skills are unavailable.
- [ ] Add run logging:
  - [ ] list resolved skills
  - [ ] list adapter mode (`native`, `fallback`)
  - [ ] list materialized paths.

Deliverables:
- [ ] Adapter interface and implementations in `app/llmctl-studio/src/services/tasks.py` and/or new `services/skill_adapters/`.
- [ ] Integration tests per provider mode.

## Stage 4 - Execution pipeline cutover

- [ ] Remove `_inject_script_map` dependence for skills in normal path.
- [ ] Ensure stage scripts (`pre_init`, `init`, `post_init`, `post_run`) continue unchanged.
- [ ] Ensure skill resources can still be referenced from workspace (read-only copy/link policy).
- [ ] Persist resolved-skill metadata on task/node run records for audit/debug.
- [ ] Enforce no-global-mutation execution path:
  - [ ] all provider setup commands run with run-local env/home.
  - [ ] remove any codepaths that write user-scoped settings during task execution.
- [ ] Add robust failure behavior:
  - [ ] fail-fast on invalid required skills
  - [ ] optional downgrade to fallback mode by policy.

Deliverables:
- [ ] Updated task execution flow in `app/llmctl-studio/src/services/tasks.py`.
- [ ] Updated task payload docs in `docs/task-types/README.md`.

## Stage 5 - UI and MCP/API surface

- [ ] Add Skills list/detail/create/edit/delete screens.
- [ ] Add attach/detach/reorder UX on selected entity pages (node/task/agent based on v1 scope).
- [ ] Add install/import workflow:
  - [ ] upload bundle
  - [ ] from local path
  - [ ] from git source (optional v1.1).
- [ ] Add validation preview (manifest + warnings + compatibility hints).
- [ ] Add MCP/API tools for skill management:
  - [ ] list skills
  - [ ] get skill detail/version
  - [ ] create/update/archive skill
  - [ ] attach/detach skill.

Deliverables:
- [ ] Routes and handlers in `app/llmctl-studio/src/web/views.py`.
- [ ] Templates under `app/llmctl-studio/src/web/templates/`.
- [ ] MCP tool additions in `app/llmctl-mcp/src/tools.py`.

## Stage 6 - Backfill and rollout

- [ ] Build and run backfill:
  - [ ] migrate each legacy `script_type=skill` into a new skill package.
  - [ ] auto-generate minimal `SKILL.md` when only script content exists.
  - [ ] map existing task/agent references to new attachments.
- [ ] Cutover rollout:
  - [ ] enable new Skills system path
  - [ ] immediately disable legacy Skill Script path
  - [ ] block new legacy `script_type=skill` writes at API/model layer.
- [ ] Verification period (new path only):
  - [ ] validate resolved skills for representative runs
  - [ ] validate provider adapter materialization/fallback logging.
  - [ ] run concurrency stress test (100 simultaneous runs) and confirm zero skill bleed.

Deliverables:
- [ ] Backfill report with counts and mismatch summary.
- [ ] Rollout runbook with emergency data rollback steps (not legacy runtime re-enable).

## Stage 7 - Hard cut cleanup

- [ ] Remove `SCRIPT_TYPE_SKILL` from model constants and UI labels.
- [ ] Delete legacy `_inject_script_map` skill-specific path.
- [ ] Remove old seed assumptions that refer to "Skill Script" terminology.
- [ ] Update docs and prompts to use only "Skills" terminology.

Deliverables:
- [ ] No runtime references to "Skill Script" remain.
- [ ] No user-facing labels mention "Skill Script".

## Testing plan

- [ ] Unit tests:
  - [ ] skill validation/parsing
  - [ ] manifest and checksum generation
  - [ ] resolver merge/precedence logic
  - [ ] adapter path generation and fallback.
  - [ ] run-local path generation and env/home isolation.
- [ ] Integration tests:
  - [ ] run with native skills mode for each provider adapter
  - [ ] run with fallback mode
  - [ ] migration backfill + attachment mapping.
  - [ ] concurrent execution test with overlapping skill names across runs.
- [ ] UI tests:
  - [ ] create/import/edit/archive skill
  - [ ] attach/detach/reorder
  - [ ] detail view file browser.
- [ ] Regression tests:
  - [ ] stage script execution unchanged
  - [ ] MCP integration unchanged
  - [ ] flowchart node execution behavior unchanged except skills loading.

## Acceptance criteria

- [ ] Users can create/import skills and attach them without using Script records.
- [ ] Skills resolve deterministically and are visible in run logs.
- [ ] Codex/Claude/Gemini targeted runtimes use native adapter paths where supported.
- [ ] Non-native runtimes receive deterministic fallback behavior.
- [ ] Legacy Skill Script path and writes are removed with no regressions.
- [ ] 100 parallel runs with disjoint skill sets complete with zero cross-run skill/config contamination.
- [ ] Documentation is updated and internally consistent.

## Open questions

- [ ] Should skills be version-pinned per node/task, or always latest active version?
- [ ] Do we allow org-global/system skills that cannot be edited by normal users?
- [ ] Should skills support secrets references, or only plain resources + MCP tools?
- [ ] What is the max allowed skill package size and per-file size?
- [ ] Do we support remote registries in v1 or defer to v1.1?
- [ ] Do we introduce containerized node executors in v1.x for stronger isolation, or stay process-isolated only?

## Suggested implementation order (high confidence)

1. Stage 0 decisions + Stage 1 schema.
2. Stage 2 validation/package service.
3. Stage 3 adapters + run-isolation plumbing.
4. Stage 4 runtime cutover and no-global-mutation enforcement.
5. Stage 5 UI/API.
6. Stage 6 backfill rollout + concurrency verification.
7. Stage 7 hard-cut cleanup.
