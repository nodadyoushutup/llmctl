# llmctl-rag

Lightweight RAG utilities for indexing this repo into ChromaDB and running retrieval.

## Quickstart

1) Install deps (in a venv is recommended)

```
python3 -m venv .venv
. .venv/bin/activate
pip install -r app/llmctl-rag/requirements.txt
```

2) Ensure Chroma is running (from repo root)

```
docker compose -f docker/docker-compose.yml up -d chromadb
```

3) Index the repo (from repo root)

```
export OPENAI_API_KEY=your_key_here
python3 app/llmctl-rag/ingest.py --reset
```

4) Query

```
python3 app/llmctl-rag/query.py "Where is the task model defined?"
```

## Flask chat UI

Start the chat UI after you have indexed the repo:

```
export OPENAI_API_KEY=your_key_here
python3 app/llmctl-rag/run.py
```

Then open http://localhost:5050.

Optional env overrides:

- OPENAI_CHAT_MODEL (default: gpt-4o-mini)
- OPENAI_CHAT_TEMPERATURE (default: 0.2)
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
- OPENAI_API_KEY (required for embedding)
- OPENAI_EMBED_MODEL (default: text-embedding-3-small)
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
- RAG_MAX_FILE_BYTES_BY_TYPE (e.g., `pdf=20000000;docx=5000000`)
- RAG_EXCLUDE_GLOBS_BY_TYPE (e.g., `pdf=*.draft.pdf;code=vendor/*|*.min.js`)
- RAG_CHUNK_LINES_BY_TYPE (e.g., `code=200;markdown=120`)
- RAG_CHUNK_OVERLAP_LINES_BY_TYPE (e.g., `code=40;markdown=20`)
- RAG_WATCH_DEBOUNCE_S (default: 1.0)

## Notes

- The ingester skips large/binary files and common build/cache directories.
- Use --reset when you want a clean reindex.
- If you run ingest inside Docker, set CHROMA_HOST=chromadb.
- For watch mode in Docker, use the `llmctl-rag` service in docker-compose and mount the repo.
