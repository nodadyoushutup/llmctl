#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../../.." && pwd)
IMAGE_NAME="${IMAGE_NAME:-llmctl-studio-frontend:latest}"
VITE_API_BASE_URL="${VITE_API_BASE_URL:-}"
VITE_API_BASE_PATH="${VITE_API_BASE_PATH:-/api}"
VITE_WEB_BASE_PATH="${VITE_WEB_BASE_PATH:-/web}"
VITE_SOCKET_PATH="${VITE_SOCKET_PATH:-/api/socket.io}"
VITE_SOCKET_NAMESPACE="${VITE_SOCKET_NAMESPACE:-/rt}"

cd "${REPO_ROOT}"

docker build \
  --build-arg VITE_API_BASE_URL="${VITE_API_BASE_URL}" \
  --build-arg VITE_API_BASE_PATH="${VITE_API_BASE_PATH}" \
  --build-arg VITE_WEB_BASE_PATH="${VITE_WEB_BASE_PATH}" \
  --build-arg VITE_SOCKET_PATH="${VITE_SOCKET_PATH}" \
  --build-arg VITE_SOCKET_NAMESPACE="${VITE_SOCKET_NAMESPACE}" \
  -f app/llmctl-studio-frontend/docker/Dockerfile \
  -t "${IMAGE_NAME}" \
  .
