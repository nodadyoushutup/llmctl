#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
TEMPLATE_PATH="${REPO_ROOT}/kubernetes-overlays/harbor-images/kustomization.tmpl.yaml"
OUTPUT_PATH="${REPO_ROOT}/kubernetes-overlays/harbor-images/kustomization.yaml"

usage() {
  cat <<'EOF'
Usage: scripts/configure-harbor-image-overlays.sh [options]

Render Harbor image overlay for Kubernetes.

Defaults:
  - Registry endpoint auto-discovered from Harbor ClusterIP service (fallback: NodePort)
  - Project: llmctl
  - Tag: latest

Options:
  --registry <host:port>   Harbor registry endpoint (example: 10.107.62.134:80)
  --project <name>         Harbor project name (default: llmctl)
  --tag <tag>              Image tag (default: latest)
  -h, --help               Show this help

Outputs:
  - kubernetes-overlays/harbor-images/kustomization.yaml

Then apply one of:
  - kubectl apply -k kubernetes-overlays/harbor-images
  - kubectl apply -k kubernetes-overlays/minikube-live-code-harbor
EOF
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

discover_registry() {
  local service_ip=""
  local service_port=""
  local node_port=""
  local node_ip=""
  local profile="${MINIKUBE_PROFILE:-llmctl}"

  if have_cmd kubectl; then
    service_ip="$(kubectl -n llmctl-harbor get svc harbor -o jsonpath='{.spec.clusterIP}' 2>/dev/null || true)"
    service_port="$(kubectl -n llmctl-harbor get svc harbor -o jsonpath='{.spec.ports[?(@.name=="http")].port}' 2>/dev/null || true)"
    if [ -n "${service_ip}" ] && [ "${service_ip}" != "None" ] && [ -n "${service_port}" ]; then
      printf '%s:%s\n' "${service_ip}" "${service_port}"
      return 0
    fi

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

HARBOR_REGISTRY="${HARBOR_REGISTRY:-}"
HARBOR_PROJECT="${HARBOR_PROJECT:-llmctl}"
HARBOR_TAG="${HARBOR_TAG:-latest}"

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

if [ -z "${HARBOR_REGISTRY}" ]; then
  if ! HARBOR_REGISTRY="$(discover_registry)"; then
    echo "Error: could not auto-discover Harbor registry endpoint." >&2
    echo "Set it explicitly with: --registry <host:port>" >&2
    exit 1
  fi
fi

if [ ! -f "${TEMPLATE_PATH}" ]; then
  echo "Error: missing template: ${TEMPLATE_PATH}" >&2
  exit 1
fi

mkdir -p "$(dirname "${OUTPUT_PATH}")"

sed \
  -e "s|__HARBOR_REGISTRY__|${HARBOR_REGISTRY}|g" \
  -e "s|__HARBOR_PROJECT__|${HARBOR_PROJECT}|g" \
  -e "s|__HARBOR_TAG__|${HARBOR_TAG}|g" \
  "${TEMPLATE_PATH}" >"${OUTPUT_PATH}"

echo "Rendered ${OUTPUT_PATH}"
echo "  registry: ${HARBOR_REGISTRY}"
echo "  project:  ${HARBOR_PROJECT}"
echo "  tag:      ${HARBOR_TAG}"
echo
echo "Apply Harbor images overlay:"
echo "  kubectl apply -k kubernetes-overlays/harbor-images"
echo
echo "Apply Harbor + live code overlay:"
echo "  kubectl apply -k kubernetes-overlays/minikube-live-code-harbor"
