from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from fastmcp import FastMCP
from sqlalchemy import Boolean, DateTime, Integer, select
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
    TaskTemplate,
)
from services.celery_app import celery_app
from services.tasks import run_agent, run_pipeline
from storage.script_storage import ensure_script_file, remove_script_file

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
        _apply_data(item, data, session)
        session.flush()
        if isinstance(item, Script):
            _ensure_script_storage(session, item)
        return {"ok": True, "item": _serialize_model(item, include_relationships)}


@mcp.tool()
def delete_record(model: str, record_id: int) -> dict[str, Any]:
    model_cls = _resolve_model(model)
    script_path = None
    with session_scope() as session:
        item = session.get(model_cls, record_id)
        if item is None:
            return {"ok": False, "error": f"{model_cls.__name__} {record_id} not found."}
        if isinstance(item, Script):
            script_path = item.file_path
        session.delete(item)
    if script_path:
        remove_script_file(script_path)
    return {"ok": True, "deleted": record_id}


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
            return {"ok": False, "error": f"Run {run_id} not found."}
        if run.status in RUN_ACTIVE_STATUSES:
            return {"ok": False, "error": "Run already active.", "status": run.status}
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
                "error": "Agent already has an active run.",
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

    return {"ok": True, "run_id": run_id, "task_id": task.id}


@mcp.tool()
def cancel_run(run_id: int) -> dict[str, Any]:
    task_id = None
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            return {"ok": False, "error": f"Run {run_id} not found."}
        if run.status not in RUN_ACTIVE_STATUSES:
            return {"ok": False, "error": "Run already stopped.", "status": run.status}
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

    return {"ok": True, "run_id": run_id, "status": "stopped", "task_id": task_id}


@mcp.tool()
def end_run(run_id: int) -> dict[str, Any]:
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            return {"ok": False, "error": f"Run {run_id} not found."}
        if run.status not in RUN_ACTIVE_STATUSES:
            return {"ok": False, "error": "Run already stopped.", "status": run.status}
        run.run_end_requested = True
        if run.status in {"starting", "running"}:
            run.status = "stopping"
        agent = session.get(Agent, run.agent_id)
        if agent is not None:
            agent.run_end_requested = True
    return {"ok": True, "run_id": run_id, "status": "stopping"}


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
