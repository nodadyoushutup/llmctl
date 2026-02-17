from __future__ import annotations

import os
import subprocess
from pathlib import Path

from db import KNOWN_HOSTS_PATH

_SAFE_DIRECTORY_ARG = "safe.directory=*"


def run_git(
    args: list[str],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> str:
    try:
        result = subprocess.run(
            ["git", "-c", _SAFE_DIRECTORY_ARG, *args],
            cwd=str(cwd) if cwd else None,
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("git is required for GitHub sources") from exc
    if result.returncode != 0:
        error = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {error}")
    return result.stdout.strip()


def git_env(config) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    ssh_key = (config.git_ssh_key_path or "").strip()
    if ssh_key:
        key_path = Path(ssh_key)
        if key_path.is_file():
            ssh_cmd = [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-o",
                f"UserKnownHostsFile={KNOWN_HOSTS_PATH}",
                "-i",
                str(key_path),
                "-o",
                "IdentitiesOnly=yes",
            ]
            env["GIT_SSH_COMMAND"] = " ".join(ssh_cmd)
    return env


def ensure_git_repo(config) -> None:
    if not config.git_url:
        raise RuntimeError("Git URL is required for GitHub sources")

    repo_root = config.repo_root
    if repo_root.exists():
        if not (repo_root / ".git").exists():
            raise RuntimeError(f"Git dir exists but is not a repo: {repo_root}")
        return

    repo_root.parent.mkdir(parents=True, exist_ok=True)
    env = git_env(config)
    run_git(
        [
            "clone",
            "--branch",
            config.git_branch,
            "--single-branch",
            config.git_url,
            str(repo_root),
        ],
        env=env,
    )


def git_fetch_and_reset(config) -> None:
    repo_root = config.repo_root
    env = git_env(config)
    run_git(["fetch", "origin", config.git_branch], cwd=repo_root, env=env)
    run_git(
        ["checkout", "-B", config.git_branch, f"origin/{config.git_branch}"],
        cwd=repo_root,
        env=env,
    )
    run_git(
        ["reset", "--hard", f"origin/{config.git_branch}"],
        cwd=repo_root,
        env=env,
    )


def git_rev_parse(
    repo_root: Path, ref: str = "HEAD", env: dict[str, str] | None = None
) -> str:
    return run_git(["rev-parse", ref], cwd=repo_root, env=env)


def git_diff_paths(repo_root: Path, old: str, new: str) -> tuple[list[Path], list[Path]]:
    raw = subprocess.run(
        ["git", "diff", "--name-status", "-z", old, new],
        cwd=str(repo_root),
        check=False,
        capture_output=True,
    )
    if raw.returncode != 0:
        error = (raw.stderr or raw.stdout).decode("utf-8", errors="ignore").strip()
        raise RuntimeError(f"git diff failed: {error}")

    parts = raw.stdout.decode("utf-8", errors="ignore").split("\0")
    changed: list[Path] = []
    deleted: list[Path] = []

    idx = 0
    while idx < len(parts):
        status = parts[idx]
        idx += 1
        if not status:
            continue
        code = status[0]
        if code in {"R", "C"}:
            if idx + 1 >= len(parts):
                break
            old_path = parts[idx]
            new_path = parts[idx + 1]
            idx += 2
            if old_path:
                deleted.append(repo_root / old_path)
            if new_path:
                changed.append(repo_root / new_path)
        else:
            if idx >= len(parts):
                break
            path = parts[idx]
            idx += 1
            if not path:
                continue
            if code == "D":
                deleted.append(repo_root / path)
            else:
                changed.append(repo_root / path)

    return changed, deleted


def safe_git_url(url: str | None) -> str:
    if not url:
        return "unknown"
    if "x-access-token:" not in url:
        return url
    prefix, _, rest = url.partition("x-access-token:")
    if "@" not in rest:
        return f"{prefix}x-access-token:***"
    _, _, tail = rest.partition("@")
    return f"{prefix}x-access-token:***@{tail}"
