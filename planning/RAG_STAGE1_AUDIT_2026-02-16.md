# RAG Stage 1 Functional Audit (2026-02-16)

Stage audited from `RAG_STUDIO_CUTOVER_PLAN.md`:
- Stage 1 - Full RAG functional audit (reference inventory)

Baseline references:
- `planning/RAG_STAGE0_BASELINE_SNAPSHOT_2026-02-16.md`
- `app/llmctl-rag/*` (read-only reference implementation)

Audit method:
- Reviewed all Stage 1 target modules and templates.
- Enumerated route and test surface.
- Proposed Studio destination modules for migration mapping (to be finalized in Stage 2).

## Capability Matrix (source -> Studio destination -> parity status)

Status legend:
- `missing`: no Studio-owned implementation exists yet.
- `partial`: related Studio capability exists, but not full RAG parity behavior.

### Entry/runtime

| Reference file | Current responsibility | Proposed Studio destination | Status |
|---|---|---|---|
| `app/llmctl-rag/run.py` | App bootstrap, optional worker autostart, scheduler start/stop, Flask runtime | `app/llmctl-studio/src/rag/runtime/run.py` | missing |
| `app/llmctl-rag/celery_app.py` | Dedicated Celery app config and default queue setup | `app/llmctl-studio/src/rag/worker/celery_app.py` | missing |
| `app/llmctl-rag/watch.py` | Watchdog + git-poll ingest modes (deferred for v1 scope) | `app/llmctl-studio/src/rag/legacy/watch_reference.py` (reference only) | missing |
| `app/llmctl-rag/query.py` | CLI query against Chroma collections | deferred in v1 (CLI non-goal) | missing |

### Web/API

| Reference file | Current responsibility | Proposed Studio destination | Status |
|---|---|---|---|
| `app/llmctl-rag/web_app.py` | Monolithic RAG web UI + API (`34` routes), scheduler loop, chat context assembly, task orchestration endpoints | `app/llmctl-studio/src/rag/web/views.py` + `app/llmctl-studio/src/rag/web/api.py` + `app/llmctl-studio/src/rag/web/scheduler.py` | missing |
| `app/llmctl-rag/web/templates/*.html` | RAG pages (`index`, `sources`, `source_new`, `source_edit`, `source_detail`, `tasks`, `task_detail`, `collections`, `collection_detail`) | `app/llmctl-studio/src/web/templates/rag/*.html` | missing |
| `app/llmctl-rag/web/static/app.js` | Chat UX, source index actions (fresh/delta/pause/resume), list row-link behavior, polling, Drive verify, Chroma test | `app/llmctl-studio/src/web/static/rag/app.js` | missing |

### Data/storage

| Reference file | Current responsibility | Proposed Studio destination | Status |
|---|---|---|---|
| `app/llmctl-rag/models.py` | SQLAlchemy models: `Source`, `Task`, `SourceFileState`, `IntegrationSetting` | `app/llmctl-studio/src/core/models.py` (new RAG tables) | partial |
| `app/llmctl-rag/db.py` | SQLite engine/session bootstrap + schema patching for `sources` columns | `app/llmctl-studio/src/core/db.py` (migration functions) | partial |
| `app/llmctl-rag/sources_store.py` | Source CRUD, kind normalization, schedule interval fields, next-index timestamp logic | `app/llmctl-studio/src/rag/repositories/sources.py` | missing |
| `app/llmctl-rag/tasks_store.py` | Task lifecycle state machine + metadata serialization | `app/llmctl-studio/src/rag/repositories/index_jobs.py` | missing |
| `app/llmctl-rag/source_file_states_store.py` | Delta fingerprint state CRUD + summary counters | `app/llmctl-studio/src/rag/repositories/source_file_states.py` | missing |
| `app/llmctl-rag/settings_store.py` | Integration settings persistence and defaults | `app/llmctl-studio/src/core/integration_settings.py` | partial |

### RAG engine

