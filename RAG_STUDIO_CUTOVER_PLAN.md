# RAG to Studio Cutover Plan

**Work checklist instructions**
- Check off each subtask as it is completed.
- Use `- [x]` for done and `- [ ]` for not done.
- Update this file in place as implementation progresses.
- Keep `app/llmctl-rag` read-only until final deprecation stage.

Goal: migrate all llmctl-rag capabilities into llmctl-studio using new, Studio-owned code paths. During migration, keep the current RAG app unchanged as a reference implementation only. After full parity and cutover, remove the RAG app.

## Decision log (locked on 2026-02-16)

- [x] Watchdog filesystem indexing is deferred for now.
- [x] Fresh index and delta index per source are required now.
- [x] No git-poll auto indexing in v1.
- [x] No standalone CLI flows in v1 (`ingest/query/watch`).
- [x] No migration of existing `llmctl-rag` data is needed.
- [x] RAG moves into a dedicated top-level Studio section in main navigation.
- [x] Keep per-source collections.
- [x] OpenAI and Gemini functionality must match current RAG app support.
- [x] Google Drive must exist as both:
  - [x] settings under Studio Integrations (service account configuration)
  - [x] a source type (alongside local and GitHub)
- [x] No dedicated Google workspace/MCP workspace view in v1.
- [x] Local folder and GitHub source support are required.
- [x] Rollout is feature-by-feature with verification after each completed stage.
- [x] Chat behavior target is exact migration parity.
- [x] Avoid naming collision with Studio Task nodes:
  - [x] use `Index Jobs` as the UI label.
- [x] Use dedicated RAG queues; do not share/interfere with node execution queues.
- [x] Indexing triggers for v1: manual and scheduled only.
- [x] Scheduled indexing mode must be selectable (`fresh` or `delta`).
- [x] Indexing actions are per-source only in v1 (no "index all sources" action).
- [x] Pause/resume/cancel controls are required in v1.
- [x] Settings split:
  - [x] Chroma integration holds connection and MCP-related setup.
  - [x] RAG has its own configuration, including DB provider selection.
  - [x] Only ChromaDB is available as RAG DB provider initially.
- [x] RAG nav/page scope for v1:
  - [x] include `Chat`, `Sources`, and `Index Jobs`
  - [x] exclude RAG `Collections` page (use existing Chroma collections UI)
  - [x] RAG settings are integrated into current Studio Settings pages (not a RAG-only settings page)
- [x] `app/llmctl-rag` deletion is user-owned and manual; Codex should not delete it.

## Non-negotiable constraints

- [ ] Do not import runtime code from `app/llmctl-rag` into Studio.
- [ ] Implement new Studio files/modules and copy/adapt logic as needed.
- [ ] Keep RAG behavior available for reference testing until cutover is complete.
- [ ] Do not change RAG DB/schema or runtime behavior during migration work.
- [ ] For template/pipeline updates, treat as DB updates unless explicitly asked to change seed data.
- [ ] Do not delete `app/llmctl-rag`; only user performs final removal.

## Definition of done

- [ ] All required RAG features exist in Studio with parity or approved replacement behavior.
- [ ] Studio RAG flows pass parity test suite and performance gates.
- [ ] RAG production traffic/workflows are fully switched to Studio.
- [ ] RAG app is deprecated and removed from the repo in a controlled final stage.

## Stage 0 - Scope lock and migration governance

- [x] Confirm v1 parity scope:
  - [x] Required now: source indexing (`fresh` + `delta`), source management, chat parity, OpenAI/Gemini support, GitHub/local/Google Drive sources, manual/scheduled triggers, pause/resume/cancel lifecycle.
  - [x] Deferred: watchdog filesystem indexing, git-poll auto indexing, standalone CLI flows.
- [x] Confirm where RAG lives in Studio UX:
  - [x] Dedicated top-level RAG section/pages in main nav.
  - [ ] Embedded into existing Studio sections.
  - [ ] Hybrid.
