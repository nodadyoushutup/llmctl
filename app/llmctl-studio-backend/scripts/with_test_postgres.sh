#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME=$(basename "${BASH_SOURCE[0]}")
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../../.." && pwd)

POSTGRES_IMAGE="${LLMCTL_TEST_POSTGRES_IMAGE:-postgres:16-alpine}"
POSTGRES_CONTAINER="${LLMCTL_TEST_POSTGRES_CONTAINER:-llmctl-studio-test-postgres}"
POSTGRES_PORT="${LLMCTL_TEST_POSTGRES_PORT:-15432}"
POSTGRES_DB="${LLMCTL_TEST_POSTGRES_DB:-llmctl_studio}"
POSTGRES_USER="${LLMCTL_TEST_POSTGRES_USER:-llmctl}"
POSTGRES_PASSWORD="${LLMCTL_TEST_POSTGRES_PASSWORD:-llmctl}"
READY_TIMEOUT_SECONDS="${LLMCTL_TEST_POSTGRES_READY_TIMEOUT_SECONDS:-60}"
KEEP_CONTAINER="${LLMCTL_TEST_POSTGRES_KEEP_CONTAINER:-0}"
PYTHON_BIN="${PYTHON_BIN:-${REPO_ROOT}/.venv/bin/python3}"
SKIP_DEP_CHECK="${LLMCTL_TEST_SKIP_DEP_CHECK:-0}"
STRICT_PORT="${LLMCTL_TEST_POSTGRES_STRICT_PORT:-0}"

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

require_cmd() {
  have_cmd "$1" || fail "Missing required command: $1"
}

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME [options] [-- command...]

Runs Studio backend tests with a disposable local PostgreSQL container and exports:
  LLMCTL_STUDIO_DATABASE_URI=postgresql+psycopg://...

If no command is provided after --, defaults to:
  <PYTHON_BIN> -m unittest discover -s app/llmctl-studio-backend/tests

Options:
  --keep-container   Leave the PostgreSQL container running after command exits.
  --skip-dep-check   Skip Python dependency/import preflight.
  --python <path>    Override Python binary (default: .venv/bin/python3).
  -h, --help         Show this help text.

Environment overrides:
  LLMCTL_TEST_POSTGRES_IMAGE
  LLMCTL_TEST_POSTGRES_CONTAINER
  LLMCTL_TEST_POSTGRES_PORT
  LLMCTL_TEST_POSTGRES_DB
  LLMCTL_TEST_POSTGRES_USER
  LLMCTL_TEST_POSTGRES_PASSWORD
  LLMCTL_TEST_POSTGRES_READY_TIMEOUT_SECONDS
  LLMCTL_TEST_POSTGRES_KEEP_CONTAINER
  LLMCTL_TEST_SKIP_DEP_CHECK
  LLMCTL_TEST_POSTGRES_STRICT_PORT
  PYTHON_BIN
EOF
}

cleanup_container() {
  if docker ps -a --format '{{.Names}}' | grep -Fxq "$POSTGRES_CONTAINER"; then
    docker rm -f "$POSTGRES_CONTAINER" >/dev/null 2>&1 || true
  fi
}

port_is_available() {
  python3 - "$1" <<'PY'
import socket
import sys

port = int(sys.argv[1])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    sock.bind(("127.0.0.1", port))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
raise SystemExit(0)
PY
}

resolve_postgres_port() {
  if port_is_available "$POSTGRES_PORT"; then
    return
  fi
  if [[ "$STRICT_PORT" == "1" ]]; then
    fail "Port ${POSTGRES_PORT} is already in use. Set LLMCTL_TEST_POSTGRES_PORT to a free port."
  fi
  local replacement_port
  replacement_port=$(
    python3 - "$POSTGRES_PORT" <<'PY'
import socket
import sys

base = int(sys.argv[1])
for candidate in range(base + 1, base + 101):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", candidate))
    except OSError:
        sock.close()
        continue
    sock.close()
    print(candidate)
    raise SystemExit(0)

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.bind(("127.0.0.1", 0))
print(sock.getsockname()[1])
sock.close()
PY
  )
  log "Port ${POSTGRES_PORT} is busy; using ${replacement_port}."
  POSTGRES_PORT="${replacement_port}"
}

