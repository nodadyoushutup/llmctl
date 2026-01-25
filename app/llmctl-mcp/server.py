from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Any

from fastmcp import FastMCP
from sqlalchemy import Boolean, DateTime, Integer, delete, func, select, update
from sqlalchemy import inspect as sa_inspect

from core.config import Config
from core.db import init_db, init_engine, session_scope, utcnow
from core.models import (
    Agent,
    AgentTask,
    Attachment,
    IntegrationSetting,
    MCPServer,
    Memory,
    Milestone,
    Pipeline,
    PipelineRun,
    PipelineStep,
    Role,
    Run,
    RUN_ACTIVE_STATUSES,
    Script,
    SCRIPT_TYPE_INIT,
    SCRIPT_TYPE_POST_INIT,
    SCRIPT_TYPE_POST_RUN,
    SCRIPT_TYPE_PRE_INIT,
    SCRIPT_TYPE_SKILL,
    TaskTemplate,
    agent_scripts,
    agent_task_attachments,
    agent_task_scripts,
    pipeline_step_attachments,
    task_template_attachments,
)
from core.task_kinds import QUICK_TASK_KIND, is_quick_task_kind
from services.celery_app import celery_app
from services.code_review import (
    CODE_REVIEW_FAIL_EMOJI,
    CODE_REVIEW_PASS_EMOJI,
    CODE_REVIEW_ROLE_PROMPT,
    CODE_REVIEW_TASK_KIND,
    ensure_code_reviewer_agent,
    ensure_code_reviewer_role,
)
from services.integrations import load_integration_settings
from services.tasks import (
    OUTPUT_INSTRUCTIONS_ONE_OFF,
    run_agent,
    run_agent_task,
    run_pipeline,
    _build_agent_prompt_payload,
)
from storage.attachment_storage import remove_attachment_file, write_attachment_file
from storage.script_storage import (
    ensure_script_file,
    remove_script_file,
    write_script_file,
)

# NOTE: Keep naming consistent with llmctl-studio models.
MODEL_REGISTRY = {
    "mcpserver": MCPServer,
    "mcp_server": MCPServer,
    "mcp_servers": MCPServer,
    "script": Script,
    "scripts": Script,
    "attachment": Attachment,
    "attachments": Attachment,
    "memory": Memory,
    "memories": Memory,
    "integrationsetting": IntegrationSetting,
    "integration_setting": IntegrationSetting,
    "integration_settings": IntegrationSetting,
    "agent": Agent,
    "agents": Agent,
    "autorun": Run,
    "autoruns": Run,
    "run": Run,
    "runs": Run,
    "role": Role,
    "roles": Role,
    "agenttask": AgentTask,
    "agent_task": AgentTask,
    "agent_tasks": AgentTask,
    "tasktemplate": TaskTemplate,
    "task_template": TaskTemplate,
    "task_templates": TaskTemplate,
    "pipeline": Pipeline,
    "pipelines": Pipeline,
    "pipelinestep": PipelineStep,
    "pipeline_step": PipelineStep,
    "pipeline_steps": PipelineStep,
    "pipelinerun": PipelineRun,
    "pipeline_run": PipelineRun,
    "pipeline_runs": PipelineRun,
    "milestone": Milestone,
    "milestones": Milestone,
}

READONLY_COLUMNS = {"id", "created_at", "updated_at"}

DEFAULT_LIMIT = int(os.getenv("LLMCTL_MCP_DEFAULT_LIMIT", "200"))
MAX_LIMIT = int(os.getenv("LLMCTL_MCP_MAX_LIMIT", "1000"))

# Initialize database engine on module import.
init_engine(Config.SQLALCHEMY_DATABASE_URI)
init_db()

mcp = FastMCP("llmctl-mcp", json_response=True)


def _normalize_model_name(model_name: str) -> str:
    return (
        model_name.strip().lower().replace("-", "_").replace(" ", "_")
    )