- [x] Confirm data strategy:
  - [ ] Migrate existing `llmctl-rag` SQLite data into Studio.
  - [x] Fresh start in Studio (no historical migration).
  - [ ] Selective migration.
- [x] Confirm rollout strategy:
  - [ ] Big-bang cutover.
  - [x] Phased cutover by feature.
  - [ ] Phased cutover by source type/team.
- [x] Confirm naming for indexing run records in Studio UI:
  - [x] `Index Jobs`
- [x] Confirm v1 index trigger scope:
  - [x] per-source actions only
  - [x] no global "index all sources" action in v1
- [x] Confirm scheduled indexing behavior:
  - [x] schedule units: minutes/hours/days/weeks
  - [x] schedule mode selectable: `fresh` or `delta`
- [x] Baseline references:
  - [x] Capture current RAG behavior snapshot (API/UI/screens/test outputs): `docs/RAG_STAGE0_BASELINE_SNAPSHOT_2026-02-16.md`.
  - [x] Record baseline commit hashes for Studio and RAG: `7b7adda10e54208a84d9812f6e0c5072baa2fdac`.

Deliverables:
- [x] Final scope statement in this doc.
- [x] Explicit non-goals list.
- [x] Agreed cutover gate checklist.

### Stage 0 final scope statement (locked 2026-02-16)

- Studio v1 RAG scope includes source CRUD, per-source indexing (`fresh`/`delta`), source scheduling, pause/resume/cancel, and chat parity with source citations.
- Source types in scope are local filesystem, GitHub, and Google Drive.
- Provider support in scope is OpenAI and Gemini parity for embeddings/chat.
- RAG lives in a dedicated top-level Studio nav section with pages for `Chat`, `Sources`, and `Index Jobs`.
- RAG settings stay inside Studio settings (split between Chroma integration and RAG settings), with `chroma` as the only visible DB provider in v1.
- Rollout proceeds by phased feature cutover with verification after each completed stage.

### Stage 0 explicit non-goals (v1)

- No filesystem watchdog indexing.
- No git-poll trigger indexing.
- No standalone CLI (`ingest`, `query`, `watch`) migration.
- No global "index all sources" action in v1.
- No dedicated RAG collections page (use existing Studio Chroma collections UI).
- No migration/backfill of existing standalone `llmctl-rag` SQLite data.
- No deletion of `app/llmctl-rag` during migration stages.

### Stage 0 cutover gate checklist (agreed)

- [ ] Stage 1 audit artifacts completed and reviewed (capability matrix + risk register).
- [ ] Stage 3 schema and migration changes merged and validated.
- [ ] Stage 4-6 engine/integration/orchestration parity validated by automated tests.
- [ ] Stage 7 UI/API parity accepted, including per-source index actions and list-view interaction standards.
- [ ] Stage 8 config precedence and settings split behavior validated.
- [ ] Stage 9 parity test report passes quality and performance thresholds.
- [ ] Stage 10 shadow comparison report signed off for representative datasets.
- [ ] User approves final Stage 11 deprecation handoff checklist.

## Stage 1 - Full RAG functional audit (reference inventory)

- [x] Entry/runtime audit:
  - [x] `app/llmctl-rag/run.py`
  - [x] `app/llmctl-rag/celery_app.py`
  - [x] `app/llmctl-rag/watch.py`
  - [x] `app/llmctl-rag/query.py`
- [x] Web/API audit:
  - [x] `app/llmctl-rag/web_app.py`
  - [x] `app/llmctl-rag/web/templates/*.html`
  - [x] `app/llmctl-rag/web/static/app.js`
- [x] Data/storage audit:
  - [x] `app/llmctl-rag/models.py`
  - [x] `app/llmctl-rag/db.py`
  - [x] `app/llmctl-rag/sources_store.py`
  - [x] `app/llmctl-rag/tasks_store.py`
  - [x] `app/llmctl-rag/source_file_states_store.py`
  - [x] `app/llmctl-rag/settings_store.py`