| Reference file | Current responsibility | Proposed Studio destination | Status |
|---|---|---|---|
| `app/llmctl-rag/ingest.py` | File iteration/filtering, parser/chunker pipeline, chunk metadata, token-aware embedding batching, retries, backoff, parallel embedding | `app/llmctl-studio/src/rag/engine/ingest.py` | missing |
| `app/llmctl-rag/parsers.py` | Parser registry and parsing for text/code/markdown/html/pdf/docx/pptx/xlsx | `app/llmctl-studio/src/rag/engine/parsers.py` | missing |
| `app/llmctl-rag/chunkers.py` | Line/token/structure/PDF chunkers | `app/llmctl-studio/src/rag/engine/chunkers.py` | missing |
| `app/llmctl-rag/pdf_pipeline.py` | PDF extraction, OCR, vector heuristics/gating, table/unit extraction, per-page parallel parsing | `app/llmctl-studio/src/rag/engine/pdf_pipeline.py` | missing |
| `app/llmctl-rag/office_parsers.py` | DOCX/PPTX/XLSX parsing to structural spans | `app/llmctl-studio/src/rag/engine/office_parsers.py` | missing |
| `app/llmctl-rag/doc_structures.py` | Markdown/HTML section span extraction | `app/llmctl-studio/src/rag/engine/doc_structures.py` | missing |
| `app/llmctl-rag/code_spans.py` | Language detection + python/js/bash symbol span extraction | `app/llmctl-studio/src/rag/engine/code_spans.py` | missing |
| `app/llmctl-rag/pipeline.py` | Parsed/chunk datamodel and parser/chunker registries | `app/llmctl-studio/src/rag/engine/pipeline.py` | missing |
| `app/llmctl-rag/token_utils.py` | Token counting/splitting with `tiktoken` fallback | `app/llmctl-studio/src/rag/engine/token_utils.py` | missing |
| `app/llmctl-rag/provider_adapters.py` | OpenAI/Gemini embedding + chat adapters, API key handling | `app/llmctl-studio/src/rag/providers/adapters.py` | missing |

### Source integrations

| Reference file | Current responsibility | Proposed Studio destination | Status |
|---|---|---|---|
| `app/llmctl-rag/git_sync.py` | Git clone/fetch/reset, SSH env/known_hosts wiring, diff path detection | `app/llmctl-studio/src/rag/integrations/git_sync.py` | missing |
| `app/llmctl-rag/google_drive_sync.py` | Service-account validation, folder verify, recursive listing, export/download, concurrent workers | `app/llmctl-studio/src/rag/integrations/google_drive_sync.py` | missing |

### Supporting runtime dependency discovered during audit

| Reference file | Why it is migration-critical | Proposed Studio destination | Status |
|---|---|---|---|
| `app/llmctl-rag/tasks_worker.py` | Core index execution path (fresh/delta), progress checkpoints, pause/resume/cancel semantics, queue-routing behavior | `app/llmctl-studio/src/rag/worker/tasks.py` | missing |

## Web/API surface summary

- Route count in standalone RAG app: `34`.
- Includes:
  - source CRUD and source-specific index controls
  - task list/detail/status and lifecycle controls
  - collection list/detail/delete
  - provider/settings updates
  - Drive verify, GitHub repo list, Chroma connectivity check
  - chat API with merged retrieval across source collections
- Scheduler behavior in `web_app.py`:
  - poll loop via background thread
  - schedules due sources
  - currently enqueues scheduled runs with `fresh` mode

## Test Coverage Audit and Studio parity mapping

Test modules discovered:
- `17` modules under `app/llmctl-rag/tests/test_*.py`.

### Baseline local execution check

Executed command:
- `python3 -m unittest discover -s app/llmctl-rag/tests -v`

Result:
- `38` tests discovered.
- `29` passed.
- `9` import/dependency errors in this environment (`sqlalchemy`, `numpy`, and transitive parser deps).

### Test module -> Studio parity target

