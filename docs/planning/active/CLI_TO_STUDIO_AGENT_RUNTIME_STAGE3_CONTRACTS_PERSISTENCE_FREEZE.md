# CLI To Studio Agent Runtime Migration - Stage 3 Contracts + Persistence Freeze

Date: 2026-02-20
Source stage: `docs/planning/active/CLI_TO_STUDIO_AGENT_RUNTIME_MIGRATION_SEQUENTIAL_PLAN.md` (Stage 3)

## Stage 3 Completion Checklist

- [x] Define JSON schemas and versioned contracts for node outputs, routing outputs, artifacts, and special-node tool outputs.
- [x] Freeze API error envelope and request/correlation ID requirements across backend responses and socket payloads.
- [x] Add/adjust DB schema for run/node artifacts, routing state, fallback/degraded status markers, and idempotency keys.
- [x] Define socket event contract names in `domain:entity:action` format and payload invariants.

## 1) Contract Schema Freeze

Canonical Stage 3 runtime contracts are now centralized in:

- `app/llmctl-studio-backend/src/services/runtime_contracts.py`

Frozen contract artifacts:

- Node output contract version: `v1`
- Routing output contract version: `v1`
- Node artifact contract version: `v1`
- Node artifact payload version: `1`
- API error envelope contract version: `v1`
- Socket event contract version: `v1`

Frozen JSON-schema-style contract maps:

- `NODE_OUTPUT_BASE_JSON_SCHEMA`
- `ROUTING_OUTPUT_JSON_SCHEMA`
- `SPECIAL_NODE_OUTPUT_JSON_SCHEMAS`
- `NODE_ARTIFACT_JSON_SCHEMAS`
- `API_ERROR_ENVELOPE_JSON_SCHEMA`
- `SOCKET_EVENT_ENVELOPE_JSON_SCHEMA`

Runtime enforcement points:

- Special-node output validation in task runtime (`plan`, `milestone`, `memory`, `decision`).
- Artifact payload contract validation before DB persistence.
- Kubernetes executor validation of returned `output_state` and `routing_state`.

## 2) API Error Envelope + Request/Correlation IDs Freeze

Shared API envelope helpers are now centralized in:

- `app/llmctl-studio-backend/src/web/api_contracts.py`

Workflow APIs now share a single error envelope shape:

- `ok` (boolean)
- `error.contract_version` (`v1`)
- `error.code`
- `error.message`
- `error.details`
- `error.request_id`
- top-level optional `correlation_id`

Views now route workflow request/correlation extraction and error envelopes through shared helpers:

- `app/llmctl-studio-backend/src/web/views.py`

Socket event envelopes now always include:

- `request_id` (required, generated when missing)
- optional `correlation_id`

## 3) Persistence Schema Freeze

Schema and ORM updates:

- `app/llmctl-studio-backend/src/core/db.py`
- `app/llmctl-studio-backend/src/core/models.py`

### 3.1 `flowchart_run_nodes` additions

- `output_contract_version` (`v1`)
- `routing_contract_version` (`v1`)
- `degraded_status` (bool)
- `degraded_reason` (text)
- `idempotency_key` (unique when present)

### 3.2 `node_artifacts` additions

- `contract_version` (`v1`)
- `idempotency_key` (unique when present)

### 3.3 new table `runtime_idempotency_keys`

- `scope`
- `idempotency_key`
- `first_seen_at`
- `last_seen_at`
- `hit_count`
- uniqueness on (`scope`, `idempotency_key`)

### 3.4 runtime write-path enforcement

- Node-run contract/degraded markers are set during create/success/failure paths.
- Artifact contract metadata and idempotency keys are persisted on all special-node artifact writes.
- Dispatch idempotency now uses DB-backed keys with in-memory fallback.

## 4) Socket Event Contract Naming Freeze

Realtime event contracts now canonicalize event names to `domain:entity:action`:

- canonicalization helper: `canonical_socket_event_type(...)`
- canonical envelope/emit flow: `app/llmctl-studio-backend/src/services/realtime_events.py`

Behavioral freeze:

- Existing dotted names are normalized (for example `node.task.updated` -> `node:task:updated`).
- Canonical event name is used for socket emits.
- Envelope preserves `legacy_event_type` when normalization changed the incoming value.

## 5) Automated Evidence

Executed with repository virtualenv interpreter:

1. `./.venv/bin/python app/llmctl-studio-backend/tests/test_realtime_events_stage6.py`
2. `./.venv/bin/python app/llmctl-studio-backend/tests/test_node_executor_stage6.py`
3. `./.venv/bin/python app/llmctl-studio-backend/tests/test_runtime_contracts_stage3.py`

Result: all above suites passed.
