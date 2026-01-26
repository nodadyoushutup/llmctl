from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from sqlalchemy import func, select, update
from sqlalchemy import inspect as sa_inspect

from core.config import Config
from core.db import session_scope, utcnow
from core.models import (
    Agent,
    AgentTask,
    Attachment,
    Pipeline,
    PipelineRun,
    PipelineStep,
    Run,
    RUN_ACTIVE_STATUSES,
    Role,
    Script,
    TaskTemplate,
    agent_scripts,
    agent_task_scripts,
)
from core.task_kinds import QUICK_TASK_KIND, is_quick_task_kind
from services.celery_app import celery_app
from services.code_review import (
    CODE_REVIEW_TASK_KIND,
    ensure_code_reviewer_agent,
    ensure_code_reviewer_role,
)
from services.integrations import load_integration_settings
from services.tasks import run_agent, run_agent_task, run_pipeline
from storage.attachment_storage import remove_attachment_file
from storage.script_storage import remove_script_file

from attachments import (
    _attach_attachments,
    _create_attachment_record,
    _decode_base64,
    _delete_attachment_if_unused,
    _resolve_attachment_target,
)
from constants import DEFAULT_LIMIT, MAX_LIMIT, MODEL_REGISTRY
from db_utils import (
    _apply_data,
    _clamp_limit,
    _coerce_value,
    _column_map,
    _resolve_model,
    _serialize_model,
)
from deletions import (
    _delete_agent_record,
    _delete_attachment_record,
    _delete_pipeline_record,
    _delete_pipeline_run_record,
    _delete_role_record,
    _delete_run_record,
    _delete_script_record,
    _delete_task_record,
    _delete_task_template_record,
)
from prompts import _build_code_review_prompt, _build_quick_task_prompt
from scripts import (
    _ensure_script_storage,
    _parse_script_ids_by_type,
    _resolve_script_ids_by_type,
    _set_script_links,
    _sync_script_storage,
)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def list_models() -> dict[str, Any]:
        models = sorted({cls.__name__ for cls in MODEL_REGISTRY.values()})
        return {"ok": True, "models": models}

    @mcp.tool()
    def model_schema(model: str) -> dict[str, Any]:
        model_cls = _resolve_model(model)
        mapper = sa_inspect(model_cls)
        columns = []
        for column in mapper.columns:
            columns.append(
                {
                    "name": column.key,
                    "type": str(column.type),
                    "nullable": bool(column.nullable),
                    "primary_key": bool(column.primary_key),
                }
            )
        relationships = []
        for rel in mapper.relationships:
            relationships.append(
                {
                    "name": rel.key,
                    "target": rel.mapper.class_.__name__,
                    "uselist": bool(rel.uselist),
                }
            )
        return {
            "ok": True,
            "model": model_cls.__name__,
            "table": model_cls.__tablename__,
            "columns": columns,
            "relationships": relationships,
        }

    @mcp.tool()
    def list_records(
        model: str,
        limit: int | None = None,
        offset: int = 0,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
        descending: bool = False,
        include_relationships: bool = False,
    ) -> dict[str, Any]:
        model_cls = _resolve_model(model)
        columns = _column_map(model_cls)
        stmt = select(model_cls)
        if filters:
            for key, value in filters.items():
                if key not in columns:
                    raise ValueError(f"Unknown filter column '{key}'.")
                stmt = stmt.where(columns[key] == _coerce_value(columns[key], value))
        if order_by:
            if order_by not in columns:
                raise ValueError(f"Unknown order_by column '{order_by}'.")
            order_col = columns[order_by]
            stmt = stmt.order_by(order_col.desc() if descending else order_col.asc())
        limit = _clamp_limit(DEFAULT_LIMIT if limit is None else limit, MAX_LIMIT)
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset:
            stmt = stmt.offset(max(0, int(offset)))
        with session_scope() as session:
            items = session.execute(stmt).scalars().all()
            payload = [_serialize_model(item, include_relationships) for item in items]
            return {"ok": True, "count": len(payload), "items": payload}

    @mcp.tool()
    def get_record(
        model: str,
        record_id: int,
        include_relationships: bool = False,
    ) -> dict[str, Any]:
        model_cls = _resolve_model(model)
        with session_scope() as session:
            item = session.get(model_cls, record_id)
            if item is None:
                return {"ok": False, "error": f"{model_cls.__name__} {record_id} not found."}
            return {"ok": True, "item": _serialize_model(item, include_relationships)}

    @mcp.tool()
    def create_record(
        model: str,
        data: dict[str, Any],
        include_relationships: bool = False,
    ) -> dict[str, Any]:
        model_cls = _resolve_model(model)
        with session_scope() as session:
            item = model_cls()
            session.add(item)
            _apply_data(item, data, session)
            session.flush()
            if isinstance(item, Script):
                _ensure_script_storage(session, item)
            return {"ok": True, "item": _serialize_model(item, include_relationships)}

    @mcp.tool()
    def update_record(
        model: str,
        record_id: int,
        data: dict[str, Any],
        include_relationships: bool = False,
    ) -> dict[str, Any]:
        model_cls = _resolve_model(model)
        with session_scope() as session:
            item = session.get(model_cls, record_id)
            if item is None:
                return {"ok": False, "error": f"{model_cls.__name__} {record_id} not found."}
            previous_script_path = item.file_path if isinstance(item, Script) else None
            _apply_data(item, data, session)
            session.flush()
            if isinstance(item, Script):
                _sync_script_storage(session, item, previous_script_path)
            return {"ok": True, "item": _serialize_model(item, include_relationships)}

    @mcp.tool()
    def delete_record(model: str, record_id: int) -> dict[str, Any]:
        model_cls = _resolve_model(model)
        script_path = None
        attachment_path = None
        result: dict[str, Any] | None = None
        with session_scope() as session:
            item = session.get(model_cls, record_id)
            if item is None:
                return {"ok": False, "error": f"{model_cls.__name__} {record_id} not found."}
            if isinstance(item, Agent):
                result = _delete_agent_record(session, item)
                if not result.get("ok"):
                    return result
            elif isinstance(item, Role):
                result = _delete_role_record(session, item)
            elif isinstance(item, TaskTemplate):
                result = _delete_task_template_record(session, item)
            elif isinstance(item, Pipeline):
                result = _delete_pipeline_record(session, item)
            elif isinstance(item, Script):
                result, script_path = _delete_script_record(session, item)
            elif isinstance(item, Attachment):
                result, attachment_path = _delete_attachment_record(session, item)
            elif isinstance(item, Run):
                result = _delete_run_record(session, item)
            elif isinstance(item, PipelineRun):
                result = _delete_pipeline_run_record(session, item)
            elif isinstance(item, AgentTask):
                result = _delete_task_record(session, item)
            else:
                session.delete(item)
                result = {"ok": True, "deleted": record_id}
        if script_path:
            remove_script_file(script_path)
        if attachment_path:
            remove_attachment_file(attachment_path)
        return result or {"ok": True, "deleted": record_id}

    @mcp.tool()
    def set_agent_scripts(
        agent_id: int,
        script_ids_by_type: dict[str, list[int]] | None = None,
    ) -> dict[str, Any]:
        with session_scope() as session:
            agent = session.get(Agent, agent_id)
            if agent is None:
                return {"ok": False, "error": f"Agent {agent_id} not found."}
            try:
                parsed = _parse_script_ids_by_type(script_ids_by_type)
                resolved = _resolve_script_ids_by_type(session, parsed)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            _set_script_links(session, agent_scripts, "agent_id", agent_id, resolved)
        return {"ok": True, "agent_id": agent_id}

    @mcp.tool()
    def set_task_scripts(
        task_id: int,
        script_ids_by_type: dict[str, list[int]] | None = None,
    ) -> dict[str, Any]:
        with session_scope() as session:
            task = session.get(AgentTask, task_id)
            if task is None:
                return {"ok": False, "error": f"Task {task_id} not found."}
            try:
                parsed = _parse_script_ids_by_type(script_ids_by_type)
                resolved = _resolve_script_ids_by_type(session, parsed)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            _set_script_links(session, agent_task_scripts, "agent_task_id", task_id, resolved)
        return {"ok": True, "task_id": task_id}

    @mcp.tool()
    def reorder_pipeline_steps(
        pipeline_id: int,
        ordered_step_ids: list[int],
    ) -> dict[str, Any]:
        if not ordered_step_ids:
            return {"ok": False, "error": "ordered_step_ids is required."}
        with session_scope() as session:
            steps = (
                session.execute(
                    select(PipelineStep).where(PipelineStep.pipeline_id == pipeline_id)
                )
                .scalars()
                .all()
            )
            if not steps:
                return {"ok": False, "error": f"Pipeline {pipeline_id} not found or empty."}
            step_ids = {step.id for step in steps}
            requested_ids = []
            for step_id in ordered_step_ids:
                if isinstance(step_id, bool):
                    return {"ok": False, "error": "Step ids must be integers."}
                if isinstance(step_id, int):
                    requested_ids.append(step_id)
                elif isinstance(step_id, str) and step_id.strip().isdigit():
                    requested_ids.append(int(step_id.strip()))
                else:
                    return {"ok": False, "error": "Step ids must be integers."}
            if set(requested_ids) != step_ids:
                return {
                    "ok": False,
                    "error": "ordered_step_ids must include all pipeline steps.",
                }
            steps_by_id = {step.id: step for step in steps}
            for index, step_id in enumerate(requested_ids, start=1):
                steps_by_id[step_id].step_order = index
        return {"ok": True, "pipeline_id": pipeline_id, "count": len(ordered_step_ids)}

    @mcp.tool()
    def create_attachment(
        file_name: str,
        content_base64: str | None = None,
        content_text: str | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        if not file_name:
            return {"ok": False, "error": "file_name is required."}
        if content_base64:
            content = _decode_base64(content_base64)
        elif content_text is not None:
            content = content_text.encode("utf-8")
        else:
            return {"ok": False, "error": "content_base64 or content_text is required."}
        with session_scope() as session:
            attachment = _create_attachment_record(
                session,
                file_name=file_name,
                content=content,
                content_type=content_type,
            )
            return {"ok": True, "item": _serialize_model(attachment)}

    @mcp.tool()
    def attach_attachment(
        target: str,
        target_id: int,
        attachment_id: int,
    ) -> dict[str, Any]:
        with session_scope() as session:
            try:
                record = _resolve_attachment_target(session, target, target_id)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            if record is None:
                return {"ok": False, "error": f"{target} {target_id} not found."}
            attachment = session.get(Attachment, attachment_id)
            if attachment is None:
                return {"ok": False, "error": f"Attachment {attachment_id} not found."}
            _attach_attachments(record, [attachment])
        return {"ok": True, "attachment_id": attachment_id, "target_id": target_id}

    @mcp.tool()
    def detach_attachment(
        target: str,
        target_id: int,
        attachment_id: int,
        delete_if_unused: bool = True,
    ) -> dict[str, Any]:
        removed_path: str | None = None
        with session_scope() as session:
            try:
                record = _resolve_attachment_target(session, target, target_id)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            if record is None:
                return {"ok": False, "error": f"{target} {target_id} not found."}
            attachment = session.get(Attachment, attachment_id)
            if attachment is None:
                return {"ok": False, "error": f"Attachment {attachment_id} not found."}
            if attachment not in getattr(record, "attachments", []):
                return {"ok": False, "error": "Attachment not linked to target."}
            record.attachments.remove(attachment)
            session.flush()
            if delete_if_unused:
                removed_path = _delete_attachment_if_unused(session, attachment)
        if removed_path:
            remove_attachment_file(removed_path)
        return {"ok": True, "attachment_id": attachment_id, "target_id": target_id}

    @mcp.tool()
    def enqueue_task(
        agent_id: int,
        prompt: str,
        kind: str | None = None,
        script_ids_by_type: dict[str, list[int]] | None = None,
        attachment_ids: list[int] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not prompt or not prompt.strip():
            return {"ok": False, "error": "Prompt is required."}
        task_kind = (kind or "").strip() or None
        prepared_attachments: list[tuple[str, bytes, str | None]] = []
        if attachments:
            for payload in attachments:
                if not isinstance(payload, dict):
                    return {"ok": False, "error": "Attachment payloads must be objects."}
                file_name = str(payload.get("file_name") or "").strip()
                content_type = payload.get("content_type")
                content_base64 = payload.get("content_base64")
                content_text = payload.get("content_text")
                if not file_name:
                    return {"ok": False, "error": "Attachment file_name is required."}
                if content_base64:
                    content = _decode_base64(content_base64)
                elif content_text is not None:
                    content = str(content_text).encode("utf-8")
                else:
                    return {"ok": False, "error": "Attachment content is required."}
                prepared_attachments.append(
                    (
                        file_name,
                        content,
                        str(content_type).strip() if content_type else None,
                    )
                )
        with session_scope() as session:
            agent = session.get(Agent, agent_id)
            if agent is None:
                return {"ok": False, "error": f"Agent {agent_id} not found."}
            attachment_records: list[Attachment] = []
            if script_ids_by_type is not None:
                try:
                    parsed = _parse_script_ids_by_type(script_ids_by_type)
                    resolved = _resolve_script_ids_by_type(session, parsed)
                except ValueError as exc:
                    return {"ok": False, "error": str(exc)}
            else:
                resolved = None
            if attachment_ids:
                rows = (
                    session.execute(select(Attachment).where(Attachment.id.in_(attachment_ids)))
                    .scalars()
                    .all()
                )
                if len(rows) != len(set(attachment_ids)):
                    return {"ok": False, "error": "One or more attachments were not found."}
                attachment_records.extend(rows)
            task_prompt = prompt
            if is_quick_task_kind(task_kind):
                task_prompt = _build_quick_task_prompt(agent, prompt)
            task = AgentTask(
                agent_id=agent_id,
                status="queued",
                prompt=task_prompt,
                kind=task_kind,
            )
            session.add(task)
            session.flush()
            if resolved is not None:
                _set_script_links(session, agent_task_scripts, "agent_task_id", task.id, resolved)
            for file_name, content, content_type in prepared_attachments:
                attachment_records.append(
                    _create_attachment_record(
                        session,
                        file_name=file_name,
                        content=content,
                        content_type=content_type,
                    )
                )
            if attachment_records:
                _attach_attachments(task, attachment_records)
            task_id = task.id
        celery_task = run_agent_task.delay(task_id)
        with session_scope() as session:
            task = session.get(AgentTask, task_id)
            if task is not None:
                task.celery_task_id = celery_task.id
        return {"ok": True, "task_id": task_id, "celery_task_id": celery_task.id}

    @mcp.tool()
    def enqueue_quick_task(
        agent_id: int,
        prompt: str,
        attachment_ids: list[int] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return enqueue_task(
            agent_id=agent_id,
            prompt=prompt,
            kind=QUICK_TASK_KIND,
            attachment_ids=attachment_ids,
            attachments=attachments,
        )

    @mcp.tool()
    def enqueue_github_code_review(
        pr_number: int,
        pr_title: str | None = None,
        pr_url: str | None = None,
    ) -> dict[str, Any]:
        settings = load_integration_settings("github")
        repo = (settings.get("repo") or "").strip()
        pat = (settings.get("pat") or "").strip()
        if not repo or not pat:
            return {
                "ok": False,
                "error": "GitHub repository and PAT are required to run code reviews.",
            }
        if not pr_url and repo:
            pr_url = f"https://github.com/{repo}/pull/{pr_number}"
        with session_scope() as session:
            role = ensure_code_reviewer_role(session)
            agent = ensure_code_reviewer_agent(session, role)
            prompt = _build_code_review_prompt(
                repo=repo,
                pr_number=pr_number,
                pr_title=pr_title,
                pr_url=pr_url,
                role_prompt=role.description if role is not None else None,
            )
            task = AgentTask(
                agent_id=agent.id,
                status="queued",
                prompt=prompt,
                kind=CODE_REVIEW_TASK_KIND,
            )
            session.add(task)
            session.flush()
            task_id = task.id
        celery_task = run_agent_task.delay(task_id)
        with session_scope() as session:
            task = session.get(AgentTask, task_id)
            if task is not None:
                task.celery_task_id = celery_task.id
        return {"ok": True, "task_id": task_id, "celery_task_id": celery_task.id}

    @mcp.tool()
    def start_agent(agent_id: int) -> dict[str, Any]:
        with session_scope() as session:
            agent = session.get(Agent, agent_id)
            if agent is None:
                return {"ok": False, "error": f"Agent {agent_id} not found."}
            active_run_id = session.execute(
                select(Run.id)
                .where(
                    Run.agent_id == agent_id,
                    Run.status.in_(RUN_ACTIVE_STATUSES),
                )
                .order_by(Run.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if active_run_id:
                return {
                    "ok": False,
                    "error": "Agent already has an active autorun.",
                    "active_run_id": active_run_id,
                }
            run = Run(
                agent_id=agent_id,
                run_max_loops=agent.run_max_loops,
                status="starting",
                last_started_at=utcnow(),
                run_end_requested=False,
            )
            session.add(run)
            agent.last_started_at = run.last_started_at
            agent.run_end_requested = False
            session.flush()
            run_id = run.id
        task = run_agent.delay(run_id)
        with session_scope() as session:
            run = session.get(Run, run_id)
            if run is not None:
                run.task_id = task.id
                agent = session.get(Agent, run.agent_id)
                if agent is not None:
                    agent.task_id = task.id
        return {"ok": True, "run_id": run_id, "autorun_id": run_id, "task_id": task.id}

    @mcp.tool()
    def stop_agent(agent_id: int) -> dict[str, Any]:
        task_id = None
        run_id = None
        status = "stopped"
        with session_scope() as session:
            agent = session.get(Agent, agent_id)
            if agent is None:
                return {"ok": False, "error": f"Agent {agent_id} not found."}
            run = (
                session.execute(
                    select(Run)
                    .where(
                        Run.agent_id == agent_id,
                        Run.status.in_(RUN_ACTIVE_STATUSES),
                    )
                    .order_by(Run.created_at.desc())
                    .limit(1)
                )
                .scalars()
                .first()
            )
            if run is None:
                agent.run_end_requested = False
                return {"ok": True, "agent_id": agent_id, "status": "stopped"}
            if run.task_id:
                run.run_end_requested = True
                if run.status in {"starting", "running"}:
                    run.status = "stopping"
            else:
                run.status = "stopped"
                run.run_end_requested = False
            status = run.status
            if run.task_id:
                run.last_run_task_id = run.task_id
            task_id = run.task_id
            run_id = run.id
            agent.run_end_requested = run.run_end_requested
            if run.task_id:
                agent.last_run_task_id = run.task_id
        if task_id and Config.CELERY_REVOKE_ON_STOP:
            try:
                celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
            except Exception:
                pass
        return {
            "ok": True,
            "agent_id": agent_id,
            "run_id": run_id,
            "autorun_id": run_id,
            "status": status,
            "task_id": task_id,
        }

    @mcp.tool()
    def cancel_task(task_id: int) -> dict[str, Any]:
        revoked = False
        with session_scope() as session:
            task = session.get(AgentTask, task_id)
            if task is None:
                return {"ok": False, "error": f"Task {task_id} not found."}
            if task.status not in {"queued", "running"}:
                return {
                    "ok": False,
                    "error": "Task is not running.",
                    "status": task.status,
                }
            if task.celery_task_id and Config.CELERY_REVOKE_ON_STOP:
                celery_app.control.revoke(
                    task.celery_task_id, terminate=True, signal="SIGTERM"
                )
                revoked = True
            task.status = "canceled"
            task.error = "Canceled by user."
            task.finished_at = utcnow()
            return {
                "ok": True,
                "task_id": task_id,
                "status": task.status,
                "revoked": revoked,
            }

    @mcp.tool()
    def start_run(run_id: int) -> dict[str, Any]:
        with session_scope() as session:
            run = session.get(Run, run_id)
            if run is None:
                return {"ok": False, "error": f"Autorun {run_id} not found."}
            if run.status in RUN_ACTIVE_STATUSES:
                return {
                    "ok": False,
                    "error": "Autorun already active.",
                    "status": run.status,
                }
            agent = session.get(Agent, run.agent_id)
            if agent is None:
                return {"ok": False, "error": f"Agent {run.agent_id} not found."}
            active_run_id = (
                session.execute(
                    select(Run.id).where(
                        Run.agent_id == agent.id,
                        Run.status.in_(RUN_ACTIVE_STATUSES),
                        Run.id != run_id,
                    )
                )
                .scalar_one_or_none()
            )
            if active_run_id:
                return {
                    "ok": False,
                    "error": "Agent already has an active autorun.",
                    "active_run_id": active_run_id,
                }
            run.status = "starting"
            run.last_started_at = utcnow()
            run.run_end_requested = False
            agent.last_started_at = run.last_started_at
            agent.run_end_requested = False
            session.flush()
            run_id = run.id

        task = run_agent.delay(run_id)

        with session_scope() as session:
            run = session.get(Run, run_id)
            if run is not None:
                run.task_id = task.id
                agent = session.get(Agent, run.agent_id)
                if agent is not None:
                    agent.task_id = task.id

        return {"ok": True, "run_id": run_id, "autorun_id": run_id, "task_id": task.id}

    @mcp.tool()
    def cancel_run(run_id: int) -> dict[str, Any]:
        task_id = None
        with session_scope() as session:
            run = session.get(Run, run_id)
            if run is None:
                return {"ok": False, "error": f"Autorun {run_id} not found."}
            if run.status not in RUN_ACTIVE_STATUSES:
                return {
                    "ok": False,
                    "error": "Autorun already stopped.",
                    "status": run.status,
                }
            stopped_at = utcnow()
            run.status = "stopped"
            run.run_end_requested = False
            task_id = run.task_id
            if task_id:
                run.last_run_task_id = task_id
                run.task_id = None
            run.last_stopped_at = stopped_at
            agent = session.get(Agent, run.agent_id)
            if agent is not None:
                agent.run_end_requested = False
                if task_id:
                    agent.last_run_task_id = task_id
                agent.task_id = None
                agent.last_stopped_at = stopped_at

        if task_id:
            try:
                celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
            except Exception:
                pass

        return {
            "ok": True,
            "run_id": run_id,
            "autorun_id": run_id,
            "status": "stopped",
            "task_id": task_id,
        }

    @mcp.tool()
    def end_run(run_id: int) -> dict[str, Any]:
        with session_scope() as session:
            run = session.get(Run, run_id)
            if run is None:
                return {"ok": False, "error": f"Autorun {run_id} not found."}
            if run.status not in RUN_ACTIVE_STATUSES:
                return {
                    "ok": False,
                    "error": "Autorun already stopped.",
                    "status": run.status,
                }
            run.run_end_requested = True
            if run.status in {"starting", "running"}:
                run.status = "stopping"
            agent = session.get(Agent, run.agent_id)
            if agent is not None:
                agent.run_end_requested = True
        return {"ok": True, "run_id": run_id, "autorun_id": run_id, "status": "stopping"}

    @mcp.tool()
    def set_run_active(run_id: int, enabled: bool) -> dict[str, Any]:
        if enabled:
            return start_run(run_id)
        return cancel_run(run_id)

    @mcp.tool()
    def toggle_pipeline_loop(
        pipeline_id: int,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        with session_scope() as session:
            pipeline = session.get(Pipeline, pipeline_id)
            if pipeline is None:
                return {"ok": False, "error": f"Pipeline {pipeline_id} not found."}
            if enabled is None:
                pipeline.loop_enabled = not bool(pipeline.loop_enabled)
            else:
                pipeline.loop_enabled = bool(enabled)
            loop_enabled = pipeline.loop_enabled
        return {"ok": True, "pipeline_id": pipeline_id, "loop_enabled": loop_enabled}

    @mcp.tool()
    def start_pipeline(pipeline_id: int) -> dict[str, Any]:
        with session_scope() as session:
            pipeline = session.get(Pipeline, pipeline_id)
            if pipeline is None:
                return {"ok": False, "error": f"Pipeline {pipeline_id} not found."}
            run = PipelineRun.create(
                session,
                pipeline_id=pipeline_id,
                status="queued",
            )
            run_id = run.id
        run_pipeline.delay(pipeline_id, run_id)
        return {"ok": True, "pipeline_id": pipeline_id, "run_id": run_id}

    @mcp.tool()
    def cancel_pipeline_run(
        run_id: int | None = None,
        pipeline_id: int | None = None,
    ) -> dict[str, Any]:
        if run_id is None and pipeline_id is None:
            return {"ok": False, "error": "run_id or pipeline_id is required."}
        revoke_ids: list[str] = []
        with session_scope() as session:
            run = None
            if run_id is not None:
                run = session.get(PipelineRun, run_id)
            elif pipeline_id is not None:
                run = (
                    session.execute(
                        select(PipelineRun)
                        .where(
                            PipelineRun.pipeline_id == pipeline_id,
                            PipelineRun.status.in_({"queued", "running"}),
                        )
                        .order_by(PipelineRun.created_at.desc())
                    )
                    .scalars()
                    .first()
                )
            if run is None:
                return {"ok": False, "error": "Pipeline run not found."}
            if run.status not in {"queued", "running"}:
                return {"ok": False, "error": "Pipeline run already stopped.", "status": run.status}
            now = utcnow()
            run.status = "canceled"
            run.finished_at = now
            if run.celery_task_id:
                revoke_ids.append(run.celery_task_id)
            tasks = (
                session.execute(
                    select(AgentTask).where(AgentTask.pipeline_run_id == run.id)
                )
                .scalars()
                .all()
            )
            for task in tasks:
                if task.status in {"pending", "queued", "running"}:
                    task.status = "canceled"
                    if not task.error:
                        task.error = "Canceled by user."
                    task.finished_at = now
                if task.celery_task_id:
                    revoke_ids.append(task.celery_task_id)

        for task_id in revoke_ids:
            try:
                celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
            except Exception:
                pass

        return {"ok": True, "run_id": run.id, "status": "canceled"}
