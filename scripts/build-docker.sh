#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)

echo "Building llmctl-studio-backend:latest in current Docker context..."
"${REPO_ROOT}/app/llmctl-studio-backend/docker/build-studio.sh"

echo "Building llmctl-executor:latest in current Docker context..."
"${REPO_ROOT}/app/llmctl-executor/build-executor.sh"

echo "Building llmctl-celery-worker:latest in current Docker context..."
"${REPO_ROOT}/app/llmctl-celery-worker/docker/build-celery-worker.sh"

echo "Done: built llmctl-studio-backend:latest, llmctl-executor:latest, and llmctl-celery-worker:latest."
