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
start_forward "argocd" "argocd-server" "30934" "80"
start_forward "argocd" "argocd-server" "30370" "443"
start_forward "llmctl-harbor" "harbor" "30082" "80"
start_forward "llmctl" "llmctl-mcp-atlassian" "18000" "8000"

echo "Port forwards are running. Keep this script open."
echo "Studio: http://<host-lan-ip>:30157/flowcharts/1"
echo "ArgoCD: http://<host-lan-ip>:30934 or https://<host-lan-ip>:30370"
echo "Harbor: http://<host-lan-ip>:30082"
echo "Jira MCP (Atlassian): http://<host-lan-ip>:18000/mcp"
echo "Press Ctrl+C to stop all forwards."

while true; do
  if ! wait -n; then
    echo "A port-forward process exited. Check /tmp/pf-*.log for details."
    exit 1
  fi
done
