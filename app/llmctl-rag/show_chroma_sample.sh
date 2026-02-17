#!/usr/bin/env bash
set -euo pipefail

CHROMA_HOST="${CHROMA_HOST:-localhost}"
CHROMA_PORT="${CHROMA_PORT:-8000}"
CHROMA_COLLECTION="${CHROMA_COLLECTION:-example}"
CHROMA_PEEK_LIMIT="${CHROMA_PEEK_LIMIT:-3}"
CHROMA_DOC_CHARS="${CHROMA_DOC_CHARS:-500}"
CHROMA_PATH_SUFFIX="${CHROMA_PATH_SUFFIX:-.py}"
CHROMA_SCAN_LIMIT="${CHROMA_SCAN_LIMIT:-200}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

run_python() {
  "$PYTHON_BIN" - <<'PY'
import os
import sys

try:
    import chromadb
except Exception as exc:
    print(f"chromadb import failed: {exc}", file=sys.stderr)
    raise

host = os.environ.get("CHROMA_HOST", "localhost")
port = int(os.environ.get("CHROMA_PORT", "8000"))
collection_name = os.environ.get("CHROMA_COLLECTION", "example")
peek_limit = int(os.environ.get("CHROMA_PEEK_LIMIT", "3"))
max_chars = int(os.environ.get("CHROMA_DOC_CHARS", "500"))
path_suffix = os.environ.get("CHROMA_PATH_SUFFIX", ".py")
scan_limit = int(os.environ.get("CHROMA_SCAN_LIMIT", "200"))
scan_limit = max(scan_limit, peek_limit)

client = chromadb.HttpClient(host=host, port=port)
try:
    collections = client.list_collections()
except Exception as exc:
    print(f"Failed to connect to Chroma at {host}:{port}: {exc}", file=sys.stderr)
    sys.exit(1)

print(f"Chroma @ {host}:{port}")
if not collections:
    print("No collections found.")
    sys.exit(0)

print("Collections:")
for col in collections:
    print(f"- {col.name}")

names = {col.name for col in collections}
if collection_name in names:
    target = collection_name
    print(f"Using collection: {target}")
else:
    target = collections[0].name
    print(f"Using collection: {target} (CHROMA_COLLECTION={collection_name} not found)")

collection = client.get_collection(name=target)
print(f"Filtering paths ending with: {path_suffix}")

def iter_batches():
    batch_size = min(100, scan_limit)
    offset = 0
    try:
        while offset < scan_limit:
            batch = collection.get(
                limit=batch_size,
                offset=offset,
                include=["documents", "metadatas"],
            )
            ids = batch.get("ids", [])
            if not ids:
                break
            yield batch
            offset += batch_size
    except Exception as exc:
        print(f"collection.get failed, falling back to peek: {exc}", file=sys.stderr)
        yield collection.peek(limit=scan_limit)

def is_match(path: str) -> bool:
    if not path_suffix:
        return True
    return path.lower().endswith(path_suffix.lower())

selected = []
for batch in iter_batches():
    ids = batch.get("ids", [])
    metadatas = batch.get("metadatas", [])
    documents = batch.get("documents", [])
    for i, doc_id in enumerate(ids):
        meta = metadatas[i] if i < len(metadatas) and metadatas[i] else {}
        path = meta.get("path", "")
        if not is_match(path):
            continue
        doc = documents[i] if i < len(documents) else ""
        selected.append((doc_id, meta, doc))
        if len(selected) >= peek_limit:
            break
    if len(selected) >= peek_limit:
        break

if not selected:
    print("No matching documents found in collection.")
    sys.exit(0)

for idx, (doc_id, meta, doc) in enumerate(selected, start=1):
    path = meta.get("path", "unknown")
    start_line = meta.get("start_line", "?")
    end_line = meta.get("end_line", "?")
    print(f"\n#{idx} {doc_id} {path} ({start_line}-{end_line})")
    if doc:
        snippet = doc[:max_chars]
        print(snippet)
        if len(doc) > max_chars:
            print(f"... ({len(doc)} chars total)")
PY
}

if ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import chromadb
PY
then
  cat <<'MSG' >&2
chromadb is not available in your current Python environment.

If you're using the llmctl-rag container, run this script inside it:
  kubectl -n llmctl exec deploy/llmctl-rag -- \
    bash -lc "CHROMA_COLLECTION=${CHROMA_COLLECTION} /app/app/llmctl-rag/show_chroma_sample.sh"

Or install deps locally:
  python3 -m pip install -r app/llmctl-rag/requirements.txt
MSG
  exit 1
fi

run_python
