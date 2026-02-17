#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/print-k8s-credentials.sh [options]

Print Harbor, ArgoCD, and PostgreSQL credentials from Kubernetes secrets/configmaps
as copy-pasteable shell exports.

Options:
  --harbor-namespace <ns>      Harbor namespace (default: llmctl-harbor)
  --harbor-secret <name>       Harbor secret name (default: llmctl-harbor-core)
  --argocd-namespace <ns>      ArgoCD namespace (default: argocd)
  --argocd-secret <name>       ArgoCD initial secret (default: argocd-initial-admin-secret)
  --argocd-main-secret <name>  ArgoCD main secret (default: argocd-secret)
  --studio-namespace <ns>      Studio namespace for Postgres creds (default: llmctl)
  --studio-secret <name>       Studio secret (default: llmctl-studio-secrets)
  --studio-config <name>       Studio configmap (default: llmctl-studio-config)
  -h, --help                   Show this help message
EOF
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Error: required command not found: $1" >&2
    exit 1
  fi
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

decode_base64() {
  if printf 'dGVzdA==' | base64 --decode >/dev/null 2>&1; then
    base64 --decode
  elif printf 'dGVzdA==' | base64 -d >/dev/null 2>&1; then
    base64 -d
  else
    base64 -D
  fi
}

secret_exists() {
  local namespace="$1"
  local secret_name="$2"
  kubectl -n "${namespace}" get secret "${secret_name}" >/dev/null 2>&1
}

configmap_exists() {
  local namespace="$1"
  local config_name="$2"
  kubectl -n "${namespace}" get configmap "${config_name}" >/dev/null 2>&1
}

get_secret_key_b64() {
  local namespace="$1"
  local secret_name="$2"
  local key="$3"
  kubectl -n "${namespace}" get secret "${secret_name}" -o go-template="{{index .data \"${key}\"}}" 2>/dev/null || true
}

get_secret_key_decoded() {
  local namespace="$1"
  local secret_name="$2"
  local key="$3"
  local encoded=""
  encoded="$(get_secret_key_b64 "${namespace}" "${secret_name}" "${key}")"
  if [ -z "${encoded}" ]; then
    return 0
  fi
  printf '%s' "${encoded}" | decode_base64
}

get_configmap_key() {
  local namespace="$1"
  local config_name="$2"
  local key="$3"
  kubectl -n "${namespace}" get configmap "${config_name}" -o go-template="{{index .data \"${key}\"}}" 2>/dev/null || true
}

emit_export() {
  local key="$1"
  local value="${2:-}"
  printf 'export %s=%q\n' "${key}" "${value}"
}

argocd_password_matches_hash() {
  local candidate="$1"
  local hash_value="$2"

  if ! have_cmd python3; then
    return 1
  fi

  ARGOC_PASS_CANDIDATE="${candidate}" ARGOC_HASH_VALUE="${hash_value}" python3 - <<'PY' >/dev/null 2>&1
import os
import sys

try:
    import bcrypt
except Exception:
    sys.exit(2)

candidate = os.environ.get("ARGOC_PASS_CANDIDATE", "").encode("utf-8")
hash_value = os.environ.get("ARGOC_HASH_VALUE", "").encode("utf-8")
if not candidate or not hash_value:
    sys.exit(1)

sys.exit(0 if bcrypt.checkpw(candidate, hash_value) else 1)
PY
}

HARBOR_NAMESPACE="llmctl-harbor"
HARBOR_SECRET="llmctl-harbor-core"
ARGOCD_NAMESPACE="argocd"
ARGOCD_SECRET="argocd-initial-admin-secret"
ARGOCD_MAIN_SECRET="argocd-secret"
STUDIO_NAMESPACE="llmctl"
STUDIO_SECRET="llmctl-studio-secrets"
STUDIO_CONFIG="llmctl-studio-config"

while [ $# -gt 0 ]; do
  case "$1" in
    --harbor-namespace)
      HARBOR_NAMESPACE="$2"
      shift 2
      ;;
    --harbor-secret)
      HARBOR_SECRET="$2"
      shift 2
      ;;
    --argocd-namespace)
      ARGOCD_NAMESPACE="$2"
      shift 2
      ;;
    --argocd-secret)
      ARGOCD_SECRET="$2"
      shift 2
      ;;
    --argocd-main-secret)
      ARGOCD_MAIN_SECRET="$2"
      shift 2
      ;;
    --studio-namespace)
      STUDIO_NAMESPACE="$2"
      shift 2
      ;;
    --studio-secret)
      STUDIO_SECRET="$2"
      shift 2
      ;;
    --studio-config)
      STUDIO_CONFIG="$2"
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

require_cmd kubectl
require_cmd base64

echo "# Harbor credentials"
if secret_exists "${HARBOR_NAMESPACE}" "${HARBOR_SECRET}"; then
  harbor_password="$(get_secret_key_decoded "${HARBOR_NAMESPACE}" "${HARBOR_SECRET}" "HARBOR_ADMIN_PASSWORD")"
  harbor_postgres_password="$(get_secret_key_decoded "${HARBOR_NAMESPACE}" "${HARBOR_SECRET}" "POSTGRESQL_PASSWORD")"
  harbor_registry_password="$(get_secret_key_decoded "${HARBOR_NAMESPACE}" "${HARBOR_SECRET}" "REGISTRY_CREDENTIAL_PASSWORD")"

  emit_export HARBOR_NAMESPACE "${HARBOR_NAMESPACE}"
  emit_export HARBOR_SECRET "${HARBOR_SECRET}"
  emit_export HARBOR_USERNAME "admin"

  if [ -n "${harbor_password}" ]; then
    emit_export HARBOR_PASSWORD "${harbor_password}"
  else
    echo "# HARBOR_PASSWORD not found in ${HARBOR_NAMESPACE}/${HARBOR_SECRET}"
  fi

  if [ -n "${harbor_postgres_password}" ]; then
    emit_export HARBOR_POSTGRES_PASSWORD "${harbor_postgres_password}"
  fi

  if [ -n "${harbor_registry_password}" ]; then
    emit_export HARBOR_REGISTRY_PASSWORD "${harbor_registry_password}"
  fi
