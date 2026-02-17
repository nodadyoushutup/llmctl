#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)

usage() {
  cat <<'EOF'
Usage: scripts/build-minikube.sh [--profile <name>]

Builds llmctl-studio:latest, llmctl-executor:latest, and llmctl-celery-worker:latest into the selected Minikube profile's Docker daemon.

Options:
  --profile <name>   Minikube profile to target (default: $MINIKUBE_PROFILE or llmctl)
  -h, --help         Show this help message
EOF
}

PROFILE="${MINIKUBE_PROFILE:-llmctl}"

while [ $# -gt 0 ]; do
  case "$1" in
    --profile)
      if [ $# -lt 2 ]; then
        echo "Error: --profile requires a value." >&2
        usage
        exit 2
      fi
      PROFILE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Error: Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if ! command -v minikube >/dev/null 2>&1; then
  echo "Error: minikube is not installed or not in PATH." >&2
  exit 1
fi

if ! minikube -p "${PROFILE}" status >/dev/null 2>&1; then
  echo "Error: minikube profile '${PROFILE}' is not running." >&2
  echo "Start it with: minikube -p ${PROFILE} start" >&2
  exit 1
fi

echo "Building llmctl-studio:latest, llmctl-executor:latest, and llmctl-celery-worker:latest in minikube profile '${PROFILE}'..."
(
  eval "$(minikube -p "${PROFILE}" docker-env)"
  "${REPO_ROOT}/app/llmctl-studio-backend/docker/build-studio.sh"
  "${REPO_ROOT}/app/llmctl-executor/build-executor.sh"
  "${REPO_ROOT}/app/llmctl-celery-worker/docker/build-celery-worker.sh"
)

minikube -p "${PROFILE}" ssh -- \
  "docker images --format '{{.Repository}}:{{.Tag}}' | grep -q '^llmctl-studio:latest$'"
minikube -p "${PROFILE}" ssh -- \
  "docker images --format '{{.Repository}}:{{.Tag}}' | grep -q '^llmctl-executor:latest$'"
minikube -p "${PROFILE}" ssh -- \
  "docker images --format '{{.Repository}}:{{.Tag}}' | grep -q '^llmctl-celery-worker:latest$'"

echo "Done: llmctl-studio:latest, llmctl-executor:latest, and llmctl-celery-worker:latest are available inside minikube profile '${PROFILE}'."