def _resolve_model(model_name: str):
    if not model_name:
        raise ValueError("Model name is required.")
    key = _normalize_model_name(model_name)
    model = MODEL_REGISTRY.get(key)
    if model is None:
        known = sorted({cls.__name__ for cls in MODEL_REGISTRY.values()})
        raise ValueError(f"Unknown model '{model_name}'. Available: {', '.join(known)}")
    return model


def _column_map(model) -> dict[str, Any]:
    mapper = sa_inspect(model)
    return {column.key: column for column in mapper.columns}


def _relationship_map(model) -> dict[str, Any]:
    mapper = sa_inspect(model)
    return {rel.key: rel for rel in mapper.relationships}


def _coerce_value(column, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(column.type, Boolean):
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if isinstance(column.type, Integer):
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        return value
    if isinstance(column.type, DateTime):
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return value
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _serialize_relationships(obj, include: bool) -> dict[str, Any]:
    if not include:
        return {}
    data: dict[str, Any] = {}
    mapper = sa_inspect(obj.__class__)
    for rel in mapper.relationships:
        key = rel.key
        if rel.uselist:
            items = getattr(obj, key) or []
            data[f"{key}_ids"] = [getattr(item, "id", None) for item in items]
        else:
            item = getattr(obj, key)
            data[f"{key}_id"] = getattr(item, "id", None) if item else None
    return data


def _serialize_model(obj, include_relationships: bool = False) -> dict[str, Any]:
    data = {}
    for column in sa_inspect(obj.__class__).columns:
        data[column.key] = _serialize_value(getattr(obj, column.key))
    data.update(_serialize_relationships(obj, include_relationships))
    return data


def _apply_relationship(obj, rel_key: str, value: Any, session) -> None:
    relationships = _relationship_map(obj.__class__)
    rel = relationships[rel_key]
    related_cls = rel.mapper.class_
    def _coerce_id(raw: Any) -> int:
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str) and raw.strip().isdigit():
            return int(raw.strip())
        raise ValueError(f"Relationship '{rel_key}' expects an id.")
    if rel.uselist:
        if value is None:
            setattr(obj, rel_key, [])
            return
        if not isinstance(value, list):
            raise ValueError(f"Relationship '{rel_key}' expects a list of ids.")
        if not value:
            setattr(obj, rel_key, [])
            return
        ids = [_coerce_id(item_id) for item_id in value]
        items = (
            session.execute(select(related_cls).where(related_cls.id.in_(ids)))
            .scalars()
            .all()
        )
        items_by_id = {item.id: item for item in items}
        ordered = [items_by_id[item_id] for item_id in ids if item_id in items_by_id]
        setattr(obj, rel_key, ordered)
    else:
        if value is None:
            setattr(obj, rel_key, None)
            return
        item_id = _coerce_id(value)
        item = session.get(related_cls, item_id)
        if item is None:
            raise ValueError(f"Related id {item_id} not found for '{rel_key}'.")
        setattr(obj, rel_key, item)


def _apply_data(obj, data: dict[str, Any], session) -> None:
    if not isinstance(data, dict):
        raise ValueError("Data must be a dictionary.")
    columns = _column_map(obj.__class__)
    relationships = _relationship_map(obj.__class__)
    unknown = set(data.keys()) - set(columns.keys()) - set(relationships.keys())
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")
    for key, value in data.items():
        if key in columns:
            if key in READONLY_COLUMNS:
                continue
            setattr(obj, key, _coerce_value(columns[key], value))
        elif key in relationships:
            _apply_relationship(obj, key, value, session)


def _ensure_script_storage(session, script: Script) -> None:
    path = ensure_script_file(
        script.id,
        script.file_name,
        script.content,
        script.file_path,
    )
    if script.file_path != str(path):
        script.file_path = str(path)
        session.flush()


def _clamp_limit(limit: int | None) -> int | None:
    if limit is None:
        return None
    limit = max(0, int(limit))
    return min(limit, MAX_LIMIT)


