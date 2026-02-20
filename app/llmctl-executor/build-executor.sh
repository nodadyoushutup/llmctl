#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
IMAGE_NAME="${IMAGE_NAME:-llmctl-executor-frontier:latest}"
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
  -f app/llmctl-executor/Dockerfile \
  -t "${IMAGE_NAME}" \
  .
