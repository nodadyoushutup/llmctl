#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  capture_screenshot.sh --url <url> --route <route> [options]

Required:
  --url <url>                 URL to capture (example: http://localhost:5000/)
  --route <route-or-page>     Route/page label used in filename

Options:
  --state <state>             State label (default: baseline)
  --viewport <WxH>            Viewport in WIDTHxHEIGHT format (default: 1920x1080)
  --out-dir <path>            Output directory (default: docs/screenshots)
  --root <path>               Repository root for relative out-dir (default: current directory)
  -h, --help                  Show this help
USAGE
}

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Error: required command not found: $command_name" >&2
    exit 1
  fi
}

slugify() {
  printf '%s' "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's|[/[:space:]]+|-|g; s|[^a-z0-9._-]+|-|g; s|-+|-|g; s|^-+||; s|-+$||'
}

url=""
route=""
state="baseline"
viewport="1920x1080"
out_dir="docs/screenshots"
repo_root="$(pwd)"

while (($# > 0)); do
  case "$1" in
    --url)
      url="${2:-}"
      shift 2
      ;;
    --route)
      route="${2:-}"
      shift 2
      ;;
    --state)
      state="${2:-}"
      shift 2
      ;;
    --viewport)
      viewport="${2:-}"
      shift 2
      ;;
    --out-dir)
      out_dir="${2:-}"
      shift 2
      ;;
    --root)
      repo_root="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Error: unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$url" || -z "$route" ]]; then
  echo "Error: --url and --route are required." >&2
  usage
  exit 1
fi

if [[ ! "$viewport" =~ ^[0-9]+x[0-9]+$ ]]; then
  echo "Error: --viewport must match WIDTHxHEIGHT (for example 1920x1080)." >&2
  exit 1
fi

width="${viewport%x*}"
height="${viewport#*x}"
window_size="${width},${height}"

require_command chromium-browser
require_command date
require_command sha256sum

mkdir -p "$repo_root"
if [[ "$out_dir" = /* ]]; then
  output_dir="$out_dir"
else
  output_dir="$repo_root/$out_dir"
fi
mkdir -p "$output_dir"

timestamp="$(date +%Y%m%d-%H%M%S)"
if git -C "$repo_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git_sha="$(git -C "$repo_root" rev-parse --short=7 HEAD 2>/dev/null || true)"
fi
if [[ -z "${git_sha:-}" ]]; then
  git_sha="nogit00"
fi

route_slug="$(slugify "$route")"
state_slug="$(slugify "$state")"
seed="${url}|${route_slug}|${state_slug}|${viewport}|${timestamp}|$$|$RANDOM"
hash6="$(printf '%s' "$seed" | sha256sum | cut -c1-6)"
filename="${route_slug}--${state_slug}--${viewport}--${timestamp}--${git_sha}--${hash6}.png"
output_path="$output_dir/$filename"

chromium-browser \
  --headless \
  --disable-gpu \
  --disable-dev-shm-usage \
  --hide-scrollbars \
  --screenshot="$output_path" \
  --window-size="$window_size" \
  "$url"

printf '%s\n' "$output_path"
