# CLI To Studio Agent Runtime Migration - Stage 2 Architecture Freeze

Date: 2026-02-20

Status: Locked

Related plans:
- `docs/planning/archive/CLI_TO_STUDIO_AGENT_RUNTIME_MIGRATION_PLAN.md`
- `docs/planning/archive/CLI_TO_STUDIO_AGENT_RUNTIME_MIGRATION_SEQUENTIAL_PLAN.md`
- `docs/planning/archive/CLI_TO_STUDIO_AGENT_RUNTIME_MIGRATION_FANOUT_PLAN.md`

## Stage 2 Completion Checklist

- [x] Lock module boundaries for Studio orchestrator, runtime workers, tool adapters, persistence services, and UI integration points.
- [x] Publish canonical component dependency map and allowed call paths (prevent cross-layer leakage).
- [x] Freeze executor split architecture (`llmctl-executor-frontier`, `llmctl-executor-vllm`) and ownership boundaries.
- [x] Define canonical async lifecycle state machine for workflow run and node run progression.

## 1) Module Boundaries (Frozen)

### 1.1 API and UI integration boundary

Owned paths:
- `app/llmctl-studio-backend/src/web/app.py`
- `app/llmctl-studio-backend/src/web/views.py`
- `app/llmctl-studio-backend/src/rag/web/views.py`
- `app/llmctl-studio-frontend/src/App.jsx`
- `app/llmctl-studio-frontend/src/lib/httpClient.js`
- `app/llmctl-studio-frontend/src/lib/studioApi.js`

Rules:
- Backend API routes remain JSON-first under `/api` with Socket.IO on `/rt` namespace.
- Frontend pages/components call backend through shared API client modules (`studioApi` -> `httpClient`).
- Frontend operation outcomes route through shared flash (`FlashProvider` / `useFlash`).
- Leaf frontend pages do not own transport details beyond invoking shared client modules.

### 1.2 Orchestrator boundary

Owned paths:
- `app/llmctl-studio-backend/src/services/tasks.py`

Rules:
- Orchestrator owns flowchart run lifecycle, activation queueing, fan-out/fan-in gating, and route resolution.
- Orchestrator creates/persists `FlowchartRun`, `FlowchartRunNode`, task metadata, and node artifacts.
- Orchestrator may call execution router, instruction tooling, and domain-node handlers.
- Orchestrator does not directly implement Kubernetes API dispatch details.

### 1.3 Execution transport boundary

Owned paths:
- `app/llmctl-studio-backend/src/services/execution/contracts.py`
- `app/llmctl-studio-backend/src/services/execution/router.py`
- `app/llmctl-studio-backend/src/services/execution/kubernetes_executor.py`
- `app/llmctl-studio-backend/src/services/execution/idempotency.py`

Rules:
- Execution router selects provider and dispatch metadata contract.
- Kubernetes executor owns pod/job submission, startup marker validation, and remote result parsing.
- Execution transport does not own workflow graph routing or domain-node business logic.

### 1.4 Instruction and adapter boundary

Owned paths:
- `app/llmctl-studio-backend/src/services/instructions/compiler.py`
- `app/llmctl-studio-backend/src/services/instruction_adapters/*`
- `app/llmctl-studio-backend/src/services/skill_adapters.py`

Rules:
- Compiler owns deterministic instruction artifact assembly and manifest hashing.
- Instruction adapters own provider-specific materialization behavior.
- Orchestrator consumes this subsystem as a service; it does not inline provider-specific file materialization.

### 1.5 Persistence and integration settings boundary

Owned paths:
- `app/llmctl-studio-backend/src/core/models.py`
- `app/llmctl-studio-backend/src/core/db.py`
- `app/llmctl-studio-backend/src/services/integrations.py`

Rules:
- Domain entities and DB constraints are defined in core model/db modules.
- Runtime settings normalization/validation is owned by integrations service.
- All writes happen via session-scoped service/API paths, not by frontend or executor image runtime.

### 1.6 Realtime boundary

Owned paths:
- `app/llmctl-studio-backend/src/services/realtime_events.py`
- `app/llmctl-studio-backend/src/web/realtime.py`

Rules:
- Event envelope shape, sequencing, idempotency key behavior, and room scoping are centralized.
- Service modules emit via `emit_contract_event`; they do not bypass envelope construction.

## 2) Canonical Dependency Map (Frozen)

