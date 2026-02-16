#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    src_path = repo_root / "app" / "llmctl-executor" / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
    os.chdir(repo_root)

    from llmctl_executor.cli import main as cli_main

    return int(cli_main())


if __name__ == "__main__":
    raise SystemExit(main())
