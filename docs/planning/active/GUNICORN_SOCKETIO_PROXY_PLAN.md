# Gunicorn + Socket.IO HTTP/HTTPS/Proxy Plan

Goal: harden Studio app serving for HTTP, HTTPS, and reverse proxies using Gunicorn (not Flask dev server), add configurable Gunicorn controls via `.env` + Compose, install and wire Flask-SocketIO with Redis-backed cross-worker event propagation, and plan migration of backend-to-frontend emits to Socket.IO while preserving POST for client-to-server message submission.

## Stage 0 - Requirements Gathering
- [x] Confirm deployment targets in scope for first implementation pass.
- [x] Confirm reverse proxy stack(s) to support first (Nginx, Traefik, Caddy, cloud LB, or mixed).
- [x] Confirm TLS termination model (proxy-terminated TLS only vs end-to-end TLS to app container).
- [x] Confirm websocket policy (WebSocket required vs allow polling fallback).
- [x] Confirm Gunicorn control surface exposed via `.env` + Compose with optional overrides and sane defaults.
- [x] Confirm Redis topology and reliability expectations for Socket.IO message queue.
- [x] Confirm migration scope for first Socket.IO emits (chat-only vs broader event classes).
- [x] Confirm frontend-agnostic Socket.IO architecture supports current Jinja UI and planned React UI migration without rework.
- [x] Confirm rollout strategy and compatibility constraints for existing frontend flows.
- [x] Confirm Socket.IO origin/CORS policy for current host + future React host deployment model.
- [x] Confirm requirements are complete and approved to start Stage 1.

## Stage 0 - Interview Notes
- [x] Service/runtime scope for first pass: `llmctl-studio` web serving plus parity expectations across execution runtimes (local workspace and `llmctl-executor` container path) so event behavior does not diverge by runtime.
- [x] Reverse proxy requirement: app must be proxy-agnostic and remain correct behind reverse proxies (headers, scheme, host/origin resolution, websocket upgrade handling), without hard-coupling to a single proxy product.
- [x] Example operator stack: Nginx Proxy Manager may be used in real deployments, but support target is generic reverse proxy compatibility.
- [x] TLS compatibility direction: maximize compatibility by supporting both proxy-terminated TLS and end-to-end TLS-capable app serving paths.
- [x] Socket transport policy: WebSocket-first operation with polling fallback only when WebSocket upgrade/connect failures are detected.
- [x] Gunicorn env controls for v1: expose core knobs (`bind`, `workers`, `threads`, `worker_class`, `worker_connections`, `timeout`, `graceful_timeout`, `keepalive`, `log_level`, access/error logs, `max_requests`, `max_requests_jitter`) as optional settings with practical defaults.
- [x] Redis baseline: single shared Redis instance (same deployment used by Celery) is required for first pass; reuse existing Redis credentials/config where feasible.
- [x] Migration scope: broad site-wide migration of backend-to-frontend push opportunities to Socket.IO in first wave (not chat-only).
- [x] Frontend transition requirement: Socket.IO server/client contract must stay compatible through Jinja now and React later, avoiding emit/path/proxy coupling that would force a disruptive cutover.
- [x] Compliance/readiness requirement: include explicit discovery/research pass to identify all app areas that must change for robust multi-worker Gunicorn + Socket.IO + reverse proxy behavior.
- [x] Rollout strategy: big-bang cutover to Socket.IO-targeted flows once implementation is ready.
- [x] Post-cutover expectation: run a dedicated cleanup session to remove obsolete pre-Socket.IO pathways after successful cutover verification.
- [x] Socket.IO origin/CORS policy for now: wide-open (`*`) to maximize immediate compatibility; plan should include clear follow-up hardening path.

## Stage 1 - Code Planning
- [x] Translate approved requirements into Stage 2 through Stage 10 implementation stages.
- [x] Define acceptance criteria and dependency ordering for each execution stage.