SCRIPT_TYPE_KEYS = {
    "pre_init": SCRIPT_TYPE_PRE_INIT,
    "init": SCRIPT_TYPE_INIT,
    "post_init": SCRIPT_TYPE_POST_INIT,
    "post_run": SCRIPT_TYPE_POST_RUN,
    "skill": SCRIPT_TYPE_SKILL,
}


def _normalize_script_type_key(raw: str) -> str:
    if not raw:
        raise ValueError("Script type is required.")
    key = raw.strip().lower().replace("-", "_").replace(" ", "_")
    if key in SCRIPT_TYPE_KEYS:
        return SCRIPT_TYPE_KEYS[key]
    if key in SCRIPT_TYPE_KEYS.values():
        return key
    valid = ", ".join(sorted(SCRIPT_TYPE_KEYS))
    raise ValueError(f"Unknown script type '{raw}'. Use: {valid}.")


def _parse_script_ids_by_type(
    raw: dict[str, Any] | None,
) -> dict[str, list[int]]:
    grouped = {value: [] for value in SCRIPT_TYPE_KEYS.values()}
    if not raw:
        return grouped
    if not isinstance(raw, dict):
        raise ValueError("script_ids_by_type must be a dictionary.")
    for key, value in raw.items():
        script_type = _normalize_script_type_key(str(key))
        if value is None:
            ids: list[int] = []
        elif isinstance(value, list):
            ids = []
            for item in value:
                if isinstance(item, bool):
                    raise ValueError("Script ids must be integers.")
                if isinstance(item, int):
                    ids.append(item)
                elif isinstance(item, str) and item.strip().isdigit():
                    ids.append(int(item.strip()))
                else:
                    raise ValueError("Script ids must be integers.")
        else:
            raise ValueError("Script ids must be a list.")
        grouped[script_type] = ids
    return grouped


def _resolve_script_ids_by_type(
    session,
    script_ids_by_type: dict[str, list[int]],
) -> dict[str, list[int]]:
    all_ids: list[int] = []
    for ids in script_ids_by_type.values():
        all_ids.extend(ids)
    if not all_ids:
        return script_ids_by_type
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("Duplicate scripts are not allowed.")
    scripts = (
        session.execute(select(Script).where(Script.id.in_(all_ids)))
        .scalars()
        .all()
    )
    scripts_by_id = {script.id: script for script in scripts}
    if len(scripts_by_id) != len(set(all_ids)):
        raise ValueError("One or more scripts were not found.")
    for script_type, ids in script_ids_by_type.items():
        for script_id in ids:
            script = scripts_by_id[script_id]
            if script.script_type != script_type:
                raise ValueError("Script selection is invalid.")
    return script_ids_by_type


def _set_script_links(
    session,
    table,
    fk_name: str,
    fk_value: int,
    script_ids_by_type: dict[str, list[int]],
) -> None:
    session.execute(delete(table).where(table.c[fk_name] == fk_value))
    rows: list[dict[str, int]] = []
    for ids in script_ids_by_type.values():
        for position, script_id in enumerate(ids, start=1):
            rows.append(
                {
                    fk_name: fk_value,
                    "script_id": script_id,
                    "position": position,
                }
            )
    if rows:
        session.execute(table.insert(), rows)


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


def _sync_script_storage(session, script: Script, previous_path: str | None) -> None:
    path = write_script_file(script.id, script.file_name, script.content)
    script.file_path = str(path)
    session.flush()
    if previous_path and previous_path != script.file_path:
        remove_script_file(previous_path)


