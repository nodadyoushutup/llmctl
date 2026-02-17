#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import quote_plus


def _bootstrap() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    studio_src = repo_root / "app" / "llmctl-studio" / "src"
    sys.path.insert(0, str(studio_src))
    os.chdir(repo_root)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify PostgreSQL connectivity and Studio schema health.",
    )
    parser.add_argument(
        "--database-uri",
        default="",
        help=(
            "PostgreSQL SQLAlchemy URI override. "
            "Defaults to LLMCTL_STUDIO_DATABASE_URI or LLMCTL_POSTGRES_*."
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=60.0,
        help="Maximum wait time for the DB to become healthy.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=2.0,
        help="Retry interval while waiting for DB health.",
    )
    return parser.parse_args()


def _resolve_database_uri(explicit_uri: str) -> str:
    uri = explicit_uri.strip()
    if uri:
        return uri

    env_uri = os.getenv("LLMCTL_STUDIO_DATABASE_URI", "").strip()
    if env_uri:
        return env_uri

    host = os.getenv("LLMCTL_POSTGRES_HOST", "").strip()
    port = os.getenv("LLMCTL_POSTGRES_PORT", "").strip()
    database = os.getenv("LLMCTL_POSTGRES_DB", "").strip()
    user = os.getenv("LLMCTL_POSTGRES_USER", "").strip()
    password = os.getenv("LLMCTL_POSTGRES_PASSWORD", "").strip()
    if all((host, port, database, user, password)):
        return (
            "postgresql+psycopg://"
            f"{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{database}"
        )

    raise RuntimeError(
        "Missing database config. Set --database-uri, LLMCTL_STUDIO_DATABASE_URI, "
        "or all LLMCTL_POSTGRES_* values."
    )


def main() -> int:
    args = _parse_args()
    database_uri = _resolve_database_uri(args.database_uri)
    os.environ["LLMCTL_STUDIO_DATABASE_URI"] = database_uri

    _bootstrap()

    from core.db import run_startup_db_healthcheck

    run_startup_db_healthcheck(
        database_uri,
        timeout_seconds=max(args.timeout_seconds, 0.0),
        interval_seconds=max(args.interval_seconds, 0.1),
    )
    print("Database health check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
