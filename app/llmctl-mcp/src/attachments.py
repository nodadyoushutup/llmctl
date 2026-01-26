from __future__ import annotations

import base64
import binascii
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select

from core.models import (
    AgentTask,
    Attachment,
    PipelineStep,
    TaskTemplate,
    agent_task_attachments,
    pipeline_step_attachments,
    task_template_attachments,
)
from storage.attachment_storage import write_attachment_file


def _decode_base64(value: str) -> bytes:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Attachment content must be base64.")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("Attachment content must be base64.")


def _safe_file_name(file_name: str, fallback: str) -> str:
    cleaned = Path(file_name).name if file_name else ""
    if not cleaned or cleaned in {".", ".."}:
        return fallback
    return cleaned


def _create_attachment_record(
    session,
    file_name: str,
    content: bytes,
    content_type: str | None = None,
) -> Attachment:
    safe_name = _safe_file_name(file_name, "attachment")
    attachment = Attachment(
        file_name=safe_name,
        file_path=None,
        content_type=content_type or None,
        size_bytes=len(content) if content is not None else 0,
    )
    session.add(attachment)
    session.flush()
    path = write_attachment_file(attachment.id, safe_name, content)
    attachment.file_path = str(path)
    session.flush()
    return attachment


def _attachment_in_use(session, attachment_id: int) -> bool:
    task_refs = session.execute(
        select(func.count())
        .select_from(agent_task_attachments)
        .where(agent_task_attachments.c.attachment_id == attachment_id)
    ).scalar_one()
    if task_refs:
        return True
    template_refs = session.execute(
        select(func.count())
        .select_from(task_template_attachments)
        .where(task_template_attachments.c.attachment_id == attachment_id)
    ).scalar_one()
    if template_refs:
        return True
    step_refs = session.execute(
        select(func.count())
        .select_from(pipeline_step_attachments)
        .where(pipeline_step_attachments.c.attachment_id == attachment_id)
    ).scalar_one()
    return bool(step_refs)


def _unlink_attachment(session, attachment_id: int) -> None:
    session.execute(
        delete(agent_task_attachments).where(
            agent_task_attachments.c.attachment_id == attachment_id
        )
    )
    session.execute(
        delete(task_template_attachments).where(
            task_template_attachments.c.attachment_id == attachment_id
        )
    )
    session.execute(
        delete(pipeline_step_attachments).where(
            pipeline_step_attachments.c.attachment_id == attachment_id
        )
    )


def _delete_attachment_if_unused(session, attachment: Attachment) -> str | None:
    if _attachment_in_use(session, attachment.id):
        return None
    file_path = attachment.file_path
    session.delete(attachment)
    return file_path


def _attach_attachments(target, attachments: list[Attachment]) -> None:
    if not attachments:
        return
    existing_ids = {item.id for item in getattr(target, "attachments", [])}
    for attachment in attachments:
        if attachment.id in existing_ids:
            continue
        target.attachments.append(attachment)


def _resolve_attachment_target(session, target: str, target_id: int):
    normalized = target.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"task", "agent_task", "agenttask"}:
        record = session.get(AgentTask, target_id)
        return record
    if normalized in {"template", "task_template", "tasktemplate"}:
        record = session.get(TaskTemplate, target_id)
        return record
    if normalized in {"pipeline_step", "pipelinestep", "step"}:
        record = session.get(PipelineStep, target_id)
        return record
    raise ValueError("Target must be task, task_template, or pipeline_step.")