wait_for_postgres() {
  local deadline
  deadline=$((SECONDS + READY_TIMEOUT_SECONDS))
  while true; do
    if docker exec "$POSTGRES_CONTAINER" pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
      return
    fi
    if (( SECONDS >= deadline )); then
      docker logs --tail 60 "$POSTGRES_CONTAINER" >&2 || true
      fail "Timed out waiting for PostgreSQL readiness after ${READY_TIMEOUT_SECONDS}s."
    fi
    sleep 1
  done
}

start_postgres() {
  if docker ps --format '{{.Names}}' | grep -Fxq "$POSTGRES_CONTAINER"; then
    local mapped_port
    mapped_port="$(docker port "$POSTGRES_CONTAINER" 5432/tcp | head -n1 | awk -F: '{print $NF}')"
    if [[ -n "$mapped_port" ]]; then
      POSTGRES_PORT="$mapped_port"
    fi
    log "Reusing running container '${POSTGRES_CONTAINER}' on 127.0.0.1:${POSTGRES_PORT}."
    return
  fi
  if docker ps -a --format '{{.Names}}' | grep -Fxq "$POSTGRES_CONTAINER"; then
    log "Removing stale container '${POSTGRES_CONTAINER}'."
    docker rm -f "$POSTGRES_CONTAINER" >/dev/null
  fi

  resolve_postgres_port
  log "Starting PostgreSQL container '${POSTGRES_CONTAINER}' on 127.0.0.1:${POSTGRES_PORT}."
  docker run -d \
    --name "$POSTGRES_CONTAINER" \
    -e "POSTGRES_DB=${POSTGRES_DB}" \
    -e "POSTGRES_USER=${POSTGRES_USER}" \
    -e "POSTGRES_PASSWORD=${POSTGRES_PASSWORD}" \
    -p "${POSTGRES_PORT}:5432" \
    "$POSTGRES_IMAGE" >/dev/null
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --keep-container)
        KEEP_CONTAINER=1
        shift
        ;;
      --skip-dep-check)
        SKIP_DEP_CHECK=1
        shift
        ;;
      --python)
        [[ $# -ge 2 ]] || fail "--python requires a value."
        PYTHON_BIN="$2"
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      --)
        shift
        TEST_CMD=("$@")
        return
        ;;
      *)
        fail "Unknown argument: $1 (use -- to pass command arguments)"
        ;;
    esac
  done
}

TEST_CMD=()
parse_args "$@"

require_cmd docker
require_cmd python3
[[ -x "$PYTHON_BIN" ]] || fail "Python binary not executable: $PYTHON_BIN"

if [[ "$KEEP_CONTAINER" != "1" ]]; then
  trap cleanup_container EXIT
fi

start_postgres
wait_for_postgres

export LLMCTL_STUDIO_DATABASE_URI="postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_PORT}/${POSTGRES_DB}"

if [[ "$SKIP_DEP_CHECK" != "1" ]]; then
  if ! "$PYTHON_BIN" -c "import flask, sqlalchemy, psycopg" >/dev/null 2>&1; then
    log "Installing backend Python dependencies into $(dirname "$PYTHON_BIN")"
    "$PYTHON_BIN" -m pip install -r "${REPO_ROOT}/app/llmctl-studio-backend/requirements.txt"
  fi
fi

if [[ ${#TEST_CMD[@]} -eq 0 ]]; then
  TEST_CMD=("$PYTHON_BIN" -m unittest discover -s app/llmctl-studio-backend/tests)
fi

log "LLMCTL_STUDIO_DATABASE_URI configured for local test run."
log "Running command: ${TEST_CMD[*]}"
"${TEST_CMD[@]}"
