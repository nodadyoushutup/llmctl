#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path


def _bootstrap() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    studio_src = repo_root / "app" / "llmctl-studio" / "src"
    sys.path.insert(0, str(studio_src))
    os.chdir(repo_root)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill legacy skill scripts into first-class skills tables.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes to the database (default is dry-run).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional maximum number of legacy scripts to migrate.",
    )
    parser.add_argument(
        "--script-id",
        action="append",
        type=int,
        help="Limit migration to specific legacy script ids (repeatable).",
    )
    return parser.parse_args()


def _slugify(value: str) -> str:
    lowered = (value or "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return cleaned or "skill"


def _safe_filename(value: str, fallback: str) -> str:
    name = Path(value).name if value else ""
    if not name or name in {".", ".."}:
        return fallback
    return name


def _checksum(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _render_skill_md(
    *,
    display_name: str,
    description: str,
    script_path: str,
    legacy_script_id: int,
) -> str:
    return (
        "---\n"
        f"name: {_slugify(display_name)}\n"
        f"description: {description}\n"
        "metadata:\n"
        "  imported_from: legacy_skill_script\n"
        f"  legacy_script_id: {legacy_script_id}\n"
        "---\n\n"
        f"# {display_name}\n\n"
        f"{description}\n\n"
        "## Resources\n\n"
        f"- Script: `{script_path}`\n"
    )


def _next_name(base: str, used: set[str]) -> str:
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}-{index}"
        index += 1
    used.add(candidate)
    return candidate


def main() -> int:
    _bootstrap()
    args = _parse_args()

    from sqlalchemy import select

    from core.config import Config
    from core.db import create_session, init_db, init_engine
    from core.models import SCRIPT_TYPE_SKILL, Script, Skill, SkillFile, SkillVersion

    init_engine(Config.SQLALCHEMY_DATABASE_URI)
    init_db()

    session = create_session()
    summary = {
        "applied": bool(args.apply),
        "inspected": 0,
        "migrated": 0,
        "skipped_already_migrated": 0,
        "skipped_missing_content": 0,
    }
    try:
        query = select(Script).where(Script.script_type == SCRIPT_TYPE_SKILL).order_by(Script.id.asc())
        if args.script_id:
            query = query.where(Script.id.in_(args.script_id))
        legacy_scripts = list(session.execute(query).scalars().all())
        if args.limit and args.limit > 0:
            legacy_scripts = legacy_scripts[: args.limit]

        used_names = {
            str(value)
            for value in session.execute(select(Skill.name)).scalars().all()
            if isinstance(value, str) and value.strip()
        }

        for script in legacy_scripts:
            summary["inspected"] += 1
            source_type = "legacy_skill_script"
            source_ref = str(script.id)
            existing = (
                session.execute(
                    select(Skill).where(
                        Skill.source_type == source_type,
                        Skill.source_ref == source_ref,
                    )
                )
                .scalars()
                .first()
            )
            if existing is not None:
                summary["skipped_already_migrated"] += 1
                continue

            script_content = script.content or ""
            if not script_content.strip():
                summary["skipped_missing_content"] += 1
                continue

            base_display_name = (Path(script.file_name or "").stem or f"skill-{script.id}").strip()
            display_name = base_display_name.replace("_", " ").replace("-", " ").strip().title()
            if not display_name:
                display_name = f"Skill {script.id}"
            description = (script.description or "").strip() or (
                f"Migrated from legacy skill script {script.file_name or script.id}."
            )
            skill_name = _next_name(_slugify(base_display_name), used_names)

            script_file_name = _safe_filename(script.file_name or "", f"legacy-script-{script.id}.sh")
            script_path = f"scripts/{script_file_name}"
            skill_md = _render_skill_md(
                display_name=display_name,
                description=description,
                script_path=script_path,
                legacy_script_id=script.id,
            )

            manifest = {
                "imported_from": "legacy_skill_script",
                "legacy_script_id": script.id,
                "files": [
                    {"path": "SKILL.md"},
                    {"path": script_path},
                ],
            }
            manifest_json = json.dumps(manifest, indent=2, sort_keys=True)
            manifest_hash = _checksum(
                json.dumps(
                    {"manifest": manifest, "skill_md": skill_md, "script_content": script_content},
                    sort_keys=True,
                )
            )

            if args.apply:
                skill = Skill.create(
                    session,
                    name=skill_name,
                    display_name=display_name,
                    description=description,
                    status="active",
                    source_type=source_type,
                    source_ref=source_ref,
                )
                version = SkillVersion.create(
                    session,
                    skill_id=skill.id,
                    version="1.0.0",
                    manifest_json=manifest_json,
                    manifest_hash=manifest_hash,
                )
                SkillFile.create(
                    session,
                    skill_version_id=version.id,
                    path="SKILL.md",
                    content=skill_md,
                    checksum=_checksum(skill_md),
                    size_bytes=len(skill_md.encode("utf-8")),
                )
                SkillFile.create(
                    session,
                    skill_version_id=version.id,
                    path=script_path,
                    content=script_content,
                    checksum=_checksum(script_content),
                    size_bytes=len(script_content.encode("utf-8")),
                )
            summary["migrated"] += 1

        if args.apply:
            session.commit()
        else:
            session.rollback()
    finally:
        session.close()

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
