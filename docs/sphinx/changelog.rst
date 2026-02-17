Changelog
=========

2026-02-17
----------

- Completed Studio React-only cutover: backend no longer serves legacy Jinja/static GUI routes, and frontend nginx removed backend fallback proxy behavior.
- Documented final split route/runtime contract: ``/web`` (React frontend) and ``/api`` (backend API/realtime).
- Added React-only runtime guard and automated backend/split integration tests to prevent legacy GUI route regressions.
- Completed Celery runtime decoupling for Studio: backend now runs web/API only, while dedicated Kubernetes deployments run worker (`llmctl-celery-worker`) and beat (`llmctl-celery-beat`).
- Documented Celery queue topology, dedicated beat scheduling model, and worker-slot scaling formula (`replicas x concurrency`) for Kubernetes operations.
- Added automated worker runtime tests for `app/llmctl-celery-worker/run.py` and Stage 7 queue/beat smoke validation notes.
- Migrated integrated MCP runtime architecture to Kubernetes-hosted services and removed Studio runtime dependence on bundled MCP executables.
- Added integrated MCP endpoint contract and lifecycle documentation (startup migration sync + seed alignment) for DB-backed ``mcp_servers`` rows.
- Added Kubernetes operator documentation for integrated MCP Deployments/Services, secret inputs, and one-release cutover gate controls.

2026-02-16
----------

- Added first-class Launch Chat runtime with durable thread sessions.
- Added session-scoped model, MCP, and optional RAG collection selectors.
- Added session-scoped Chat response complexity control (``low``/``medium``/``high``/``extra_high``) applied to prompt assembly for both RAG and non-RAG turns.
- Added Markdown-rendered Chat bubbles with structured formatting support (including tables).
- Added context budgeting and automatic compaction at configured usage limits.
- Added clear-in-place thread reset behavior.
- Added Chat activity/audit surfaces and event taxonomy.
- Added Chat runtime API routes and contract-boundary RAG client.
- Migrated RAG indexing/retrieval orchestration to first-class ``rag`` flowchart nodes.
- Added shared Chat/RAG contract endpoints at ``/api/rag/contract/*`` with compatibility aliases.
- Removed standalone RAG Index Jobs surfaces from active Studio navigation/runtime paths.
- Added real-time RAG integration-health gating for flowchart ``rag`` node palette visibility/execution.
- Added Sources-page quick RAG triggers (``Index`` and ``Delta Index``) in both list and detail views, with duplicate-run blocking, Node Activity labeling, and explicit exclusion from workflow-node RAG lists.
- Added Claude provider runtime readiness checks (CLI detection/version + optional auto-install policy).
- Added Claude provider settings diagnostics for CLI/auth readiness with DB-first auth precedence.
- Added curated Claude model suggestions while keeping freeform model IDs supported.
- Added vLLM Local HuggingFace token integration for token-aware Qwen downloads and conditional generic ``owner/model`` downloads.
- Migrated Studio in-app skills to Agent-only binding with node-level payload deprecation modes (``warn``/``reject``) and deterministic legacy backfill/archival.
- Added Studio skill authoring uploads with explicit per-file path mapping, per-conflict actions (replace/keep-both/skip), git-source read-only guards, and binary-envelope materialization for approved asset/doc uploads.
- Split Google integrations into separate ``google_cloud`` and ``google_workspace`` providers with independent service-account settings and dedicated Integrations tabs/routes.
- Added automatic migration of legacy ``google_drive`` integration settings into split Cloud/Workspace providers during settings reads/writes.
- Added Google Workspace integrated MCP scaffold controls while intentionally guarding runtime server creation until a supported Workspace MCP service-account execution path is finalized.
- Added Gunicorn-first Studio serving controls with optional environment overrides for concurrency, worker behavior, logs, and timeout/lifecycle tuning.
- Added reverse-proxy compliance controls/documentation for trusted forwarded headers, scheme/host resolution, WebSocket upgrades, and TLS termination modes.
- Added Flask-SocketIO + Redis multi-worker architecture documentation including sticky-session guidance for polling fallback and websocket-first transport recommendations.
- Added canonical realtime event-contract and room-scoping documentation for Jinja now and React migration compatibility.
- Added Node Executor runtime documentation covering DB-backed settings, multi-provider architecture (workspace/docker/kubernetes), execution contract versioning, dispatch state machine, fallback semantics, and cancellation behavior.
- Migrated MCP server configuration storage and APIs to JSON-only semantics, including PostgreSQL ``JSONB`` persistence with fail-fast legacy TOML-to-JSON migration behavior.