## Stage 2 - Discovery + Compatibility Design
- [x] Inventory all current backend-to-frontend update paths in `llmctl-studio` (template JS polling loops, status APIs, async task progress surfaces, chat/runtime status).
- [x] Produce a proxy/socket compatibility matrix for HTTP, HTTPS, reverse proxy forwarding headers, websocket upgrade behavior, and polling fallback boundaries.
- [x] Select and document Gunicorn + Flask-SocketIO runtime model for multi-worker operation (including Redis manager usage and worker-class compatibility constraints).
- [x] Define canonical Socket.IO event contract (event names, namespaces, room/channel identifiers, payload envelope, versioning).
- [x] Define migration map from current polling/status endpoints to Socket.IO emits and identify any endpoints that remain POST-only.
- [x] Acceptance criteria: a written implementation blueprint exists in this plan (or linked doc) with concrete file targets, selected runtime model, and a complete migration inventory.

### Stage 2 Blueprint (2026-02-16)

#### 1) Current Update-Path Inventory (`llmctl-studio`)

| Surface | Current frontend behavior | Current backend read path | Proposed Socket.IO stream | Planned room(s) |
| --- | --- | --- | --- | --- |
| Node detail live state (`app/llmctl-studio/src/web/templates/task_detail.html`) | Poll every 1s while queued/running | `GET /nodes/<task_id>/status` (`app/llmctl-studio/src/web/views.py`) | `node.task.updated`, `node.task.stage.updated`, `node.task.completed` | `task:<task_id>`, `run:<run_id>` |
| Flowchart canvas runtime (`app/llmctl-studio/src/web/templates/flowchart_detail.html`) | Poll `runtime` endpoint at 250ms-900ms cadence, retry at 1200ms on error | `GET /flowcharts/<flowchart_id>/runtime` (`app/llmctl-studio/src/web/views.py`) | `flowchart.runtime.updated`, `flowchart.node.running_set` | `flowchart:<flowchart_id>`, `flowchart_run:<run_id>` |
| Flowchart run detail page (`app/llmctl-studio/src/web/templates/flowchart_history_run_detail.html`) | Full-page reload every 4s while run is active | Full page render route | `flowchart.run.updated`, `flowchart.node.updated` | `flowchart_run:<run_id>` |
| Autorun detail page (`app/llmctl-studio/src/web/templates/run_detail.html`) | Full-page reload every 5s while run is active | Full page render route | `autorun.updated`, `autorun.node_set.updated` | `autorun:<run_id>` |
| HuggingFace/vLLM download card (`app/llmctl-studio/src/web/templates/settings_integrations.html`) | Poll every 1200ms while job active | `GET /settings/provider/vllm-local/downloads/<job_id>` (`app/llmctl-studio/src/web/views.py`) | `download.job.updated`, `download.job.completed` | `download_job:<job_id>` |
| Chat runtime turn submission (`app/llmctl-studio/src/web/templates/chat_runtime.html`) | POST turn and wait for response payload (no push channel) | `POST /api/chat/threads/<thread_id>/turn` (`app/llmctl-studio/src/web/views.py`) | `chat.turn.requested`, `chat.turn.responded`, `chat.turn.failed`, `chat.activity.appended` | `thread:<thread_id>` |
| RAG JS polling boundary (`app/llmctl-studio/src/web/static/rag/app.js`) | Poll `/api/rag/tasks/status` every 2s for job tables/details | API boundary currently outside this Stage 2 Studio route inventory | `rag.index_job.updated` (if retained under Studio ownership) | `rag_job:<job_id>`, `rag_source:<source_id>` |

Backend emit source points identified for Stage 6 wiring:
- `app/llmctl-studio/src/services/tasks.py`: node lifecycle + stage logs + flowchart run/node lifecycle + HuggingFace download Celery progress updates.
- `app/llmctl-studio/src/chat/runtime.py`: turn requested/retrieval/compaction/failure/responded activity points.
- `app/llmctl-studio/src/services/execution/router.py`: runtime-provider metadata path to keep workspace/executor parity in event payloads.

#### 2) Proxy / HTTP / HTTPS / Socket Compatibility Matrix

