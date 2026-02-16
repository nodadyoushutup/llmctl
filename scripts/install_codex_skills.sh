#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  install_codex_skills.sh [--skill <name>] [--dry-run]

Options:
  --skill <name>   Install only one skill by directory name.
  --dry-run        Show actions without copying files.
  -h, --help       Show this help.

Behavior:
  - Source: <repo-root>/codex-skills
  - Destination: ${CODEX_HOME:-$HOME/.codex}/skills
  - Sync strategy: rsync --delete when available, fallback to cp -a replacement
USAGE
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_root="$repo_root/codex-skills"
dest_root="${CODEX_HOME:-$HOME/.codex}/skills"
selected_skill=""
dry_run=0

while (($# > 0)); do
  case "$1" in
    --skill)
      selected_skill="${2:-}"
      shift 2
      ;;
    --dry-run)
      dry_run=1
      shift
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

if [[ ! -d "$source_root" ]]; then
  echo "Error: source skills directory not found: $source_root" >&2
  exit 1
fi

mkdir -p "$dest_root"

installed_any=0
for skill_dir in "$source_root"/*; do
  [[ -d "$skill_dir" ]] || continue
  [[ -f "$skill_dir/SKILL.md" ]] || continue

  skill_name="$(basename "$skill_dir")"
  if [[ -n "$selected_skill" && "$skill_name" != "$selected_skill" ]]; then
    continue
  fi

  destination="$dest_root/$skill_name"
  installed_any=1

  if (( dry_run )); then
    echo "[DRY-RUN] sync $skill_dir -> $destination"
    continue
  fi

  if command -v rsync >/dev/null 2>&1; then
    mkdir -p "$destination"
    rsync -a --delete "$skill_dir/" "$destination/"
  else
    rm -rf "$destination"
    mkdir -p "$dest_root"
    cp -a "$skill_dir" "$destination"
  fi
  echo "[OK] Installed skill: $skill_name"
done

if (( installed_any == 0 )); then
  if [[ -n "$selected_skill" ]]; then
    echo "Error: no skill matched --skill $selected_skill under $source_root" >&2
    exit 1
  fi
  echo "Error: no skills found under $source_root" >&2
  exit 1
fi
