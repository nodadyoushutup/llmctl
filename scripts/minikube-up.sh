#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME=$(basename "${BASH_SOURCE[0]}")
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)

PROFILE="${MINIKUBE_PROFILE:-llmctl}"
GPU_MODE="${MINIKUBE_GPU:-auto}"
APPLY_OVERLAY=1
WAIT_ROLLOUT=1
ENABLE_ARGOCD=0
ENABLE_LIVE_MOUNT=1
ROLLOUT_TIMEOUT_SECONDS="${ROLLOUT_TIMEOUT_SECONDS:-600}"

MOUNT_LOG_FILE="${MINIKUBE_MOUNT_LOG_FILE:-${REPO_ROOT}/data/minikube/live-code-mount.log}"
MOUNT_PID_FILE="${MINIKUBE_MOUNT_PID_FILE:-${REPO_ROOT}/data/minikube/live-code-mount.pid}"
MOUNT_TARGET="${MINIKUBE_LIVE_CODE_TARGET:-/workspace/llmctl}"
LIVE_MOUNT_SCRIPT=""

log() {
  echo "[${SCRIPT_NAME}] $*"
}

fail() {
  echo "[${SCRIPT_NAME}] ERROR: $*" >&2
  exit 1
}

usage() {
  cat <<EOF
Usage: ${SCRIPT_NAME} [options]

Bring Minikube + llmctl dev stack back online in one command.

Options:
  --profile <name>      Minikube profile (default: ${PROFILE})
  --gpu                 Force-enable GPU support
  --no-gpu              Force-disable GPU support
  --gpu-mode <mode>     GPU mode: auto|on|off (default: ${GPU_MODE})
  --no-live-mount       Do not start the background minikube live-code mount
  --no-apply            Do not run kubectl apply -k kubernetes/llmctl-studio/overlays/dev
  --no-wait             Do not wait for deployment rollout
  --argocd              Also run scripts/install/install-argocd-on-minikube.sh
  -h, --help            Show this help text
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --profile)
        [[ $# -ge 2 ]] || fail "--profile requires a value."
        PROFILE="$2"
        shift 2
        ;;
      --gpu)
        GPU_MODE="on"
        shift
        ;;
      --no-gpu)
        GPU_MODE="off"
        shift
        ;;
      --gpu-mode)
        [[ $# -ge 2 ]] || fail "--gpu-mode requires a value."
        GPU_MODE="$2"
        shift 2
        ;;
      --no-live-mount)
        ENABLE_LIVE_MOUNT=0
        shift
        ;;
      --no-apply)
        APPLY_OVERLAY=0
        shift
        ;;
      --no-wait)
        WAIT_ROLLOUT=0
        shift
        ;;
      --argocd)
        ENABLE_ARGOCD=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        fail "Unknown argument: $1"
        ;;
    esac
  done
}

ensure_minikube() {
  local status
  local minikube_script
  minikube_script="${REPO_ROOT}/scripts/install/install-minikube-single-node.sh"
  [[ -x "${minikube_script}" ]] || fail "Missing executable: ${minikube_script}"

  if command -v minikube >/dev/null 2>&1; then
    status="$(minikube -p "${PROFILE}" status 2>/dev/null || true)"
    if grep -q "host: Running" <<<"${status}" && grep -q "kubelet: Running" <<<"${status}" && grep -q "apiserver: Running" <<<"${status}"; then
      log "Minikube profile '${PROFILE}' is already running."
      kubectl config use-context "${PROFILE}" >/dev/null 2>&1 || true
      return
    fi
  fi

  log "Starting Minikube profile '${PROFILE}' (GPU mode: ${GPU_MODE})..."
  "${minikube_script}" --profile "${PROFILE}" --gpu-mode "${GPU_MODE}"
}

