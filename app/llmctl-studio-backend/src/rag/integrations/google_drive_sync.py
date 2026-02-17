from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import re
import shutil
from pathlib import Path
from typing import Any, Callable
import threading


DRIVE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

_GOOGLE_EXPORTS: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
    "application/vnd.google-apps.script": ("application/vnd.google-apps.script+json", ".json"),
}


@dataclass(frozen=True)
class DriveFolderInfo:
    id: str
    name: str


@dataclass(frozen=True)
class DriveSyncStats:
    files_downloaded: int
    folders_synced: int
    files_skipped: int


@dataclass(frozen=True)
class _DriveDownloadJob:
    file_id: str
    output_path: Path
    export_mime: str | None


def service_account_email(service_account_json: str) -> str | None:
    info = _load_service_account_info(service_account_json)
    email = info.get("client_email")
    if isinstance(email, str) and email.strip():
        return email.strip()
    return None


def verify_folder_access(
    service_account_json: str, folder_id: str, *, service: Any | None = None
) -> DriveFolderInfo:
    folder_key = _normalize_folder_id(folder_id)
    drive_service = service or _build_drive_service(service_account_json)
    metadata = _get_folder_metadata(drive_service, folder_key)
    return DriveFolderInfo(id=str(metadata.get("id") or folder_key), name=str(metadata.get("name") or folder_key))


def sync_folder(
    service_account_json: str,
    folder_id: str,
    destination: Path,
    *,
    service: Any | None = None,
    on_file_downloaded: Callable[[Path, DriveSyncStats], None] | None = None,
    max_workers: int = 1,
) -> DriveSyncStats:
    folder_key = _normalize_folder_id(folder_id)
    drive_service = service or _build_drive_service(service_account_json)
    service_factory: Callable[[], Any] | None = None
    if service is None:
        service_factory = lambda: _build_drive_service(service_account_json)
    _get_folder_metadata(drive_service, folder_key)
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    stats = {"files_downloaded": 0, "folders_synced": 1, "files_skipped": 0}
    _sync_folder(
        drive_service,
        folder_key,
        destination,
        stats,
        on_file_downloaded=on_file_downloaded,
        service_factory=service_factory,
        max_workers=max_workers,
    )
    return DriveSyncStats(**stats)


def count_syncable_files(
    service_account_json: str,
    folder_id: str,
    *,
    service: Any | None = None,
) -> int:
    folder_key = _normalize_folder_id(folder_id)
    drive_service = service or _build_drive_service(service_account_json)
    _get_folder_metadata(drive_service, folder_key)
    return _count_syncable_files(drive_service, folder_key)


def _normalize_folder_id(folder_id: str) -> str:
    value = (folder_id or "").strip()
    if not value:
        raise ValueError("Google Drive folder ID is required.")
    return value


def _load_service_account_info(service_account_json: str) -> dict[str, Any]:
    raw = (service_account_json or "").strip()
    if not raw:
        raise ValueError("Google Drive service account JSON is required.")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Google Drive service account JSON is invalid.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Google Drive service account JSON must be an object.")
    required_keys = ("client_email", "private_key", "token_uri")
    missing = [key for key in required_keys if not str(payload.get(key) or "").strip()]
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"Google Drive service account JSON is missing: {joined}.")
    return payload


def _import_google_clients():
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload
    except ImportError as exc:
        raise RuntimeError(
            "Google Drive dependencies are not installed. Install the Studio RAG extras."
        ) from exc
    return Credentials, build, MediaIoBaseDownload


