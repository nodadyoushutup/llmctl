#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.config/.gemini/.env"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

# Match Codex-style full access unless the user overrides it.
export GEMINI_SANDBOX="${GEMINI_SANDBOX:-false}"

exec gemini --approval-mode=yolo "$@"
