#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from sqlalchemy import text


def _bootstrap() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    studio_src = repo_root / "app" / "llmctl-studio" / "src"
    sys.path.insert(0, str(studio_src))
    os.chdir(repo_root)
    return repo_root


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill legacy node-bound skill bindings into agent_skill_bindings "
            "using the deterministic Stage 2 migration mapping."
        )
    )
    parser.add_argument(
        "--database-uri",
        default="",
        help="Optional DB URI override. Defaults to Config.SQLALCHEMY_DATABASE_URI.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON report output.",
    )
    return parser.parse_args()


def _safe_table_count(connection, table: str) -> int:
    try:
        return int(connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0)
    except Exception:
        return 0


def main() -> int:
    _bootstrap()
    args = _parse_args()

    from core.config import Config
    from core.db import init_db, init_engine

    database_uri = args.database_uri.strip() or Config.SQLALCHEMY_DATABASE_URI
    engine = init_engine(database_uri)
    if engine is None:
        raise RuntimeError("Failed to initialize database engine.")

    with engine.begin() as connection:
        before_agent_bindings = _safe_table_count(connection, "agent_skill_bindings")
        before_unmapped = _safe_table_count(connection, "legacy_unmapped_node_skills")
        before_node_bindings = _safe_table_count(connection, "flowchart_node_skills")

    init_db()

    with engine.begin() as connection:
        after_agent_bindings = _safe_table_count(connection, "agent_skill_bindings")
        after_unmapped = _safe_table_count(connection, "legacy_unmapped_node_skills")
        after_node_bindings = _safe_table_count(connection, "flowchart_node_skills")

    report = {
        "database_uri": database_uri,
        "before": {
            "agent_skill_bindings": before_agent_bindings,
            "legacy_unmapped_node_skills": before_unmapped,
            "flowchart_node_skills": before_node_bindings,
        },
        "after": {
            "agent_skill_bindings": after_agent_bindings,
            "legacy_unmapped_node_skills": after_unmapped,
            "flowchart_node_skills": after_node_bindings,
        },
        "delta": {
            "agent_skill_bindings": after_agent_bindings - before_agent_bindings,
            "legacy_unmapped_node_skills": after_unmapped - before_unmapped,
        },
    }
    if args.pretty:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
