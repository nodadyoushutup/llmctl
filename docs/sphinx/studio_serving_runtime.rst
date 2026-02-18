Studio Serving Runtime
======================

Overview
--------

Studio now runs with a Gunicorn-first serving model and Socket.IO-first
backend-to-frontend updates. The runtime is designed for:

- direct HTTP development
- HTTPS and reverse-proxy deployments
- multi-worker Gunicorn with Redis-backed Socket.IO fan-out
- PostgreSQL-backed persistent metadata (SQLite is not supported)
- React-only Studio UI served by ``llmctl-studio-frontend``

Database Configuration
----------------------

Studio requires PostgreSQL for all runtime database access.

Set one of the following:

- ``LLMCTL_STUDIO_DATABASE_URI`` (full PostgreSQL SQLAlchemy URI)
- ``LLMCTL_POSTGRES_HOST``, ``LLMCTL_POSTGRES_PORT``,
  ``LLMCTL_POSTGRES_DB``, ``LLMCTL_POSTGRES_USER``,
  ``LLMCTL_POSTGRES_PASSWORD``

Startup DB Health Check
-----------------------

Studio performs DB preflight checks before web/API startup. The preflight verifies:

- database connectivity (``SELECT 1``)
- schema readiness by creating/migrating tables
- presence of required core tables

Optional controls:

- ``LLMCTL_STUDIO_DB_HEALTHCHECK_ENABLED`` (default ``true``)
- ``LLMCTL_STUDIO_DB_HEALTHCHECK_TIMEOUT_SECONDS`` (default ``60``)
- ``LLMCTL_STUDIO_DB_HEALTHCHECK_INTERVAL_SECONDS`` (default ``2``)

Standalone CLI check:

.. code-block:: bash

   python3 app/llmctl-studio-backend/scripts/check_database_health.py

Local Backend Test Bootstrap
----------------------------

To avoid local test runs failing when PostgreSQL wiring is missing, use the
test wrapper script. It starts a disposable local PostgreSQL container,
exports ``LLMCTL_STUDIO_DATABASE_URI``, and runs your test command.

Run a targeted backend test:

.. code-block:: bash

   bash app/llmctl-studio-backend/scripts/with_test_postgres.sh -- \
     .venv/bin/python3 -m unittest app/llmctl-studio-backend/tests/test_node_executor_stage4.py

Run full backend test discovery:

.. code-block:: bash

   bash app/llmctl-studio-backend/scripts/with_test_postgres.sh

Useful options:

- ``--keep-container``: keep the test PostgreSQL container running after tests.
- ``--skip-dep-check``: skip Python dependency import preflight.
- ``--python <path>``: use a specific Python binary.
- default local DB port is ``15432``; if busy, the script auto-selects a free port.

Integrated MCP Startup Gate (Kubernetes)
----------------------------------------

In Kubernetes deployments, Studio backend startup is guarded by init-container
``wait-for-integrated-mcp`` in ``kubernetes/llmctl-studio/base/studio-deployment.yaml``.

Purpose:

- enforce MCP-first startup ordering during one-release cutover
- prevent Studio migration/seed sync from racing unavailable MCP services

Controls (``kubernetes/llmctl-studio/base/studio-configmap.yaml``):

