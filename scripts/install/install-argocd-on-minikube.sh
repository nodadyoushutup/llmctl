#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME=$(basename "${BASH_SOURCE[0]}")
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)

MINIKUBE_PROFILE="${MINIKUBE_PROFILE:-llmctl}"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
ARGOCD_ADMIN_USERNAME="admin"
ARGOCD_ADMIN_PASSWORD="${ARGOCD_ADMIN_PASSWORD:-}"
ARGOCD_CREDENTIALS_FILE="${ARGOCD_CREDENTIALS_FILE:-${REPO_ROOT}/data/argocd/argocd-admin-credentials.env}"
ARGOCD_SERVER_SERVICE_TYPE="${ARGOCD_SERVER_SERVICE_TYPE:-NodePort}"
BIN_DIR="${BIN_DIR:-/usr/local/bin}"
FORCE_INSTALL="${FORCE_INSTALL:-0}"

log() {
  echo "[$SCRIPT_NAME] $*"
}

fail() {
  echo "[$SCRIPT_NAME] ERROR: $*" >&2
  exit 1
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

as_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  elif have_cmd sudo; then
    sudo "$@"
  else
    fail "This step needs root. Re-run as root or install sudo."
  fi
}

require_cmd() {
  have_cmd "$1" || fail "Missing required command: $1"
}

normalize_os() {
  case "$(uname -s)" in
    Linux) echo "linux" ;;
    Darwin) echo "darwin" ;;
    *) fail "Unsupported OS: $(uname -s)" ;;
  esac
}

normalize_arch() {
  case "$(uname -m)" in
    x86_64|amd64) echo "amd64" ;;
    arm64|aarch64) echo "arm64" ;;
    *) fail "Unsupported CPU architecture: $(uname -m)" ;;
  esac
}

install_argocd_cli() {
  if have_cmd argocd && [[ "$FORCE_INSTALL" != "1" ]]; then
    log "argocd CLI already installed: $(argocd version --client --short 2>/dev/null || true)"
    return
  fi

  local os
  local arch
  local tmp_bin

  os="$(normalize_os)"
  arch="$(normalize_arch)"
  tmp_bin="$(mktemp)"

  log "Installing argocd CLI for ${os}/${arch}..."
  curl -fsSL "https://github.com/argoproj/argo-cd/releases/latest/download/argocd-${os}-${arch}" -o "$tmp_bin"
  chmod +x "$tmp_bin"
  as_root mkdir -p "$BIN_DIR"
  as_root install -m 0755 "$tmp_bin" "$BIN_DIR/argocd"
  rm -f "$tmp_bin"
}

decode_base64() {
  if printf 'dGVzdA==' | base64 --decode >/dev/null 2>&1; then
    base64 --decode
  elif printf 'dGVzdA==' | base64 -d >/dev/null 2>&1; then
    base64 -d
  else
    base64 -D
  fi
}

ensure_minikube_running() {
  require_cmd minikube
  if ! minikube -p "$MINIKUBE_PROFILE" status >/dev/null 2>&1; then
    fail "Minikube profile '${MINIKUBE_PROFILE}' is not running. Run scripts/install/install-minikube-single-node.sh first."
  fi
}

install_argocd_core() {
  local manifest_url
  manifest_url="https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml"

  log "Installing Argo CD into namespace '${ARGOCD_NAMESPACE}'..."
  kubectl create namespace "$ARGOCD_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
  # Use server-side apply to avoid oversized
  # kubectl.kubernetes.io/last-applied-configuration annotations on large CRDs.
  kubectl apply --server-side --force-conflicts -f "$manifest_url"

  kubectl -n "$ARGOCD_NAMESPACE" rollout status deployment/argocd-server --timeout=600s
  kubectl -n "$ARGOCD_NAMESPACE" rollout status deployment/argocd-repo-server --timeout=600s
  kubectl -n "$ARGOCD_NAMESPACE" rollout status deployment/argocd-applicationset-controller --timeout=600s
  kubectl -n "$ARGOCD_NAMESPACE" rollout status statefulset/argocd-application-controller --timeout=600s
}

