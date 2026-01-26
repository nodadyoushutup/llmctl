#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

"${SCRIPT_DIR}/app/llmctl-studio/docker/build-studio.sh"
"${SCRIPT_DIR}/app/llmctl-mcp/docker/build-llmctl-mcp.sh"
"${SCRIPT_DIR}/app/llmctl-mcp/docker/build-chromadb-mcp.sh"
"${SCRIPT_DIR}/app/llmctl-mcp/docker/build-github-mcp.sh"
"${SCRIPT_DIR}/app/llmctl-rag/docker/build-rag.sh"