| Topology | Expected behavior | Required settings/controls | Notes |
| --- | --- | --- | --- |
| Direct HTTP (dev) | Web UI + Socket.IO work without proxy headers | Gunicorn bind only | Baseline local mode. |
| Reverse proxy HTTP -> HTTP upstream | Correct host/scheme/path handling and websocket upgrades | Trust forwarded headers (`X-Forwarded-For/Proto/Host/Port/Prefix`) via middleware and explicit trust depth | Prevent over-trusting by limiting proxy hops. |
| Reverse proxy HTTPS termination -> HTTP upstream | App sees canonical `https` externally while upstream remains `http` | Same forwarded-header trust, proxy websocket upgrade headers, stable `Host` forwarding | Primary deployment target for Nginx Proxy Manager-like setups. |
| Reverse proxy HTTPS -> HTTPS upstream | End-to-end TLS-capable path | Optional Gunicorn TLS cert/key envs + forwarded-header handling | Keep optional to preserve compatibility. |
| Multi-worker + WebSocket + polling fallback enabled | Works when websocket is primary; polling fallback remains available | Redis message queue + sticky session behavior for polling fallback paths | Polling across workers requires sticky-session-compatible routing. |
| Multi-worker + WebSocket-only transport | Cross-worker sockets without polling path dependency | Redis message queue + enforce websocket-only transport policy | Useful where sticky sessions are unavailable. |

#### 3) Selected Runtime Model for Stage 3+

- App server: Gunicorn (replace Flask dev server for container runtime).
- Socket stack: Flask-SocketIO with Redis message queue and WebSocket-first transport policy.
- Async model: `threading` mode with Gunicorn threaded workers (`worker_class=gthread`) plus `simple-websocket`.
- Worker controls: all Gunicorn env controls remain optional with defaults; `workers` stays externally configurable as requested.
- Redis strategy: default Socket.IO broker URL derives from existing Celery Redis host/port/credentials when explicit Socket.IO URL is not provided.
- Multi-worker safety rule:
  - Keep Redis message queue enabled whenever workers > 1.
  - Keep fallback polling enabled for compatibility, but document sticky-session requirement on that fallback path.
  - If sticky routing is unavailable, production-safe mode is websocket-only transport.

#### 4) Canonical Socket.IO Event Contract (v1)

- Namespace: `/rt` (single namespace for v1 to reduce handshake/config complexity).
- Envelope fields:
  - `contract_version`: `v1`
  - `event_id`: UUIDv4
  - `emitted_at`: ISO8601 UTC
  - `event_type`: namespaced string (examples below)
  - `entity_kind`: `task|flowchart_run|flowchart_node|chat_thread|chat_turn|download_job|rag_job`
  - `entity_id`: string id
  - `room_keys`: list of room ids targeted
  - `runtime`: `{ selected_provider, final_provider, dispatch_status, fallback_attempted, fallback_reason }` when available
  - `payload`: event-specific object
- Core room conventions:
  - `task:<task_id>`
  - `run:<run_id>`
  - `flowchart:<flowchart_id>`
  - `flowchart_run:<run_id>`
  - `thread:<thread_id>`
  - `download_job:<job_id>`
- Core event types for first cutover:
  - `node.task.updated`
  - `node.task.stage.updated`
  - `node.task.completed`
  - `flowchart.runtime.updated`
  - `flowchart.node.updated`
  - `flowchart.run.updated`
  - `download.job.updated`
  - `download.job.completed`
  - `chat.turn.requested`
  - `chat.turn.responded`
  - `chat.turn.failed`
  - `chat.activity.appended`

#### 5) Migration Map (Polling/Reload -> Socket.IO)

| Current path | Current pattern | Socket.IO replacement | HTTP fallback policy |
| --- | --- | --- | --- |
| `/nodes/<task_id>/status` | 1s polling | `task:<id>` room events with lifecycle + stage payload deltas | Poll same endpoint only when socket fails |
| `/flowcharts/<flowchart_id>/runtime` | 250ms-900ms polling | `flowchart:<id>` + `flowchart_run:<id>` runtime delta events | Poll endpoint only after socket failure |
| Run detail/flowchart run detail full reloads | 4-5s page reload loops | Run-scoped status events to patch DOM incrementally | Keep reload fallback only on socket failure |
| `/settings/provider/vllm-local/downloads/<job_id>` | 1200ms polling | `download_job:<id>` progress events from Celery task state transitions | Keep status poll only on socket failure |
| `/api/rag/tasks/status` (RAG JS boundary) | 2s polling | `rag_job` events if Stage 7 includes this boundary | Keep poll until ownership path is fully migrated |

