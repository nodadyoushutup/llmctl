from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

import core.db as core_db
from core.config import Config
from core.db import create_session
from services.skills import (
    MAX_SKILL_MD_BYTES,
    SkillPackageValidationError,
    build_skill_package,
    build_skill_package_from_directory,
    encode_binary_skill_content,
    export_skill_package_from_db,
    format_validation_errors,
    import_skill_package_to_db,
    load_skill_bundle,
    serialize_skill_bundle,
)


class StudioDbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_dir / 'skills-stage2.sqlite3'}"
        self._reset_engine()

    def tearDown(self) -> None:
        self._dispose_engine()
        Config.SQLALCHEMY_DATABASE_URI = self._orig_db_uri
        self._tmp.cleanup()

    def _dispose_engine(self) -> None:
        if core_db._engine is not None:
            core_db._engine.dispose()
        core_db._engine = None
        core_db.SessionLocal = None

    def _reset_engine(self) -> None:
        self._dispose_engine()
        core_db.init_engine(Config.SQLALCHEMY_DATABASE_URI)
        core_db.init_db()


class SkillsStage2Tests(StudioDbTestCase):
    def _write_package(self, package_dir: Path, *, skill_md: str, script: str = "echo ok\n") -> None:
        package_dir.mkdir(parents=True, exist_ok=True)
        (package_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
        scripts_dir = package_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        (scripts_dir / "run.sh").write_text(script, encoding="utf-8")

    def test_build_package_from_directory_normalizes_metadata(self) -> None:
        package_root = Path(self._tmp.name) / "pkg-1"
        self._write_package(
            package_root,
            skill_md=(
                "---\n"
                "name:  My Skill  \n"
                "display_name:  My Skill  \n"
                "description: Uses deterministic setup.\n"
                "version: v1.2.3\n"
                "status: ACTIVE\n"
                "---\n\n"
                "# My Skill\n"
            ),
        )

        package = build_skill_package_from_directory(package_root)

        self.assertEqual("my-skill", package.metadata.name)
        self.assertEqual("My Skill", package.metadata.display_name)
        self.assertEqual("1.2.3", package.metadata.version)
        self.assertEqual("active", package.metadata.status)
        self.assertEqual(2, len(package.files))
        self.assertEqual("SKILL.md", package.files[0].path)
        self.assertEqual("scripts/run.sh", package.files[1].path)
        self.assertTrue(package.manifest_hash)

    def test_build_package_rejects_disallowed_root_files(self) -> None:
        package_root = Path(self._tmp.name) / "pkg-2"
        self._write_package(
            package_root,
            skill_md=(
                "---\n"
                "name: bad-pkg\n"
                "display_name: Bad Pkg\n"
                "description: Testing disallowed root files.\n"
                "version: 1.0.0\n"
                "status: draft\n"
                "---\n"
            ),
        )
        (package_root / "README.txt").write_text("not allowed", encoding="utf-8")

        with self.assertRaises(SkillPackageValidationError) as exc_info:
            build_skill_package_from_directory(package_root)

        errors = format_validation_errors(exc_info.exception.errors)
        codes = {str(entry["code"]) for entry in errors}
        self.assertIn("disallowed_path", codes)

    def test_build_package_enforces_skill_md_size_limit(self) -> None:
        oversized = "x" * (MAX_SKILL_MD_BYTES + 1)
        files = [
            (
                "SKILL.md",
                (
                    "---\n"
                    "name: too-big\n"
                    "display_name: Too Big\n"
                    "description: desc\n"
                    "version: 1.0.0\n"
                    "status: draft\n"
                    "---\n\n"
                )
                + oversized,
            )
        ]

        with self.assertRaises(SkillPackageValidationError) as exc_info:
            build_skill_package(files)

        errors = format_validation_errors(exc_info.exception.errors)
        codes = {str(entry["code"]) for entry in errors}
        self.assertIn("skill_md_too_large", codes)

    def test_bundle_roundtrip_is_deterministic(self) -> None:
        package = build_skill_package(
            [
                (
                    "SKILL.md",
                    (
                        "---\n"
                        "name: deterministic\n"
                        "display_name: Deterministic\n"
                        "description: Deterministic bundle output.\n"
                        "version: 2.0.0\n"
                        "status: active\n"
                        "---\n"
                    ),
                ),
                ("scripts/run.sh", "echo deterministic\n"),
            ]
        )

        first_payload = serialize_skill_bundle(package)
        loaded = load_skill_bundle(first_payload)
        second_payload = serialize_skill_bundle(loaded)

        self.assertEqual(package.manifest_hash, loaded.manifest_hash)
        self.assertEqual(first_payload, second_payload)

    def test_import_export_roundtrip_and_duplicate_version_reject(self) -> None:
        package = build_skill_package(
            [
                (
                    "SKILL.md",
                    (
                        "---\n"
                        "name: db-skill\n"
                        "display_name: DB Skill\n"
                        "description: Roundtrip through DB.\n"
                        "version: 1.0.0\n"
                        "status: active\n"
                        "---\n"
                    ),
                ),
                ("scripts/run.sh", "echo db\n"),
            ]
        )

        session = create_session()
        try:
            result = import_skill_package_to_db(
                session,
                package,
                source_type="import",
                source_ref="unit-test",
                actor="tester",
            )
            session.commit()
            self.assertEqual("db-skill", result.skill_name)

            exported = export_skill_package_from_db(
                session,
                skill_name="db-skill",
                version="1.0.0",
            )
            self.assertEqual(package.manifest_hash, exported.manifest_hash)

            with self.assertRaises(ValueError):
                import_skill_package_to_db(
                    session,
                    package,
                    source_type="import",
                    source_ref="unit-test",
                    actor="tester",
                )
        finally:
            session.rollback()
            session.close()

        bundle = json.loads(serialize_skill_bundle(package))
        self.assertEqual("db-skill", bundle["metadata"]["name"])

    def test_build_package_supports_binary_envelope_files(self) -> None:
        binary_payload = b"%PDF-1.7\nbinary payload\n"
        package = build_skill_package(
            [
                (
                    "SKILL.md",
                    (
                        "---\n"
                        "name: binary-skill\n"
                        "display_name: Binary Skill\n"
                        "description: Includes binary files.\n"
                        "version: 1.0.0\n"
                        "status: active\n"
                        "---\n\n"
                        "# Binary Skill\n"
                    ),
                ),
                ("assets/guide.pdf", encode_binary_skill_content(binary_payload)),
            ]
        )

        self.assertEqual(2, len(package.files))
        binary_file = next(item for item in package.files if item.path == "assets/guide.pdf")
        self.assertEqual(len(binary_payload), binary_file.size_bytes)
        self.assertTrue(binary_file.checksum)

        loaded = load_skill_bundle(serialize_skill_bundle(package))
        self.assertEqual(package.manifest_hash, loaded.manifest_hash)

    def test_build_package_rejects_invalid_binary_envelope_payload(self) -> None:
        with self.assertRaises(SkillPackageValidationError) as exc_info:
            build_skill_package(
                [
                    (
                        "SKILL.md",
                        (
                            "---\n"
                            "name: bad-binary\n"
                            "display_name: Bad Binary\n"
                            "description: invalid binary envelope.\n"
                            "version: 1.0.0\n"
                            "status: active\n"
                            "---\n"
                        ),
                    ),
                    ("assets/image.png", "__LLMCTL_BINARY_BASE64__:!!!not-base64!!!"),
                ]
            )

        errors = format_validation_errors(exc_info.exception.errors)
        codes = {str(entry["code"]) for entry in errors}
        self.assertIn("invalid_binary_payload", codes)


if __name__ == "__main__":
    unittest.main()
