#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    studio_src = repo_root / "app" / "llmctl-studio-backend" / "src"
    mcp_src = repo_root / "app" / "llmctl-mcp" / "src"
    sys.path.insert(0, str(studio_src))
    sys.path.insert(0, str(mcp_src))
    os.chdir(repo_root)

    from app import run

    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
