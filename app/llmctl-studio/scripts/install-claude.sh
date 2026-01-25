#!/usr/bin/env bash
set -euo pipefail

BIN_NAME="claude"
PACKAGE="@anthropic-ai/claude-code"
INSTALL_URL="https://claude.ai/install.sh"
MIN_NODE_MAJOR=18

installer_failed=false
if command -v curl >/dev/null 2>&1; then
  if ! curl -fsSL "$INSTALL_URL" | bash; then
    installer_failed=true
  fi
elif command -v wget >/dev/null 2>&1; then
  if ! wget -qO- "$INSTALL_URL" | bash; then
    installer_failed=true
  fi
else
  installer_failed=true
fi

if [[ "$installer_failed" == "true" ]]; then
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
    echo "Falling back to npm install (deprecated by Anthropic)." >&2
    npm_prefix="$(npm config get prefix)"
    install_prefix="$npm_prefix"
    if [[ ! -w "$npm_prefix" ]]; then
      install_prefix="${NPM_PREFIX:-$HOME/.local}"
      mkdir -p "$install_prefix"
    fi

    if [[ "$install_prefix" == "$npm_prefix" ]]; then
      npm install -g "$PACKAGE"
    else
      npm install -g --prefix "$install_prefix" "$PACKAGE"
    fi

    bin_dir="$install_prefix/bin"
    if [[ "$install_prefix" != "$npm_prefix" && ":$PATH:" != *":$bin_dir:"* ]]; then
      echo "Add ${bin_dir} to PATH to use ${BIN_NAME}." >&2
    fi
  else
    echo "curl/wget (preferred) or npm (Node.js ${MIN_NODE_MAJOR}+) is required to install ${BIN_NAME}." >&2
    exit 1
  fi
fi

if ! command -v "$BIN_NAME" >/dev/null 2>&1; then
  echo "${BIN_NAME} installed but not found on PATH. Open a new shell or adjust PATH." >&2
fi

echo "${BIN_NAME} installed. Try: ${BIN_NAME} --version" >&2
