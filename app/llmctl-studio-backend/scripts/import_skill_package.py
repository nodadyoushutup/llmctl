#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


def _bootstrap() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    studio_src = repo_root / "app" / "llmctl-studio" / "src"
    sys.path.insert(0, str(studio_src))
    os.chdir(repo_root)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import a skill package JSON bundle into skills tables.",
    )
    parser.add_argument(
        "--bundle",
        required=True,
        help="Path to a skill bundle JSON file.",
    )
    parser.add_argument(
        "--source-ref",
        default="",
        help="Optional source reference recorded on skill metadata.",
    )
    parser.add_argument(
        "--actor",
        default="",
        help="Optional actor identifier for created_by/updated_by.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write import to DB. Defaults to dry-run validation only.",
    )
    return parser.parse_args()


def main() -> int:
    _bootstrap()
    args = _parse_args()

    from core.config import Config
    from core.db import create_session, init_db, init_engine
    from services.skills import (
        SkillPackageValidationError,
        format_validation_errors,
        import_skill_package_to_db,
        load_skill_bundle,
    )

    init_engine(Config.SQLALCHEMY_DATABASE_URI)
    init_db()

    bundle_payload = Path(args.bundle).read_text(encoding="utf-8")

    try:
        package = load_skill_bundle(bundle_payload)
    except SkillPackageValidationError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "errors": format_validation_errors(exc.errors),
                },
                sort_keys=True,
            )
        )
        return 1

    session = create_session()
    try:
        result = import_skill_package_to_db(
            session,
            package,
            source_type="import",
            source_ref=args.source_ref or None,
            actor=args.actor or None,
        )
        if args.apply:
            session.commit()
        else:
            session.rollback()
    except ValueError as exc:
        session.rollback()
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 1
    finally:
        session.close()

    print(
        json.dumps(
            {
                "ok": True,
                "applied": bool(args.apply),
                "skill_id": result.skill_id,
                "skill_name": result.skill_name,
                "version_id": result.version_id,
                "version": result.version,
                "file_count": result.file_count,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
