#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT="${SCRIPT_DIR}"
MODELS_DIR="${REPO_ROOT}/models"

MODEL_ID="${1:-${QWEN_MODEL_ID:-Qwen/Qwen2.5-0.5B-Instruct}}"
MODEL_DIR_NAME="${2:-${QWEN_MODEL_DIR_NAME:-qwen2.5-0.5b-instruct}}"
MODEL_TARGET_DIR="${MODELS_DIR}/${MODEL_DIR_NAME}"
MODEL_LABEL="${QWEN_MODEL_LABEL:-${MODEL_ID##*/}}"
MODEL_CONTAINER_PATH="/app/models/custom/${MODEL_DIR_NAME}"

mkdir -p "${MODELS_DIR}" "${MODEL_TARGET_DIR}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[download-qwen] python3 is required but not found." >&2
  exit 1
fi

PYTHON_BIN="python3"
if ! python3 -c "import huggingface_hub" >/dev/null 2>&1; then
  VENV_DIR="${MODELS_DIR}/.download-venv"
  if [ ! -x "${VENV_DIR}/bin/python" ]; then
    echo "[download-qwen] Creating local virtualenv at ${VENV_DIR}" >&2
    python3 -m venv "${VENV_DIR}"
  fi
  echo "[download-qwen] Installing huggingface_hub in local virtualenv..." >&2
  "${VENV_DIR}/bin/python" -m pip install --upgrade pip huggingface_hub >/dev/null
  PYTHON_BIN="${VENV_DIR}/bin/python"
fi

echo "[download-qwen] Downloading ${MODEL_ID} into ${MODEL_TARGET_DIR}" >&2
MODEL_ID="${MODEL_ID}" MODEL_TARGET_DIR="${MODEL_TARGET_DIR}" "${PYTHON_BIN}" - <<'PY'
import os
from huggingface_hub import snapshot_download

repo_id = os.environ["MODEL_ID"]
local_dir = os.environ["MODEL_TARGET_DIR"]
token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")

snapshot_download(repo_id=repo_id, local_dir=local_dir, token=token)
PY

MODEL_TARGET_DIR="${MODEL_TARGET_DIR}" MODEL_LABEL="${MODEL_LABEL}" MODEL_ID="${MODEL_ID}" MODEL_CONTAINER_PATH="${MODEL_CONTAINER_PATH}" "${PYTHON_BIN}" - <<'PY'
import json
import os
from pathlib import Path

model_target_dir = Path(os.environ["MODEL_TARGET_DIR"])
manifest = {
    "name": os.environ["MODEL_LABEL"],
    "model": os.environ["MODEL_CONTAINER_PATH"],
    "description": f"Downloaded from {os.environ['MODEL_ID']} by download-qwen.sh",
}
(model_target_dir / "model.json").write_text(
    json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
)
PY

echo "[download-qwen] Done." >&2
echo "[download-qwen] Local directory: ${MODEL_TARGET_DIR}" >&2
echo "[download-qwen] vLLM model value: ${MODEL_CONTAINER_PATH}" >&2
