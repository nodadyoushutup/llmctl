# CLI To Studio Agent Runtime Migration - Sequential Plan

Source of truth companion: `docs/planning/active/CLI_TO_STUDIO_AGENT_RUNTIME_MIGRATION_PLAN.md`

Execution order:
1. Complete Stages 2-6 in strict sequence.
2. Wait for all fan-out stages (Stages 7-13) to complete.
3. Complete Stages 14-16 in strict sequence.

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

- [ ] Implement shared internal tool invocation framework with schema validation, idempotency, retry controls, and artifact persistence hooks.
- [ ] Implement standard fallback contract (`success_with_warning`, `fallback_used`) when required deterministic tools fail/conflict.
- [ ] Implement shared tracing/audit envelope for tool calls, errors, and correlation propagation.
- [ ] Deliver cutover-critical base tool scaffolding required before domain fan-out implementation begins.

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