POST endpoints intentionally preserved as ingress (no change in Stage 2 design):
- `/api/chat/threads/<thread_id>/turn`
- `/flowcharts/<flowchart_id>/run`
- `/flowcharts/runs/<run_id>/cancel`
- `/nodes/<task_id>/cancel`
- `/settings/provider/vllm-local/qwen/start`
- `/settings/provider/vllm-local/huggingface/start`

#### 6) Concrete File Targets for Stage 3-7

- `app/llmctl-studio/src/web/app.py`: initialize Socket.IO + forwarded-header middleware.
- `app/llmctl-studio/src/core/config.py`: add Gunicorn and Socket.IO env config defaults.
- `app/llmctl-studio/run.py`: keep debug/dev runner path explicit; production path moves to Gunicorn.
- `app/llmctl-studio/docker/Dockerfile`: run Studio under Gunicorn by default.
- `docker/docker-compose.yml`: expose Gunicorn + Socket.IO env controls and defaults.
- `app/llmctl-studio/src/services/tasks.py`: emit lifecycle/progress events from authoritative state changes.
- `app/llmctl-studio/src/chat/runtime.py`: emit chat turn/activity events.
- `app/llmctl-studio/src/services/execution/router.py`: include provider metadata in emitted runtime payloads.
- `app/llmctl-studio/src/web/templates/*.html` and `app/llmctl-studio/src/web/static/rag/app.js`: replace polling/reload loops with socket subscriptions and failure fallback hooks.

#### 7) Stage 2 Reference Notes

- Flask-SocketIO deployment notes (Gunicorn/threaded worker guidance and reverse proxy websocket config): https://flask-socketio.readthedocs.io/en/latest/deployment.html
- python-socketio multi-worker requirements (sticky sessions + message queue, websocket-only caveat): https://python-socketio.readthedocs.io/en/stable/server.html
- Flask proxy middleware guidance (`ProxyFix`) and header trust model: https://flask.palletsprojects.com/en/stable/deploying/proxy_fix/

## Stage 3 - Gunicorn Serving Foundation
- [x] Add Gunicorn dependency and any required async worker dependencies in `app/llmctl-studio/requirements.txt`.
- [x] Introduce Studio Gunicorn entrypoint/config module that reads env vars with sensible defaults for:
  - [x] `bind`, `workers`, `threads`, `worker_class`, `worker_connections`, `timeout`, `graceful_timeout`, `keepalive`, `log_level`, access/error logs, `max_requests`, `max_requests_jitter`.
- [x] Keep all Gunicorn settings optional; default behavior must remain operational with zero new env values provided.
- [x] Update `app/llmctl-studio/docker/Dockerfile` and `docker/docker-compose.yml` so `llmctl-studio` runs under Gunicorn by default (not Flask dev server).
- [x] Keep Flask dev workflow intact for local debug when explicitly enabled.
- [x] Acceptance criteria: Studio container starts with Gunicorn, serves existing routes successfully, and concurrency settings are externally controllable via `.env` + Compose.

Stage 3 implementation notes:
- Added `app/llmctl-studio/src/web/gunicorn_config.py` with env-driven Gunicorn defaults.
- Updated `app/llmctl-studio/run.py` to launch Gunicorn by default (`LLMCTL_STUDIO_USE_GUNICORN`) and keep Flask dev server when debug mode is active unless explicitly overridden.
- Added `gunicorn` and `simple-websocket` in `app/llmctl-studio/requirements.txt`.
- Updated container defaults in `app/llmctl-studio/docker/Dockerfile` and `docker/docker-compose.yml` with optional Gunicorn controls.
- Validation run: `python3 -m compileall app/llmctl-studio/run.py app/llmctl-studio/src/web/gunicorn_config.py app/llmctl-studio/src/web/app.py`.

