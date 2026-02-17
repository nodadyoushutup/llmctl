#!/usr/bin/env bash
set -euo pipefail

APP_UID="${APP_UID:-1000}"
APP_GID="${APP_GID:-1000}"
APP_USER="${APP_USER:-llmctl-studio}"
APP_GROUP="${APP_GROUP:-llmctl-studio}"
DOCKER_GID="${DOCKER_GID:-999}"

EXISTING_USER="$(getent passwd "${APP_UID}" | cut -d: -f1 || true)"
EXISTING_GROUP="$(getent group "${APP_GID}" | cut -d: -f1 || true)"

if [ -z "${EXISTING_GROUP}" ]; then
  groupadd -g "${APP_GID}" "${APP_GROUP}"
else
  APP_GROUP="${EXISTING_GROUP}"
fi

if ! id -u "${APP_USER}" >/dev/null 2>&1; then
  if [ -z "${EXISTING_USER}" ]; then
    useradd -m -u "${APP_UID}" -g "${APP_GID}" -s /bin/bash "${APP_USER}"
  else
    useradd -m -o -u "${APP_UID}" -g "${APP_GID}" -s /bin/bash "${APP_USER}"
  fi
fi

if [ ! -d "/home/${APP_USER}" ]; then
  mkdir -p "/home/${APP_USER}"
  chown "${APP_UID}:${APP_GID}" "/home/${APP_USER}"
fi

if getent group docker >/dev/null 2>&1; then
  DOCKER_GID="$(getent group docker | cut -d: -f3)"
fi

if getent group "${DOCKER_GID}" >/dev/null 2>&1; then
  DOCKER_GROUP="$(getent group "${DOCKER_GID}" | cut -d: -f1)"
else
  groupadd -g "${DOCKER_GID}" docker
  DOCKER_GROUP="docker"
fi

usermod -aG "${DOCKER_GROUP}" "${APP_USER}"
