#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME=$(basename "${BASH_SOURCE[0]}")

MINIKUBE_PROFILE="${MINIKUBE_PROFILE:-llmctl}"
MINIKUBE_DRIVER="${MINIKUBE_DRIVER:-docker}"
MINIKUBE_K8S_VERSION="${MINIKUBE_K8S_VERSION:-}"
MINIKUBE_CPUS="${MINIKUBE_CPUS:-4}"
MINIKUBE_MEMORY_MB="${MINIKUBE_MEMORY_MB:-8192}"
MINIKUBE_DISK_SIZE="${MINIKUBE_DISK_SIZE:-30g}"
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

sha256_file() {
  local path="$1"
  if have_cmd sha256sum; then
    sha256sum "$path" | awk '{print $1}'
  elif have_cmd shasum; then
    shasum -a 256 "$path" | awk '{print $1}'
  else
    fail "Need sha256sum or shasum for checksum validation."
  fi
}

install_binary_from_url() {
  local url="$1"
  local checksum_url="$2"
  local out_name="$3"

  local tmp_bin
  local tmp_sha
  local expected
  local actual

  tmp_bin="$(mktemp)"
  tmp_sha="$(mktemp)"

  curl -fsSL "$url" -o "$tmp_bin"
  curl -fsSL "$checksum_url" -o "$tmp_sha"

  expected="$(tr -d '[:space:]' < "$tmp_sha")"
  actual="$(sha256_file "$tmp_bin")"
  if [[ "$expected" != "$actual" ]]; then
    rm -f "$tmp_bin" "$tmp_sha"
    fail "Checksum mismatch for $out_name."
  fi

  chmod +x "$tmp_bin"
  as_root mkdir -p "$BIN_DIR"
  as_root install -m 0755 "$tmp_bin" "$BIN_DIR/$out_name"

  rm -f "$tmp_bin" "$tmp_sha"
}

ensure_kubectl() {
  if have_cmd kubectl && [[ "$FORCE_INSTALL" != "1" ]]; then
    log "kubectl already installed: $(kubectl version --client --output=yaml 2>/dev/null | awk '/gitVersion:/ {print $2; exit}' || true)"
    return
  fi

  local os
  local arch
  local version

  os="$(normalize_os)"
  arch="$(normalize_arch)"
  version="$(curl -fsSL https://dl.k8s.io/release/stable.txt)"

  log "Installing kubectl ${version} for ${os}/${arch}..."
  install_binary_from_url \
    "https://dl.k8s.io/release/${version}/bin/${os}/${arch}/kubectl" \
    "https://dl.k8s.io/release/${version}/bin/${os}/${arch}/kubectl.sha256" \
    "kubectl"
}

ensure_minikube() {
  if have_cmd minikube && [[ "$FORCE_INSTALL" != "1" ]]; then
    log "minikube already installed: $(minikube version --short 2>/dev/null || minikube version 2>/dev/null | head -n1 || true)"
    return
  fi

  local os
  local arch

  os="$(normalize_os)"
  arch="$(normalize_arch)"

  log "Installing minikube for ${os}/${arch}..."
  install_binary_from_url \
    "https://storage.googleapis.com/minikube/releases/latest/minikube-${os}-${arch}" \
    "https://storage.googleapis.com/minikube/releases/latest/minikube-${os}-${arch}.sha256" \
    "minikube"
}

start_single_node_cluster() {
  local args=()

  args+=(start)
  args+=("--profile=${MINIKUBE_PROFILE}")
  args+=("--driver=${MINIKUBE_DRIVER}")
  args+=("--nodes=1")
  args+=("--cpus=${MINIKUBE_CPUS}")
  args+=("--memory=${MINIKUBE_MEMORY_MB}")
  args+=("--disk-size=${MINIKUBE_DISK_SIZE}")

  if [[ -n "$MINIKUBE_K8S_VERSION" ]]; then
    args+=("--kubernetes-version=${MINIKUBE_K8S_VERSION}")
  fi

  log "Starting single-node cluster profile '${MINIKUBE_PROFILE}'..."
  minikube "${args[@]}"

  kubectl config use-context "$MINIKUBE_PROFILE" >/dev/null 2>&1 || true

  log "Cluster is up. Node status:"
  kubectl get nodes -o wide
}

main() {
  require_cmd curl

  if [[ "$MINIKUBE_DRIVER" == "docker" ]]; then
    require_cmd docker
    if ! docker info >/dev/null 2>&1; then
      fail "Docker is installed but not reachable. Start Docker first or set MINIKUBE_DRIVER."
    fi
  fi

  ensure_kubectl
  ensure_minikube
  start_single_node_cluster

  log "Done. Useful commands:"
  log "  minikube -p ${MINIKUBE_PROFILE} status"
  log "  kubectl get nodes"
  log "  kubectl get pods -A"
}

main "$@"