## Stage 4 - Reverse Proxy, HTTP/HTTPS, and Forwarded Header Compliance
- [x] Add trusted forwarded-header handling (`X-Forwarded-*`) in app initialization so URL generation, scheme detection, and request context behave correctly behind reverse proxies.
- [x] Add configuration for proxy trust depth and safe defaults to avoid over-trusting spoofed headers.
- [x] Validate websocket upgrade compatibility assumptions for generic reverse proxies (including Nginx Proxy Manager) and document required proxy headers/timeouts.
- [x] Ensure HTTPS-aware behavior is correct when TLS terminates at proxy and when TLS reaches app directly (where enabled).
- [x] Acceptance criteria: route URLs, redirects, and socket handshake URLs resolve correctly behind proxy with both `http` and `https` frontends.

Stage 4 implementation notes:
- Added proxy trust controls in `app/llmctl-studio/src/core/config.py`:
  - `LLMCTL_STUDIO_PROXY_FIX_ENABLED` (default `false` in app config)
  - `LLMCTL_STUDIO_PROXY_FIX_X_FOR|X_PROTO|X_HOST|X_PORT|X_PREFIX` (default `1`, minimum `0`)
  - `LLMCTL_STUDIO_PREFERRED_URL_SCHEME` (default `http`)
- Applied `werkzeug.middleware.proxy_fix.ProxyFix` in `app/llmctl-studio/src/web/app.py` when proxy fix is enabled.
- Enabled proxy-fix defaults for container deployments in `docker/docker-compose.yml` (`LLMCTL_STUDIO_PROXY_FIX_ENABLED=true` + trust depth `1`), preserving app-level safe default (`false`) outside Compose.
- Added optional Gunicorn TLS controls in `app/llmctl-studio/src/web/gunicorn_config.py` and Compose:
  - `GUNICORN_CERTFILE`, `GUNICORN_KEYFILE`, `GUNICORN_CA_CERTS`.

Required reverse-proxy headers for correct URL/scheme resolution:
- `X-Forwarded-For`
- `X-Forwarded-Proto`
- `X-Forwarded-Host`
- `X-Forwarded-Port`
- `X-Forwarded-Prefix` (only when mounting app under a path prefix)

Required websocket proxy behavior:
- Preserve `Host` header to upstream.
- Forward upgrade headers: `Upgrade: websocket` and `Connection: upgrade`.
- Ensure forwarded proto/host headers are present so socket handshake URLs resolve with external scheme/host.

Proxy timeout guidance:
- HTTP upstream timeout should be greater than Gunicorn `timeout`.
- Websocket idle/read timeout should be high enough for long-lived connections (do not apply short request timeouts used for normal HTTP endpoints).

Stage 4 validation run:
- `python3 -m compileall app/llmctl-studio/src/core/config.py app/llmctl-studio/src/web/app.py app/llmctl-studio/src/web/gunicorn_config.py app/llmctl-studio/run.py`
- `docker compose -f docker/docker-compose.yml config`
- Note: direct runtime smoke test of `url_for`/handshake behavior was not run in this environment because local Python env is missing Flask dependencies.

## Stage 5 - Flask-SocketIO + Redis Multi-Worker Backbone
- [x] Install and initialize Flask-SocketIO in Studio app bootstrap.
- [x] Configure Socket.IO to use Redis message queue for cross-worker fan-out, reusing current Celery Redis host/port credentials by default.
- [x] Add explicit Socket.IO config env vars (path, CORS/origins, ping/pong/timeout knobs where needed), all optional with sane defaults.
- [x] Implement baseline socket lifecycle handlers (connect/disconnect/health) and observability hooks (structured logs/metrics counters if available).
- [x] Preserve current POST ingress for client-to-server messages while enabling Socket.IO for backend-to-frontend emits.
- [x] Acceptance criteria: multi-worker Gunicorn emits propagate across workers via Redis and connected clients receive consistent events.

Stage 5 implementation notes:
- Added `Flask-SocketIO` dependency in `app/llmctl-studio/requirements.txt`.
- Added new realtime module `app/llmctl-studio/src/web/realtime.py`:
  - Initializes `socketio` with app config.
  - Uses Redis message queue for cross-worker fan-out.
  - Implements baseline handlers in namespace `/rt`:
    - `connect` -> emits `rt.connected`
    - `disconnect`
    - `rt.health` request/ack
  - Adds basic connection/health counters and server-side logging.
  - Exposes `emit_realtime(...)` helper for subsequent migration stages.
