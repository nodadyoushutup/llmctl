from __future__ import annotations

from dataclasses import dataclass
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from rag.domain.contracts import (
    RAG_FLOWCHART_MODE_DELTA_INDEX,
    RAG_FLOWCHART_MODE_FRESH_INDEX,
    execute_query_contract,
    run_index_for_collections,
)
from services.execution.tooling import (
    ToolInvocationConfig,
    ToolInvocationOutcome,
    invoke_deterministic_tool,
)

TOOL_DOMAIN_CONTRACT_VERSION = "v1"
TOOL_DOMAIN_NODE_TYPE = "task"

TOOL_DOMAIN_WORKSPACE = "workspace"
TOOL_DOMAIN_GIT = "git"
TOOL_DOMAIN_COMMAND = "command"
TOOL_DOMAIN_RAG = "rag"

WORKSPACE_TOOL_NAME = "deterministic.workspace"
GIT_TOOL_NAME = "deterministic.git"
COMMAND_TOOL_NAME = "deterministic.command"
RAG_TOOL_NAME = "deterministic.rag"

WORKSPACE_OPERATIONS = {
    "list",
    "read",
    "write",
    "mkdir",
    "delete",
    "move",
    "copy",
    "search",
    "apply_patch",
    "chmod",
}
GIT_OPERATIONS = {
    "branch",
    "commit",
    "push",
    "pull_request",
    "cherry_pick",
    "rebase_noninteractive",
    "tag",
}
COMMAND_OPERATIONS = {
    "run",
    "session_start",
    "session_write",
    "session_read",
    "session_stop",
    "background_start",
    "background_status",
    "background_wait",
    "background_stop",
    "resource_limits",
}
RAG_OPERATIONS = {
    "index",
    "query",
}


