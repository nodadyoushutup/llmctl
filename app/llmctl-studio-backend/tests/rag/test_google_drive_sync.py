from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[4]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

from rag.integrations.google_drive_sync import (
    count_syncable_files,
    service_account_email,
    sync_folder,
    verify_folder_access,
)


class _FakeRequest:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class _FakeFilesApi:
    def __init__(self, metadata_by_id, children_by_parent):
        self._metadata_by_id = metadata_by_id
        self._children_by_parent = children_by_parent

    def get(self, *, fileId, **kwargs):
        payload = self._metadata_by_id.get(fileId)
        if payload is None:
            raise RuntimeError("not found")
        return _FakeRequest(payload)

    def list(self, *, q, **kwargs):
        parent_id = q.split("'")[1]
        payload = {
            "files": self._children_by_parent.get(parent_id, []),
            "nextPageToken": None,
        }
        return _FakeRequest(payload)


class _FakeDriveService:
    def __init__(self, metadata_by_id, children_by_parent):
        self._files_api = _FakeFilesApi(metadata_by_id, children_by_parent)

    def files(self):
        return self._files_api


class GoogleDriveSyncTests(unittest.TestCase):
    def test_service_account_email_validates_json(self):
        payload = (
            '{"client_email":"svc@example.com","private_key":"abc","token_uri":"uri"}'
        )
        self.assertEqual("svc@example.com", service_account_email(payload))
        with self.assertRaises(ValueError):
            service_account_email("{bad")
        with self.assertRaises(ValueError):
            service_account_email('{"client_email":"svc@example.com"}')

    def test_verify_folder_access(self):
        service = _FakeDriveService(
            metadata_by_id={
                "folder-1": {
                    "id": "folder-1",
                    "name": "Knowledge",
                    "mimeType": "application/vnd.google-apps.folder",
                    "trashed": False,
                }
            },
            children_by_parent={},
        )
        folder = verify_folder_access("", "folder-1", service=service)
        self.assertEqual("folder-1", folder.id)
        self.assertEqual("Knowledge", folder.name)

    def test_count_syncable_files(self):
        service = _FakeDriveService(
            metadata_by_id={
                "root": {
                    "id": "root",
                    "name": "Root",
                    "mimeType": "application/vnd.google-apps.folder",
                    "trashed": False,
                }
            },
            children_by_parent={
                "root": [
                    {"id": "f-1", "name": "notes.txt", "mimeType": "text/plain"},
                    {
                        "id": "g-1",
                        "name": "Design Doc",
                        "mimeType": "application/vnd.google-apps.document",
                    },
                    {
                        "id": "sub-1",
                        "name": "Sheets",
                        "mimeType": "application/vnd.google-apps.folder",
                    },
                    {
                        "id": "g-unsupported",
                        "name": "Form",
                        "mimeType": "application/vnd.google-apps.form",
                    },
                    {
                        "id": "shortcut-1",
                        "name": "Shortcut",
                        "mimeType": "application/vnd.google-apps.shortcut",
                    },
                ],
                "sub-1": [
                    {
                        "id": "g-2",
                        "name": "Budget",
                        "mimeType": "application/vnd.google-apps.spreadsheet",
                    }
                ],
            },
        )
        self.assertEqual(3, count_syncable_files("", "root", service=service))

    def test_sync_folder_downloads_and_exports(self):
        service = _FakeDriveService(
            metadata_by_id={
                "root": {
                    "id": "root",
                    "name": "Root",
                    "mimeType": "application/vnd.google-apps.folder",
                    "trashed": False,
                }
            },
            children_by_parent={
                "root": [
                    {"id": "f-1", "name": "notes.txt", "mimeType": "text/plain"},
                    {
                        "id": "g-1",
                        "name": "Design Doc",
                        "mimeType": "application/vnd.google-apps.document",
                    },
                    {
                        "id": "sub-1",
                        "name": "Sheets",
                        "mimeType": "application/vnd.google-apps.folder",
                    },
                ],
                "sub-1": [
                    {
                        "id": "g-2",
                        "name": "Budget",
                        "mimeType": "application/vnd.google-apps.spreadsheet",
                    }
                ],
            },
        )

        def _fake_download_file(_service, file_id, output_path):
            output_path.write_text(f"file:{file_id}", encoding="utf-8")

        def _fake_download_export(_service, file_id, mime_type, output_path):
            output_path.write_text(f"export:{file_id}:{mime_type}", encoding="utf-8")

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "drive-sync"
            with patch(
                "rag.integrations.google_drive_sync._download_file",
                _fake_download_file,
            ):
                with patch(
                    "rag.integrations.google_drive_sync._download_export",
                    _fake_download_export,
                ):
                    stats = sync_folder("", "root", destination, service=service)

            self.assertEqual(3, stats.files_downloaded)
            self.assertEqual(2, stats.folders_synced)
            self.assertEqual(0, stats.files_skipped)
            self.assertTrue((destination / "notes.txt").is_file())
            self.assertTrue((destination / "Design Doc.docx").is_file())
            self.assertTrue((destination / "Sheets" / "Budget.xlsx").is_file())

    def test_sync_folder_emits_file_progress(self):
        service = _FakeDriveService(
            metadata_by_id={
                "root": {
                    "id": "root",
                    "name": "Root",
                    "mimeType": "application/vnd.google-apps.folder",
                    "trashed": False,
                }
            },
            children_by_parent={
                "root": [
                    {"id": "f-1", "name": "notes.txt", "mimeType": "text/plain"},
                    {
                        "id": "g-1",
                        "name": "Design Doc",
                        "mimeType": "application/vnd.google-apps.document",
                    },
                ],
            },
        )
        progress: list[tuple[str, int]] = []

        def _fake_download_file(_service, file_id, output_path):
            output_path.write_text(f"file:{file_id}", encoding="utf-8")

        def _fake_download_export(_service, file_id, mime_type, output_path):
            output_path.write_text(f"export:{file_id}:{mime_type}", encoding="utf-8")

        def _on_file_downloaded(path: Path, stats):
            progress.append((path.name, stats.files_downloaded))

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "drive-sync"
            with patch(
                "rag.integrations.google_drive_sync._download_file",
                _fake_download_file,
            ):
                with patch(
                    "rag.integrations.google_drive_sync._download_export",
                    _fake_download_export,
                ):
                    sync_folder(
                        "",
                        "root",
                        destination,
                        service=service,
                        on_file_downloaded=_on_file_downloaded,
                    )

        self.assertEqual(2, len(progress))
        self.assertEqual([1, 2], [count for _, count in progress])

    def test_sync_folder_supports_concurrent_workers(self):
        service = _FakeDriveService(
            metadata_by_id={
                "root": {
                    "id": "root",
                    "name": "Root",
                    "mimeType": "application/vnd.google-apps.folder",
                    "trashed": False,
                }
            },
            children_by_parent={
                "root": [
                    {"id": "f-1", "name": "a.txt", "mimeType": "text/plain"},
                    {"id": "f-2", "name": "b.txt", "mimeType": "text/plain"},
                    {
                        "id": "g-1",
                        "name": "Design Doc",
                        "mimeType": "application/vnd.google-apps.document",
                    },
                ],
            },
        )

        def _fake_download_file(_service, file_id, output_path):
            output_path.write_text(f"file:{file_id}", encoding="utf-8")

        def _fake_download_export(_service, file_id, mime_type, output_path):
            output_path.write_text(f"export:{file_id}:{mime_type}", encoding="utf-8")

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "drive-sync"
            with patch(
                "rag.integrations.google_drive_sync._download_file",
                _fake_download_file,
            ):
                with patch(
                    "rag.integrations.google_drive_sync._download_export",
                    _fake_download_export,
                ):
                    stats = sync_folder(
                        "",
                        "root",
                        destination,
                        service=service,
                        max_workers=4,
                    )

            self.assertEqual(3, stats.files_downloaded)
            self.assertTrue((destination / "a.txt").is_file())
            self.assertTrue((destination / "b.txt").is_file())
            self.assertTrue((destination / "Design Doc.docx").is_file())


if __name__ == "__main__":
    unittest.main()