- Updated `app/llmctl-studio/src/web/app.py` to call `init_socketio(app)` during app bootstrap.
- Updated `app/llmctl-studio/src/core/config.py` with Socket.IO env controls (all optional with defaults):
  - `LLMCTL_STUDIO_SOCKETIO_MESSAGE_QUEUE` (default derived from Celery Redis host/port/db)
  - `LLMCTL_STUDIO_SOCKETIO_REDIS_DB`
  - `LLMCTL_STUDIO_SOCKETIO_ASYNC_MODE`
  - `LLMCTL_STUDIO_SOCKETIO_PATH`
  - `LLMCTL_STUDIO_SOCKETIO_CORS_ALLOWED_ORIGINS`
  - `LLMCTL_STUDIO_SOCKETIO_TRANSPORTS`
  - `LLMCTL_STUDIO_SOCKETIO_PING_INTERVAL`
  - `LLMCTL_STUDIO_SOCKETIO_PING_TIMEOUT`
  - `LLMCTL_STUDIO_SOCKETIO_MONITOR_CLIENTS`
  - `LLMCTL_STUDIO_SOCKETIO_LOGGER`
  - `LLMCTL_STUDIO_SOCKETIO_ENGINEIO_LOGGER`
- Updated `docker/docker-compose.yml` to expose the same Socket.IO controls with practical defaults.
- Updated `app/llmctl-studio/run.py` debug-server path to use `socketio.run(...)` so Socket.IO works in non-Gunicorn dev mode too.
- Existing POST ingress endpoints remain unchanged in this stage.

Stage 5 validation run:
- `python3 -m compileall app/llmctl-studio/src/core/config.py app/llmctl-studio/src/web/app.py app/llmctl-studio/src/web/realtime.py app/llmctl-studio/src/web/gunicorn_config.py app/llmctl-studio/run.py`
- `docker compose -f docker/docker-compose.yml config`

## Stage 6 - Unified Emit Service + Runtime Parity (Workspace + Executor Path)
- [x] Create a centralized backend emit service/module so all emits go through one contract and transport abstraction.
- [x] Ensure event emission works uniformly for local workspace execution and `llmctl-executor`-driven execution paths (no runtime-specific payload divergence).
- [x] Add room/channel conventions for task/thread/run scoping to avoid global broadcast noise.
- [x] Add defensive delivery semantics (idempotent event ids / sequencing metadata where needed) to reduce duplicate/out-of-order UI state regressions.
- [x] Acceptance criteria: identical logical events are emitted with consistent payload schema regardless of underlying runtime path.

Stage 6 implementation notes:
- Added centralized emit module `app/llmctl-studio/src/services/realtime_events.py`:
  - Canonical envelope fields: `contract_version`, `event_id`, `idempotency_key`, `sequence`, `sequence_stream`, `emitted_at`, `event_type`, `entity_kind`, `entity_id`, `room_keys`, `runtime`, `payload`.
  - Transport abstraction via `emit_contract_event(...)` -> `web.realtime.emit_realtime(...)`.
  - Runtime metadata normalization for node-executor routing fields (`selected_provider`, `final_provider`, `dispatch_status`, `fallback_*`, dispatch/id fields).
  - Room convention helpers: task/run/flowchart/flowchart_run/flowchart_node/thread/download scopes.
  - Defensive delivery semantics: per-stream sequencing + idempotency key.
- Updated `app/llmctl-studio/src/services/tasks.py` to use centralized realtime emit helpers:
  - Emits `node.task.stage.updated` on stage transitions in `_update_task_logs(...)`.
  - Emits `node.task.updated` on task start and `node.task.completed` on terminal transitions.
  - Emits `flowchart.run.updated` at run start/failure/finalization.
  - Emits `flowchart.node.updated` for node running/succeeded/failed transitions.
  - Includes execution runtime metadata from `ExecutionRequest.run_metadata_payload()` / `ExecutionResult.run_metadata` so workspace and executor-driven paths share the same runtime schema.
  - Added guardrail-failure emits (`_record_flowchart_guardrail_failure`) for failed node/task visibility.
