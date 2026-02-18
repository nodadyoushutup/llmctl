#!/usr/bin/env python3
"""Guardrail check for Studio page notification usage.

This check flags page components that appear to emit local notification-like
state updates (`set*Error`, `set*Message`, `set*Info`, `set*Warning`) without
using the shared flash message hooks.

Opt-out for rare exceptions by adding this comment in the file:
  flash-guardrail: allow-local-notification
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
PAGES_DIR = ROOT / "app" / "llmctl-studio-frontend" / "src" / "pages"

SETTER_PATTERN = re.compile(r"\bset[A-Za-z0-9_]*(Error|Message|Info|Warning)\s*\(")
FLASH_PATTERN = re.compile(r"\buseFlashState\b|\buseFlash\s*\(")
ALLOW_MARKER = "flash-guardrail: allow-local-notification"


def main() -> int:
    if not PAGES_DIR.exists():
        print(f"error: pages directory not found: {PAGES_DIR}", file=sys.stderr)
        return 2

    offenders: list[pathlib.Path] = []
    for path in sorted(PAGES_DIR.rglob("*.jsx")):
        text = path.read_text(encoding="utf-8")
        if ALLOW_MARKER in text:
            continue
        if not SETTER_PATTERN.search(text):
            continue
        if FLASH_PATTERN.search(text):
            continue
        offenders.append(path)

    if offenders:
        print("Flash notification guardrail failed.\n")
        print("The following pages use local notification-like setters without flash hooks:")
        for path in offenders:
            print(f"- {path.relative_to(ROOT)}")
        print("\nUse useFlash/useFlashState or document an exception with:")
        print(f"  {ALLOW_MARKER}")
        return 1

    print("Flash notification guardrail passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
