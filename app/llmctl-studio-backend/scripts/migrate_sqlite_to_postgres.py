#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus


def _bootstrap() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    studio_src = repo_root / "app" / "llmctl-studio-backend" / "src"
    sys.path.insert(0, str(studio_src))
    os.chdir(repo_root)


def _default_sqlite_path() -> str:
    repo_root = Path(__file__).resolve().parents[3]
    return str(repo_root / "data" / "llmctl-studio.sqlite3")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "One-time migration: copy llmctl-studio data from SQLite into PostgreSQL."
        ),
    )
    parser.add_argument(
        "--sqlite-path",
        default=_default_sqlite_path(),
        help="Path to source SQLite database file.",
    )
    parser.add_argument(
        "--postgres-uri",
        default="",
        help=(
            "Target PostgreSQL SQLAlchemy URI. "
            "Defaults to LLMCTL_STUDIO_DATABASE_URI or LLMCTL_POSTGRES_*."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Rows per insert batch.",
    )
    parser.add_argument(
        "--truncate-target",
        action="store_true",
        help="Truncate destination tables before copy.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print migration plan without writing rows.",
    )
    return parser.parse_args()


def _resolve_postgres_uri(explicit_uri: str) -> str:
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
        "Missing target PostgreSQL config. Set --postgres-uri, "
        "LLMCTL_STUDIO_DATABASE_URI, or all LLMCTL_POSTGRES_* values."
    )


def _coerce_boolean(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "t", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "f", "no", "n", "off", ""}:
            return False
    return value


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'

def main() -> int:
    args = _parse_args()
    if args.batch_size < 1:
        raise ValueError("--batch-size must be >= 1")

    sqlite_path = Path(args.sqlite_path).expanduser().resolve()
    if not sqlite_path.is_file():
        raise FileNotFoundError(f"SQLite source DB not found: {sqlite_path}")

    postgres_uri = _resolve_postgres_uri(args.postgres_uri)
    if not postgres_uri.lower().startswith("postgresql"):
        raise RuntimeError("Target --postgres-uri must be a PostgreSQL SQLAlchemy URI.")
    os.environ["LLMCTL_STUDIO_DATABASE_URI"] = postgres_uri

    _bootstrap()

    from sqlalchemy import (
        Boolean,
        Integer,
        MetaData,
        Table,
        create_engine,
        func,
        inspect,
        select,
        text,
    )
    from core.db import Base, init_db, init_engine
    import core.models as _models  # noqa: F401

    def _reset_sequences(connection, table_names: list[str]) -> None:
        for table_name in table_names:
            sequence_name = connection.execute(
                text("SELECT pg_get_serial_sequence(:table_name, 'id')"),
                {"table_name": table_name},
            ).scalar()
            if not sequence_name:
                continue
            connection.execute(
                text(
                    f"SELECT setval(:seq_name, "
                    f"COALESCE((SELECT MAX(id) FROM {_quoted(table_name)}), 0) + 1, false)"
                ),
                {"seq_name": sequence_name},
            )

    source_engine = create_engine(f"sqlite:///{sqlite_path}", future=True)
    target_engine = init_engine(postgres_uri)
    init_db()

    source_tables = set(inspect(source_engine).get_table_names())
    target_tables = set(inspect(target_engine).get_table_names())
    ordered_tables = [
        table.name
        for table in Base.metadata.sorted_tables
        if table.name in source_tables and table.name in target_tables
    ]
    if not ordered_tables:
        raise RuntimeError("No overlapping tables found between source and target.")

    print(f"SQLite source: {sqlite_path}")
    print(f"Target tables considered: {len(ordered_tables)}")
    if args.dry_run:
        print("Mode: dry-run (no writes)")
    elif args.truncate_target:
        print("Mode: truncate target then copy")
    else:
        print("Mode: copy into empty target")

    copied_row_total = 0
    copied_tables: list[str] = []
    copied_rows_by_table: dict[str, int] = {}

    with source_engine.connect() as source_conn, target_engine.begin() as target_conn:
        if args.truncate_target and not args.dry_run:
            for table_name in reversed(ordered_tables):
                target_conn.execute(
                    text(f"TRUNCATE TABLE {_quoted(table_name)} RESTART IDENTITY CASCADE")
                )

        for table_name in ordered_tables:
            source_table = Table(table_name, MetaData(), autoload_with=source_engine)
            target_table = Table(table_name, MetaData(), autoload_with=target_conn)
            common_columns = [
                column.name for column in target_table.columns if column.name in source_table.c
            ]
            if not common_columns:
                continue

            source_count = source_conn.execute(
                select(func.count()).select_from(source_table)
            ).scalar_one()
            if source_count == 0:
                continue

            if not args.truncate_target and not args.dry_run:
                existing_count = target_conn.execute(
                    select(func.count()).select_from(target_table)
                ).scalar_one()
                if existing_count > 0:
                    raise RuntimeError(
                        f"Target table '{table_name}' is not empty ({existing_count} rows). "
                        "Use --truncate-target to overwrite."
                    )

            print(f"Copying {table_name}: {source_count} rows")
            if args.dry_run:
                copied_rows_by_table[table_name] = int(source_count)
                continue

            boolean_columns = {
                column_name
                for column_name in common_columns
                if isinstance(target_table.c[column_name].type, Boolean)
            }
            source_select = select(*(source_table.c[column] for column in common_columns))
            result = source_conn.execute(source_select)
            table_inserted = 0
            while True:
                rows = result.fetchmany(args.batch_size)
                if not rows:
                    break
                payload: list[dict[str, Any]] = []
                for row in rows:
                    row_payload = {
                        column_name: row._mapping[column_name]
                        for column_name in common_columns
                    }
                    for column_name in boolean_columns:
                        row_payload[column_name] = _coerce_boolean(
                            row_payload[column_name]
                        )
                    payload.append(row_payload)
                target_conn.execute(target_table.insert(), payload)
                table_inserted += len(payload)
            copied_row_total += table_inserted
            copied_rows_by_table[table_name] = table_inserted
            copied_tables.append(table_name)

        if not args.dry_run:
            integer_id_tables: list[str] = []
            for table_name in copied_tables:
                reflected_table = Table(
                    table_name,
                    MetaData(),
                    autoload_with=target_conn,
                )
                if "id" not in reflected_table.c:
                    continue
                if not isinstance(reflected_table.c["id"].type, Integer):
                    continue
                integer_id_tables.append(table_name)
            _reset_sequences(target_conn, integer_id_tables)

    print("Migration summary:")
    for table_name in ordered_tables:
        count = copied_rows_by_table.get(table_name, 0)
        if count:
            print(f"- {table_name}: {count}")
    if not args.dry_run:
        print(f"Total rows copied: {copied_row_total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