class ToolDomainError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolDomainContext:
    workspace_root: Path
    execution_id: int | None = None
    request_id: str | None = None
    correlation_id: str | None = None

    def resolved_workspace_root(self) -> Path:
        root = Path(self.workspace_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root


@dataclass
class _PTYSession:
    session_id: str
    process: subprocess.Popen[bytes]
    master_fd: int
    cwd: Path
    started_at: float


@dataclass
class _BackgroundJob:
    job_id: str
    process: subprocess.Popen[Any]
    cwd: Path
    command: list[str]
    started_at: float
    stdout_path: Path
    stderr_path: Path


_PTY_SESSIONS: dict[str, _PTYSession] = {}
_BACKGROUND_JOBS: dict[str, _BackgroundJob] = {}
_SESSION_LOCK = threading.Lock()


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_operation(value: Any) -> str:
    return _normalize_text(value).lower()


def _parse_positive_int(value: Any, *, default: int, minimum: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed < minimum:
        return default
    return parsed


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    if normalized == "":
        return default
    return default


def _relative_path(root: Path, candidate: Path) -> str:
    try:
        return candidate.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return candidate.name


def _resolve_workspace_path(root: Path, value: Any | None) -> Path:
    raw = _normalize_text(value)
    candidate = (root / raw).resolve() if raw else root.resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ToolDomainError(f"Path escapes workspace root: {candidate}")
    return candidate


def _parse_command(value: Any) -> tuple[list[str], bool]:
    if isinstance(value, list):
        tokens = [str(item) for item in value if str(item).strip()]
        if not tokens:
            raise ToolDomainError("Command list is empty.")
        return tokens, False
    text = _normalize_text(value)
    if not text:
        raise ToolDomainError("Command is required.")
    return [text], True


def _build_domain_output(
    *,
    domain: str,
    operation: str,
    result: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    output_state: dict[str, Any] = {
        "node_type": TOOL_DOMAIN_NODE_TYPE,
        "contract_version": TOOL_DOMAIN_CONTRACT_VERSION,
        "tool_domain": domain,
        "operation": operation,
        "result": result,
    }
    routing_state: dict[str, Any] = {
        "tool_domain": domain,
        "operation": operation,
    }
    return output_state, routing_state


def _validate_domain_output(
    output_state: dict[str, Any],
    routing_state: dict[str, Any],
) -> None:
    if not isinstance(output_state, dict):
        raise ValueError("output_state must be an object.")
    if not isinstance(routing_state, dict):
        raise ValueError("routing_state must be an object.")
    if str(output_state.get("node_type") or "").strip().lower() != TOOL_DOMAIN_NODE_TYPE:
        raise ValueError("output_state.node_type must be 'task'.")
    if str(output_state.get("contract_version") or "").strip() != TOOL_DOMAIN_CONTRACT_VERSION:
        raise ValueError("output_state.contract_version is invalid.")
    if not isinstance(output_state.get("result"), dict):
        raise ValueError("output_state.result must be an object.")
    operation = _normalize_operation(output_state.get("operation"))
    if not operation:
        raise ValueError("output_state.operation is required.")
    if _normalize_operation(routing_state.get("operation")) != operation:
        raise ValueError("routing_state.operation must match output_state.operation.")
    domain = _normalize_operation(output_state.get("tool_domain"))
    if not domain:
        raise ValueError("output_state.tool_domain is required.")
    if _normalize_operation(routing_state.get("tool_domain")) != domain:
        raise ValueError("routing_state.tool_domain must match output_state.tool_domain.")


def _invoke_domain_tool(
    *,
    context: ToolDomainContext,
    domain: str,
    tool_name: str,
    operation: str,
    args: dict[str, Any] | None,
    invoke: Any,
) -> ToolInvocationOutcome:
    payload = dict(args or {})
    idempotency_key = _normalize_text(payload.get("idempotency_key")) or None
    return invoke_deterministic_tool(
        config=ToolInvocationConfig(
            node_type=TOOL_DOMAIN_NODE_TYPE,
            tool_name=tool_name,
            operation=operation,
            execution_id=context.execution_id,
            request_id=context.request_id,
            correlation_id=context.correlation_id,
            idempotency_key=idempotency_key,
        ),
        invoke=lambda: _build_domain_output(
            domain=domain,
            operation=operation,
            result=invoke(),
        ),
        validate=_validate_domain_output,
    )


def _run_subprocess(
    *,
    command: list[str],
    cwd: Path,
    timeout_seconds: int = 120,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=max(1, int(timeout_seconds)),
        env=env,
    )
    if check and completed.returncode != 0:
        raise ToolDomainError(
            "Command failed: "
            + " ".join(command)
            + f" (exit={completed.returncode}). stderr={completed.stderr.strip()}"
        )
    return completed


def _workspace_operation_list(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    target = _resolve_workspace_path(root, args.get("path"))
    if not target.exists():
        raise ToolDomainError(f"Path does not exist: {target}")
    include_hidden = _coerce_bool(args.get("include_hidden"))
    recursive = _coerce_bool(args.get("recursive"))
    entries = target.rglob("*") if recursive else target.iterdir()
    rows: list[dict[str, Any]] = []
    for entry in entries:
        rel = _relative_path(root, entry)
        if not include_hidden and any(part.startswith(".") for part in Path(rel).parts):
            continue
        stats = entry.stat()
        rows.append(
            {
                "path": rel,
                "type": "dir" if entry.is_dir() else "file",
                "size": int(stats.st_size),
                "mode": oct(stat.S_IMODE(stats.st_mode)),
                "modified_at": int(stats.st_mtime),
            }
        )
    rows.sort(key=lambda item: str(item.get("path") or ""))
    return {
        "path": _relative_path(root, target),
        "recursive": recursive,
        "entries": rows,
    }


def _workspace_operation_read(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    target = _resolve_workspace_path(root, args.get("path"))
    if not target.exists() or not target.is_file():
        raise ToolDomainError(f"File does not exist: {target}")
    encoding = _normalize_text(args.get("encoding")) or "utf-8"
    max_bytes = _parse_positive_int(args.get("max_bytes"), default=5_000_000)
    data = target.read_bytes()
    truncated = len(data) > max_bytes
    payload = data[:max_bytes]
    return {
        "path": _relative_path(root, target),
        "content": payload.decode(encoding, errors="replace"),
        "encoding": encoding,
        "bytes": len(payload),
        "truncated": truncated,
        "total_bytes": len(data),
    }


def _workspace_operation_write(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    target = _resolve_workspace_path(root, args.get("path"))
    create_parents = _coerce_bool(args.get("create_parents"), default=True)
    if create_parents:
        target.parent.mkdir(parents=True, exist_ok=True)
    append = _coerce_bool(args.get("append"))
    encoding = _normalize_text(args.get("encoding")) or "utf-8"
    content = str(args.get("content") or "")
    mode = "a" if append else "w"
    with target.open(mode, encoding=encoding) as handle:
        written = handle.write(content)
    return {
        "path": _relative_path(root, target),
        "bytes_written": int(written),
        "append": append,
    }


def _workspace_operation_mkdir(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    target = _resolve_workspace_path(root, args.get("path"))
    target.mkdir(
        parents=_coerce_bool(args.get("parents"), default=True),
        exist_ok=_coerce_bool(args.get("exist_ok"), default=True),
    )
    return {
        "path": _relative_path(root, target),
        "created": True,
    }


def _workspace_operation_delete(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    target = _resolve_workspace_path(root, args.get("path"))
    if target.resolve() == root.resolve():
        raise ToolDomainError("Refusing to delete workspace root.")
    if not target.exists():
        return {
            "path": _relative_path(root, target),
            "deleted": False,
            "reason": "not_found",
        }
    if target.is_dir():
        if _coerce_bool(args.get("recursive"), default=True):
            shutil.rmtree(target)
        else:
            target.rmdir()
    else:
        target.unlink()
    return {
        "path": _relative_path(root, target),
        "deleted": True,
    }


def _workspace_operation_move(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    source = _resolve_workspace_path(root, args.get("source"))
    target = _resolve_workspace_path(root, args.get("target"))
    if not source.exists():
        raise ToolDomainError(f"Source does not exist: {source}")
    overwrite = _coerce_bool(args.get("overwrite"))
    if target.exists():
        if not overwrite:
            raise ToolDomainError(f"Target exists: {target}")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    return {
        "source": _relative_path(root, source),
        "target": _relative_path(root, target),
        "moved": True,
    }


def _workspace_operation_copy(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    source = _resolve_workspace_path(root, args.get("source"))
    target = _resolve_workspace_path(root, args.get("target"))
    if not source.exists():
        raise ToolDomainError(f"Source does not exist: {source}")
    overwrite = _coerce_bool(args.get("overwrite"))
    recursive = _coerce_bool(args.get("recursive"), default=True)
    if target.exists():
        if not overwrite:
            raise ToolDomainError(f"Target exists: {target}")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        if not recursive:
            raise ToolDomainError("Recursive copy is required for directories.")
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)
    return {
        "source": _relative_path(root, source),
        "target": _relative_path(root, target),
        "copied": True,
    }


def _workspace_operation_search(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    target = _resolve_workspace_path(root, args.get("path"))
    if not target.exists() or not target.is_dir():
        raise ToolDomainError(f"Search root must be a directory: {target}")
    query = str(args.get("query") or "")
    if not query:
        raise ToolDomainError("search.query is required.")
    use_regex = _coerce_bool(args.get("regex"))
    pattern = re.compile(query) if use_regex else None
    glob = _normalize_text(args.get("glob")) or "**/*"
    max_results = _parse_positive_int(args.get("max_results"), default=100)
    matches: list[dict[str, Any]] = []
    for file_path in target.glob(glob):
        if not file_path.is_file():
            continue
        rel_path = _relative_path(root, file_path)
        try:
            with file_path.open("r", encoding="utf-8", errors="replace") as handle:
                for index, line in enumerate(handle, start=1):
                    matched = bool(pattern.search(line)) if pattern else query in line
                    if not matched:
                        continue
                    matches.append(
                        {
                            "path": rel_path,
                            "line_number": index,
                            "line": line.rstrip("\n"),
                        }
                    )
                    if len(matches) >= max_results:
                        return {
                            "query": query,
                            "regex": use_regex,
                            "matches": matches,
                            "truncated": True,
                        }
        except OSError:
            continue
    return {
        "query": query,
        "regex": use_regex,
        "matches": matches,
        "truncated": False,
    }


def _workspace_operation_apply_patch(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    patch_text = str(args.get("patch") or "")
    if not patch_text.strip():
        raise ToolDomainError("apply_patch requires patch text.")
    timeout_seconds = _parse_positive_int(args.get("timeout_seconds"), default=120)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".patch",
        delete=False,
    ) as handle:
        handle.write(patch_text)
        patch_path = Path(handle.name)
    try:
        patch_bin = shutil.which("patch")
        if patch_bin is not None:
            completed = _run_subprocess(
                command=[
                    patch_bin,
                    "-p0",
                    "--forward",
                    "--batch",
                    "--reject-file=-",
                    "-i",
                    str(patch_path),
                ],
                cwd=root,
                timeout_seconds=timeout_seconds,
                check=False,
            )
            if completed.returncode == 0:
                return {
                    "applied": True,
                    "method": "patch",
                    "stdout": completed.stdout.strip(),
                    "stderr": completed.stderr.strip(),
                }
        git_bin = shutil.which("git")
        if git_bin is None:
            raise ToolDomainError(
                "No patch implementation is available (missing 'patch' and 'git')."
            )
        completed = _run_subprocess(
            command=[
                git_bin,
                "apply",
                "--whitespace=nowarn",
                str(patch_path),
            ],
            cwd=root,
            timeout_seconds=timeout_seconds,
            check=True,
        )
        return {
            "applied": True,
            "method": "git_apply",
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }
    finally:
        try:
            patch_path.unlink(missing_ok=True)
        except OSError:
            pass


def _parse_chmod_mode(value: Any) -> int:
    if isinstance(value, int):
        return value
    text = _normalize_text(value)
    if not text:
        raise ToolDomainError("chmod.mode is required.")
    if text.startswith("0o"):
        base = 8
    elif text.startswith("0x"):
        base = 16
    else:
        base = 8
    try:
        parsed = int(text, base=base)
    except ValueError as exc:
        raise ToolDomainError(f"Invalid chmod mode: {value}") from exc
    return parsed


def _workspace_operation_chmod(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    target = _resolve_workspace_path(root, args.get("path"))
    if not target.exists():
        raise ToolDomainError(f"Path does not exist: {target}")
    mode = _parse_chmod_mode(args.get("mode"))
    target.chmod(mode)
    return {
        "path": _relative_path(root, target),
        "mode": oct(mode),
    }


def _workspace_operation_dispatch(root: Path, operation: str, args: dict[str, Any]) -> dict[str, Any]:
    if operation == "list":
        return _workspace_operation_list(root, args)
    if operation == "read":
        return _workspace_operation_read(root, args)
    if operation == "write":
        return _workspace_operation_write(root, args)
    if operation == "mkdir":
        return _workspace_operation_mkdir(root, args)
    if operation == "delete":
        return _workspace_operation_delete(root, args)
    if operation == "move":
        return _workspace_operation_move(root, args)
    if operation == "copy":
        return _workspace_operation_copy(root, args)
    if operation == "search":
        return _workspace_operation_search(root, args)
    if operation == "apply_patch":
        return _workspace_operation_apply_patch(root, args)
    if operation == "chmod":
        return _workspace_operation_chmod(root, args)
    raise ToolDomainError(f"Unsupported workspace operation: {operation}")


def run_workspace_tool(
    *,
    context: ToolDomainContext,
    operation: str,
    args: dict[str, Any] | None = None,
) -> ToolInvocationOutcome:
    normalized_operation = _normalize_operation(operation)
    if normalized_operation not in WORKSPACE_OPERATIONS:
        raise ToolDomainError(f"Unsupported workspace operation: {operation}")
    root = context.resolved_workspace_root()
    payload = dict(args or {})
    return _invoke_domain_tool(
        context=context,
        domain=TOOL_DOMAIN_WORKSPACE,
        tool_name=WORKSPACE_TOOL_NAME,
        operation=normalized_operation,
        args=payload,
        invoke=lambda: _workspace_operation_dispatch(root, normalized_operation, payload),
    )


def _run_git(
    *,
    root: Path,
    command: list[str],
    timeout_seconds: int = 120,
    check: bool = True,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    if shutil.which("git") is None:
        raise ToolDomainError("git is not available on PATH.")
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return _run_subprocess(
        command=["git", *command],
        cwd=root,
        timeout_seconds=timeout_seconds,
        check=check,
        env=env,
    )


def _git_operation_branch(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    action = _normalize_operation(args.get("action") or "list")
    timeout_seconds = _parse_positive_int(args.get("timeout_seconds"), default=120)
    if action == "list":
        completed = _run_git(
            root=root,
            command=["branch", "--list", "--format=%(refname:short)"],
            timeout_seconds=timeout_seconds,
        )
        rows = [
            line.strip()
            for line in completed.stdout.splitlines()
            if line.strip()
        ]
        return {"action": action, "branches": rows}
    name = _normalize_text(args.get("name"))
    if not name:
        raise ToolDomainError("git branch action requires name.")
    if action == "create":
        start_point = _normalize_text(args.get("from"))
        command = ["branch", name]
        if start_point:
            command.append(start_point)
        _run_git(root=root, command=command, timeout_seconds=timeout_seconds)
        return {"action": action, "branch": name}
    if action == "delete":
        force = _coerce_bool(args.get("force"))
        command = ["branch", "-D" if force else "-d", name]
        _run_git(root=root, command=command, timeout_seconds=timeout_seconds)
        return {"action": action, "branch": name, "force": force}
    if action == "switch":
        create = _coerce_bool(args.get("create"))
        start_point = _normalize_text(args.get("from"))
        command = ["switch"]
        if create:
            command.extend(["-c", name])
            if start_point:
                command.append(start_point)
        else:
            command.append(name)
        _run_git(root=root, command=command, timeout_seconds=timeout_seconds)
        return {"action": action, "branch": name, "create": create}
    raise ToolDomainError(f"Unsupported git branch action: {action}")


def _git_operation_commit(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    timeout_seconds = _parse_positive_int(args.get("timeout_seconds"), default=120)
    add_all = _coerce_bool(args.get("add_all"), default=True)
    if add_all:
        _run_git(root=root, command=["add", "-A"], timeout_seconds=timeout_seconds)
    else:
        paths = args.get("paths")
        if not isinstance(paths, list) or not paths:
            raise ToolDomainError("git commit.paths must be a non-empty list when add_all=false.")
        _run_git(
            root=root,
            command=["add", *[str(item) for item in paths]],
            timeout_seconds=timeout_seconds,
        )
    message = _normalize_text(args.get("message"))
    if not message:
        raise ToolDomainError("git commit requires message.")
    command = ["commit", "-m", message]
    if _coerce_bool(args.get("allow_empty")):
        command.append("--allow-empty")
    completed = _run_git(
        root=root,
        command=command,
        timeout_seconds=timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        if "nothing to commit" in completed.stderr.lower():
            return {
                "committed": False,
                "reason": "nothing_to_commit",
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
            }
        raise ToolDomainError(
            f"git commit failed (exit={completed.returncode}): {completed.stderr.strip()}"
        )
    sha = _run_git(root=root, command=["rev-parse", "HEAD"], timeout_seconds=timeout_seconds)
    return {
        "committed": True,
        "commit": sha.stdout.strip(),
        "stdout": completed.stdout.strip(),
    }


def _git_operation_push(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    timeout_seconds = _parse_positive_int(args.get("timeout_seconds"), default=180)
    remote = _normalize_text(args.get("remote")) or "origin"
    branch = _normalize_text(args.get("branch"))
    if not branch:
        head = _run_git(
            root=root,
            command=["rev-parse", "--abbrev-ref", "HEAD"],
            timeout_seconds=timeout_seconds,
        )
        branch = head.stdout.strip()
    command = ["push"]
    if _coerce_bool(args.get("set_upstream")):
        command.append("-u")
    if _coerce_bool(args.get("force")):
        command.append("--force")
    command.extend([remote, branch])
    completed = _run_git(root=root, command=command, timeout_seconds=timeout_seconds)
    return {
        "remote": remote,
        "branch": branch,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _origin_compare_url(root: Path, base: str, head: str) -> str | None:
    try:
        completed = _run_git(
            root=root,
            command=["config", "--get", "remote.origin.url"],
            timeout_seconds=30,
        )
    except Exception:
        return None
    remote = completed.stdout.strip()
    if not remote:
        return None
    https_url = remote
    if remote.startswith("git@github.com:"):
        https_url = "https://github.com/" + remote[len("git@github.com:") :]
    if https_url.endswith(".git"):
        https_url = https_url[:-4]
    if not https_url.startswith("https://github.com/"):
        return None
    return f"{https_url}/compare/{base}...{head}?expand=1"


def _git_operation_pull_request(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    timeout_seconds = _parse_positive_int(args.get("timeout_seconds"), default=180)
    base = _normalize_text(args.get("base")) or "main"
    head = _normalize_text(args.get("head"))
    if not head:
        completed = _run_git(
            root=root,
            command=["rev-parse", "--abbrev-ref", "HEAD"],
            timeout_seconds=timeout_seconds,
        )
        head = completed.stdout.strip()
    title = _normalize_text(args.get("title")) or f"Update {head}"
    body = str(args.get("body") or "").strip()
    gh_bin = shutil.which("gh")
    if gh_bin is not None:
        command = [
            gh_bin,
            "pr",
            "create",
            "--base",
            base,
            "--head",
            head,
            "--title",
            title,
            "--body",
            body or "Automated pull request from llmctl runtime tooling.",
        ]
        completed = _run_subprocess(
            command=command,
            cwd=root,
            timeout_seconds=timeout_seconds,
            check=False,
        )
        if completed.returncode == 0:
            url = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else ""
            return {
                "created": True,
                "url": url,
                "base": base,
                "head": head,
            }
    compare_url = _origin_compare_url(root, base, head)
    return {
        "created": False,
        "base": base,
        "head": head,
        "compare_url": compare_url,
        "reason": "gh_cli_unavailable_or_failed",
    }


def _git_operation_cherry_pick(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    commit = _normalize_text(args.get("commit"))
    if not commit:
        raise ToolDomainError("git cherry_pick requires commit.")
    timeout_seconds = _parse_positive_int(args.get("timeout_seconds"), default=120)
    command = ["cherry-pick"]
    if _coerce_bool(args.get("no_commit")):
        command.append("--no-commit")
    mainline = _parse_positive_int(args.get("mainline"), default=0, minimum=0)
    if mainline > 0:
        command.extend(["-m", str(mainline)])
    command.append(commit)
    completed = _run_git(root=root, command=command, timeout_seconds=timeout_seconds)
    return {
        "commit": commit,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _git_operation_rebase_noninteractive(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    upstream = _normalize_text(args.get("upstream"))
    if not upstream:
        raise ToolDomainError("git rebase_noninteractive requires upstream.")
    timeout_seconds = _parse_positive_int(args.get("timeout_seconds"), default=180)
    command = ["rebase", upstream]
    branch = _normalize_text(args.get("branch"))
    if branch:
        command.append(branch)
    completed = _run_git(
        root=root,
        command=command,
        timeout_seconds=timeout_seconds,
        env_overrides={
            "GIT_SEQUENCE_EDITOR": "true",
            "GIT_EDITOR": "true",
        },
    )
    return {
        "upstream": upstream,
        "branch": branch or None,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _git_operation_tag(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    action = _normalize_operation(args.get("action") or "create")
    timeout_seconds = _parse_positive_int(args.get("timeout_seconds"), default=120)
    if action == "list":
        completed = _run_git(root=root, command=["tag", "--list"], timeout_seconds=timeout_seconds)
        rows = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        return {"action": action, "tags": rows}
    name = _normalize_text(args.get("name"))
    if not name:
        raise ToolDomainError("git tag action requires name.")
    if action == "create":
        target = _normalize_text(args.get("target"))
        message = _normalize_text(args.get("message"))
        command = ["tag"]
        if message:
            command.extend(["-a", name, "-m", message])
        else:
            command.append(name)
        if target:
            command.append(target)
        _run_git(root=root, command=command, timeout_seconds=timeout_seconds)
        return {"action": action, "tag": name, "target": target or "HEAD"}
    if action == "delete":
        _run_git(root=root, command=["tag", "-d", name], timeout_seconds=timeout_seconds)
        return {"action": action, "tag": name}
    if action == "push":
        remote = _normalize_text(args.get("remote")) or "origin"
        _run_git(root=root, command=["push", remote, name], timeout_seconds=timeout_seconds)
        return {"action": action, "tag": name, "remote": remote}
    raise ToolDomainError(f"Unsupported git tag action: {action}")


def _git_operation_dispatch(root: Path, operation: str, args: dict[str, Any]) -> dict[str, Any]:
    if operation == "branch":
        return _git_operation_branch(root, args)
    if operation == "commit":
        return _git_operation_commit(root, args)
    if operation == "push":
        return _git_operation_push(root, args)
    if operation == "pull_request":
        return _git_operation_pull_request(root, args)
    if operation == "cherry_pick":
        return _git_operation_cherry_pick(root, args)
    if operation == "rebase_noninteractive":
        return _git_operation_rebase_noninteractive(root, args)
    if operation == "tag":
        return _git_operation_tag(root, args)
    raise ToolDomainError(f"Unsupported git operation: {operation}")


def run_git_tool(
    *,
    context: ToolDomainContext,
    operation: str,
    args: dict[str, Any] | None = None,
) -> ToolInvocationOutcome:
    normalized_operation = _normalize_operation(operation)
    if normalized_operation not in GIT_OPERATIONS:
        raise ToolDomainError(f"Unsupported git operation: {operation}")
    root = context.resolved_workspace_root()
    payload = dict(args or {})
    return _invoke_domain_tool(
        context=context,
        domain=TOOL_DOMAIN_GIT,
        tool_name=GIT_TOOL_NAME,
        operation=normalized_operation,
        args=payload,
        invoke=lambda: _git_operation_dispatch(root, normalized_operation, payload),
    )


def _artifacts_dir(root: Path) -> Path:
    path = root / ".llmctl" / "tool-artifacts" / "commands"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _command_run(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    command, shell = _parse_command(args.get("command"))
    timeout_seconds = _parse_positive_int(args.get("timeout_seconds"), default=120)
    working_dir = _resolve_workspace_path(root, args.get("cwd"))
    env = os.environ.copy()
    env_overrides = args.get("env")
    if isinstance(env_overrides, dict):
        for key, value in env_overrides.items():
            env[str(key)] = str(value)
    try:
        completed = subprocess.run(
            command[0] if shell else command,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=shell,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolDomainError(
            f"Command timed out after {timeout_seconds} seconds."
        ) from exc
    result: dict[str, Any] = {
        "command": command,
        "shell": shell,
        "cwd": _relative_path(root, working_dir),
        "exit_code": int(completed.returncode),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    if _coerce_bool(args.get("capture_artifacts"), default=True):
        run_id = uuid.uuid4().hex[:12]
        artifact_dir = _artifacts_dir(root) / run_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = artifact_dir / "stdout.log"
        stderr_path = artifact_dir / "stderr.log"
        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8")
        result["artifacts"] = {
            "directory": _relative_path(root, artifact_dir),
            "stdout": _relative_path(root, stdout_path),
            "stderr": _relative_path(root, stderr_path),
        }
    return result


def _build_pty_env(overrides: dict[str, Any] | None) -> dict[str, str]:
    env = os.environ.copy()
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            env[str(key)] = str(value)
    return env


def _command_session_start(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    import pty

    command, shell = _parse_command(args.get("command"))
    working_dir = _resolve_workspace_path(root, args.get("cwd"))
    master_fd, slave_fd = pty.openpty()
    popen_command = command[0] if shell else command
    process = subprocess.Popen(
        popen_command,
        cwd=working_dir,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        shell=shell,
        start_new_session=True,
        env=_build_pty_env(args.get("env")),
    )
    os.close(slave_fd)
    os.set_blocking(master_fd, False)
    session_id = uuid.uuid4().hex
    with _SESSION_LOCK:
        _PTY_SESSIONS[session_id] = _PTYSession(
            session_id=session_id,
            process=process,
            master_fd=master_fd,
            cwd=working_dir,
            started_at=time.time(),
        )
    return {
        "session_id": session_id,
        "pid": process.pid,
        "cwd": _relative_path(root, working_dir),
        "command": command,
        "shell": shell,
    }


def _read_from_master_fd(
    master_fd: int,
    *,
    max_bytes: int,
    wait_ms: int,
) -> str:
    deadline = time.time() + (max(0, wait_ms) / 1000.0)
    chunks: list[bytes] = []
    remaining = max(1, max_bytes)
    while remaining > 0:
        try:
            data = os.read(master_fd, remaining)
        except BlockingIOError:
            if time.time() >= deadline:
                break
            time.sleep(0.01)
            continue
        if not data:
            break
        chunks.append(data)
        remaining -= len(data)
        if time.time() >= deadline:
            break
    return b"".join(chunks).decode("utf-8", errors="replace")


def _command_session_write(_root: Path, args: dict[str, Any]) -> dict[str, Any]:
    session_id = _normalize_text(args.get("session_id"))
    if not session_id:
        raise ToolDomainError("session_write requires session_id.")
    payload = str(args.get("input") or "")
    if _coerce_bool(args.get("append_newline"), default=False):
        payload += "\n"
    with _SESSION_LOCK:
        session = _PTY_SESSIONS.get(session_id)
    if session is None:
        raise ToolDomainError(f"Unknown session_id: {session_id}")
    data = payload.encode("utf-8")
    written = os.write(session.master_fd, data)
    return {
        "session_id": session_id,
        "bytes_written": written,
    }


def _command_session_read(_root: Path, args: dict[str, Any]) -> dict[str, Any]:
    session_id = _normalize_text(args.get("session_id"))
    if not session_id:
        raise ToolDomainError("session_read requires session_id.")
    max_bytes = _parse_positive_int(args.get("max_bytes"), default=8192)
    wait_ms = _parse_positive_int(args.get("wait_ms"), default=0, minimum=0)
    with _SESSION_LOCK:
        session = _PTY_SESSIONS.get(session_id)
    if session is None:
        raise ToolDomainError(f"Unknown session_id: {session_id}")
    output = _read_from_master_fd(session.master_fd, max_bytes=max_bytes, wait_ms=wait_ms)
    exit_code = session.process.poll()
    return {
        "session_id": session_id,
        "output": output,
        "running": exit_code is None,
        "exit_code": exit_code,
    }


def _command_session_stop(_root: Path, args: dict[str, Any]) -> dict[str, Any]:
    session_id = _normalize_text(args.get("session_id"))
    if not session_id:
        raise ToolDomainError("session_stop requires session_id.")
    with _SESSION_LOCK:
        session = _PTY_SESSIONS.pop(session_id, None)
    if session is None:
        return {
            "session_id": session_id,
            "stopped": False,
            "reason": "not_found",
        }
    if session.process.poll() is None:
        if _coerce_bool(args.get("force")):
            session.process.kill()
        else:
            session.process.terminate()
        timeout_seconds = _parse_positive_int(args.get("timeout_seconds"), default=5)
        try:
            session.process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            session.process.kill()
            session.process.wait(timeout=timeout_seconds)
    try:
        os.close(session.master_fd)
    except OSError:
        pass
    return {
        "session_id": session_id,
        "stopped": True,
        "exit_code": session.process.returncode,
    }


def _command_background_start(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    command, shell = _parse_command(args.get("command"))
    working_dir = _resolve_workspace_path(root, args.get("cwd"))
    job_id = uuid.uuid4().hex
    artifact_dir = _artifacts_dir(root) / job_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = artifact_dir / "stdout.log"
    stderr_path = artifact_dir / "stderr.log"
    stdout_handle = stdout_path.open("w", encoding="utf-8")
    stderr_handle = stderr_path.open("w", encoding="utf-8")
    popen_command = command[0] if shell else command
    try:
        process = subprocess.Popen(
            popen_command,
            cwd=working_dir,
            stdout=stdout_handle,
            stderr=stderr_handle,
            shell=shell,
            start_new_session=True,
        )
    finally:
        stdout_handle.close()
        stderr_handle.close()
    job = _BackgroundJob(
        job_id=job_id,
        process=process,
        cwd=working_dir,
        command=command,
        started_at=time.time(),
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )
    with _SESSION_LOCK:
        _BACKGROUND_JOBS[job_id] = job
    return {
        "job_id": job_id,
        "pid": process.pid,
        "cwd": _relative_path(root, working_dir),
        "command": command,
        "shell": shell,
        "artifacts": {
            "directory": _relative_path(root, artifact_dir),
            "stdout": _relative_path(root, stdout_path),
            "stderr": _relative_path(root, stderr_path),
        },
    }


def _tail_text(path: Path, *, max_bytes: int = 4096) -> str:
    if not path.exists():
        return ""
    data = path.read_bytes()
    return data[-max(1, max_bytes) :].decode("utf-8", errors="replace")


def _command_background_status(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    job_id = _normalize_text(args.get("job_id"))
    if not job_id:
        raise ToolDomainError("background_status requires job_id.")
    with _SESSION_LOCK:
        job = _BACKGROUND_JOBS.get(job_id)
    if job is None:
        raise ToolDomainError(f"Unknown job_id: {job_id}")
    exit_code = job.process.poll()
    max_tail = _parse_positive_int(args.get("tail_bytes"), default=4096)
    return {
        "job_id": job_id,
        "running": exit_code is None,
        "exit_code": exit_code,
        "pid": job.process.pid,
        "elapsed_ms": int((time.time() - job.started_at) * 1000),
        "stdout_tail": _tail_text(job.stdout_path, max_bytes=max_tail),
        "stderr_tail": _tail_text(job.stderr_path, max_bytes=max_tail),
        "artifacts": {
            "stdout": _relative_path(root, job.stdout_path),
            "stderr": _relative_path(root, job.stderr_path),
        },
    }


def _command_background_wait(root: Path, args: dict[str, Any]) -> dict[str, Any]:
    job_id = _normalize_text(args.get("job_id"))
    if not job_id:
        raise ToolDomainError("background_wait requires job_id.")
    timeout_seconds = _parse_positive_int(args.get("timeout_seconds"), default=120)
    with _SESSION_LOCK:
        job = _BACKGROUND_JOBS.get(job_id)
    if job is None:
        raise ToolDomainError(f"Unknown job_id: {job_id}")
    try:
        exit_code = job.process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise ToolDomainError(
            f"background_wait timed out after {timeout_seconds} seconds for job {job_id}."
        ) from exc
    max_tail = _parse_positive_int(args.get("tail_bytes"), default=4096)
    return {
        "job_id": job_id,
        "running": False,
        "exit_code": exit_code,
        "stdout_tail": _tail_text(job.stdout_path, max_bytes=max_tail),
        "stderr_tail": _tail_text(job.stderr_path, max_bytes=max_tail),
        "artifacts": {
            "stdout": _relative_path(root, job.stdout_path),
            "stderr": _relative_path(root, job.stderr_path),
        },
    }


def _command_background_stop(_root: Path, args: dict[str, Any]) -> dict[str, Any]:
    job_id = _normalize_text(args.get("job_id"))
    if not job_id:
        raise ToolDomainError("background_stop requires job_id.")
    with _SESSION_LOCK:
        job = _BACKGROUND_JOBS.pop(job_id, None)
    if job is None:
        return {
            "job_id": job_id,
            "stopped": False,
            "reason": "not_found",
        }
    if job.process.poll() is None:
        sig = signal.SIGKILL if _coerce_bool(args.get("force")) else signal.SIGTERM
        job.process.send_signal(sig)
        timeout_seconds = _parse_positive_int(args.get("timeout_seconds"), default=5)
        try:
            job.process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            job.process.kill()
            job.process.wait(timeout=timeout_seconds)
    return {
        "job_id": job_id,
        "stopped": True,
        "exit_code": job.process.returncode,
    }


def _read_mem_total_bytes() -> int | None:
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if not line.startswith("MemTotal:"):
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                return int(parts[1]) * 1024
    except (OSError, ValueError):
        return None
    return None


def _normalize_rlimit_value(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def _command_resource_limits(_root: Path, _args: dict[str, Any]) -> dict[str, Any]:
    limits: dict[str, dict[str, int | None]] = {}
    try:
        import resource
    except ImportError:  # pragma: no cover - non-POSIX environments only
        resource = None  # type: ignore[assignment]
    if resource is not None:
        for key, label in (
            ("RLIMIT_CPU", "cpu_seconds"),
            ("RLIMIT_AS", "virtual_memory_bytes"),
            ("RLIMIT_DATA", "data_segment_bytes"),
            ("RLIMIT_FSIZE", "file_size_bytes"),
            ("RLIMIT_NOFILE", "open_files"),
        ):
            if not hasattr(resource, key):
                continue
            soft, hard = resource.getrlimit(getattr(resource, key))
            limits[label] = {
                "soft": _normalize_rlimit_value(soft),
                "hard": _normalize_rlimit_value(hard),
            }
    return {
        "cpu_count": int(os.cpu_count() or 1),
        "memory_total_bytes": _read_mem_total_bytes(),
        "limits": limits,
    }


def _command_operation_dispatch(root: Path, operation: str, args: dict[str, Any]) -> dict[str, Any]:
    if operation == "run":
        return _command_run(root, args)
    if operation == "session_start":
        return _command_session_start(root, args)
    if operation == "session_write":
        return _command_session_write(root, args)
    if operation == "session_read":
        return _command_session_read(root, args)
    if operation == "session_stop":
        return _command_session_stop(root, args)
    if operation == "background_start":
        return _command_background_start(root, args)
    if operation == "background_status":
        return _command_background_status(root, args)
    if operation == "background_wait":
        return _command_background_wait(root, args)
    if operation == "background_stop":
        return _command_background_stop(root, args)
    if operation == "resource_limits":
        return _command_resource_limits(root, args)
    raise ToolDomainError(f"Unsupported command operation: {operation}")


def run_command_tool(
    *,
    context: ToolDomainContext,
    operation: str,
    args: dict[str, Any] | None = None,
) -> ToolInvocationOutcome:
    normalized_operation = _normalize_operation(operation)
    if normalized_operation not in COMMAND_OPERATIONS:
        raise ToolDomainError(f"Unsupported command operation: {operation}")
    root = context.resolved_workspace_root()
    payload = dict(args or {})
    return _invoke_domain_tool(
        context=context,
        domain=TOOL_DOMAIN_COMMAND,
        tool_name=COMMAND_TOOL_NAME,
        operation=normalized_operation,
        args=payload,
        invoke=lambda: _command_operation_dispatch(root, normalized_operation, payload),
    )


def _normalize_rag_index_mode(value: Any) -> str:
    cleaned = _normalize_text(value).lower()
    if cleaned in {"fresh_index", "full", "fresh"}:
        return RAG_FLOWCHART_MODE_FRESH_INDEX
    if cleaned in {"delta_index", "delta"}:
        return RAG_FLOWCHART_MODE_DELTA_INDEX
    raise ToolDomainError(
        "RAG index mode must be one of: full, fresh_index, delta, delta_index."
    )


def _rag_operation_index(_root: Path, args: dict[str, Any]) -> dict[str, Any]:
    mode = _normalize_rag_index_mode(args.get("mode"))
    collections = args.get("collections")
    if not isinstance(collections, list):
        raise ToolDomainError("rag index requires collections list.")
    model_provider = _normalize_text(args.get("model_provider")) or "codex"
    logs: list[str] = []
    summary = run_index_for_collections(
        mode=mode,
        collections=[str(item) for item in collections],
        model_provider=model_provider,
        on_log=lambda message: logs.append(str(message)),
    )
    return {
        "mode": summary.get("mode"),
        "collections": list(summary.get("collections") or []),
        "source_count": int(summary.get("source_count") or 0),
        "total_files": int(summary.get("total_files") or 0),
        "total_chunks": int(summary.get("total_chunks") or 0),
        "sources": list(summary.get("sources") or []),
        "logs": logs,
    }


def _rag_operation_query(_root: Path, args: dict[str, Any]) -> dict[str, Any]:
    question = str(args.get("question") or "")
    collections = args.get("collections")
    if not isinstance(collections, list):
        raise ToolDomainError("rag query requires collections list.")
    top_k = _parse_positive_int(args.get("top_k"), default=5)
    response = execute_query_contract(
        question=question,
        collections=[str(item) for item in collections],
        top_k=top_k,
        request_id=_normalize_text(args.get("request_id")) or None,
        runtime_kind=_normalize_text(args.get("runtime_kind")) or "flowchart",
        flowchart_run_id=args.get("flowchart_run_id"),
        flowchart_node_run_id=args.get("flowchart_node_run_id"),
    )
    return {
        "mode": str(response.get("mode") or "query"),
        "answer": response.get("answer"),
        "collections": list(response.get("collections") or []),
        "retrieval_context": list(response.get("retrieval_context") or []),
        "retrieval_stats": dict(response.get("retrieval_stats") or {}),
        "citation_records": list(response.get("citation_records") or []),
        "synthesis_error": response.get("synthesis_error"),
    }


def _rag_operation_dispatch(root: Path, operation: str, args: dict[str, Any]) -> dict[str, Any]:
    if operation == "index":
        return _rag_operation_index(root, args)
    if operation == "query":
        return _rag_operation_query(root, args)
    raise ToolDomainError(f"Unsupported rag operation: {operation}")


def run_rag_tool(
    *,
    context: ToolDomainContext,
    operation: str,
    args: dict[str, Any] | None = None,
) -> ToolInvocationOutcome:
    normalized_operation = _normalize_operation(operation)
    if normalized_operation not in RAG_OPERATIONS:
        raise ToolDomainError(f"Unsupported rag operation: {operation}")
    root = context.resolved_workspace_root()
    payload = dict(args or {})
    return _invoke_domain_tool(
        context=context,
        domain=TOOL_DOMAIN_RAG,
        tool_name=RAG_TOOL_NAME,
        operation=normalized_operation,
        args=payload,
        invoke=lambda: _rag_operation_dispatch(root, normalized_operation, payload),
    )
