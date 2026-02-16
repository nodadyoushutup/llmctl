#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)

"${REPO_ROOT}/app/llmctl-studio/docker/build-studio.sh"
"${REPO_ROOT}/app/llmctl-rag/docker/build-rag.sh"