- [x] RAG engine audit:
  - [x] `app/llmctl-rag/ingest.py`
  - [x] `app/llmctl-rag/parsers.py`
  - [x] `app/llmctl-rag/chunkers.py`
  - [x] `app/llmctl-rag/pdf_pipeline.py`
  - [x] `app/llmctl-rag/office_parsers.py`
  - [x] `app/llmctl-rag/doc_structures.py`
  - [x] `app/llmctl-rag/code_spans.py`
  - [x] `app/llmctl-rag/pipeline.py`
  - [x] `app/llmctl-rag/token_utils.py`
  - [x] `app/llmctl-rag/provider_adapters.py`
- [x] Source integration audit:
  - [x] `app/llmctl-rag/git_sync.py`
  - [x] `app/llmctl-rag/google_drive_sync.py`
- [x] Test coverage audit:
  - [x] `app/llmctl-rag/tests/*`
  - [x] Map each test to a Studio parity target.

Deliverables:
- [x] Capability matrix with source files, destination modules, parity status: `docs/RAG_STAGE1_AUDIT_2026-02-16.md`.
- [x] Risk register (high/medium/low) for cutover blockers: `docs/RAG_STAGE1_AUDIT_2026-02-16.md`.

## Stage 2 - Studio target architecture and destination map

- [x] Create Studio-owned RAG module namespace (example: `app/llmctl-studio/src/rag/`).
- [x] Define Studio boundaries:
  - [x] Core RAG domain services.
  - [x] Queue worker layer.
  - [x] Web views/API layer.
  - [x] Storage/repository layer.
- [x] Define naming conventions to avoid accidental coupling to old RAG code.
- [x] Define DB ownership in Studio:
  - [x] Source records.
  - [x] RAG task records.
  - [x] Source file state records (for delta indexing).
  - [x] RAG integration/settings records.
- [x] Define Studio queue topology for RAG:
  - [x] dedicated RAG queue namespace (no node queue reuse)
  - [x] index queue
  - [x] drive queue
  - [x] git queue
- [x] Define scheduler model:
  - [x] source schedule poll loop
  - [x] source next-index timestamps
  - [x] source schedule mode (`fresh`/`delta`) persistence + execution
- [x] Define trigger policy:
  - [x] manual trigger APIs/UI
  - [x] scheduled indexing only
  - [x] no filesystem watch trigger in v1
  - [x] no git-poll trigger in v1
- [x] Define route namespace and template placement in Studio.
- [x] Define dedicated top-level Studio nav and page IA for RAG section.
- [x] Exclude dedicated RAG collections route/page; point users to existing Chroma collections UI.

Deliverables:
- [x] Architecture section added to this plan with final paths.
- [x] Migration map from each RAG module to each Studio module.

### Stage 2 architecture lock (2026-02-16)

Studio-owned namespace and boundary packages created:
- `app/llmctl-studio/src/rag/__init__.py`
- `app/llmctl-studio/src/rag/contracts.py`
- `app/llmctl-studio/src/rag/domain/__init__.py`
- `app/llmctl-studio/src/rag/repositories/__init__.py`
- `app/llmctl-studio/src/rag/worker/__init__.py`
- `app/llmctl-studio/src/rag/worker/queues.py`
- `app/llmctl-studio/src/rag/web/__init__.py`
- `app/llmctl-studio/src/rag/web/routes.py`
- `app/llmctl-studio/src/rag/runtime/__init__.py`
- `app/llmctl-studio/src/rag/engine/__init__.py`
- `app/llmctl-studio/src/rag/integrations/__init__.py`
- `app/llmctl-studio/src/rag/providers/__init__.py`
- `app/llmctl-studio/src/rag/legacy/__init__.py`

