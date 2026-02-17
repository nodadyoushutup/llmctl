#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME=$(basename "${BASH_SOURCE[0]}")
CUDA_TEST_IMAGE="${CUDA_TEST_IMAGE:-nvidia/cuda:12.4.1-base-ubuntu22.04}"
SKIP_GPU_TEST="${SKIP_GPU_TEST:-0}"

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

if [[ ! -f /etc/os-release ]]; then
  fail "Cannot detect OS. /etc/os-release not found."
fi

source /etc/os-release

if ! have_cmd apt-get; then
  fail "This script currently supports Debian/Ubuntu hosts with apt-get."
fi

require_cmd curl
require_cmd gpg
require_cmd docker

if ! have_cmd nvidia-smi; then
  fail "nvidia-smi not found. Install NVIDIA driver on the host first."
fi

log "Host GPU check:"
nvidia-smi

log "Installing NVIDIA Container Toolkit repository prerequisites..."
as_root apt-get update
as_root apt-get install -y --no-install-recommends ca-certificates curl gnupg

keyring_path="/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg"
repo_list_path="/etc/apt/sources.list.d/nvidia-container-toolkit.list"
repo_url="https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list"

log "Installing NVIDIA Container Toolkit apt keyring..."
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | as_root gpg --dearmor -o "${keyring_path}"
as_root chmod a+r "${keyring_path}"

log "Configuring NVIDIA Container Toolkit apt repository..."
repo_content="$(curl -fsSL "${repo_url}" | sed "s#deb https://#deb [signed-by=${keyring_path}] https://#g")"
printf "%s\n" "${repo_content}" | as_root tee "${repo_list_path}" >/dev/null

log "Installing NVIDIA Container Toolkit packages..."
as_root apt-get update
as_root apt-get install -y --no-install-recommends nvidia-container-toolkit

require_cmd nvidia-ctk

log "Configuring Docker runtime integration for NVIDIA..."
as_root nvidia-ctk runtime configure --runtime=docker

log "Restarting Docker daemon..."
if have_cmd systemctl; then
  as_root systemctl restart docker
elif have_cmd service; then
  as_root service docker restart
else
  fail "Cannot restart Docker automatically (no systemctl/service). Restart Docker manually."
fi

sleep 2

log "Docker runtime info:"
docker info | grep -Ei "Runtimes|Default Runtime|nvidia" || true

if [[ "${SKIP_GPU_TEST}" == "1" ]]; then
  log "Skipping container GPU smoke test (SKIP_GPU_TEST=1)."
  log "Setup complete."
  exit 0
fi

log "Running GPU smoke test container (${CUDA_TEST_IMAGE})..."
docker run --rm --gpus all "${CUDA_TEST_IMAGE}" nvidia-smi

log "GPU passthrough is functional."
log "You can now build/push images and deploy via Kubernetes manifests/overlays."
