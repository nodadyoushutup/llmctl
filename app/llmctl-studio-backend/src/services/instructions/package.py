from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil

from services.instructions.compiler import (
    CompiledInstructionPackage,
    MANIFEST_FILENAME,
)

INSTRUCTIONS_SUBDIR = Path(".llmctl") / "instructions"


def _write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@dataclass(frozen=True)
class MaterializedInstructionPackage:
    package_dir: Path
    manifest_hash: str
    artifact_paths: dict[str, Path]
    materialized_paths: tuple[str, ...]


def materialize_instruction_package(
    workspace: Path,
    compiled: CompiledInstructionPackage,
) -> MaterializedInstructionPackage:
    package_dir = workspace / INSTRUCTIONS_SUBDIR
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)

    artifact_paths: dict[str, Path] = {}
    for file_name in sorted(compiled.artifacts):
        path = package_dir / file_name
        _write_text_file(path, compiled.artifacts[file_name])
        artifact_paths[file_name] = path

    manifest_path = package_dir / MANIFEST_FILENAME
    manifest_content = json.dumps(compiled.manifest, indent=2, sort_keys=True)
    _write_text_file(manifest_path, manifest_content + "\n")
    artifact_paths[MANIFEST_FILENAME] = manifest_path

    materialized_paths = tuple(
        str(artifact_paths[name]) for name in sorted(artifact_paths)
    )
    return MaterializedInstructionPackage(
        package_dir=package_dir,
        manifest_hash=compiled.manifest_hash,
        artifact_paths=artifact_paths,
        materialized_paths=materialized_paths,
    )

