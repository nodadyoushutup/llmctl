from __future__ import annotations

from typing import Any

from sqlalchemy import select, update

from core.config import Config
from core.models import (
    Agent,
    AgentTask,
    Attachment,
    Role,
    Run,
    RUN_ACTIVE_STATUSES,
    Script,
)
from services.celery_app import celery_app


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


def _delete_script_record(session, script: Script) -> tuple[dict[str, Any], str | None]:
    script_path = script.file_path
    detached_tasks = len(script.tasks)
    detached_nodes = len(script.flowchart_nodes)
    if script.tasks:
        script.tasks = []
    if script.flowchart_nodes:
        script.flowchart_nodes = []
    session.delete(script)
    return {
        "ok": True,
        "deleted": script.id,
        "detached_bindings": detached_tasks + detached_nodes,
    }, script_path


def _delete_attachment_record(
    session,
    attachment: Attachment,
) -> tuple[dict[str, Any], str | None]:
    file_path = attachment.file_path
    from attachments import _unlink_attachment

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