else
  echo "# Harbor secret not found: ${HARBOR_NAMESPACE}/${HARBOR_SECRET}"
fi

echo
echo "# ArgoCD credentials"
emit_export ARGOCD_NAMESPACE "${ARGOCD_NAMESPACE}"
emit_export ARGOCD_USERNAME "admin"

argocd_password_hash=""
argocd_password=""
if secret_exists "${ARGOCD_NAMESPACE}" "${ARGOCD_MAIN_SECRET}"; then
  argocd_password_hash="$(get_secret_key_decoded "${ARGOCD_NAMESPACE}" "${ARGOCD_MAIN_SECRET}" "admin.password")"
  if [ -n "${argocd_password_hash}" ]; then
    emit_export ARGOCD_PASSWORD_BCRYPT_HASH "${argocd_password_hash}"
  fi
fi

argocd_initial_password=""
if secret_exists "${ARGOCD_NAMESPACE}" "${ARGOCD_SECRET}"; then
  argocd_initial_password="$(get_secret_key_decoded "${ARGOCD_NAMESPACE}" "${ARGOCD_SECRET}" "password")"
fi

argocd_credentials_file="data/argocd/argocd-admin-credentials.env"
argocd_file_password=""
if [ -f "${argocd_credentials_file}" ]; then
  argocd_file_password="$(sed -n 's/^ARGOCD_PASSWORD=//p' "${argocd_credentials_file}" | tail -n1 || true)"
fi

if [ -n "${argocd_password_hash}" ]; then
  if [ -n "${argocd_file_password}" ] && argocd_password_matches_hash "${argocd_file_password}" "${argocd_password_hash}"; then
    argocd_password="${argocd_file_password}"
  elif [ -n "${argocd_initial_password}" ] && argocd_password_matches_hash "${argocd_initial_password}" "${argocd_password_hash}"; then
    argocd_password="${argocd_initial_password}"
  fi
fi

if [ -n "${argocd_password}" ]; then
  emit_export ARGOCD_PASSWORD "${argocd_password}"
elif [ -n "${argocd_initial_password}" ] && [ -z "${argocd_password_hash}" ]; then
  emit_export ARGOCD_PASSWORD "${argocd_initial_password}"
else
  echo "# Could not recover current ArgoCD plaintext password from secrets."
  echo "# If needed, reset it: kubectl -n ${ARGOCD_NAMESPACE} patch secret ${ARGOCD_MAIN_SECRET} --type merge --patch-file <generated-patch>"
fi

echo
echo "# PostgreSQL credentials (llmctl Studio)"
emit_export POSTGRES_NAMESPACE "${STUDIO_NAMESPACE}"
emit_export POSTGRES_SECRET "${STUDIO_SECRET}"

if secret_exists "${STUDIO_NAMESPACE}" "${STUDIO_SECRET}"; then
  pg_password="$(get_secret_key_decoded "${STUDIO_NAMESPACE}" "${STUDIO_SECRET}" "LLMCTL_POSTGRES_PASSWORD")"
  if [ -n "${pg_password}" ]; then
    emit_export LLMCTL_POSTGRES_PASSWORD "${pg_password}"
    emit_export PGPASSWORD "${pg_password}"
  else
    echo "# LLMCTL_POSTGRES_PASSWORD not found in ${STUDIO_NAMESPACE}/${STUDIO_SECRET}"
  fi
else
  echo "# Studio secret not found: ${STUDIO_NAMESPACE}/${STUDIO_SECRET}"
fi

if configmap_exists "${STUDIO_NAMESPACE}" "${STUDIO_CONFIG}"; then
  pg_host="$(get_configmap_key "${STUDIO_NAMESPACE}" "${STUDIO_CONFIG}" "LLMCTL_POSTGRES_HOST")"
  pg_port="$(get_configmap_key "${STUDIO_NAMESPACE}" "${STUDIO_CONFIG}" "LLMCTL_POSTGRES_PORT")"
  pg_db="$(get_configmap_key "${STUDIO_NAMESPACE}" "${STUDIO_CONFIG}" "LLMCTL_POSTGRES_DB")"
  pg_user="$(get_configmap_key "${STUDIO_NAMESPACE}" "${STUDIO_CONFIG}" "LLMCTL_POSTGRES_USER")"

  [ -n "${pg_host}" ] && emit_export LLMCTL_POSTGRES_HOST "${pg_host}"
  [ -n "${pg_port}" ] && emit_export LLMCTL_POSTGRES_PORT "${pg_port}"
  [ -n "${pg_db}" ] && emit_export LLMCTL_POSTGRES_DB "${pg_db}"
  [ -n "${pg_user}" ] && emit_export LLMCTL_POSTGRES_USER "${pg_user}"

  if [ -n "${pg_password:-}" ] && [ -n "${pg_host}" ] && [ -n "${pg_port}" ] && [ -n "${pg_db}" ] && [ -n "${pg_user}" ]; then
    emit_export LLMCTL_POSTGRES_URI "postgresql://${pg_user}:${pg_password}@${pg_host}:${pg_port}/${pg_db}"
  fi
else
  echo "# Studio configmap not found: ${STUDIO_NAMESPACE}/${STUDIO_CONFIG}"
fi
