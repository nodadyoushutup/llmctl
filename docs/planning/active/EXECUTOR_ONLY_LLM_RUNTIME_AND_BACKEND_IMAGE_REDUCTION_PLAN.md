# Executor-Only LLM Runtime And Backend Image Reduction Plan

Goal: route all LLM interactions through executor pods so the Studio backend no longer needs heavy LLM runtime dependencies (CLI tools, CUDA, PyTorch, vLLM), enabling a materially smaller backend image.

## Stage 0 - Requirements Gathering

- [x] Capture requested direction and expected outcome from user.
  - [x] User intent captured: all LLM calls should execute in executor pods.
  - [x] User intent captured: backend image should be slimmed by removing LLM/runtime/GPU toolchain dependencies that are no longer needed there.
- [x] Confirm migration scope boundary (chat only vs all remaining LLM call paths).
  - [x] Scope selected: all LLM interactions execute in executor pods.
- [x] Confirm rollout strategy (hard cutover vs phased toggle/feature flag).
  - [x] Rollout selected: hard cutover to executor-only LLM runtime.
- [x] Confirm acceptance criteria and evidence requirements (runtime metadata, logs, tests, image size delta target).
  - [x] Acceptance criteria selected (custom): remove backend LLM/GPU runtime dependencies that are only needed in executor images.
  - [x] Acceptance criteria selected (custom): backend image size must decrease versus baseline, with no fixed percentage threshold.
  - [x] Acceptance criteria selected (custom): verify executor receives all required runtime context so behavior remains correct after backend dependency removal.
- [x] Confirm operational constraints (downtime tolerance, compatibility window, rollback expectations).
  - [x] Constraint selected: dev-mode rolling cutover with no maintenance window and fast rollback to prior image/tag if needed.
- [x] Confirm Stage 0 completeness with user and ask whether to proceed to Stage 1.
  - [x] User approved proceeding to Stage 1.

## Stage 1 - Code Planning

- [x] Define Stage 2 through Stage X based on approved Stage 0 requirements.
- [x] Freeze file-level scope and sequencing.
- [x] Define explicit acceptance criteria per stage.
- [x] Ensure final two stages are `Automated Testing` and `Docs Updates`.

## Stage 2 - LLM Call Path Inventory And Contract Freeze

- [x] Enumerate every backend LLM invocation path (Chat, RAG chat synthesis, quick/task/flowchart paths, utility transforms) and classify as executor-routed vs local.
  - [x] Inventory result: chat runtime and RAG web chat synthesis were backend-local; flowchart/quick/agent-task executor-node paths already existed.
- [x] Freeze a single executor request/response contract for all LLM interactions, including provider/model/MCP/RAG/context window inputs.
  - [x] Contract implementation: executor node types `llm_call` and `rag_chat_completion` added under the existing `ExecutionRequest`/`ExecutionResult` contract.
- [x] Freeze required runtime evidence fields for all paths (`provider_dispatch_id`, `k8s_job_name`, `k8s_pod_name`, terminal reason, request/correlation IDs).
  - [x] Evidence propagation: chat turn runtime metadata now records executor run/provider metadata and executor error payloads.
- [x] Acceptance criteria: no ambiguous/unowned LLM path remains and contract is sufficient to remove backend-local LLM execution.

## Stage 3 - Migrate Chat Runtime To Executor Pods

- [x] Route `chat/runtime.py` turn execution through `ExecutionRouter`/executor instead of direct `_run_llm`.
- [x] Preserve chat behavior semantics (session-scoped model/MCP/RAG selectors, error reason codes, turn/activity lifecycle).
- [x] Persist executor runtime evidence in chat turn metadata and activity events.
- [x] Acceptance criteria: chat LLM execution never runs in backend process and chat turns show executor dispatch evidence.

## Stage 4 - Migrate Remaining Non-Executor LLM Paths

- [x] Migrate any remaining direct backend LLM call paths (including RAG chat synthesis and optional transform paths) to executor runtime.
  - [x] RAG web chat and retrieval synthesis now dispatch through executor `rag_chat_completion`.
  - [x] Agent task Celery execution now always routes through executor-node path.
- [x] Remove or block backend-local LLM fallback execution for these paths.
- [x] Normalize executor routing/helpers so all LLM paths use one shared dispatch model.
- [x] Acceptance criteria: all LLM invocations are executor-routed and backend-local LLM execution paths are eliminated/disabled.

## Stage 5 - Executor Payload Parity And Runtime Context Hardening

