from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select

from core.models import (
    Script,
    ensure_legacy_skill_script_writable,
    is_legacy_skill_script_type,
)
from storage.script_storage import ensure_script_file, remove_script_file, write_script_file

from constants import SCRIPT_TYPE_KEYS


def _ensure_script_storage(session, script: Script) -> None:
    path = ensure_script_file(
        script.id,
        script.file_name,
        script.content,
        script.file_path,
    )
    if script.file_path != str(path):
        script.file_path = str(path)
        session.flush()


def _sync_script_storage(session, script: Script, previous_path: str | None) -> None:
    path = write_script_file(script.id, script.file_name, script.content)
    script.file_path = str(path)
    session.flush()
    if previous_path and previous_path != script.file_path:
        remove_script_file(previous_path)


def _normalize_script_type_key(raw: str) -> str:
    if not raw:
        raise ValueError("Script type is required.")
    key = raw.strip().lower().replace("-", "_").replace(" ", "_")
    if key in SCRIPT_TYPE_KEYS:
        script_type = SCRIPT_TYPE_KEYS[key]
        ensure_legacy_skill_script_writable(script_type)
        return script_type
    if key in SCRIPT_TYPE_KEYS.values():
        ensure_legacy_skill_script_writable(key)
        return key
    valid = ", ".join(sorted(SCRIPT_TYPE_KEYS))
    raise ValueError(f"Unknown script type '{raw}'. Use: {valid}.")


def _parse_script_ids_by_type(
    raw: dict[str, Any] | None,
) -> dict[str, list[int]]:
    grouped = {value: [] for value in SCRIPT_TYPE_KEYS.values()}
    if not raw:
        return grouped
    if not isinstance(raw, dict):
        raise ValueError("script_ids_by_type must be a dictionary.")
    for key, value in raw.items():
        script_type = _normalize_script_type_key(str(key))
        if value is None:
            ids: list[int] = []
        elif isinstance(value, list):
            ids = []
            for item in value:
                if isinstance(item, bool):
                    raise ValueError("Script ids must be integers.")
                if isinstance(item, int):
                    ids.append(item)
                elif isinstance(item, str) and item.strip().isdigit():
                    ids.append(int(item.strip()))
                else:
                    raise ValueError("Script ids must be integers.")
        else:
            raise ValueError("Script ids must be a list.")
        grouped[script_type] = ids
    return grouped


def _resolve_script_ids_by_type(
    session,
    script_ids_by_type: dict[str, list[int]],
) -> dict[str, list[int]]:
    all_ids: list[int] = []
    for ids in script_ids_by_type.values():
        all_ids.extend(ids)
    if not all_ids:
        return script_ids_by_type
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("Duplicate scripts are not allowed.")
    scripts = (
        session.execute(select(Script).where(Script.id.in_(all_ids)))
        .scalars()
        .all()
    )
    scripts_by_id = {script.id: script for script in scripts}
    if len(scripts_by_id) != len(set(all_ids)):
        raise ValueError("One or more scripts were not found.")
    for script_type, ids in script_ids_by_type.items():
        ensure_legacy_skill_script_writable(script_type)
        for script_id in ids:
            script = scripts_by_id[script_id]
            if is_legacy_skill_script_type(script.script_type):
                raise ValueError(
                    "Legacy script_type=skill records are disabled. Use Skills attachments."
                )
            if script.script_type != script_type:
                raise ValueError("Script selection is invalid.")
    return script_ids_by_type


def _set_script_links(
    session,
    table,
    fk_name: str,
    fk_value: int,
    script_ids_by_type: dict[str, list[int]],
) -> None:
    session.execute(delete(table).where(table.c[fk_name] == fk_value))
    rows: list[dict[str, int]] = []
    for ids in script_ids_by_type.values():
        for position, script_id in enumerate(ids, start=1):
            rows.append(
                {
                    fk_name: fk_value,
                    "script_id": script_id,
                    "position": position,
                }
            )
    if rows:
        session.execute(table.insert(), rows)
