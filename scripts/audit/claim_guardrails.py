#!/usr/bin/env python3
"""Hard gates for invariant claim closure evidence."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ALLOWED_STATUS = {"pass", "fail", "insufficient_evidence"}
TEST_ANCHOR_RE = re.compile(r"\bdef\s+test_|\bit\s*\(|\btest\s*\(")
REFERENCE_RE = re.compile(r"([A-Za-z0-9_./-]+):(\d+)")
MARKDOWN_DIVIDER_RE = re.compile(r"^:?-{3,}:?$")


@dataclass(frozen=True)
class TableRow:
    line_number: int
    values: dict[str, str]


@dataclass(frozen=True)
class EvidenceRef:
    path: str
    line: int


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _strip_ticks(value: str) -> str:
    return value.strip().strip("`").strip()


def parse_markdown_table(path: Path, required_columns: set[str]) -> list[TableRow]:
    if not path.exists():
        raise FileNotFoundError(f"Missing markdown table file: {path}")

    headers: list[str] | None = None
    rows: list[TableRow] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line.startswith("|") or line.count("|") < 3:
            continue

        parts = [part.strip() for part in line.strip("|").split("|")]
        normalized_parts = [part.lower() for part in parts]
        if headers is None and set(required_columns).issubset(set(normalized_parts)):
            headers = normalized_parts
            continue

        if headers is None:
            continue
        if all(MARKDOWN_DIVIDER_RE.match(part) for part in parts):
            continue
        if len(parts) != len(headers):
            continue

        values = {headers[index]: parts[index] for index in range(len(headers))}
        rows.append(TableRow(line_number=line_number, values=values))

    if headers is None:
        required = ", ".join(sorted(required_columns))
        raise ValueError(f"Unable to find markdown table with required columns ({required}) in {path}")
    return rows


def parse_evidence_refs(raw_value: str) -> list[EvidenceRef]:
    value = _strip_ticks(raw_value)
    if not value or value.upper() == "TBD":
        return []
    seen: set[tuple[str, int]] = set()
    refs: list[EvidenceRef] = []
    for path_text, line_text in REFERENCE_RE.findall(value):
        item = (path_text, int(line_text))
        if item in seen:
            continue
        seen.add(item)
        refs.append(EvidenceRef(path=item[0], line=item[1]))
    return refs


def _resolve(root: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else root / path


def _is_test_path(raw_path: str) -> bool:
    normalized = raw_path.replace("\\", "/")
    name = Path(normalized).name.lower()
    return (
        "/tests/" in normalized
        or name.startswith("test_")
        or ".test." in name
    )


def _is_static_code_path(raw_path: str) -> bool:
    normalized = raw_path.replace("\\", "/")
    if normalized.startswith("docs/"):
        return False
    if _is_test_path(normalized):
        return False
    return True


def _valid_file_line(path: Path, line_number: int) -> bool:
    if line_number < 1 or not path.exists() or not path.is_file():
        return False
    return line_number <= len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def _has_runtime_test_anchor(path: Path, line_number: int) -> bool:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    lower = max(1, line_number - 40)
    upper = min(len(lines), line_number + 40)
    for index in range(lower, upper + 1):
        if TEST_ANCHOR_RE.search(lines[index - 1]):
            return True
    return False


def run_guardrails(*, matrix_path: Path, inventory_path: Path, repo_root: Path) -> list[str]:
    matrix_rows = parse_markdown_table(
        matrix_path,
        {"claim_id", "invariant", "code_evidence", "test_evidence", "status"},
    )
    inventory_rows = parse_markdown_table(inventory_path, {"claim_id"})
    inventory_claim_ids = {_strip_ticks(row.values["claim_id"]) for row in inventory_rows}

    failures: list[str] = []
    for row in matrix_rows:
        claim_id = _strip_ticks(row.values.get("claim_id", ""))
        status = _strip_ticks(row.values.get("status", "")).lower()
        invariant = _strip_ticks(row.values.get("invariant", "")).lower()
        code_refs = parse_evidence_refs(row.values.get("code_evidence", ""))
        test_refs = parse_evidence_refs(row.values.get("test_evidence", ""))

        if status not in ALLOWED_STATUS:
            failures.append(
                f"{matrix_path}:{row.line_number} {claim_id}: invalid status '{status}' (allowed: pass/fail/insufficient_evidence)."
            )
            continue

        if claim_id not in inventory_claim_ids:
            failures.append(
                f"{matrix_path}:{row.line_number} {claim_id}: missing inventory linkage in {inventory_path}."
            )

        if invariant != "yes" or status != "pass":
            continue

        valid_static = False
        for ref in code_refs:
            resolved = _resolve(repo_root, ref.path)
            if _valid_file_line(resolved, ref.line) and _is_static_code_path(ref.path):
                valid_static = True
                break
        if not code_refs:
            failures.append(
                f"{matrix_path}:{row.line_number} {claim_id}: invariant pass is missing static code evidence references."
            )
        elif not valid_static:
            failures.append(
                f"{matrix_path}:{row.line_number} {claim_id}: invariant pass static evidence must resolve to non-doc, non-test code with valid lines."
            )

        valid_runtime = False
        for ref in test_refs:
            resolved = _resolve(repo_root, ref.path)
            if not _valid_file_line(resolved, ref.line):
                continue
            if not _is_test_path(ref.path):
                continue
            if _has_runtime_test_anchor(resolved, ref.line):
                valid_runtime = True
                break
        if not test_refs:
            failures.append(
                f"{matrix_path}:{row.line_number} {claim_id}: invariant pass is missing runtime test evidence references."
            )
        elif not valid_runtime:
            failures.append(
                f"{matrix_path}:{row.line_number} {claim_id}: missing claim-to-test linkage (no valid runtime test anchor near referenced test evidence)."
            )

    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail invariant pass claims that are missing static+runtime evidence or claim-to-test linkage."
        )
    )
    parser.add_argument(
        "--matrix",
        default="docs/planning/active/RUNTIME_MIGRATION_CLAIM_EVIDENCE_MATRIX.md",
        help="Path to the claim evidence matrix markdown file.",
    )
    parser.add_argument(
        "--inventory",
        default="docs/planning/active/RUNTIME_MIGRATION_CLAIM_INVENTORY.md",
        help="Path to the claim inventory markdown file.",
    )
    parser.add_argument(
        "--repo-root",
        default=str(_repo_root()),
        help="Repository root used to resolve relative evidence paths.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    matrix_path = _resolve(repo_root, args.matrix)
    inventory_path = _resolve(repo_root, args.inventory)
    failures = run_guardrails(
        matrix_path=matrix_path,
        inventory_path=inventory_path,
        repo_root=repo_root,
    )

    if failures:
        print("Claim guardrails failed.")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Claim guardrails passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
