from __future__ import annotations

import json
from datetime import datetime, timezone

from celery.utils.log import get_task_logger

from celery_app import celery_app
from config import build_source_config, load_config
from git_sync import ensure_git_repo, git_fetch_and_reset
from ingest import ingest
from logging_utils import log_sink
from settings_store import load_integration_settings
from sources_store import list_sources, update_source_index
from tasks_store import (
    TASK_STATUS_FAILED,
    TASK_STATUS_SUCCEEDED,
    append_task_output,
    get_task,
    mark_task_finished,
    mark_task_running,
)


logger = get_task_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _task_output_sink(task_id: int):
    def _sink(message: str) -> None:
        append_task_output(task_id, message)

    return _sink


@celery_app.task(bind=True)
def run_index_task(self, task_id: int, source_id: int | None, reset: bool) -> None:
    mark_task_running(task_id, celery_task_id=self.request.id)
    append_task_output(task_id, "Index task started.")
    output_lines: list[str] = []
    error: str | None = None
    try:
        with log_sink(_task_output_sink(task_id)):
            config = load_config()
            github_settings = load_integration_settings("github")
            sources = list_sources()
            if source_id is not None:
                sources = [source for source in sources if source.id == source_id]
                if not sources:
                    raise RuntimeError("Source not found.")

            errors: list[str] = []
            for source in sources:
                append_task_output(task_id, f"Indexing {source.name}...")
                source_config = build_source_config(config, source, github_settings)
                source_meta = {
                    "source_id": source.id,
                    "source_name": source.name,
                    "source_kind": source.kind,
                }
                try:
                    if source.kind == "github":
                        append_task_output(task_id, f"Syncing {source.name} from GitHub...")
                        ensure_git_repo(source_config)
                        git_fetch_and_reset(source_config)
                    total_files, total_chunks, files_by_type, _ = ingest(
                        source_config, reset=reset, source_meta=source_meta
                    )
                    update_source_index(
                        source.id,
                        last_indexed_at=_utcnow(),
                        last_error=None,
                        indexed_file_count=total_files,
                        indexed_chunk_count=total_chunks,
                        indexed_file_types=json.dumps(files_by_type, sort_keys=True),
                    )
                    summary = f"{source.name}: {total_files} files, {total_chunks} chunks"
                    output_lines.append(summary)
                    append_task_output(task_id, summary)
                except Exception as exc:
                    update_source_index(
                        source.id,
                        last_indexed_at=source.last_indexed_at,
                        last_error=str(exc),
                    )
                    errors.append(f"{source.name}: {exc}")
                    failure_line = f"{source.name}: failed ({exc})"
                    output_lines.append(failure_line)
                    append_task_output(task_id, failure_line)
                    if source_id is not None:
                        break
            if errors:
                error = "; ".join(errors)
    except Exception as exc:
        logger.exception("Index task failed")
        error = str(exc)
        output_lines.append(f"Task failed: {error}")
        append_task_output(task_id, f"Task failed: {error}")

    status = TASK_STATUS_FAILED if error else TASK_STATUS_SUCCEEDED
    output = None
    if output_lines:
        current = get_task(task_id)
        if current and not current.output:
            output = "\n".join(output_lines)
    mark_task_finished(task_id, status=status, output=output, error=error)
