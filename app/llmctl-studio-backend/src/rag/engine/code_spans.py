from __future__ import annotations

import ast
import re
from typing import Iterable


def _slice_lines(lines: list[str], start_line: int, end_line: int) -> str:
    start_idx = max(0, start_line - 1)
    end_idx = max(start_idx, end_line)
    return "".join(lines[start_idx:end_idx])


def python_spans(text: str) -> list[dict[str, object]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    lines = text.splitlines(keepends=True)
    spans: list[dict[str, object]] = []

    if tree.body and isinstance(tree.body[0], ast.Expr):
        value = getattr(tree.body[0], "value", None)
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            start_line = getattr(tree.body[0], "lineno", None)
            end_line = getattr(tree.body[0], "end_lineno", None)
            if start_line and end_line:
                spans.append(
                    {
                        "text": _slice_lines(lines, start_line, end_line),
                        "start_line": start_line,
                        "end_line": end_line,
                        "metadata": {
                            "symbol": "__module_docstring__",
                            "symbol_type": "module_docstring",
                        },
                    }
                )

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            symbol_type = "class"
        elif isinstance(node, ast.FunctionDef):
            symbol_type = "function"
        elif isinstance(node, ast.AsyncFunctionDef):
            symbol_type = "async_function"
        else:
            continue

        start_line = getattr(node, "lineno", None)
        end_line = getattr(node, "end_lineno", None)
        if not start_line or not end_line:
            continue

        spans.append(
            {
                "text": _slice_lines(lines, start_line, end_line),
                "start_line": start_line,
                "end_line": end_line,
                "metadata": {
                    "symbol": getattr(node, "name", "<unknown>"),
                    "symbol_type": symbol_type,
                },
            }
        )

    spans.sort(key=lambda item: (item.get("start_line") or 0, item.get("end_line") or 0))
    return spans


_JS_FUNC_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"
)
_JS_CLASS_RE = re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)")
_JS_ARROW_RE = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>"
)
_JS_FUNC_EXPR_RE = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?function\b"
)


def _brace_span(lines: list[str], start_idx: int) -> int:
    opened = 0
    saw_open = False
    for idx in range(start_idx, len(lines)):
        line = lines[idx]
        for ch in line:
            if ch == "{":
                opened += 1
                saw_open = True
            elif ch == "}":
                opened -= 1
            if saw_open and opened <= 0:
                return idx
    return start_idx


def js_ts_spans(text: str) -> list[dict[str, object]]:
    lines = text.splitlines(keepends=True)
    spans: list[dict[str, object]] = []

    for idx, line in enumerate(lines):
        name = None
        symbol_type = None
        match = _JS_FUNC_RE.match(line)
        if match:
            name = match.group(1)
            symbol_type = "function"
        else:
            match = _JS_CLASS_RE.match(line)
            if match:
                name = match.group(1)
                symbol_type = "class"
            else:
                match = _JS_ARROW_RE.match(line)
                if match:
                    name = match.group(1)
                    symbol_type = "arrow_function"
                else:
                    match = _JS_FUNC_EXPR_RE.match(line)
                    if match:
                        name = match.group(1)
                        symbol_type = "function_expression"

        if not match:
            continue

        end_idx = _brace_span(lines, idx)
        spans.append(
            {
                "text": _slice_lines(lines, idx + 1, end_idx + 1),
                "start_line": idx + 1,
                "end_line": end_idx + 1,
                "metadata": {
                    "symbol": name or "<unknown>",
                    "symbol_type": symbol_type or "symbol",
                },
            }
        )

    spans.sort(key=lambda item: (item.get("start_line") or 0, item.get("end_line") or 0))
    return spans


_BASH_FUNC_RE = re.compile(
    r"^\s*(?:function\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\(\)"
)


def _brace_span_simple(lines: list[str], start_idx: int) -> int:
    opened = 0
    saw_open = False
    for idx in range(start_idx, len(lines)):
        line = lines[idx]
        for ch in line:
            if ch == "{":
                opened += 1
                saw_open = True
            elif ch == "}":
                opened -= 1
            if saw_open and opened <= 0:
                return idx
    return start_idx


def bash_spans(text: str) -> list[dict[str, object]]:
    lines = text.splitlines(keepends=True)
    spans: list[dict[str, object]] = []

    for idx, line in enumerate(lines):
        match = _BASH_FUNC_RE.match(line)
        if not match:
            continue
        name = match.group(1)
        end_idx = _brace_span_simple(lines, idx)
        spans.append(
            {
                "text": _slice_lines(lines, idx + 1, end_idx + 1),
                "start_line": idx + 1,
                "end_line": end_idx + 1,
                "metadata": {
                    "symbol": name,
                    "symbol_type": "function",
                },
            }
        )

    spans.sort(key=lambda item: (item.get("start_line") or 0, item.get("end_line") or 0))
    return spans


_SHEBANG_RE = re.compile(r"^#!\s*(.+)$")


def detect_language(text: str) -> str | None:
    lines = text.splitlines()
    if not lines:
        return None
    first = lines[0].strip()
    match = _SHEBANG_RE.match(first)
    if match:
        value = match.group(1)
        if "python" in value:
            return "python"
        if "bash" in value or value.endswith("/sh") or " zsh" in value:
            return "bash"
        if "node" in value or "deno" in value:
            return "javascript"

    if re.search(r"^\s*def\s+\w+\s*\(", text, re.MULTILINE):
        return "python"
    if re.search(r"^\s*class\s+\w+\s*:\s*$", text, re.MULTILINE):
        return "python"
    if re.search(r"^\s*function\s+\w+\s*\(", text, re.MULTILINE):
        return "javascript"
    if re.search(r"^\s*\w+\(\)\s*\{", text, re.MULTILINE):
        return "bash"

    return None


def spans_for_language(language: str, text: str) -> list[dict[str, object]]:
    if language == "python":
        return python_spans(text)
    if language in {"javascript", "typescript"}:
        return js_ts_spans(text)
    if language in {"bash", "shell", "sh", "zsh"}:
        return bash_spans(text)
    return []
