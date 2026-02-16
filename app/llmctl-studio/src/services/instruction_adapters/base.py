from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Protocol

from services.instructions.compiler import (
    CompiledInstructionPackage,
    INSTRUCTIONS_FILENAME,
)

FRONTIER_INSTRUCTION_FILENAMES: dict[str, str] = {
    "codex": "AGENTS.md",
    "gemini": "GEMINI.md",
    "claude": "CLAUDE.md",
}
NON_FRONTIER_DEFAULT_INSTRUCTION_FILENAME = "AGENT.md"
_MARKDOWN_FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def is_frontier_instruction_provider(provider: str | None) -> bool:
    normalized = str(provider or "").strip().lower()
    return normalized in FRONTIER_INSTRUCTION_FILENAMES


def validate_agent_markdown_filename(value: str | None) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError("Instruction markdown filename is required.")
    if cleaned.startswith("."):
        raise ValueError("Instruction markdown filename cannot start with '.'.")
    if not cleaned.endswith(".md"):
        raise ValueError("Instruction markdown filename must end with '.md'.")
    if not _MARKDOWN_FILENAME_RE.fullmatch(cleaned):
        raise ValueError(
            "Instruction markdown filename may only contain A-Z, a-z, 0-9, '.', '_', and '-'."
        )
    return cleaned


def resolve_agent_markdown_filename(
    *,
    provider: str | None,
    configured_filename: str | None = None,
) -> str:
    normalized_provider = str(provider or "").strip().lower()
    fixed = FRONTIER_INSTRUCTION_FILENAMES.get(normalized_provider)
    if fixed:
        return fixed
    candidate = str(configured_filename or "").strip()
    if not candidate:
        return NON_FRONTIER_DEFAULT_INSTRUCTION_FILENAME
    return validate_agent_markdown_filename(candidate)


def compiled_instructions_markdown(compiled: CompiledInstructionPackage) -> str:
    return str(compiled.artifacts.get(INSTRUCTIONS_FILENAME) or "")


def write_compiled_instruction_file(
    workspace: Path,
    file_name: str,
    compiled: CompiledInstructionPackage,
) -> Path:
    path = workspace / file_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(compiled_instructions_markdown(compiled), encoding="utf-8")
    return path


@dataclass(frozen=True)
class InstructionAdapterDescriptor:
    provider: str
    adapter: str
    native_filename: str | None
    supports_native: bool


@dataclass(frozen=True)
class InstructionAdapterMaterializationResult:
    mode: str
    adapter: str
    materialized_paths: tuple[str, ...]
    warnings: tuple[str, ...] = tuple()


class InstructionAdapter(Protocol):
    def materialize(
        self,
        compiled: CompiledInstructionPackage,
        *,
        workspace: Path,
        runtime_home: Path,
        codex_home: Path | None = None,
    ) -> InstructionAdapterMaterializationResult:
        ...

    def fallback_payload(self, compiled: CompiledInstructionPackage) -> dict[str, object] | str:
        ...

    def describe(self) -> InstructionAdapterDescriptor:
        ...
