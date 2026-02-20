# CLI To Studio Agent Runtime Migration Plan

Goal: migrate the current CLI-wrapper-driven agent execution model into Studio as the primary runtime while preserving flowchart context passing, tool-based operations, structured output contracts, and operational safety controls.

## Stage 0 - Requirements Gathering

- [x] Run Stage 0 interview one question per turn with explicit options.
- [x] Confirm migration scope boundary (`full replacement`, `side-by-side`, or `partial extraction`).
- [x] Confirm tool execution trust model (`sandboxed host tools`, `isolated worker tools`, or `hybrid`).
- [x] Confirm executor workspace storage lifecycle (`shared persistent`, `isolated persistent per run`, or `isolated ephemeral per run`).
- [x] Confirm where AGENTS/skills/prompt policy will live (`system prompt only`, `retrieval + composition`, or `mixed static + dynamic`).
- [x] Confirm data access approach for plans/milestones/memory (`existing MCP`, `direct SQLAlchemy tools`, or `hybrid`).
- [x] Confirm flowchart contract requirements (`best-effort JSON`, `strict schema JSON`, or `schema + versioned contracts`).
- [x] Confirm node-level configuration and permission surface parity (`per-node MCP/model/agent/prompt/tool allowlists` remains unchanged).
- [x] Confirm Studio model-management architecture (model records, provider bindings, and execution-time resolution strategy).
- [x] Confirm Studio model-management UI behavior for creating/editing/versioning models.
- [x] Confirm deterministic tool coverage strategy for special nodes (`decision`, `milestone`, `memory`, `plan`, and related workflow primitives).
- [x] Confirm deterministic tool contract and fallback rules when tool calls fail or return conflicting state.
- [x] Confirm deterministic branching contract from condition outputs to downstream connector/path activation.
- [x] Confirm decision condition evaluation strictness policy for connector routing.
- [x] Complete exhaustive deterministic tool inventory for cutover-critical workflows (no missing functional gaps).
- [x] Review and lock current connector/context-pass methodology baseline (execution loop, edge semantics, routing persistence, and downstream activation behavior).
- [x] Confirm routing inspector validation behavior and save-time UX for invalid configuration.
- [x] Confirm git write governance defaults (`manual approvals`, `policy-driven`, or `auto-allow`).
- [x] Confirm timeout/retry policy defaults and per-node override behavior.
- [x] Confirm model/provider unavailability behavior.
- [x] Confirm authorization model and policy enforcement defaults.
- [x] Confirm async update idempotency/deduplication strategy.
- [x] Confirm observability/audit baseline for production operations.
- [x] Confirm LLM-facing node/run introspection tool scope and default boundaries.
- [x] Confirm node artifact persistence contract across all node types (task, memory, milestone, plan, decision, etc.).
- [x] Confirm existing flowchart definition migration strategy.
- [x] Confirm rollback data compatibility policy for big-bang cutover.
- [x] Confirm rollout strategy and cutover risk tolerance.
- [x] Reopen Stage 0 scope for executor dependency isolation and packaging strategy updates.
- [x] Confirm executor split topology for Studio runtime workers (`single executor`, `frontier + vLLM split`, or `multi-executor class strategy`).
- [x] Confirm dependency policy per executor image (`SDK-only`, `mixed SDK + CLI`, or `custom per-executor profile`).
- [x] Confirm CLI tooling deprecation scope inside executors (`full removal`, `partial keep`, or `defer removal`).
- [x] Confirm vLLM executor runtime target (`GPU-only`, `dual-mode GPU+CPU fallback`, or `split GPU/CPU executors`).
- [x] Confirm vLLM dependency pinning/update policy (`strict lockfile`, `pinned requirements with scheduled updates`, or `rolling latest`).
- [x] Confirm vLLM Kubernetes scheduling policy for dual-mode execution (`prefer GPU + fallback`, `hard GPU when available class`, or `separate queue/routing`).
- [x] Confirm frontier executor base/runtime profile (`CPU-only non-CUDA`, dependency lock strategy, and minimal package posture).
- [x] Confirm frontier executor SDK inventory baseline (`minimal core SDKs`, `expanded SDK bundle`, or `workflow-scoped allowlist`).
- [x] Confirm frontier forbidden package/tool policy (explicit denylist for CLI binaries and conflict-prone Python packages).
- [x] Confirm executor image lineage migration (`remove llmctl-executor-base`, create dedicated `llmctl-executor-vllm` and `llmctl-executor-frontier` images, and update Harbor build/release flow accordingly).
- [x] Confirm frontier image composition policy (no dependency on `llmctl-executor-base`; standalone CPU/non-CUDA image with direct SDK dependencies only).
- [x] Confirm runtime settings contract for executor version/tag selection (separate configurable image/tag controls for frontier and vLLM executor pod spawning).
- [x] Confirm Stage 0 completeness and ask whether to proceed to Stage 1.

