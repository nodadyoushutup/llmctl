#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
IMAGE_NAME="${IMAGE_NAME:-llmctl-executor:latest}"
INSTALL_VLLM="${INSTALL_VLLM:-true}"
INSTALL_CLAUDE="${INSTALL_CLAUDE:-true}"

cd "${REPO_ROOT}"

docker build \
  --build-arg INSTALL_VLLM="${INSTALL_VLLM}" \
  --build-arg INSTALL_CLAUDE="${INSTALL_CLAUDE}" \
  -f app/llmctl-executor/Dockerfile \
  -t "${IMAGE_NAME}" \
  .
