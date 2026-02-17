#!/usr/bin/env bash
set -euo pipefail

PROFILE="${MINIKUBE_PROFILE:-llmctl}"
MOUNT_TARGET="${MINIKUBE_LIVE_CODE_TARGET:-/workspace/llmctl}"
PROJECT_ROOT_INPUT="${1:-$(pwd)}"

fail() {
  echo "[minikube-live-code-mount.sh] ERROR: $*" >&2
  exit 1
}

if ! command -v minikube >/dev/null 2>&1; then
  fail "minikube command not found in PATH."
fi

if ! minikube -p "${PROFILE}" status >/dev/null 2>&1; then
  fail "minikube profile '${PROFILE}' is not running."
fi

if [[ ! -d "${PROJECT_ROOT_INPUT}" ]]; then
  fail "project root does not exist: ${PROJECT_ROOT_INPUT}"
fi

PROJECT_ROOT="$(cd "${PROJECT_ROOT_INPUT}" && pwd)"

echo "[minikube-live-code-mount.sh] profile=${PROFILE} source=${PROJECT_ROOT} target=${MOUNT_TARGET}"
echo "[minikube-live-code-mount.sh] keep this process running while using kubernetes/llmctl-studio/overlays/dev"

exec minikube -p "${PROFILE}" mount "${PROJECT_ROOT}:${MOUNT_TARGET}"