Naming and ownership conventions locked:
- Use `rag_*` table naming for all Studio RAG tables to prevent collisions with non-RAG Studio entities.
- Use `Index Jobs` as the UI/domain label, and `index_jobs` in repository module naming.
- Keep all new runtime code under `src/rag/*`; no imports from `app/llmctl-rag/*`.
- Keep deferred/non-goal behaviors under `src/rag/legacy/*` as reference-only artifacts.

DB ownership locked (Stage 3 implementation targets):
- source records: `rag_sources`
- index job records: `rag_index_jobs`
- source file state records: `rag_source_file_states`
- RAG settings records: `rag_settings`

Queue topology locked:
- namespace: `llmctl_studio.rag`
- index queue: `llmctl_studio.rag.index`
- drive queue: `llmctl_studio.rag.drive`
- git queue: `llmctl_studio.rag.git`
- routing by source kind contract is defined in `app/llmctl-studio/src/rag/worker/queues.py`

Scheduler and trigger policy locked:
- one source schedule poll loop scans `rag_sources.next_index_at` and enqueues due source runs.
- schedule mode is persisted per source as `fresh` or `delta` and used at enqueue time.
- trigger modes in v1: manual + scheduled only.
- excluded trigger modes in v1: filesystem watch + git-poll.

Route namespace and placement locked:
- RAG page routes under `/rag/*`.
- RAG API routes under `/api/rag/*`.
- RAG templates under `app/llmctl-studio/src/web/templates/rag/*`.
- RAG static assets under `app/llmctl-studio/src/web/static/rag/*`.
- no dedicated RAG collections page; collections continue via existing Chroma routes under `/chroma/*`.

Top-level nav and IA lock:
- top-level section label: `RAG`
- pages in scope: `Chat`, `Sources`, `Index Jobs`

### Stage 2 migration map (reference -> Studio destination)

| RAG reference module | Studio destination module/path | Notes |
|---|---|---|
| `app/llmctl-rag/run.py` | `app/llmctl-studio/src/rag/runtime/run.py` | Runtime bootstrap for RAG web + scheduler lifecycle. |
| `app/llmctl-rag/celery_app.py` | `app/llmctl-studio/src/rag/worker/celery_app.py` | Dedicated RAG Celery app/queue config. |
| `app/llmctl-rag/watch.py` | `app/llmctl-studio/src/rag/legacy/watch_reference.py` | Deferred in v1 (reference only). |
| `app/llmctl-rag/query.py` | deferred in v1 | CLI flow is out of scope for cutover v1. |
| `app/llmctl-rag/web_app.py` | `app/llmctl-studio/src/rag/web/views.py`, `app/llmctl-studio/src/rag/web/api.py`, `app/llmctl-studio/src/rag/web/scheduler.py` | Split monolith into web/API/scheduler modules. |
| `app/llmctl-rag/web/templates/*.html` | `app/llmctl-studio/src/web/templates/rag/*.html` | RAG templates under Studio web templates tree. |
| `app/llmctl-rag/web/static/app.js` | `app/llmctl-studio/src/web/static/rag/app.js` | RAG UI client logic and polling behavior. |
| `app/llmctl-rag/models.py` | `app/llmctl-studio/src/core/models.py` | Adds `rag_*` tables only. |
| `app/llmctl-rag/db.py` | `app/llmctl-studio/src/core/db.py` | RAG migration/bootstrap functions in Studio DB path. |
| `app/llmctl-rag/sources_store.py` | `app/llmctl-studio/src/rag/repositories/sources.py` | Source CRUD and schedule fields. |
| `app/llmctl-rag/tasks_store.py` | `app/llmctl-studio/src/rag/repositories/index_jobs.py` | Index job lifecycle and metadata state machine. |
| `app/llmctl-rag/source_file_states_store.py` | `app/llmctl-studio/src/rag/repositories/source_file_states.py` | Delta fingerprint state persistence. |
| `app/llmctl-rag/settings_store.py` | `app/llmctl-studio/src/rag/repositories/settings.py` | RAG-owned provider/indexing settings persistence. |
| `app/llmctl-rag/ingest.py` | `app/llmctl-studio/src/rag/engine/ingest.py` | Ingestion pipeline and embedding orchestration. |
| `app/llmctl-rag/parsers.py` | `app/llmctl-studio/src/rag/engine/parsers.py` | Text/code/markdown/html/pdf/office parser dispatch. |
| `app/llmctl-rag/chunkers.py` | `app/llmctl-studio/src/rag/engine/chunkers.py` | Chunking strategies and payload shape parity. |
| `app/llmctl-rag/pdf_pipeline.py` | `app/llmctl-studio/src/rag/engine/pdf_pipeline.py` | PDF extraction/OCR/vector heuristics. |
| `app/llmctl-rag/office_parsers.py` | `app/llmctl-studio/src/rag/engine/office_parsers.py` | DOCX/PPTX/XLSX parsing. |
| `app/llmctl-rag/doc_structures.py` | `app/llmctl-studio/src/rag/engine/doc_structures.py` | Document structure extraction. |
| `app/llmctl-rag/code_spans.py` | `app/llmctl-studio/src/rag/engine/code_spans.py` | Symbol/code span extraction. |
| `app/llmctl-rag/pipeline.py` | `app/llmctl-studio/src/rag/engine/pipeline.py` | Parsed/chunk model contracts and registries. |
| `app/llmctl-rag/token_utils.py` | `app/llmctl-studio/src/rag/engine/token_utils.py` | Token-aware batching helpers. |
| `app/llmctl-rag/provider_adapters.py` | `app/llmctl-studio/src/rag/providers/adapters.py` | OpenAI/Gemini embedding + chat adapters. |
| `app/llmctl-rag/git_sync.py` | `app/llmctl-studio/src/rag/integrations/git_sync.py` | Git source sync behavior. |
| `app/llmctl-rag/google_drive_sync.py` | `app/llmctl-studio/src/rag/integrations/google_drive_sync.py` | Google Drive verify/sync behavior. |
| `app/llmctl-rag/tasks_worker.py` | `app/llmctl-studio/src/rag/worker/tasks.py` | Index worker orchestration and checkpoints. |

