#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
PORT_FORWARD_PID=""
PORT_FORWARD_LOG=""

usage() {
  cat <<'EOF'
Usage: scripts/build-harbor.sh [options]

Build and push llmctl images to Harbor.

Defaults:
  - Builds and pushes all images: llmctl-studio, llmctl-studio-frontend, llmctl-mcp, llmctl-executor
  - Pushes tag: latest
  - Project: llmctl
  - Harbor login user: admin
  - Harbor login password: Harbor12345
  - Harbor registry: auto-discovered from kubectl/minikube (NodePort service)

Options:
  --registry <host:port>   Harbor registry endpoint (example: 192.168.49.2:30082)
  --project <name>         Harbor project (default: llmctl)
  --tag <tag>              Image tag to push (default: latest)
  --username <name>        Harbor username (default: admin)
  --password <value>       Harbor password (default: Harbor12345)
  --no-login               Skip docker login before push

  --studio                 Build/push llmctl-studio only
  --frontend               Build/push llmctl-studio-frontend only
  --mcp                    Build/push llmctl-mcp only
  --executor               Build/push llmctl-executor only
  --all                    Build/push all images

  -h, --help               Show this help message

Environment:
  HARBOR_REGISTRY, HARBOR_PROJECT, HARBOR_TAG, HARBOR_USERNAME, HARBOR_PASSWORD, HARBOR_API_SCHEME
  MINIKUBE_PROFILE (used by auto-discovery; default: llmctl)
EOF
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

discover_registry() {
  local node_port=""
  local node_ip=""
  local profile="${MINIKUBE_PROFILE:-llmctl}"

  if have_cmd kubectl; then
    node_port="$(kubectl -n llmctl-harbor get svc harbor -o jsonpath='{.spec.ports[?(@.name=="http")].nodePort}' 2>/dev/null || true)"
    if [ -n "${node_port}" ]; then
      if have_cmd minikube; then
        node_ip="$(minikube -p "${profile}" ip 2>/dev/null || true)"
      fi

      if [ -z "${node_ip}" ]; then
        node_ip="$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}' 2>/dev/null || true)"
      fi

      if [ -n "${node_ip}" ]; then
        printf '%s:%s\n' "${node_ip}" "${node_port}"
        return 0
      fi
    fi
  fi

  return 1
}

require_cmd() {
  if ! have_cmd "$1"; then
    echo "Error: required command not found: $1" >&2
    exit 1
  fi
}

cleanup_port_forward() {
  if [ -n "${PORT_FORWARD_PID}" ]; then
    kill "${PORT_FORWARD_PID}" >/dev/null 2>&1 || true
    wait "${PORT_FORWARD_PID}" 2>/dev/null || true
    PORT_FORWARD_PID=""
  fi

  if [ -n "${PORT_FORWARD_LOG}" ] && [ -f "${PORT_FORWARD_LOG}" ]; then
    rm -f "${PORT_FORWARD_LOG}"
    PORT_FORWARD_LOG=""
  fi
}

HARBOR_REGISTRY="${HARBOR_REGISTRY:-}"
HARBOR_PROJECT="${HARBOR_PROJECT:-llmctl}"
HARBOR_TAG="${HARBOR_TAG:-latest}"
HARBOR_USERNAME="${HARBOR_USERNAME:-admin}"
HARBOR_PASSWORD="${HARBOR_PASSWORD:-Harbor12345}"
HARBOR_API_SCHEME="${HARBOR_API_SCHEME:-http}"
DO_LOGIN=true

SELECTED_STUDIO=false
SELECTED_FRONTEND=false
SELECTED_MCP=false
SELECTED_EXECUTOR=false
SELECTION_MADE=false

while [ $# -gt 0 ]; do
  case "$1" in
    --registry)
      if [ $# -lt 2 ]; then
        echo "Error: --registry requires a value." >&2
        usage
        exit 2
      fi
      HARBOR_REGISTRY="$2"
      shift 2
      ;;
    --project)
      if [ $# -lt 2 ]; then
        echo "Error: --project requires a value." >&2
        usage
        exit 2
      fi
      HARBOR_PROJECT="$2"
      shift 2
      ;;
    --tag)
      if [ $# -lt 2 ]; then
        echo "Error: --tag requires a value." >&2
        usage
        exit 2
      fi
      HARBOR_TAG="$2"
      shift 2
      ;;
    --username)
      if [ $# -lt 2 ]; then
        echo "Error: --username requires a value." >&2
        usage
        exit 2
      fi
      HARBOR_USERNAME="$2"
      shift 2
      ;;
    --password)
      if [ $# -lt 2 ]; then
        echo "Error: --password requires a value." >&2
        usage
        exit 2
      fi
      HARBOR_PASSWORD="$2"
      shift 2
      ;;
    --no-login)
      DO_LOGIN=false
      shift
      ;;
    --studio)
      SELECTED_STUDIO=true
      SELECTION_MADE=true
      shift
      ;;
    --frontend)
      SELECTED_FRONTEND=true
      SELECTION_MADE=true
      shift
      ;;
    --mcp)
      SELECTED_MCP=true
      SELECTION_MADE=true
      shift
      ;;
    --executor)
      SELECTED_EXECUTOR=true
      SELECTION_MADE=true
      shift
      ;;
    --all)
      SELECTED_STUDIO=true
      SELECTED_FRONTEND=true
      SELECTED_MCP=true
      SELECTED_EXECUTOR=true
      SELECTION_MADE=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Error: unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [ "${SELECTION_MADE}" = false ]; then
  SELECTED_STUDIO=true
  SELECTED_FRONTEND=true
  SELECTED_MCP=true
  SELECTED_EXECUTOR=true