def _build_code_review_prompt(
    repo: str,
    pr_number: int,
    pr_title: str | None,
    pr_url: str | None,
    role_prompt: str | None = None,
) -> str:
    pr_label = f"{repo}#{pr_number}" if repo else f"#{pr_number}"
    base_prompt = role_prompt.strip() if role_prompt else CODE_REVIEW_ROLE_PROMPT
    lines = [
        base_prompt,
        "",
        f"Pull request to review: {pr_label}",
    ]
    if pr_title:
        lines.append(f"Title: {pr_title}")
    if pr_url:
        lines.append(f"URL: {pr_url}")
    lines.extend(
        [
            "",
            "Requirements:",
            "- Use the GitHub MCP tools to read the PR, diff, and relevant files.",
            "- Leave feedback as a comment on the pull request (not just in this response).",
            (
                f"- Start the comment with {CODE_REVIEW_PASS_EMOJI} pass "
                f"or {CODE_REVIEW_FAIL_EMOJI} fail."
            ),
            "- Cite explicit files/lines or include short code blocks with file paths.",
            "- Do a full, proper code review every time.",
            "- If you cannot post a comment, explain why in your output.",
        ]
    )
    return "\n".join(lines)


def _build_quick_task_prompt(agent: Agent, prompt: str) -> str:
    payload: dict[str, object] = {
        "prompt": prompt,
        "output_instructions": OUTPUT_INSTRUCTIONS_ONE_OFF,
    }
    agent_payload = _build_agent_prompt_payload(agent, include_autoprompt=False)
    if agent_payload:
        payload["agent"] = agent_payload
    return json.dumps(payload, indent=2, sort_keys=True)


def _delete_agent_record(session, agent: Agent) -> dict[str, Any]:
    active_run_id = (
        session.execute(
            select(Run.id).where(
                Run.agent_id == agent.id,
                Run.status.in_(RUN_ACTIVE_STATUSES),
            )
        )
        .scalar_one_or_none()
    )
    if active_run_id:
        return {
            "ok": False,
            "error": "Disable autorun before deleting.",
            "active_run_id": active_run_id,
        }
    agent.mcp_servers = []
    agent.scripts = []
    runs = (
        session.execute(select(Run).where(Run.agent_id == agent.id))
        .scalars()
        .all()
    )
    run_ids = [run.id for run in runs]
    tasks = (
        session.execute(select(AgentTask).where(AgentTask.agent_id == agent.id))
        .scalars()
        .all()
    )
    for task in tasks:
        task.agent_id = None
    if run_ids:
        session.execute(
            update(AgentTask)
            .where(AgentTask.run_id.in_(run_ids))
            .values(run_id=None)
        )
        for run in runs:
            session.delete(run)
    session.delete(agent)
    return {
        "ok": True,
        "deleted": agent.id,
        "detached_tasks": len(tasks),
        "deleted_runs": len(runs),
        "deleted_autoruns": len(runs),
    }


def _delete_role_record(session, role: Role) -> dict[str, Any]:
    assigned_agents = (
        session.execute(select(Agent).where(Agent.role_id == role.id))
        .scalars()
        .all()
    )
    for agent in assigned_agents:
        agent.role_id = None
    session.delete(role)
    return {
        "ok": True,
        "deleted": role.id,
        "detached_agents": len(assigned_agents),
    }


def _delete_task_template_record(session, template: TaskTemplate) -> dict[str, Any]:
    steps = (
        session.execute(
            select(PipelineStep).where(
                PipelineStep.task_template_id == template.id
            )
        )
        .scalars()
        .all()
    )
    step_ids = [step.id for step in steps]
    if step_ids:
        tasks = (
            session.execute(
                select(AgentTask).where(AgentTask.pipeline_step_id.in_(step_ids))
            )
            .scalars()
            .all()
        )
        for task in tasks:
            task.pipeline_step_id = None
    tasks_with_template = (
        session.execute(
            select(AgentTask).where(AgentTask.task_template_id == template.id)
        )
        .scalars()
        .all()
    )
    for task in tasks_with_template:
        task.task_template_id = None
    for step in steps:
        session.delete(step)
    session.delete(template)
    return {
        "ok": True,
        "deleted": template.id,
        "deleted_steps": len(steps),
    }