## Stage 0 - Interview Notes

- [x] Migration scope boundary selected: `full replacement` (day-one cutover target).
- [x] Tool execution trust model selected: `isolated worker tools` (retain Kubernetes executor model).
- [x] Executor workspace lifecycle selected: `isolated ephemeral per run` (clean workspace, teardown on executor termination).
- [x] Prompt/policy composition selected: `retrieval + composition`, aligned with existing runtime assembly (node MCP selection + agent skill/role selection + executor-time config build from experiment agent classes).
- [x] Data access model selected: `hybrid` with internal tools as primary path and MCP retained as optional/canonical interoperability surface (including use by other tools/services).
- [x] Flowchart output contract selected: `strict schema JSON` with validation-enforced node/agent outputs.
- [x] Rollout strategy selected: `big-bang cutover + hard rollback` after extended internal build/iteration period.
- [x] Tenancy/isolation question explicitly skipped as not relevant for this plan; inherit current Studio assumptions unless later changed.
- [x] Long-lived state source of truth selected: `Postgres only` for memory/plans/milestones/workflow state.
- [x] Schema validation failure policy selected: auto-retry with repair prompt up to configured max attempts, then fail node.
- [x] Node-level config/permissions selected: preserve existing flowchart UX and behavior (`per-node MCP selection`, `additional prompt`, `model`, `agent`, and explicit per-node tool allowlists).
- [x] Workspace bootstrap default selected: fresh git clone per run from selected repo/ref for reproducible clean starts.
- [x] Artifact retention selected: `standard` persistence (logs, tool calls, diffs/patches, structured node outputs, and error traces).
- [x] Git write governance selected: `policy-driven auto-allow` only when node/workflow git configuration is present and valid.
- [x] Timeout/retry policy selected: global defaults with explicit per-node overrides.
- [x] Model/provider unavailability behavior selected: fail node immediately (no automatic fallback).
- [x] Authorization/policy mode selected: no user-level permissions for now; runtime remains permissive/open while retaining policy validation/audit hooks for node/tool operations.
- [x] Async update idempotency selected: request-ID/correlation-ID based dedupe across HTTP, executor, and socket events.
- [x] Observability baseline selected: `standard` (request IDs, node timings, tool invocation logs, schema-failure traces, and git action audit trail).
- [x] Flowchart definition compatibility selected: `one-time migration` to new runtime schema before cutover.
- [x] Rollback data policy selected: forward-only acceptable; low priority on preserving legacy stored records, with preference to rehydrate only critical data when needed.
- [x] Additional Stage 0 scope added per user request: model-management redesign and deterministic tooling for special workflow nodes.
- [x] Additional Stage 0 scope added per user request: executor dependency isolation to address vLLM package/version conflicts and remove unnecessary CLI-tool installs from executor images.
- [x] Executor split topology selected: `frontier + vLLM split` with dedicated images `llmctl-executor-frontier` and `llmctl-executor-vllm`.
- [x] Executor dependency policy selected: `SDK-only` packages in executor images (no default CLI-tool installation requirement).
- [x] Executor CLI deprecation scope selected: `full removal` of CLI tool installs from executor images.
- [x] vLLM executor runtime target selected: `dual-mode GPU+CPU fallback` in a single `llmctl-executor-vllm` image.
- [x] vLLM dependency policy selected: `strict lockfile` with explicit bump PRs for dependency updates.
- [x] vLLM scheduling policy selected: `prefer GPU + fallback` automatic execution path when GPU capacity is unavailable.
- [x] Frontier executor runtime profile selected: `CPU-only non-CUDA base` with `strict lockfile` and minimal SDK-only dependency posture.
- [x] Frontier SDK inventory baseline selected (custom): include all required SDK packages for operational support across frontier models from OpenAI, Google, and Anthropic.
- [x] Frontier Google integration track selected: support both Gemini Developer API (`google-genai`) and Vertex AI (`google-cloud-aiplatform`) within frontier executor dependencies.
- [x] Frontier provider-config requirement added: ensure Vertex-specific runtime settings are exposed/available in model/provider configuration and runtime execution path.
- [x] Executor forbidden policy selected: hard denylist with no CLI binaries in executor images and explicit blocking of conflict-prone Python packages outside approved lockfiles.
- [x] Executor image lineage migration selected: retire `llmctl-executor-base` in favor of dedicated split images `llmctl-executor-vllm` and `llmctl-executor-frontier`, and update Harbor build/release flow to publish both.
- [x] Frontier image composition selected: standalone CPU/non-CUDA image with direct SDK installs; do not inherit from `llmctl-executor-base`.
- [x] Runtime settings contract selected: expose two global executor image/tag controls (`frontier` and `vLLM`) for pod spawn version selection.
- [x] Model-management architecture selected: keep direct `1:1` model-to-provider binding and preserve provider-specific runtime controls (for example OpenAI reasoning options) in model configuration.
- [x] Model UI/edit behavior selected: `snapshot-at-create`; compatibility for new provider/model capabilities will ship through future Studio releases rather than automatic schema upgrades.
- [x] Model-management list interaction selected: clicking a model row opens the model detail view, with icon-only row actions retained for direct operations.
- [x] Model-management keyboard interaction selected: when a row is focused, `Enter` opens detail view; in-row icon actions remain independently focusable/operable.
- [x] Model delete confirmation selected: two-click inline confirm on row-level trash action (no modal/type-to-confirm flow by default).
- [x] Model delete failure UX selected: revert row action state to normal and surface operation error through shared flash message area (no persistent row-level error lock).
- [x] Model operation outcome feedback selected: route create/update/delete success/error/warning/info through shared flash message area; keep inline messaging only for field-level validation errors.
- [x] Model-management create entrypoint selected: include primary `New Model` CTA in the shared model list panel header.
- [x] Model creation UX selected: launch create via routed page transition (`/models/new`) reusing the model detail/edit page structure.
- [x] Model list empty-state action selected: show a primary `New Model` button within the empty-state body (in addition to header-level create affordances).
- [x] Model-management default list columns selected: `Name`, `Provider`, `Default Alias`, `Capability Tags`, and icon-only `Actions` (omit redundant ID/updated-at columns in default view).
- [x] Model detail provider-specific settings presentation selected: place advanced provider controls in a collapsed-on-load `Advanced provider settings` section.
- [x] Model compatibility drift UX selected: show non-blocking compatibility notice via shared flash area and present an optional in-form `review settings` hint when new provider capabilities are not represented in the saved model snapshot.
- [x] Model detail delete control placement selected: expose delete as header-level icon/button near save controls (rather than bottom-page danger zone).
- [x] Model detail/create unsaved-change navigation selected: prompt user to discard changes or stay on page before route transition.
- [x] Model detail/create primary actions selected: keep `Save`/`Cancel` in the page header action area (no sticky footer action bar).
- [x] Model detail/create cancel behavior selected: when there are no unsaved changes, `Cancel` returns user to the model list route.
- [x] Model detail/create save enablement selected: keep `Save` disabled until form state is both valid and dirty (changed from persisted/default values).
- [x] Model list loading UX selected: use panel-scoped skeleton rows that preserve table/layout structure while data is loading.
- [x] Model list initial-load error UX selected: render inline panel error state with primary `Retry` action (operation-level error also surfaced via shared flash channel where applicable).
- [x] Model list icon-action accessibility selected: every icon-only action button must include both tooltip text and explicit `aria-label`.
- [x] Model list search interaction selected: use debounced typeahead filtering (approximately 250-300ms) with immediate result refresh after debounce.
- [x] Model list pagination/search coupling selected: reset pagination to page 1 whenever search or filter criteria change.
- [x] Model-management default list paging/sort selected: paginated list at `25/page` with default sort `Name ASC`, and pagination controls must live in the standardized panel header layout (consistent with Flowcharts/Memories-style panel headers).
- [x] Model-management panel-header layout selected: place pagination controls on the right side of the shared panel header, after search/filter controls.
- [x] Model-management narrow-screen header priority selected: collapse non-critical filters into a `Filters` popover before moving pagination/search/primary CTA.
- [x] Model list capability-tag overflow selected: render first two tags plus `+N` summary chip, with full tag list available via hover tooltip.
- [x] Model list capability-tag mobile interaction selected: on touch/mobile, tapping the `+N` chip opens/closes an anchored popover with the full tag list.
- [x] Model detail navigation selected: open model detail as routed page transition with URL change and browser back navigation restoring list context.
- [x] Model list return-state behavior selected: restore full list view state on back navigation (`page`, `sort`, `filters/search`, and scroll position).
- [x] Special node execution mode selected: `tool-first deterministic` for `decision`, `milestone`, `memory`, and `plan` nodes (LLM used only where explicitly needed).
- [x] Special node failure policy selected: if required tools fail or return conflicting/invalid results, fallback to LLM reasoning is allowed to continue workflow execution.
- [x] Special node fallback status selected: record as `success with warning` (degraded/fallback_used) for observability and downstream branching.
- [x] Optional summary behavior selected: allow optional LLM-generated human-readable summaries for deterministic nodes, while structured tool outputs remain authoritative.
- [x] Cutover tooling requirement selected: full deterministic tool suite at cutover with no missing functional gaps.
- [x] Memory tool coverage selected for cutover: core CRUD + search (`get`, `list`, `create`, `update`, `delete`, `search`).
- [x] Plan tool coverage selected for cutover: core operations (`get`, `list`, `create`, `update`, `delete`, `reorder_stages`, `set_stage_status`).
- [x] Milestone tool coverage selected for cutover: core operations (`get`, `list`, `create`, `update`, `delete`, `set_status`, `attach_evidence`).
- [x] Decision tool coverage selected for cutover: core operations (`create`, `evaluate`, `list_options`, `score_options`, `record_outcome`, `get`, `list`).
- [x] Branching determinism invariant added: condition evaluation outputs must be strictly persisted in contract-validated form so Python runtime can deterministically activate correct downstream workflow paths/connectors.
- [x] RAG tool coverage selected for cutover: core operations (`rag_source_list`, `rag_index_status`, `rag_trigger_index`, `rag_query`) with explicit support for both full indexing and delta indexing (new/changed files only).
- [x] Workflow-control tool coverage selected for cutover: core operations (`workflow_pause`, `workflow_resume`, `workflow_cancel`, `node_retry`, `node_skip`, `node_rewind`).
- [x] Git tool coverage selected for cutover: extended operations (read tools + `branch_create/switch`, `commit`, `push`, `pr_create`, `cherry_pick`, `rebase_noninteractive`, `tag_create`) with cross-branch coordination support for multi-agent workflows.
- [x] Filesystem/workspace tool coverage selected for cutover: core operations (`list`, `read`, `write`, `mkdir`, `delete`, `move/rename`, `copy`, `search`, `apply_patch`, `chmod`).
- [x] Command-execution tool coverage selected for cutover: extended operations (single-command, PTY sessions, timeout controls, background jobs, artifact capture, and resource-limit introspection).
- [x] Artifact invariant added: every node run must persist a traceable artifact record; artifacts are node-type-specific (for example task prompts/results, memory records, milestone/plan database state, decision evaluation outputs).
- [x] Artifact granularity selected: final-state-only artifact per node run (no full step transcript requirement by default).
- [x] Connector/branch tool coverage selected for cutover: core operations (`branch_evaluate`, `connector_conditions_get`, `connector_conditions_validate`, `next_nodes_resolve`).
- [x] Contract-validation tool coverage selected for cutover: core validation (`node_output_validate`, connector condition payload validation, and DB-write payload validation).
- [x] Flow-migration tooling selected for cutover readiness: core operations (schema transform + post-transform validation + dry-run execution check).
- [x] Observability/debug tool coverage selected for cutover: core operations (`run_get`, `node_run_get`, `logs_get`, `tool_calls_get`, `artifact_get`, `failure_trace_get`).
- [x] Model/provider management tool coverage selected for cutover: core operations (`provider_list/get`, `model_list/get/create/update/delete`, `model_validate_provider_settings`).
- [x] Tool-gap policy selected: temporary MCP fallback is allowed for uncovered operations, but implementation remains tool-first with expectation of exhaustive internal tool coverage by cutover.
- [x] Global tooling rule selected: any remaining/unlisted tool domains default to `core` coverage for cutover planning unless explicitly marked otherwise.
- [x] Explicit tool-scope exceptions retained: `git` and `command-execution` remain `extended`; artifact persistence remains final-state-only.
- [x] Exception review complete: no additional tool-scope exceptions requested beyond `git` and `command-execution`.
- [x] Context-budget constraint added: prioritize minimal/core tool exposure to protect runtime context window and preserve reliable flowchart operation in Studio.
- [x] Stage 0 extension approved: perform explicit connector/context-pass methodology review before Stage 1 planning.
- [x] Current baseline observed: runtime builds node input context from solid triggering upstream outputs plus dotted pulled context, persists `output_state` and `routing_state` per node run, and resolves downstream solid-edge activation from decision `matched_connector_ids`/`route_key` routing outputs.
- [x] Connector fan-in direction selected for migration: replace fixed all-solid-parent gating with configurable fan-in thresholds exposed in the node inspector.
- [x] Decision no-match policy selected: use explicit fallback connector when configured; otherwise fail the node. Policy should be configurable in node inspector.
- [x] Decision condition evaluation policy selected: `hybrid` (strict structured predicates first, then controlled heuristic fallback).
- [x] Decision multi-match routing policy selected: keep fan-out behavior; launch every downstream branch whose connector condition evaluates valid.
- [x] Decision connector-id synchronization policy selected: retain automatic sync/repair between solid outgoing connectors and `decision_conditions` definitions.
- [x] Edge context payload policy selected: keep full upstream payload pass-through (no per-edge field filtering/allowlists in this migration cut).
- [x] Route-resolution error policy selected: fail-fast on unresolved/invalid connector routing conditions.
- [x] Connector tracing controls selected: keep tracing runtime/internal only for now (no new inspector verbosity controls in this migration cut).
- [x] LLM node/run introspection scope selected: run-scoped read tools by default, with opt-in cross-run summary queries under strict filters/limits to control context bloat.
- [x] UI placement selected: routing controls live in a contextual `Node Inspector > Routing` section and render only when applicable.
- [x] Fan-in UI control selected: simple preset dropdown (`all`, `any`, `custom N`) instead of raw numeric-only control.
- [x] Fan-in `custom N` bounds selected: enforce minimum `1` and maximum equal to current count of solid upstream connectors.
- [x] Fan-in `custom N` shrink handling selected: auto-clamp to new valid maximum when upstream count decreases and emit warning via shared flash message area.
- [x] Decision no-match fallback UI selected: connector selector dropdown scoped to solid outgoing connectors from the current decision node.
- [x] Routing bulk-edit behavior selected: hide/disable routing controls in multi-select node inspector mode (routing config remains single-node only).
- [x] Routing inspector validation behavior selected: block save on invalid routing config, show inline field-level errors, and emit operation-level flash feedback.
- [x] Routing validation focus behavior selected: when save is blocked, auto-scroll/focus the first invalid routing field while preserving inline error visibility.
- [x] Routing editor update timing selected: apply connector/routing derived-state synchronization in real-time as inspector values change.
- [x] Routing inspector default visibility selected: collapsed-by-default with concise summary chips for current routing settings.
- [x] Routing collapsed-summary invalid-state visibility selected: include explicit `Invalid` chip with lightweight reason/count indicator even before section expansion.
- [x] Degraded/fallback warning UI placement selected: show warning on affected node plus corresponding warning entry in the run timeline/event stream (no standalone global banner requirement).
- [x] Invalid-routing unsaved edit behavior selected: preserve inspector draft edits across close/reopen until user fixes or explicitly discards.
- [x] Routing summary chip detail level selected: balanced detail (show preset plus key value such as `custom N` or fail/fallback mode without verbose connector diagnostics).
- [x] Decision fallback connector visibility selected: show both inspector-selected fallback connector and an inline `Fallback` badge on the corresponding connector in canvas/graph UI.
- [x] Decision multi-match runtime visualization selected: show node-level summary only (for example `Routed: N`) without per-connector mini status badges.
- [x] Decision route-count badge visibility selected: run-detail context only (not always shown in design/edit mode).
- [x] Routing collapsed-summary chip interaction selected: chips are read-only summaries; all routing edits require expanding the Routing inspector section.

