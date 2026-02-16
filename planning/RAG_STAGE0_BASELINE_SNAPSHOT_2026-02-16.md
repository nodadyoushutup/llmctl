# RAG Stage 0 Baseline Snapshot (2026-02-16)

This artifact records the standalone `llmctl-rag` baseline before Studio parity migration work.

## Baseline commit hashes

- Repository `HEAD`: `7b7adda10e54208a84d9812f6e0c5072baa2fdac`
- Latest commit touching `app/llmctl-rag`: `7b7adda10e54208a84d9812f6e0c5072baa2fdac` (`2026-02-15T21:38:57-05:00`)
- Latest commit touching `app/llmctl-studio`: `7b7adda10e54208a84d9812f6e0c5072baa2fdac` (`2026-02-15T21:38:57-05:00`)

## UI snapshot inventory

Templates present in `app/llmctl-rag/web/templates/`:

- `index.html`
- `sources.html`
- `source_new.html`
- `source_detail.html`
- `source_edit.html`
- `collections.html`
- `collection_detail.html`
- `tasks.html`
- `task_detail.html`

Static assets present in `app/llmctl-rag/web/static/`:

- `app.js`
- `styles.css`

## API and route surface snapshot

Routes declared in `app/llmctl-rag/web_app.py`:

- `GET /`
- `GET /sources`
- `GET /sources/new`
- `GET /collections`
- `GET /collections/detail`
- `GET /sources/<int:source_id>`
- `GET /sources/<int:source_id>/edit`
- `GET /tasks`
- `GET /tasks/<int:task_id>`
- `GET /tasks/<int:task_id>/status`
- `GET /api/tasks/status`
- `POST /tasks/<int:task_id>/delete`
- `POST /tasks/<int:task_id>/cancel`
- `POST /tasks/<int:task_id>/pause`
- `POST /tasks/<int:task_id>/resume`
- `POST /settings/github`
- `POST /settings/rag`
- `POST /settings/google-drive`
- `POST /sources`
- `POST /sources/<int:source_id>`
- `POST /sources/<int:source_id>/clear`
- `POST /sources/<int:source_id>/delete`
- `POST /collections/delete`
- `GET /api/github/repos`
- `POST /api/google-drive/verify`
- `GET /api/index`
- `POST /api/index`
- `GET /api/sources/<int:source_id>/index`
- `POST /api/sources/<int:source_id>/index`
- `POST /api/sources/<int:source_id>/pause`
- `POST /api/sources/<int:source_id>/resume`
- `POST /api/chat`
- `GET /api/health`
- `POST /api/chroma/test`

## Test snapshot

Discovered test modules in `app/llmctl-rag/tests/`:

- `test_chunkers.py`
- `test_code_spans.py`
- `test_config_precedence.py`
- `test_doc_structures.py`
- `test_google_drive_sync.py`
- `test_office_parsers.py`
- `test_parsers.py`
- `test_pdf_pipeline.py`
- `test_performance.py`
- `test_provider_adapters.py`
- `test_quality.py`
- `test_regression.py`
- `test_web_app_collections.py`
- `test_web_app_delta_index.py`
- `test_web_app_prompts.py`
- `test_web_app_sources.py`
- `test_web_app_tasks.py`

Attempted baseline test command:

- Command: `python3 -m pytest app/llmctl-rag/tests -q`
- Result: failed in current environment (`No module named pytest`).

## Notes

- This snapshot is inventory-based and keeps `app/llmctl-rag` unchanged.
- UI screenshot capture is deferred to manual parity verification during shadow/cutover gates.
