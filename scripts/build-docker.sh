#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)

echo "Building llmctl-studio:latest in current Docker context..."
"${REPO_ROOT}/app/llmctl-studio-backend/docker/build-studio.sh"

echo "Building llmctl-executor:latest in current Docker context..."
"${REPO_ROOT}/app/llmctl-executor/build-executor.sh"

echo "Done: built llmctl-studio:latest and llmctl-executor:latest."