## Stage 3 - Studio data model and migrations

- [x] Add Studio models for RAG sources/tasks/file states/settings.
- [x] Add DB migration functions in Studio DB bootstrap path.
- [x] Add repository/store layer APIs in Studio for source/task lifecycle.
- [x] Add schedule columns and indexes required for source polling.
- [x] Add schedule mode column/field (`fresh`/`delta`) for source schedules.
- [x] Add task metadata shape for checkpoints/progress.
- [x] No one-time import/backfill from `llmctl-rag.db` (clean Studio start).

Deliverables:
- [x] Schema changes in `app/llmctl-studio/src/core/models.py`.
- [x] Migration logic in `app/llmctl-studio/src/core/db.py`.
- [x] Data bootstrap path for net-new Studio RAG records only.

## Stage 4 - Indexing and retrieval engine port (new Studio code)

- [x] Port parsing/chunking pipeline into Studio-owned modules:
  - [x] text/code/markdown/html parsers
  - [x] office parsers (docx/pptx/xlsx)
  - [x] PDF pipeline with OCR/vector heuristics
- [x] Port document/chunk identity strategy (`doc_group_id`, `chunk_id`) as-is unless changed by decision.
- [x] Port token-aware batching/rate limiting/retry behavior for embeddings.
- [x] Port delta fingerprint logic and deletion semantics.
- [x] Port retrieval merge/ranking across multiple source collections.
- [x] Port provider adapters (OpenAI/Gemini embedding + chat).

Deliverables:
- [x] Studio RAG engine modules with unit tests.
- [x] No import dependency on `app/llmctl-rag/*`.

## Stage 5 - Source integrations (local, GitHub, Google Drive)

- [x] Port local source indexing flow.
- [x] Port GitHub source sync flow:
  - [x] clone/fetch/reset behavior
  - [x] PAT + SSH key support
  - [x] known_hosts handling
