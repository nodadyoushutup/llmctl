Studio Serving Runtime
======================

Overview
--------

Studio now runs with a Gunicorn-first serving model and Socket.IO-first
backend-to-frontend updates. The runtime is designed for:

- direct HTTP development
- HTTPS and reverse-proxy deployments
- multi-worker Gunicorn with Redis-backed Socket.IO fan-out
- compatibility with both current Jinja pages and future React frontend clients

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

This contract is frontend-agnostic by design, so Jinja pages and future React
clients consume the same realtime events without backend contract rewrites.

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
  explicit allowlist for deployed Studio origin(s), plus future React origin(s)
  when split-host frontend deployment is introduced
