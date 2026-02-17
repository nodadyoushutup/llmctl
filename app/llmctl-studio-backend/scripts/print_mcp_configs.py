#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from sqlalchemy import select


def _bootstrap() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    studio_src = repo_root / "app" / "llmctl-studio-backend" / "src"
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
    from core.db import init_db, init_engine, session_scope
    from core.mcp_config import parse_mcp_config
    from core.models import MCPServer

    init_engine(Config.SQLALCHEMY_DATABASE_URI)
    init_db()

    with session_scope() as session:
        query = select(MCPServer.server_key, MCPServer.config_json)
        if args.server:
            query = query.where(MCPServer.server_key.in_(args.server))
        rows = session.execute(query.order_by(MCPServer.server_key.asc())).all()

        payload = {}
        for server_key, config_json in rows:
            try:
                payload[server_key] = parse_mcp_config(
                    config_json, server_key=server_key
                )
            except Exception as exc:
                payload[server_key] = {"error": str(exc)}
        print(json.dumps(payload, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
