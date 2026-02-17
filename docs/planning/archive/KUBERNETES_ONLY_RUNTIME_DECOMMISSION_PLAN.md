# Kubernetes-Only Runtime Decommission Plan

Goal: decommission Docker Compose/local runtime execution paths and enforce Kubernetes-only deployment/runtime behavior, including Kubernetes pod-based ephemeral executors.

## Stage 0 - Requirements Gathering
- [x] Confirm exact Docker decommission scope (Compose/dev workflows/runtime code paths) and what remains for image builds only.
- [x] Confirm required runtime policy changes in Studio UI/API (Kubernetes-only selection vs hidden/removed alternatives).
- [x] Confirm executor lifecycle contract for Kubernetes ephemeral pods (creation, teardown, failure handling, namespace policy).
- [x] Confirm migration strategy for existing runtime configuration rows that reference Docker/workspace modes.
- [x] Confirm local developer workflow after Compose removal (how Studio/RAG/services are started for development).
- [x] Confirm rollout strategy (single cutover vs phased cutover) and rollback expectation.
- [x] Confirm requirements are complete and approved to start Stage 1.

## Stage 0 - Interview Notes
- [x] Scope decision: hard cut now. Remove Compose deployment workflow and remove Docker/workspace runtime executors immediately; keep Dockerfiles/build scripts for image builds.
- [x] Runtime policy decision: Kubernetes-only enforced. Remove non-Kubernetes options from UI and reject non-Kubernetes runtime values in API/service layers.
- [x] Executor lifecycle decision: short TTL retention for terminal executor pods, then auto-delete (target window to be finalized in implementation stage).
- [x] Migration strategy decision: auto-migrate existing non-Kubernetes runtime configuration values to `kubernetes`.
- [x] Local development decision: Kubernetes-only local development via Kubernetes overlays/cluster workflows; no non-Kubernetes fallback mode.
- [x] Rollout decision: single coordinated cutover; rollback path is reverting to prior release if needed.
- [x] Executor pod namespace decision: run ephemeral executor pods in the same namespace as Studio.

## Stage 1 - Code Planning
- [x] Translate approved Stage 0 requirements into Stage 2 through Stage X execution stages.
- [x] Define concrete file-level scope, dependency order, and acceptance criteria per stage.
- [x] Ensure the final two stages are `Automated Testing` and `Docs Updates`.

## Stage 1 - Execution Order
- [x] Stage 2: Runtime contract hard-cut to Kubernetes-only providers/metadata semantics.
- [x] Stage 3: Executor runtime implementation cutover to Kubernetes-only pod execution.
- [x] Stage 4: Node executor settings persistence/API/UI contraction to Kubernetes-only fields.
- [x] Stage 5: Database/runtime migration for existing non-Kubernetes values + constraints alignment.
- [x] Stage 6: Deployment workflow decommission for Compose/local Docker runtime entrypoints.
- [x] Stage 7: Automated Testing.
- [x] Stage 8: Docs Updates.

## Stage 2 - Runtime Contract Hard-Cut (Kubernetes-Only)
- [x] Update node executor provider constants/enums in `app/llmctl-studio-backend/src/services/execution/contracts.py`, `app/llmctl-studio-backend/src/services/integrations.py`, and `app/llmctl-studio-backend/src/core/models.py` to remove `workspace` and `docker` as valid node executor providers.
- [x] Remove fallback-related node executor runtime metadata semantics (`fallback_provider`, `fallback_enabled`, `fallback_on_dispatch_error`, fallback reason/state transitions) from normalization and summaries where node executor routing is concerned.
- [x] Ensure runtime metadata normalization/writers only emit Kubernetes provider values for node executor routing fields.
- [x] Acceptance criteria: node executor provider contract is Kubernetes-only at type/constant boundaries, and fallback routing metadata is no longer part of the runtime contract.