## Stage 1 - Code Planning

- [x] Define Stage 2 through Stage X implementation stages from approved Stage 0 answers.
- [x] Freeze architecture boundaries (orchestrator, runtime workers, tools, persistence, and UI integration).
- [x] Freeze API/socket/tool contracts including request/correlation ID propagation.
- [x] Define migration checkpoints, fallback paths, and rollback triggers.
- [x] Partition implementation into prerequisite sequential stages and post-baseline fan-out stages for multi-agent execution.
- [x] Ensure final two stages are `Automated Testing` and `Docs Updates`.

Dependency model:
- Stages 2-6 are strict sequential prerequisites (`2 -> 3 -> 4 -> 5 -> 6`).
- Stages 7-13 are fan-out stages and may run in parallel after Stage 6 is complete.
- Stage 14 reconverges fan-out output for end-to-end cutover readiness.
- Stage 15 and Stage 16 are mandatory final stages and must run in order.
- Sequential tracking doc: `docs/planning/active/CLI_TO_STUDIO_AGENT_RUNTIME_MIGRATION_SEQUENTIAL_PLAN.md`.
- Fan-out tracking doc: `docs/planning/active/CLI_TO_STUDIO_AGENT_RUNTIME_MIGRATION_FANOUT_PLAN.md`.

