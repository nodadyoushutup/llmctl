from __future__ import annotations

from pathlib import Path

from core.config import Config


def _safe_file_name(file_name: str, fallback: str) -> str:
    cleaned = Path(file_name).name if file_name else ""
    if not cleaned or cleaned in {".", ".."}:
        return fallback
    return cleaned


def script_storage_dir(script_id: int) -> Path:
    return Path(Config.SCRIPTS_DIR) / f"script-{script_id}"


def build_script_path(script_id: int, file_name: str) -> Path:
    safe_name = _safe_file_name(file_name, f"script-{script_id}")
    return script_storage_dir(script_id) / safe_name


def write_script_file(script_id: int, file_name: str, content: str) -> Path:
    path = build_script_path(script_id, file_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content or "", encoding="utf-8")
    try:
        path.chmod(0o755)
    except OSError:
        pass
    return path


def read_script_file(file_path: str | None) -> str:
    if not file_path:
        return ""
    path = Path(file_path)
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return ""


def ensure_script_file(
    script_id: int,
    file_name: str,
    content: str,
    file_path: str | None = None,
) -> Path:
    if file_path:
        path = Path(file_path)
        if path.is_file():
            return path
    return write_script_file(script_id, file_name, content)


def remove_script_file(file_path: str | None) -> None:
    if not file_path:
        return
    path = Path(file_path)
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return
    parent = path.parent
    scripts_root = Path(Config.SCRIPTS_DIR).resolve()
    try:
        parent_resolved = parent.resolve()
    except OSError:
        return
    if parent_resolved == scripts_root or scripts_root not in parent_resolved.parents:
        return
    try:
        parent.rmdir()
    except OSError:
        return
