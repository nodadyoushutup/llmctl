#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    studio_src = repo_root / "app" / "llmctl-studio" / "src"
    mcp_root = repo_root / "app" / "llmctl-mcp"
    sys.path.insert(0, str(studio_src))
    sys.path.insert(0, str(mcp_root))
    os.chdir(repo_root)

    from server import run

    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
