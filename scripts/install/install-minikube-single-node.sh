#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME=$(basename "${BASH_SOURCE[0]}")

MINIKUBE_PROFILE="${MINIKUBE_PROFILE:-llmctl}"
MINIKUBE_DRIVER="${MINIKUBE_DRIVER:-docker}"
MINIKUBE_K8S_VERSION="${MINIKUBE_K8S_VERSION:-}"
MINIKUBE_CPUS="${MINIKUBE_CPUS:-4}"
MINIKUBE_MEMORY_MB="${MINIKUBE_MEMORY_MB:-8192}"
MINIKUBE_DISK_SIZE="${MINIKUBE_DISK_SIZE:-30g}"
MINIKUBE_GPU="${MINIKUBE_GPU:-auto}"
BIN_DIR="${BIN_DIR:-/usr/local/bin}"
FORCE_INSTALL="${FORCE_INSTALL:-0}"
MINIKUBE_GPU_EFFECTIVE="off"

log() {
  echo "[$SCRIPT_NAME] $*"
}

fail() {
  echo "[$SCRIPT_NAME] ERROR: $*" >&2
  exit 1
}

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME [options]

Installs kubectl + minikube, then starts a single-node minikube profile.

Options:
  --profile <name>      Minikube profile (default: ${MINIKUBE_PROFILE})
  --driver <driver>     Minikube driver (default: ${MINIKUBE_DRIVER})
  --gpu                 Force-enable GPU support (--gpus=all)
  --no-gpu              Force-disable GPU support
  --gpu-mode <mode>     GPU mode: auto|on|off (default: ${MINIKUBE_GPU})
  -h, --help            Show this help text
EOF
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

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --profile)
        [[ $# -ge 2 ]] || fail "--profile requires a value."
        MINIKUBE_PROFILE="$2"
        shift 2
        ;;
      --driver)
        [[ $# -ge 2 ]] || fail "--driver requires a value."
        MINIKUBE_DRIVER="$2"
        shift 2
        ;;
      --gpu)
        MINIKUBE_GPU="on"
        shift
        ;;
      --no-gpu)
        MINIKUBE_GPU="off"
        shift
        ;;
      --gpu-mode)
        [[ $# -ge 2 ]] || fail "--gpu-mode requires a value."
        MINIKUBE_GPU="$2"
        shift 2
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

normalize_gpu_mode() {
  local normalized
  normalized="$(echo "${1:-}" | tr '[:upper:]' '[:lower:]')"
  case "$normalized" in
    auto|on|off)
      echo "$normalized"
      ;;
    *)
      return 1
      ;;
  esac
}

detect_nvidia_gpu() {
  if ! have_cmd nvidia-smi; then
    return 1
  fi
  local gpu_line
  gpu_line="$(nvidia-smi -L 2>/dev/null | head -n1 || true)"
  [[ -n "$gpu_line" ]]
}

resolve_gpu_mode() {
  local requested
  if ! requested="$(normalize_gpu_mode "$MINIKUBE_GPU")"; then
    fail "Invalid MINIKUBE_GPU value '${MINIKUBE_GPU}'. Use auto, on, or off."
  fi

  case "$requested" in
    auto)
      if detect_nvidia_gpu; then
        MINIKUBE_GPU_EFFECTIVE="on"
        log "Detected NVIDIA GPU on host; GPU mode enabled."
      else
        MINIKUBE_GPU_EFFECTIVE="off"
        log "No NVIDIA GPU detected on host; GPU mode disabled."
      fi
      ;;
    on)
      MINIKUBE_GPU_EFFECTIVE="on"
      ;;
    off)
      MINIKUBE_GPU_EFFECTIVE="off"
      ;;
  esac

  if [[ "$MINIKUBE_GPU_EFFECTIVE" == "on" && "$MINIKUBE_DRIVER" != "docker" ]]; then
    if [[ "$requested" == "auto" ]]; then
      log "GPU auto-detected, but MINIKUBE_DRIVER='${MINIKUBE_DRIVER}' is not docker; disabling GPU mode."
      MINIKUBE_GPU_EFFECTIVE="off"
      return
    fi
    fail "GPU mode requires MINIKUBE_DRIVER=docker in this script."
  fi
}

enable_gpu_addon() {
  log "Enabling minikube addon 'nvidia-device-plugin'..."
  minikube -p "${MINIKUBE_PROFILE}" addons enable nvidia-device-plugin
  local allocatable
  allocatable="$(kubectl get nodes -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}' 2>/dev/null || true)"
  if [[ "$allocatable" =~ ^[0-9]+$ ]] && [[ "$allocatable" -gt 0 ]]; then
    log "GPU capacity detected on node: nvidia.com/gpu=${allocatable}"
  else
    log "GPU addon enabled, but node allocatable nvidia.com/gpu is not visible yet."
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

  if [[ "$MINIKUBE_GPU_EFFECTIVE" == "on" ]]; then
    args+=("--gpus=all")
    args+=("--container-runtime=docker")
  fi

  if [[ -n "$MINIKUBE_K8S_VERSION" ]]; then
    args+=("--kubernetes-version=${MINIKUBE_K8S_VERSION}")
  fi

  log "Starting single-node cluster profile '${MINIKUBE_PROFILE}'..."
  minikube "${args[@]}"

  kubectl config use-context "$MINIKUBE_PROFILE" >/dev/null 2>&1 || true

  if [[ "$MINIKUBE_GPU_EFFECTIVE" == "on" ]]; then
    enable_gpu_addon
  fi

  log "Cluster is up. Node status:"
  kubectl get nodes -o wide
}

main() {
  parse_args "$@"
  require_cmd curl
  resolve_gpu_mode

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
  if [[ "$MINIKUBE_GPU_EFFECTIVE" == "on" ]]; then
    log "  kubectl get nodes -o jsonpath='{.items[0].status.allocatable.nvidia\\.com/gpu}{\"\\n\"}'"
  fi
}

main "$@"
