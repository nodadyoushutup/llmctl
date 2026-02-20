#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Stage 13 one-time flowchart runtime schema migration helper with "
            "compatibility-gate and evidence export."
        )
    )
    parser.add_argument(
        "--flowchart-id",
        action="append",
        type=int,
        default=[],
        help="Limit migration to one or more flowchart ids (repeatable).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist transformed flowchart snapshots when compatibility gate passes.",
    )
    parser.add_argument(
        "--non-strict-policy",
        action="store_true",
        help=(
            "Downgrade policy-only compatibility violations to warnings when possible. "
            "Default is strict policy mode."
        ),
    )
    parser.add_argument(
        "--export-json",
        default="",
        help="Optional path to write migration evidence JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    from core.config import Config
    from core.db import init_db, init_engine, session_scope
    from services.flow_migration import run_flowchart_schema_migration

    init_engine(Config.SQLALCHEMY_DATABASE_URI)
    init_db()

    with session_scope() as session:
        result = run_flowchart_schema_migration(
            session,
            flowchart_ids=list(args.flowchart_id or []),
            apply=bool(args.apply),
            strict_policy=not bool(args.non_strict_policy),
        )

    export_path = str(args.export_json or "").strip()
    if export_path:
        target = Path(export_path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(f"Evidence written: {target}")

    flowchart_count = int(result.get("flowchart_count") or 0)
    blocked_count = int(result.get("blocked_count") or 0)
    applied_count = int(result.get("applied_count") or 0)
    changed_count = int(result.get("changed_count") or 0)

    mode = "apply" if args.apply else "dry-run"
    print(
        f"Flowchart migration ({mode}) analyzed {flowchart_count} flowchart(s); "
        f"changed={changed_count}, blocked={blocked_count}, applied={applied_count}."
    )

    if blocked_count > 0:
        print("Compatibility gate blocked one or more flowcharts.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
