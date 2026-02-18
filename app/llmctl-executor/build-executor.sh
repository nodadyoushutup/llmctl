#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
IMAGE_NAME="${IMAGE_NAME:-llmctl-executor:latest}"
INSTALL_VLLM="${INSTALL_VLLM:-false}"
VLLM_VERSION="${VLLM_VERSION:-0.9.0}"
TRANSFORMERS_VERSION="${TRANSFORMERS_VERSION:-4.53.3}"
VERSION_TAG="${1:-}"

if [[ $# -gt 1 ]]; then
  echo "Usage: $0 [version_tag]" >&2
  exit 1
fi

if [[ -n "${VERSION_TAG}" ]]; then
  if [[ "${IMAGE_NAME}" =~ :[^/]+$ ]]; then
    IMAGE_NAME="${IMAGE_NAME%:*}:${VERSION_TAG}"
  else
    IMAGE_NAME="${IMAGE_NAME}:${VERSION_TAG}"
  fi
fi

cd "${REPO_ROOT}"

docker build \
  --build-arg INSTALL_VLLM="${INSTALL_VLLM}" \
  --build-arg VLLM_VERSION="${VLLM_VERSION}" \
  --build-arg TRANSFORMERS_VERSION="${TRANSFORMERS_VERSION}" \
  -f app/llmctl-executor/Dockerfile \
  -t "${IMAGE_NAME}" \
  .
