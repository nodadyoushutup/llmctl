#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
IMAGE_NAME="${IMAGE_NAME:-llmctl-executor-base:latest}"
INSTALL_CLAUDE="${INSTALL_CLAUDE:-true}"
VLLM_VERSION="${VLLM_VERSION:-0.8.5}"

cd "${REPO_ROOT}"

docker build \
  --build-arg INSTALL_CLAUDE="${INSTALL_CLAUDE}" \
  --build-arg VLLM_VERSION="${VLLM_VERSION}" \
  -f app/llmctl-executor/Dockerfile.base \
  -t "${IMAGE_NAME}" \
  .
