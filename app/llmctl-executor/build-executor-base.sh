#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
IMAGE_NAME="${IMAGE_NAME:-llmctl-executor-vllm:latest}"
VLLM_VERSION="${VLLM_VERSION:-0.9.0}"
TRANSFORMERS_VERSION="${TRANSFORMERS_VERSION:-4.53.3}"
INSTALL_STUDIO_BACKEND_DEPS="${INSTALL_STUDIO_BACKEND_DEPS:-true}"
PUSH_IMAGE="${PUSH_IMAGE:-false}"
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

if [[ "${VLLM_VERSION}" == "0.9.0" && ! "${TRANSFORMERS_VERSION}" =~ ^4\. ]]; then
  echo "Unsupported dependency combination: vllm ${VLLM_VERSION} requires transformers 4.x (got ${TRANSFORMERS_VERSION})." >&2
  echo "Unset TRANSFORMERS_VERSION or set it to 4.53.3 before building." >&2
  exit 1
fi

if [[ "${PUSH_IMAGE}" != "true" && "${PUSH_IMAGE}" != "false" ]]; then
  echo "Invalid PUSH_IMAGE value '${PUSH_IMAGE}'. Expected 'true' or 'false'." >&2
  exit 1
fi

if [[ "${INSTALL_STUDIO_BACKEND_DEPS}" != "true" && "${INSTALL_STUDIO_BACKEND_DEPS}" != "false" ]]; then
  echo "Invalid INSTALL_STUDIO_BACKEND_DEPS value '${INSTALL_STUDIO_BACKEND_DEPS}'. Expected 'true' or 'false'." >&2
  exit 1
fi

cd "${REPO_ROOT}"

if [[ "${PUSH_IMAGE}" == "true" ]]; then
  if docker buildx version >/dev/null 2>&1; then
    docker buildx build \
      --build-arg INSTALL_STUDIO_BACKEND_DEPS="${INSTALL_STUDIO_BACKEND_DEPS}" \
      --build-arg VLLM_VERSION="${VLLM_VERSION}" \
      --build-arg TRANSFORMERS_VERSION="${TRANSFORMERS_VERSION}" \
      -f app/llmctl-executor/Dockerfile.base \
      -t "${IMAGE_NAME}" \
      --push \
      .
  else
    docker build \
      --build-arg INSTALL_STUDIO_BACKEND_DEPS="${INSTALL_STUDIO_BACKEND_DEPS}" \
      --build-arg VLLM_VERSION="${VLLM_VERSION}" \
      --build-arg TRANSFORMERS_VERSION="${TRANSFORMERS_VERSION}" \
      -f app/llmctl-executor/Dockerfile.base \
      -t "${IMAGE_NAME}" \
      .
    docker push "${IMAGE_NAME}"
  fi
else
  docker build \
    --build-arg INSTALL_STUDIO_BACKEND_DEPS="${INSTALL_STUDIO_BACKEND_DEPS}" \
    --build-arg VLLM_VERSION="${VLLM_VERSION}" \
    --build-arg TRANSFORMERS_VERSION="${TRANSFORMERS_VERSION}" \
    -f app/llmctl-executor/Dockerfile.base \
    -t "${IMAGE_NAME}" \
    .
fi
