from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from core.config import Config


def _safe_file_name(file_name: str, fallback: str) -> str:
    cleaned = Path(file_name).name if file_name else ""
    if not cleaned or cleaned in {".", ".."}:
        return fallback
    return cleaned


def build_attachment_path(attachment_id: int, file_name: str) -> Path:
    safe_name = _safe_file_name(file_name, f"attachment-{attachment_id}")
    ext = Path(safe_name).suffix
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    token = uuid4().hex
    storage_name = f"attachment-{attachment_id}-{timestamp}-{token}{ext}"
    return Path(Config.ATTACHMENTS_DIR) / storage_name


def write_attachment_file(
    attachment_id: int,
    file_name: str,
    content: bytes | None,
) -> Path:
    path = build_attachment_path(attachment_id, file_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content or b"")
    return path


def remove_attachment_file(file_path: str | None) -> None:
    if not file_path:
        return
    path = Path(file_path)
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return