- [x] Ensure executor receives complete context previously available in backend process (workspace identity, env/auth, model config, MCP configs, RAG retrieval context, prompt envelope).
- [x] Add validation for required payload fields and structured failure messages when payload is incomplete.
- [x] Verify idempotent/traceable request handling with request or correlation IDs propagated end-to-end.
- [x] Acceptance criteria: executor has all required context for equivalent behavior and failures are diagnosable via structured metadata.

## Stage 6 - Backend Image Dependency Reduction

- [x] Remove backend-only installation of LLM CLI/tooling and GPU stack not required for control-plane behavior (CUDA/PyTorch/vLLM/tool CLIs where no longer needed).
- [x] Keep heavyweight runtime dependencies in executor image only.
- [ ] Update backend Dockerfile/requirements/build steps and verify backend still boots and serves non-LLM control-plane APIs.
  - [x] Backend Dockerfile updated to remove Node-based LLM CLI installation and backend-side `vllm` install.
  - [x] Executor Dockerfile/build flow updated with configurable CUDA/vLLM base images and optional system-site-packages inheritance to avoid repeated vLLM rebuild cost.
  - [ ] Runtime boot verification pending in environment with backend dependencies installed.
- [ ] Acceptance criteria: backend image is smaller than baseline and removed dependencies are no longer present in backend image layers.
  - [ ] Image-size delta measurement pending user-run Harbor builds.
  - [ ] Build handoff rule: Codex provides explicit Harbor build command(s); user runs builds and confirms resulting image tags/digests.

## Stage 7 - Integration Wiring And Dev Rollout Prep

- [x] Update runtime/config wiring so executor-only LLM behavior is the hard default for dev rollout.
- [x] Ensure deployment manifests/env settings remain valid after backend image slimming.
  - [x] Dev overlay now pins runtime images to Harbor artifacts using `latest@sha256:<digest>` for backend, executor, mcp, and celery worker/beat.
- [ ] Execute smoke validations for chat + quick + flowchart + RAG chat paths with executor evidence checks.
- [ ] After each user-confirmed image build, update Kubernetes image refs to new tags for both:
  - [x] mutable tag (`latest`)
  - [x] immutable content tag (git SHA tag and/or image digest)
- [x] Apply/verify Kubernetes rollout after image ref updates.
  - [x] ArgoCD app reconciled to commit `f77e7f98cfa8bcc683c82af8ce4577581354f3a7` with `Synced`/`Healthy` status.
  - [x] Deployment rollouts verified for `llmctl-studio-backend`, `llmctl-mcp`, `llmctl-celery-worker`, and `llmctl-celery-beat`.
- [ ] Acceptance criteria: dev rollout path is stable with fast rollback to prior image/tag if needed.

## Stage 8 - Automated Testing

- [x] Run targeted automated tests for affected backend/executor/runtime paths.
  - [x] Attempted targeted test runs.
  - [x] Installed/used local Postgres test harness and reran targeted tests.
  - [x] `test_node_executor_stage4.py` passes under Postgres harness.
  - [x] `test_chat_runtime_stage8.py` and `test_react_stage8_api_routes.py` updated for Postgres schema isolation and now pass under harness.
- [x] Run static compile checks for touched backend Python modules.
- [x] Add/adjust tests asserting LLM calls are executor-routed for all surfaces and backend-local execution is not used.
  - [x] Added coverage for non-quick `run_agent_task` executor routing in `test_node_executor_stage4.py`.
- [ ] Validate backend image composition checks (dependency absence/presence expectations) in automation where practical.
- [ ] Record pass/fail outcomes and follow-up work.

## Build/Deploy Handoff Protocol (New Required Workflow)

- [x] For every Docker rebuild request, Codex must provide the exact Harbor build/push command(s) instead of running long local Docker builds.
- [x] User runs the command(s) and replies with completion confirmation plus resulting image tag/digest.
- [x] Only after user confirmation, Codex updates Kubernetes manifests/values to reference:
  - [x] `latest`
  - [x] SHA/digest-pinned image reference
- [x] Codex then performs rollout/status checks and records outcomes in this plan.

## Stage 9 - Docs Updates

- [x] Update Sphinx/Read the Docs and operational docs for executor-only LLM runtime and backend image composition.
  - [x] Updated operational Kubernetes docs (`kubernetes/README.md`) for executor-only LLM runtime behavior.
  - [x] Updated Sphinx docs (`docs/sphinx/changelog.rst`, `docs/sphinx/node_executor_runtime.rst`) for executor-only LLM runtime behavior.
- [x] Document the architecture split explicitly: backend is control-plane; executor is LLM runtime plane.
- [x] Document rollback/runbook notes for dev-mode hard cutover.
- [x] Record explicit no-op decision if no docs changes are needed.
  - [x] Not a no-op: docs were updated.