fi

if [ -z "${HARBOR_REGISTRY}" ]; then
  if ! HARBOR_REGISTRY="$(discover_registry)"; then
    echo "Error: could not auto-discover Harbor registry endpoint." >&2
    echo "Set it explicitly with: --registry <host:port>" >&2
    exit 1
  fi
fi

require_cmd docker
trap cleanup_port_forward EXIT

start_local_port_forward_fallback() {
  require_cmd kubectl

  cleanup_port_forward
  PORT_FORWARD_LOG="$(mktemp)"

  kubectl -n llmctl-harbor port-forward --address 127.0.0.1 svc/harbor :80 >"${PORT_FORWARD_LOG}" 2>&1 &
  PORT_FORWARD_PID=$!

  local local_port=""
  local i
  for i in $(seq 1 60); do
    if ! kill -0 "${PORT_FORWARD_PID}" >/dev/null 2>&1; then
      break
    fi

    local_port="$(grep -Eo '127\.0\.0\.1:[0-9]+' "${PORT_FORWARD_LOG}" | head -n1 | cut -d: -f2 || true)"
    if [ -n "${local_port}" ]; then
      break
    fi

    sleep 0.2
  done

  if [ -z "${local_port}" ]; then
    echo "Error: failed to establish Harbor port-forward fallback." >&2
    if [ -s "${PORT_FORWARD_LOG}" ]; then
      cat "${PORT_FORWARD_LOG}" >&2
    fi
    cleanup_port_forward
    return 1
  fi

  HARBOR_REGISTRY="127.0.0.1:${local_port}"
  echo "Using local Harbor port-forward fallback: ${HARBOR_REGISTRY}"
}

docker_login_once() {
  local tmp_output
  tmp_output="$(mktemp)"
  trap 'rm -f "${tmp_output}"' RETURN

  if ! printf '%s' "${HARBOR_PASSWORD}" | docker login "${HARBOR_REGISTRY}" --username "${HARBOR_USERNAME}" --password-stdin >"${tmp_output}" 2>&1; then
    cat "${tmp_output}" >&2
    if grep -qi "server gave HTTP response to HTTPS client" "${tmp_output}"; then
      rm -f "${tmp_output}"
      trap - RETURN
      return 10
    fi
    if grep -qi "connect: connection refused" "${tmp_output}"; then
      rm -f "${tmp_output}"
      trap - RETURN
      return 11
    fi
    rm -f "${tmp_output}"
    trap - RETURN
    return 1
  fi

  cat "${tmp_output}"
  rm -f "${tmp_output}"
  trap - RETURN
  return 0
}

