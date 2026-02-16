#!/usr/bin/env bash
set -euo pipefail

PACKAGE="@openai/codex"
PACKAGE_TAG="${CODEX_NPM_TAG:-latest}"
PACKAGE_SPEC="${PACKAGE}@${PACKAGE_TAG}"
BIN_NAME="codex"
MIN_NODE_MAJOR=16

use_npm=false
if command -v npm >/dev/null 2>&1 && command -v node >/dev/null 2>&1; then
  node_version="$(node -v)"
  node_major="${node_version#v}"
  node_major="${node_major%%.*}"
  if [[ "${node_major}" =~ ^[0-9]+$ ]] && (( node_major >= MIN_NODE_MAJOR )); then
    use_npm=true
  else
    echo "Node.js ${MIN_NODE_MAJOR}+ is required for npm install (found ${node_version})." >&2
  fi
fi

if [[ "$use_npm" == "true" ]]; then
  npm_prefix="$(npm config get prefix)"
  install_prefix="$npm_prefix"
  if [[ ! -w "$npm_prefix" ]]; then
    install_prefix="${NPM_PREFIX:-$HOME/.local}"
    mkdir -p "$install_prefix"
  fi

  if [[ "$install_prefix" == "$npm_prefix" ]]; then
    npm install -g "$PACKAGE_SPEC"
  else
    npm install -g --prefix "$install_prefix" "$PACKAGE_SPEC"
  fi

  bin_dir="$install_prefix/bin"
  if [[ "$install_prefix" != "$npm_prefix" && ":$PATH:" != *":$bin_dir:"* ]]; then
    echo "Add ${bin_dir} to PATH to use ${BIN_NAME}." >&2
  fi

  echo "${BIN_NAME} installed from ${PACKAGE_SPEC}. Try: ${bin_dir}/${BIN_NAME} --version" >&2
elif command -v brew >/dev/null 2>&1; then
  brew install --cask codex
  echo "${BIN_NAME} installed. Try: ${BIN_NAME} --version" >&2
else
  echo "npm (Node.js ${MIN_NODE_MAJOR}+) or brew is required to install ${BIN_NAME}." >&2
  exit 1
fi