set_admin_password_if_requested() {
  if [[ -z "$ARGOCD_ADMIN_PASSWORD" ]]; then
    return
  fi

  local password_hash
  local password_mtime
  local patch_file

  password_hash="$(argocd account bcrypt --password "$ARGOCD_ADMIN_PASSWORD" | tail -n1 | tr -d '[:space:]')"
  password_mtime="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  patch_file="$(mktemp)"

  cat > "$patch_file" <<PATCH
stringData:
  admin.password: '${password_hash}'
  admin.passwordMtime: '${password_mtime}'
PATCH

  kubectl -n "$ARGOCD_NAMESPACE" patch secret argocd-secret --type merge --patch-file "$patch_file"
  rm -f "$patch_file"

  kubectl -n "$ARGOCD_NAMESPACE" rollout restart deployment/argocd-server
  kubectl -n "$ARGOCD_NAMESPACE" rollout status deployment/argocd-server --timeout=600s

  log "Applied custom Argo CD admin password from ARGOCD_ADMIN_PASSWORD."
}

configure_server_access() {
  if [[ "$ARGOCD_SERVER_SERVICE_TYPE" == "NodePort" ]]; then
    kubectl -n "$ARGOCD_NAMESPACE" patch svc argocd-server --type merge -p '{"spec": {"type": "NodePort"}}' >/dev/null
  fi
}

resolve_server_url() {
  local urls
  local selected

  urls="$(minikube -p "$MINIKUBE_PROFILE" service argocd-server -n "$ARGOCD_NAMESPACE" --url 2>/dev/null || true)"
  selected="$(printf '%s\n' "$urls" | grep '^https://' | head -n1 || true)"
  if [[ -z "$selected" ]]; then
    selected="$(printf '%s\n' "$urls" | grep '^http://' | head -n1 || true)"
  fi
  printf '%s' "$selected"
}

read_admin_password() {
  if [[ -n "$ARGOCD_ADMIN_PASSWORD" ]]; then
    printf '%s' "$ARGOCD_ADMIN_PASSWORD"
    return
  fi

  local b64
  b64="$(kubectl -n "$ARGOCD_NAMESPACE" get secret argocd-initial-admin-secret -o jsonpath='{.data.password}')"
  if [[ -z "$b64" ]]; then
    fail "Could not read argocd-initial-admin-secret password."
  fi

  printf '%s' "$b64" | decode_base64
}

write_credentials_file() {
  local server_url="$1"
  local admin_password="$2"

  umask 077
  mkdir -p "$(dirname "$ARGOCD_CREDENTIALS_FILE")"
  cat > "$ARGOCD_CREDENTIALS_FILE" <<CREDS
ARGOCD_PROFILE=${MINIKUBE_PROFILE}
ARGOCD_NAMESPACE=${ARGOCD_NAMESPACE}
ARGOCD_SERVER_URL=${server_url}
ARGOCD_USERNAME=${ARGOCD_ADMIN_USERNAME}
ARGOCD_PASSWORD=${admin_password}
CREDS
  chmod 600 "$ARGOCD_CREDENTIALS_FILE"
}

main() {
  require_cmd curl
  require_cmd kubectl

  ensure_minikube_running
  install_argocd_cli
  install_argocd_core
  set_admin_password_if_requested
  configure_server_access

  local server_url
  local admin_password
  local server_host

  server_url="$(resolve_server_url)"
  admin_password="$(read_admin_password)"

  write_credentials_file "$server_url" "$admin_password"

  if [[ -n "$server_url" ]]; then
    server_host="${server_url#https://}"
    server_host="${server_host#http://}"
  else
    server_host="argocd-server"
  fi

  log "Argo CD install complete."
  if [[ -n "$server_url" ]]; then
    log "Server URL: $server_url"
  else
    log "Server URL not auto-detected. Run: minikube -p ${MINIKUBE_PROFILE} service argocd-server -n ${ARGOCD_NAMESPACE} --url"
  fi
  log "Credentials written to: $ARGOCD_CREDENTIALS_FILE"
  log "Username: ${ARGOCD_ADMIN_USERNAME}"
  log "Login example: argocd login ${server_host} --username ${ARGOCD_ADMIN_USERNAME} --password '<password>' --insecure"
}

main "$@"