login_harbor() {
  if [ "${DO_LOGIN}" = false ]; then
    echo "Skipping docker login (--no-login)."
    return
  fi

  local login_rc=0
  if docker_login_once; then
    return
  else
    login_rc=$?
  fi

  if [ "${login_rc}" -eq 10 ] && [[ "${HARBOR_REGISTRY}" != localhost:* ]] && [[ "${HARBOR_REGISTRY}" != 127.0.0.1:* ]] && have_cmd kubectl; then
    echo "Detected HTTP Harbor endpoint; retrying login via local port-forward."
    start_local_port_forward_fallback
    if docker_login_once; then
      return
    else
      login_rc=$?
    fi
  fi

  if [ "${login_rc}" -eq 11 ] && [[ "${HARBOR_REGISTRY}" == localhost:* ]] && have_cmd kubectl; then
    echo "Localhost Harbor endpoint refused connection; retrying via managed local port-forward."
    start_local_port_forward_fallback
    if docker_login_once; then
      return
    else
      login_rc=$?
    fi
  fi

  if [ "${login_rc}" -eq 10 ]; then
    cat >&2 <<EOF
Hint: Harbor is exposed over HTTP in this setup.
Configure Docker insecure registries for ${HARBOR_REGISTRY}, then restart Docker.
Or rerun with --registry 127.0.0.1:<port> while running:
  kubectl -n llmctl-harbor port-forward svc/harbor <port>:80
EOF
  elif [ "${login_rc}" -eq 11 ]; then
    cat >&2 <<EOF
Hint: if you run with localhost, Docker may try IPv6 (::1) while port-forward is IPv4-only.
Use 127.0.0.1 explicitly, for example:
  kubectl -n llmctl-harbor port-forward svc/harbor 30082:80
  ./scripts/build-harbor.sh --registry 127.0.0.1:30082
EOF
  fi

  exit 1
}

ensure_harbor_project() {
  require_cmd curl

  local check_http_code=""
  check_http_code="$(curl -sS -o /dev/null -w '%{http_code}' --user "${HARBOR_USERNAME}:${HARBOR_PASSWORD}" \
    "${HARBOR_API_SCHEME}://${HARBOR_REGISTRY}/api/v2.0/projects/${HARBOR_PROJECT}")"

  if [ "${check_http_code}" = "200" ]; then
    echo "Harbor project '${HARBOR_PROJECT}' already exists."
    return
  fi

  if [ "${check_http_code}" != "404" ]; then
    echo "Error: failed to query Harbor project '${HARBOR_PROJECT}' (HTTP ${check_http_code})." >&2
    exit 1
  fi

  echo "Harbor project '${HARBOR_PROJECT}' not found. Creating it..."

  local create_body
  create_body="$(mktemp)"
  trap 'rm -f "${create_body}"' RETURN
  printf '{"project_name":"%s","public":true}\n' "${HARBOR_PROJECT}" >"${create_body}"

  local create_http_code=""
  create_http_code="$(curl -sS -o /dev/null -w '%{http_code}' --user "${HARBOR_USERNAME}:${HARBOR_PASSWORD}" \
    -H 'Content-Type: application/json' \
    -X POST \
    --data @"${create_body}" \
    "${HARBOR_API_SCHEME}://${HARBOR_REGISTRY}/api/v2.0/projects")"

  rm -f "${create_body}"
  trap - RETURN

  if [ "${create_http_code}" = "201" ] || [ "${create_http_code}" = "409" ]; then
    echo "Harbor project '${HARBOR_PROJECT}' is ready."
    return
  fi

  echo "Error: failed to create Harbor project '${HARBOR_PROJECT}' (HTTP ${create_http_code})." >&2
  exit 1
}

build_and_push() {
  local image_name="$1"
  local build_script="$2"
  local local_image="${image_name}:latest"
  local remote_image="${HARBOR_REGISTRY}/${HARBOR_PROJECT}/${image_name}:${HARBOR_TAG}"

  echo
  echo "==> Building ${local_image}"
  "${build_script}"

  echo "==> Tagging ${local_image} -> ${remote_image}"
  docker tag "${local_image}" "${remote_image}"

  echo "==> Pushing ${remote_image}"
  docker push "${remote_image}"
}

echo "Harbor registry: ${HARBOR_REGISTRY}"
echo "Harbor project: ${HARBOR_PROJECT}"
echo "Harbor tag: ${HARBOR_TAG}"

login_harbor
ensure_harbor_project

if [ "${SELECTED_STUDIO}" = true ]; then
  build_and_push "llmctl-studio" "${REPO_ROOT}/app/llmctl-studio-backend/docker/build-studio.sh"
fi

if [ "${SELECTED_FRONTEND}" = true ]; then
  build_and_push "llmctl-studio-frontend" "${REPO_ROOT}/app/llmctl-studio-frontend/docker/build-frontend.sh"
fi

if [ "${SELECTED_MCP}" = true ]; then
  build_and_push "llmctl-mcp" "${REPO_ROOT}/app/llmctl-mcp/docker/build-llmctl-mcp.sh"
fi

if [ "${SELECTED_EXECUTOR}" = true ]; then
  build_and_push "llmctl-executor" "${REPO_ROOT}/app/llmctl-executor/build-executor.sh"
fi

echo
echo "Done. Pushed selected images to Harbor project '${HARBOR_PROJECT}' with tag '${HARBOR_TAG}'."
