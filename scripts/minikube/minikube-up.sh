#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME=$(basename "${BASH_SOURCE[0]}")
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
INSTALL_SCRIPT="${REPO_ROOT}/scripts/install/install-minikube-single-node.sh"

log() {
  echo "[${SCRIPT_NAME}] $*"
}

fail() {
  echo "[${SCRIPT_NAME}] ERROR: $*" >&2
  exit 1
}

main() {
  [[ -x "${INSTALL_SCRIPT}" ]] || fail "Missing executable: ${INSTALL_SCRIPT}"
  log "Starting Minikube only. Live-code and overlay steps are managed separately."
  "${INSTALL_SCRIPT}" "$@"
  log "Minikube start workflow complete."
}

main "$@"
