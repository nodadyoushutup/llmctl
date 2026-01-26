#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path


def _bootstrap() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    studio_src = repo_root / "app" / "llmctl-studio" / "src"
    sys.path.insert(0, str(studio_src))
    os.chdir(repo_root)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print parsed MCP server configs from the database.",
    )
    parser.add_argument(
        "--server",
        action="append",
        help="Limit to a specific server key (repeatable).",
    )
    return parser.parse_args()


def main() -> int:
    _bootstrap()
    args = _parse_args()

    from core.config import Config
    from core.mcp_config import parse_mcp_config

    db_url = Config.SQLALCHEMY_DATABASE_URI
    if not db_url.startswith("sqlite:///"):
        raise RuntimeError("Only sqlite:/// URLs are supported by this script.")
    db_path = db_url[len("sqlite:///") :]

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        payload = {}
        if args.server:
            placeholders = ", ".join("?" for _ in args.server)
            rows = conn.execute(
                f"SELECT server_key, config_json FROM mcp_servers "
                f"WHERE server_key IN ({placeholders})",
                tuple(args.server),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT server_key, config_json FROM mcp_servers"
            ).fetchall()
        for row in rows:
            try:
                payload[row["server_key"]] = parse_mcp_config(
                    row["config_json"], server_key=row["server_key"]
                )
            except Exception as exc:
                payload[row["server_key"]] = {"error": str(exc)}
        print(json.dumps(payload, indent=2, sort_keys=True))
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