- [x] Port Google Drive source sync flow:
  - [x] service account validation
  - [x] folder access verification
  - [x] export/download behavior
  - [x] concurrent download workers
- [x] Port per-source collection mapping and stats updates.

Deliverables:
- [x] Studio integration services for local/git/drive sources.
- [x] Provider and credentials handling parity verified.

Stage 5 verification artifacts:
- [x] Added Google Drive parity tests: `app/llmctl-studio/tests/rag/test_google_drive_sync.py`.
- [x] Added source integration/config + GitHub sync tests: `app/llmctl-studio/tests/rag/test_source_integrations.py`.

## Stage 6 - Task orchestration, queues, scheduler, checkpoints

- [ ] Add Studio Celery tasks for RAG index runs.
- [ ] Add queue routing by source type.
- [ ] Keep RAG queue workers isolated from node execution queues.
- [ ] Keep orchestration scoped to per-source indexing jobs in v1.
- [ ] Port pause/resume/cancel lifecycle.
- [ ] Port checkpoint persistence and resume behavior:
  - [ ] fresh mode
  - [ ] delta mode
- [ ] Port progress payload shape for UI polling.
- [ ] Port scheduler thread for timed source indexing.
- [ ] Add duplicate-task guardrails per source.
- [ ] Explicitly exclude v1 trigger modes:
  - [ ] no filesystem watch-mode trigger path
  - [ ] no git-poll trigger path

Deliverables:
- [ ] Studio worker runtime reaches feature parity with RAG task lifecycle.
- [ ] Queue and scheduler behavior validated under load.

## Stage 7 - Studio UI and API cutover

- [ ] Add dedicated RAG top-level nav section in Studio.
- [x] Use non-conflicting naming in UI for indexing runs (`Index Jobs`).
- [ ] Add Studio pages/API for:
  - [ ] Sources list/create/edit/detail/delete
  - [ ] Index jobs list/detail with polling
  - [ ] Chat + retrieval sources panel
  - [ ] no dedicated RAG collections page (use existing Studio Chroma pages)
- [ ] Add Google Drive integration UX in Studio Integrations settings:
  - [ ] service account configuration fields/validation
  - [ ] source form wiring for Drive verification and source creation
  - [ ] no dedicated Google workspace page in v1
- [ ] Add schedule controls in source forms:
  - [ ] interval value/unit
  - [ ] schedule index mode selector (`fresh`/`delta`)
- [ ] Keep index actions per-source only (no "index all" control in v1).
- [ ] Add Studio endpoints for:
  - [ ] index now (per-source)
  - [ ] pause/resume source index
  - [ ] github repo list
  - [ ] google drive verify
  - [ ] chroma connection test
  - [ ] task status polling
- [ ] Keep list-view behavior consistent:
  - [ ] use `table-row-link` + `data-href`
  - [ ] ignore interactive element clicks in row handlers
  - [ ] use icon-only actions, trash + confirm for delete
  - [ ] avoid redundant ID/updated columns when row links to detail

Deliverables:
- [ ] Studio templates/routes/services fully replace RAG UI/API usage.
- [ ] UX and interaction parity sign-off.

## Stage 8 - Config and settings precedence cutover

- [ ] Port RAG config precedence behavior:
  - [ ] env vars
  - [ ] integration settings in DB
  - [ ] source-specific overrides
- [ ] Port provider/model defaults and validation.
- [ ] Port Chroma host/port normalization behavior.
- [ ] Implement settings split:
  - [ ] Chroma integration settings for Chroma connection + MCP setup
  - [ ] RAG settings for indexing behavior and RAG provider selection
  - [ ] RAG provider selector includes `chroma` only in v1 (single visible option)
  - [ ] fail-safe behavior when Chroma integration is missing/misconfigured
- [ ] Port chat controls:
  - [ ] response style/verbosity
  - [ ] top_k
  - [ ] context budget
  - [ ] history limits