## Stage 2 - Sequential Baseline A: Runtime Architecture Freeze

- [x] Lock module boundaries for Studio orchestrator, runtime workers, tool adapters, persistence services, and UI integration points.
- [x] Publish canonical component dependency map and allowed call paths (prevent cross-layer leakage).
- [x] Freeze executor split architecture (`llmctl-executor-frontier`, `llmctl-executor-vllm`) and ownership boundaries.
- [x] Define canonical async lifecycle state machine for workflow run and node run progression.
- [x] Stage output locked in `docs/planning/active/CLI_TO_STUDIO_AGENT_RUNTIME_STAGE2_ARCHITECTURE_FREEZE.md`.

## Stage 3 - Sequential Baseline B: Contracts + Persistence Foundations

- [x] Define JSON schemas and versioned contracts for node outputs, routing outputs, artifacts, and special-node tool outputs.
- [x] Freeze API error envelope and request/correlation ID requirements across backend responses and socket payloads.
- [x] Add/adjust DB schema for run/node artifacts, routing state, fallback/degraded status markers, and idempotency keys.
- [x] Define socket event contract names in `domain:entity:action` format and payload invariants.
- [x] Stage output locked in `docs/planning/active/CLI_TO_STUDIO_AGENT_RUNTIME_STAGE3_CONTRACTS_PERSISTENCE_FREEZE.md`.

