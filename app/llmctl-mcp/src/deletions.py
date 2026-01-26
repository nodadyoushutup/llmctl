from __future__ import annotations

from typing import Any

from sqlalchemy import select, update

from core.config import Config
from core.models import (
    Agent,
    AgentTask,
    Attachment,
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
