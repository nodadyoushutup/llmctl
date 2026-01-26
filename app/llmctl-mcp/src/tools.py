from __future__ import annotations

from typing import Any

from datetime import timedelta

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

from attachments import (
    _attach_attachments,
    _create_attachment_record,
    _decode_base64,
    _delete_attachment_if_unused,
    _resolve_attachment_target,
)
from constants import DEFAULT_LIMIT, MAX_LIMIT, MODEL_REGISTRY
from db_utils import (
    _clamp_limit,
    _coerce_value,
    _column_map,
    _resolve_model,
    _serialize_model,
)
from prompts import _build_code_review_prompt, _build_quick_task_prompt
from scripts import _parse_script_ids_by_type, _resolve_script_ids_by_type, _set_script_links


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def llmctl_get_model() -> dict[str, Any]:
        """Read/list all LLMCTL Studio data models available for MCP queries.

        Use this to discover valid model names before calling llmctl_get_model_schema
        or other model-specific tools. Prefer this over guessing model names.
        For row-level access, use llmctl_get_model_rows once you have the model name.
        Synonyms: read, list.
        Keywords: models list, model names, available tables, database models.
        """
        models = sorted({cls.__name__ for cls in MODEL_REGISTRY.values()})
        return {"ok": True, "models": models}

    @mcp.tool()
    def llmctl_get_model_schema(model: str) -> dict[str, Any]:
        """Read/list a model's schema, columns, and relationships.

        Use this to confirm field names for filtering/ordering and to see related
        models. Do not infer schema from code or files; ask this tool instead.
        For actual records, use llmctl_get_model_rows with the model name.
        Synonyms: read, list.
        Keywords: schema, fields, columns, relationships, attributes.
        """
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
    def llmctl_get_model_rows(
        model: str,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order_by: str | None = "id",
        descending: bool = False,
        include_relationships: bool = False,
    ) -> dict[str, Any]:
        """Read/list rows from any LLMCTL Studio model.

        Use this when you need records for a specific model without a bespoke tool.
        Prefer llmctl_get_model_schema first if you are unsure of fields/filters.
        Filters are column-based and support simple operators:
        - value: equals
        - {"op": "in", "value": [..]}
        - {"op": "lt|lte|gt|gte|ne|like|ilike", "value": ...}
        Synonyms: read, list, query.
        Keywords: generic model query, rows, records.
        """
        model_cls = _resolve_model(model)
        columns = _column_map(model_cls)
        stmt = select(model_cls)
        if filters:
            if not isinstance(filters, dict):
                return {"ok": False, "error": "filters must be an object."}
            for key, raw in filters.items():
                if key not in columns:
                    return {"ok": False, "error": f"Unknown filter column '{key}'."}
                col = columns[key]
                if isinstance(raw, dict) and "op" in raw:
                    op = str(raw.get("op", "")).strip().lower()
                    value = raw.get("value")
                    if op == "in":
                        if not isinstance(value, list):
                            return {
                                "ok": False,
                                "error": f"Filter '{key}' op 'in' expects a list.",
                            }
                        coerced = [_coerce_value(col, item) for item in value]
                        stmt = stmt.where(col.in_(coerced))
                    elif op in {"lt", "lte", "gt", "gte", "ne", "like", "ilike", "eq"}:
                        coerced = _coerce_value(col, value)
                        if op == "eq":
                            stmt = (
                                stmt.where(col.is_(None))
                                if coerced is None
                                else stmt.where(col == coerced)
                            )
                        elif op == "ne":
                            stmt = (
                                stmt.where(col.is_not(None))
                                if coerced is None
                                else stmt.where(col != coerced)
                            )
                        elif op == "lt":
                            stmt = stmt.where(col < coerced)
                        elif op == "lte":
                            stmt = stmt.where(col <= coerced)
                        elif op == "gt":
                            stmt = stmt.where(col > coerced)
                        elif op == "gte":
                            stmt = stmt.where(col >= coerced)
                        elif op == "like":
                            stmt = stmt.where(col.like(coerced))
                        elif op == "ilike":
                            stmt = stmt.where(col.ilike(coerced))
                    else:
                        return {
                            "ok": False,
                            "error": f"Unsupported filter op '{op}' for '{key}'.",
                        }
                else:
                    coerced = _coerce_value(col, raw)
                    if coerced is None:
                        stmt = stmt.where(col.is_(None))
                    else:
                        stmt = stmt.where(col == coerced)
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
    def llmctl_get_pipeline(
        limit: int | None = None,
        offset: int = 0,
        order_by: str | None = "id",
        descending: bool = False,
        include_steps: bool = False,
        pipeline_id: int | None = None,
    ) -> dict[str, Any]:
        """Read/list LLMCTL Studio pipelines from the database.

        Use this for any request about pipelines, IDs, names, counts, or summaries.
        If pipeline_id is provided, return that specific pipeline.
        Do not use filesystem or repo inspection to answer pipeline questions.
        For additional fields or related records, use llmctl_get_model_rows.
        Synonyms: read, list.
        Keywords: pipelines list, workflows, pipeline summary, pipeline catalog.
        """
        if pipeline_id is not None:
            with session_scope() as session:
                item = session.get(Pipeline, pipeline_id)
                if item is None:
                    return {"ok": False, "error": f"Pipeline {pipeline_id} not found."}
                return {"ok": True, "item": _serialize_model(item, include_steps)}
        columns = _column_map(Pipeline)
        stmt = select(Pipeline)
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
            payload = [_serialize_model(item, include_steps) for item in items]
            return {"ok": True, "count": len(payload), "items": payload}

    @mcp.tool()
    def llmctl_get_agent_task(
        hours: int = 24,
        limit: int | None = None,
        offset: int = 0,
        order_by: str | None = "finished_at",
        descending: bool = True,
    ) -> dict[str, Any]:
        """Read/list LLMCTL Studio tasks completed in the last N hours.

        Use this for "recent tasks", "what ran", "completed tasks", or time-window
        activity questions. Set hours to control the lookback window.
        For additional fields or related records, use llmctl_get_model_rows.
        Synonyms: read, list.
        Keywords: recent tasks, completed tasks, task history, activity log.
        """
        if hours <= 0:
            return {"ok": False, "error": "hours must be greater than 0."}
        columns = _column_map(AgentTask)
        cutoff = utcnow() - timedelta(hours=hours)
        stmt = select(AgentTask).where(
            AgentTask.status == "succeeded",
            AgentTask.finished_at.is_not(None),
            AgentTask.finished_at >= cutoff,
        )
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
            payload = [_serialize_model(item, include_relationships=False) for item in items]
            return {"ok": True, "count": len(payload), "items": payload}

    @mcp.tool()
    def set_agent_scripts(
        agent_id: int,
        script_ids_by_type: dict[str, list[int]] | None = None,
    ) -> dict[str, Any]:
        """Replace the scripts attached to an agent by script type.

        Use to configure agent workflow scripts (pre_init, init, post_run, etc.).
        This overwrites existing script links for the agent.
        Keywords: agent scripts, workflow scripts, pre_init, post_run.

        IDs: agent_id and script ids are numeric LLMCTL Studio IDs.
        Use llmctl_get_model/llmctl_get_model_schema or list queries to discover valid IDs.
        """
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
        """Replace the scripts attached to a specific task by script type.

        Use script_ids_by_type to map stages (init, post_run, etc.) to script ids.
        This overwrites existing script links for the task.
        Keywords: task scripts, task workflow, init script, post_run script.

        IDs: task_id and script ids are numeric LLMCTL Studio IDs.
        """
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
        """Reorder all steps in a pipeline by supplying the full ordered id list.

        The list must include every step in the pipeline. Use this to change
        pipeline execution order.
        Keywords: reorder steps, pipeline order, step sequence.

        IDs: pipeline_id and ordered_step_ids are numeric LLMCTL Studio IDs.
        """
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
        """Create an attachment stored in LLMCTL Studio.

        Use this to upload text or binary content before attaching it to a record.
        Follow up with attach_attachment to link it to a task or step.
        Keywords: upload file, create attachment, add file, store file.
        """
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
        """Attach an existing attachment to a target model record.

        Use this after create_attachment to link files to tasks, steps, or other records.
        Targets include task, pipeline_step, and other attachment-aware models.
        Keywords: link attachment, attach file, add attachment to record.

        IDs: target_id and attachment_id are numeric LLMCTL Studio IDs.
        """
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
        """Detach an attachment from a target; optionally delete if unused.

        Use this to remove files from records while keeping or cleaning up storage.
        Set delete_if_unused to remove orphaned attachments.
        Keywords: remove attachment, unlink file, delete attachment.

        IDs: target_id and attachment_id are numeric LLMCTL Studio IDs.
        """
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
        """Queue a task for an agent, optionally with scripts and attachments.

        Use this to start a standard task run through the agent pipeline.
        Prefer enqueue_quick_task for lightweight one-off prompts.
        Keywords: queue task, run task, start task, agent task.

        IDs: agent_id is a numeric LLMCTL Studio agent ID.
        """
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
        """Queue a quick task for an agent.

        Use this for lightweight, single-shot tasks without full pipeline context.
        Keywords: quick task, short task, one-off task.

        IDs: agent_id is a numeric LLMCTL Studio agent ID.
        """
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
        """Queue a GitHub PR code review task using configured GitHub integration.

        Requires GitHub repo and PAT to be configured in integrations.
        Use this when the user asks for a PR review.
        Keywords: code review, PR review, GitHub review.

        IDs: pr_number is the GitHub PR number (not a Studio record ID).
        """
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
        """Start an autorun for an agent.

        Use this to kick off the agent's background run loop.
        This creates a new autorun record and starts processing.
        Keywords: start agent, autorun start, run agent.

        IDs: agent_id is a numeric LLMCTL Studio agent ID.
        """
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
        """Request stop for the agent's active autorun.

        Use this to stop a running autorun without deleting the agent.
        Use end_run or cancel_run for specific autoruns if needed.
        Keywords: stop agent, stop autorun, halt agent.

        IDs: agent_id is a numeric LLMCTL Studio agent ID.
        """
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
        """Cancel a queued or running task.

        Use this to halt an in-progress task run and mark it canceled.
        Keywords: cancel task, stop task, abort task.

        IDs: task_id is a numeric LLMCTL Studio task ID.
        """
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
        """Start an existing autorun by id.

        Use this to resume or start a specific autorun record.
        Prefer start_agent when you do not have a run_id yet.
        Keywords: start run, autorun start, resume run.

        IDs: run_id is a numeric LLMCTL Studio autorun ID.
        """
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
        """Cancel a running autorun.

        Use this to force stop an autorun run immediately and revoke tasks.
        Keywords: cancel run, stop run, abort run.

        IDs: run_id is a numeric LLMCTL Studio autorun ID.
        """
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
        """Request graceful stop for a running autorun.

        Use this to signal the autorun to finish current work and stop.
        This is gentler than cancel_run.
        Keywords: end run, graceful stop, stop after current.

        IDs: run_id is a numeric LLMCTL Studio autorun ID.
        """
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
        """Start or cancel an autorun based on enabled flag.

        Use enabled=true to start; enabled=false to cancel.
        This is a convenience wrapper for start_run/cancel_run.
        Keywords: toggle run, enable run, disable run.

        IDs: run_id is a numeric LLMCTL Studio autorun ID.
        """
        if enabled:
            return start_run(run_id)
        return cancel_run(run_id)

    @mcp.tool()
    def toggle_pipeline_loop(
        pipeline_id: int,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        """Toggle or set a pipeline's loop mode.

        Use enabled to explicitly set; omit to toggle current state.
        Use this when asked to enable/disable pipeline looping.
        Keywords: loop pipeline, repeat pipeline, pipeline looping.

        IDs: pipeline_id is a numeric LLMCTL Studio pipeline ID.
        """
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
        """Start a pipeline run.

        Use this to queue the next run for a pipeline.
        Prefer this over enqueue_task for pipeline-level execution.
        Keywords: start pipeline, run pipeline, trigger pipeline.

        IDs: pipeline_id is a numeric LLMCTL Studio pipeline ID.
        """
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
        """Cancel a pipeline run by run id or latest run for pipeline id.

        Use pipeline_id to cancel the most recent active run for that pipeline.
        Use run_id for a specific pipeline run.
        Keywords: cancel pipeline, stop pipeline run, abort pipeline run.

        IDs: run_id and pipeline_id are numeric LLMCTL Studio IDs.
        """
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
