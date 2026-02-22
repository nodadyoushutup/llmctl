#!/usr/bin/env python3
"""Guardrail check for legacy Studio header variants.

This check blocks reintroduction of deprecated header class variants that were
replaced by shared compact header primitives.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND_SRC = ROOT / "app" / "llmctl-studio-frontend" / "src"

FORBIDDEN_PATTERNS = {
    "card-header": re.compile(r"\bcard-header\b"),
    "provider-settings-header": re.compile(r"\bprovider-settings-header\b"),
    "topbar": re.compile(r"\btopbar\b"),
    "topbar-row": re.compile(r"\btopbar-row\b"),
    "chat-panel-header": re.compile(r"\bchat-panel-header\b"),
    "chat-main-topbar": re.compile(r"\bchat-main-topbar\b"),
    "chat-main-title": re.compile(r"\bchat-main-title\b"),
    "chat-main-actions": re.compile(r"\bchat-main-actions\b"),
    "chat-main-usage": re.compile(r"\bchat-main-usage\b"),
    "chat-threads-header": re.compile(r"\bchat-threads-header\b"),
}

SCAN_EXTENSIONS = (".jsx", ".css")


def iter_source_files(base: pathlib.Path) -> list[pathlib.Path]:
    paths: list[pathlib.Path] = []
    for ext in SCAN_EXTENSIONS:
        paths.extend(sorted(base.rglob(f"*{ext}")))
    return paths


def main() -> int:
    if not FRONTEND_SRC.exists():
        print(f"error: frontend source path not found: {FRONTEND_SRC}", file=sys.stderr)
        return 2

    failures: list[tuple[pathlib.Path, str]] = []
    for path in iter_source_files(FRONTEND_SRC):
        text = path.read_text(encoding="utf-8")
        for label, pattern in FORBIDDEN_PATTERNS.items():
            if pattern.search(text):
                failures.append((path, label))

    if failures:
        print("Header consistency guardrail failed.\n")
        print("Deprecated header variants found:")
        for path, label in failures:
            print(f"- {path.relative_to(ROOT)} ({label})")
        print("\nUse shared header primitives (for example `PanelHeader`) instead.")
        return 1

    print("Header consistency guardrail passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
