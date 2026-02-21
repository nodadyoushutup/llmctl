Changelog
=========

2026-02-21
----------

- Documented final Studio backend structural module layout after decomposition of ``web.views`` into package modules and package-based ``core.models`` layout.
- Documented removal of vestigial backend CLI-era entrypoints (``src/__main__.py`` and ``src/cli/*``) from active runtime paths.
- Updated Sphinx API generation excludes for package-based ``web/views`` and ``core/models`` paths.
- Closed runtime migration claim audit remediation with full claim matrix closure (``pass: 348``, ``fail: 0``, ``insufficient_evidence: 0``).
- Added frontier CLI runtime guardrail script and CI gate to fail on direct ``codex|gemini|claude`` command execution in Studio runtime paths.
- Updated Stage 9 flowchart backend tests for current graph-save contract semantics (structural violations ``400`` vs semantic validation via ``validation.errors``).
- Updated migration runbook and specialized flowchart node docs to reflect current cutover status, guardrails, and memory-node/system-MCP enforcement behavior.
- Documented memory-node mode selection contracts (``llm_guided``/``deterministic``), failure controls (``retry_count``/``fallback_enabled``), startup backfill migration defaults, and degraded fallback status markers in specialized flowchart node docs.

2026-02-20
----------

- Added Stage 16 runtime migration documentation set: operator/developer cutover runbook, contract reference index, rollback procedure, and known sign-off gap inventory.
- Expanded Node Executor runtime docs with split frontier/vLLM image settings, build/release commands, and tooling/runtime ownership boundaries.
- Added API reference pages for ``services.execution.tooling``, ``services.runtime_contracts``, and ``services.flow_migration``.
- Linked Studio serving/runtime guide to the migration runbook for cutover operations.

2026-02-18
----------

- Added Sphinx reference documentation for specialized flowchart nodes (Memory/Plan/Milestone/Decision), including curated inspector controls, retention settings, artifact schemas, and branchless Stage 5 operator guidance.
- Documented specialized artifact REST contracts and socket payload schemas, including ``flowchart:node_artifact:persisted`` and ``request_id``/``correlation_id`` tracing requirements.
- Documented MCP alignment for specialized artifact retrieval through ``llmctl_get_memory``, ``llmctl_get_plan``, ``llmctl_get_milestone``, ``llmctl_get_decision_artifact``, and ``llmctl_get_node_artifact``.
- Recorded Wave boundaries for rollout tracking: Wave 1 specialization = Memory + Plan; Wave 2 specialization = Milestone + Decision.
- Restored Node Detail RAG indexing visibility for ``Quick RAG`` and flowchart ``rag`` indexing runs by mapping the ``llm_query`` stage label to ``RAG Indexing``/``RAG Delta Indexing`` from canonical execution mode metadata.
- Added RAG indexing stage-log capture plumbing so indexing log lines are persisted into task stage logs and rendered in Node Detail stage panels.
- Added explicit execution-mode contract fields for Node Detail/status API payloads and normalized realtime runtime metadata (``query``, ``indexing``, ``delta_indexing``).
- Migrated Chat turn LLM execution to Kubernetes executor pods (executor-dispatched ``llm_call`` runtime path).
- Migrated RAG web chat synthesis/completion to Kubernetes executor pods (executor-dispatched ``rag_chat_completion`` path).
- Updated agent-task Celery execution flow to route all task kinds through Kubernetes executor dispatch (no worker-local LLM execution path).
- Began backend image-slim cutover by removing backend-side LLM CLI installation and backend-side ``vllm`` install from the Studio backend Docker image.
- Updated Kubernetes/operator docs to reflect executor-only LLM runtime architecture and dev rollback guidance.

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
- Completed Kubernetes-only node execution cutover: node-like compute now executes in Kubernetes executor pods using full ``node_execution`` payloads and structured ``output_state``/``routing_state`` results (no probe-only path).
- Added runtime evidence contract docs for ``provider_dispatch_id``, ``k8s_job_name``, ``k8s_pod_name``, and ``k8s_terminal_reason``.
- Documented final architecture split: chat remains service-runtime, node-like workloads run in executor pods.
- Added ``with_test_postgres.sh`` local test harness to bootstrap disposable PostgreSQL and prevent backend test runs from blocking on missing local DB wiring.

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
