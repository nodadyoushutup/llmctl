#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
IMAGE_NAME="${IMAGE_NAME:-llmctl-executor:latest}"
INSTALL_VLLM="${INSTALL_VLLM:-true}"
INSTALL_CLAUDE="${INSTALL_CLAUDE:-true}"
EXECUTOR_BASE_IMAGE="${EXECUTOR_BASE_IMAGE:-nvidia/cuda:12.8.0-cudnn-runtime-ubuntu24.04}"
VENV_SYSTEM_SITE_PACKAGES="${VENV_SYSTEM_SITE_PACKAGES:-false}"

cd "${REPO_ROOT}"

docker build \
  --build-arg EXECUTOR_BASE_IMAGE="${EXECUTOR_BASE_IMAGE}" \
  --build-arg INSTALL_VLLM="${INSTALL_VLLM}" \
  --build-arg INSTALL_CLAUDE="${INSTALL_CLAUDE}" \
  --build-arg VENV_SYSTEM_SITE_PACKAGES="${VENV_SYSTEM_SITE_PACKAGES}" \
  -f app/llmctl-executor/Dockerfile \
  -t "${IMAGE_NAME}" \
  .
