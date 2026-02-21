#!/usr/bin/env python3
"""Fail when frontier runtime paths shell out to codex/gemini/claude binaries."""

from __future__ import annotations

import argparse
import ast
import glob
import re
import sys
from dataclasses import dataclass
from pathlib import Path

FORBIDDEN_BINARIES = {"codex", "gemini", "claude"}
SUBPROCESS_CALLS = {"run", "Popen", "call", "check_call", "check_output"}
HELPER_CALLS = {"_run_subprocess", "_run_command", "run_subprocess", "run_command"}
COMMAND_KEYWORDS = {"args", "command", "cmd"}
COMMAND_VAR_RE = re.compile(r"(?:^|_)(?:cmd|command|argv|args)$", re.IGNORECASE)

DEFAULT_PATH_GLOBS = (
    "app/llmctl-studio-backend/src/services/tasks.py",
    "app/llmctl-studio-backend/src/services/execution/*.py",
    "app/llmctl-studio-backend/src/services/execution/**/*.py",
)


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    binary: str
    reason: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _normalize_token(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    if not cleaned:
        return None
    return cleaned


def _first_command_token(expr: ast.AST) -> str | None:
    if isinstance(expr, ast.Constant):
        return _normalize_token(expr.value)
    if isinstance(expr, (ast.List, ast.Tuple)) and expr.elts:
        first = expr.elts[0]
        if isinstance(first, ast.Constant):
            return _normalize_token(first.value)
    return None


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_command_invocation(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute):
        if isinstance(func.value, ast.Name) and func.value.id == "subprocess":
            return func.attr in SUBPROCESS_CALLS
        return False
    if isinstance(func, ast.Name):
        return func.id in HELPER_CALLS
    return False


class RuntimeCliGuardrailVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.violations: list[Violation] = []
        self._scope_stack: list[dict[str, str]] = [{}]

    def _push_scope(self) -> None:
        self._scope_stack.append({})

    def _pop_scope(self) -> None:
        self._scope_stack.pop()

    def _record_command_var(self, target: ast.expr, token: str) -> None:
        if not isinstance(target, ast.Name):
            return
        if not COMMAND_VAR_RE.search(target.id):
            return
        self._scope_stack[-1][target.id] = token

    def _resolve_name_token(self, name: str) -> str | None:
        for scope in reversed(self._scope_stack):
            token = scope.get(name)
            if token:
                return token
        return None

    def _token_from_expr(self, expr: ast.AST) -> str | None:
        direct = _first_command_token(expr)
        if direct:
            return direct
        if isinstance(expr, ast.Name):
            return self._resolve_name_token(expr.id)
        return None

    def _check_candidate_expr(self, *, call: ast.Call, candidate: ast.AST, reason: str) -> None:
        token = self._token_from_expr(candidate)
        if token in FORBIDDEN_BINARIES:
            self.violations.append(
                Violation(
                    path=self.path,
                    line=call.lineno,
                    binary=token,
                    reason=reason,
                )
            )

    def _check_command_call(self, node: ast.Call) -> None:
        if node.args:
            self._check_candidate_expr(call=node, candidate=node.args[0], reason="positional command argument")
        for keyword in node.keywords:
            if keyword.arg in COMMAND_KEYWORDS:
                self._check_candidate_expr(
                    call=node,
                    candidate=keyword.value,
                    reason=f"keyword command argument '{keyword.arg}'",
                )

    def visit_Assign(self, node: ast.Assign) -> None:
        token = _first_command_token(node.value)
        if token:
            for target in node.targets:
                self._record_command_var(target, token)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            token = _first_command_token(node.value)
            if token:
                self._record_command_var(node.target, token)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if _is_command_invocation(node):
            self._check_command_call(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._push_scope()
        self.generic_visit(node)
        self._pop_scope()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._push_scope()
        self.generic_visit(node)
        self._pop_scope()

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._push_scope()
        self.generic_visit(node)
        self._pop_scope()


def _resolve_paths(repo_root: Path, path_patterns: list[str] | None) -> list[Path]:
    patterns = path_patterns if path_patterns else list(DEFAULT_PATH_GLOBS)
    resolved: set[Path] = set()
    for raw_pattern in patterns:
        pattern = raw_pattern.strip()
        if not pattern:
            continue
        if any(ch in pattern for ch in "*?[]"):
            if Path(pattern).is_absolute():
                matches = [Path(item) for item in glob.glob(pattern, recursive=True)]
            else:
                matches = [Path(item) for item in repo_root.glob(pattern)]
            for matched in matches:
                if matched.is_file():
                    resolved.add(matched.resolve())
            continue
        candidate = Path(pattern)
        if not candidate.is_absolute():
            candidate = repo_root / candidate
        if candidate.is_file():
            resolved.add(candidate.resolve())
    return sorted(resolved)


def scan_file(path: Path) -> list[Violation]:
    try:
        source = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [Violation(path=path, line=1, binary="", reason="file does not exist")]
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [
            Violation(
                path=path,
                line=exc.lineno or 1,
                binary="",
                reason=f"failed to parse python source: {exc.msg}",
            )
        ]
    visitor = RuntimeCliGuardrailVisitor(path)
    visitor.visit(tree)
    return visitor.violations


def run_guardrail(*, repo_root: Path, paths: list[str] | None = None) -> list[str]:
    target_paths = _resolve_paths(repo_root, paths)
    if not target_paths:
        return ["No runtime source files matched guardrail path patterns."]

    failures: list[str] = []
    for path in target_paths:
        for violation in scan_file(path):
            rel = violation.path.resolve().relative_to(repo_root.resolve())
            if violation.binary:
                failures.append(
                    f"{rel}:{violation.line}: forbidden frontier CLI binary '{violation.binary}' in command execution path ({violation.reason})."
                )
            else:
                failures.append(f"{rel}:{violation.line}: {violation.reason}.")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail when runtime command execution paths directly invoke codex/gemini/claude binaries."
        )
    )
    parser.add_argument(
        "--repo-root",
        default=str(_repo_root()),
        help="Repository root used to resolve relative paths.",
    )
    parser.add_argument(
        "--path",
        action="append",
        dest="paths",
        default=None,
        help="Override guardrail scan path/glob (repeatable). Defaults to runtime service paths.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    failures = run_guardrail(repo_root=repo_root, paths=args.paths)

    if failures:
        print("Frontier CLI runtime guardrail failed.")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Frontier CLI runtime guardrail passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