## Stage 4 - Sequential Baseline C: Execution Loop + Routing Core

- [x] Implement/align orchestrator execution loop with connector/context-pass baseline (solid trigger + dotted context pull behavior).
- [x] Implement deterministic route resolution persistence (`matched_connector_ids`, `route_key`, `routing_state`) with fail-fast invalid-route handling.
- [x] Implement configurable fan-in policy (`all`, `any`, `custom N`) and save-time validation invariants.
- [x] Implement decision no-match behavior (explicit fallback connector or fail) as runtime-enforced policy.

## Stage 5 - Sequential Baseline D: Executor Image + Runtime Plumbing

- [x] Finalize split executor image definitions and lockfiles, including frontier CPU-only profile and vLLM dual-mode GPU/CPU fallback profile.
- [x] Remove deprecated CLI-tool dependency installs from executor images and enforce denylist policy.
- [x] Implement runtime settings for independent frontier/vLLM executor image tag selection.
- [x] Update Harbor-oriented build/release pipeline and image publication references for split executors.

## Stage 6 - Sequential Baseline E: Deterministic Tooling Framework

- [x] Implement shared internal tool invocation framework with schema validation, idempotency, retry controls, and artifact persistence hooks.
- [x] Implement standard fallback contract (`success_with_warning`, `fallback_used`) when required deterministic tools fail/conflict.
- [x] Implement shared tracing/audit envelope for tool calls, errors, and correlation propagation.
- [x] Deliver cutover-critical base tool scaffolding required before domain fan-out implementation begins.
- [x] Stage output locked in `docs/planning/active/CLI_TO_STUDIO_AGENT_RUNTIME_STAGE6_DETERMINISTIC_TOOLING_FREEZE.md`.

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

