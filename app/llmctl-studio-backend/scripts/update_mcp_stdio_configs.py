#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select


def _bootstrap() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    studio_src = repo_root / "app" / "llmctl-studio-backend" / "src"
    sys.path.insert(0, str(studio_src))
    os.chdir(repo_root)


def _build_target_configs(use_llmctl_tap: bool) -> dict[str, dict[str, object]]:
    repo_root = Path(__file__).resolve().parents[3]
    chroma_wrapper = (
        repo_root / "app" / "llmctl-studio-backend" / "src" / "core" / "chroma_mcp_stdio_wrapper.py"
    )
    return {
        "chroma": {
            "command": "python3",
            "args": [
                str(chroma_wrapper),
                "--client-type",
                "http",
                "--host",
                "llmctl-chromadb",
                "--port",
                "8000",
                "--ssl",
                "false",
            ],
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update MCP server configs to stdio command/args.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes to the database (default is dry-run).",
    )
    parser.add_argument(
        "--server",
        action="append",
        choices=sorted(_build_target_configs(False).keys()),
        help="Limit to a specific server key (repeatable).",
    )
    parser.add_argument(
        "--llmctl-stdio-tap",
        action="store_true",
        help="No-op retained for compatibility.",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        help="Print the rendered config JSON for each target server.",
    )
    return parser.parse_args()


def main() -> int:
    _bootstrap()
    args = _parse_args()

    from core.config import Config
    from core.db import create_session, init_db, init_engine
    from core.mcp_config import parse_mcp_config, render_mcp_config
    from core.models import MCPServer

    init_engine(Config.SQLALCHEMY_DATABASE_URI)
    init_db()

    target_configs = _build_target_configs(args.llmctl_stdio_tap)
    target_keys = args.server or sorted(target_configs.keys())

    def update_session(session) -> list[str]:
        servers = (
            session.execute(
                select(MCPServer).where(MCPServer.server_key.in_(target_keys))
            )
            .scalars()
            .all()
        )
        by_key = {server.server_key: server for server in servers}
        updated: list[str] = []
        for server_key in target_keys:
            target = target_configs[server_key]
            row = by_key.get(server_key)
            if row is None:
                print(f"Skipping {server_key}: not found in DB.")
                continue
            try:
                current = parse_mcp_config(row.config_json, server_key=server_key)
            except Exception as exc:
                print(f"Skipping {server_key}: invalid config ({exc}).")
                continue
            next_config = dict(current)
            next_config.pop("url", None)
            next_config.pop("transport", None)
            next_config.pop("gemini_transport", None)
            next_config["command"] = target["command"]
            next_config["args"] = target["args"]
            rendered = render_mcp_config(server_key, next_config)
            if rendered == row.config_json:
                print(f"No change for {server_key}.")
                if args.print:
                    print(json.dumps(rendered, indent=2, sort_keys=True))
                continue
            print(f"Updating {server_key}.")
            if args.print:
                print(json.dumps(rendered, indent=2, sort_keys=True))
            if args.apply:
                row.config_json = rendered
                row.updated_at = datetime.now(timezone.utc)
            updated.append(server_key)
        return updated

    session = create_session()
    try:
        updated = update_session(session)
        if args.apply:
            session.commit()
        else:
            session.rollback()
    finally:
        session.close()
    print(json.dumps({"applied": bool(args.apply), "updated": updated}, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