def _build_drive_service(service_account_json: str):
    info = _load_service_account_info(service_account_json)
    Credentials, build, _ = _import_google_clients()
    credentials = Credentials.from_service_account_info(info, scopes=[DRIVE_READONLY_SCOPE])
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _get_folder_metadata(service, folder_id: str) -> dict[str, Any]:
    try:
        metadata = (
            service.files()
            .get(
                fileId=folder_id,
                fields="id,name,mimeType,trashed",
                supportsAllDrives=True,
            )
            .execute()
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to access Google Drive folder: {_drive_error_message(exc)}") from exc
    if not isinstance(metadata, dict):
        raise RuntimeError("Google Drive API returned invalid folder metadata.")
    if metadata.get("trashed"):
        raise RuntimeError("Google Drive folder exists but is in trash.")
    if metadata.get("mimeType") != DRIVE_FOLDER_MIME_TYPE:
        raise RuntimeError("Google Drive ID exists but is not a folder.")
    return metadata


def _drive_error_message(exc: Exception) -> str:
    status = getattr(getattr(exc, "resp", None), "status", None)
    reason = str(getattr(exc, "reason", "") or "").strip()
    if not reason:
        reason = str(exc).strip() or "unknown error"
    if status is not None:
        return f"{status} {reason}"
    return reason


def _sync_folder(
    service,
    folder_id: str,
    destination: Path,
    stats: dict[str, int],
    *,
    on_file_downloaded: Callable[[Path, DriveSyncStats], None] | None = None,
    service_factory: Callable[[], Any] | None = None,
    max_workers: int = 1,
) -> None:
    jobs: list[_DriveDownloadJob] = []
    reserved_paths: set[str] = set()
    _plan_folder_downloads(
        service,
        folder_id,
        destination,
        stats,
        reserved_paths,
        jobs,
    )
    _download_jobs(
        service,
        service_factory=service_factory,
        jobs=jobs,
        stats=stats,
        on_file_downloaded=on_file_downloaded,
        max_workers=max_workers,
    )


def _plan_folder_downloads(
    service,
    folder_id: str,
    destination: Path,
    stats: dict[str, int],
    reserved_paths: set[str],
    jobs: list[_DriveDownloadJob],
) -> None:
    items = _list_folder_items(service, folder_id)
    for item in items:
        file_id = str(item.get("id") or "").strip()
        mime_type = str(item.get("mimeType") or "").strip()
        name = _safe_filename(str(item.get("name") or file_id))
        if not file_id or not mime_type:
            stats["files_skipped"] += 1
            continue

        if mime_type == DRIVE_FOLDER_MIME_TYPE:
            child_dir = _unique_path(destination / name, reserved_paths)
            child_dir.mkdir(parents=True, exist_ok=True)
            stats["folders_synced"] += 1
            _plan_folder_downloads(
                service,
                file_id,
                child_dir,
                stats,
                reserved_paths,
                jobs,
            )
            continue

        if mime_type == "application/vnd.google-apps.shortcut":
            stats["files_skipped"] += 1
            continue

        if mime_type.startswith("application/vnd.google-apps."):
            export = _GOOGLE_EXPORTS.get(mime_type)
            if not export:
                stats["files_skipped"] += 1
                continue
            export_mime, suffix = export
            filename = name if name.lower().endswith(suffix) else f"{name}{suffix}"
            output_path = _unique_path(destination / filename, reserved_paths)
            jobs.append(
                _DriveDownloadJob(
                    file_id=file_id,
                    output_path=output_path,
                    export_mime=export_mime,
                )
            )
            continue

        output_path = _unique_path(destination / name, reserved_paths)
        jobs.append(
            _DriveDownloadJob(
                file_id=file_id,
                output_path=output_path,
                export_mime=None,
            )
        )


def _execute_download_job(service, job: _DriveDownloadJob) -> Path:
    if job.export_mime:
        _download_export(service, job.file_id, job.export_mime, job.output_path)
    else:
        _download_file(service, job.file_id, job.output_path)
    return job.output_path


def _download_jobs(
    service,
    *,
    service_factory: Callable[[], Any] | None,
    jobs: list[_DriveDownloadJob],
    stats: dict[str, int],
    on_file_downloaded: Callable[[Path, DriveSyncStats], None] | None = None,
    max_workers: int = 1,
) -> None:
    if not jobs:
        return

    worker_count = max(1, int(max_workers))
    if worker_count <= 1 or len(jobs) <= 1:
        for job in jobs:
            output_path = _execute_download_job(service, job)
            stats["files_downloaded"] += 1
            if on_file_downloaded:
                on_file_downloaded(output_path, DriveSyncStats(**stats))
        return

    local_state = threading.local()

    def _service_for_thread():
        if service_factory is None:
            return service
        cached = getattr(local_state, "service", None)
        if cached is None:
            cached = service_factory()
            local_state.service = cached
        return cached

    def _run_download(job: _DriveDownloadJob) -> Path:
        worker_service = _service_for_thread()
        return _execute_download_job(worker_service, job)

    with ThreadPoolExecutor(max_workers=min(worker_count, len(jobs))) as executor:
        futures = [executor.submit(_run_download, job) for job in jobs]
        for future in futures:
            output_path = future.result()
            stats["files_downloaded"] += 1
            if on_file_downloaded:
                on_file_downloaded(output_path, DriveSyncStats(**stats))


def _count_syncable_files(service, folder_id: str) -> int:
    total = 0
    items = _list_folder_items(service, folder_id)
    for item in items:
        file_id = str(item.get("id") or "").strip()
        mime_type = str(item.get("mimeType") or "").strip()
        if not file_id or not mime_type:
            continue
        if mime_type == DRIVE_FOLDER_MIME_TYPE:
            total += _count_syncable_files(service, file_id)
            continue
        if mime_type == "application/vnd.google-apps.shortcut":
            continue
        if mime_type.startswith("application/vnd.google-apps."):
            if mime_type in _GOOGLE_EXPORTS:
                total += 1
            continue
        total += 1
    return total


def _list_folder_items(service, folder_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page_token = None
    while True:
        response = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields="nextPageToken, files(id,name,mimeType)",
                pageSize=1000,
                pageToken=page_token,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                corpora="allDrives",
            )
            .execute()
        )
        batch = response.get("files") if isinstance(response, dict) else None
        if isinstance(batch, list):
            items.extend([item for item in batch if isinstance(item, dict)])
        page_token = response.get("nextPageToken") if isinstance(response, dict) else None
        if not page_token:
            break
    items.sort(key=lambda item: (str(item.get("name") or "").lower(), str(item.get("id") or "")))
    return items


def _download_file(service, file_id: str, output_path: Path) -> None:
    _, _, MediaIoBaseDownload = _import_google_clients()
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    _download_request(request, output_path, MediaIoBaseDownload)


def _download_export(service, file_id: str, mime_type: str, output_path: Path) -> None:
    _, _, MediaIoBaseDownload = _import_google_clients()
    request = service.files().export_media(fileId=file_id, mimeType=mime_type)
    _download_request(request, output_path, MediaIoBaseDownload)


def _download_request(request, output_path: Path, downloader_cls) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        downloader = downloader_cls(handle, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()


def _safe_filename(value: str) -> str:
    name = re.sub(r"[\\/\x00-\x1f]+", "-", value or "").strip()
    name = name.strip(" .")
    return name or "untitled"


def _unique_path(path: Path, reserved_paths: set[str] | None = None) -> Path:
    if reserved_paths is None:
        reserved_paths = set()
    if not path.exists() and path.as_posix() not in reserved_paths:
        reserved_paths.add(path.as_posix())
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 10_000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        candidate_key = candidate.as_posix()
        if not candidate.exists() and candidate_key not in reserved_paths:
            reserved_paths.add(candidate_key)
            return candidate
    raise RuntimeError(f"Unable to create a unique path for {path.name}.")
