from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import SKILL_STATUS_CHOICES, Skill, SkillFile, SkillVersion

SKILL_BUNDLE_SCHEMA_VERSION = 1
MAX_SKILL_MD_BYTES = 64 * 1024
MAX_SKILL_FILE_BYTES = 256 * 1024
MAX_SKILL_PACKAGE_BYTES = 1024 * 1024

_ALLOWED_ROOT_DIRS = ("scripts", "references", "assets")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_VERSION_RE = re.compile(r"^(?:v)?([0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?)$")


@dataclass(frozen=True)
class SkillValidationError:
    code: str
    message: str
    path: str | None = None
    field: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "field": self.field,
        }


class SkillPackageValidationError(ValueError):
    def __init__(self, errors: Sequence[SkillValidationError]):
        self.errors = list(errors)
        super().__init__("Skill package validation failed")


@dataclass(frozen=True)
class SkillPackageMetadata:
    name: str
    display_name: str
    description: str
    version: str
    status: str


@dataclass(frozen=True)
class SkillPackageFile:
    path: str
    content: str
    checksum: str
    size_bytes: int


@dataclass(frozen=True)
class SkillPackage:
    metadata: SkillPackageMetadata
    files: tuple[SkillPackageFile, ...]
    manifest: dict[str, Any]
    manifest_hash: str


@dataclass(frozen=True)
class SkillImportResult:
    skill_id: int
    skill_name: str
    version_id: int
    version: str
    file_count: int


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_skill_slug(value: str | None) -> str:
    lowered = (value or "").strip().lower()
    cleaned = _SLUG_RE.sub("-", lowered).strip("-")
    return cleaned or "skill"


def normalize_skill_display_name(value: str | None) -> str:
    collapsed = " ".join((value or "").strip().split())
    return collapsed or "Skill"


def normalize_skill_description(value: str | None) -> str:
    return (value or "").strip()