Deliverables:
- [ ] Studio configuration behavior documented and tested.
- [ ] No hidden runtime dependency on RAG config modules.

## Stage 9 - Parity testing and quality gates

- [ ] Port/replicate RAG tests into Studio equivalents:
  - [ ] parser/chunker tests
  - [ ] provider adapter tests
  - [ ] web source/task/collection behavior
  - [ ] delta indexing behavior
  - [ ] regression/performance checks
- [ ] Add end-to-end parity scenarios:
  - [ ] local source full index
  - [ ] github source fresh and delta
  - [ ] google drive source fresh and delta
  - [ ] pause/resume/cancel recovery
  - [ ] chat response with retrieved citations
- [ ] Define and hit performance thresholds:
  - [ ] throughput
  - [ ] queue latency
  - [ ] memory footprint
  - [ ] error rate
- [ ] Run test commands with `python3`.
- [ ] Enforce exact chat parity gates before acceptance:
  - [ ] system prompt behavior parity
  - [ ] history trimming/query text generation parity
  - [ ] context assembly/source citation formatting parity
  - [ ] response-style/verbosity behavior parity

Deliverables:
- [ ] Studio parity test report.
- [ ] Cutover approval based on objective gates.

## Stage 10 - Shadow mode and production cutover

- [ ] User verification gate after each completed feature stage before proceeding.
- [ ] Run Studio in shadow mode against representative datasets.
- [ ] Compare outputs/metrics between RAG and Studio:
  - [ ] source stats
  - [ ] chunk counts
  - [ ] task behavior
  - [ ] chat retrieval quality
- [ ] Fix parity gaps and rerun until acceptable.
- [ ] Flip primary traffic/workflow to Studio RAG paths.
- [ ] Freeze creation of new workflows in standalone RAG app.

Deliverables:
- [ ] Cutover runbook with rollback steps.
- [ ] Signed parity comparison report.

## Stage 11 - Deprecation and removal of standalone RAG app

- [ ] Announce deprecation date and migration complete state.
- [ ] Remove Studio runtime dependencies on standalone RAG app.
- [ ] Remove old Docker/service wiring references once Studio cutover is complete.
- [ ] Update docs to mark standalone RAG as deprecated.
- [ ] Keep `app/llmctl-rag` in repo until user manually removes it.

Deliverables:
- [ ] Studio runs entirely on Studio-owned RAG implementation.
- [ ] No build/runtime dependency on old RAG app remains.
- [ ] Manual deletion handoff checklist prepared for user.

## Initial capability checklist (first pass inventory)

- [ ] Multi-source management: local, GitHub, Google Drive.
- [ ] Per-source Chroma collection creation and maintenance.
- [ ] Fresh and delta indexing modes.
- [ ] Pause/resume/cancel indexing tasks with checkpoints.
- [ ] Per-source-only indexing actions (no global index-all control in v1).
- [ ] Queue routing by source kind (index/drive/git).
- [ ] Source scheduling with poll loop and `next_index_at`.
- [ ] Source schedule mode selection (`fresh`/`delta`).
- [ ] Delta file-state tracking with fingerprints.
- [ ] Parsing coverage: text/code/markdown/html/pdf/docx/pptx/xlsx.
- [ ] PDF OCR and vector geometry extraction heuristics.
- [ ] Chunking strategies: line/token/structure/pdf.
- [ ] Embedding batching, rate limiting, retry/backoff.
- [ ] OpenAI/Gemini embedding and chat adapters.
- [ ] Chat retrieval across collections with source citations/snippets.
- [ ] UI polling for source/task status and progress payloads.
- [ ] Integrations settings storage for rag/github/google_drive.
- [ ] Chroma connectivity testing and collection browser.
- [x] Watch mode is deferred post-cutover.
- [x] Git poll sync mode is deferred post-cutover.
- [x] CLI flows are deferred post-cutover.

## Open decisions to resolve while executing

- [x] No unresolved scope decisions currently.