| RAG test module | Coverage intent | Studio parity target |
|---|---|---|
| `app/llmctl-rag/tests/test_chunkers.py` | token/PDF chunk payload behavior | `app/llmctl-studio/tests/rag/test_chunkers.py` |
| `app/llmctl-rag/tests/test_code_spans.py` | code symbol span extraction + language detection | `app/llmctl-studio/tests/rag/test_code_spans.py` |
| `app/llmctl-rag/tests/test_config_precedence.py` | DB settings vs env precedence | `app/llmctl-studio/tests/rag/test_config_precedence.py` |
| `app/llmctl-rag/tests/test_doc_structures.py` | markdown/html structure extraction | `app/llmctl-studio/tests/rag/test_doc_structures.py` |
| `app/llmctl-rag/tests/test_google_drive_sync.py` | Drive verify/count/sync + progress callback | `app/llmctl-studio/tests/rag/test_google_drive_sync.py` |
| `app/llmctl-rag/tests/test_office_parsers.py` | docx/pptx/xlsx parse output type | `app/llmctl-studio/tests/rag/test_office_parsers.py` |
| `app/llmctl-rag/tests/test_parsers.py` | parser registry behavior and doc-type filtering | `app/llmctl-studio/tests/rag/test_parsers.py` |
| `app/llmctl-rag/tests/test_pdf_pipeline.py` | vector gating heuristics for PDFs | `app/llmctl-studio/tests/rag/test_pdf_pipeline.py` |
| `app/llmctl-rag/tests/test_performance.py` | token chunker speed threshold | `app/llmctl-studio/tests/rag/test_performance.py` |
| `app/llmctl-rag/tests/test_provider_adapters.py` | Gemini/OpenAI embedding adapter behavior | `app/llmctl-studio/tests/rag/test_provider_adapters.py` |
| `app/llmctl-rag/tests/test_quality.py` | content retention in chunking | `app/llmctl-studio/tests/rag/test_quality.py` |
| `app/llmctl-rag/tests/test_regression.py` | golden manifest chunk-count regression | `app/llmctl-studio/tests/rag/test_regression.py` |
| `app/llmctl-rag/tests/test_web_app_collections.py` | collections routes/template interactions | `app/llmctl-studio/tests/rag/test_web_collections.py` |
| `app/llmctl-rag/tests/test_web_app_delta_index.py` | delta-mode route/UI/JS wiring | `app/llmctl-studio/tests/rag/test_web_delta_index.py` |
| `app/llmctl-rag/tests/test_web_app_prompts.py` | prompt wording constraints | `app/llmctl-studio/tests/rag/test_web_prompts.py` |
| `app/llmctl-rag/tests/test_web_app_sources.py` | source clear/schedule/incomplete-task guardrails | `app/llmctl-studio/tests/rag/test_web_sources.py` |
| `app/llmctl-rag/tests/test_web_app_tasks.py` | progress payload and task detail rendering | `app/llmctl-studio/tests/rag/test_web_tasks.py` |

## Risk Register

| Severity | Risk | Evidence from audit | Mitigation target |
|---|---|---|---|
| high | Pause/resume/cancel parity regression | `tasks_worker.py` checkpoint/metadata flow spans fresh + delta + source-type branches | Port worker first with checkpoint fixtures; add parity tests before UI cutover |
| high | Delta indexing correctness drift | `source_file_states_store.py` + `_run_source_delta_index` use fingerprints/removal semantics and fallback resets | Port state schema + delta logic together; snapshot comparison tests on changed/deleted files |
| high | PDF extraction parity loss | `pdf_pipeline.py` contains OCR/vector gating heuristics and payload structure used by `pdf_chunker` | Preserve heuristic constants and payload shape; add page-level parity fixtures |
| high | Provider adapter behavior mismatch | `provider_adapters.py` has Gemini batch endpoint behavior + API error shaping + OpenAI lazy loader | Port adapters with contract tests from `test_provider_adapters.py` |
| medium | Scheduler mode mismatch with v1 scope | Current scheduler path enqueues scheduled jobs as `fresh` only | Add schedule mode persistence and scheduling branch in Stage 3/6 |
| medium | Monolithic web logic increases cutover risk | `web_app.py` mixes routes, scheduler, orchestration, chat assembly | Split into service/router modules in Studio before adding endpoints |
| medium | Git sync side effects and host-key behavior | `git_sync.py` uses hard reset and custom `GIT_SSH_COMMAND` with known_hosts | Reproduce behavior in isolated git queue workers; include SSH/PAT integration tests |
| medium | Google Drive sync destructive local mirror behavior | `sync_folder()` clears destination directory before refresh | Keep behavior explicit in UX and logs; guard against path misconfiguration |
| medium | Test suite quality gap for runtime behaviors | Several web tests are source-string assertions instead of request-level integration tests | Port existing tests, then add API integration tests for critical paths |
| low | Optional dependency variance by environment | unittest run failed imports for `sqlalchemy` and `numpy` in this environment | Define Studio RAG test extras/dependency group and CI matrix |

## Stage 1 completion verdict

- Stage 1 inventory items listed in the plan are fully audited.
- Capability matrix and risk register are produced in this artifact.
- Ready to proceed to Stage 2 architecture finalization using this destination map.