resolve_live_mount_script() {
  local candidate
  local candidates=(
    "${REPO_ROOT}/scripts/minikube/live-code.sh"
    "${REPO_ROOT}/scripts/minikube-live-code-mount.sh"
  )
  for candidate in "${candidates[@]}"; do
    if [[ -x "${candidate}" ]]; then
      LIVE_MOUNT_SCRIPT="${candidate}"
      return
    fi
  done
  fail "Could not find a live-code mount script under scripts/minikube/live-code.sh or scripts/minikube-live-code-mount.sh."
}

mount_target_is_healthy() {
  minikube -p "${PROFILE}" ssh -- "mount | grep -E '[[:space:]]${MOUNT_TARGET}[[:space:]]' >/dev/null" >/dev/null 2>&1 \
    && minikube -p "${PROFILE}" ssh -- "test -f '${MOUNT_TARGET}/app/llmctl-studio-frontend/package.json' && test -f '${MOUNT_TARGET}/kubernetes/README.md'" >/dev/null 2>&1
}

stop_mount_process() {
  local pid="$1"
  if [[ "${pid}" =~ ^[0-9]+$ ]] && kill -0 "${pid}" >/dev/null 2>&1; then
    kill "${pid}" >/dev/null 2>&1 || true
    sleep 1
    if kill -0 "${pid}" >/dev/null 2>&1; then
      kill -9 "${pid}" >/dev/null 2>&1 || true
    fi
  fi
}

reset_mount_target() {
  minikube -p "${PROFILE}" ssh -- "sudo umount '${MOUNT_TARGET}' || umount '${MOUNT_TARGET}' || true" >/dev/null 2>&1 || true
}

start_live_mount() {
  local pid
  local attempt
  local max_attempts=3

  mkdir -p "$(dirname "${MOUNT_LOG_FILE}")"

  if [[ -f "${MOUNT_PID_FILE}" ]]; then
    pid="$(cat "${MOUNT_PID_FILE}" 2>/dev/null || true)"
    if [[ "${pid}" =~ ^[0-9]+$ ]] && kill -0 "${pid}" >/dev/null 2>&1; then
      if mount_target_is_healthy; then
        log "Live-code mount already running (pid ${pid})."
        return
      fi
      log "Live-code mount process exists (pid ${pid}) but target '${MOUNT_TARGET}' is unhealthy. Restarting mount..."
      stop_mount_process "${pid}"
      reset_mount_target
    fi
  fi

  pid="$(pgrep -f "minikube -p ${PROFILE} mount .+:${MOUNT_TARGET}" | head -n1 || true)"
  if [[ "${pid}" =~ ^[0-9]+$ ]] && kill -0 "${pid}" >/dev/null 2>&1; then
    if mount_target_is_healthy; then
      echo "${pid}" > "${MOUNT_PID_FILE}"
      log "Live-code mount already running (pid ${pid})."
      return
    fi
    log "Detected stale live-code mount process (pid ${pid}). Restarting mount..."
    stop_mount_process "${pid}"
    reset_mount_target
  fi

  for attempt in $(seq 1 "${max_attempts}"); do
    log "Starting live-code mount in background (attempt ${attempt}/${max_attempts})..."
    : > "${MOUNT_LOG_FILE}"
    MINIKUBE_PROFILE="${PROFILE}" nohup "${LIVE_MOUNT_SCRIPT}" "${REPO_ROOT}" >"${MOUNT_LOG_FILE}" 2>&1 &
    pid=$!
    echo "${pid}" > "${MOUNT_PID_FILE}"

    sleep 4
    if kill -0 "${pid}" >/dev/null 2>&1 && mount_target_is_healthy; then
      log "Live-code mount running (pid ${pid})."
      log "Live-code mount log: ${MOUNT_LOG_FILE}"
      return
    fi

    stop_mount_process "${pid}"
    reset_mount_target
    log "Live-code mount attempt ${attempt} exited early. Retrying..."
    sleep 2
  done

  tail -n 60 "${MOUNT_LOG_FILE}" >&2 || true
  fail "Live-code mount failed to start."
}