## Stage 3 - Executor Runtime Implementation Cutover
- [x] Refactor `app/llmctl-studio-backend/src/services/execution/router.py` to dispatch exclusively through `KubernetesExecutor`; remove Docker/workspace routing branches.
- [x] Remove runtime imports/exports and code paths for `docker_executor` and `workspace_executor` from `app/llmctl-studio-backend/src/services/execution/__init__.py` and any call sites.
- [x] Update `app/llmctl-studio-backend/src/services/execution/kubernetes_executor.py` to remove workspace fallback execution logic and enforce fail-on-dispatch/execution behavior.
- [x] Implement short terminal pod retention policy for Kubernetes executor jobs (same namespace as Studio) via configurable or defaulted job TTL semantics, then rely on automatic cleanup and existing prune behavior.
- [x] Acceptance criteria: every node execution dispatches as a Kubernetes Job/Pod only, no fallback to workspace/docker exists, and terminal jobs auto-expire on short TTL.

## Stage 4 - Settings/API/UI Contraction (Kubernetes-Only)
- [x] Reduce node executor settings surface in `app/llmctl-studio-backend/src/services/integrations.py` to Kubernetes-relevant keys; remove Docker/workspace-specific persisted keys and validation.
- [x] Update node runtime settings routes/context in `app/llmctl-studio-backend/src/web/views.py` to accept/render only Kubernetes runtime settings.
- [x] Update `app/llmctl-studio-backend/src/web/templates/settings_runtime.html` node runtime panel to remove Docker/workspace/fallback controls and present Kubernetes-only controls.
- [x] Enforce backend rejection (validation error) for any non-Kubernetes provider submissions at settings API boundaries.
- [x] Acceptance criteria: runtime settings UI/API only exposes Kubernetes executor configuration and rejects non-Kubernetes provider values.

## Stage 5 - DB + Runtime Migration Alignment
- [x] Add runtime migration logic in `app/llmctl-studio-backend/src/core/migrations.py` and/or `app/llmctl-studio-backend/src/core/db.py` to rewrite persisted non-Kubernetes node executor settings to Kubernetes values.
- [x] Update agent task/provider constraint and normalization logic in `app/llmctl-studio-backend/src/core/db.py` and `app/llmctl-studio-backend/src/services/tasks.py` so new writes use Kubernetes-only provider semantics while preserving readability of legacy rows.
- [x] Ensure provider dispatch ID pattern/validation no longer depends on Docker/workspace prefixes for new node executor writes.
- [x] Acceptance criteria: existing installations auto-migrate runtime settings to Kubernetes, and runtime/provider persistence enforces Kubernetes-only behavior without manual DB intervention.

## Stage 6 - Compose/Local Docker Deployment Decommission
- [x] Remove Docker Compose deployment entrypoint from repo workflow (`docker/docker-compose.yml`) and clean script/docs references that instruct Compose-based Studio/RAG runtime startup.
- [x] Keep Dockerfiles and image build scripts required for container image builds (`app/*/Dockerfile`, `app/*/docker/build-*.sh`, `scripts/build-*.sh`).
- [x] Update Kubernetes-first local-dev paths to rely on Minikube/Kubernetes overlays and existing k8s manifests.
- [x] Acceptance criteria: repository no longer supports Compose-based runtime deployment; documented and scripted deployment/runtime workflows are Kubernetes-only while image build tooling remains.

## Stage 7 - Automated Testing
- [x] Update/add tests covering Kubernetes-only routing, settings validation, and migration rewrite behavior (`app/llmctl-studio-backend/tests/test_node_executor_stage*.py`, runtime/settings tests, and DB migration coverage).
- [x] Remove/update tests that assert Docker/workspace provider routing or fallback behavior.
- [x] Run targeted automated test suites for modified backend/runtime areas and resolve regressions.
- [x] Acceptance criteria: all executed automated checks for Kubernetes-only runtime/deployment changes pass.
- [x] Follow-up: installed backend test dependencies in repo-local `.venv` (`Flask`, `SQLAlchemy`, and `requirements.txt` set), then reran targeted Kubernetes-only node executor tests successfully.

## Stage 8 - Docs Updates
- [x] Update Kubernetes and runtime operator docs (`kubernetes/README.md`, Sphinx runtime docs) to reflect Kubernetes-only deployment and node execution behavior.
- [x] Remove or rewrite Compose/local Docker runtime references across documentation and developer guidance (`AGENTS.md`, relevant READMEs, planning references where appropriate).
- [x] Ensure docs describe Kubernetes pod-based ephemeral executor behavior and short TTL cleanup policy.
- [x] Acceptance criteria: docs consistently describe Kubernetes-only deployment/runtime workflows with no Docker Compose runtime path.
