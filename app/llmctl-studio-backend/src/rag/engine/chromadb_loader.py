from __future__ import annotations

import importlib
import threading
from typing import Any

_patch_lock = threading.Lock()
_pydantic_env_patch_applied = False


def _is_dotenv_io_error(exc: BaseException) -> bool:
    if not isinstance(exc, OSError):
        return False
    filename = str(getattr(exc, "filename", "") or "")
    if filename.endswith(".env"):
        return True
    return ".env" in str(exc)


def _patch_pydantic_env_file_reader() -> None:
    global _pydantic_env_patch_applied
    if _pydantic_env_patch_applied:
        return
    with _patch_lock:
        if _pydantic_env_patch_applied:
            return
        env_settings_module: Any | None = None
        for module_name in ("pydantic.v1.env_settings", "pydantic.env_settings"):
            try:
                env_settings_module = importlib.import_module(module_name)
                break
            except ModuleNotFoundError:
                continue
        if env_settings_module is None:
            _pydantic_env_patch_applied = True
            return

        source_cls = getattr(env_settings_module, "EnvSettingsSource", None)
        original = getattr(source_cls, "_read_env_files", None) if source_cls else None
        if not callable(original):
            _pydantic_env_patch_applied = True
            return

        def _safe_read_env_files(self, case_sensitive):  # type: ignore[no-untyped-def]
            try:
                return original(self, case_sensitive)
            except OSError as exc:
                if _is_dotenv_io_error(exc):
                    return {}
                raise

        source_cls._read_env_files = _safe_read_env_files
        _pydantic_env_patch_applied = True


def import_chromadb():
    try:
        return importlib.import_module("chromadb")
    except OSError as exc:
        if not _is_dotenv_io_error(exc):
            raise
        _patch_pydantic_env_file_reader()
        return importlib.import_module("chromadb")