- [ ] Implement deterministic tool-first execution handlers for memory, plan, milestone, and decision node classes.
- [ ] Implement required domain tool operations and conflict/failure fallback semantics.
- [ ] Persist canonical structured outputs and node-type-specific final-state artifacts.
- [ ] Add contract and behavior tests for deterministic outputs and degraded/fallback paths.

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

## Stage 14 - Sequential Reconvergence: Integration + Cutover Readiness

- [ ] Merge fan-out outputs behind a unified runtime feature gate and remove temporary integration shims.
- [ ] Execute end-to-end cutover rehearsal across representative workflows (task + special nodes + routing fan-out/fan-in).
- [ ] Validate rollback triggers, migration checkpoint criteria, and failure containment behavior.
- [ ] Finalize release checklist for big-bang cutover and hard rollback path.

## Stage 15 - Automated Testing

- [ ] Run backend contract/integration test suites for API, socket events, routing determinism, and special-node tooling.
- [ ] Run frontend unit/integration tests for model management and routing inspector behavior.
- [ ] Run end-to-end migration and execution regression tests, including degraded/fallback scenarios.
- [ ] Record automated test evidence and unresolved failures for cutover sign-off.

## Stage 16 - Docs Updates

- [ ] Update Sphinx and Read the Docs content for runtime architecture, contracts, and operator workflows.
- [ ] Update internal developer docs for executor split images, build/release flow, and tool-domain ownership.
- [ ] Update API/socket/tool contract references and migration runbook documentation.
- [ ] Archive finalized planning and implementation notes with links to test evidence and rollout checklist artifacts.
