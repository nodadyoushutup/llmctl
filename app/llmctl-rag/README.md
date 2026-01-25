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
python app/llmctl-rag/ingest.py --reset
```

4) Query

```
python app/llmctl-rag/query.py "Where is the task model defined?"
```

## Watch mode

Run a watchdog to keep the collection in sync as files change.

```
python app/llmctl-rag/watch.py
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
python app/llmctl-rag/watch.py
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
- RAG_EXCLUDE_DIRS (comma-separated)
- RAG_EXCLUDE_GLOBS (comma-separated)
- RAG_INCLUDE_GLOBS (comma-separated)
- RAG_WATCH_DEBOUNCE_S (default: 1.0)

## Notes

- The ingester skips large/binary files and common build/cache directories.
- Use --reset when you want a clean reindex.
- If you run ingest inside Docker, set CHROMA_HOST=chromadb.
- For watch mode in Docker, use the `llmctl-rag` service in docker-compose and mount the repo.