def normalize_skill_version(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    match = _VERSION_RE.match(raw)
    if not match:
        return ""
    return match.group(1)


def normalize_skill_status(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in SKILL_STATUS_CHOICES:
        return normalized
    return ""


def format_validation_errors(
    errors: Sequence[SkillValidationError],
) -> list[dict[str, str | None]]:
    return [error.as_dict() for error in errors]


def _normalize_relative_path(raw_path: str) -> str:
    posix_value = raw_path.replace("\\", "/")
    rel = PurePosixPath(posix_value)
    if rel.is_absolute():
        return ""
    normalized_parts: list[str] = []
    for part in rel.parts:
        if part in {"", ".", ".."}:
            return ""
        normalized_parts.append(part)
    return "/".join(normalized_parts)


def _parse_skill_markdown_front_matter(content: str) -> dict[str, str]:
    if not content.startswith("---\n"):
        return {}
    end = content.find("\n---\n", 4)
    if end < 0:
        return {}
    payload = content[4:end]
    metadata: dict[str, str] = {}
    for line in payload.splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        # We only read top-level `key: value` lines for deterministic parsing.
        if line[0].isspace() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        if not key:
            continue
        metadata[key] = value.strip().strip("\"'")
    return metadata


def _validate_file_paths(paths: Iterable[str]) -> list[SkillValidationError]:
    errors: list[SkillValidationError] = []
    seen: set[str] = set()
    for raw_path in paths:
        normalized = _normalize_relative_path(raw_path)
        if not normalized:
            errors.append(
                SkillValidationError(
                    code="invalid_path",
                    message="Skill file paths must be relative and path-safe.",
                    path=raw_path,
                )
            )
            continue
        if normalized in seen:
            errors.append(
                SkillValidationError(
                    code="duplicate_path",
                    message="Duplicate skill file path.",
                    path=normalized,
                )
            )
            continue
        seen.add(normalized)
        if normalized == "SKILL.md":
            continue
        root = normalized.split("/", 1)[0]
        if root not in _ALLOWED_ROOT_DIRS:
            errors.append(
                SkillValidationError(
                    code="disallowed_path",
                    message=(
                        "Only SKILL.md at root and files under scripts/, "
                        "references/, or assets/ are allowed."
                    ),
                    path=normalized,
                )
            )
    return errors


def _validate_file_sizes(files: Sequence[tuple[str, str]]) -> list[SkillValidationError]:
    errors: list[SkillValidationError] = []
    total_bytes = 0
    has_skill_md = False
    for path, content in files:
        payload = content.encode("utf-8")
        size_bytes = len(payload)
        total_bytes += size_bytes
        if path == "SKILL.md":
            has_skill_md = True
            if size_bytes > MAX_SKILL_MD_BYTES:
                errors.append(
                    SkillValidationError(
                        code="skill_md_too_large",
                        message=f"SKILL.md exceeds {MAX_SKILL_MD_BYTES} bytes.",
                        path=path,
                    )
                )
            continue
        if size_bytes > MAX_SKILL_FILE_BYTES:
            errors.append(
                SkillValidationError(
                    code="file_too_large",
                    message=(
                        f"Skill file exceeds {MAX_SKILL_FILE_BYTES} bytes."
                    ),
                    path=path,
                )
            )
    if total_bytes > MAX_SKILL_PACKAGE_BYTES:
        errors.append(
            SkillValidationError(
                code="package_too_large",
                message=f"Skill package exceeds {MAX_SKILL_PACKAGE_BYTES} bytes.",
            )
        )
    if not has_skill_md:
        errors.append(
            SkillValidationError(
                code="missing_skill_md",
                message="Skill package must include SKILL.md at package root.",
                path="SKILL.md",
            )
        )
    return errors


def _resolve_metadata(
    skill_md_content: str,
    overrides: dict[str, str] | None,
) -> tuple[SkillPackageMetadata | None, list[SkillValidationError]]:
    errors: list[SkillValidationError] = []
    front_matter = _parse_skill_markdown_front_matter(skill_md_content)
    source = {**front_matter, **(overrides or {})}

    raw_display_name = source.get("display_name") or source.get("name") or ""
    display_name = normalize_skill_display_name(raw_display_name)

    raw_name = source.get("name") or display_name
    name = normalize_skill_slug(raw_name)

    description = normalize_skill_description(source.get("description"))
    if not description:
        errors.append(
            SkillValidationError(
                code="missing_metadata",
                message="Skill metadata requires a non-empty description.",
                field="description",
            )
        )

    version = normalize_skill_version(source.get("version"))
    if not version:
        errors.append(
            SkillValidationError(
                code="invalid_version",
                message="Skill metadata version must be semver (for example, 1.0.0).",
                field="version",
            )
        )

    status = normalize_skill_status(source.get("status") or "draft")
    if not status:
        errors.append(
            SkillValidationError(
                code="invalid_status",
                message=(
                    "Skill metadata status must be one of: "
                    + ", ".join(SKILL_STATUS_CHOICES)
                    + "."
                ),
                field="status",
            )
        )

    if errors:
        return None, errors
    return (
        SkillPackageMetadata(
            name=name,
            display_name=display_name,
            description=description,
            version=version,
            status=status,
        ),
        [],
    )


def build_skill_package(
    files: Sequence[tuple[str, str]],
    *,
    metadata_overrides: dict[str, str] | None = None,
) -> SkillPackage:
    normalized_files = [(_normalize_relative_path(path), content) for path, content in files]

    errors: list[SkillValidationError] = []
    errors.extend(_validate_file_paths(path for path, _ in files))

    valid_files = [(path, content) for path, content in normalized_files if path]
    valid_files.sort(key=lambda item: item[0])

    errors.extend(_validate_file_sizes(valid_files))

    skill_md_content = ""
    for path, content in valid_files:
        if path == "SKILL.md":
            skill_md_content = content
            break

    metadata, metadata_errors = _resolve_metadata(skill_md_content, metadata_overrides)
    errors.extend(metadata_errors)

    if errors:
        raise SkillPackageValidationError(errors)

    package_files: list[SkillPackageFile] = []
    for path, content in valid_files:
        size_bytes = len(content.encode("utf-8"))
        package_files.append(
            SkillPackageFile(
                path=path,
                content=content,
                checksum=_sha256_text(content),
                size_bytes=size_bytes,
            )
        )

    files_manifest = [
        {
            "path": skill_file.path,
            "checksum": skill_file.checksum,
            "size_bytes": skill_file.size_bytes,
        }
        for skill_file in package_files
    ]

    assert metadata is not None
    manifest = {
        "schema_version": SKILL_BUNDLE_SCHEMA_VERSION,
        "metadata": asdict(metadata),
        "limits": {
            "max_skill_md_bytes": MAX_SKILL_MD_BYTES,
            "max_file_bytes": MAX_SKILL_FILE_BYTES,
            "max_package_bytes": MAX_SKILL_PACKAGE_BYTES,
        },
        "files": files_manifest,
    }
    manifest_hash = _sha256_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )

    return SkillPackage(
        metadata=metadata,
        files=tuple(package_files),
        manifest=manifest,
        manifest_hash=manifest_hash,
    )


def build_skill_package_from_directory(
    package_dir: str | Path,
    *,
    metadata_overrides: dict[str, str] | None = None,
) -> SkillPackage:
    root = Path(package_dir).expanduser().resolve()
    if not root.is_dir():
        raise SkillPackageValidationError(
            [
                SkillValidationError(
                    code="invalid_package_dir",
                    message="Skill package path must be an existing directory.",
                    path=str(package_dir),
                )
            ]
        )

    collected: list[tuple[str, str]] = []
    errors: list[SkillValidationError] = []
    for file_path in sorted(root.rglob("*")):
        if file_path.is_dir():
            continue
        if file_path.is_symlink():
            errors.append(
                SkillValidationError(
                    code="symlink_not_allowed",
                    message="Symlinked files are not allowed in skill packages.",
                    path=str(file_path.relative_to(root).as_posix()),
                )
            )
            continue
        relative_path = file_path.relative_to(root).as_posix()
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            errors.append(
                SkillValidationError(
                    code="non_utf8_file",
                    message="Skill package files must be UTF-8 text.",
                    path=relative_path,
                )
            )
            continue
        collected.append((relative_path, content))

    if errors:
        raise SkillPackageValidationError(errors)

    return build_skill_package(collected, metadata_overrides=metadata_overrides)


def serialize_skill_bundle(package: SkillPackage, *, pretty: bool = False) -> str:
    payload = {
        "schema_version": SKILL_BUNDLE_SCHEMA_VERSION,
        "metadata": asdict(package.metadata),
        "manifest": package.manifest,
        "manifest_hash": package.manifest_hash,
        "files": [
            {
                "path": skill_file.path,
                "content": skill_file.content,
            }
            for skill_file in package.files
        ],
    }
    if pretty:
        return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_skill_bundle(payload: str | dict[str, Any]) -> SkillPackage:
    data: dict[str, Any]
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise SkillPackageValidationError(
                [
                    SkillValidationError(
                        code="invalid_bundle_json",
                        message="Skill bundle JSON is invalid.",
                    )
                ]
            ) from exc
        if not isinstance(parsed, dict):
            raise SkillPackageValidationError(
                [
                    SkillValidationError(
                        code="invalid_bundle_payload",
                        message="Skill bundle payload must be a JSON object.",
                    )
                ]
            )
        data = parsed
    else:
        data = payload

    files_raw = data.get("files")
    if not isinstance(files_raw, list):
        raise SkillPackageValidationError(
            [
                SkillValidationError(
                    code="invalid_bundle_payload",
                    message="Skill bundle must include a files list.",
                    field="files",
                )
            ]
        )

    files: list[tuple[str, str]] = []
    file_errors: list[SkillValidationError] = []
    for index, entry in enumerate(files_raw):
        if not isinstance(entry, dict):
            file_errors.append(
                SkillValidationError(
                    code="invalid_file_entry",
                    message="Skill file entries must be objects.",
                    path=f"files[{index}]",
                )
            )
            continue
        path = entry.get("path")
        content = entry.get("content")
        if not isinstance(path, str) or not isinstance(content, str):
            file_errors.append(
                SkillValidationError(
                    code="invalid_file_entry",
                    message="Skill file entries require string path and content fields.",
                    path=f"files[{index}]",
                )
            )
            continue
        files.append((path, content))

    if file_errors:
        raise SkillPackageValidationError(file_errors)

    metadata_payload = data.get("metadata")
    metadata_overrides: dict[str, str] = {}
    if isinstance(metadata_payload, dict):
        for key in ("name", "display_name", "description", "version", "status"):
            value = metadata_payload.get(key)
            if isinstance(value, str):
                metadata_overrides[key] = value

    package = build_skill_package(files, metadata_overrides=metadata_overrides)

    expected_hash = data.get("manifest_hash")
    if isinstance(expected_hash, str) and expected_hash.strip():
        if expected_hash.strip() != package.manifest_hash:
            raise SkillPackageValidationError(
                [
                    SkillValidationError(
                        code="manifest_hash_mismatch",
                        message="Skill bundle manifest hash does not match file content.",
                        field="manifest_hash",
                    )
                ]
            )

    return package


def export_skill_package_from_db(
    session: Session,
    *,
    skill_name: str | None = None,
    skill_id: int | None = None,
    version: str | None = None,
) -> SkillPackage:
    if not skill_name and not skill_id:
        raise ValueError("skill_name or skill_id is required")

    query = select(Skill)
    if skill_id is not None:
        query = query.where(Skill.id == skill_id)
    else:
        query = query.where(Skill.name == str(skill_name))

    skill = session.execute(query).scalars().first()
    if skill is None:
        raise ValueError("Skill was not found")

    version_query = select(SkillVersion).where(SkillVersion.skill_id == skill.id)
    if version:
        version_query = version_query.where(SkillVersion.version == version)
        version_query = version_query.order_by(SkillVersion.id.desc())
    else:
        version_query = version_query.order_by(SkillVersion.id.desc())

    selected_version = session.execute(version_query).scalars().first()
    if selected_version is None:
        raise ValueError("Skill version was not found")

    skill_files = (
        session.execute(
            select(SkillFile)
            .where(SkillFile.skill_version_id == selected_version.id)
            .order_by(SkillFile.path.asc())
        )
        .scalars()
        .all()
    )

    package_files = [(file.path, file.content) for file in skill_files]
    metadata_overrides = {
        "name": skill.name,
        "display_name": skill.display_name,
        "description": skill.description or "",
        "version": selected_version.version,
        "status": skill.status,
    }
    return build_skill_package(package_files, metadata_overrides=metadata_overrides)


def import_skill_package_to_db(
    session: Session,
    package: SkillPackage,
    *,
    source_type: str = "import",
    source_ref: str | None = None,
    actor: str | None = None,
) -> SkillImportResult:
    existing_skill = session.execute(
        select(Skill).where(Skill.name == package.metadata.name)
    ).scalars().first()

    if existing_skill is None:
        existing_skill = Skill.create(
            session,
            name=package.metadata.name,
            display_name=package.metadata.display_name,
            description=package.metadata.description,
            status=package.metadata.status,
            source_type=source_type,
            source_ref=source_ref,
            created_by=actor,
            updated_by=actor,
        )
    else:
        existing_skill.display_name = package.metadata.display_name
        existing_skill.description = package.metadata.description
        existing_skill.status = package.metadata.status
        existing_skill.source_type = source_type
        existing_skill.source_ref = source_ref
        existing_skill.updated_by = actor

    version_exists = session.execute(
        select(SkillVersion).where(
            SkillVersion.skill_id == existing_skill.id,
            SkillVersion.version == package.metadata.version,
        )
    ).scalars().first()
    if version_exists is not None:
        raise ValueError(
            f"Skill '{existing_skill.name}' already has version '{package.metadata.version}'."
        )

    skill_version = SkillVersion.create(
        session,
        skill_id=existing_skill.id,
        version=package.metadata.version,
        manifest_json=json.dumps(package.manifest, indent=2, sort_keys=True),
        manifest_hash=package.manifest_hash,
    )

    for entry in package.files:
        SkillFile.create(
            session,
            skill_version_id=skill_version.id,
            path=entry.path,
            content=entry.content,
            checksum=entry.checksum,
            size_bytes=entry.size_bytes,
        )

    return SkillImportResult(
        skill_id=existing_skill.id,
        skill_name=existing_skill.name,
        version_id=skill_version.id,
        version=skill_version.version,
        file_count=len(package.files),
    )