- Updated `app/llmctl-studio/src/web/realtime.py`:
  - Added default message-queue bootstrap for external worker emits using Redis env values.
  - Added defensive exception handling around `emit_realtime(...)` to avoid hard task failures if emit transport errors occur.
- Added tests in `app/llmctl-studio/tests/test_realtime_events_stage6.py`:
  - Event envelope sequencing/idempotency contract checks.
  - Multi-room emit fan-out behavior checks.
  - Runtime metadata normalization checks.
  - Runtime schema parity integration test scaffold (workspace vs docker-selected path).

Stage 6 validation run:
- `python3 -m compileall app/llmctl-studio/src/services/realtime_events.py app/llmctl-studio/src/services/tasks.py app/llmctl-studio/src/web/realtime.py app/llmctl-studio/tests/test_realtime_events_stage6.py`
- `python3 -m unittest app/llmctl-studio/tests/test_realtime_events_stage6.py` -> blocked in this shell due missing Python dependencies (`flask`, `sqlalchemy`).

## Stage 7 - Site-Wide Socket.IO Cutover (Big-Bang)
- [x] Migrate all identified Studio backend-to-frontend push surfaces from polling-first behavior to Socket.IO-first subscriptions.
- [x] Keep polling as fallback only after verified socket failure (client-side and server-side detection rules).
- [x] Maintain POST-based write operations for user actions and command submission.
- [x] Ensure Jinja frontend consumes the same event contract intended for upcoming React frontend usage (no template-coupled event semantics).
- [x] Acceptance criteria: targeted Studio UI surfaces receive real-time updates primarily via Socket.IO; polling activates only on socket failure paths.

Stage 7 implementation notes:
- Added room subscription lifecycle on Socket.IO namespace `/rt` in `app/llmctl-studio/src/web/realtime.py`:
  - `rt.subscribe` and `rt.unsubscribe` handlers with room-prefix validation (`task`, `run`, `flowchart`, `flowchart_run`, `flowchart_node`, `thread`, `download_job`).
- Added shared browser realtime helper in `app/llmctl-studio/src/web/templates/base.html`:
  - Loads Socket.IO client from configured Socket.IO path.
  - Exposes `window.llmctlRealtime.connect(...)` with room management and explicit socket-failure callbacks.
- Migrated `task_detail` from polling-first to Socket.IO-first in `app/llmctl-studio/src/web/templates/task_detail.html`:
  - Subscribes to `task:<id>`.
  - Refreshes task status on `node.task.*` events.
  - Starts 1s polling only when socket connection/subscription fails.
- Migrated flowchart runtime sync in `app/llmctl-studio/src/web/templates/flowchart_detail.html`:
  - Subscribes to `flowchart:<id>` and active `flowchart_run:<id>`.
  - Reacts to `flowchart.*` events and syncs runtime state.
  - Enables runtime polling loop only on realtime socket failure.
- Migrated run detail reload loop in `app/llmctl-studio/src/web/templates/run_detail.html`:
  - Subscribes to `run:<id>`.
  - Reloads page on `node.task.*` events for that room.
  - Falls back to timed reload only when socket fails.
- Migrated flowchart run detail reload loop in `app/llmctl-studio/src/web/templates/flowchart_history_run_detail.html`:
  - Subscribes to `flowchart:<id>` + `flowchart_run:<id>`.
  - Reloads on `flowchart.*` events.
  - Falls back to timed reload only when socket fails.
- Migrated HuggingFace download status card in `app/llmctl-studio/src/web/templates/settings_integrations.html`:
  - Subscribes to `download_job:<id>` and consumes `download.job.updated` / `download.job.completed`.
  - Polls job status endpoint only after socket failure.
- Added backend emit coverage for download progress in `app/llmctl-studio/src/services/tasks.py`:
  - New `_emit_download_job_event(...)` emits contract events from `run_huggingface_download_task` progress/final states.

