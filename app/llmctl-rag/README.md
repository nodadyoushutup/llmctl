# llmctl-rag

Lightweight RAG utilities for indexing this repo into ChromaDB and running retrieval.

## Quickstart

1) Install deps (in a venv is recommended)

```
python3 -m venv .venv
. .venv/bin/activate
pip install -r app/llmctl-rag/requirements.txt
```

2) Ensure Chroma is running in Kubernetes (from repo root)

```
kubectl apply -f kubernetes/llmctl-studio/base/chromadb.yaml
```

3) Index the repo (from repo root)

```
export RAG_EMBED_PROVIDER=openai
export OPENAI_API_KEY=your_key_here
python3 app/llmctl-rag/ingest.py --reset
```

4) Query

```
python3 app/llmctl-rag/query.py "Where is the task model defined?"
```

Gemini example:

```
export RAG_EMBED_PROVIDER=gemini
export GEMINI_API_KEY=your_key_here
python3 app/llmctl-rag/ingest.py --reset
```

## Flask chat UI

Start the chat UI after you have indexed the repo:

```
export RAG_CHAT_PROVIDER=openai
export OPENAI_API_KEY=your_key_here
python3 app/llmctl-rag/run.py
```

Then open http://localhost:5050.

Optional env overrides:

- RAG_CHAT_PROVIDER (default: openai, options: openai | gemini)
- OPENAI_CHAT_MODEL (default: gpt-4o-mini)
- GEMINI_CHAT_MODEL (default: gemini-2.5-flash)
- RAG_CHAT_TEMPERATURE (default: 0.2)
- RAG_CHAT_RESPONSE_STYLE (default: high, options: low | medium | high)
- RAG_CHAT_TOP_K (default: 5)
- RAG_CHAT_MAX_HISTORY (default: 8)
- RAG_CHAT_MAX_CONTEXT_CHARS (default: 12000)
- RAG_CHAT_SNIPPET_CHARS (default: 600)
- RAG_CHAT_CONTEXT_BUDGET_TOKENS (default: 8000)
- RAG_WEB_PORT (default: 5050)

The UI includes a Settings tab that saves RAG config into the local
`llmctl-rag` SQLite database (`data/llmctl-rag/llmctl-rag.db` in the repo,
or `/data/llmctl-rag/llmctl-rag.db` in Docker). Environment variables still
override DB values when set.

Use the "Index now" button in the chat view to manually kick off indexing.

Indexing controls in the Sources/Tasks views now support:

- **Fresh index**: start a new run from the beginning for that source.
- **Pause**: request a graceful stop after the current file finishes.
- **Resume**: continue a paused run from the saved checkpoint.

When you trigger indexing across all sources, llmctl-rag now fans out one Celery
task per source so different sources can index concurrently.

Pause checkpoints are stored in the local `llmctl-rag` SQLite database, so they
survive service restarts/reboots (assuming Redis stays available for Celery).

## Google Drive sources

The Sources UI supports `Google Drive folder` sources. Setup flow:

1) Open Settings and paste the Google service account JSON key into
   **Google Drive integration**.
2) Share the target Drive folder with the service account email
   (`client_email` from that JSON).
3) Create a source with type **Google Drive folder** and paste the folder ID.
4) Use **Verify access** on the source form before creating the source.

During indexing, llmctl-rag syncs that folder into the local data directory and
then indexes the synced files.

## Watch mode

Run a watchdog to keep the collection in sync as files change.

```
python3 app/llmctl-rag/watch.py
```

Options:

- `--reset`: delete and recreate the collection before the initial ingest
- `--skip-initial`: skip the initial full ingest and only process changes
- `--debounce`: seconds to wait for a quiet period before indexing changes

## Git poll mode

Poll a GitHub repository/branch and reindex on changes.

```
export RAG_MODE=git
export RAG_GIT_URL=https://github.com/yourorg/yourrepo
export RAG_GIT_BRANCH=main
export RAG_GIT_POLL_S=300
export RAG_GIT_DIR=/tmp/llmctl-rag-repo
python3 app/llmctl-rag/watch.py
```

## Configuration (env)

