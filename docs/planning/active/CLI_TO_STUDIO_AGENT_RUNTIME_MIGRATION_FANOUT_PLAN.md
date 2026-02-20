# CLI To Studio Agent Runtime Migration - Fan-Out Plan

Source of truth companion: `docs/planning/active/CLI_TO_STUDIO_AGENT_RUNTIME_MIGRATION_PLAN.md`

Prerequisites:
1. Stage 6 must be complete before starting fan-out work.
2. Each fan-out stage should be assigned wholesale to one agent.
3. Stages 7-13 can run in parallel with no ordering constraints between them.
4. Reconvergence begins only after all fan-out stages are complete.

## Stage 7 - Fan-Out A: Model/Provider Management API + Backend Contracts

- [ ] Implement provider/model CRUD and validation APIs with stable response contracts and pagination/filtering/sorting support.
- [ ] Preserve direct `1:1` model-provider binding and provider-specific runtime settings behavior.
- [ ] Implement compatibility-drift signaling contract and request/correlation ID propagation in API/socket surfaces.
- [ ] Add backend contract tests for provider/model payloads and error envelopes.

## Stage 8 - Fan-Out B: Model Management React UX

- [ ] Implement routed list/detail/create model UX (`/models`, `/models/new`, `/models/:id`) with row-click detail navigation.
- [ ] Enforce list-view interaction rules (row-link behavior, icon-only actions, delete confirm behavior, omitted redundant columns).
- [ ] Route operation outcomes via shared flash message area (`FlashProvider`/`useFlash`) and keep inline validation field-scoped.
- [ ] Implement list state restoration (pagination/sort/filter/scroll), debounced search, and loading/error/empty-state patterns.

## Stage 9 - Fan-Out C: Routing Inspector UX + Validation

- [ ] Implement `Node Inspector > Routing` section with collapsed summary chips and invalid-state chip behavior.
- [ ] Implement routing controls (`all/any/custom N`, decision fallback connector selector) with real-time derived-state sync.
- [ ] Implement save-blocking validation UX (inline errors, focus/scroll to first invalid field, flash-level operation feedback).
- [ ] Implement connector-level fallback badge and run-detail route-count visualization behaviors.

## Stage 10 - Fan-Out D: Special Node Tool Domains (Memory/Plan/Milestone/Decision)

- [x] Implement deterministic tool-first execution handlers for memory, plan, milestone, and decision node classes.
- [x] Implement required domain tool operations and conflict/failure fallback semantics.
- [x] Persist canonical structured outputs and node-type-specific final-state artifacts.
- [x] Add contract and behavior tests for deterministic outputs and degraded/fallback paths.

## Stage 11 - Fan-Out E: Workspace/Git/Command/RAG Tool Domains

- [ ] Implement filesystem/workspace tool suite (`list/read/write/.../apply_patch/chmod`) in shared tooling framework.
- [ ] Implement extended git tool suite (branch, commit, push, PR, cherry-pick, noninteractive rebase, tagging).
- [ ] Implement extended command-execution tooling (PTY/session lifecycle, timeouts, background jobs, artifact capture).
- [ ] Implement RAG indexing/query tooling with full + delta indexing support and stable contracts.

## Stage 12 - Fan-Out F: Observability + Run Introspection + Workflow Control

- [ ] Implement run/node/tool/artifact/failure trace query surfaces with strict filters/limits.
- [ ] Implement workflow control tools (`pause/resume/cancel/retry/skip/rewind`) with idempotent semantics.
- [ ] Implement warning propagation for degraded fallback usage in node status and run event timeline.
- [ ] Ensure request/correlation ID tracing is available across API logs, socket events, and persisted artifacts.

## Stage 13 - Fan-Out G: Flow Migration Tooling + Compatibility Gate

- [ ] Implement one-time flowchart schema transform pipeline for legacy definition migration.
- [ ] Implement post-transform validation and dry-run execution checks before migration acceptance.
- [ ] Implement compatibility gate reporting for non-migratable or policy-violating flow definitions.
- [ ] Implement migration evidence artifacts and rollback-trigger metadata capture.
