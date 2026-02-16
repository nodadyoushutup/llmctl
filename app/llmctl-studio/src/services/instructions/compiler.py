from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

ROLE_FILENAME = "ROLE.md"
AGENT_FILENAME = "AGENT.md"
PRIORITIES_FILENAME = "PRIORITIES.md"
INSTRUCTIONS_FILENAME = "INSTRUCTIONS.md"
MANIFEST_FILENAME = "manifest.json"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_markdown(value: str | None) -> str:
    raw = str(value or "")
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    normalized = "\n".join(lines).strip("\n")
    if not normalized:
        return ""
    return f"{normalized}\n"


def _normalize_runtime_overrides(
    runtime_overrides: tuple[str, ...],
) -> tuple[str, ...]:
    entries: list[str] = []
    for entry in runtime_overrides:
        normalized = _normalize_markdown(entry).strip()
        if normalized:
            entries.append(normalized)
    return tuple(entries)


def _normalize_priorities(priorities: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for entry in priorities:
        cleaned = _normalize_markdown(entry).strip()
        if cleaned:
            normalized.append(cleaned)
    return tuple(normalized)


def _render_priorities_markdown(priorities: tuple[str, ...]) -> str:
    lines = ["# Priorities", ""]
    for index, entry in enumerate(priorities, start=1):
        lines.append(f"## Priority {index}")
        lines.append("")
        lines.append(entry)
        lines.append("")
    return _normalize_markdown("\n".join(lines))


def _render_runtime_overrides_markdown(runtime_overrides: tuple[str, ...]) -> str:
    lines = ["## Runtime Overrides", ""]
    for index, entry in enumerate(runtime_overrides, start=1):
        lines.append(f"### Override {index}")
        lines.append("")
        lines.append(entry)
        lines.append("")
    return _normalize_markdown("\n".join(lines))


def _render_instructions_markdown(
    *,
    run_mode: str,
    provider: str,
    role_markdown: str,
    agent_markdown: str,
    priorities_markdown: str | None,
    runtime_overrides: tuple[str, ...],
    provider_header: str,
    provider_suffix: str,
) -> str:
    lines = [
        "# Compiled Instructions",
        "",
        f"Run mode: `{run_mode}`",
        f"Provider: `{provider}`",
        "",
    ]
    if provider_header:
        lines.extend(["## Provider Header", "", provider_header, ""])
    lines.extend(["## Role Source", "", role_markdown.strip(), ""])
    lines.extend(["## Agent Source", "", agent_markdown.strip(), ""])
    if priorities_markdown:
        lines.extend(["## Priorities Source", "", priorities_markdown.strip(), ""])
    if runtime_overrides:
        lines.extend([_render_runtime_overrides_markdown(runtime_overrides).strip(), ""])
    if provider_suffix:
        lines.extend(["## Provider Suffix", "", provider_suffix, ""])
    return _normalize_markdown("\n".join(lines))


@dataclass(frozen=True)
class InstructionCompileInput:
    run_mode: str
    provider: str
    role_markdown: str = ""
    agent_markdown: str = ""
    priorities: tuple[str, ...] = tuple()
    runtime_overrides: tuple[str, ...] = tuple()
    provider_header: str = ""
    provider_suffix: str = ""
    source_ids: dict[str, int | None] = field(default_factory=dict)
    source_versions: dict[str, str | None] = field(default_factory=dict)
    generated_at: str | None = None


@dataclass(frozen=True)
class CompiledInstructionPackage:
    run_mode: str
    provider: str
    artifacts: dict[str, str]
    manifest: dict[str, Any]
    manifest_hash: str


def compile_instruction_package(
    compile_input: InstructionCompileInput,
) -> CompiledInstructionPackage:
    run_mode = str(compile_input.run_mode or "").strip() or "task"
    provider = str(compile_input.provider or "").strip() or "unknown"
    role_markdown = _normalize_markdown(compile_input.role_markdown)
    if not role_markdown:
        role_markdown = "# Role\n\nNo role instructions resolved.\n"
    agent_markdown = _normalize_markdown(compile_input.agent_markdown)
    if not agent_markdown:
        agent_markdown = "# Agent\n\nNo agent instructions resolved.\n"
    runtime_overrides = _normalize_runtime_overrides(compile_input.runtime_overrides)
    priorities = _normalize_priorities(compile_input.priorities)
    priorities_markdown: str | None = None
    if run_mode == "autorun" and priorities:
        priorities_markdown = _render_priorities_markdown(priorities)
    provider_header = _normalize_markdown(compile_input.provider_header).strip()
    provider_suffix = _normalize_markdown(compile_input.provider_suffix).strip()
    instructions_markdown = _render_instructions_markdown(
        run_mode=run_mode,
        provider=provider,
        role_markdown=role_markdown,
        agent_markdown=agent_markdown,
        priorities_markdown=priorities_markdown,
        runtime_overrides=runtime_overrides,
        provider_header=provider_header,
        provider_suffix=provider_suffix,
    )

    artifacts: dict[str, str] = {
        ROLE_FILENAME: role_markdown,
        AGENT_FILENAME: agent_markdown,
        INSTRUCTIONS_FILENAME: instructions_markdown,
    }
    if priorities_markdown:
        artifacts[PRIORITIES_FILENAME] = priorities_markdown

    artifact_manifest: dict[str, dict[str, Any]] = {}
    total_size_bytes = 0
    for file_name in sorted(artifacts):
        content = artifacts[file_name]
        size_bytes = len(content.encode("utf-8"))
        total_size_bytes += size_bytes
        artifact_manifest[file_name] = {
            "path": file_name,
            "sha256": _sha256_text(content),
            "size_bytes": size_bytes,
        }

    fingerprint = {
        "package_version": 1,
        "run_mode": run_mode,
        "provider": provider,
        "source_ids": {
            key: compile_input.source_ids[key]
            for key in sorted(compile_input.source_ids)
        },
        "source_versions": {
            key: compile_input.source_versions[key]
            for key in sorted(compile_input.source_versions)
        },
        "artifact_manifest": artifact_manifest,
    }
    manifest_hash = _sha256_text(
        json.dumps(fingerprint, sort_keys=True, separators=(",", ":"))
    )
    generated_at = compile_input.generated_at or _utcnow_iso()
    manifest = {
        "package_version": 1,
        "generated_at": generated_at,
        "hash_algorithm": "sha256",
        "manifest_hash": manifest_hash,
        "run_mode": run_mode,
        "provider": provider,
        "source_ids": fingerprint["source_ids"],
        "source_versions": fingerprint["source_versions"],
        "includes_priorities": priorities_markdown is not None,
        "instruction_size_bytes": artifact_manifest[INSTRUCTIONS_FILENAME]["size_bytes"],
        "total_size_bytes": total_size_bytes,
        "artifacts": artifact_manifest,
    }
    return CompiledInstructionPackage(
        run_mode=run_mode,
        provider=provider,
        artifacts=artifacts,
        manifest=manifest,
        manifest_hash=manifest_hash,
    )

