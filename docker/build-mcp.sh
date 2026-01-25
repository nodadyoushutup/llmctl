#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
IMAGE_NAME="llmctl-mcp:latest"

cd "${REPO_ROOT}"

docker build -f docker/llmctl-mcp.Dockerfile -t "${IMAGE_NAME}" .
