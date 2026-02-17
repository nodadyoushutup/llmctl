#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

LEGACY_SKILL_SCRIPT_TYPE = "skill"


def _bootstrap() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    studio_src = repo_root / "app" / "llmctl-studio-backend" / "src"
    sys.path.insert(0, str(studio_src))
    os.chdir(repo_root)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill legacy skill scripts into first-class skills tables and "
            "map legacy references to flowchart node skill attachments."
        ),
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
    parser.add_argument(
        "--report-file",
        type=str,
        default="",
        help="Optional file path to write JSON report output.",
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


def _append_mismatch(summary: dict[str, object], kind: str, message: str) -> None:
    mismatches = summary["mismatches"]
    if not isinstance(mismatches, list):
        return
    if len(mismatches) >= 200:
        return
    mismatches.append({"kind": kind, "message": message})


def _candidate_sort_key(item: tuple[int, int, int, int, str]) -> tuple[int, int, int, int]:
    source_order, position, script_id, skill_id, _source = item
    return source_order, position, script_id, skill_id


def _collect_reference_candidates(
    session,
    *,
    script_to_skill: dict[int, int],
    summary: dict[str, object],
) -> dict[int, list[tuple[int, int, int, int, str]]]:
    from sqlalchemy import select

    from core.models import (
        AgentTask,
        Script,
        agent_task_scripts,
        flowchart_node_scripts,
    )

    source_order = {
        "flowchart_node_scripts": 1,
        "agent_task_scripts": 2,
    }
    default_position = 2**31 - 1
    candidates: dict[int, list[tuple[int, int, int, int, str]]] = {}
    reference_scan = summary["reference_scan"]

    def _add_candidate(
        *,
        node_id: int,
        script_id: int,
        position: int | None,
        source: str,
        source_ref: str,
    ) -> None:
        if not isinstance(reference_scan, dict):
            return
        skill_id = script_to_skill.get(script_id)
        if skill_id is None:
            reference_scan["unmapped_script_refs"] = int(reference_scan.get("unmapped_script_refs", 0)) + 1
            _append_mismatch(
                summary,
                "unmapped_legacy_script_reference",
                f"{source_ref} references script {script_id}, but no migrated skill mapping exists.",
            )
            return
        normalized_position = int(position) if position is not None else default_position
        candidates.setdefault(node_id, []).append(
            (
                int(source_order.get(source, 99)),
                normalized_position,
                script_id,
                skill_id,
                source,
            )
        )

    node_rows = session.execute(
        select(
            flowchart_node_scripts.c.flowchart_node_id,
            flowchart_node_scripts.c.script_id,
            flowchart_node_scripts.c.position,
        )
        .join(Script, Script.id == flowchart_node_scripts.c.script_id)
        .where(Script.script_type == LEGACY_SKILL_SCRIPT_TYPE)
    ).all()
    for node_id, script_id, position in node_rows:
        if isinstance(reference_scan, dict):
            reference_scan["flowchart_node_script_refs"] = int(
                reference_scan.get("flowchart_node_script_refs", 0)
            ) + 1
        _add_candidate(
            node_id=int(node_id),
            script_id=int(script_id),
            position=int(position) if position is not None else None,
            source="flowchart_node_scripts",
            source_ref=f"flowchart_node:{node_id}",
        )

    task_rows = session.execute(
        select(
            AgentTask.id,
            AgentTask.flowchart_node_id,
            agent_task_scripts.c.script_id,
            agent_task_scripts.c.position,
        )
        .join(agent_task_scripts, agent_task_scripts.c.agent_task_id == AgentTask.id)
        .join(Script, Script.id == agent_task_scripts.c.script_id)
        .where(Script.script_type == LEGACY_SKILL_SCRIPT_TYPE)
    ).all()
    for task_id, node_id, script_id, position in task_rows:
        if isinstance(reference_scan, dict):
            reference_scan["agent_task_script_refs"] = int(
                reference_scan.get("agent_task_script_refs", 0)
            ) + 1
        if node_id is None:
            if isinstance(reference_scan, dict):
                reference_scan["agent_task_refs_without_node"] = int(
                    reference_scan.get("agent_task_refs_without_node", 0)
                ) + 1
            _append_mismatch(
                summary,
                "agent_task_without_flowchart_node",
                (
                    f"Agent task {task_id} references legacy skill script {script_id} "
                    "but has no flowchart_node_id for node-level migration."
                ),
            )
            continue
        _add_candidate(
            node_id=int(node_id),
            script_id=int(script_id),
            position=int(position) if position is not None else None,
            source="agent_task_scripts",
            source_ref=f"agent_task:{task_id}->flowchart_node:{node_id}",
        )

    return candidates


def _apply_node_skill_attachments(
    session,
    *,
    candidates_by_node: dict[int, list[tuple[int, int, int, int, str]]],
    apply_changes: bool,
    summary: dict[str, object],
) -> None:
    from sqlalchemy import delete, select

    from core.models import flowchart_node_skills

    attachments = summary["attachments"]
    if not isinstance(attachments, dict):
        return

    touched_nodes = 0
    for node_id, candidates in sorted(candidates_by_node.items()):
        touched_nodes += 1
        existing_rows = session.execute(
            select(
                flowchart_node_skills.c.skill_id,
                flowchart_node_skills.c.position,
            ).where(flowchart_node_skills.c.flowchart_node_id == node_id)
        ).all()

        ordered_existing_ids = [
            int(skill_id)
            for skill_id, _position in sorted(
                existing_rows,
                key=lambda item: (
                    int(item[1]) if item[1] is not None else 2**31 - 1,
                    int(item[0]),
                ),
            )
        ]

        final_ids = list(ordered_existing_ids)
        for _source_order, _position, _script_id, skill_id, _source in sorted(
            candidates,
            key=_candidate_sort_key,
        ):
            if skill_id in final_ids:
                attachments["already_present"] = int(attachments.get("already_present", 0)) + 1
                continue
            final_ids.append(skill_id)
            attachments["added"] = int(attachments.get("added", 0)) + 1

        if final_ids == ordered_existing_ids:
            continue

        if not apply_changes:
            continue

        session.execute(
            delete(flowchart_node_skills).where(flowchart_node_skills.c.flowchart_node_id == node_id)
        )
        rows = [
            {
                "flowchart_node_id": node_id,
                "skill_id": skill_id,
                "position": position,
            }
            for position, skill_id in enumerate(final_ids, start=1)
        ]
        if rows:
            session.execute(flowchart_node_skills.insert(), rows)

    attachments["nodes_touched"] = touched_nodes


def main() -> int:
    _bootstrap()
    args = _parse_args()

    from sqlalchemy import select

    from core.config import Config
    from core.db import create_session, init_db, init_engine
    from core.models import Script, Skill, SkillFile, SkillVersion

    init_engine(Config.SQLALCHEMY_DATABASE_URI)
    init_db()

    session = create_session()
    summary: dict[str, object] = {
        "applied": bool(args.apply),
        "legacy_scripts": {
            "inspected": 0,
            "migrated": 0,
            "skipped_already_migrated": 0,
            "skipped_missing_content": 0,
        },
        "reference_scan": {
            "flowchart_node_script_refs": 0,
            "agent_task_script_refs": 0,
            "agent_task_refs_without_node": 0,
            "unmapped_script_refs": 0,
        },
        "attachments": {
            "nodes_touched": 0,
            "added": 0,
            "already_present": 0,
        },
        "mismatches": [],
    }
    try:
        query = (
            select(Script)
            .where(Script.script_type == LEGACY_SKILL_SCRIPT_TYPE)
            .order_by(Script.id.asc())
        )
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

        script_to_skill: dict[int, int] = {}
        legacy_summary = summary["legacy_scripts"]
        if not isinstance(legacy_summary, dict):
            raise RuntimeError("Invalid summary payload")

        for script in legacy_scripts:
            legacy_summary["inspected"] = int(legacy_summary.get("inspected", 0)) + 1
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
                script_to_skill[int(script.id)] = int(existing.id)
                legacy_summary["skipped_already_migrated"] = int(
                    legacy_summary.get("skipped_already_migrated", 0)
                ) + 1
                continue

            script_content = script.content or ""
            if not script_content.strip():
                legacy_summary["skipped_missing_content"] = int(
                    legacy_summary.get("skipped_missing_content", 0)
                ) + 1
                _append_mismatch(
                    summary,
                    "missing_legacy_script_content",
                    f"Legacy script {script.id} has empty content and was not migrated.",
                )
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
                script_to_skill[int(script.id)] = int(skill.id)
            else:
                # Dry-run: synthetic ids let us estimate attachment impact without DB writes.
                script_to_skill[int(script.id)] = -int(script.id)

            legacy_summary["migrated"] = int(legacy_summary.get("migrated", 0)) + 1

        candidates = _collect_reference_candidates(
            session,
            script_to_skill=script_to_skill,
            summary=summary,
        )
        _apply_node_skill_attachments(
            session,
            candidates_by_node=candidates,
            apply_changes=bool(args.apply),
            summary=summary,
        )

        if args.apply:
            session.commit()
        else:
            session.rollback()
    finally:
        session.close()

    if args.report_file.strip():
        report_path = Path(args.report_file.strip())
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