- CHROMA_HOST (default: localhost)
- CHROMA_PORT (default: 8000)
- CHROMA_COLLECTION (default: llmctl_repo)
- RAG_EMBED_PROVIDER (default: openai, options: openai | gemini)
- RAG_CHAT_PROVIDER (default: openai, options: openai | gemini)
- OPENAI_API_KEY (required when OpenAI provider is selected)
- OPENAI_EMBED_MODEL (default: text-embedding-3-small)
- OPENAI_CHAT_MODEL (default: gpt-4o-mini)
- GEMINI_API_KEY or GOOGLE_API_KEY (required when Gemini provider is selected)
- GEMINI_EMBED_MODEL (default: models/gemini-embedding-001)
- GEMINI_CHAT_MODEL (default: gemini-2.5-flash)
- RAG_CHAT_TEMPERATURE (default: 0.2)
- RAG_CHAT_RESPONSE_STYLE (default: high, options: low | medium | high)
- OPENAI_CHAT_TEMPERATURE (legacy alias still supported)
- RAG_MODE (default: local, options: local | git)
- RAG_GIT_URL (required when RAG_MODE=git)
- RAG_GIT_BRANCH (default: main)
- RAG_GIT_POLL_S (default: 300)
- RAG_GIT_DIR (default: /tmp/llmctl-rag-repo)
- RAG_ROOT (default: repo root)
- RAG_CHUNK_LINES (default: 120)
- RAG_CHUNK_OVERLAP_LINES (default: 20)
- RAG_MAX_FILE_BYTES (default: 1000000)
- RAG_EMBED_MAX_TOKENS_PER_REQUEST (default: 300000)
- RAG_EMBED_MAX_TOKENS_PER_INPUT (default: 8192)
- RAG_EMBED_MAX_BATCH_ITEMS (default: 100)
- RAG_EMBED_PARALLEL_REQUESTS (default: CELERY_WORKER_CONCURRENCY, concurrent embedding/upsert requests per indexing pipeline)
- RAG_EMBED_TARGET_TOKENS_PER_MINUTE (default: 0, disabled)
- RAG_EMBED_MIN_REQUEST_INTERVAL_S (default: 0, disabled)
- RAG_EMBED_RATE_LIMIT_MAX_RETRIES (default: 6)
- RAG_DRIVE_SYNC_WORKERS (default: 4, Google Drive download concurrency per source)
- RAG_INDEX_PARALLEL_WORKERS (default: 1, per-source file indexing fan-out within one index task)
- RAG_PDF_PAGE_WORKERS (default: 1, per-file PDF page parsing fan-out)
- RAG_CHAT_TOP_K (default: 5)
- RAG_CHAT_MAX_HISTORY (default: 8)
- RAG_CHAT_MAX_CONTEXT_CHARS (default: 12000)
- RAG_CHAT_SNIPPET_CHARS (default: 600)
- RAG_CHAT_CONTEXT_BUDGET_TOKENS (default: 8000)
- RAG_EXCLUDE_DIRS (comma-separated)
- RAG_EXCLUDE_GLOBS (comma-separated)
- RAG_INCLUDE_GLOBS (comma-separated)
- RAG_ENABLED_DOC_TYPES (comma-separated doc types; empty = all)
- RAG_OCR_ENABLED (default: true)
- RAG_OCR_LANG (default: eng)
- RAG_OCR_DPI (default: 150)
- RAG_OCR_TIMEOUT_S (default: 45, set 0 to disable timeout)
- RAG_OCR_INCLUDE_CHAR_BOXES (default: false, enables second OCR pass per page)
  - OCR is only attempted on PDF pages where embedded images are detected.
  - Vector geometry payloads are captured only when page geometry looks like actual drawings (and skipped for low-signal axis-aligned table/layout pages).
- RAG_MAX_FILE_BYTES_BY_TYPE (e.g., `pdf=20000000;docx=5000000`)
- RAG_EXCLUDE_GLOBS_BY_TYPE (e.g., `pdf=*.draft.pdf;code=vendor/*|*.min.js`)
- RAG_CHUNK_LINES_BY_TYPE (e.g., `code=200;markdown=120`)
- RAG_CHUNK_OVERLAP_LINES_BY_TYPE (e.g., `code=40;markdown=20`)
- RAG_WATCH_DEBOUNCE_S (default: 1.0)
- CELERY_WORKER_CONCURRENCY (default in Docker compose: 6)
- CELERY_WORKER_QUEUES (default: llmctl_rag,llmctl_rag_index,llmctl_rag_drive,llmctl_rag_git)

If you hit OpenAI embedding `429` responses while indexing, set:

```
export RAG_EMBED_MAX_TOKENS_PER_REQUEST=120000
export RAG_EMBED_TARGET_TOKENS_PER_MINUTE=250000
export RAG_EMBED_MIN_REQUEST_INTERVAL_S=0.75
export RAG_EMBED_PARALLEL_REQUESTS=6
```

## Provider notes

- ChromaDB is unchanged. Only embedding/chat providers are switched.
- Keep embedding provider/model stable for indexed collections. If you change them, run:

```
python3 app/llmctl-rag/ingest.py --reset
```

## Notes

- The ingester skips large/binary files and common build/cache directories.
- Use --reset when you want a clean reindex.
- If you run ingest inside Docker, set CHROMA_HOST=llmctl-chromadb.
- For watch mode in Docker, use the `llmctl-rag` service in docker-compose and mount the repo.
