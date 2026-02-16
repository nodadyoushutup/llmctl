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
        description="Validate a Skill package directory or JSON bundle.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--path",
        help="Path to a skill package directory (contains SKILL.md).",
    )
    source.add_argument(
        "--bundle",
        help="Path to a serialized skill bundle JSON file.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print output JSON.",
    )
    return parser.parse_args()


def _emit(payload: dict[str, object], *, pretty: bool) -> None:
    if pretty:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, sort_keys=True))


def main() -> int:
    _bootstrap()
    args = _parse_args()

    from services.skills import (
        SkillPackageValidationError,
        build_skill_package_from_directory,
        format_validation_errors,
        load_skill_bundle,
    )

    try:
        if args.path:
            package = build_skill_package_from_directory(args.path)
        else:
            bundle_payload = Path(args.bundle).read_text(encoding="utf-8")
            package = load_skill_bundle(bundle_payload)
    except SkillPackageValidationError as exc:
        _emit(
            {
                "valid": False,
                "errors": format_validation_errors(exc.errors),
            },
            pretty=args.pretty,
        )
        return 1

    _emit(
        {
            "valid": True,
            "metadata": {
                "name": package.metadata.name,
                "display_name": package.metadata.display_name,
                "description": package.metadata.description,
                "version": package.metadata.version,
                "status": package.metadata.status,
            },
            "manifest_hash": package.manifest_hash,
            "file_count": len(package.files),
        },
        pretty=args.pretty,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
