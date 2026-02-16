from __future__ import annotations

from datetime import timedelta
import json
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

import core.db as core_db
from core.config import Config
from core.db import session_scope, utcnow
from core.models import (
    RAG_INDEX_JOB_STATUS_QUEUED,
    RAG_INDEX_MODE_DELTA,
    RAG_INDEX_MODE_FRESH,
)
from rag.repositories.index_jobs import (
    create_index_job,
    get_index_job,
    index_job_meta,
    update_index_job_checkpoint,
    update_index_job_progress,
)
from rag.repositories.settings import load_rag_settings, save_rag_settings
from rag.repositories.source_file_states import (
    SourceFileStateInput,
    summarize_source_file_states,
    upsert_source_file_states,
)
from rag.repositories.sources import (
    RAGSourceInput,
    create_source,
    list_due_sources,
    schedule_source_next_index,
)


class StudioDbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_dir / 'stage3.sqlite3'}"
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


class RagStage3Tests(StudioDbTestCase):
    def test_rag_tables_and_columns_exist(self) -> None:
        with session_scope() as session:
            tables = {
                row[0]
                for row in session.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                ).all()
            }
            self.assertIn("rag_sources", tables)
            self.assertIn("rag_index_jobs", tables)
            self.assertIn("rag_source_file_states", tables)
            self.assertIn("rag_settings", tables)

            source_columns = {
                row[1]
                for row in session.execute(text("PRAGMA table_info(rag_sources)")).all()
            }
            self.assertIn("index_schedule_mode", source_columns)
            self.assertIn("next_index_at", source_columns)

            job_columns = {
                row[1]
                for row in session.execute(text("PRAGMA table_info(rag_index_jobs)")).all()
            }
            self.assertIn("mode", job_columns)
            self.assertIn("meta_json", job_columns)

    def test_source_schedule_mode_and_due_selection(self) -> None:
        source = create_source(
            RAGSourceInput(
                name="Repo Source",
                kind="github",
                git_repo="git@github.com:org/repo.git",
                index_schedule_value=1,
                index_schedule_unit="hours",
                index_schedule_mode=RAG_INDEX_MODE_DELTA,
            )
        )
        self.assertEqual(RAG_INDEX_MODE_DELTA, source.index_schedule_mode)

        due = list_due_sources(now=utcnow())
        self.assertFalse(any(item.id == source.id for item in due))

        when = schedule_source_next_index(
            source.id,
            from_time=utcnow() - timedelta(hours=2),
        )
        self.assertIsNotNone(when)

        due = list_due_sources(now=utcnow())
        self.assertTrue(any(item.id == source.id for item in due))

    def test_index_job_meta_shape_for_checkpoint_and_progress(self) -> None:
        source = create_source(
            RAGSourceInput(
                name="Local Source",
                kind="local",
                local_path=str(REPO_ROOT),
                index_schedule_mode=RAG_INDEX_MODE_FRESH,
            )
        )
        job = create_index_job(
            source_id=source.id,
            mode=RAG_INDEX_MODE_FRESH,
            status=RAG_INDEX_JOB_STATUS_QUEUED,
        )
        meta = index_job_meta(job)
        self.assertIn("checkpoint", meta)
        self.assertIn("progress", meta)
        self.assertEqual("queued", meta["progress"]["phase"])

        update_index_job_checkpoint(job.id, {"stage": "scan", "cursor": "path:42"})
        update_index_job_progress(job.id, {"phase": "running", "percent": 35.5})

        reloaded = get_index_job(job.id)
        assert reloaded is not None
        updated_meta = index_job_meta(reloaded)
        self.assertEqual("scan", updated_meta["checkpoint"]["stage"])
        self.assertEqual("path:42", updated_meta["checkpoint"]["cursor"])
        self.assertEqual("running", updated_meta["progress"]["phase"])
        self.assertAlmostEqual(35.5, updated_meta["progress"]["percent"])
        json.loads(reloaded.meta_json or "{}")

    def test_source_file_state_summary_and_settings_crud(self) -> None:
        source = create_source(
            RAGSourceInput(
                name="Drive Source",
                kind="google_drive",
                drive_folder_id="folder-123",
                index_schedule_mode=RAG_INDEX_MODE_FRESH,
            )
        )
        upsert_source_file_states(
            source.id,
            [
                SourceFileStateInput(
                    path="a.md",
                    fingerprint="fp-1",
                    indexed=True,
                    doc_type="markdown",
                    chunk_count=3,
                ),
                SourceFileStateInput(
                    path="b.py",
                    fingerprint="fp-2",
                    indexed=True,
                    doc_type="code",
                    chunk_count=5,
                ),
            ],
        )
        stats = summarize_source_file_states(source.id)
        self.assertEqual(2, stats.indexed_file_count)
        self.assertEqual(8, stats.indexed_chunk_count)
        self.assertEqual(1, stats.indexed_file_types.get("markdown"))
        self.assertEqual(1, stats.indexed_file_types.get("code"))

        save_rag_settings(
            "rag",
            {
                "embed_provider": "openai",
                "chat_provider": "gemini",
            },
        )
        settings = load_rag_settings("rag")
        self.assertEqual("openai", settings.get("embed_provider"))
        self.assertEqual("gemini", settings.get("chat_provider"))


if __name__ == "__main__":
    unittest.main()
