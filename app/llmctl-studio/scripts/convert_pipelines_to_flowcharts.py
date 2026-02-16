#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "llmctl-studio.sqlite3"


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def _value(row: sqlite3.Row, *names: str) -> Any:
    for name in names:
        if name in row.keys():
            return row[name]
    return None


def _order_column(available: set[str], preferred: tuple[str, ...]) -> str:
    for name in preferred:
        if name in available:
            return name
    return "id"


def _insert_row(
    conn: sqlite3.Connection,
    table: str,
    data: dict[str, Any],
    columns_cache: dict[str, set[str]],
) -> int:
    table_columns = columns_cache.setdefault(table, _table_columns(conn, table))
    payload = {key: value for key, value in data.items() if key in table_columns}
    if not payload:
        raise ValueError(f"No insertable columns for table '{table}'.")
    keys = list(payload.keys())
    placeholders = ", ".join(["?"] * len(keys))
    sql = f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({placeholders})"
    cursor = conn.execute(sql, [payload[key] for key in keys])
    return int(cursor.lastrowid)


def _load_pipeline_rows(conn: sqlite3.Connection) -> tuple[list[sqlite3.Row], dict[int, list[sqlite3.Row]]]:
    pipelines = conn.execute("SELECT * FROM pipelines ORDER BY id ASC").fetchall()
    steps_by_pipeline: dict[int, list[sqlite3.Row]] = defaultdict(list)
    if not _table_exists(conn, "pipeline_steps"):
        return pipelines, steps_by_pipeline

    step_columns = _table_columns(conn, "pipeline_steps")
    order_col = _order_column(step_columns, ("position", "order_index", "step_order"))
    steps = conn.execute(
        f"SELECT * FROM pipeline_steps ORDER BY pipeline_id ASC, {order_col} ASC, id ASC"
    ).fetchall()
    for step in steps:
        pipeline_id = _value(step, "pipeline_id")
        if isinstance(pipeline_id, int):
            steps_by_pipeline[pipeline_id].append(step)
    return pipelines, steps_by_pipeline


def _build_step_config(step: sqlite3.Row) -> str:
    ignored = {
        "id",
        "pipeline_id",
        "position",
        "order_index",
        "step_order",
        "name",
        "title",
        "label",
        "description",
        "task_template_id",
        "template_id",
        "task_id",
        "model_id",
        "created_at",
        "updated_at",
    }
    legacy: dict[str, Any] = {}
    for key in step.keys():
        if key in ignored:
            continue
        value = step[key]
        if value is not None:
            legacy[str(key)] = value
    payload = {
        "legacy_pipeline_step_id": _value(step, "id"),
        "legacy_pipeline_step_description": _value(step, "description"),
        "legacy_fields": legacy,
    }
    return json.dumps(payload, sort_keys=True)


def _convert(
    conn: sqlite3.Connection,
    *,
    dry_run: bool,
    export_path: Path | None,
) -> dict[str, Any]:
    if not _table_exists(conn, "pipelines"):
        return {
            "ok": True,
            "converted": 0,
            "message": "No legacy pipelines table found. Nothing to convert.",
            "pipelines": [],
        }
    required_tables = {"flowcharts", "flowchart_nodes", "flowchart_edges"}
    missing = [table for table in required_tables if not _table_exists(conn, table)]
    if missing:
        return {
            "ok": False,
            "converted": 0,
            "error": f"Missing required flowchart tables: {', '.join(sorted(missing))}",
            "pipelines": [],
        }

    conn.execute("BEGIN")
    columns_cache: dict[str, set[str]] = {}
    pipelines, steps_by_pipeline = _load_pipeline_rows(conn)
    converted: list[dict[str, Any]] = []

    for pipeline in pipelines:
        pipeline_id = _value(pipeline, "id")
        if not isinstance(pipeline_id, int):
            continue
        name = str(_value(pipeline, "name") or f"Pipeline {pipeline_id}").strip()
        description = _value(pipeline, "description", "prompt")
        flowchart_id = _insert_row(
            conn,
            "flowcharts",
            {
                "name": name,
                "description": description,
                "created_at": _value(pipeline, "created_at"),
                "updated_at": _value(pipeline, "updated_at"),
            },
            columns_cache,
        )
        start_node_id = _insert_row(
            conn,
            "flowchart_nodes",
            {
                "flowchart_id": flowchart_id,
                "node_type": "start",
                "title": "Start",
                "x": 0.0,
                "y": 0.0,
            },
            columns_cache,
        )

        previous_node_id = start_node_id
        converted_steps: list[dict[str, Any]] = []
        for index, step in enumerate(steps_by_pipeline.get(pipeline_id, []), start=1):
            step_id = _value(step, "id")
            step_title = (
                _value(step, "title")
                or _value(step, "name")
                or _value(step, "label")
                or f"Step {index}"
            )
            ref_id = _value(step, "task_template_id", "template_id", "task_id")
            model_id = _value(step, "model_id")
            node_id = _insert_row(
                conn,
                "flowchart_nodes",
                {
                    "flowchart_id": flowchart_id,
                    "node_type": "task",
                    "ref_id": ref_id if isinstance(ref_id, int) else None,
                    "title": str(step_title),
                    "x": float(index * 320),
                    "y": 0.0,
                    "model_id": model_id if isinstance(model_id, int) else None,
                    "config_json": _build_step_config(step),
                    "created_at": _value(step, "created_at"),
                    "updated_at": _value(step, "updated_at"),
                },
                columns_cache,
            )
            _insert_row(
                conn,
                "flowchart_edges",
                {
                    "flowchart_id": flowchart_id,
                    "source_node_id": previous_node_id,
                    "target_node_id": node_id,
                    "created_at": _value(step, "created_at"),
                    "updated_at": _value(step, "updated_at"),
                },
                columns_cache,
            )
            previous_node_id = node_id
            converted_steps.append(
                {
                    "pipeline_step_id": step_id,
                    "flowchart_node_id": node_id,
                    "title": str(step_title),
                }
            )

        converted.append(
            {
                "pipeline_id": pipeline_id,
                "pipeline_name": name,
                "flowchart_id": flowchart_id,
                "flowchart_name": name,
                "converted_steps": converted_steps,
            }
        )

    if dry_run:
        conn.execute("ROLLBACK")
    else:
        conn.execute("COMMIT")

    result = {
        "ok": True,
        "converted": len(converted),
        "dry_run": dry_run,
        "pipelines": converted,
    }
    if export_path is not None:
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One-time conversion helper: migrate legacy pipeline rows to flowchart rows."
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="Path to the Studio SQLite database file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run conversion logic but rollback all changes.",
    )
    parser.add_argument(
        "--export-json",
        default="",
        help="Optional path to write conversion/export metadata as JSON.",
    )
    args = parser.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    if not db_path.exists():
        print(f"Database file not found: {db_path}")
        return 1

    export_path = Path(args.export_json).expanduser().resolve() if args.export_json else None
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        result = _convert(
            conn,
            dry_run=bool(args.dry_run),
            export_path=export_path,
        )

    if not result.get("ok"):
        print(result.get("error") or "Conversion failed.")
        return 1

    print(
        f"Converted {result.get('converted', 0)} pipeline(s)"
        + (" [dry-run]" if args.dry_run else "")
        + f" from {db_path}"
    )
    if export_path is not None:
        print(f"Export written: {export_path}")
    message = result.get("message")
    if message:
        print(str(message))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