- ``LLMCTL_STUDIO_MCP_WAIT_ENABLED`` (default ``true``)
- ``LLMCTL_STUDIO_MCP_WAIT_TIMEOUT_SECONDS`` (default ``240``)
- ``LLMCTL_STUDIO_MCP_REQUIRED_ENDPOINTS`` (comma-separated URL list; default
  includes ``http://llmctl-mcp.<namespace>.svc.cluster.local:9020/mcp``)

If the gate times out, Studio pod startup fails fast. For rollback/debug
scenarios, set ``LLMCTL_STUDIO_MCP_WAIT_ENABLED=false`` to bypass the wait.

SQLite One-Time Migration Utility
---------------------------------

For existing local SQLite data, use the one-time copy tool:

.. code-block:: bash

   python3 app/llmctl-studio-backend/scripts/migrate_sqlite_to_postgres.py \
     --sqlite-path data/llmctl-studio.sqlite3 \
     --truncate-target

Gunicorn-First Serving
----------------------

Container runtime defaults to Gunicorn via ``LLMCTL_STUDIO_USE_GUNICORN=true``.
Flask debug server remains available for local debug paths.

Primary Gunicorn controls are optional and read from environment variables:

- bind/listen: ``GUNICORN_BIND``
- concurrency: ``GUNICORN_WORKERS``, ``GUNICORN_THREADS``,
  ``GUNICORN_WORKER_CLASS``, ``GUNICORN_WORKER_CONNECTIONS``
- lifecycle/timeouts: ``GUNICORN_TIMEOUT``, ``GUNICORN_GRACEFUL_TIMEOUT``,
  ``GUNICORN_KEEPALIVE``
- logging: ``GUNICORN_LOG_LEVEL``, ``GUNICORN_ACCESS_LOG``,
  ``GUNICORN_ERROR_LOG``
- recycle controls: ``GUNICORN_MAX_REQUESTS``,
  ``GUNICORN_MAX_REQUESTS_JITTER``
- optional upstream TLS: ``GUNICORN_CERTFILE``, ``GUNICORN_KEYFILE``,
  ``GUNICORN_CA_CERTS``
- control socket: ``GUNICORN_CONTROL_SOCKET``,
  ``GUNICORN_CONTROL_SOCKET_MODE``, ``GUNICORN_CONTROL_SOCKET_DISABLE``

All controls have sane defaults, so zero-override startup remains operational.

Reverse Proxy and TLS
---------------------

Proxy header trust is controlled by ``ProxyFix`` settings:

- ``LLMCTL_STUDIO_PROXY_FIX_ENABLED``
- ``LLMCTL_STUDIO_PROXY_FIX_X_FOR``
- ``LLMCTL_STUDIO_PROXY_FIX_X_PROTO``
- ``LLMCTL_STUDIO_PROXY_FIX_X_HOST``
- ``LLMCTL_STUDIO_PROXY_FIX_X_PORT``
- ``LLMCTL_STUDIO_PROXY_FIX_X_PREFIX``

Required forwarded headers:

- ``X-Forwarded-For``
- ``X-Forwarded-Proto``
- ``X-Forwarded-Host``
- ``X-Forwarded-Port``
- ``X-Forwarded-Prefix`` (only when path-prefix mounting is used)

WebSocket proxy requirements:

- preserve upstream ``Host``
- forward ``Upgrade: websocket`` and ``Connection: upgrade``
- configure proxy timeouts for long-lived WebSocket connections

Supported TLS models:

- TLS terminated at proxy, HTTP upstream to Studio
- TLS terminated at proxy, HTTPS upstream to Studio (optional)
- direct HTTP for local development

Studio Route Contract (`/web` + `/api`)
----------------------------------------

Studio is split into two services on one host:

- ``/web/*`` -> ``llmctl-studio-frontend`` (React SPA)
- ``/api/*`` -> ``llmctl-studio-backend`` (Flask API + Socket.IO)

Backend policy:

- Flask no longer serves Jinja templates for user-facing pages.
- Legacy backend static/template GUI assets are removed.
- Legacy GUI assets are retained for reference under ``_legacy/llmctl-studio-backend/src/web/``.
- Non-API GUI routes are blocked in React-only runtime mode.

Frontend nginx policy:

- Proxy only ``/api/*`` to the backend service.
- No legacy catch-all proxy fallback to backend GUI routes.

Socket.IO + Redis Architecture
------------------------------

Socket.IO runs on namespace ``/rt`` and defaults to path ``/socket.io``.
Message fan-out uses Redis, reusing the same Redis deployment used by Celery.

Socket.IO controls:

- queue/path/origins: ``LLMCTL_STUDIO_SOCKETIO_MESSAGE_QUEUE``,
  ``LLMCTL_STUDIO_SOCKETIO_PATH``, ``LLMCTL_STUDIO_SOCKETIO_CORS_ALLOWED_ORIGINS``
- transport/health: ``LLMCTL_STUDIO_SOCKETIO_TRANSPORTS``,
  ``LLMCTL_STUDIO_SOCKETIO_PING_INTERVAL``,
  ``LLMCTL_STUDIO_SOCKETIO_PING_TIMEOUT``
- diagnostics: ``LLMCTL_STUDIO_SOCKETIO_MONITOR_CLIENTS``,
  ``LLMCTL_STUDIO_SOCKETIO_LOGGER``,
  ``LLMCTL_STUDIO_SOCKETIO_ENGINEIO_LOGGER``

Multi-worker expectations:

- Redis message queue is required for cross-worker event propagation.
- WebSocket transport is preferred.
- Polling fallback is supported, but production proxies/load balancers should
  provide sticky sessions when polling may be used.
- If sticky sessions are not available, prefer ``websocket``-only transport.

Celery Runtime Topology (Decoupled)
-----------------------------------

Celery execution is intentionally split from Studio backend web serving.

Runtime responsibilities:

- ``llmctl-studio-backend``: Celery producer/control-plane only (enqueue,
  revoke, status polling); no local Celery worker or beat subprocesses.
- ``llmctl-celery-worker``: consumes all Studio task queues.
- ``llmctl-celery-beat``: single scheduler deployment for periodic tasks.

Execution split:

- node-like workloads are dispatched to Kubernetes executor Jobs/Pods
  (see :doc:`node_executor_runtime`).
- chat turns are not pod-dispatched and continue on service runtime.

Active queue contract:

- ``llmctl_studio``
- ``llmctl_studio.downloads.huggingface``
- ``llmctl_studio.rag.index``
- ``llmctl_studio.rag.drive``
- ``llmctl_studio.rag.git``

Scaling model:

- worker slots = ``replicas x concurrency``
- current Kubernetes baseline: ``4 replicas x concurrency 1 = 4`` worker slots

Operational guidance:

- keep beat at one replica unless explicit scheduler coordination is introduced
  (to avoid duplicate periodic dispatch).
- scale worker replicas/concurrency independently from Studio backend API
  replicas.
- if task latency grows, increase worker slots before scaling Studio API pods.

Event Contract and Frontend Model
---------------------------------

Backend emits use a shared envelope contract with key fields:

- ``contract_version``, ``event_id``, ``idempotency_key``
- ``sequence``, ``sequence_stream``
- ``emitted_at``, ``event_type``
- ``entity_kind``, ``entity_id``
- ``room_keys``, ``runtime``, ``payload``

Room conventions include:

- ``task:<task_id>``
- ``run:<run_id>``
- ``flowchart:<flowchart_id>``
- ``flowchart_run:<flowchart_run_id>``
- ``thread:<thread_id>``
- ``download_job:<job_id>``

POST remains the write ingress path for user actions (for example turn submit,
run/cancel actions, settings actions). Socket.IO is the primary push path for
backend-to-frontend updates.

This contract is consumed by the React frontend in the split runtime.

Node Detail API and Runtime Metadata Contract
---------------------------------------------

Node detail/status payloads expose stable execution-mode metadata for RAG runs:

- ``task.execution_mode`` in ``GET /api/nodes/<id>``
- ``execution_mode`` in ``GET /api/nodes/<id>/status``

Canonical values:

- ``query``
- ``indexing``
- ``delta_indexing``

Realtime/runtime metadata normalization also carries ``execution_mode`` so
frontend consumers can align stage labels consistently with API responses.

Node Detail stage assembly keeps canonical stage keys and remaps only
``llm_query`` labels for RAG runs:

- ``query`` -> ``LLM Query``
- ``indexing`` -> ``RAG Indexing``
- ``delta_indexing`` -> ``RAG Delta Indexing``

Non-RAG nodes and missing/unknown modes keep existing ``LLM Query`` behavior.

Developer Workflow (React-Only Split)
-------------------------------------

Local split development:

1. Start backend:

   .. code-block:: bash

      python3 app/llmctl-studio-backend/run.py

2. Start frontend:

   .. code-block:: bash

      cd app/llmctl-studio-frontend
      npm run dev

3. Ensure frontend API base path is ``/api`` and Socket.IO path is ``/api/socket.io``.

Kubernetes split rollout:

- frontend deployment: ``llmctl-studio-frontend``
- backend deployment: ``llmctl-studio-backend``
- ingress paths: ``/web`` and ``/api``
- Minikube ``overlays/dev`` frontend runs Vite dev server with polling file watch,
  so edits in ``app/llmctl-studio-frontend/src`` hot-reload without restarting the
  frontend deployment.

Operational Guidance
--------------------

If realtime updates appear delayed or missing:

1. verify Redis connectivity and queue URL configuration
2. verify proxy upgrade headers and timeout settings
3. confirm Socket.IO path/origin values match external routing
4. check whether clients are in fallback polling mode

Polling fallback behavior is intentionally failure-gated:

- fallback starts after verified socket connect timeout, or
- after sustained disconnect from an already-ready socket

This avoids premature polling during transient connect events.

CORS hardening follow-up:

- current compatibility default may be wide open (``*``)
- production should set ``LLMCTL_STUDIO_SOCKETIO_CORS_ALLOWED_ORIGINS`` to an
  explicit allowlist for deployed Studio frontend origin(s)
