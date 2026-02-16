from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from core.models import (
    Agent,
    FlowchartNode,
    Skill,
    SkillVersion,
    agent_skill_bindings,
    flowchart_node_skills,
)
from services.skills import (
    decode_skill_file_content_bytes,
    skill_file_content_checksum,
    skill_file_content_size_bytes,
)

SKILL_FALLBACK_MAX_PER_SKILL_CHARS = 12_000
SKILL_FALLBACK_MAX_TOTAL_CHARS = 32_000

_NATIVE_PROVIDER_ADAPTERS = {
    "codex": "codex",
    "claude": "claude_code",
    "gemini": "gemini_cli",
}
_WORKSPACE_SKILLS_ROOT = Path(".llmctl") / "skills"


@dataclass(frozen=True)
class ResolvedSkillFile:
    path: str
    content: str
    checksum: str
    size_bytes: int


@dataclass(frozen=True)
class ResolvedSkill:
    skill_id: int
    name: str
    display_name: str
    description: str
    version_id: int
    version: str
    manifest_hash: str
    files: tuple[ResolvedSkillFile, ...]


@dataclass(frozen=True)
class ResolvedSkillSet:
    skills: tuple[ResolvedSkill, ...]
    manifest_hash: str


@dataclass(frozen=True)
class SkillAdapterResult:
    mode: str
    adapter: str
    materialized_paths: tuple[str, ...]
    fallback_entries: tuple[dict[str, str], ...]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_skill_relative_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    rel = PurePosixPath(normalized)
    if rel.is_absolute():
        raise ValueError(f"Skill file path must be relative: {path}")
    parts = list(rel.parts)
    if not parts:
        raise ValueError("Skill file path is empty")
    for segment in parts:
        if segment in {"", ".", ".."}:
            raise ValueError(f"Skill file path is not path-safe: {path}")
    return "/".join(parts)


def _latest_skill_version(skill: Skill) -> SkillVersion:
    versions = sorted(list(skill.versions or []), key=lambda item: item.id, reverse=True)
    if not versions:
        raise ValueError(
            f"Skill '{skill.name}' has no versions and cannot be resolved for runtime."
        )
    return versions[0]


def _resolve_skill_files(version: SkillVersion) -> tuple[ResolvedSkillFile, ...]:
    files: list[ResolvedSkillFile] = []
    has_skill_md = False
    for entry in sorted(list(version.files or []), key=lambda item: item.path):
        safe_path = _safe_skill_relative_path(entry.path)
        content = entry.content or ""
        checksum = (entry.checksum or "").strip() or skill_file_content_checksum(content)
        size_bytes = int(entry.size_bytes or skill_file_content_size_bytes(content))
        files.append(
            ResolvedSkillFile(
                path=safe_path,
                content=content,
                checksum=checksum,
                size_bytes=size_bytes,
            )
        )
        if safe_path == "SKILL.md":
            has_skill_md = True
    if not has_skill_md:
        raise ValueError(
            f"Skill version {version.id} is missing SKILL.md and cannot be resolved."
        )
    return tuple(files)


def _effective_manifest_hash(version: SkillVersion, files: tuple[ResolvedSkillFile, ...]) -> str:
    explicit = (version.manifest_hash or "").strip()
    if explicit:
        return explicit
    payload = {
        "version_id": version.id,
        "version": version.version,
        "files": [
            {
                "path": entry.path,
                "checksum": entry.checksum,
                "size_bytes": entry.size_bytes,
            }
            for entry in files
        ],
    }
    return _sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _resolved_manifest_hash(resolved: list[ResolvedSkill]) -> str:
    manifest_payload = {
        "skills": [
            {
                "skill_id": skill.skill_id,
                "name": skill.name,
                "version_id": skill.version_id,
                "version": skill.version,
                "manifest_hash": skill.manifest_hash,
                "files": [
                    {
                        "path": entry.path,
                        "checksum": entry.checksum,
                        "size_bytes": entry.size_bytes,
                    }
                    for entry in skill.files
                ],
            }
            for skill in resolved
        ]
    }
    return _sha256_text(json.dumps(manifest_payload, sort_keys=True, separators=(",", ":")))


def _resolve_ordered_skill_set(
    *,
    skills: list[Skill],
    position_by_skill_id: dict[int, int | None],
) -> ResolvedSkillSet:
    def _sort_key(skill: Skill) -> tuple[int, str, int]:
        position = position_by_skill_id.get(skill.id)
        normalized_position = position if position is not None else 2**31 - 1
        return normalized_position, (skill.name or "").lower(), int(skill.id)

    resolved: list[ResolvedSkill] = []
    for skill in sorted(skills, key=_sort_key):
        version = _latest_skill_version(skill)
        files = _resolve_skill_files(version)
        manifest_hash = _effective_manifest_hash(version, files)
        resolved.append(
            ResolvedSkill(
                skill_id=skill.id,
                name=skill.name,
                display_name=skill.display_name,
                description=skill.description or "",
                version_id=version.id,
                version=version.version,
                manifest_hash=manifest_hash,
                files=files,
            )
        )

    return ResolvedSkillSet(
        skills=tuple(resolved),
        manifest_hash=_resolved_manifest_hash(resolved),
    )


def resolve_agent_skills(
    session: Session,
    agent_id: int,
) -> ResolvedSkillSet:
    agent = (
        session.execute(
            select(Agent)
            .options(
                selectinload(Agent.skills)
                .selectinload(Skill.versions)
                .selectinload(SkillVersion.files)
            )
            .where(Agent.id == agent_id)
        )
        .scalars()
        .first()
    )
    if agent is None:
        raise ValueError(f"Agent {agent_id} was not found.")

    position_rows = session.execute(
        select(agent_skill_bindings.c.skill_id, agent_skill_bindings.c.position).where(
            agent_skill_bindings.c.agent_id == agent_id
        )
    ).all()
    position_by_skill_id: dict[int, int | None] = {
        int(skill_id): (int(position) if position is not None else None)
        for skill_id, position in position_rows
    }

    return _resolve_ordered_skill_set(
        skills=list(agent.skills or []),
        position_by_skill_id=position_by_skill_id,
    )