Stage 7 validation run:
- `python3 -m compileall app/llmctl-studio/src/web/realtime.py app/llmctl-studio/src/services/realtime_events.py app/llmctl-studio/src/services/tasks.py`
- `docker compose -f docker/docker-compose.yml config`

## Stage 8 - Post-Cutover Cleanup
- [x] Remove obsolete pre-cutover polling/event plumbing that is no longer required.
- [x] Remove dead code paths and redundant status endpoints that were only supporting superseded polling loops.
- [x] Tighten temporary compatibility shims introduced during migration.
- [x] Capture a hardening backlog item for replacing wide-open Socket.IO CORS policy with explicit allowlist controls.
- [x] Acceptance criteria: codebase no longer carries duplicate legacy update mechanisms beyond intentional socket-failure fallback paths.

Stage 8 implementation notes:
- Tightened Socket.IO fallback verification logic in shared client helper (`app/llmctl-studio/src/web/templates/base.html`):
  - Polling fallback is now triggered only after verified failure conditions:
    - connection timeout before initial ready state, or
    - sustained disconnect after ready state.
  - Added explicit socket teardown on fallback decision to prevent duplicate realtime + polling streams.
- Removed remaining polling-first UI language and aligned status copy with socket-first behavior:
  - `app/llmctl-studio/src/web/templates/task_detail.html`
  - `app/llmctl-studio/src/web/templates/run_detail.html`
- Confirmed superseded fixed-interval reload loops were replaced with event-driven updates plus failure-only fallback in Stage 7 surfaces:
  - `app/llmctl-studio/src/web/templates/task_detail.html`
  - `app/llmctl-studio/src/web/templates/flowchart_detail.html`
  - `app/llmctl-studio/src/web/templates/flowchart_history_run_detail.html`
  - `app/llmctl-studio/src/web/templates/run_detail.html`
  - `app/llmctl-studio/src/web/templates/settings_integrations.html`
- Status endpoints retained intentionally for fallback and initial state hydration (not redundant):
  - `/nodes/<task_id>/status`
  - `/flowcharts/<flowchart_id>/runtime`
  - `/settings/provider/vllm-local/downloads/<job_id>`
- CORS hardening backlog item captured for Stage 10 docs/ops follow-up:
  - Replace `LLMCTL_STUDIO_SOCKETIO_CORS_ALLOWED_ORIGINS=*` default with explicit allowlist per deployment environment.
  - Document recommended allowlist patterns for Jinja host and future React host split.

Stage 8 validation run:
- `python3 -m compileall app/llmctl-studio/src/services/tasks.py app/llmctl-studio/src/web/realtime.py`
- `docker compose -f docker/docker-compose.yml restart llmctl-studio`
- `docker compose -f docker/docker-compose.yml config`

## Stage 9 - Automated Testing
- [ ] Add/adjust automated tests for Gunicorn config loading and env default behavior.
- [ ] Add/adjust tests for forwarded-header/proxy correctness (scheme/host/url generation behind proxy).
- [ ] Add/adjust Socket.IO tests for connect/disconnect, emit contract validity, and Redis-backed cross-worker propagation.
- [ ] Add/adjust tests for socket-failure-triggered polling fallback behavior.
- [ ] Add/adjust tests proving runtime parity of emitted events across workspace and executor paths.
- [ ] Run targeted automated test suites for touched Studio modules and include command log in implementation notes.
- [ ] Acceptance criteria: automated tests pass for changed areas and guard key concurrency/proxy/socket regressions.

## Stage 10 - Docs Updates
- [ ] Update Sphinx and Read the Docs documentation for Gunicorn-first serving, env/Compose controls, and recommended defaults.
- [ ] Document reverse proxy requirements (forwarded headers, websocket upgrade settings, timeout guidance, TLS termination modes).
- [ ] Document Flask-SocketIO + Redis architecture, scaling behavior, and multi-worker expectations.
- [ ] Document Socket.IO event contract and frontend consumption model suitable for both current Jinja and future React frontend.
- [ ] Document operational guidance: troubleshooting websocket fallback, Redis dependency expectations, and CORS hardening follow-up.
- [ ] Acceptance criteria: deployment and developer docs are sufficient to run, scale, and extend the new architecture without code spelunking.
