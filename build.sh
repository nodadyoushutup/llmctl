#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

"${SCRIPT_DIR}/app/llmctl-studio/docker/build-studio.sh"
"${SCRIPT_DIR}/app/llmctl-rag/docker/build-rag.sh"
