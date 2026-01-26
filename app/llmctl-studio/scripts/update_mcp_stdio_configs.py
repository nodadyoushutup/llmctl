#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def _bootstrap() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    studio_src = repo_root / "app" / "llmctl-studio" / "src"
    sys.path.insert(0, str(studio_src))
    os.chdir(repo_root)


def _build_target_configs(use_llmctl_tap: bool) -> dict[str, dict[str, object]]:
    llmctl_args: list[str] = [
        "exec",
        "-i",
        "llmctl-mcp",
        "env",
        "LLMCTL_MCP_TRANSPORT=stdio",
        "python3",
        "app/llmctl-mcp/run.py",
    ]
    if use_llmctl_tap:
        llmctl_args = [
            "exec",
            "-i",
            "llmctl-mcp",
            "python3",
            "app/llmctl-mcp/scripts/mcp_stdio_tap.py",
            "--log",
            "/app/data/mcp-stdio-tap.log",
            "--",
            *llmctl_args[3:],
        ]
    return {
        "github": {
            "command": "docker",
            "args": [
                "exec",
                "-i",
                "github-mcp",
                "/server/github-mcp-server",
                "stdio",
            ],
        },
        "jira": {
            "command": "docker",
            "args": ["exec", "-i", "jira-mcp", "mcp-atlassian", "--transport", "stdio"],
        },
        "chroma": {
            "command": "docker",
            "args": [
                "exec",
                "-i",
                "chromadb-mcp",
                "chromadb-mcp",
                "--client-type",
                "http",
                "--host",
                "chromadb",
                "--port",
                "8000",
                "--ssl",
                "false",
            ],
        },
        "llmctl-mcp": {
            "command": "docker",
            "args": llmctl_args,
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
        help="Wrap llmctl-mcp stdio command with mcp_stdio_tap.py logging.",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        help="Print the rendered config TOML for each target server.",
    )
    return parser.parse_args()


def main() -> int:
    _bootstrap()
    args = _parse_args()

    from core.config import Config
    from core.mcp_config import parse_mcp_config, render_mcp_config

    db_url = Config.SQLALCHEMY_DATABASE_URI
    if not db_url.startswith("sqlite:///"):
        raise RuntimeError("Only sqlite:/// URLs are supported by this script.")
    db_path = db_url[len("sqlite:///") :]

    target_configs = _build_target_configs(args.llmctl_stdio_tap)
    target_keys = args.server or sorted(target_configs.keys())

    def update_session(conn: sqlite3.Connection) -> list[str]:
        updated: list[str] = []
        for server_key in target_keys:
            target = target_configs[server_key]
            row = conn.execute(
                "SELECT id, server_key, config_json FROM mcp_servers WHERE server_key = ?",
                (server_key,),
            ).fetchone()
            if row is None:
                print(f"Skipping {server_key}: not found in DB.")
                continue
            try:
                current = parse_mcp_config(row["config_json"], server_key=server_key)
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
            if rendered.strip() == (row["config_json"] or "").strip():
                print(f"No change for {server_key}.")
                if args.print:
                    print(rendered)
                continue
            print(f"Updating {server_key}.")
            if args.print:
                print(rendered)
            if args.apply:
                updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
                conn.execute(
                    "UPDATE mcp_servers SET config_json = ?, updated_at = ? WHERE id = ?",
                    (rendered, updated_at, row["id"]),
                )
            updated.append(server_key)
        return updated

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        updated = update_session(conn)
        if args.apply:
            conn.commit()
        else:
            conn.rollback()
    finally:
        conn.close()
    print(json.dumps({"applied": bool(args.apply), "updated": updated}, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