Primary request path:
1. React route/page (`app/llmctl-studio-frontend/src/App.jsx`) calls shared API client (`app/llmctl-studio-frontend/src/lib/studioApi.js` -> `app/llmctl-studio-frontend/src/lib/httpClient.js`).
2. Flask API route (`app/llmctl-studio-backend/src/web/views.py` or `app/llmctl-studio-backend/src/rag/web/views.py`) validates request and loads/saves domain state.
3. Orchestrator (`app/llmctl-studio-backend/src/services/tasks.py`) constructs node execution requests and runtime context.
4. Execution router (`app/llmctl-studio-backend/src/services/execution/router.py`) routes to provider executor.
5. Kubernetes executor (`app/llmctl-studio-backend/src/services/execution/kubernetes_executor.py`) dispatches pod/job and returns `output_state` / `routing_state`.
6. Orchestrator persists node/run outcomes and emits contract events (`app/llmctl-studio-backend/src/services/realtime_events.py`).
7. Socket transport publishes via `app/llmctl-studio-backend/src/web/realtime.py`.

Node execution callback path:
1. Executor pod callback entrypoint is `_execute_flowchart_node_request` in `app/llmctl-studio-backend/src/services/tasks.py`.
2. Callback delegates to `_execute_flowchart_node(...)` dispatching by node type to deterministic handlers.
3. Callback returns `(output_state, routing_state)` only; orchestrator owns run/node persistence and routing activation.

## 3) Allowed and Forbidden Call Paths (Frozen)

Allowed:
- `web/*` -> `services/*` -> `core/*`
- `services/tasks.py` -> `services/execution/*`
- `services/tasks.py` -> `services/instructions/*` and `services/instruction_adapters/*`
- `services/*` -> `services/realtime_events.py` -> `web/realtime.py`
- `frontend/pages/*` -> `frontend/lib/studioApi.js` -> `frontend/lib/httpClient.js`

Forbidden:
- `web/views.py` importing or implementing Kubernetes executor internals.
- `services/execution/*` implementing workflow graph decisions or mutating flowchart graph topology.
- Executor pod callbacks running schema migrations/DDL.
- Frontend leaf pages/components issuing ad-hoc `fetch` calls for mutation/read paths that belong in shared API modules.
- Frontend leaf pages/components introducing operation-level notification systems outside shared flash.

## 4) Executor Split Architecture Freeze (Target for Stage 5)

Target images:
- `llmctl-executor-frontier`
- `llmctl-executor-vllm`

Frozen responsibilities:
- `llmctl-executor-frontier`: non-vLLM provider execution path, CPU/non-CUDA base, SDK-only dependencies, no bundled CLI tool installs.
- `llmctl-executor-vllm`: vLLM provider execution path, dual-mode GPU-preferred with CPU fallback, strict lockfile policy.

Provider-to-executor class mapping (frozen):
- Frontier executor class: `codex`, `gemini`, `claude` (and future non-vLLM providers).
- vLLM executor class: `vllm_local`, `vllm_remote`.

Runtime settings contract (frozen target):
- Separate image/tag controls for frontier and vLLM executor dispatch classes.
- Current single-image keys remain valid during migration; split-key rollout is implemented in Stage 3 and Stage 5.

Release/build ownership freeze:
- Harbor build flow will publish both split images.
- `llmctl-executor-base` lineage is retired once split images are authoritative.

## 5) Canonical Async Lifecycle State Machine (Frozen)

### 5.1 Flowchart run lifecycle

Run states:
- `queued`
- `running`
- `stopping`
- `stopped`
- `completed`
- `failed`
- `canceled`

Transitions:
- `queued -> running` when Celery task begins.
- `running -> stopping` on graceful stop request.
- `stopping -> stopped` when graceful stop is honored.
- `queued -> stopped` on pre-start stop request.
- `queued|running|stopping -> canceled` on force cancel.
- `running|stopping -> completed` when execution finishes without terminal error.
- `running|stopping -> failed` on terminal error.

### 5.2 Flowchart node run lifecycle

Node run states:
- `queued` (optional pre-dispatch representation)
- `running`
- `succeeded`
- `failed`
- `canceled` (force-cancel path)

Transitions:
- `queued|running -> canceled` on force cancel.
- `running -> succeeded` when execution result is success and persistence succeeds.
- `running -> failed` on dispatch failure, execution failure, route-resolution failure, or persistence failure.

### 5.3 Dispatch metadata lifecycle

Dispatch states:
- `dispatch_pending`
- `dispatch_submitted`
- `dispatch_confirmed`
- `dispatch_failed`

Contract rules:
- `provider_dispatch_id` is required for `dispatch_submitted` and `dispatch_confirmed`.
- `dispatch_uncertain=true` indicates ambiguous remote state and is fail-closed.
- `workspace_identity` is normalized and path-safe.

## 6) Implementation Guardrails For Stage 3+

- Stage 3 contract/schema work must preserve these boundaries and status semantics.
- Stage 4 routing-core work must keep orchestrator ownership of graph activation/routing decisions.
- Stage 5 executor image/runtime plumbing must implement the split-image target without violating API/orchestrator boundaries.
- Stage 6 tooling framework must integrate through orchestrator and execution contracts, not by bypassing persistence/event boundaries.
