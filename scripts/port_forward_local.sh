#!/usr/bin/env bash
set -euo pipefail

HOST_BIND="0.0.0.0"
KUBECTL="${KUBECTL:-kubectl}"

declare -a PIDS=()

cleanup() {
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}

trap cleanup EXIT INT TERM

check_port_free() {
  local port="$1"
  if ss -ltn "( sport = :$port )" | tail -n +2 | grep -q .; then
    echo "Port $port is already in use on this host. Stop the current listener first."
    exit 1
  fi
}

start_forward() {
  local namespace="$1"
  local service="$2"
  local local_port="$3"
  local remote_port="$4"

  check_port_free "$local_port"

  echo "Forwarding ${namespace}/${service} ${HOST_BIND}:${local_port} -> ${remote_port}"
  "$KUBECTL" -n "$namespace" port-forward --address "$HOST_BIND" "svc/${service}" "${local_port}:${remote_port}" >/tmp/pf-"${namespace}"-"${service}"-"${local_port}".log 2>&1 &
  PIDS+=("$!")
}

start_forward "llmctl" "llmctl-studio-frontend" "30157" "8080"
start_forward "ingress-nginx" "ingress-nginx-controller" "3080" "80"
start_forward "ingress-nginx" "ingress-nginx-controller" "3443" "443"
start_forward "argocd" "argocd-server" "30934" "80"
start_forward "argocd" "argocd-server" "30370" "443"
start_forward "llmctl-harbor" "harbor" "30082" "80"
start_forward "llmctl" "llmctl-mcp" "19020" "9020"
start_forward "llmctl" "llmctl-mcp-github" "18001" "8000"
start_forward "llmctl" "llmctl-mcp-atlassian" "18000" "8000"
start_forward "llmctl" "llmctl-mcp-chroma" "18002" "8000"
start_forward "llmctl" "llmctl-mcp-google-cloud" "18003" "8000"
start_forward "llmctl" "llmctl-mcp-google-workspace" "18004" "8000"

echo "Port forwards are running. Keep this script open."
echo "Studio: http://<host-lan-ip>:30157/flowcharts/1"
echo "Ingress HTTP: http://<host-lan-ip>:3080"
echo "Ingress HTTPS: https://<host-lan-ip>:3443"
echo "MCP via ingress: http://<host-lan-ip>:3080/mcp/llmctl"
echo "MCP via ingress: https://<host-lan-ip>:3443/mcp/llmctl"
echo "ArgoCD: http://<host-lan-ip>:30934 or https://<host-lan-ip>:30370"
echo "Harbor: http://<host-lan-ip>:30082"
echo "LLMCTL MCP: http://<host-lan-ip>:19020/mcp"
echo "GitHub MCP: http://<host-lan-ip>:18001/mcp"
echo "Atlassian MCP: http://<host-lan-ip>:18000/mcp/"
echo "Chroma MCP: http://<host-lan-ip>:18002/mcp/"
echo "Google Cloud MCP: http://<host-lan-ip>:18003/mcp"
echo "Google Workspace MCP: http://<host-lan-ip>:18004/mcp"
echo "Press Ctrl+C to stop all forwards."

while true; do
  if ! wait -n; then
    echo "A port-forward process exited. Check /tmp/pf-*.log for details."
    exit 1
  fi
done