def _delete_pipeline_record(session, pipeline: Pipeline) -> dict[str, Any]:
    steps = (
        session.execute(select(PipelineStep).where(PipelineStep.pipeline_id == pipeline.id))
        .scalars()
        .all()
    )
    runs = (
        session.execute(select(PipelineRun).where(PipelineRun.pipeline_id == pipeline.id))
        .scalars()
        .all()
    )
    step_ids = [step.id for step in steps]
    run_ids = [run.id for run in runs]
    task_ids = set(
        session.execute(
            select(AgentTask.id).where(AgentTask.pipeline_id == pipeline.id)
        )
        .scalars()
        .all()
    )
    if step_ids:
        task_ids.update(
            session.execute(
                select(AgentTask.id).where(AgentTask.pipeline_step_id.in_(step_ids))
            )
            .scalars()
            .all()
        )
    if run_ids:
        task_ids.update(
            session.execute(
                select(AgentTask.id).where(AgentTask.pipeline_run_id.in_(run_ids))
            )
            .scalars()
            .all()
        )
    if task_ids:
        tasks = (
            session.execute(select(AgentTask).where(AgentTask.id.in_(task_ids)))
            .scalars()
            .all()
        )
        for task in tasks:
            session.delete(task)
    for step in steps:
        session.delete(step)
    for run in runs:
        session.delete(run)
    session.delete(pipeline)
    return {
        "ok": True,
        "deleted": pipeline.id,
        "deleted_steps": len(steps),
        "deleted_runs": len(runs),
        "deleted_pipeline_runs": len(runs),
    }


def _delete_script_record(session, script: Script) -> tuple[dict[str, Any], str | None]:
    script_path = script.file_path
    if script.agents:
        script.agents = []
    if script.tasks:
        script.tasks = []
    session.delete(script)
    return {
        "ok": True,
        "deleted": script.id,
    }, script_path


def _delete_attachment_record(
    session,
    attachment: Attachment,
) -> tuple[dict[str, Any], str | None]:
    file_path = attachment.file_path
    _unlink_attachment(session, attachment.id)
    session.delete(attachment)
    return {
        "ok": True,
        "deleted": attachment.id,
    }, file_path


def _delete_run_record(session, run: Run) -> dict[str, Any]:
    if run.status in RUN_ACTIVE_STATUSES:
        return {
            "ok": False,
            "error": "Stop the autorun before deleting.",
            "status": run.status,
        }
    session.execute(
        update(AgentTask)
        .where(AgentTask.run_id == run.id)
        .values(run_id=None)
    )
    session.delete(run)
    return {"ok": True, "deleted": run.id}


def _delete_pipeline_run_record(session, run: PipelineRun) -> dict[str, Any]:
    if run.status in {"queued", "running"}:
        return {
            "ok": False,
            "error": "Stop the pipeline run before deleting.",
            "status": run.status,
        }
    session.execute(
        update(AgentTask)
        .where(AgentTask.pipeline_run_id == run.id)
        .values(pipeline_run_id=None)
    )
    session.delete(run)
    return {"ok": True, "deleted": run.id}


def _delete_task_record(session, task: AgentTask) -> dict[str, Any]:
    if task.status in {"queued", "running"} and task.celery_task_id:
        if Config.CELERY_REVOKE_ON_STOP:
            try:
                celery_app.control.revoke(
                    task.celery_task_id, terminate=True, signal="SIGTERM"
                )
            except Exception:
                pass
    session.delete(task)
    return {"ok": True, "deleted": task.id}


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
    limit = _clamp_limit(DEFAULT_LIMIT if limit is None else limit)
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


def run() -> None:
    host = os.getenv("LLMCTL_MCP_HOST", "0.0.0.0")
    port = int(os.getenv("LLMCTL_MCP_PORT", "9020"))
    path = os.getenv("LLMCTL_MCP_PATH", "/mcp")
    transport = os.getenv("LLMCTL_MCP_TRANSPORT", "http")
    mcp.run(transport=transport, host=host, port=port, path=path)


if __name__ == "__main__":
    run()
