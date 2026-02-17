#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../../.." && pwd)
IMAGE_NAME="${IMAGE_NAME:-llmctl-studio-backend:latest}"
DOCKER_GID="${DOCKER_GID:-}"

if [ -z "${DOCKER_GID}" ] && [ -S /var/run/docker.sock ]; then
  DOCKER_GID="$(stat -c '%g' /var/run/docker.sock)"
fi

DOCKER_GID="${DOCKER_GID:-999}"

cd "${REPO_ROOT}"

docker build \
  --build-arg DOCKER_GID="${DOCKER_GID}" \
  -f app/llmctl-studio-backend/docker/Dockerfile \
  -t "${IMAGE_NAME}" \
  .
