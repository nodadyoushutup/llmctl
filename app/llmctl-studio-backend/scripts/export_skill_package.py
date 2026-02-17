#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


def _bootstrap() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    studio_src = repo_root / "app" / "llmctl-studio-backend" / "src"
    sys.path.insert(0, str(studio_src))
    os.chdir(repo_root)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a skill/version from DB to deterministic JSON bundle.",
    )
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument(
        "--skill-name",
        help="Skill slug to export.",
    )
    selector.add_argument(
        "--skill-id",
        type=int,
        help="Skill id to export.",
    )
    parser.add_argument(
        "--version",
        help="Skill version to export. Defaults to latest by id.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output JSON file path.",
    )
    return parser.parse_args()


def main() -> int:
    _bootstrap()
    args = _parse_args()

    from core.config import Config
    from core.db import create_session, init_db, init_engine
    from services.skills import export_skill_package_from_db, serialize_skill_bundle

    init_engine(Config.SQLALCHEMY_DATABASE_URI)
    init_db()

    session = create_session()
    try:
        package = export_skill_package_from_db(
            session,
            skill_name=args.skill_name,
            skill_id=args.skill_id,
            version=args.version,
        )
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 1
    finally:
        session.close()

    bundle_json = serialize_skill_bundle(package, pretty=True)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(bundle_json, encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "output": str(output_path),
                "skill": package.metadata.name,
                "version": package.metadata.version,
                "manifest_hash": package.manifest_hash,
                "file_count": len(package.files),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