def resolve_flowchart_node_skills(
    session: Session,
    flowchart_node_id: int,
) -> ResolvedSkillSet:
    node = (
        session.execute(
            select(FlowchartNode)
            .options(
                selectinload(FlowchartNode.skills)
                .selectinload(Skill.versions)
                .selectinload(SkillVersion.files)
            )
            .where(FlowchartNode.id == flowchart_node_id)
        )
        .scalars()
        .first()
    )
    if node is None:
        raise ValueError(f"Flowchart node {flowchart_node_id} was not found.")

    position_rows = session.execute(
        select(flowchart_node_skills.c.skill_id, flowchart_node_skills.c.position).where(
            flowchart_node_skills.c.flowchart_node_id == flowchart_node_id
        )
    ).all()
    position_by_skill_id: dict[int, int | None] = {
        int(skill_id): (int(position) if position is not None else None)
        for skill_id, position in position_rows
    }

    return _resolve_ordered_skill_set(
        skills=list(node.skills or []),
        position_by_skill_id=position_by_skill_id,
    )


def select_skill_adapter(provider: str) -> tuple[str, str]:
    normalized = (provider or "").strip().lower()
    adapter = _NATIVE_PROVIDER_ADAPTERS.get(normalized)
    if adapter:
        return "native", adapter
    return "fallback", "prompt_fallback"


def _materialization_root(
    *,
    adapter: str,
    runtime_home: Path,
    codex_home: Path | None,
) -> Path:
    if adapter == "codex":
        return (codex_home or runtime_home / ".codex") / "skills"
    if adapter == "claude_code":
        return runtime_home / ".claude" / "skills"
    if adapter == "gemini_cli":
        return runtime_home / ".gemini" / "skills"
    raise ValueError(f"Unsupported native adapter '{adapter}'.")


def _write_read_only_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(decode_skill_file_content_bytes(content))
    try:
        path.chmod(0o444)
    except OSError:
        return


def _materialize_skill_tree(
    target_root: Path,
    resolved: ResolvedSkillSet,
) -> list[str]:
    if target_root.exists():
        shutil.rmtree(target_root)
    target_root.mkdir(parents=True, exist_ok=True)
    materialized_paths: list[str] = []
    for skill in resolved.skills:
        skill_dir = target_root / skill.name
        skill_dir.mkdir(parents=True, exist_ok=True)
        for entry in skill.files:
            rel_path = _safe_skill_relative_path(entry.path)
            destination = skill_dir / Path(rel_path)
            _write_read_only_file(destination, entry.content)
        materialized_paths.append(str(skill_dir))
    return materialized_paths


def materialize_skill_set(
    resolved: ResolvedSkillSet,
    *,
    provider: str,
    workspace: Path,
    runtime_home: Path,
    codex_home: Path | None = None,
    ) -> SkillAdapterResult:
    mode, adapter = select_skill_adapter(provider)
    if not resolved.skills:
        return SkillAdapterResult(
            mode=mode,
            adapter=adapter,
            materialized_paths=tuple(),
            fallback_entries=tuple(),
        )

    workspace_root = workspace / _WORKSPACE_SKILLS_ROOT
    materialized_paths = _materialize_skill_tree(workspace_root, resolved)

    if mode == "fallback":
        return SkillAdapterResult(
            mode=mode,
            adapter=adapter,
            materialized_paths=tuple(materialized_paths),
            fallback_entries=tuple(build_skill_fallback_entries(resolved)),
        )

    target_root = _materialization_root(
        adapter=adapter,
        runtime_home=runtime_home,
        codex_home=codex_home,
    )
    materialized_paths.extend(_materialize_skill_tree(target_root, resolved))

    return SkillAdapterResult(
        mode=mode,
        adapter=adapter,
        materialized_paths=tuple(materialized_paths),
        fallback_entries=tuple(),
    )


def build_skill_fallback_entries(
    resolved: ResolvedSkillSet,
) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    remaining_total = SKILL_FALLBACK_MAX_TOTAL_CHARS

    for skill in resolved.skills:
        skill_md = ""
        for entry in skill.files:
            if entry.path == "SKILL.md":
                skill_md = entry.content
                break
        if not skill_md:
            continue

        snippet = skill_md.strip()
        if len(snippet) > SKILL_FALLBACK_MAX_PER_SKILL_CHARS:
            snippet = snippet[:SKILL_FALLBACK_MAX_PER_SKILL_CHARS]
        if len(snippet) > remaining_total:
            snippet = snippet[:remaining_total]
        snippet = snippet.strip()
        if not snippet:
            continue

        entries.append(
            {
                "name": skill.name,
                "display_name": skill.display_name,
                "version": skill.version,
                "description": skill.description,
                "content": snippet,
            }
        )
        remaining_total -= len(snippet)
        if remaining_total <= 0:
            break

    return entries


def skill_ids_payload(resolved: ResolvedSkillSet) -> list[int]:
    return [skill.skill_id for skill in resolved.skills]


def skill_versions_payload(resolved: ResolvedSkillSet) -> list[dict[str, Any]]:
    return [
        {
            "skill_id": skill.skill_id,
            "name": skill.name,
            "version_id": skill.version_id,
            "version": skill.version,
        }
        for skill in resolved.skills
    ]