apply_dev_overlay() {
  local attempt
  local max_attempts=5
  local apply_log

  apply_log="$(mktemp)"
  for attempt in $(seq 1 "${max_attempts}"); do
    log "Applying Kubernetes dev overlay (attempt ${attempt}/${max_attempts})..."
    if kubectl apply -k "${REPO_ROOT}/kubernetes/llmctl-studio/overlays/dev" >"${apply_log}" 2>&1; then
      cat "${apply_log}"
      rm -f "${apply_log}"
      return
    fi

    cat "${apply_log}" >&2
    if grep -q "validate.nginx.ingress.kubernetes.io" "${apply_log}"; then
      log "Ingress admission webhook not ready yet; waiting and retrying..."
      kubectl -n ingress-nginx rollout status deploy/ingress-nginx-controller --timeout=300s || true
      sleep 5
      continue
    fi

    rm -f "${apply_log}"
    fail "kubectl apply -k failed."
  done

  rm -f "${apply_log}"
  fail "kubectl apply -k failed after ${max_attempts} attempts."
}

maybe_warn_missing_secrets() {
  if ! kubectl -n llmctl get secret llmctl-studio-secrets >/dev/null 2>&1; then
    log "WARNING: Secret 'llmctl-studio-secrets' not found in namespace 'llmctl'."
    log "         Backend rollout may fail until the secret is created."
  fi
}

wait_for_rollout() {
  local deploy
  local deploys=(
    llmctl-redis
    llmctl-postgres
    llmctl-chromadb
    llmctl-mcp
    llmctl-mcp-github
    llmctl-mcp-atlassian
    llmctl-mcp-chroma
    llmctl-mcp-google-cloud
    llmctl-celery-worker
    llmctl-celery-beat
    llmctl-studio-backend
    llmctl-studio-frontend
  )

  log "Waiting for rollout in namespace llmctl..."
  for deploy in "${deploys[@]}"; do
    kubectl -n llmctl rollout status "deployment/${deploy}" --timeout="${ROLLOUT_TIMEOUT_SECONDS}s"
  done
}

maybe_install_argocd() {
  if [[ "${ENABLE_ARGOCD}" != "1" ]]; then
    return
  fi
  log "Installing/updating Argo CD on Minikube..."
  MINIKUBE_PROFILE="${PROFILE}" "${REPO_ROOT}/scripts/install/install-argocd-on-minikube.sh"
}

print_endpoints() {
  local ip frontend_port backend_port
  ip="$(minikube -p "${PROFILE}" ip 2>/dev/null || true)"
  frontend_port="$(kubectl -n llmctl get svc llmctl-studio-frontend -o jsonpath='{.spec.ports[?(@.name=="http")].nodePort}' 2>/dev/null || true)"
  backend_port="$(kubectl -n llmctl get svc llmctl-studio-backend -o jsonpath='{.spec.ports[?(@.name=="http")].nodePort}' 2>/dev/null || true)"

  if [[ -n "${ip}" && -n "${frontend_port}" ]]; then
    log "Studio frontend: http://${ip}:${frontend_port}/web/overview"
  fi
  if [[ -n "${ip}" && -n "${backend_port}" ]]; then
    log "Studio backend health: http://${ip}:${backend_port}/api/health"
  fi
}

main() {
  parse_args "$@"

  ensure_minikube

  if [[ "${ENABLE_LIVE_MOUNT}" == "1" ]]; then
    resolve_live_mount_script
    start_live_mount
  fi

  if [[ "${APPLY_OVERLAY}" == "1" ]]; then
    apply_dev_overlay
  fi

  maybe_warn_missing_secrets

  if [[ "${WAIT_ROLLOUT}" == "1" ]]; then
    wait_for_rollout
  fi

  maybe_install_argocd
  print_endpoints

  log "Minikube restore workflow complete."
}

main "$@"
