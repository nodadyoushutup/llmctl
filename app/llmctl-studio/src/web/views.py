from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import selectinload

from services.celery_app import celery_app
from services.code_review import (
    CODE_REVIEW_FAIL_EMOJI,
    CODE_REVIEW_PASS_EMOJI,
    CODE_REVIEW_ROLE_PROMPT,
    CODE_REVIEW_TASK_KIND,
    ensure_code_reviewer_agent,
    ensure_code_reviewer_role,
)
from core.config import Config
from core.db import session_scope, utcnow
from services.integrations import (
    LLM_PROVIDER_LABELS,
    LLM_PROVIDERS,
    integration_overview as _integration_overview,
    load_integration_settings as _load_integration_settings,
    resolve_default_model_id,
    resolve_enabled_llm_providers,
    resolve_llm_provider,
    save_integration_settings as _save_integration_settings,
)
from core.models import (
    Agent,
    AgentTask,
    Attachment,
    LLMModel,
    Memory,
    MCPServer,
    Milestone,
    Pipeline,
    PipelineRun,
    PipelineStep,
    Run,
    Role,
    RUN_ACTIVE_STATUSES,
    Script,
    agent_scripts,
    agent_task_attachments,
    agent_task_scripts,
    pipeline_step_attachments,
    task_template_attachments,
    SCRIPT_TYPE_CHOICES,
    SCRIPT_TYPE_LABELS,
    SCRIPT_TYPE_INIT,
    SCRIPT_TYPE_POST_INIT,
    SCRIPT_TYPE_POST_RUN,
    SCRIPT_TYPE_PRE_INIT,
    SCRIPT_TYPE_SKILL,
    TaskTemplate,
)
from core.mcp_config import format_mcp_config, validate_server_key
from storage.script_storage import read_script_file, remove_script_file, write_script_file
from storage.attachment_storage import remove_attachment_file, write_attachment_file
from core.task_stages import TASK_STAGE_ORDER
from core.task_kinds import QUICK_TASK_KIND, is_quick_task_kind, task_kind_label
from services.tasks import (
    OUTPUT_INSTRUCTIONS_ONE_OFF,
    run_agent,
    run_agent_task,
    run_pipeline,
)

bp = Blueprint("agents", __name__, template_folder="templates")
logger = logging.getLogger(__name__)

DEFAULT_TASKS_PER_PAGE = 10
TASKS_PER_PAGE_OPTIONS = (10, 25, 50, 100)
DEFAULT_RUNS_PER_PAGE = DEFAULT_TASKS_PER_PAGE
RUNS_PER_PAGE_OPTIONS = TASKS_PER_PAGE_OPTIONS
CODEX_MODEL_PREFERENCE = (
    "gpt-5.2-codex",
    "gpt-5.2",
    "gpt-5.1-codex-max",
    "gpt-5.1-codex-mini",
)
GEMINI_MODEL_OPTIONS = (
    "gemini-3-pro-preview",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
)
IMAGE_ATTACHMENT_EXTENSIONS = {
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".webp",
}
SCRIPT_TYPE_FIELDS = {
    SCRIPT_TYPE_PRE_INIT: "pre_init_script_ids",
    SCRIPT_TYPE_INIT: "init_script_ids",
    SCRIPT_TYPE_POST_INIT: "post_init_script_ids",
    SCRIPT_TYPE_POST_RUN: "post_run_script_ids",
    SCRIPT_TYPE_SKILL: "skill_script_ids",
}
QUICK_AGENT_NAME = "Quick"


def _parse_agent_payload(raw_json: str) -> tuple[str, str | None, str | None]:
    payload = json.loads(raw_json)

    prompt_text = None
    name = None

    if isinstance(payload, dict):
        name_value = payload.get("name") or payload.get("title")
        if isinstance(name_value, str):
            name = name_value.strip() or None
        prompt_value = payload.get("prompt")
        if isinstance(prompt_value, str):
            prompt_text = prompt_value
        formatted = json.dumps(payload, indent=2, sort_keys=True)
        return formatted, prompt_text, name

    if isinstance(payload, str):
        return raw_json.strip(), payload, None

    formatted = json.dumps(payload, indent=2, sort_keys=True)
    return formatted, None, None


def _parse_task_prompt(raw_prompt: str | None) -> tuple[str | None, str | None]:
    if not raw_prompt:
        return None, None
    stripped = raw_prompt.strip()
    if not stripped:
        return raw_prompt, None
    try:
        payload = json.loads(raw_prompt)
    except (json.JSONDecodeError, TypeError):
        return raw_prompt, None
    formatted = json.dumps(payload, indent=2, sort_keys=True)
    prompt_text = None
    if isinstance(payload, dict):
        prompt_value = payload.get("prompt")
        if isinstance(prompt_value, str):
            prompt_text = prompt_value
    elif isinstance(payload, str):
        prompt_text = payload
    return prompt_text, formatted


def _parse_role_details(raw_json: str) -> str:
    if not raw_json:
        return "{}"
    payload = json.loads(raw_json)
    if not isinstance(payload, dict):
        raise ValueError("Role details must be a JSON object.")
    return json.dumps(payload, indent=2, sort_keys=True)


def _save_uploaded_attachments(
    session,
    uploads,
) -> list[Attachment]:
    attachments: list[Attachment] = []
    for upload in uploads:
        if not upload or not upload.filename:
            continue
        file_name = Path(upload.filename).name if upload.filename else ""
        if not file_name or file_name in {".", ".."}:
            raise ValueError("Attachment file name is invalid.")
        content = upload.read()
        content_type = (upload.mimetype or "").strip() or None
        attachment = Attachment.create(
            session,
            file_name=file_name,
            file_path=None,
            content_type=content_type,
            size_bytes=len(content) if content is not None else 0,
        )
        path = write_attachment_file(attachment.id, file_name, content)
        attachment.file_path = str(path)
        attachments.append(attachment)
    return attachments


def _attach_attachments(target, attachments: list[Attachment]) -> None:
    if not attachments:
        return
    existing_ids = {item.id for item in getattr(target, "attachments", [])}
    for attachment in attachments:
        if attachment.id in existing_ids:
            continue
        target.attachments.append(attachment)


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


def _is_image_attachment(attachment: Attachment) -> bool:
    if attachment.content_type and attachment.content_type.startswith("image/"):
        return True
    suffix = Path(attachment.file_name or "").suffix.lower()
    return bool(suffix) and suffix in IMAGE_ATTACHMENT_EXTENSIONS


def _load_prompt_payload(prompt_json: str | None, prompt_text: str | None) -> object | None:
    if prompt_json:
        try:
            return json.loads(prompt_json)
        except json.JSONDecodeError:
            pass
    if prompt_text:
        return prompt_text
    return prompt_json


def _load_role_details(role: Role) -> dict[str, object]:
    if not role.details_json:
        return {}
    try:
        payload = json.loads(role.details_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_role_payload(role: Role) -> dict[str, object]:
    return {
        "name": role.name,
        "description": role.description or "",
        "details": _load_role_details(role),
    }


def _build_agent_scripts_payload(scripts: list[Script]) -> dict[str, object] | None:
    if not scripts:
        return None
    grouped = {
        "pre_init": [],
        "init": [],
        "post_init": [],
        "post_run": [],
        "skill": [],
    }
    for script in scripts:
        path = script.file_path or script.file_name
        entry = {
            "description": script.description or "",
            "path": path,
        }
        if script.script_type == SCRIPT_TYPE_PRE_INIT:
            grouped["pre_init"].append(entry)
        elif script.script_type == SCRIPT_TYPE_INIT:
            grouped["init"].append(entry)
        elif script.script_type == SCRIPT_TYPE_POST_INIT:
            grouped["post_init"].append(entry)
        elif script.script_type == SCRIPT_TYPE_POST_RUN:
            grouped["post_run"].append(entry)
        elif script.script_type == SCRIPT_TYPE_SKILL:
            grouped["skill"].append(entry)
    payload: dict[str, object] = {
        "description": (
            "Scripts attached to this agent. Skill scripts are available to the LLM as needed; "
            "other scripts are for reference."
        ),
    }
    payload.update(grouped)
    return payload


def _build_agent_payload(
    agent: Agent,
    include_autoprompt: bool = True,
) -> dict[str, object]:
    description = agent.description or agent.name or ""
    payload: dict[str, object] = {"description": description}
    if include_autoprompt and agent.autonomous_prompt:
        payload["autoprompt"] = agent.autonomous_prompt
    scripts_payload = _build_agent_scripts_payload(list(agent.scripts))
    if scripts_payload:
        payload["scripts"] = scripts_payload
    return payload


def _build_agent_prompt_payload(
    agent: Agent,
    include_autoprompt: bool = True,
) -> object | None:
    agent_payload = _build_agent_payload(agent, include_autoprompt=include_autoprompt)
    role = agent.role
    if agent.role_id and role is not None:
        agent_payload["role"] = _build_role_payload(role)
        return agent_payload
    return agent_payload


def _group_scripts_by_type(scripts: list[Script]) -> dict[str, list[Script]]:
    grouped = {script_type: [] for script_type in SCRIPT_TYPE_FIELDS}
    for script in scripts:
        grouped.setdefault(script.script_type, []).append(script)
    for script_list in grouped.values():
        script_list.sort(key=lambda item: item.file_name.lower())
    return grouped


def _group_selected_scripts_by_type(
    scripts: list[Script],
) -> dict[str, list[Script]]:
    grouped = {script_type: [] for script_type in SCRIPT_TYPE_FIELDS}
    for script in scripts:
        grouped.setdefault(script.script_type, []).append(script)
    return grouped


def _parse_script_selection() -> tuple[dict[str, list[int]], list[int], str | None]:
    script_ids_by_type: dict[str, list[int]] = {}
    try:
        for script_type, field_name in SCRIPT_TYPE_FIELDS.items():
            values = [value.strip() for value in request.form.getlist(field_name)]
            ids: list[int] = []
            for value in values:
                if not value:
                    continue
                if not value.isdigit():
                    raise ValueError("Script selection is invalid.")
                ids.append(int(value))
            script_ids_by_type[script_type] = ids
    except ValueError as exc:
        return {}, [], str(exc)

    legacy_values = [value.strip() for value in request.form.getlist("script_ids")]
    legacy_ids: list[int] = []
    for value in legacy_values:
        if not value:
            continue
        if not value.isdigit():
            return {}, [], "Script selection is invalid."
        legacy_ids.append(int(value))

    return script_ids_by_type, legacy_ids, None


def _resolve_script_selection(
    session,
    script_ids_by_type: dict[str, list[int]],
    legacy_ids: list[int],
) -> tuple[dict[str, list[int]], str | None]:
    has_typed_selection = any(script_ids_by_type.values())
    all_ids: list[int] = []
    if has_typed_selection:
        for ids in script_ids_by_type.values():
            all_ids.extend(ids)
    else:
        all_ids = legacy_ids

    if not all_ids:
        return {script_type: [] for script_type in SCRIPT_TYPE_FIELDS}, None

    if len(all_ids) != len(set(all_ids)):
        return {}, "Duplicate scripts are not allowed."

    scripts = (
        session.execute(select(Script).where(Script.id.in_(all_ids)))
        .scalars()
        .all()
    )
    scripts_by_id = {script.id: script for script in scripts}
    if len(scripts_by_id) != len(set(all_ids)):
        return {}, "One or more scripts were not found."

    if not has_typed_selection:
        grouped = {script_type: [] for script_type in SCRIPT_TYPE_FIELDS}
        for script_id in all_ids:
            script = scripts_by_id[script_id]
            grouped.setdefault(script.script_type, []).append(script_id)
        return grouped, None

    for script_type, ids in script_ids_by_type.items():
        for script_id in ids:
            script = scripts_by_id[script_id]
            if script.script_type != script_type:
                return {}, "Script selection is invalid."

    return script_ids_by_type, None


def _set_agent_scripts(
    session,
    agent_id: int,
    script_ids_by_type: dict[str, list[int]],
) -> None:
    session.execute(
        delete(agent_scripts).where(agent_scripts.c.agent_id == agent_id)
    )
    rows: list[dict[str, int]] = []
    for ids in script_ids_by_type.values():
        for position, script_id in enumerate(ids, start=1):
            rows.append(
                {
                    "agent_id": agent_id,
                    "script_id": script_id,
                    "position": position,
                }
            )
    if rows:
        session.execute(agent_scripts.insert(), rows)


def _set_task_scripts(
    session,
    task_id: int,
    script_ids_by_type: dict[str, list[int]],
) -> None:
    session.execute(
        delete(agent_task_scripts).where(
            agent_task_scripts.c.agent_task_id == task_id
        )
    )
    rows: list[dict[str, int]] = []
    for ids in script_ids_by_type.values():
        for position, script_id in enumerate(ids, start=1):
            rows.append(
                {
                    "agent_task_id": task_id,
                    "script_id": script_id,
                    "position": position,
                }
            )
    if rows:
        session.execute(agent_task_scripts.insert(), rows)


def _read_script_content(script: Script) -> str:
    file_contents = read_script_file(script.file_path)
    if file_contents:
        return file_contents
    return script.content or ""


def _human_time(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _parse_milestone_due_date(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.endswith("Z"):
        cleaned = f"{cleaned[:-1]}+00:00"
    try:
        if "T" in cleaned:
            parsed = datetime.fromisoformat(cleaned)
        else:
            parsed = datetime.fromisoformat(f"{cleaned}T00:00:00")
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _format_bytes(value: int | None) -> str:
    if value is None:
        return "-"
    if value < 1024:
        return f"{value} B"
    size = float(value)
    for unit in ("KB", "MB", "GB", "TB"):
        size /= 1024
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
    return f"{size:.1f} TB"


_STAGE_STATUS_CLASSES = {
    "pending": "status-queued",
    "running": "status-running",
    "completed": "status-success",
    "failed": "status-failed",
    "skipped": "status-idle",
}


def _parse_stage_logs(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items() if value is not None}


def _build_stage_status_map(
    task_status: str | None,
    current_stage: str | None,
) -> dict[str, str]:
    stage_keys = [stage_key for stage_key, _ in TASK_STAGE_ORDER]
    index_map = {stage_key: index for index, stage_key in enumerate(stage_keys)}
    statuses = {stage_key: "pending" for stage_key in stage_keys}
    if not task_status:
        return statuses
    if task_status == "succeeded":
        return {stage_key: "completed" for stage_key in stage_keys}
    if task_status == "running":
        if current_stage in index_map:
            current_index = index_map[current_stage]
            for stage_key, index in index_map.items():
                if index < current_index:
                    statuses[stage_key] = "completed"
                elif index == current_index:
                    statuses[stage_key] = "running"
        return statuses
    if task_status == "failed":
        if current_stage in index_map:
            current_index = index_map[current_stage]
            for stage_key, index in index_map.items():
                if index < current_index:
                    statuses[stage_key] = "completed"
                elif index == current_index:
                    statuses[stage_key] = "failed"
                else:
                    statuses[stage_key] = "skipped"
        return statuses
    if task_status in {"canceled", "stopped"}:
        if current_stage in index_map:
            current_index = index_map[current_stage]
            for stage_key, index in index_map.items():
                if index < current_index:
                    statuses[stage_key] = "completed"
                else:
                    statuses[stage_key] = "skipped"
        else:
            statuses = {stage_key: "skipped" for stage_key in stage_keys}
        return statuses
    return statuses


def _build_stage_entries(task: AgentTask) -> list[dict[str, str]]:
    stage_logs = _parse_stage_logs(task.stage_logs)
    status_map = _build_stage_status_map(task.status, task.current_stage)
    entries: list[dict[str, str]] = []
    for stage_key, label in TASK_STAGE_ORDER:
        status = status_map.get(stage_key, "pending")
        entries.append(
            {
                "key": stage_key,
                "label": label,
                "status": status,
                "status_label": status.replace("_", " "),
                "status_class": _STAGE_STATUS_CLASSES.get(status, "status-idle"),
                "logs": stage_logs.get(stage_key, ""),
            }
        )
    return entries


def _script_type_label(value: str | None) -> str:
    if not value:
        return "-"
    return SCRIPT_TYPE_LABELS.get(value, value)


def _safe_redirect_target(target: str | None, fallback: str) -> str:
    if not target:
        return fallback
    if target.startswith("/") and "://" not in target and "\\\\" not in target:
        return target
    return fallback


def _parse_positive_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed < 1:
        return default
    return parsed


def _parse_run_settings(run_mode: str, run_max_loops_raw: str) -> tuple[int | None, str | None]:
    if run_mode == "forever":
        return None, None
    if not run_max_loops_raw:
        return None, "Autorun limit is required unless running forever."
    try:
        run_max_loops = int(run_max_loops_raw)
    except ValueError:
        return None, "Autorun limit must be a number."
    if run_max_loops < 1:
        return None, "Autorun limit must be at least 1."
    return run_max_loops, None


@bp.app_context_processor
def _inject_template_helpers() -> dict[str, object]:
    return {
        "human_time": _human_time,
        "integration_overview": _integration_overview(),
        "task_kind_label": task_kind_label,
        "script_type_label": _script_type_label,
    }


def _load_agents() -> list[Agent]:
    with session_scope() as session:
        agents = (
            session.execute(
                select(Agent)
                .options(selectinload(Agent.mcp_servers))
                .order_by(Agent.created_at.desc())
            )
            .scalars()
            .all()
        )
    return agents


def _load_quick_agent_id(agents: list[Agent]) -> int | None:
    for agent in agents:
        if agent.name == QUICK_AGENT_NAME:
            return agent.id
    return None


def _load_runs(limit: int | None = None) -> list[Run]:
    with session_scope() as session:
        stmt = select(Run).options(selectinload(Run.agent)).order_by(
            Run.created_at.desc()
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        return session.execute(stmt).scalars().all()


def _load_runs_page(page: int, per_page: int) -> tuple[list[Run], int, int, int]:
    with session_scope() as session:
        total_runs = session.execute(select(func.count(Run.id))).scalar_one()
        total_pages = (
            max(1, (total_runs + per_page - 1) // per_page) if total_runs else 1
        )
        page = max(1, min(page, total_pages))
        runs: list[Run] = []
        if total_runs:
            stmt = (
                select(Run)
                .options(selectinload(Run.agent))
                .order_by(Run.created_at.desc())
                .limit(per_page)
                .offset((page - 1) * per_page)
            )
            runs = session.execute(stmt).scalars().all()
        return runs, total_runs, page, total_pages


def _active_agent_ids(agent_ids: list[int]) -> set[int]:
    if not agent_ids:
        return set()
    with session_scope() as session:
        rows = (
            session.execute(
                select(Run.agent_id)
                .where(
                    Run.agent_id.in_(agent_ids),
                    Run.status.in_(RUN_ACTIVE_STATUSES),
                )
                .distinct()
            )
            .scalars()
            .all()
        )
    return set(rows)


def _agent_status_by_id(agent_ids: list[int]) -> dict[int, str]:
    if not agent_ids:
        return {}
    status_by_id: dict[int, str] = {}
    with session_scope() as session:
        active_rows = session.execute(
            select(Run.agent_id, Run.status, Run.updated_at)
            .where(
                Run.agent_id.in_(agent_ids),
                Run.status.in_(RUN_ACTIVE_STATUSES),
            )
            .order_by(Run.updated_at.desc())
        ).all()
        for row in active_rows:
            agent_id = row[0]
            if agent_id not in status_by_id:
                status_by_id[agent_id] = row[1]

        latest_runs = (
            select(Run.agent_id, func.max(Run.updated_at).label("latest_updated"))
            .where(Run.agent_id.in_(agent_ids))
            .group_by(Run.agent_id)
            .subquery()
        )
        rows = session.execute(
            select(Run.agent_id, Run.status).join(
                latest_runs,
                (Run.agent_id == latest_runs.c.agent_id)
                & (Run.updated_at == latest_runs.c.latest_updated),
            )
        ).all()
        for row in rows:
            status_by_id.setdefault(row[0], row[1])
    return status_by_id


def _load_default_agent() -> Agent | None:
    with session_scope() as session:
        return (
            session.execute(select(Agent).order_by(Agent.created_at.desc()).limit(1))
            .scalars()
            .first()
        )


def _agent_rollup(agents: list[Agent]) -> tuple[list[Agent], dict[str, object]]:
    agent_ids = [agent.id for agent in agents]
    active_ids = _active_agent_ids(agent_ids)
    active_agents = [agent for agent in agents if agent.id in active_ids]
    error_agents = [agent for agent in agents if agent.last_error]
    last_run_at = max(
        (agent.last_run_at for agent in agents if agent.last_run_at),
        default=None,
    )
    summary = {
        "total": len(agents),
        "active": len(active_agents),
        "errors": len(error_agents),
        "last_run_at": last_run_at,
    }
    return active_agents, summary


def _settings_summary() -> dict[str, object]:
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    return summary


def _provider_command(provider: str | None) -> str:
    if provider == "codex":
        return f"{Config.CODEX_CMD} exec"
    if provider == "gemini":
        return Config.GEMINI_CMD
    if provider == "claude":
        return f"{Config.CLAUDE_CMD} --print"
    return "-"


def _provider_model(provider: str | None, settings: dict[str, str] | None = None) -> str:
    if provider == "codex":
        settings = settings or _load_integration_settings("llm")
        model = (settings.get("codex_model") or "").strip()
        return model or Config.CODEX_MODEL or _codex_default_model()
    if provider == "gemini":
        return Config.GEMINI_MODEL or "default"
    if provider == "claude":
        return Config.CLAUDE_MODEL or "default"
    return "default"


def _provider_summary(
    provider: str | None = None,
    *,
    settings: dict[str, str] | None = None,
    enabled_providers: set[str] | None = None,
) -> dict[str, str | None]:
    settings = settings or _load_integration_settings("llm")
    enabled = enabled_providers or resolve_enabled_llm_providers(settings)
    selected = provider or resolve_llm_provider(
        settings=settings, enabled_providers=enabled
    )
    label = LLM_PROVIDER_LABELS.get(selected, selected) if selected else "not set"
    return {
        "provider": selected,
        "label": label,
        "command": _provider_command(selected),
        "model": _provider_model(selected, settings),
    }


def _provider_options() -> list[dict[str, str]]:
    return [
        {"value": key, "label": LLM_PROVIDER_LABELS.get(key, key)}
        for key in LLM_PROVIDERS
    ]


def _as_bool(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def _default_model_overview(
    settings: dict[str, str] | None = None,
) -> dict[str, object]:
    settings = settings or _load_integration_settings("llm")
    default_model_id = resolve_default_model_id(settings)
    if default_model_id is None:
        return {
            "id": None,
            "label": "not set",
            "provider_label": None,
            "model_name": None,
            "name": None,
        }
    with session_scope() as session:
        model = session.get(LLMModel, default_model_id)
        if model is None:
            return {
                "id": default_model_id,
                "label": "missing",
                "provider_label": None,
                "model_name": None,
                "name": None,
            }
        model_name = _model_display_name(model)
        provider_label = LLM_PROVIDER_LABELS.get(model.provider, model.provider)
        label = f"{model.name} ({provider_label} / {model_name})"
        return {
            "id": model.id,
            "label": label,
            "provider_label": provider_label,
            "model_name": model_name,
            "name": model.name,
        }


def _decode_model_config(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _codex_model_config_defaults(
    config: dict[str, object],
    *,
    default_model: str | None = None,
) -> dict[str, object]:
    model = str(config.get("model") or "").strip()
    if not model:
        model = default_model or _codex_default_model()
    return {
        "model": model,
        "approval_policy": config.get("approval_policy") or "never",
        "sandbox_mode": config.get("sandbox_mode") or "danger-full-access",
        "network_access": config.get("network_access") or "enabled",
        "model_reasoning_effort": config.get("model_reasoning_effort") or "high",
        "shell_env_inherit": config.get("shell_env_inherit") or "all",
        "shell_env_ignore_default_excludes": _as_bool(
            str(config.get("shell_env_ignore_default_excludes"))
            if config.get("shell_env_ignore_default_excludes") is not None
            else ""
        ),
        "notice_hide_key": config.get("notice_hide_key") or "",
        "notice_hide_enabled": _as_bool(
            str(config.get("notice_hide_enabled"))
            if config.get("notice_hide_enabled") is not None
            else ""
        ),
        "notice_migration_from": config.get("notice_migration_from") or "",
        "notice_migration_to": config.get("notice_migration_to") or "",
    }


def _normalize_optional_bool(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "false"}:
            return normalized
    return ""


def _normalize_args_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [str(item).strip() for item in value]
        return "\n".join(part for part in parts if part)
    return str(value)


def _gemini_model_config_defaults(config: dict[str, object]) -> dict[str, object]:
    return {
        "model": config.get("model") or "",
        "approval_mode": config.get("approval_mode") or "",
        "sandbox": _normalize_optional_bool(config.get("sandbox")),
        "extra_args": _normalize_args_text(config.get("extra_args")),
    }


def _simple_model_config_defaults(config: dict[str, object]) -> dict[str, object]:
    return {"model": config.get("model") or ""}


def _parse_model_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = []
    for chunk in raw.replace(",", "\n").splitlines():
        value = chunk.strip()
        if value:
            parts.append(value)
    return parts


def _codex_default_model(options: list[str] | None = None) -> str:
    if options:
        for model in CODEX_MODEL_PREFERENCE:
            if model in options:
                return model
        return options[0]
    return CODEX_MODEL_PREFERENCE[0]


def _ordered_codex_models(options: set[str]) -> list[str]:
    ordered = []
    seen = set()
    for model in CODEX_MODEL_PREFERENCE:
        if model in options:
            ordered.append(model)
            seen.add(model)
    remainder = sorted([model for model in options if model not in seen], key=str.lower)
    ordered.extend(remainder)
    return ordered


def _ordered_gemini_models(options: set[str]) -> list[str]:
    ordered = []
    seen = set()
    for model in GEMINI_MODEL_OPTIONS:
        if model in options:
            ordered.append(model)
            seen.add(model)
    remainder = sorted([model for model in options if model not in seen], key=str.lower)
    ordered.extend(remainder)
    return ordered


def _provider_default_model(provider: str) -> str:
    if provider == "codex":
        return Config.CODEX_MODEL or _codex_default_model()
    if provider == "gemini":
        return Config.GEMINI_MODEL or ""
    if provider == "claude":
        return Config.CLAUDE_MODEL or ""
    return ""


def _provider_model_options(
    settings: dict[str, str] | None = None,
    models: list[LLMModel] | None = None,
) -> dict[str, list[str]]:
    settings = settings or _load_integration_settings("llm")
    models = models or _load_llm_models()
    options: dict[str, set[str]] = {provider: set() for provider in LLM_PROVIDERS}
    if "codex" in options:
        options["codex"].update(CODEX_MODEL_PREFERENCE)
    if "gemini" in options:
        options["gemini"].update(GEMINI_MODEL_OPTIONS)
    for provider in LLM_PROVIDERS:
        options[provider].update(
            _parse_model_list(settings.get(f"{provider}_models"))
        )
        settings_model = (settings.get(f"{provider}_model") or "").strip()
        if settings_model:
            options[provider].add(settings_model)
        default_model = _provider_default_model(provider)
        if default_model:
            options[provider].add(default_model.strip())
    for model in models:
        if model.provider not in options:
            continue
        config = _decode_model_config(model.config_json)
        model_name = str(config.get("model") or "").strip()
        if model_name:
            options[model.provider].add(model_name)
    ordered: dict[str, list[str]] = {}
    for provider, values in options.items():
        if provider == "codex":
            ordered[provider] = _ordered_codex_models(values)
        elif provider == "gemini":
            ordered[provider] = _ordered_gemini_models(values)
        else:
            ordered[provider] = sorted(values, key=str.lower)
    return ordered


def _model_option_allowed(
    provider: str,
    model_name: str,
    model_options: dict[str, list[str]],
) -> bool:
    if not model_name:
        return True
    return model_name in model_options.get(provider, [])


def _model_config_payload(provider: str, form: dict[str, str]) -> dict[str, object]:
    if provider == "codex":
        return {
            "model": form.get("codex_model", "").strip(),
            "approval_policy": form.get("codex_approval_policy", "").strip(),
            "sandbox_mode": form.get("codex_sandbox_mode", "").strip(),
            "network_access": form.get("codex_network_access", "").strip(),
            "model_reasoning_effort": form.get("codex_model_reasoning_effort", "").strip(),
            "shell_env_inherit": form.get("codex_shell_env_inherit", "").strip(),
            "shell_env_ignore_default_excludes": (
                form.get("codex_shell_env_ignore_default_excludes", "")
                .strip()
                .lower()
                == "true"
            ),
            "notice_hide_key": form.get("codex_notice_hide_key", "").strip(),
            "notice_hide_enabled": (
                form.get("codex_notice_hide_enabled", "").strip().lower() == "true"
            ),
            "notice_migration_from": form.get("codex_notice_migration_from", "").strip(),
            "notice_migration_to": form.get("codex_notice_migration_to", "").strip(),
        }
    if provider == "gemini":
        sandbox_raw = form.get("gemini_sandbox", "").strip().lower()
        sandbox_value = None
        if sandbox_raw == "true":
            sandbox_value = True
        elif sandbox_raw == "false":
            sandbox_value = False
        return {
            "model": form.get("gemini_model", "").strip(),
            "approval_mode": form.get("gemini_approval_mode", "").strip(),
            "sandbox": sandbox_value,
            "extra_args": form.get("gemini_extra_args", "").strip(),
        }
    if provider == "claude":
        return {"model": form.get("claude_model", "").strip()}
    return {}


def _load_llm_models() -> list[LLMModel]:
    with session_scope() as session:
        return (
            session.execute(select(LLMModel).order_by(LLMModel.created_at.desc()))
            .scalars()
            .all()
        )


def _model_display_name(model: LLMModel) -> str:
    config = _decode_model_config(model.config_json)
    model_name = str(config.get("model") or "").strip()
    return model_name or "default"


def _codex_settings_payload(settings: dict[str, str]) -> dict[str, object]:
    return {
        "api_key": settings.get("codex_api_key") or "",
    }


def _gemini_settings_payload(settings: dict[str, str]) -> dict[str, object]:
    return {
        "api_key": settings.get("gemini_api_key") or "",
    }


def _claude_settings_payload(settings: dict[str, str]) -> dict[str, object]:
    return {
        "api_key": settings.get("claude_api_key") or "",
    }


def _gitconfig_path() -> Path:
    return Path.home() / ".gitconfig"


def _parse_link_header(header: str) -> str | None:
    if not header:
        return None
    for chunk in header.split(","):
        parts = [part.strip() for part in chunk.split(";")]
        if len(parts) < 2:
            continue
        if parts[1] == 'rel="next"':
            url_part = parts[0]
            if url_part.startswith("<") and url_part.endswith(">"):
                return url_part[1:-1]
    return None


def _parse_github_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_github_timestamp(value: str | None) -> str:
    parsed = _parse_github_datetime(value)
    if parsed is None:
        return value or "-"
    return _human_time(parsed)


def _github_status_badge(
    state: str | None, is_draft: bool, merged_at: str | None
) -> tuple[str, str]:
    if merged_at:
        return "merged", "status-merged"
    if is_draft:
        return "draft", "status-draft"
    if state == "open":
        return "open", "status-open"
    return "closed", "status-idle"


def _format_jira_timestamp(value: str | None) -> str:
    parsed = _parse_github_datetime(value)
    if parsed is None:
        return value or "-"
    return _human_time(parsed)


def _jira_status_badge(status: dict | None) -> tuple[str, str]:
    if not isinstance(status, dict):
        return "unknown", "status-idle"
    name = status.get("name") or "unknown"
    category = status.get("statusCategory")
    category_key = ""
    if isinstance(category, dict):
        category_key = category.get("key") or ""
    if category_key == "done":
        return name, "status-success"
    if category_key == "indeterminate":
        return name, "status-running"
    if category_key == "new":
        return name, "status-open"
    return name, "status-idle"


def _jira_avatar_url(user: dict | None) -> str:
    if not isinstance(user, dict):
        return ""
    avatars = user.get("avatarUrls")
    if not isinstance(avatars, dict):
        return ""
    for key in ("48x48", "32x32", "24x24", "16x16"):
        value = avatars.get(key)
        if isinstance(value, str) and value:
            return value
    for value in avatars.values():
        if isinstance(value, str) and value:
            return value
    return ""


def _user_initial(name: str | None) -> str:
    if not isinstance(name, str):
        return "?"
    stripped = name.strip()
    if not stripped:
        return "?"
    return stripped[:1].upper()


def _adf_to_text(node: object) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_adf_to_text(item) for item in node)
    if not isinstance(node, dict):
        return ""
    node_type = node.get("type")
    content = node.get("content")
    if node_type == "text":
        return node.get("text", "")
    if node_type == "hardBreak":
        return "\n"
    if node_type in {"paragraph", "heading", "blockquote"}:
        text = _adf_to_text(content)
        if text:
            return f"{text.strip()}\n"
        return ""
    if node_type == "codeBlock":
        text = _adf_to_text(content)
        if text:
            return f"{text.rstrip()}\n"
        return ""
    if node_type in {"bulletList", "orderedList"}:
        items: list[str] = []
        index = 1
        if isinstance(content, list):
            for child in content:
                if not isinstance(child, dict) or child.get("type") != "listItem":
                    continue
                item_text = _adf_to_text(child.get("content"))
                item_text = " ".join(item_text.splitlines()).strip()
                prefix = "- " if node_type == "bulletList" else f"{index}. "
                items.append(prefix + item_text if item_text else prefix.strip())
                index += 1
        return "\n".join(items) + ("\n" if items else "")
    if node_type == "listItem":
        return _adf_to_text(content)
    if content:
        return _adf_to_text(content)
    return ""


def _normalize_adf_text(value: object) -> str:
    text = _adf_to_text(value)
    if not text:
        return ""
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(lines).strip()


def _label_style(color: str) -> str:
    cleaned = color.strip().lstrip("#")
    if len(cleaned) != 6:
        return (
            "background: rgba(148, 163, 184, 0.18); "
            "border-color: rgba(148, 163, 184, 0.4); "
            "color: #e2e8f0;"
        )
    try:
        red = int(cleaned[0:2], 16)
        green = int(cleaned[2:4], 16)
        blue = int(cleaned[4:6], 16)
    except ValueError:
        return (
            "background: rgba(148, 163, 184, 0.18); "
            "border-color: rgba(148, 163, 184, 0.4); "
            "color: #e2e8f0;"
        )
    luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255
    text_color = "#0b0f14" if luminance > 0.7 else "#f8fafc"
    return (
        f"background: rgba({red}, {green}, {blue}, 0.18); "
        f"border-color: rgba({red}, {green}, {blue}, 0.45); "
        f"color: {text_color};"
    )


def _normalize_github_labels(labels: object) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    if not isinstance(labels, list):
        return normalized
    for item in labels:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or ""
        if not name:
            continue
        color = item.get("color") or ""
        normalized.append({"name": name, "style": _label_style(color)})
    return normalized


def _extract_user_logins(items: object) -> list[str]:
    if not isinstance(items, list):
        return []
    logins = {
        item.get("login")
        for item in items
        if isinstance(item, dict) and item.get("login")
    }
    return sorted(logins)


def _fetch_github_repos(pat: str) -> list[str]:
    repos: list[str] = []
    if not pat:
        return repos
    url = "https://api.github.com/user/repos?per_page=100&sort=updated"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {pat}",
        "User-Agent": "llmctl-studio",
    }
    while url:
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.load(response)
                repos.extend(
                    item["full_name"]
                    for item in payload
                    if isinstance(item, dict) and "full_name" in item
                )
                url = _parse_link_header(response.headers.get("Link", ""))
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise ValueError("GitHub PAT is invalid or lacks repo access.") from exc
            raise ValueError("GitHub API error while fetching repositories.") from exc
        except URLError as exc:
            raise ValueError("Unable to reach GitHub API.") from exc
    return sorted(set(repos))


def _normalize_atlassian_site(site: str) -> str:
    cleaned = (site or "").strip()
    if not cleaned:
        return ""
    if not cleaned.startswith(("http://", "https://")):
        cleaned = f"https://{cleaned}"
    return cleaned.rstrip("/")


def _safe_site_label(site: str) -> str:
    cleaned = (site or "").strip()
    if not cleaned:
        return ""
    if not cleaned.startswith(("http://", "https://")):
        cleaned = f"https://{cleaned}"
    parsed = urlparse(cleaned)
    host = parsed.netloc or parsed.path
    return host.split("/")[0]


def _safe_email_domain(email: str) -> str:
    cleaned = (email or "").strip()
    if "@" not in cleaned:
        return ""
    return cleaned.split("@", 1)[1]


def _error_body_snippet(exc: HTTPError) -> str:
    try:
        body = exc.read()
    except Exception:
        return ""
    if isinstance(body, bytes):
        text = body.decode("utf-8", "ignore")
    else:
        text = str(body)
    return text.replace("\n", " ")[:300]


def _combine_atlassian_key(api_key: str, username: str) -> str:
    cleaned_key = (api_key or "").strip()
    if not cleaned_key:
        return ""
    if ":" in cleaned_key:
        return cleaned_key
    cleaned_user = (username or "").strip()
    if not cleaned_user:
        return cleaned_key
    return f"{cleaned_user}:{cleaned_key}"


def _build_atlassian_headers(api_key: str) -> dict[str, str]:
    cleaned = (api_key or "").strip()
    if not cleaned:
        return {}
    headers = {
        "Accept": "application/json",
        "User-Agent": "llmctl-studio",
    }
    if ":" in cleaned:
        logger.info("Atlassian auth: using basic key_len=%s", len(cleaned))
        encoded = base64.b64encode(cleaned.encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {encoded}"
    else:
        logger.info("Atlassian auth: using bearer key_len=%s", len(cleaned))
        headers["Authorization"] = f"Bearer {cleaned}"
    return headers


def _jira_board_url(
    base: str, start_at: int, max_results: int, project_key: str | None = None
) -> str:
    params: dict[str, str | int] = {
        "startAt": start_at,
        "maxResults": max_results,
    }
    cleaned_project = (project_key or "").strip()
    if cleaned_project:
        params["projectKeyOrId"] = cleaned_project
    return f"{base}/rest/agile/1.0/board?{urlencode(params)}"


def _fetch_jira_boards(
    api_key: str, site: str, project_key: str | None = None
) -> list[dict[str, str]]:
    boards: list[dict[str, str]] = []
    if not api_key or not site:
        return boards
    base = _normalize_atlassian_site(site)
    if not base:
        return boards
    cleaned_project = (project_key or "").strip()
    auth_mode = "basic" if ":" in api_key else "bearer"
    logger.info(
        "Jira refresh: requesting boards auth=%s site=%s project=%s",
        auth_mode,
        _safe_site_label(base),
        cleaned_project or "any",
    )
    headers = _build_atlassian_headers(api_key)
    url = _jira_board_url(base, 0, 50, cleaned_project)
    seen: set[str] = set()
    while url:
        logger.info("Jira refresh: request url=%s", url)
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                status_code = getattr(response, "status", None)
                logger.info("Jira refresh: response status=%s", status_code)
                payload = json.load(response)
                values = payload.get("values")
                page_count = len(values) if isinstance(values, list) else 0
                logger.info(
                    "Jira refresh: page items=%s isLast=%s",
                    page_count,
                    payload.get("isLast"),
                )
                if isinstance(values, list):
                    for item in values:
                        if not isinstance(item, dict):
                            continue
                        name = item.get("name")
                        if not isinstance(name, str):
                            continue
                        value = name.strip()
                        if not value or value in seen:
                            continue
                        boards.append({"value": value, "label": value})
                        seen.add(value)
                is_last = payload.get("isLast")
                if isinstance(is_last, bool) and is_last:
                    url = None
                    continue
                start_at = payload.get("startAt")
                max_results = payload.get("maxResults")
                total = payload.get("total")
                if (
                    isinstance(start_at, int)
                    and isinstance(max_results, int)
                    and isinstance(total, int)
                ):
                    if start_at + max_results >= total:
                        url = None
                    else:
                        url = _jira_board_url(
                            base, start_at + max_results, max_results, cleaned_project
                        )
                else:
                    url = None
        except HTTPError as exc:
            body_snippet = _error_body_snippet(exc)
            logger.warning(
                "Jira refresh: HTTP error code=%s url=%s body=%s",
                exc.code,
                url,
                body_snippet,
            )
            if exc.code in {401, 403}:
                raise ValueError(
                    "Jira API key is invalid or lacks board access."
                ) from exc
            if exc.code == 404:
                raise ValueError("Jira site URL not found.") from exc
            raise ValueError("Jira API error while fetching boards.") from exc
        except URLError as exc:
            logger.warning("Jira refresh: network error url=%s", url)
            raise ValueError("Unable to reach Jira API.") from exc
    logger.info("Jira refresh: loaded %s boards", len(boards))
    boards.sort(key=lambda item: item["label"].lower())
    return boards


def _fetch_jira_projects(api_key: str, site: str) -> list[dict[str, str]]:
    projects: list[dict[str, str]] = []
    if not api_key or not site:
        return projects
    base = _normalize_atlassian_site(site)
    if not base:
        return projects
    auth_mode = "basic" if ":" in api_key else "bearer"
    logger.info(
        "Jira refresh: requesting projects auth=%s site=%s",
        auth_mode,
        _safe_site_label(base),
    )
    headers = _build_atlassian_headers(api_key)
    url = f"{base}/rest/api/3/project/search?startAt=0&maxResults=50"
    seen: set[str] = set()
    while url:
        logger.info("Jira refresh: request url=%s", url)
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                status_code = getattr(response, "status", None)
                logger.info("Jira refresh: response status=%s", status_code)
                payload = json.load(response)
                values = payload.get("values")
                page_count = len(values) if isinstance(values, list) else 0
                logger.info(
                    "Jira refresh: project page items=%s isLast=%s",
                    page_count,
                    payload.get("isLast"),
                )
                if isinstance(values, list):
                    for item in values:
                        if not isinstance(item, dict):
                            continue
                        key = item.get("key") or ""
                        name = item.get("name") or ""
                        key = key.strip() if isinstance(key, str) else ""
                        name = name.strip() if isinstance(name, str) else ""
                        value = key or name
                        if not value or value in seen:
                            continue
                        label = value
                        if key and name and key != name:
                            label = f"{key} - {name}"
                        projects.append({"value": value, "label": label})
                        seen.add(value)
                is_last = payload.get("isLast")
                if isinstance(is_last, bool) and is_last:
                    url = None
                    continue
                start_at = payload.get("startAt")
                max_results = payload.get("maxResults")
                total = payload.get("total")
                if (
                    isinstance(start_at, int)
                    and isinstance(max_results, int)
                    and isinstance(total, int)
                ):
                    if start_at + max_results >= total:
                        url = None
                    else:
                        url = (
                            f"{base}/rest/api/3/project/search?startAt="
                            f"{start_at + max_results}&maxResults={max_results}"
                        )
                else:
                    url = None
        except HTTPError as exc:
            body_snippet = _error_body_snippet(exc)
            logger.warning(
                "Jira refresh: HTTP error code=%s url=%s body=%s",
                exc.code,
                url,
                body_snippet,
            )
            if exc.code in {401, 403}:
                raise ValueError(
                    "Jira API key is invalid or lacks project access."
                ) from exc
            if exc.code == 404:
                raise ValueError("Jira site URL not found.") from exc
            raise ValueError("Jira API error while fetching projects.") from exc
        except URLError as exc:
            logger.warning("Jira refresh: network error url=%s", url)
            raise ValueError("Unable to reach Jira API.") from exc
    logger.info("Jira refresh: loaded %s projects", len(projects))
    projects.sort(key=lambda item: item["label"].lower())
    return projects


def _fetch_jira_board_by_name(
    api_key: str, site: str, board_name: str
) -> dict[str, object] | None:
    if not api_key or not site:
        return None
    target = (board_name or "").strip()
    if not target:
        return None
    base = _normalize_atlassian_site(site)
    if not base:
        return None
    headers = _build_atlassian_headers(api_key)
    url = (
        f"{base}/rest/agile/1.0/board?"
        f"{urlencode({'startAt': 0, 'maxResults': 50, 'name': target})}"
    )
    target_lower = target.lower()
    fallback_match: dict[str, object] | None = None
    while url:
        logger.info("Jira board lookup: request url=%s", url)
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.load(response)
                values = payload.get("values")
                if isinstance(values, list):
                    for item in values:
                        if not isinstance(item, dict):
                            continue
                        name = item.get("name")
                        if not isinstance(name, str):
                            continue
                        cleaned = name.strip()
                        if cleaned == target:
                            return item
                        if cleaned.lower() == target_lower and fallback_match is None:
                            fallback_match = item
                is_last = payload.get("isLast")
                if isinstance(is_last, bool) and is_last:
                    url = None
                    continue
                start_at = payload.get("startAt")
                max_results = payload.get("maxResults")
                total = payload.get("total")
                if (
                    isinstance(start_at, int)
                    and isinstance(max_results, int)
                    and isinstance(total, int)
                ):
                    if start_at + max_results >= total:
                        url = None
                    else:
                        url = (
                            f"{base}/rest/agile/1.0/board?startAt="
                            f"{start_at + max_results}&maxResults={max_results}"
                        )
                else:
                    url = None
        except HTTPError as exc:
            body_snippet = _error_body_snippet(exc)
            logger.warning(
                "Jira board lookup: HTTP error code=%s url=%s body=%s",
                exc.code,
                url,
                body_snippet,
            )
            if exc.code in {401, 403}:
                raise ValueError(
                    "Jira API key is invalid or lacks board access."
                ) from exc
            if exc.code == 404:
                raise ValueError("Jira site URL not found.") from exc
            raise ValueError("Jira API error while fetching board.") from exc
        except URLError as exc:
            logger.warning("Jira board lookup: network error url=%s", url)
            raise ValueError("Unable to reach Jira API.") from exc
    return fallback_match


def _fetch_jira_board_configuration(
    api_key: str, site: str, board_id: int
) -> dict[str, object]:
    if not api_key or not site or not board_id:
        return {}
    base = _normalize_atlassian_site(site)
    if not base:
        return {}
    headers = _build_atlassian_headers(api_key)
    url = f"{base}/rest/agile/1.0/board/{board_id}/configuration"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except HTTPError as exc:
        body_snippet = _error_body_snippet(exc)
        logger.warning(
            "Jira board config: HTTP error code=%s url=%s body=%s",
            exc.code,
            url,
            body_snippet,
        )
        if exc.code in {401, 403}:
            raise ValueError("Jira API key is invalid or lacks board access.") from exc
        if exc.code == 404:
            raise ValueError("Jira board configuration not found.") from exc
        raise ValueError("Jira API error while fetching board config.") from exc
    except URLError as exc:
        logger.warning("Jira board config: network error url=%s", url)
        raise ValueError("Unable to reach Jira API.") from exc
    if isinstance(payload, dict):
        return payload
    return {}


def _fetch_jira_board_issues(
    api_key: str, site: str, board_id: int
) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    if not api_key or not site or not board_id:
        return issues
    base = _normalize_atlassian_site(site)
    if not base:
        return issues
    headers = _build_atlassian_headers(api_key)
    start_at = 0
    max_results = 50
    total: int | None = None
    while True:
        query = urlencode(
            {
                "startAt": start_at,
                "maxResults": max_results,
                "fields": "summary,status,assignee,issuetype,priority",
            }
        )
        url = f"{base}/rest/agile/1.0/board/{board_id}/issue?{query}"
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.load(response)
        except HTTPError as exc:
            body_snippet = _error_body_snippet(exc)
            logger.warning(
                "Jira board issues: HTTP error code=%s url=%s body=%s",
                exc.code,
                url,
                body_snippet,
            )
            if exc.code in {401, 403}:
                raise ValueError("Jira API key is invalid or lacks board access.") from exc
            if exc.code == 404:
                raise ValueError("Jira board issues not found.") from exc
            raise ValueError("Jira API error while fetching board issues.") from exc
        except URLError as exc:
            logger.warning("Jira board issues: network error url=%s", url)
            raise ValueError("Unable to reach Jira API.") from exc
        if not isinstance(payload, dict):
            break
        values = payload.get("issues")
        if isinstance(values, list):
            for item in values:
                if not isinstance(item, dict):
                    continue
                fields = item.get("fields", {})
                if not isinstance(fields, dict):
                    fields = {}
                status = fields.get("status", {})
                if not isinstance(status, dict):
                    status = {}
                status_category = status.get("statusCategory", {})
                if not isinstance(status_category, dict):
                    status_category = {}
                assignee = fields.get("assignee", {})
                if not isinstance(assignee, dict):
                    assignee = {}
                issue_type = fields.get("issuetype", {})
                if not isinstance(issue_type, dict):
                    issue_type = {}
                priority = fields.get("priority", {})
                if not isinstance(priority, dict):
                    priority = {}
                key = item.get("key") or ""
                issues.append(
                    {
                        "key": key,
                        "summary": fields.get("summary") or "Untitled issue",
                        "status": status.get("name") or "",
                        "status_id": status.get("id") or "",
                        "status_category": status_category.get("key") or "",
                        "assignee": assignee.get("displayName") or "",
                        "issue_type": issue_type.get("name") or "",
                        "priority": priority.get("name") or "",
                        "url": f"{base}/browse/{key}" if key else "",
                    }
                )
        total_value = payload.get("total")
        if isinstance(total_value, int):
            total = total_value
        if total is None:
            break
        start_at += max_results
        if start_at >= total:
            break
    return issues


def _build_jira_board_columns(
    board_config: dict[str, object], issues: list[dict[str, object]]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    columns: list[dict[str, object]] = []
    unmapped: list[dict[str, object]] = []
    column_config = board_config.get("columnConfig", {})
    if not isinstance(column_config, dict):
        column_config = {}
    column_defs = column_config.get("columns", [])
    if not isinstance(column_defs, list):
        column_defs = []
    status_id_map: dict[str, int] = {}
    status_name_map: dict[str, int] = {}
    for column in column_defs:
        if not isinstance(column, dict):
            continue
        name = column.get("name") or "Untitled"
        statuses = column.get("statuses", [])
        status_ids: list[str] = []
        status_names: list[str] = []
        if isinstance(statuses, list):
            for status in statuses:
                if not isinstance(status, dict):
                    continue
                status_id = status.get("id")
                status_name = status.get("name")
                if isinstance(status_id, str) and status_id:
                    status_ids.append(status_id)
                if isinstance(status_name, str) and status_name:
                    status_names.append(status_name)
        index = len(columns)
        for status_id in status_ids:
            status_id_map.setdefault(status_id, index)
        for status_name in status_names:
            status_name_map.setdefault(status_name.lower(), index)
        columns.append(
            {
                "name": name,
                "status_ids": status_ids,
                "status_names": status_names,
                "issues": [],
            }
        )
    for issue in issues:
        status_id = issue.get("status_id")
        status_name = issue.get("status")
        index = None
        if isinstance(status_id, str) and status_id in status_id_map:
            index = status_id_map[status_id]
        elif isinstance(status_name, str):
            index = status_name_map.get(status_name.lower())
        if index is None or index >= len(columns):
            unmapped.append(issue)
        else:
            columns[index]["issues"].append(issue)
    return columns, unmapped


def _fetch_jira_issue(
    api_key: str, site: str, issue_key: str
) -> dict[str, object]:
    if not api_key or not site or not issue_key:
        return {}
    base = _normalize_atlassian_site(site)
    if not base:
        return {}
    headers = _build_atlassian_headers(api_key)
    fields = ",".join(
        [
            "summary",
            "description",
            "status",
            "assignee",
            "reporter",
            "priority",
            "issuetype",
            "labels",
            "created",
            "updated",
            "components",
            "fixVersions",
            "project",
            "parent",
            "subtasks",
        ]
    )
    query = urlencode({"fields": fields})
    url = f"{base}/rest/api/3/issue/{quote(issue_key)}?{query}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except HTTPError as exc:
        body_snippet = _error_body_snippet(exc)
        logger.warning(
            "Jira issue: HTTP error code=%s url=%s body=%s",
            exc.code,
            url,
            body_snippet,
        )
        if exc.code in {401, 403}:
            raise ValueError("Jira API key is invalid or lacks issue access.") from exc
        if exc.code == 404:
            raise ValueError("Jira issue not found.") from exc
        raise ValueError("Jira API error while fetching issue.") from exc
    except URLError as exc:
        logger.warning("Jira issue: network error url=%s", url)
        raise ValueError("Unable to reach Jira API.") from exc
    if not isinstance(payload, dict):
        return {}
    fields_payload = payload.get("fields", {})
    if not isinstance(fields_payload, dict):
        fields_payload = {}
    status_payload = fields_payload.get("status")
    status_label, status_class = _jira_status_badge(
        status_payload if isinstance(status_payload, dict) else None
    )
    assignee = fields_payload.get("assignee", {})
    if not isinstance(assignee, dict):
        assignee = {}
    reporter = fields_payload.get("reporter", {})
    if not isinstance(reporter, dict):
        reporter = {}
    assignee_name = assignee.get("displayName") or ""
    reporter_name = reporter.get("displayName") or ""
    issue_type = fields_payload.get("issuetype", {})
    if not isinstance(issue_type, dict):
        issue_type = {}
    priority = fields_payload.get("priority", {})
    if not isinstance(priority, dict):
        priority = {}
    project = fields_payload.get("project", {})
    if not isinstance(project, dict):
        project = {}
    parent = fields_payload.get("parent", {})
    if not isinstance(parent, dict):
        parent = {}
    parent_fields = parent.get("fields", {}) if isinstance(parent, dict) else {}
    if not isinstance(parent_fields, dict):
        parent_fields = {}
    labels = [
        label
        for label in fields_payload.get("labels", [])
        if isinstance(label, str) and label
    ]
    components = [
        component.get("name")
        for component in fields_payload.get("components", [])
        if isinstance(component, dict) and component.get("name")
    ]
    fix_versions = [
        version.get("name")
        for version in fields_payload.get("fixVersions", [])
        if isinstance(version, dict) and version.get("name")
    ]
    subtasks: list[dict[str, object]] = []
    subtask_items = fields_payload.get("subtasks", [])
    if isinstance(subtask_items, list):
        for item in subtask_items:
            if not isinstance(item, dict):
                continue
            subtask_fields = item.get("fields", {})
            if not isinstance(subtask_fields, dict):
                subtask_fields = {}
            subtask_status = subtask_fields.get("status")
            subtask_status_label, subtask_status_class = _jira_status_badge(
                subtask_status if isinstance(subtask_status, dict) else None
            )
            subtask_assignee = subtask_fields.get("assignee", {})
            if not isinstance(subtask_assignee, dict):
                subtask_assignee = {}
            subtask_assignee_name = subtask_assignee.get("displayName") or ""
            subtasks.append(
                {
                    "key": item.get("key") or "",
                    "summary": subtask_fields.get("summary") or "Untitled",
                    "status_label": subtask_status_label,
                    "status_class": subtask_status_class,
                    "assignee": subtask_assignee_name,
                    "assignee_avatar": _jira_avatar_url(subtask_assignee),
                    "assignee_initial": _user_initial(subtask_assignee_name),
                }
            )
    issue_key_value = payload.get("key") or issue_key
    return {
        "key": issue_key_value,
        "summary": fields_payload.get("summary") or "Untitled issue",
        "description": _normalize_adf_text(fields_payload.get("description")),
        "status_label": status_label,
        "status_class": status_class,
        "status": (
            status_payload.get("name")
            if isinstance(status_payload, dict)
            else ""
        ),
        "assignee": assignee_name,
        "assignee_avatar": _jira_avatar_url(assignee),
        "assignee_initial": _user_initial(assignee_name),
        "reporter": reporter_name,
        "reporter_avatar": _jira_avatar_url(reporter),
        "reporter_initial": _user_initial(reporter_name),
        "priority": priority.get("name") or "",
        "issue_type": issue_type.get("name") or "",
        "labels": labels,
        "components": components,
        "fix_versions": fix_versions,
        "created_at": _format_jira_timestamp(fields_payload.get("created")),
        "updated_at": _format_jira_timestamp(fields_payload.get("updated")),
        "project_key": project.get("key") or "",
        "project_name": project.get("name") or "",
        "parent": {
            "key": parent.get("key") or "",
            "summary": parent_fields.get("summary") or "",
        }
        if parent
        else {},
        "subtasks": subtasks,
        "url": f"{base}/browse/{issue_key_value}",
    }


def _fetch_jira_issue_comments(
    api_key: str, site: str, issue_key: str
) -> list[dict[str, object]]:
    comments: list[dict[str, object]] = []
    if not api_key or not site or not issue_key:
        return comments
    base = _normalize_atlassian_site(site)
    if not base:
        return comments
    headers = _build_atlassian_headers(api_key)
    start_at = 0
    max_results = 50
    total: int | None = None
    while True:
        query = urlencode(
            {"startAt": start_at, "maxResults": max_results, "orderBy": "-created"}
        )
        url = f"{base}/rest/api/3/issue/{quote(issue_key)}/comment?{query}"
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.load(response)
        except HTTPError as exc:
            body_snippet = _error_body_snippet(exc)
            logger.warning(
                "Jira comments: HTTP error code=%s url=%s body=%s",
                exc.code,
                url,
                body_snippet,
            )
            if exc.code in {401, 403}:
                raise ValueError("Jira API key is invalid or lacks comment access.") from exc
            if exc.code == 404:
                raise ValueError("Jira issue comments not found.") from exc
            raise ValueError("Jira API error while fetching comments.") from exc
        except URLError as exc:
            logger.warning("Jira comments: network error url=%s", url)
            raise ValueError("Unable to reach Jira API.") from exc
        if not isinstance(payload, dict):
            break
        values = payload.get("comments")
        if isinstance(values, list):
            for item in values:
                if not isinstance(item, dict):
                    continue
                author = item.get("author", {})
                if not isinstance(author, dict):
                    author = {}
                author_name = author.get("displayName") or "unknown"
                body = _normalize_adf_text(item.get("body"))
                comments.append(
                    {
                        "author": author_name,
                        "author_initial": _user_initial(author_name),
                        "author_avatar": _jira_avatar_url(author),
                        "body": body,
                        "created_at": _format_jira_timestamp(item.get("created")),
                        "updated_at": _format_jira_timestamp(item.get("updated")),
                    }
                )
        total_value = payload.get("total")
        if isinstance(total_value, int):
            total = total_value
        if total is None:
            break
        start_at += max_results
        if start_at >= total:
            break
    return comments


def _fetch_confluence_spaces(api_key: str, site: str) -> list[dict[str, str]]:
    spaces: list[dict[str, str]] = []
    if not api_key or not site:
        return spaces
    base = _normalize_atlassian_site(site)
    if not base:
        return spaces
    if not base.endswith("/wiki"):
        base = f"{base}/wiki"
    auth_mode = "basic" if ":" in api_key else "bearer"
    logger.info(
        "Confluence refresh: requesting spaces auth=%s site=%s",
        auth_mode,
        _safe_site_label(base),
    )
    headers = _build_atlassian_headers(api_key)
    url = f"{base}/rest/api/space?start=0&limit=50"
    seen: set[str] = set()
    while url:
        logger.info("Confluence refresh: request url=%s", url)
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                status_code = getattr(response, "status", None)
                logger.info("Confluence refresh: response status=%s", status_code)
                payload = json.load(response)
                results = payload.get("results")
                page_count = len(results) if isinstance(results, list) else 0
                logger.info(
                    "Confluence refresh: page items=%s next=%s",
                    page_count,
                    bool(payload.get("_links", {}).get("next")),
                )
                if isinstance(results, list):
                    for item in results:
                        if not isinstance(item, dict):
                            continue
                        key = item.get("key") or ""
                        name = item.get("name") or ""
                        key = key.strip() if isinstance(key, str) else ""
                        name = name.strip() if isinstance(name, str) else ""
                        value = key or name
                        if not value or value in seen:
                            continue
                        label = value
                        if key and name and key != name:
                            label = f"{key} - {name}"
                        spaces.append({"value": value, "label": label})
                        seen.add(value)
                next_link = None
                links = payload.get("_links")
                if isinstance(links, dict):
                    next_link = links.get("next")
                if next_link:
                    if isinstance(next_link, str) and next_link.startswith("http"):
                        url = next_link
                    elif isinstance(next_link, str):
                        url = f"{base}{next_link}"
                    else:
                        url = None
                    continue
                start = payload.get("start")
                limit = payload.get("limit")
                size = payload.get("size")
                if (
                    isinstance(start, int)
                    and isinstance(limit, int)
                    and isinstance(size, int)
                ):
                    if size < limit:
                        url = None
                    else:
                        url = (
                            f"{base}/rest/api/space?start={start + limit}&limit={limit}"
                        )
                else:
                    url = None
        except HTTPError as exc:
            body_snippet = _error_body_snippet(exc)
            logger.warning(
                "Confluence refresh: HTTP error code=%s url=%s body=%s",
                exc.code,
                url,
                body_snippet,
            )
            if exc.code in {401, 403}:
                raise ValueError(
                    "Confluence API key is invalid or lacks space access."
                ) from exc
            if exc.code == 404:
                raise ValueError("Confluence site URL not found.") from exc
            raise ValueError("Confluence API error while fetching spaces.") from exc
        except URLError as exc:
            logger.warning("Confluence refresh: network error url=%s", url)
            raise ValueError("Unable to reach Confluence API.") from exc
    logger.info("Confluence refresh: loaded %s spaces", len(spaces))
    spaces.sort(key=lambda item: item["label"].lower())
    return spaces


def _fetch_github_pull_requests(
    pat: str, repo_full_name: str, status_filter: str = "open"
) -> list[dict[str, object]]:
    pulls: list[dict[str, object]] = []
    if not pat or not repo_full_name:
        return pulls
    filter_key = (status_filter or "open").strip().lower()
    if filter_key not in {"all", "open", "closed", "merged", "draft"}:
        filter_key = "open"
    api_state = "all"
    if filter_key == "open":
        api_state = "open"
    elif filter_key == "draft":
        api_state = "open"
    elif filter_key in {"closed", "merged"}:
        api_state = "closed"
    url = (
        f"https://api.github.com/repos/{repo_full_name}/pulls"
        f"?per_page=50&state={api_state}&sort=updated&direction=desc"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {pat}",
        "User-Agent": "llmctl-studio",
    }
    while url:
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.load(response)
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    state = item.get("state", "open")
                    is_draft = bool(item.get("draft"))
                    merged_at = item.get("merged_at")
                    status_label, status_class = _github_status_badge(
                        state, is_draft, merged_at
                    )
                    if filter_key != "all" and status_label != filter_key:
                        continue
                    updated_label = _format_github_timestamp(item.get("updated_at"))
                    created_label = _format_github_timestamp(item.get("created_at"))
                    labels = _normalize_github_labels(item.get("labels", []))
                    comments = item.get("comments", 0)
                    review_comments = item.get("review_comments", 0)
                    comment_total = 0
                    if isinstance(comments, int):
                        comment_total += comments
                    if isinstance(review_comments, int):
                        comment_total += review_comments
                    pulls.append(
                        {
                            "title": item.get("title", "Untitled pull request"),
                            "number": str(item.get("number", "")),
                            "author": (
                                item.get("user", {}).get("login")
                                if isinstance(item.get("user"), dict)
                                else "unknown"
                            ),
                            "status_label": status_label,
                            "status_class": status_class,
                            "updated_at": updated_label,
                            "created_at": created_label,
                            "labels": labels,
                            "comment_count": comment_total,
                        }
                    )
                url = _parse_link_header(response.headers.get("Link", ""))
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise ValueError("GitHub PAT is invalid or lacks repo access.") from exc
            if exc.code == 404:
                raise ValueError("Repository not found or access denied.") from exc
            raise ValueError("GitHub API error while fetching pull requests.") from exc
        except URLError as exc:
            raise ValueError("Unable to reach GitHub API.") from exc
    return pulls


def _fetch_github_list(url: str, headers: dict[str, str], label: str) -> list[dict]:
    items: list[dict] = []
    while url:
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.load(response)
                if isinstance(payload, list):
                    items.extend(
                        item for item in payload if isinstance(item, dict)
                    )
                url = _parse_link_header(response.headers.get("Link", ""))
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise ValueError("GitHub PAT is invalid or lacks repo access.") from exc
            if exc.code == 404:
                raise ValueError("Pull request not found or access denied.") from exc
            raise ValueError(f"GitHub API error while fetching {label}.") from exc
        except URLError as exc:
            raise ValueError("Unable to reach GitHub API.") from exc
    return items


def _fetch_github_pull_request_detail(
    pat: str, repo_full_name: str, pr_number: int
) -> dict[str, object]:
    if not pat or not repo_full_name:
        return {}
    url = f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {pat}",
        "User-Agent": "llmctl-studio",
    }
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise ValueError("GitHub PAT is invalid or lacks repo access.") from exc
        if exc.code == 404:
            raise ValueError("Pull request not found or access denied.") from exc
        raise ValueError("GitHub API error while fetching pull request.") from exc
    except URLError as exc:
        raise ValueError("Unable to reach GitHub API.") from exc

    if not isinstance(payload, dict):
        return {}
    state = payload.get("state", "open")
    is_draft = bool(payload.get("draft"))
    merged_at = payload.get("merged_at")
    status_label, status_class = _github_status_badge(state, is_draft, merged_at)
    assignees = _extract_user_logins(payload.get("assignees"))
    requested_reviewers = _extract_user_logins(payload.get("requested_reviewers"))
    labels = _normalize_github_labels(payload.get("labels", []))
    commits = payload.get("commits")
    changed_files = payload.get("changed_files")
    additions = payload.get("additions")
    deletions = payload.get("deletions")
    return {
        "number": str(payload.get("number", pr_number)),
        "title": payload.get("title") or "Pull request",
        "body": payload.get("body") or "",
        "author": (
            payload.get("user", {}).get("login")
            if isinstance(payload.get("user"), dict)
            else "unknown"
        ),
        "status_label": status_label,
        "status_class": status_class,
        "created_at": _format_github_timestamp(payload.get("created_at")),
        "updated_at": _format_github_timestamp(payload.get("updated_at")),
        "merged_at": _format_github_timestamp(merged_at) if merged_at else "",
        "html_url": payload.get("html_url", ""),
        "head": (
            payload.get("head", {}).get("ref")
            if isinstance(payload.get("head"), dict)
            else ""
        ),
        "base": (
            payload.get("base", {}).get("ref")
            if isinstance(payload.get("base"), dict)
            else ""
        ),
        "commits": commits if isinstance(commits, int) else 0,
        "changed_files": changed_files if isinstance(changed_files, int) else 0,
        "additions": additions if isinstance(additions, int) else 0,
        "deletions": deletions if isinstance(deletions, int) else 0,
        "assignees": assignees,
        "requested_reviewers": requested_reviewers,
        "labels": labels,
    }


def _fetch_github_pull_request_timeline(
    pat: str, repo_full_name: str, pr_number: int
) -> tuple[list[dict[str, object]], set[str]]:
    if not pat or not repo_full_name:
        return [], set()
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {pat}",
        "User-Agent": "llmctl-studio",
    }
    issue_comments_url = (
        f"https://api.github.com/repos/{repo_full_name}/issues/{pr_number}/comments"
        "?per_page=100"
    )
    reviews_url = (
        f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}/reviews"
        "?per_page=100"
    )
    review_comments_url = (
        f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}/comments"
        "?per_page=100"
    )
    issue_comments = _fetch_github_list(
        issue_comments_url, headers, "pull request comments"
    )
    reviews = _fetch_github_list(reviews_url, headers, "pull request reviews")
    review_comments = _fetch_github_list(
        review_comments_url, headers, "pull request review comments"
    )

    comments: list[dict[str, object]] = []
    reviewers: set[str] = set()

    def build_comment(
        *,
        author: str,
        body: str,
        created_at_raw: str | None,
        badge_label: str,
        badge_class: str,
        context: str = "",
    ) -> None:
        comments.append(
            {
                "author": author,
                "body": body,
                "created_at": _format_github_timestamp(created_at_raw),
                "badge_label": badge_label,
                "badge_class": badge_class,
                "context": context,
                "sort_key": _parse_github_datetime(created_at_raw)
                or datetime.min.replace(tzinfo=timezone.utc),
            }
        )

    for item in issue_comments:
        author = (
            item.get("user", {}).get("login")
            if isinstance(item.get("user"), dict)
            else "unknown"
        )
        build_comment(
            author=author,
            body=item.get("body") or "",
            created_at_raw=item.get("created_at"),
            badge_label="comment",
            badge_class="status-idle",
        )

    for review in reviews:
        author = (
            review.get("user", {}).get("login")
            if isinstance(review.get("user"), dict)
            else "unknown"
        )
        if author:
            reviewers.add(author)
        state = (review.get("state") or "commented").replace("_", " ").lower()
        if state == "approved":
            badge_class = "status-success"
        elif state == "changes requested":
            badge_class = "status-failed"
        elif state == "dismissed":
            badge_class = "status-warning"
        else:
            badge_class = "status-idle"
        build_comment(
            author=author,
            body=review.get("body") or "",
            created_at_raw=review.get("submitted_at"),
            badge_label=f"review {state}",
            badge_class=badge_class,
        )

    for review_comment in review_comments:
        author = (
            review_comment.get("user", {}).get("login")
            if isinstance(review_comment.get("user"), dict)
            else "unknown"
        )
        path = review_comment.get("path") or ""
        line = review_comment.get("line")
        position = review_comment.get("position")
        context = path
        if isinstance(line, int):
            context = f"{path}:{line}" if path else str(line)
        elif isinstance(position, int):
            context = f"{path}:{position}" if path else str(position)
        build_comment(
            author=author,
            body=review_comment.get("body") or "",
            created_at_raw=review_comment.get("created_at"),
            badge_label="review comment",
            badge_class="status-idle",
            context=context,
        )

    comments.sort(key=lambda item: item["sort_key"])
    for item in comments:
        item.pop("sort_key", None)
    return comments, reviewers




def _build_github_code_review_prompt(
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


def _fetch_github_actions(pat: str, repo_full_name: str) -> list[dict[str, str]]:
    runs: list[dict[str, str]] = []
    if not pat or not repo_full_name:
        return runs
    url = (
        f"https://api.github.com/repos/{repo_full_name}/actions/runs"
        "?per_page=20"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {pat}",
        "User-Agent": "llmctl-studio",
    }
    while url:
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.load(response)
                items = payload.get("workflow_runs", []) if isinstance(payload, dict) else []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    status = item.get("status") or "completed"
                    conclusion = item.get("conclusion") or ""
                    if status in {"queued", "in_progress"}:
                        status_label = status.replace("_", " ")
                        status_class = "status-warning"
                    elif conclusion == "success":
                        status_label = "success"
                        status_class = "status-success"
                    elif conclusion in {"failure", "timed_out", "action_required"}:
                        status_label = conclusion.replace("_", " ")
                        status_class = "status-failed"
                    elif conclusion:
                        status_label = conclusion.replace("_", " ")
                        status_class = "status-idle"
                    else:
                        status_label = "completed"
                        status_class = "status-idle"
                    updated_raw = item.get("updated_at")
                    if isinstance(updated_raw, str):
                        try:
                            updated_at = datetime.fromisoformat(
                                updated_raw.replace("Z", "+00:00")
                            )
                            updated_label = _human_time(updated_at)
                        except ValueError:
                            updated_label = updated_raw
                    else:
                        updated_label = "-"
                    runs.append(
                        {
                            "name": item.get("name")
                            or item.get("display_title")
                            or "Workflow run",
                            "event": item.get("event", ""),
                            "branch": item.get("head_branch", ""),
                            "status_label": status_label,
                            "status_class": status_class,
                            "updated_at": updated_label,
                        }
                    )
                url = _parse_link_header(response.headers.get("Link", ""))
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise ValueError("GitHub PAT is invalid or lacks actions access.") from exc
            if exc.code == 404:
                raise ValueError("Repository not found or access denied.") from exc
            raise ValueError("GitHub API error while fetching workflow runs.") from exc
        except URLError as exc:
            raise ValueError("Unable to reach GitHub API.") from exc
    return runs


def _fetch_github_contents(
    pat: str, repo_full_name: str, path: str
) -> dict[str, object]:
    if not pat or not repo_full_name:
        return {"entries": [], "file": None, "path": path, "is_dir": True}
    cleaned_path = path.strip("/")
    encoded_path = quote(cleaned_path)
    if cleaned_path:
        url = f"https://api.github.com/repos/{repo_full_name}/contents/{encoded_path}"
    else:
        url = f"https://api.github.com/repos/{repo_full_name}/contents"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {pat}",
        "User-Agent": "llmctl-studio",
    }
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise ValueError("GitHub PAT is invalid or lacks repo access.") from exc
        if exc.code == 404:
            raise ValueError("Repository path not found or access denied.") from exc
        raise ValueError("GitHub API error while fetching code.") from exc
    except URLError as exc:
        raise ValueError("Unable to reach GitHub API.") from exc

    if isinstance(payload, list):
        entries = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            entries.append(
                {
                    "name": item.get("name", ""),
                    "path": item.get("path", ""),
                    "type": item.get("type", ""),
                }
            )
        entries.sort(
            key=lambda entry: (
                0 if entry.get("type") == "dir" else 1,
                entry.get("name", "").lower(),
            )
        )
        return {"entries": entries, "file": None, "path": cleaned_path, "is_dir": True}

    if isinstance(payload, dict):
        if payload.get("type") == "file":
            content = payload.get("content", "")
            if payload.get("encoding") == "base64":
                try:
                    decoded = base64.b64decode(content).decode("utf-8", errors="replace")
                except (ValueError, UnicodeDecodeError):
                    decoded = ""
            else:
                decoded = ""
            return {
                "entries": [],
                "file": {
                    "name": payload.get("name", ""),
                    "path": payload.get("path", cleaned_path),
                    "content": decoded,
                },
                "path": cleaned_path,
                "is_dir": False,
            }
        if payload.get("type") == "dir":
            return {"entries": [], "file": None, "path": cleaned_path, "is_dir": True}

    return {"entries": [], "file": None, "path": cleaned_path, "is_dir": True}


def _load_tasks_page(
    page: int,
    per_page: int,
    *,
    agent_id: int | None = None,
    kind: str | None = None,
    status: str | None = None,
) -> tuple[list[AgentTask], int, int, int]:
    with session_scope() as session:
        filters = []
        if agent_id is not None:
            filters.append(AgentTask.agent_id == agent_id)
        if kind:
            filters.append(AgentTask.kind == kind)
        if status:
            filters.append(AgentTask.status == status)

        count_stmt = select(func.count(AgentTask.id))
        if filters:
            count_stmt = count_stmt.where(*filters)
        total_tasks = session.execute(count_stmt).scalar_one()
        total_pages = (
            max(1, (total_tasks + per_page - 1) // per_page) if total_tasks else 1
        )
        page = max(1, min(page, total_pages))
        tasks = []
        if total_tasks:
            stmt = (
                select(AgentTask)
                .order_by(AgentTask.created_at.desc())
                .limit(per_page)
                .offset((page - 1) * per_page)
            )
            if filters:
                stmt = stmt.where(*filters)
            tasks = session.execute(stmt).scalars().all()
        return tasks, total_tasks, page, total_pages


def _build_pagination_items(
    current_page: int, total_pages: int
) -> list[dict[str, int | str]]:
    items: list[dict[str, int | str]] = []
    if total_pages <= 7:
        for page in range(1, total_pages + 1):
            items.append({"type": "page", "page": page})
        return items

    items.append({"type": "page", "page": 1})

    if current_page <= 4:
        window_start, window_end = 2, 5
    elif current_page >= total_pages - 3:
        window_start, window_end = total_pages - 4, total_pages - 1
    else:
        window_start, window_end = current_page - 2, current_page + 2

    if window_start > 2:
        items.append({"type": "gap"})

    for page in range(window_start, window_end + 1):
        items.append({"type": "page", "page": page})

    if window_end < total_pages - 1:
        items.append({"type": "gap"})

    items.append({"type": "page", "page": total_pages})
    return items


def _load_task_templates() -> list[TaskTemplate]:
    with session_scope() as session:
        return (
            session.execute(select(TaskTemplate).order_by(TaskTemplate.created_at.desc()))
            .scalars()
            .all()
        )


def _load_pipelines() -> list[Pipeline]:
    with session_scope() as session:
        return (
            session.execute(select(Pipeline).order_by(Pipeline.created_at.desc()))
            .scalars()
            .all()
        )


def _load_roles() -> list[Role]:
    with session_scope() as session:
        return (
            session.execute(select(Role).order_by(Role.created_at.desc()))
            .scalars()
            .all()
        )


PAGINATION_PAGE_SIZES = (10, 25, 50, 100)
PAGINATION_DEFAULT_SIZE = 10
PAGINATION_WINDOW = 2


def _parse_page(value: str | None) -> int:
    try:
        page = int(value)
    except (TypeError, ValueError):
        return 1
    return page if page > 0 else 1


def _parse_page_size(value: str | None) -> int:
    try:
        per_page = int(value)
    except (TypeError, ValueError):
        return PAGINATION_DEFAULT_SIZE
    return per_page if per_page in PAGINATION_PAGE_SIZES else PAGINATION_DEFAULT_SIZE


def _pagination_items(current_page: int, total_pages: int) -> list[int | None]:
    if total_pages <= (PAGINATION_WINDOW * 2) + 5:
        return list(range(1, total_pages + 1))

    items: list[int | None] = [1]
    start = max(2, current_page - PAGINATION_WINDOW)
    end = min(total_pages - 1, current_page + PAGINATION_WINDOW)

    if start > 2:
        items.append(None)
    items.extend(range(start, end + 1))
    if end < total_pages - 1:
        items.append(None)
    items.append(total_pages)
    return items


def _build_pagination(
    base_path: str,
    page: int,
    per_page: int,
    total_count: int,
) -> dict[str, object]:
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    if page > total_pages:
        page = total_pages

    def _page_url(target_page: int, target_per_page: int | None = None) -> str:
        params = {
            "page": target_page,
            "per_page": target_per_page or per_page,
        }
        return f"{base_path}?{urlencode(params)}"

    page_items = []
    for item in _pagination_items(page, total_pages):
        if item is None:
            page_items.append({"label": "...", "url": None, "is_gap": True})
        else:
            page_items.append(
                {
                    "label": str(item),
                    "url": _page_url(item),
                    "is_gap": False,
                    "is_current": item == page,
                }
            )

    if total_count > 0:
        start_index = (page - 1) * per_page + 1
        end_index = min(total_count, page * per_page)
    else:
        start_index = 0
        end_index = 0

    return {
        "base_path": base_path,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "total_count": total_count,
        "start_index": start_index,
        "end_index": end_index,
        "page_items": page_items,
        "prev_url": _page_url(page - 1) if page > 1 else None,
        "next_url": _page_url(page + 1) if page < total_pages else None,
        "page_sizes": PAGINATION_PAGE_SIZES,
    }


def _load_mcp_servers() -> list[MCPServer]:
    with session_scope() as session:
        return (
            session.execute(
                select(MCPServer)
                .options(selectinload(MCPServer.agents))
                .order_by(MCPServer.created_at.desc())
            )
            .scalars()
            .all()
        )


def _load_scripts() -> list[Script]:
    with session_scope() as session:
        return (
            session.execute(select(Script).order_by(Script.created_at.desc()))
            .scalars()
            .all()
        )


def _load_memories() -> list[Memory]:
    with session_scope() as session:
        return (
            session.execute(select(Memory).order_by(Memory.created_at.desc()))
            .scalars()
            .all()
        )


def _load_attachments() -> list[Attachment]:
    with session_scope() as session:
        return (
            session.execute(
                select(Attachment)
                .options(
                    selectinload(Attachment.tasks),
                    selectinload(Attachment.templates),
                    selectinload(Attachment.pipeline_steps),
                )
                .order_by(Attachment.created_at.desc())
            )
            .scalars()
            .all()
        )


def _load_milestones() -> list[Milestone]:
    with session_scope() as session:
        return (
            session.execute(
                select(Milestone).order_by(Milestone.created_at.desc())
            )
            .scalars()
            .all()
        )


def _load_pipeline_steps(pipeline_ids: list[int]) -> list[PipelineStep]:
    if not pipeline_ids:
        return []
    with session_scope() as session:
        return (
            session.execute(
                select(PipelineStep)
                .where(PipelineStep.pipeline_id.in_(pipeline_ids))
                .order_by(PipelineStep.pipeline_id.asc(), PipelineStep.step_order.asc())
            )
            .scalars()
            .all()
        )


def _load_pipeline_runs(limit: int = 10) -> list[PipelineRun]:
    with session_scope() as session:
        return (
            session.execute(
                select(PipelineRun).order_by(PipelineRun.created_at.desc()).limit(limit)
            )
            .scalars()
            .all()
        )


@bp.get("/")
def index():
    return redirect(url_for("agents.dashboard"))


@bp.get("/overview")
def dashboard():
    agents = _load_agents()
    active_agents, summary = _agent_rollup(agents)
    recent_agents = agents[:5]
    recent_runs = sorted(
        [agent for agent in agents if agent.last_run_at],
        key=lambda agent: agent.last_run_at or agent.created_at,
        reverse=True,
    )[:5]
    return render_template(
        "dashboard.html",
        agents=agents,
        active_agents=active_agents,
        recent_agents=recent_agents,
        recent_runs=recent_runs,
        summary=summary,
        human_time=_human_time,
        page_title="Overview",
        active_page="overview",
    )


@bp.get("/agents")
def list_agents():
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    agent_ids = [agent.id for agent in agents]
    agent_status_by_id = _agent_status_by_id(agent_ids)
    roles = _load_roles()
    roles_by_id = {role.id: role.name for role in roles}
    return render_template(
        "agents.html",
        agents=agents,
        agent_status_by_id=agent_status_by_id,
        roles_by_id=roles_by_id,
        summary=summary,
        human_time=_human_time,
        page_title="Agents",
        active_page="agents",
    )


@bp.get("/agents/new")
def new_agent():
    roles = _load_roles()
    models = _load_llm_models()
    scripts = _load_scripts()
    scripts_by_type = _group_scripts_by_type(scripts)
    selected_scripts_by_type = {script_type: [] for script_type in SCRIPT_TYPE_FIELDS}
    return render_template(
        "agent_new.html",
        roles=roles,
        models=models,
        scripts_by_type=scripts_by_type,
        selected_scripts_by_type=selected_scripts_by_type,
        script_type_fields=SCRIPT_TYPE_FIELDS,
        script_type_choices=SCRIPT_TYPE_CHOICES,
        page_title="Create Agent",
        active_page="agents",
    )


@bp.post("/agents")
def create_agent():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    autonomous_prompt = request.form.get("autonomous_prompt", "").strip()
    role_raw = request.form.get("role_id", "").strip()
    model_raw = request.form.get("model_id", "").strip()
    script_ids_by_type, legacy_ids, script_error = _parse_script_selection()

    if not description:
        flash("Agent description is required.", "error")
        return redirect(url_for("agents.new_agent"))
    if script_error:
        flash(script_error, "error")
        return redirect(url_for("agents.new_agent"))

    if not name:
        name = "Untitled Agent"

    role_id = None
    if role_raw:
        try:
            role_id = int(role_raw)
        except ValueError:
            flash("Role must be a number.", "error")
            return redirect(url_for("agents.new_agent"))
    model_id = None
    if model_raw:
        try:
            model_id = int(model_raw)
        except ValueError:
            flash("Model must be a number.", "error")
            return redirect(url_for("agents.new_agent"))
    with session_scope() as session:
        if role_id is not None:
            role = session.get(Role, role_id)
            if role is None:
                flash("Role not found.", "error")
                return redirect(url_for("agents.new_agent"))
        if model_id is not None:
            model = session.get(LLMModel, model_id)
            if model is None:
                flash("Model not found.", "error")
                return redirect(url_for("agents.new_agent"))
        script_ids_by_type, script_error = _resolve_script_selection(
            session,
            script_ids_by_type,
            legacy_ids,
        )
        if script_error:
            flash(script_error, "error")
            return redirect(url_for("agents.new_agent"))
        prompt_payload = {"description": description}
        if autonomous_prompt:
            prompt_payload["autoprompt"] = autonomous_prompt
        prompt_json = json.dumps(prompt_payload, indent=2, sort_keys=True)
        agent = Agent.create(
            session,
            name=name,
            role_id=role_id,
            model_id=model_id,
            description=description,
            prompt_json=prompt_json,
            prompt_text=None,
            autonomous_prompt=autonomous_prompt or None,
            is_system=False,
        )
        _set_agent_scripts(session, agent.id, script_ids_by_type)
        agent_id = agent.id

    flash(f"Agent {agent_id} created.", "success")
    return redirect(url_for("agents.view_agent", agent_id=agent_id))


@bp.get("/agents/<int:agent_id>")
def view_agent(agent_id: int):
    roles = _load_roles()
    roles_by_id = {role.id: role.name for role in roles}
    with session_scope() as session:
        agent = (
            session.execute(
                select(Agent)
                .options(
                    selectinload(Agent.scripts),
                    selectinload(Agent.mcp_servers),
                )
                .where(Agent.id == agent_id)
            )
            .scalars()
            .one_or_none()
        )
        if agent is None:
            abort(404)
    agent_status_by_id = _agent_status_by_id([agent.id])
    agent_status = agent_status_by_id.get(agent.id, "stopped")
    return render_template(
        "agent_detail.html",
        agent=agent,
        agent_status=agent_status,
        roles_by_id=roles_by_id,
        human_time=_human_time,
        page_title=f"Agent - {agent.name}",
        active_page="agents",
        agent_section="overview",
    )


@bp.get("/agents/<int:agent_id>/scripts")
def view_agent_scripts(agent_id: int):
    roles = _load_roles()
    roles_by_id = {role.id: role.name for role in roles}
    with session_scope() as session:
        agent = (
            session.execute(
                select(Agent)
                .options(
                    selectinload(Agent.scripts),
                    selectinload(Agent.mcp_servers),
                )
                .where(Agent.id == agent_id)
            )
            .scalars()
            .one_or_none()
        )
        if agent is None:
            abort(404)
    agent_status_by_id = _agent_status_by_id([agent.id])
    agent_status = agent_status_by_id.get(agent.id, "stopped")
    return render_template(
        "agent_scripts.html",
        agent=agent,
        agent_status=agent_status,
        roles_by_id=roles_by_id,
        human_time=_human_time,
        page_title=f"Agent - {agent.name} - Scripts",
        active_page="agents",
        agent_section="scripts",
    )


@bp.get("/agents/<int:agent_id>/mcp")
def view_agent_mcp(agent_id: int):
    roles = _load_roles()
    roles_by_id = {role.id: role.name for role in roles}
    mcp_servers = _load_mcp_servers()
    with session_scope() as session:
        agent = (
            session.execute(
                select(Agent)
                .options(
                    selectinload(Agent.scripts),
                    selectinload(Agent.mcp_servers),
                )
                .where(Agent.id == agent_id)
            )
            .scalars()
            .one_or_none()
        )
        if agent is None:
            abort(404)
        agent_mcp_ids = {mcp.id for mcp in agent.mcp_servers}
    agent_status_by_id = _agent_status_by_id([agent.id])
    agent_status = agent_status_by_id.get(agent.id, "stopped")
    available_mcp_servers = [
        mcp for mcp in mcp_servers if mcp.id not in agent_mcp_ids
    ]
    return render_template(
        "agent_mcp.html",
        agent=agent,
        agent_status=agent_status,
        roles_by_id=roles_by_id,
        available_mcp_servers=available_mcp_servers,
        human_time=_human_time,
        page_title=f"Agent - {agent.name} - MCP",
        active_page="agents",
        agent_section="mcp",
    )


@bp.get("/agents/<int:agent_id>/edit")
def edit_agent(agent_id: int):
    roles = _load_roles()
    models = _load_llm_models()
    scripts = _load_scripts()
    scripts_by_type = _group_scripts_by_type(scripts)
    with session_scope() as session:
        agent = (
            session.execute(
                select(Agent)
                .options(selectinload(Agent.mcp_servers), selectinload(Agent.scripts))
                .where(Agent.id == agent_id)
            )
            .scalars()
            .one_or_none()
        )
        if agent is None:
            abort(404)
        selected_scripts_by_type = _group_selected_scripts_by_type(list(agent.scripts))
    return render_template(
        "agent_edit.html",
        agent=agent,
        roles=roles,
        models=models,
        scripts_by_type=scripts_by_type,
        selected_scripts_by_type=selected_scripts_by_type,
        script_type_fields=SCRIPT_TYPE_FIELDS,
        script_type_choices=SCRIPT_TYPE_CHOICES,
        page_title=f"Edit Agent - {agent.name}",
        active_page="agents",
    )


@bp.post("/agents/<int:agent_id>")
def update_agent(agent_id: int):
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    autonomous_prompt = request.form.get("autonomous_prompt", "").strip()
    role_raw = request.form.get("role_id", "").strip()
    model_raw = request.form.get("model_id", "").strip()
    script_ids_by_type, legacy_ids, script_error = _parse_script_selection()

    if not description:
        flash("Agent description is required.", "error")
        return redirect(url_for("agents.edit_agent", agent_id=agent_id))
    if script_error:
        flash(script_error, "error")
        return redirect(url_for("agents.edit_agent", agent_id=agent_id))

    role_id = None
    if role_raw:
        try:
            role_id = int(role_raw)
        except ValueError:
            flash("Role must be a number.", "error")
            return redirect(url_for("agents.edit_agent", agent_id=agent_id))
    model_id = None
    if model_raw:
        try:
            model_id = int(model_raw)
        except ValueError:
            flash("Model must be a number.", "error")
            return redirect(url_for("agents.edit_agent", agent_id=agent_id))

    with session_scope() as session:
        agent = session.get(Agent, agent_id)
        if agent is None:
            abort(404)
        if role_id is not None:
            role = session.get(Role, role_id)
            if role is None:
                flash("Role not found.", "error")
                return redirect(url_for("agents.edit_agent", agent_id=agent_id))
        if model_id is not None:
            model = session.get(LLMModel, model_id)
            if model is None:
                flash("Model not found.", "error")
                return redirect(url_for("agents.edit_agent", agent_id=agent_id))
        script_ids_by_type, script_error = _resolve_script_selection(
            session,
            script_ids_by_type,
            legacy_ids,
        )
        if script_error:
            flash(script_error, "error")
            return redirect(url_for("agents.edit_agent", agent_id=agent_id))
        if not name:
            name = agent.name or "Untitled Agent"
        prompt_payload = {"description": description}
        if autonomous_prompt:
            prompt_payload["autoprompt"] = autonomous_prompt
        prompt_json = json.dumps(prompt_payload, indent=2, sort_keys=True)
        agent.name = name
        agent.description = description
        agent.prompt_json = prompt_json
        agent.prompt_text = None
        agent.autonomous_prompt = autonomous_prompt or None
        agent.role_id = role_id
        agent.model_id = model_id
        _set_agent_scripts(session, agent.id, script_ids_by_type)

    flash("Agent updated.", "success")
    return redirect(url_for("agents.view_agent", agent_id=agent_id))


@bp.post("/agents/<int:agent_id>/mcp-servers")
def add_agent_mcp_server(agent_id: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.view_agent", agent_id=agent_id)
    )
    mcp_raw = request.form.get("mcp_server_id", "").strip()
    if not mcp_raw.isdigit():
        flash("Select a valid MCP server.", "error")
        return redirect(redirect_target)
    mcp_id = int(mcp_raw)
    with session_scope() as session:
        agent = session.get(Agent, agent_id)
        if agent is None:
            abort(404)
        mcp_server = session.get(MCPServer, mcp_id)
        if mcp_server is None:
            flash("MCP server not found.", "error")
            return redirect(redirect_target)
        if mcp_server in agent.mcp_servers:
            flash("MCP server already attached.", "info")
            return redirect(redirect_target)
        agent.mcp_servers.append(mcp_server)
    flash("MCP server attached.", "success")
    return redirect(redirect_target)


@bp.post("/agents/<int:agent_id>/mcp-servers/<int:mcp_id>/delete")
def remove_agent_mcp_server(agent_id: int, mcp_id: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.view_agent", agent_id=agent_id)
    )
    with session_scope() as session:
        agent = session.get(Agent, agent_id)
        if agent is None:
            abort(404)
        mcp_server = session.get(MCPServer, mcp_id)
        if mcp_server is None:
            flash("MCP server not found.", "error")
            return redirect(redirect_target)
        if mcp_server not in agent.mcp_servers:
            flash("MCP server is not attached.", "info")
            return redirect(redirect_target)
        agent.mcp_servers.remove(mcp_server)
    flash("MCP server removed.", "success")
    return redirect(redirect_target)


@bp.post("/roles")
def create_role():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    raw_details = request.form.get("details_json", "").strip()

    if not description:
        flash("Role description is required.", "error")
        return redirect(url_for("agents.new_role"))

    try:
        formatted_details = _parse_role_details(raw_details)
    except json.JSONDecodeError as exc:
        flash(f"Invalid JSON: {exc.msg}", "error")
        return redirect(url_for("agents.new_role"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("agents.new_role"))

    if not name:
        name = "Untitled Role"

    with session_scope() as session:
        role = Role.create(
            session,
            name=name,
            description=description,
            details_json=formatted_details,
            is_system=False,
        )

    flash("Role created.", "success")
    return redirect(url_for("agents.view_role", role_id=role.id))


@bp.post("/agents/<int:agent_id>/start")
def start_agent(agent_id: int):
    fallback_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_agents")
    )
    with session_scope() as session:
        agent = session.get(Agent, agent_id)
        if agent is None:
            abort(404)
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
            flash("Autorun is already enabled for this agent.", "info")
            return redirect(url_for("agents.view_run", run_id=active_run_id))
        run = Run.create(
            session,
            agent_id=agent_id,
            run_max_loops=agent.run_max_loops,
            status="starting",
            last_started_at=utcnow(),
            run_end_requested=False,
        )
        agent.last_started_at = run.last_started_at
        agent.run_end_requested = False
        session.flush()
        run_id = run.id

    task = run_agent.delay(run_id)

    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            return redirect(fallback_target)
        run.task_id = task.id
        agent = session.get(Agent, run.agent_id)
        if agent is not None:
            agent.task_id = task.id

    flash("Autorun enabled.", "success")
    return redirect(url_for("agents.view_run", run_id=run_id))


@bp.post("/agents/<int:agent_id>/stop")
def stop_agent(agent_id: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_agents")
    )
    task_id = None
    with session_scope() as session:
        agent = session.get(Agent, agent_id)
        if agent is None:
            abort(404)
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
            flash("Autorun is already off.", "info")
            return redirect(redirect_target)
        if run.task_id:
            run.run_end_requested = True
            if run.status in {"starting", "running"}:
                run.status = "stopping"
        else:
            run.status = "stopped"
            run.run_end_requested = False
        if run.task_id:
            run.last_run_task_id = run.task_id
        task_id = run.task_id
        agent.run_end_requested = run.run_end_requested
        if run.task_id:
            agent.last_run_task_id = run.task_id

    if task_id and Config.CELERY_REVOKE_ON_STOP:
        celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")

    flash("Autorun disable requested.", "success")
    return redirect(redirect_target)


@bp.post("/agents/<int:agent_id>/delete")
def delete_agent(agent_id: int):
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_agents")
    )
    with session_scope() as session:
        agent = session.get(Agent, agent_id)
        if agent is None:
            abort(404)
        active_run_id = (
            session.execute(
                select(Run.id)
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
        if active_run_id:
            flash("Disable autorun before deleting.", "error")
            return redirect(next_url)
        agent.mcp_servers = []
        agent.scripts = []
        runs = (
            session.execute(select(Run).where(Run.agent_id == agent_id))
            .scalars()
            .all()
        )
        run_ids = [run.id for run in runs]
        tasks = (
            session.execute(select(AgentTask).where(AgentTask.agent_id == agent_id))
            .scalars()
            .all()
        )
        task_count = len(tasks)
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

    flash("Agent deleted.", "success")
    if task_count:
        flash(f"Detached from {task_count} task(s).", "info")
    return redirect(next_url)


@bp.post("/runs/<int:run_id>/start")
def start_run(run_id: int):
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            abort(404)
        target = url_for("agents.view_agent", agent_id=run.agent_id)
    flash("Autoruns are managed from the agent.", "info")
    return redirect(target)


@bp.post("/runs/<int:run_id>/cancel")
def cancel_run(run_id: int):
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            abort(404)
        target = url_for("agents.view_agent", agent_id=run.agent_id)
    flash("Autoruns are managed from the agent.", "info")
    return redirect(target)


@bp.post("/runs/<int:run_id>/end")
def end_run(run_id: int):
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            abort(404)
        target = url_for("agents.view_agent", agent_id=run.agent_id)
    flash("Autoruns are managed from the agent.", "info")
    return redirect(target)


@bp.post("/runs/<int:run_id>/delete")
def delete_run(run_id: int):
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.runs")
    )
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            abort(404)
        if run.status in RUN_ACTIVE_STATUSES:
            flash("Disable autorun before deleting.", "error")
            return redirect(next_url)
        session.execute(
            update(AgentTask)
            .where(AgentTask.run_id == run_id)
            .values(run_id=None)
        )
        session.delete(run)
    flash("Autorun deleted.", "success")
    return redirect(next_url)


@bp.get("/runs/new")
def new_run():
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    selected_agent_id = request.args.get("agent_id", "").strip()
    selected_agent: int | None = None
    if selected_agent_id.isdigit():
        selected_agent = int(selected_agent_id)
    return render_template(
        "run_new.html",
        agents=agents,
        selected_agent_id=selected_agent,
        summary=summary,
        page_title="Autoruns",
        active_page="runs",
    )


@bp.get("/runs/<int:run_id>")
def view_run(run_id: int):
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            abort(404)
        agent = session.get(Agent, run.agent_id)
        if agent is None:
            abort(404)
        run_task_id = run.task_id or run.last_run_task_id
        if run_task_id is None:
            run_task_id = session.execute(
                select(AgentTask.run_task_id)
                .where(
                    AgentTask.run_id == run_id,
                    AgentTask.run_task_id.isnot(None),
                    AgentTask.pipeline_run_id.is_(None),
                )
                .order_by(AgentTask.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
        run_tasks: list[AgentTask] = []
        loops_completed = 0
        if run_task_id:
            run_tasks = (
                session.execute(
                    select(AgentTask)
                    .where(
                        AgentTask.run_task_id == run_task_id,
                        AgentTask.run_id == run_id,
                    )
                    .order_by(AgentTask.created_at.desc())
                    .limit(50)
                )
                .scalars()
                .all()
            )
            loops_completed = session.execute(
                select(func.count(AgentTask.id)).where(
                    AgentTask.run_task_id == run_task_id,
                    AgentTask.run_id == run_id,
                )
            ).scalar_one()
    run_max_loops = run.run_max_loops or 0
    run_is_forever = run_max_loops < 1
    loops_remaining = (
        None if run_is_forever else max(run_max_loops - loops_completed, 0)
    )
    return render_template(
        "run_detail.html",
        run=run,
        agent=agent,
        run_task_id=run_task_id,
        run_tasks=run_tasks,
        loops_completed=loops_completed,
        loops_remaining=loops_remaining,
        run_is_forever=run_is_forever,
        run_max_loops=run_max_loops,
        summary=summary,
        page_title=run.name or f"Autorun {run.id}",
        active_page="runs",
    )


@bp.get("/runs/<int:run_id>/edit")
def edit_run(run_id: int):
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            abort(404)
        agent = session.get(Agent, run.agent_id)
        if agent is None:
            abort(404)
    run_max_loops = run.run_max_loops or 0
    run_is_forever = run_max_loops < 1
    return render_template(
        "run_edit.html",
        run=run,
        agent=agent,
        agents=agents,
        run_max_loops=run_max_loops,
        run_is_forever=run_is_forever,
        summary=summary,
        page_title=f"Autorun - {run.name or agent.name}",
        active_page="runs",
    )


@bp.post("/runs/<int:run_id>")
def update_run(run_id: int):
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            abort(404)
        target = url_for("agents.view_agent", agent_id=run.agent_id)
    flash("Autoruns are managed from the agent.", "info")
    return redirect(target)


@bp.post("/runs")
def create_run():
    flash("Autoruns are created automatically when you enable autorun on an agent.", "info")
    return redirect(url_for("agents.list_agents"))


@bp.get("/runs")
def runs():
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    page = _parse_positive_int(request.args.get("page"), 1)
    per_page = _parse_positive_int(request.args.get("per_page"), DEFAULT_RUNS_PER_PAGE)
    if per_page not in RUNS_PER_PAGE_OPTIONS:
        per_page = DEFAULT_RUNS_PER_PAGE
    runs, total_runs, page, total_pages = _load_runs_page(page, per_page)
    pagination_items = _build_pagination_items(page, total_pages)
    current_url = request.full_path
    if current_url.endswith("?"):
        current_url = current_url[:-1]
    return render_template(
        "runs.html",
        runs=runs,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total_runs=total_runs,
        per_page_options=RUNS_PER_PAGE_OPTIONS,
        pagination_items=pagination_items,
        current_url=current_url,
        summary=summary,
        human_time=_human_time,
        page_title="Autoruns",
        active_page="runs",
    )


@bp.get("/quick")
def quick_task():
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    default_agent_id = _load_quick_agent_id(agents)
    return render_template(
        "quick_task.html",
        agents=agents,
        default_agent_id=default_agent_id,
        summary=summary,
        page_title="Quick Task",
        active_page="quick",
    )


@bp.get("/chat")
def legacy_chat_redirect():
    return redirect(url_for("agents.quick_task"), code=301)


@bp.post("/quick")
def create_quick_task():
    agent_id_raw = request.form.get("agent_id", "").strip()
    prompt = request.form.get("prompt", "").strip()
    uploads = request.files.getlist("attachments")
    if not agent_id_raw:
        flash("Agent is required.", "error")
        return redirect(url_for("agents.quick_task"))
    if not prompt:
        flash("Prompt is required.", "error")
        return redirect(url_for("agents.quick_task"))

    try:
        with session_scope() as session:
            agent_id: int | None = None
            agent_payload: object | None = None
            try:
                agent_id = int(agent_id_raw)
            except ValueError:
                flash("Select a valid agent.", "error")
                return redirect(url_for("agents.quick_task"))
            agent = session.get(Agent, agent_id)
            if agent is None:
                flash("Agent not found.", "error")
                return redirect(url_for("agents.quick_task"))
            agent_payload = _build_agent_prompt_payload(
                agent,
                include_autoprompt=False,
            )

            payload: dict[str, object] = {
                "prompt": prompt,
                "output_instructions": OUTPUT_INSTRUCTIONS_ONE_OFF,
            }
            if agent_payload is not None:
                payload["agent"] = agent_payload
            prompt_payload = json.dumps(payload, indent=2, sort_keys=True)
            task = AgentTask.create(
                session,
                agent_id=agent_id,
                status="queued",
                prompt=prompt_payload,
                kind=QUICK_TASK_KIND,
            )
            attachments = _save_uploaded_attachments(session, uploads)
            _attach_attachments(task, attachments)
            task_id = task.id
    except (OSError, ValueError) as exc:
        logger.exception("Failed to save quick task attachments")
        flash(str(exc) or "Failed to save attachments.", "error")
        return redirect(url_for("agents.quick_task"))

    celery_task = run_agent_task.delay(task_id)

    with session_scope() as session:
        task = session.get(AgentTask, task_id)
        if task is not None:
            task.celery_task_id = celery_task.id

    flash(f"Quick Task {task_id} queued.", "success")
    return redirect(url_for("agents.view_task", task_id=task_id))


@bp.post("/chat")
def legacy_chat_create():
    return create_quick_task()


@bp.get("/tasks")
def list_tasks():
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    page = _parse_positive_int(request.args.get("page"), 1)
    per_page = _parse_positive_int(request.args.get("per_page"), DEFAULT_TASKS_PER_PAGE)
    if per_page not in TASKS_PER_PAGE_OPTIONS:
        per_page = DEFAULT_TASKS_PER_PAGE
    agent_filter_options = []
    filter_agent_ids = set()
    for agent in agents:
        label = agent.name or f"Agent {agent.id}"
        agent_filter_options.append({"value": agent.id, "label": label})
        filter_agent_ids.add(agent.id)
    agent_filter_options.sort(key=lambda item: item["label"].lower())

    with session_scope() as session:
        kind_values = {
            value
            for value in session.execute(select(AgentTask.kind).distinct())
            .scalars()
            .all()
            if value
        }
        status_values = {
            value
            for value in session.execute(select(AgentTask.status).distinct())
            .scalars()
            .all()
            if value
        }

    kind_filter_raw = (request.args.get("kind") or "").strip()
    kind_filter = kind_filter_raw if kind_filter_raw in kind_values else None
    status_filter_raw = (request.args.get("status") or "").strip()
    status_filter = status_filter_raw if status_filter_raw in status_values else None
    agent_filter = None
    agent_filter_raw = request.args.get("agent_id")
    if agent_filter_raw:
        candidate = _parse_positive_int(agent_filter_raw, 0)
        if candidate in filter_agent_ids:
            agent_filter = candidate

    status_order = {
        "pending": 0,
        "queued": 1,
        "running": 2,
        "succeeded": 3,
        "failed": 4,
        "canceled": 5,
    }
    task_kind_options = [
        {"value": kind, "label": task_kind_label(kind)}
        for kind in sorted(kind_values, key=lambda value: value.lower())
    ]
    task_status_options = [
        {"value": status, "label": status.replace("_", " ")}
        for status in sorted(
            status_values, key=lambda value: (status_order.get(value, 99), value)
        )
    ]

    tasks, total_tasks, page, total_pages = _load_tasks_page(
        page,
        per_page,
        agent_id=agent_filter,
        kind=kind_filter,
        status=status_filter,
    )
    pagination_items = _build_pagination_items(page, total_pages)
    agent_ids = {task.agent_id for task in tasks if task.agent_id is not None}
    agents_by_id = {}
    if agent_ids:
        with session_scope() as session:
            rows = session.execute(
                select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids))
            ).all()
        agents_by_id = {row[0]: row[1] for row in rows}
    pipeline_ids = {task.pipeline_id for task in tasks if task.pipeline_id}
    template_ids = {task.task_template_id for task in tasks if task.task_template_id}
    pipelines_by_id = {}
    templates_by_id = {}
    if pipeline_ids:
        with session_scope() as session:
            rows = session.execute(
                select(Pipeline.id, Pipeline.name).where(Pipeline.id.in_(pipeline_ids))
            ).all()
        pipelines_by_id = {row[0]: row[1] for row in rows}
    if template_ids:
        with session_scope() as session:
            rows = session.execute(
                select(TaskTemplate.id, TaskTemplate.name).where(
                    TaskTemplate.id.in_(template_ids)
                )
            ).all()
        templates_by_id = {row[0]: row[1] for row in rows}
    current_url = request.full_path
    if current_url.endswith("?"):
        current_url = current_url[:-1]
    return render_template(
        "tasks.html",
        tasks=tasks,
        agents_by_id=agents_by_id,
        pipelines_by_id=pipelines_by_id,
        templates_by_id=templates_by_id,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total_tasks=total_tasks,
        per_page_options=TASKS_PER_PAGE_OPTIONS,
        pagination_items=pagination_items,
        agent_filter_options=agent_filter_options,
        task_kind_options=task_kind_options,
        task_status_options=task_status_options,
        agent_filter=agent_filter,
        kind_filter=kind_filter,
        status_filter=status_filter,
        current_url=current_url,
        summary=summary,
        human_time=_human_time,
        page_title="Tasks",
        active_page="tasks",
    )


@bp.get("/tasks/<int:task_id>")
def view_task(task_id: int):
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    with session_scope() as session:
        task = (
            session.execute(
                select(AgentTask)
                .options(
                    selectinload(AgentTask.scripts),
                    selectinload(AgentTask.attachments),
                )
                .where(AgentTask.id == task_id)
            )
            .scalars()
            .first()
        )
        if task is None:
            abort(404)
        agent = None
        if task.agent_id is not None:
            agent = (
                session.execute(
                    select(Agent)
                    .options(selectinload(Agent.scripts))
                    .where(Agent.id == task.agent_id)
                )
                .scalars()
                .first()
            )
        pipeline = session.get(Pipeline, task.pipeline_id) if task.pipeline_id else None
        template = (
            session.get(TaskTemplate, task.task_template_id)
            if task.task_template_id
            else None
        )
        stage_entries = _build_stage_entries(task)
        prompt_text, prompt_json = _parse_task_prompt(task.prompt)
    return render_template(
        "task_detail.html",
        task=task,
        is_quick_task=is_quick_task_kind(task.kind),
        agent=agent,
        pipeline=pipeline,
        template=template,
        stage_entries=stage_entries,
        prompt_text=prompt_text,
        prompt_json=prompt_json,
        summary=summary,
        page_title=f"Task {task_id}",
        active_page="tasks",
    )


@bp.post("/tasks/<int:task_id>/attachments/<int:attachment_id>/remove")
def remove_task_attachment(task_id: int, attachment_id: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.view_task", task_id=task_id)
    )
    removed_path: str | None = None
    with session_scope() as session:
        task = (
            session.execute(
                select(AgentTask)
                .options(selectinload(AgentTask.attachments))
                .where(AgentTask.id == task_id)
            )
            .scalars()
            .first()
        )
        if task is None:
            abort(404)
        attachment = next(
            (item for item in task.attachments if item.id == attachment_id), None
        )
        if attachment is None:
            flash("Attachment not found on this task.", "error")
            return redirect(redirect_target)
        task.attachments.remove(attachment)
        session.flush()
        removed_path = _delete_attachment_if_unused(session, attachment)
    if removed_path:
        remove_attachment_file(removed_path)
    flash("Attachment removed.", "success")
    return redirect(redirect_target)


@bp.get("/tasks/<int:task_id>/status")
def task_status(task_id: int):
    with session_scope() as session:
        task = session.get(AgentTask, task_id)
        if task is None:
            abort(404)
        return {
            "id": task.id,
            "status": task.status,
            "run_task_id": task.run_task_id,
            "celery_task_id": task.celery_task_id,
            "pipeline_run_id": task.pipeline_run_id,
            "prompt_length": len(task.prompt) if task.prompt else 0,
            "output": task.output or "",
            "error": task.error or "",
            "current_stage": task.current_stage or "",
            "stage_logs": _parse_stage_logs(task.stage_logs),
            "stage_entries": _build_stage_entries(task),
            "started_at": _human_time(task.started_at),
            "finished_at": _human_time(task.finished_at),
            "created_at": _human_time(task.created_at),
        }


@bp.post("/tasks/<int:task_id>/cancel")
def cancel_task(task_id: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_tasks")
    )
    with session_scope() as session:
        task = session.get(AgentTask, task_id)
        if task is None:
            abort(404)
        if task.status not in {"queued", "running"}:
            flash("Task is not running.", "info")
            return redirect(redirect_target)
        if task.celery_task_id and Config.CELERY_REVOKE_ON_STOP:
            celery_app.control.revoke(
                task.celery_task_id, terminate=True, signal="SIGTERM"
            )
        task.status = "canceled"
        task.error = "Canceled by user."
        task.finished_at = utcnow()
    flash("Task cancel requested.", "success")
    return redirect(redirect_target)


@bp.post("/tasks/<int:task_id>/delete")
def delete_task(task_id: int):
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_tasks")
    )
    with session_scope() as session:
        task = session.get(AgentTask, task_id)
        if task is None:
            abort(404)
        if task.status in {"queued", "running"} and task.celery_task_id:
            if Config.CELERY_REVOKE_ON_STOP:
                celery_app.control.revoke(
                    task.celery_task_id, terminate=True, signal="SIGTERM"
                )
        session.delete(task)
    flash("Task deleted.", "success")
    return redirect(next_url)


@bp.get("/tasks/new")
def new_task():
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    scripts = _load_scripts()
    scripts_by_type = _group_scripts_by_type(scripts)
    selected_scripts_by_type = {script_type: [] for script_type in SCRIPT_TYPE_FIELDS}
    return render_template(
        "new_task.html",
        agents=agents,
        scripts_by_type=scripts_by_type,
        selected_scripts_by_type=selected_scripts_by_type,
        script_type_fields=SCRIPT_TYPE_FIELDS,
        script_type_choices=SCRIPT_TYPE_CHOICES,
        summary=summary,
        page_title="New Task",
        active_page="tasks",
    )


@bp.post("/tasks/new")
def create_task():
    agent_id_raw = request.form.get("agent_id", "").strip()
    prompt = request.form.get("prompt", "").strip()
    uploads = request.files.getlist("attachments")
    script_ids_by_type, legacy_ids, script_error = _parse_script_selection()
    if not agent_id_raw:
        flash("Select an agent.", "error")
        return redirect(url_for("agents.new_task"))
    try:
        agent_id = int(agent_id_raw)
    except ValueError:
        flash("Select a valid agent.", "error")
        return redirect(url_for("agents.new_task"))
    if not prompt:
        flash("Prompt is required.", "error")
        return redirect(url_for("agents.new_task"))
    if script_error:
        flash(script_error, "error")
        return redirect(url_for("agents.new_task"))

    try:
        with session_scope() as session:
            agent = session.get(Agent, agent_id)
            if agent is None:
                flash("Agent not found.", "error")
                return redirect(url_for("agents.new_task"))
            script_ids_by_type, script_error = _resolve_script_selection(
                session,
                script_ids_by_type,
                legacy_ids,
            )
            if script_error:
                flash(script_error, "error")
                return redirect(url_for("agents.new_task"))
            task = AgentTask.create(
                session,
                agent_id=agent_id,
                status="queued",
                prompt=prompt,
            )
            _set_task_scripts(session, task.id, script_ids_by_type)
            attachments = _save_uploaded_attachments(session, uploads)
            _attach_attachments(task, attachments)
            task_id = task.id
    except (OSError, ValueError) as exc:
        logger.exception("Failed to save task attachments")
        flash(str(exc) or "Failed to save attachments.", "error")
        return redirect(url_for("agents.new_task"))

    celery_task = run_agent_task.delay(task_id)

    with session_scope() as session:
        task = session.get(AgentTask, task_id)
        if task is not None:
            task.celery_task_id = celery_task.id

    flash(f"Task {task_id} queued.", "success")
    return redirect(url_for("agents.list_tasks"))


@bp.get("/milestones")
def list_milestones():
    milestones = _load_milestones()
    return render_template(
        "milestones.html",
        milestones=milestones,
        human_time=_human_time,
        page_title="Milestones",
        active_page="milestones",
    )


@bp.get("/milestones/new")
def new_milestone():
    return render_template(
        "milestone_new.html",
        page_title="Create Milestone",
        active_page="milestones",
    )


@bp.post("/milestones")
def create_milestone():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Name is required.", "error")
        return redirect(url_for("agents.new_milestone"))

    description = request.form.get("description", "").strip() or None
    due_date_raw = request.form.get("due_date", "").strip()
    due_date = _parse_milestone_due_date(due_date_raw)
    if due_date_raw and due_date is None:
        flash("Due date must be a valid date.", "error")
        return redirect(url_for("agents.new_milestone"))

    completed = bool(request.form.get("completed"))

    with session_scope() as session:
        milestone = Milestone.create(
            session,
            name=name,
            description=description,
            due_date=due_date,
            completed=completed,
        )

    flash(f"Milestone {milestone.id} created.", "success")
    return redirect(url_for("agents.view_milestone", milestone_id=milestone.id))


@bp.get("/milestones/<int:milestone_id>")
def view_milestone(milestone_id: int):
    with session_scope() as session:
        milestone = session.get(Milestone, milestone_id)
        if milestone is None:
            abort(404)
    return render_template(
        "milestone_detail.html",
        milestone=milestone,
        human_time=_human_time,
        page_title=f"Milestone - {milestone.name}",
        active_page="milestones",
    )


@bp.post("/milestones/<int:milestone_id>/delete")
def delete_milestone(milestone_id: int):
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_milestones")
    )
    with session_scope() as session:
        milestone = session.get(Milestone, milestone_id)
        if milestone is None:
            abort(404)
        session.delete(milestone)
    flash("Milestone deleted.", "success")
    return redirect(next_url)


@bp.get("/task-templates")
def list_task_templates():
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    templates = _load_task_templates()
    agents_by_id = {agent.id: agent.name for agent in agents}
    return render_template(
        "task_templates.html",
        templates=templates,
        agents_by_id=agents_by_id,
        summary=summary,
        human_time=_human_time,
        page_title="Templates",
        active_page="templates",
    )


@bp.get("/task-templates/new")
def new_task_template():
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    return render_template(
        "task_template_new.html",
        agents=agents,
        summary=summary,
        page_title="Create Template",
        active_page="templates",
    )


@bp.get("/task-templates/<int:template_id>")
def view_task_template(template_id: int):
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    agents_by_id = {agent.id: agent.name for agent in agents}
    with session_scope() as session:
        template = (
            session.execute(
                select(TaskTemplate)
                .options(selectinload(TaskTemplate.attachments))
                .where(TaskTemplate.id == template_id)
            )
            .scalars()
            .first()
        )
        if template is None:
            abort(404)
        pipeline_step_count = session.execute(
            select(func.count(PipelineStep.id)).where(
                PipelineStep.task_template_id == template_id
            )
        ).scalar_one()
        task_count = session.execute(
            select(func.count(AgentTask.id)).where(
                AgentTask.task_template_id == template_id
            )
        ).scalar_one()
    return render_template(
        "task_template_detail.html",
        template=template,
        agents_by_id=agents_by_id,
        pipeline_step_count=pipeline_step_count,
        task_count=task_count,
        summary=summary,
        human_time=_human_time,
        page_title=f"Template - {template.name}",
        active_page="templates",
    )


@bp.get("/task-templates/<int:template_id>/edit")
def edit_task_template(template_id: int):
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    with session_scope() as session:
        template = (
            session.execute(
                select(TaskTemplate)
                .options(selectinload(TaskTemplate.attachments))
                .where(TaskTemplate.id == template_id)
            )
            .scalars()
            .first()
        )
        if template is None:
            abort(404)
    return render_template(
        "task_template_edit.html",
        template=template,
        agents=agents,
        summary=summary,
        page_title=f"Edit Template - {template.name}",
        active_page="templates",
    )


@bp.get("/pipelines/new")
def new_pipeline():
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    return render_template(
        "pipeline_new.html",
        summary=summary,
        page_title="Create Pipeline",
        active_page="pipelines",
    )


@bp.get("/pipelines")
def list_pipelines():
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    pipelines = _load_pipelines()
    pipeline_ids = [pipeline.id for pipeline in pipelines]
    steps = _load_pipeline_steps(pipeline_ids)
    step_counts: dict[int, int] = {}
    for step in steps:
        step_counts[step.pipeline_id] = step_counts.get(step.pipeline_id, 0) + 1
    return render_template(
        "pipelines.html",
        pipelines=pipelines,
        step_counts=step_counts,
        summary=summary,
        human_time=_human_time,
        page_title="Pipelines",
        active_page="pipelines",
    )


@bp.get("/pipelines/<int:pipeline_id>")
def view_pipeline(pipeline_id: int):
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    templates = _load_task_templates()
    agents_by_id = {agent.id: agent.name for agent in agents}
    templates_by_id = {template.id: template for template in templates}
    with session_scope() as session:
        pipeline = session.get(Pipeline, pipeline_id)
        if pipeline is None:
            abort(404)
        steps = (
            session.execute(
                select(PipelineStep)
                .options(selectinload(PipelineStep.attachments))
                .where(PipelineStep.pipeline_id == pipeline_id)
                .order_by(PipelineStep.step_order.asc())
            )
            .scalars()
            .all()
        )
    return render_template(
        "pipeline_detail.html",
        pipeline=pipeline,
        steps=steps,
        templates=templates,
        templates_by_id=templates_by_id,
        agents_by_id=agents_by_id,
        summary=summary,
        human_time=_human_time,
        page_title=f"Pipeline - {pipeline.name}",
        active_page="pipelines",
    )


@bp.get("/pipelines/<int:pipeline_id>/edit")
def edit_pipeline(pipeline_id: int):
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    with session_scope() as session:
        pipeline = session.get(Pipeline, pipeline_id)
        if pipeline is None:
            abort(404)
    return render_template(
        "pipeline_edit.html",
        pipeline=pipeline,
        summary=summary,
        page_title=f"Edit Pipeline - {pipeline.name}",
        active_page="pipelines",
    )


@bp.get("/pipelines/runs/<int:run_id>")
def view_pipeline_run(run_id: int):
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    with session_scope() as session:
        run = session.get(PipelineRun, run_id)
        if run is None:
            abort(404)
        pipeline = (
            session.get(Pipeline, run.pipeline_id) if run.pipeline_id else None
        )
        tasks = (
            session.execute(
                select(AgentTask)
                .where(AgentTask.pipeline_run_id == run_id)
                .order_by(AgentTask.created_at.asc(), AgentTask.id.asc())
            )
            .scalars()
            .all()
        )
        agent_ids = {task.agent_id for task in tasks if task.agent_id is not None}
        template_ids = {
            task.task_template_id for task in tasks if task.task_template_id
        }
        step_ids = {task.pipeline_step_id for task in tasks if task.pipeline_step_id}
        agents_by_id: dict[int, str] = {}
        templates_by_id: dict[int, str] = {}
        steps_by_id: dict[int, PipelineStep] = {}
        if agent_ids:
            rows = session.execute(
                select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids))
            ).all()
            agents_by_id = {row[0]: row[1] for row in rows}
        if template_ids:
            rows = session.execute(
                select(TaskTemplate.id, TaskTemplate.name).where(
                    TaskTemplate.id.in_(template_ids)
                )
            ).all()
            templates_by_id = {row[0]: row[1] for row in rows}
        if step_ids:
            steps = (
                session.execute(
                    select(PipelineStep).where(PipelineStep.id.in_(step_ids))
                )
                .scalars()
                .all()
            )
            steps_by_id = {step.id: step for step in steps}
    return render_template(
        "pipeline_run_detail.html",
        pipeline_run=run,
        pipeline=pipeline,
        tasks=tasks,
        agents_by_id=agents_by_id,
        templates_by_id=templates_by_id,
        steps_by_id=steps_by_id,
        summary=summary,
        human_time=_human_time,
        page_title=f"Pipeline Run {run.id}",
        active_page="pipelines",
    )


@bp.get("/pipelines/runs/<int:run_id>/status")
def pipeline_run_status(run_id: int):
    with session_scope() as session:
        run = session.get(PipelineRun, run_id)
        if run is None:
            abort(404)
        tasks = (
            session.execute(
                select(AgentTask)
                .where(AgentTask.pipeline_run_id == run_id)
                .order_by(AgentTask.created_at.asc(), AgentTask.id.asc())
            )
            .scalars()
            .all()
        )
        agent_ids = {task.agent_id for task in tasks if task.agent_id is not None}
        template_ids = {
            task.task_template_id for task in tasks if task.task_template_id
        }
        step_ids = {task.pipeline_step_id for task in tasks if task.pipeline_step_id}
        agents_by_id: dict[int, str] = {}
        templates_by_id: dict[int, str] = {}
        steps_by_id: dict[int, PipelineStep] = {}
        if agent_ids:
            rows = session.execute(
                select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids))
            ).all()
            agents_by_id = {row[0]: row[1] for row in rows}
        if template_ids:
            rows = session.execute(
                select(TaskTemplate.id, TaskTemplate.name).where(
                    TaskTemplate.id.in_(template_ids)
                )
            ).all()
            templates_by_id = {row[0]: row[1] for row in rows}
        if step_ids:
            steps = (
                session.execute(
                    select(PipelineStep).where(PipelineStep.id.in_(step_ids))
                )
                .scalars()
                .all()
            )
            steps_by_id = {step.id: step for step in steps}
    tasks_html = render_template(
        "partials/pipeline_run_tasks.html",
        tasks=tasks,
        agents_by_id=agents_by_id,
        templates_by_id=templates_by_id,
        steps_by_id=steps_by_id,
        human_time=_human_time,
    )
    return {
        "id": run.id,
        "status": run.status,
        "celery_task_id": run.celery_task_id,
        "created_at": _human_time(run.created_at),
        "started_at": _human_time(run.started_at),
        "finished_at": _human_time(run.finished_at),
        "tasks_html": tasks_html,
    }


@bp.post("/pipelines/runs/<int:run_id>/cancel")
def cancel_pipeline_run(run_id: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.view_pipeline_run", run_id=run_id)
    )
    revoke_ids: list[str] = []
    run_task_id = None
    with session_scope() as session:
        run = session.get(PipelineRun, run_id)
        if run is None:
            abort(404)
        if run.status not in {"queued", "running"}:
            flash("Pipeline run is already stopped.", "info")
            return redirect(redirect_target)
        now = utcnow()
        run.status = "canceled"
        run.finished_at = now
        run_task_id = run.celery_task_id
        tasks = (
            session.execute(
                select(AgentTask).where(AgentTask.pipeline_run_id == run_id)
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

    if run_task_id:
        revoke_ids.append(run_task_id)
    for task_id in revoke_ids:
        try:
            celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
        except Exception as exc:
            logger.warning("Failed to revoke pipeline task %s: %s", task_id, exc)

    flash("Pipeline run canceled.", "success")
    return redirect(redirect_target)


@bp.get("/pipelines/history")
def pipeline_history():
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    pipelines = _load_pipelines()
    history_limit = 50
    runs = _load_pipeline_runs(limit=history_limit)
    pipelines_by_id = {pipeline.id: pipeline.name for pipeline in pipelines}
    return render_template(
        "pipeline_history.html",
        pipeline_runs=runs,
        history_limit=history_limit,
        pipelines_by_id=pipelines_by_id,
        summary=summary,
        human_time=_human_time,
        page_title="Pipeline History",
        active_page="pipelines",
    )


@bp.get("/mcps")
def list_mcps():
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    mcp_servers = _load_mcp_servers()
    return render_template(
        "mcps.html",
        mcp_servers=mcp_servers,
        summary=summary,
        human_time=_human_time,
        page_title="MCP Servers",
        active_page="mcps",
    )


@bp.get("/models")
def list_models():
    models = _load_llm_models()
    llm_settings = _load_integration_settings("llm")
    default_model_id = resolve_default_model_id(llm_settings)
    model_rows = []
    for model in models:
        model_rows.append(
            {
                "id": model.id,
                "name": model.name,
                "description": model.description,
                "provider": model.provider,
                "provider_label": LLM_PROVIDER_LABELS.get(model.provider, model.provider),
                "model_name": _model_display_name(model),
                "is_default": model.id == default_model_id,
            }
        )
    return render_template(
        "models.html",
        models=model_rows,
        default_model_id=default_model_id,
        page_title="Models",
        active_page="models",
    )


@bp.get("/models/new")
def new_model():
    model_options = _provider_model_options()
    codex_default_model = _codex_default_model(model_options.get("codex"))
    return render_template(
        "model_new.html",
        provider_options=_provider_options(),
        selected_provider="codex",
        codex_config=_codex_model_config_defaults(
            {},
            default_model=codex_default_model,
        ),
        gemini_config=_gemini_model_config_defaults({}),
        claude_config=_simple_model_config_defaults({}),
        model_options=model_options,
        page_title="Create Model",
        active_page="models",
    )


@bp.post("/models")
def create_model():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    provider = (request.form.get("provider") or "").strip().lower()

    if not name:
        flash("Model name is required.", "error")
        return redirect(url_for("agents.new_model"))
    if provider not in LLM_PROVIDERS:
        flash("Unknown provider selection.", "error")
        return redirect(url_for("agents.new_model"))

    config_payload = _model_config_payload(provider, request.form)
    model_options = _provider_model_options()
    model_name = str(config_payload.get("model") or "").strip()
    if provider == "codex" and not _model_option_allowed(provider, model_name, model_options):
        flash("Codex model must be selected from the configured options.", "error")
        return redirect(url_for("agents.new_model"))
    config_json = json.dumps(config_payload, indent=2, sort_keys=True)

    with session_scope() as session:
        model = LLMModel.create(
            session,
            name=name,
            description=description or None,
            provider=provider,
            config_json=config_json,
        )

    flash(f"Model {model.id} created.", "success")
    return redirect(url_for("agents.view_model", model_id=model.id))


@bp.get("/models/<int:model_id>")
def view_model(model_id: int):
    with session_scope() as session:
        model = session.get(LLMModel, model_id)
        if model is None:
            abort(404)
        attached_agents = (
            session.execute(
                select(Agent)
                .where(Agent.model_id == model_id)
                .order_by(Agent.created_at.desc())
            )
            .scalars()
            .all()
        )
    llm_settings = _load_integration_settings("llm")
    default_model_id = resolve_default_model_id(llm_settings)
    is_default = default_model_id == model_id
    config = _decode_model_config(model.config_json)
    formatted_config = json.dumps(config, indent=2, sort_keys=True)
    provider_label = LLM_PROVIDER_LABELS.get(model.provider, model.provider)
    return render_template(
        "model_detail.html",
        model=model,
        provider_label=provider_label,
        model_name=_model_display_name(model),
        config_json=formatted_config,
        attached_agents=attached_agents,
        is_default=is_default,
        page_title=f"Model - {model.name}",
        active_page="models",
    )


@bp.get("/models/<int:model_id>/edit")
def edit_model(model_id: int):
    with session_scope() as session:
        model = session.get(LLMModel, model_id)
        if model is None:
            abort(404)
    config = _decode_model_config(model.config_json)
    model_options = _provider_model_options()
    codex_default_model = _codex_default_model(model_options.get("codex"))
    return render_template(
        "model_edit.html",
        model=model,
        provider_options=_provider_options(),
        selected_provider=model.provider,
        codex_config=_codex_model_config_defaults(
            config if model.provider == "codex" else {},
            default_model=codex_default_model,
        ),
        gemini_config=_gemini_model_config_defaults(
            config if model.provider == "gemini" else {}
        ),
        claude_config=_simple_model_config_defaults(
            config if model.provider == "claude" else {}
        ),
        model_options=model_options,
        page_title=f"Edit Model - {model.name}",
        active_page="models",
    )


@bp.post("/models/<int:model_id>")
def update_model(model_id: int):
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    provider = (request.form.get("provider") or "").strip().lower()

    if not name:
        flash("Model name is required.", "error")
        return redirect(url_for("agents.edit_model", model_id=model_id))
    if provider not in LLM_PROVIDERS:
        flash("Unknown provider selection.", "error")
        return redirect(url_for("agents.edit_model", model_id=model_id))

    config_payload = _model_config_payload(provider, request.form)
    model_options = _provider_model_options()
    model_name = str(config_payload.get("model") or "").strip()
    if provider == "codex" and not _model_option_allowed(provider, model_name, model_options):
        flash("Codex model must be selected from the configured options.", "error")
        return redirect(url_for("agents.edit_model", model_id=model_id))
    config_json = json.dumps(config_payload, indent=2, sort_keys=True)

    with session_scope() as session:
        model = session.get(LLMModel, model_id)
        if model is None:
            abort(404)
        model.name = name
        model.description = description or None
        model.provider = provider
        model.config_json = config_json

    flash("Model updated.", "success")
    return redirect(url_for("agents.view_model", model_id=model_id))


@bp.post("/models/default")
def update_default_model():
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_models")
    )
    model_raw = request.form.get("model_id", "").strip()
    if not model_raw.isdigit():
        flash("Model selection required.", "error")
        return redirect(next_url)
    model_id = int(model_raw)
    make_default = _as_bool(request.form.get("is_default"))
    with session_scope() as session:
        model = session.get(LLMModel, model_id)
        if model is None:
            flash("Model not found.", "error")
            return redirect(next_url)
    if make_default:
        payload = {
            "default_model_id": str(model_id),
            f"provider_enabled_{model.provider}": "true",
        }
        _save_integration_settings("llm", payload)
        flash("Default model updated.", "success")
    else:
        _save_integration_settings("llm", {"default_model_id": ""})
        flash("Default model cleared.", "success")
    return redirect(next_url)


@bp.post("/models/<int:model_id>/delete")
def delete_model(model_id: int):
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_models")
    )
    with session_scope() as session:
        model = session.get(LLMModel, model_id)
        if model is None:
            abort(404)
        attached_agents = (
            session.execute(select(Agent).where(Agent.model_id == model_id))
            .scalars()
            .all()
        )
        for agent in attached_agents:
            agent.model_id = None
        session.delete(model)

    flash("Model deleted.", "success")
    if attached_agents:
        flash(f"Detached from {len(attached_agents)} agent(s).", "info")
    llm_settings = _load_integration_settings("llm")
    if resolve_default_model_id(llm_settings) == model_id:
        _save_integration_settings("llm", {"default_model_id": ""})
        flash("Default model cleared.", "info")
    return redirect(next_url)


@bp.get("/mcps/new")
def new_mcp():
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    return render_template(
        "mcp_new.html",
        summary=summary,
        page_title="Create MCP Server",
        active_page="mcps",
    )


@bp.post("/mcps")
def create_mcp():
    name = request.form.get("name", "").strip()
    server_key = request.form.get("server_key", "").strip()
    description = request.form.get("description", "").strip()
    raw_config = request.form.get("config_json", "").strip()

    if not name or not server_key:
        flash("Name and server key are required.", "error")
        return redirect(url_for("agents.new_mcp"))
    if not raw_config:
        flash("MCP config TOML is required.", "error")
        return redirect(url_for("agents.new_mcp"))

    try:
        validate_server_key(server_key)
        formatted_config = format_mcp_config(raw_config, server_key=server_key)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("agents.new_mcp"))

    with session_scope() as session:
        existing = session.execute(
            select(MCPServer).where(MCPServer.server_key == server_key)
        ).scalar_one_or_none()
        if existing is not None:
            flash("Server key is already in use.", "error")
            return redirect(url_for("agents.new_mcp"))
        mcp = MCPServer.create(
            session,
            name=name,
            server_key=server_key,
            description=description or None,
            config_json=formatted_config,
        )

    flash(f"MCP server {mcp.id} created.", "success")
    return redirect(url_for("agents.view_mcp", mcp_id=mcp.id))


@bp.get("/mcps/<int:mcp_id>/edit")
def edit_mcp(mcp_id: int):
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    with session_scope() as session:
        mcp_server = session.get(MCPServer, mcp_id)
        if mcp_server is None:
            abort(404)
    return render_template(
        "mcp_edit.html",
        mcp_server=mcp_server,
        summary=summary,
        page_title=f"Edit MCP Server - {mcp_server.name}",
        active_page="mcps",
    )


@bp.post("/mcps/<int:mcp_id>")
def update_mcp(mcp_id: int):
    name = request.form.get("name", "").strip()
    server_key = request.form.get("server_key", "").strip()
    description = request.form.get("description", "").strip()
    raw_config = request.form.get("config_json", "").strip()

    if not name or not server_key:
        flash("Name and server key are required.", "error")
        return redirect(url_for("agents.edit_mcp", mcp_id=mcp_id))
    if not raw_config:
        flash("MCP config TOML is required.", "error")
        return redirect(url_for("agents.edit_mcp", mcp_id=mcp_id))

    try:
        validate_server_key(server_key)
        formatted_config = format_mcp_config(raw_config, server_key=server_key)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("agents.edit_mcp", mcp_id=mcp_id))

    with session_scope() as session:
        mcp = session.get(MCPServer, mcp_id)
        if mcp is None:
            abort(404)
        existing = (
            session.execute(
                select(MCPServer).where(
                    MCPServer.server_key == server_key, MCPServer.id != mcp_id
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            flash("Server key is already in use.", "error")
            return redirect(url_for("agents.edit_mcp", mcp_id=mcp_id))
        mcp.name = name
        mcp.server_key = server_key
        mcp.description = description or None
        mcp.config_json = formatted_config

    flash("MCP server updated.", "success")
    return redirect(url_for("agents.view_mcp", mcp_id=mcp_id))


@bp.post("/mcps/<int:mcp_id>/delete")
def delete_mcp(mcp_id: int):
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_mcps")
    )
    with session_scope() as session:
        mcp = session.get(MCPServer, mcp_id)
        if mcp is None:
            abort(404)
        attached_agents = list(mcp.agents)
        if attached_agents:
            mcp.agents = []
        session.delete(mcp)

    flash("MCP server deleted.", "success")
    if attached_agents:
        flash(f"Detached from {len(attached_agents)} agent(s).", "info")
    return redirect(next_url)


@bp.get("/mcps/<int:mcp_id>")
def view_mcp(mcp_id: int):
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    with session_scope() as session:
        mcp_server = (
            session.execute(
                select(MCPServer)
                .options(selectinload(MCPServer.agents))
                .where(MCPServer.id == mcp_id)
            )
            .scalars()
            .first()
        )
        if mcp_server is None:
            abort(404)
        attached_agents = list(mcp_server.agents)
    return render_template(
        "mcp_detail.html",
        mcp_server=mcp_server,
        attached_agents=attached_agents,
        summary=summary,
        human_time=_human_time,
        page_title=mcp_server.name,
        active_page="mcps",
    )


@bp.get("/scripts")
def list_scripts():
    scripts = _load_scripts()
    return render_template(
        "scripts.html",
        scripts=scripts,
        human_time=_human_time,
        page_title="Scripts",
        active_page="scripts",
    )


@bp.get("/attachments")
def list_attachments():
    attachments = _load_attachments()
    return render_template(
        "attachments.html",
        attachments=attachments,
        human_time=_human_time,
        format_bytes=_format_bytes,
        page_title="Attachments",
        active_page="attachments",
    )


@bp.get("/attachments/<int:attachment_id>")
def view_attachment(attachment_id: int):
    with session_scope() as session:
        attachment = (
            session.execute(
                select(Attachment)
                .options(
                    selectinload(Attachment.tasks),
                    selectinload(Attachment.templates),
                    selectinload(Attachment.pipeline_steps),
                )
                .where(Attachment.id == attachment_id)
            )
            .scalars()
            .first()
        )
        if attachment is None:
            abort(404)
        tasks = list(attachment.tasks)
        templates = list(attachment.templates)
        pipeline_steps = list(attachment.pipeline_steps)

        tasks.sort(key=lambda item: item.created_at or datetime.min, reverse=True)
        templates.sort(key=lambda item: item.created_at or datetime.min, reverse=True)
        pipeline_steps.sort(key=lambda item: (item.pipeline_id, item.step_order))

        agent_ids = {task.agent_id for task in tasks if task.agent_id is not None}
        pipeline_ids = {task.pipeline_id for task in tasks if task.pipeline_id}
        template_ids = {task.task_template_id for task in tasks if task.task_template_id}
        pipeline_ids.update(step.pipeline_id for step in pipeline_steps)
        template_ids.update(step.task_template_id for step in pipeline_steps)

        agents_by_id: dict[int, str] = {}
        if agent_ids:
            rows = session.execute(
                select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids))
            ).all()
            agents_by_id = {row[0]: row[1] for row in rows}

        pipelines_by_id: dict[int, str] = {}
        if pipeline_ids:
            rows = session.execute(
                select(Pipeline.id, Pipeline.name).where(Pipeline.id.in_(pipeline_ids))
            ).all()
            pipelines_by_id = {row[0]: row[1] for row in rows}

        templates_by_id: dict[int, str] = {}
        if template_ids:
            rows = session.execute(
                select(TaskTemplate.id, TaskTemplate.name).where(
                    TaskTemplate.id.in_(template_ids)
                )
            ).all()
            templates_by_id = {row[0]: row[1] for row in rows}

    is_image_attachment = _is_image_attachment(attachment)
    attachment_preview_url = None
    if is_image_attachment and attachment.file_path:
        attachment_preview_url = url_for(
            "agents.view_attachment_file", attachment_id=attachment.id
        )

    return render_template(
        "attachment_detail.html",
        attachment=attachment,
        attachment_preview_url=attachment_preview_url,
        is_image_attachment=is_image_attachment,
        tasks=tasks,
        templates=templates,
        pipeline_steps=pipeline_steps,
        agents_by_id=agents_by_id,
        pipelines_by_id=pipelines_by_id,
        templates_by_id=templates_by_id,
        human_time=_human_time,
        format_bytes=_format_bytes,
        page_title=f"Attachment - {attachment.file_name}",
        active_page="attachments",
    )


@bp.get("/attachments/<int:attachment_id>/file")
def view_attachment_file(attachment_id: int):
    with session_scope() as session:
        attachment = session.get(Attachment, attachment_id)
        if attachment is None or not attachment.file_path:
            abort(404)
        file_path = Path(attachment.file_path)
        content_type = attachment.content_type
        file_name = attachment.file_name

    if not file_path.exists():
        abort(404)
    try:
        attachments_root = Path(Config.ATTACHMENTS_DIR).resolve()
        resolved_path = file_path.resolve()
    except OSError:
        abort(404)
    if resolved_path != attachments_root and attachments_root not in resolved_path.parents:
        abort(404)

    return send_file(
        resolved_path,
        mimetype=content_type or None,
        as_attachment=False,
        download_name=file_name,
        conditional=True,
    )


@bp.post("/attachments/<int:attachment_id>/delete")
def delete_attachment(attachment_id: int):
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_attachments")
    )
    removed_path: str | None = None
    with session_scope() as session:
        attachment = session.get(Attachment, attachment_id)
        if attachment is None:
            abort(404)
        removed_path = attachment.file_path
        _unlink_attachment(session, attachment.id)
        session.delete(attachment)
    if removed_path:
        remove_attachment_file(removed_path)
    flash("Attachment deleted.", "success")
    return redirect(next_url)


@bp.get("/memories")
def list_memories():
    memories = _load_memories()
    return render_template(
        "memories.html",
        memories=memories,
        human_time=_human_time,
        page_title="Memories",
        active_page="memories",
    )


@bp.get("/memories/new")
def new_memory():
    return render_template(
        "memory_new.html",
        page_title="Create Memory",
        active_page="memories",
    )


@bp.post("/memories")
def create_memory():
    description = request.form.get("description", "").strip()
    if not description:
        flash("Description is required.", "error")
        return redirect(url_for("agents.new_memory"))

    with session_scope() as session:
        memory = Memory.create(session, description=description)

    flash(f"Memory {memory.id} created.", "success")
    return redirect(url_for("agents.view_memory", memory_id=memory.id))


@bp.get("/memories/<int:memory_id>")
def view_memory(memory_id: int):
    with session_scope() as session:
        memory = session.get(Memory, memory_id)
        if memory is None:
            abort(404)
    return render_template(
        "memory_detail.html",
        memory=memory,
        human_time=_human_time,
        page_title="Memory",
        active_page="memories",
    )


@bp.get("/memories/<int:memory_id>/edit")
def edit_memory(memory_id: int):
    with session_scope() as session:
        memory = session.get(Memory, memory_id)
        if memory is None:
            abort(404)
    return render_template(
        "memory_edit.html",
        memory=memory,
        page_title="Edit Memory",
        active_page="memories",
    )


@bp.post("/memories/<int:memory_id>")
def update_memory(memory_id: int):
    description = request.form.get("description", "").strip()
    if not description:
        flash("Description is required.", "error")
        return redirect(url_for("agents.edit_memory", memory_id=memory_id))

    with session_scope() as session:
        memory = session.get(Memory, memory_id)
        if memory is None:
            abort(404)
        memory.description = description

    flash("Memory updated.", "success")
    return redirect(url_for("agents.view_memory", memory_id=memory_id))


@bp.post("/memories/<int:memory_id>/delete")
def delete_memory(memory_id: int):
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_memories")
    )
    with session_scope() as session:
        memory = session.get(Memory, memory_id)
        if memory is None:
            abort(404)
        session.delete(memory)

    flash("Memory deleted.", "success")
    return redirect(next_url)


@bp.get("/scripts/new")
def new_script():
    return render_template(
        "script_new.html",
        script_types=SCRIPT_TYPE_CHOICES,
        page_title="Create Script",
        active_page="scripts",
    )


@bp.post("/scripts")
def create_script():
    file_name = request.form.get("file_name", "").strip()
    description = request.form.get("description", "").strip()
    script_type = request.form.get("script_type", "").strip()
    content = request.form.get("content", "")
    uploaded_file = request.files.get("script_file")

    if uploaded_file and uploaded_file.filename:
        file_name = file_name or uploaded_file.filename
        content_bytes = uploaded_file.read()
        content = content_bytes.decode("utf-8", errors="replace")

    file_name = Path(file_name).name if file_name else ""
    if not file_name or file_name in {".", ".."}:
        flash("File name is required.", "error")
        return redirect(url_for("agents.new_script"))
    if script_type not in SCRIPT_TYPE_LABELS:
        flash("Select a valid script type.", "error")
        return redirect(url_for("agents.new_script"))
    if not content or not content.strip():
        flash("Script content is required.", "error")
        return redirect(url_for("agents.new_script"))

    try:
        with session_scope() as session:
            script = Script.create(
                session,
                file_name=file_name,
                description=description or None,
                content=content,
                script_type=script_type,
            )
            path = write_script_file(script.id, file_name, content)
            script.file_path = str(path)
    except OSError:
        logger.exception("Failed to write script %s to disk", file_name)
        flash("Failed to write the script file.", "error")
        return redirect(url_for("agents.new_script"))

    flash(f"Script {script.id} created.", "success")
    return redirect(url_for("agents.view_script", script_id=script.id))


@bp.get("/scripts/<int:script_id>")
def view_script(script_id: int):
    with session_scope() as session:
        script = (
            session.execute(
                select(Script)
                .options(selectinload(Script.agents))
                .where(Script.id == script_id)
            )
            .scalars()
            .first()
        )
        if script is None:
            abort(404)
        attached_agents = list(script.agents)
        script_content = _read_script_content(script)
    return render_template(
        "script_detail.html",
        script=script,
        script_content=script_content,
        attached_agents=attached_agents,
        human_time=_human_time,
        page_title=f"Script - {script.file_name}",
        active_page="scripts",
    )


@bp.get("/scripts/<int:script_id>/edit")
def edit_script(script_id: int):
    with session_scope() as session:
        script = session.get(Script, script_id)
        if script is None:
            abort(404)
        script_content = _read_script_content(script)
    return render_template(
        "script_edit.html",
        script=script,
        script_content=script_content,
        script_types=SCRIPT_TYPE_CHOICES,
        page_title=f"Edit Script - {script.file_name}",
        active_page="scripts",
    )


@bp.post("/scripts/<int:script_id>")
def update_script(script_id: int):
    file_name = request.form.get("file_name", "").strip()
    description = request.form.get("description", "").strip()
    script_type = request.form.get("script_type", "").strip()
    content = request.form.get("content", "")
    uploaded_file = request.files.get("script_file")

    if uploaded_file and uploaded_file.filename:
        file_name = file_name or uploaded_file.filename
        content_bytes = uploaded_file.read()
        content = content_bytes.decode("utf-8", errors="replace")

    try:
        with session_scope() as session:
            script = session.get(Script, script_id)
            if script is None:
                abort(404)
            if not file_name:
                file_name = script.file_name
            file_name = Path(file_name).name if file_name else ""
            if not file_name or file_name in {".", ".."}:
                flash("File name is required.", "error")
                return redirect(url_for("agents.edit_script", script_id=script_id))
            if script_type not in SCRIPT_TYPE_LABELS:
                flash("Select a valid script type.", "error")
                return redirect(url_for("agents.edit_script", script_id=script_id))
            if not content or not content.strip():
                flash("Script content is required.", "error")
                return redirect(url_for("agents.edit_script", script_id=script_id))
            old_path = script.file_path
            script.file_name = file_name
            script.description = description or None
            script.content = content
            script.script_type = script_type
            path = write_script_file(script.id, file_name, content)
            script.file_path = str(path)
            if old_path and old_path != script.file_path:
                remove_script_file(old_path)
    except OSError:
        logger.exception("Failed to write script %s to disk", script_id)
        flash("Failed to write the script file.", "error")
        return redirect(url_for("agents.edit_script", script_id=script_id))

    flash("Script updated.", "success")
    return redirect(url_for("agents.view_script", script_id=script_id))


@bp.post("/scripts/<int:script_id>/delete")
def delete_script(script_id: int):
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_scripts")
    )
    with session_scope() as session:
        script = session.get(Script, script_id)
        if script is None:
            abort(404)
        script_path = script.file_path
        attached_agents = list(script.agents)
        if attached_agents:
            script.agents = []
        session.delete(script)

    flash("Script deleted.", "success")
    if attached_agents:
        flash(f"Detached from {len(attached_agents)} agent(s).", "info")
    remove_script_file(script_path)
    return redirect(next_url)


@bp.get("/github")
def github_workspace():
    settings = _load_integration_settings("github")
    repo = settings.get("repo") or "No repository selected"
    pat = settings.get("pat") or ""
    tab = request.args.get("tab", "pulls").strip().lower()
    if tab not in {"pulls", "actions", "code"}:
        tab = "pulls"
    pr_status = request.args.get("pr_status", "open").strip().lower()
    if pr_status not in {"all", "open", "closed", "merged", "draft"}:
        pr_status = "open"
    pr_author_raw = (request.args.get("pr_author") or "all").strip()
    pr_author = "all"
    code_path = request.args.get("path", "").strip().lstrip("/")
    pull_requests: list[dict[str, object]] = []
    pr_error = None
    pr_authors: list[str] = []
    actions: list[dict[str, str]] = []
    actions_error = None
    code_entries: list[dict[str, str]] = []
    code_file = None
    code_error = None
    code_parent = ""
    code_selected_path = ""
    if pat and settings.get("repo"):
        repo_name = settings.get("repo", "")
        try:
            pull_requests = _fetch_github_pull_requests(pat, repo_name, pr_status)
        except ValueError as exc:
            pr_error = str(exc)
        if pull_requests:
            authors = {
                pr.get("author") for pr in pull_requests if pr.get("author")
            }
            pr_authors = sorted(authors, key=lambda value: value.lower())
            if pr_author_raw and pr_author_raw.lower() != "all":
                selected_author = None
                for author in pr_authors:
                    if author.lower() == pr_author_raw.lower():
                        selected_author = author
                        break
                if selected_author:
                    pull_requests = [
                        pr
                        for pr in pull_requests
                        if (pr.get("author") or "").lower()
                        == selected_author.lower()
                    ]
                    pr_author = selected_author
        try:
            actions = _fetch_github_actions(pat, repo_name)
        except ValueError as exc:
            actions_error = str(exc)
        try:
            contents = _fetch_github_contents(pat, repo_name, code_path)
            code_entries = contents.get("entries", [])
            code_file = contents.get("file")
            if code_path:
                code_parent = "/".join(code_path.split("/")[:-1])
            if isinstance(code_file, dict):
                code_selected_path = code_file.get("path", "")
            if code_file and code_path:
                try:
                    parent_contents = _fetch_github_contents(pat, repo_name, code_parent)
                    code_entries = parent_contents.get("entries", [])
                except ValueError:
                    pass
        except ValueError as exc:
            code_error = str(exc)
    return render_template(
        "github.html",
        github_repo=repo,
        github_repo_selected=bool(settings.get("repo")),
        github_connected=bool(settings.get("pat")),
        github_pull_requests=pull_requests,
        github_pr_error=pr_error,
        github_pr_status=pr_status,
        github_pr_author=pr_author,
        github_pr_authors=pr_authors,
        github_actions=actions,
        github_actions_error=actions_error,
        github_code_entries=code_entries,
        github_code_file=code_file,
        github_code_error=code_error,
        github_code_path=code_path,
        github_code_parent=code_parent,
        github_code_selected_path=code_selected_path,
        github_active_tab=tab,
        page_title="GitHub",
        active_page="github",
    )


def _render_github_pull_request_page(pr_number: int, active_tab: str):
    settings = _load_integration_settings("github")
    repo = settings.get("repo") or ""
    pat = settings.get("pat") or ""
    if not repo or not pat:
        flash(
            "GitHub repository and PAT are required to view pull requests.",
            "error",
        )
        return redirect(url_for("agents.github_workspace", tab="pulls"))
    tab_labels = {
        "conversation": "Conversation",
        "commits": "Commits",
        "checks": "Checks",
        "files": "Files changed",
    }
    selected_tab = active_tab if active_tab in tab_labels else "conversation"
    pr_error = None
    comments_error = None
    pull_request: dict[str, object] = {}
    comments: list[dict[str, object]] = []
    reviewers: list[str] = []
    try:
        pull_request = _fetch_github_pull_request_detail(pat, repo, pr_number)
    except ValueError as exc:
        pr_error = str(exc)
    if pull_request:
        try:
            comments, reviewer_logins = _fetch_github_pull_request_timeline(
                pat, repo, pr_number
            )
            reviewers = sorted(
                set(pull_request.get("requested_reviewers", []))
                | set(reviewer_logins)
            )
        except ValueError as exc:
            comments_error = str(exc)
            reviewers = pull_request.get("requested_reviewers", [])
    base_title = (
        f"PR #{pr_number} - {pull_request.get('title')}"
        if pull_request.get("title")
        else f"PR #{pr_number}"
    )
    page_title = f"{base_title} - {tab_labels[selected_tab]}"
    return render_template(
        "github_pull_request.html",
        github_repo=repo or "No repository selected",
        github_connected=bool(pat),
        github_pr=pull_request,
        github_pr_number=pr_number,
        github_pr_comments=comments,
        github_pr_reviewers=reviewers,
        github_pr_active_tab=selected_tab,
        github_pr_error=pr_error,
        github_pr_comments_error=comments_error,
        page_title=page_title,
        active_page="github",
    )


@bp.get("/github/pulls/<int:pr_number>")
def github_pull_request(pr_number: int):
    return _render_github_pull_request_page(pr_number, "conversation")


@bp.get("/github/pulls/<int:pr_number>/commits")
def github_pull_request_commits(pr_number: int):
    return _render_github_pull_request_page(pr_number, "commits")


@bp.get("/github/pulls/<int:pr_number>/checks")
def github_pull_request_checks(pr_number: int):
    return _render_github_pull_request_page(pr_number, "checks")


@bp.get("/github/pulls/<int:pr_number>/files")
def github_pull_request_files(pr_number: int):
    return _render_github_pull_request_page(pr_number, "files")


@bp.post("/github/pulls/<int:pr_number>/code-review")
def github_pull_request_code_review(pr_number: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"),
        url_for("agents.github_pull_request", pr_number=pr_number),
    )
    settings = _load_integration_settings("github")
    repo = settings.get("repo") or ""
    pat = settings.get("pat") or ""
    if not repo or not pat:
        flash(
            "GitHub repository and PAT are required to run code reviews.",
            "error",
        )
        return redirect(redirect_target)

    pr_title = request.form.get("pr_title", "").strip() or None
    pr_url = request.form.get("pr_url", "").strip() or None
    if not pr_url and repo:
        pr_url = f"https://github.com/{repo}/pull/{pr_number}"

    with session_scope() as session:
        role = ensure_code_reviewer_role(session)
        agent = ensure_code_reviewer_agent(session, role)
        prompt = _build_github_code_review_prompt(
            repo=repo,
            pr_number=pr_number,
            pr_title=pr_title,
            pr_url=pr_url,
            role_prompt=role.description if role is not None else None,
        )
        task = AgentTask.create(
            session,
            agent_id=agent.id,
            status="queued",
            prompt=prompt,
            kind=CODE_REVIEW_TASK_KIND,
        )
        task_id = task.id

    celery_task = run_agent_task.delay(task_id)

    with session_scope() as session:
        task = session.get(AgentTask, task_id)
        if task is not None:
            task.celery_task_id = celery_task.id

    flash(f"Code review task {task_id} queued.", "success")
    return redirect(url_for("agents.view_task", task_id=task_id))


@bp.get("/jira")
def jira_workspace():
    settings = _load_integration_settings("jira")
    board = settings.get("board") or "No board selected"
    site = settings.get("site") or "No site configured"
    api_key = settings.get("api_key") or ""
    email = settings.get("email") or ""
    board_columns: list[dict[str, object]] = []
    board_unmapped: list[dict[str, object]] = []
    board_error: str | None = None
    board_issue_total: int | None = None
    board_type: str | None = None
    board_url: str | None = None
    board_column_count = 0
    if api_key and settings.get("board") and settings.get("site"):
        auth_key = _combine_atlassian_key(api_key, email)
        if ":" not in auth_key:
            board_error = (
                "Jira API key needs an Atlassian email. Enter it in settings."
            )
        else:
            try:
                board_info = _fetch_jira_board_by_name(
                    auth_key, settings.get("site") or "", settings.get("board") or ""
                )
                if not board_info:
                    board_error = (
                        "Selected Jira board not found. Refresh boards in settings."
                    )
                else:
                    board_id = board_info.get("id")
                    if isinstance(board_id, str) and board_id.isdigit():
                        board_id = int(board_id)
                    if isinstance(board_id, int):
                        board_type = board_info.get("type") or None
                        location = board_info.get("location", {})
                        if isinstance(location, dict):
                            project_key = location.get("projectKey")
                            base = _normalize_atlassian_site(settings.get("site") or "")
                            if (
                                isinstance(project_key, str)
                                and project_key
                                and base
                            ):
                                board_url = (
                                    f"{base}/jira/software/c/projects/"
                                    f"{project_key}/boards/{board_id}"
                                )
                        board_config = _fetch_jira_board_configuration(
                            auth_key, settings.get("site") or "", board_id
                        )
                        issues = _fetch_jira_board_issues(
                            auth_key, settings.get("site") or "", board_id
                        )
                        board_issue_total = len(issues)
                        board_columns, board_unmapped = _build_jira_board_columns(
                            board_config, issues
                        )
                        board_column_count = len(board_columns) + (
                            1 if board_unmapped else 0
                        )
                        if not board_columns:
                            board_error = "No columns returned for this board."
                    else:
                        board_error = "Selected Jira board is missing an id."
            except ValueError as exc:
                board_error = str(exc)
    return render_template(
        "jira.html",
        jira_board=board,
        jira_site=site,
        jira_board_selected=bool(settings.get("board")),
        jira_connected=bool(settings.get("api_key")),
        jira_board_columns=board_columns,
        jira_board_unmapped=board_unmapped,
        jira_board_error=board_error,
        jira_board_issue_total=board_issue_total,
        jira_board_type=board_type,
        jira_board_url=board_url,
        jira_board_column_count=board_column_count,
        page_title="Jira",
        active_page="jira",
    )


@bp.get("/jira/issues/<issue_key>")
def jira_issue_detail(issue_key: str):
    settings = _load_integration_settings("jira")
    board = settings.get("board") or "No board selected"
    site = settings.get("site") or "No site configured"
    api_key = settings.get("api_key") or ""
    email = settings.get("email") or ""
    issue: dict[str, object] = {"key": issue_key, "summary": "Jira issue"}
    issue_error: str | None = None
    comments_error: str | None = None
    comments: list[dict[str, object]] = []
    if not api_key or not settings.get("site"):
        issue_error = "Jira API key and site URL are required to load issues."
    else:
        auth_key = _combine_atlassian_key(api_key, email)
        if ":" not in auth_key:
            issue_error = (
                "Jira API key needs an Atlassian email. Enter it in settings."
            )
        else:
            try:
                fetched_issue = _fetch_jira_issue(
                    auth_key, settings.get("site") or "", issue_key
                )
                if not fetched_issue:
                    issue_error = "Issue not found or access denied."
                else:
                    issue = fetched_issue
                    try:
                        comments = _fetch_jira_issue_comments(
                            auth_key, settings.get("site") or "", issue_key
                        )
                    except ValueError as exc:
                        comments_error = str(exc)
            except ValueError as exc:
                issue_error = str(exc)
    page_title = (
        f"{issue.get('key')} - {issue.get('summary')}"
        if issue
        else f"{issue_key} - Jira"
    )
    return render_template(
        "jira_issue.html",
        jira_board=board,
        jira_site=site,
        jira_issue=issue,
        jira_issue_error=issue_error,
        jira_comments=comments,
        jira_comments_error=comments_error,
        page_title=page_title,
        active_page="jira",
    )


@bp.get("/confluence")
def confluence_workspace():
    settings = _load_integration_settings("confluence")
    space = settings.get("space") or "No space selected"
    site = settings.get("site") or "No site configured"
    return render_template(
        "confluence.html",
        confluence_space=space,
        confluence_site=site,
        confluence_space_selected=bool(settings.get("space")),
        confluence_connected=bool(settings.get("api_key")),
        page_title="Confluence",
        active_page="confluence",
    )


@bp.post("/task-templates")
def create_task_template():
    name = request.form.get("name", "").strip()
    prompt = request.form.get("prompt", "").strip()
    description = request.form.get("description", "").strip()
    agent_id_raw = request.form.get("agent_id", "").strip()
    uploads = request.files.getlist("attachments")
    agent_id: int | None = None
    if agent_id_raw:
        if not agent_id_raw.isdigit():
            flash("Select a valid agent.", "error")
            return redirect(url_for("agents.new_task_template"))
        agent_id = int(agent_id_raw)
    if not name or not prompt:
        flash("Template name and prompt are required.", "error")
        return redirect(url_for("agents.new_task_template"))
    try:
        with session_scope() as session:
            if agent_id is not None:
                agent = session.get(Agent, agent_id)
                if agent is None:
                    flash("Agent not found.", "error")
                    return redirect(url_for("agents.new_task_template"))
            template = TaskTemplate.create(
                session,
                name=name,
                prompt=prompt,
                description=description or None,
                agent_id=agent_id,
            )
            attachments = _save_uploaded_attachments(session, uploads)
            _attach_attachments(template, attachments)
            template_id = template.id
    except (OSError, ValueError) as exc:
        logger.exception("Failed to save template attachments")
        flash(str(exc) or "Failed to save attachments.", "error")
        return redirect(url_for("agents.new_task_template"))
    flash("Template created.", "success")
    return redirect(url_for("agents.view_task_template", template_id=template_id))


@bp.post("/task-templates/<int:template_id>")
def update_task_template(template_id: int):
    name = request.form.get("name", "").strip()
    prompt = request.form.get("prompt", "").strip()
    description = request.form.get("description", "").strip()
    agent_id_raw = request.form.get("agent_id", "").strip()
    uploads = request.files.getlist("attachments")
    agent_id: int | None = None
    if agent_id_raw:
        if not agent_id_raw.isdigit():
            flash("Select a valid agent.", "error")
            return redirect(url_for("agents.edit_task_template", template_id=template_id))
        agent_id = int(agent_id_raw)
    if not name or not prompt:
        flash("Template name and prompt are required.", "error")
        return redirect(url_for("agents.edit_task_template", template_id=template_id))
    try:
        with session_scope() as session:
            template = session.get(TaskTemplate, template_id)
            if template is None:
                abort(404)
            if agent_id is not None:
                agent = session.get(Agent, agent_id)
                if agent is None:
                    flash("Agent not found.", "error")
                    return redirect(
                        url_for("agents.edit_task_template", template_id=template_id)
                    )
            template.name = name
            template.prompt = prompt
            template.description = description or None
            template.agent_id = agent_id
            attachments = _save_uploaded_attachments(session, uploads)
            _attach_attachments(template, attachments)
    except (OSError, ValueError) as exc:
        logger.exception("Failed to save template attachments")
        flash(str(exc) or "Failed to save attachments.", "error")
        return redirect(url_for("agents.edit_task_template", template_id=template_id))
    flash("Template updated.", "success")
    return redirect(url_for("agents.view_task_template", template_id=template_id))


@bp.post("/task-templates/<int:template_id>/attachments/<int:attachment_id>/remove")
def remove_task_template_attachment(template_id: int, attachment_id: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"),
        url_for("agents.edit_task_template", template_id=template_id),
    )
    removed_path: str | None = None
    with session_scope() as session:
        template = (
            session.execute(
                select(TaskTemplate)
                .options(selectinload(TaskTemplate.attachments))
                .where(TaskTemplate.id == template_id)
            )
            .scalars()
            .first()
        )
        if template is None:
            abort(404)
        attachment = next(
            (item for item in template.attachments if item.id == attachment_id), None
        )
        if attachment is None:
            flash("Attachment not found on this template.", "error")
            return redirect(redirect_target)
        template.attachments.remove(attachment)
        session.flush()
        removed_path = _delete_attachment_if_unused(session, attachment)
    if removed_path:
        remove_attachment_file(removed_path)
    flash("Attachment removed.", "success")
    return redirect(redirect_target)


@bp.post("/task-templates/<int:template_id>/delete")
def delete_task_template(template_id: int):
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_task_templates")
    )
    with session_scope() as session:
        template = session.get(TaskTemplate, template_id)
        if template is None:
            abort(404)
        steps = (
            session.execute(
                select(PipelineStep).where(
                    PipelineStep.task_template_id == template_id
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
                select(AgentTask).where(AgentTask.task_template_id == template_id)
            )
            .scalars()
            .all()
        )
        for task in tasks_with_template:
            task.task_template_id = None
        for step in steps:
            session.delete(step)
        session.delete(template)
    flash("Template deleted.", "success")
    return redirect(next_url)


@bp.post("/pipelines")
def create_pipeline():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    if not name:
        flash("Pipeline name is required.", "error")
        return redirect(url_for("agents.new_pipeline"))
    with session_scope() as session:
        Pipeline.create(
            session,
            name=name,
            description=description or None,
        )
    flash("Pipeline created.", "success")
    return redirect(url_for("agents.list_pipelines"))


@bp.post("/pipelines/<int:pipeline_id>")
def update_pipeline(pipeline_id: int):
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    if not name:
        flash("Pipeline name is required.", "error")
        return redirect(url_for("agents.edit_pipeline", pipeline_id=pipeline_id))
    redirect_target = _safe_redirect_target(
        request.form.get("next"),
        url_for("agents.view_pipeline", pipeline_id=pipeline_id),
    )
    with session_scope() as session:
        pipeline = session.get(Pipeline, pipeline_id)
        if pipeline is None:
            abort(404)
        pipeline.name = name
        pipeline.description = description or None
    flash("Pipeline updated.", "success")
    return redirect(redirect_target)


@bp.post("/pipelines/<int:pipeline_id>/delete")
def delete_pipeline(pipeline_id: int):
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_pipelines")
    )
    with session_scope() as session:
        pipeline = session.get(Pipeline, pipeline_id)
        if pipeline is None:
            abort(404)
        steps = (
            session.execute(
                select(PipelineStep).where(PipelineStep.pipeline_id == pipeline_id)
            )
            .scalars()
            .all()
        )
        runs = (
            session.execute(
                select(PipelineRun).where(PipelineRun.pipeline_id == pipeline_id)
            )
            .scalars()
            .all()
        )
        step_ids = [step.id for step in steps]
        run_ids = [run.id for run in runs]
        task_ids = set(
            session.execute(
                select(AgentTask.id).where(AgentTask.pipeline_id == pipeline_id)
            )
            .scalars()
            .all()
        )
        if step_ids:
            task_ids.update(
                session.execute(
                    select(AgentTask.id).where(
                        AgentTask.pipeline_step_id.in_(step_ids)
                    )
                )
                .scalars()
                .all()
            )
        if run_ids:
            task_ids.update(
                session.execute(
                    select(AgentTask.id).where(
                        AgentTask.pipeline_run_id.in_(run_ids)
                    )
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
    flash("Pipeline deleted.", "success")
    return redirect(next_url)


@bp.post("/pipelines/<int:pipeline_id>/steps")
def add_pipeline_step(pipeline_id: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_pipelines")
    )
    template_id = request.form.get("template_id", "").strip()
    additional_prompt = request.form.get("additional_prompt", "").strip()
    step_order_raw = request.form.get("step_order", "").strip()
    uploads = request.files.getlist("attachments")
    if not template_id:
        flash("Select a template.", "error")
        return redirect(redirect_target)
    try:
        with session_scope() as session:
            pipeline = session.get(Pipeline, pipeline_id)
            if pipeline is None:
                flash("Pipeline not found.", "error")
                return redirect(url_for("agents.list_pipelines"))
            template = session.get(TaskTemplate, int(template_id))
            if template is None:
                flash("Template not found.", "error")
                return redirect(redirect_target)
            if template.agent_id is None:
                flash("Template must have an agent assigned.", "error")
                return redirect(redirect_target)
            if step_order_raw:
                step_order = int(step_order_raw)
            else:
                step_order = (
                    session.execute(
                        select(func.max(PipelineStep.step_order)).where(
                            PipelineStep.pipeline_id == pipeline_id
                        )
                    ).scalar_one()
                    or 0
                )
                step_order += 1
            step = PipelineStep.create(
                session,
                pipeline_id=pipeline_id,
                task_template_id=template.id,
                step_order=step_order,
                additional_prompt=additional_prompt or None,
            )
            attachments = _save_uploaded_attachments(session, uploads)
            _attach_attachments(step, attachments)
    except (OSError, ValueError) as exc:
        logger.exception("Failed to save pipeline step attachments")
        flash(str(exc) or "Failed to save attachments.", "error")
        return redirect(redirect_target)
    flash("Pipeline step added.", "success")
    return redirect(redirect_target)


@bp.post("/pipelines/<int:pipeline_id>/steps/<int:step_id>/prompt")
def update_pipeline_step_prompt(pipeline_id: int, step_id: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"),
        url_for("agents.view_pipeline", pipeline_id=pipeline_id),
    )
    additional_prompt = request.form.get("additional_prompt", "").strip()
    uploads = request.files.getlist("attachments")
    try:
        with session_scope() as session:
            step = session.get(PipelineStep, step_id)
            if step is None or step.pipeline_id != pipeline_id:
                abort(404)
            step.additional_prompt = additional_prompt or None
            attachments = _save_uploaded_attachments(session, uploads)
            _attach_attachments(step, attachments)
    except (OSError, ValueError) as exc:
        logger.exception("Failed to save pipeline step attachments")
        flash(str(exc) or "Failed to save attachments.", "error")
        return redirect(redirect_target)
    flash("Pipeline step prompt updated.", "success")
    return redirect(redirect_target)


@bp.post(
    "/pipelines/<int:pipeline_id>/steps/<int:step_id>/attachments/<int:attachment_id>/remove"
)
def remove_pipeline_step_attachment(
    pipeline_id: int, step_id: int, attachment_id: int
):
    redirect_target = _safe_redirect_target(
        request.form.get("next"),
        url_for("agents.view_pipeline", pipeline_id=pipeline_id),
    )
    removed_path: str | None = None
    with session_scope() as session:
        step = (
            session.execute(
                select(PipelineStep)
                .options(selectinload(PipelineStep.attachments))
                .where(PipelineStep.id == step_id)
            )
            .scalars()
            .first()
        )
        if step is None or step.pipeline_id != pipeline_id:
            abort(404)
        attachment = next(
            (item for item in step.attachments if item.id == attachment_id), None
        )
        if attachment is None:
            flash("Attachment not found on this step.", "error")
            return redirect(redirect_target)
        step.attachments.remove(attachment)
        session.flush()
        removed_path = _delete_attachment_if_unused(session, attachment)
    if removed_path:
        remove_attachment_file(removed_path)
    flash("Attachment removed.", "success")
    return redirect(redirect_target)


@bp.post("/pipelines/<int:pipeline_id>/steps/<int:step_id>/delete")
def delete_pipeline_step(pipeline_id: int, step_id: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"),
        url_for("agents.view_pipeline", pipeline_id=pipeline_id),
    )
    with session_scope() as session:
        step = session.get(PipelineStep, step_id)
        if step is None or step.pipeline_id != pipeline_id:
            abort(404)
        tasks = (
            session.execute(
                select(AgentTask).where(AgentTask.pipeline_step_id == step_id)
            )
            .scalars()
            .all()
        )
        for task in tasks:
            task.pipeline_step_id = None
        session.delete(step)
    flash("Pipeline step deleted.", "success")
    return redirect(redirect_target)


def _move_pipeline_step(pipeline_id: int, step_id: int, direction: str):
    redirect_target = _safe_redirect_target(
        request.form.get("next"),
        url_for("agents.view_pipeline", pipeline_id=pipeline_id),
    )
    with session_scope() as session:
        steps = (
            session.execute(
                select(PipelineStep)
                .where(PipelineStep.pipeline_id == pipeline_id)
                .order_by(PipelineStep.step_order.asc(), PipelineStep.id.asc())
            )
            .scalars()
            .all()
        )
        step_index = next(
            (index for index, step in enumerate(steps) if step.id == step_id),
            None,
        )
        if step_index is None:
            abort(404)
        offset = -1 if direction == "up" else 1
        target_index = step_index + offset
        if target_index < 0:
            flash("Pipeline step is already first.", "error")
            return redirect(redirect_target)
        if target_index >= len(steps):
            flash("Pipeline step is already last.", "error")
            return redirect(redirect_target)
        steps[step_index], steps[target_index] = (
            steps[target_index],
            steps[step_index],
        )
        for index, step in enumerate(steps, start=1):
            step.step_order = index
    flash("Pipeline step moved.", "success")
    return redirect(redirect_target)


@bp.post("/pipelines/<int:pipeline_id>/steps/<int:step_id>/move-up")
def move_pipeline_step_up(pipeline_id: int, step_id: int):
    return _move_pipeline_step(pipeline_id, step_id, "up")


@bp.post("/pipelines/<int:pipeline_id>/steps/<int:step_id>/move-down")
def move_pipeline_step_down(pipeline_id: int, step_id: int):
    return _move_pipeline_step(pipeline_id, step_id, "down")


@bp.post("/pipelines/<int:pipeline_id>/loop")
def toggle_pipeline_loop(pipeline_id: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"),
        url_for("agents.view_pipeline", pipeline_id=pipeline_id),
    )
    requested = (request.form.get("loop_enabled") or "").strip().lower()
    with session_scope() as session:
        pipeline = session.get(Pipeline, pipeline_id)
        if pipeline is None:
            abort(404)
        if requested:
            pipeline.loop_enabled = requested in {"1", "true", "yes", "on"}
        else:
            pipeline.loop_enabled = not bool(pipeline.loop_enabled)
        loop_enabled = pipeline.loop_enabled
    flash(
        f"Pipeline loop {'enabled' if loop_enabled else 'disabled'}.",
        "success",
    )
    return redirect(redirect_target)


@bp.post("/pipelines/<int:pipeline_id>/run")
def start_pipeline(pipeline_id: int):
    with session_scope() as session:
        pipeline = session.get(Pipeline, pipeline_id)
        if pipeline is None:
            flash("Pipeline not found.", "error")
            return redirect(url_for("agents.list_pipelines"))
        run = PipelineRun.create(
            session,
            pipeline_id=pipeline_id,
            status="queued",
        )
        run_id = run.id
    run_pipeline.delay(pipeline_id, run_id)
    flash("Pipeline started.", "success")
    return redirect(url_for("agents.view_pipeline_run", run_id=run_id))


@bp.get("/settings")
def settings():
    summary = _settings_summary()
    integration_overview = _integration_overview()
    llm_settings = _load_integration_settings("llm")
    enabled_providers = resolve_enabled_llm_providers(llm_settings)
    provider_overview = _provider_summary(
        settings=llm_settings, enabled_providers=enabled_providers
    )
    default_model_summary = _default_model_overview(llm_settings)
    gitconfig_path = _gitconfig_path()
    gitconfig_overview = {
        "path": str(gitconfig_path),
        "exists": gitconfig_path.exists(),
    }
    core_overview = {
        "DATA_DIR": Config.DATA_DIR,
        "DATABASE_FILENAME": Config.DATABASE_FILENAME,
        "CODEX_MODEL": Config.CODEX_MODEL or "default",
    }
    celery_overview = {
        "CELERY_BROKER_URL": Config.CELERY_BROKER_URL,
        "CELERY_RESULT_BACKEND": Config.CELERY_RESULT_BACKEND,
    }
    runtime_overview = {
        "AGENT_POLL_SECONDS": Config.AGENT_POLL_SECONDS,
        "CELERY_REVOKE_ON_STOP": (
            "enabled" if Config.CELERY_REVOKE_ON_STOP else "disabled"
        ),
    }
    return render_template(
        "settings.html",
        core_overview=core_overview,
        celery_overview=celery_overview,
        runtime_overview=runtime_overview,
        integration_overview=integration_overview,
        provider_overview=provider_overview,
        default_model_summary=default_model_summary,
        gitconfig_overview=gitconfig_overview,
        summary=summary,
        page_title="Settings",
        active_page="settings",
        settings_title="Settings",
        settings_subtitle="Choose a section to configure.",
        settings_section="overview",
    )


@bp.get("/settings/roles")
@bp.get("/roles")
def list_roles():
    page = _parse_page(request.args.get("page"))
    per_page = _parse_page_size(request.args.get("per_page"))
    with session_scope() as session:
        total_count = session.execute(select(func.count(Role.id))).scalar_one()
        pagination = _build_pagination(request.path, page, per_page, total_count)
        offset = (pagination["page"] - 1) * per_page
        roles = (
            session.execute(
                select(Role)
                .order_by(Role.created_at.desc())
                .limit(per_page)
                .offset(offset)
            )
            .scalars()
            .all()
        )
    return render_template(
        "roles.html",
        roles=roles,
        pagination=pagination,
        human_time=_human_time,
        page_title="Roles",
        active_page="roles",
    )


@bp.get("/settings/roles/new")
@bp.get("/roles/new")
def new_role():
    return render_template(
        "role_new.html",
        page_title="Create Role",
        active_page="roles",
    )


@bp.get("/settings/roles/<int:role_id>")
@bp.get("/roles/<int:role_id>")
def view_role(role_id: int):
    with session_scope() as session:
        role = session.get(Role, role_id)
        if role is None:
            abort(404)
    return render_template(
        "role_detail.html",
        role=role,
        human_time=_human_time,
        page_title=f"Role - {role.name}",
        active_page="roles",
    )


@bp.get("/settings/roles/<int:role_id>/edit")
@bp.get("/roles/<int:role_id>/edit")
def edit_role(role_id: int):
    with session_scope() as session:
        role = session.get(Role, role_id)
        if role is None:
            abort(404)
    return render_template(
        "role_edit.html",
        role=role,
        page_title=f"Edit Role - {role.name}",
        active_page="roles",
    )


@bp.post("/settings/roles/<int:role_id>")
@bp.post("/roles/<int:role_id>")
def update_role(role_id: int):
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    raw_details = request.form.get("details_json", "").strip()

    if not description:
        flash("Role description is required.", "error")
        return redirect(url_for("agents.edit_role", role_id=role_id))

    try:
        formatted_details = _parse_role_details(raw_details)
    except json.JSONDecodeError as exc:
        flash(f"Invalid JSON: {exc.msg}", "error")
        return redirect(url_for("agents.edit_role", role_id=role_id))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("agents.edit_role", role_id=role_id))

    with session_scope() as session:
        role = session.get(Role, role_id)
        if role is None:
            abort(404)
        if not name:
            name = role.name or "Untitled Role"
        role.name = name
        role.description = description
        role.details_json = formatted_details

    flash("Role updated.", "success")
    return redirect(url_for("agents.view_role", role_id=role_id))


@bp.post("/settings/roles/<int:role_id>/delete")
@bp.post("/roles/<int:role_id>/delete")
def delete_role(role_id: int):
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_roles")
    )
    with session_scope() as session:
        role = session.get(Role, role_id)
        if role is None:
            abort(404)
        assigned_agents = (
            session.execute(
                select(Agent).where(Agent.role_id == role_id)
            )
            .scalars()
            .all()
        )
        for agent in assigned_agents:
            agent.role_id = None
        session.delete(role)

    flash("Role deleted.", "success")
    if assigned_agents:
        flash(
            f"Removed role from {len(assigned_agents)} agent(s).",
            "info",
        )
    return redirect(next_url)


@bp.get("/settings/core")
def settings_core():
    summary = _settings_summary()
    core_config = {
        "DATA_DIR": Config.DATA_DIR,
        "DATABASE_FILENAME": Config.DATABASE_FILENAME,
        "SQLALCHEMY_DATABASE_URI": Config.SQLALCHEMY_DATABASE_URI,
        "AGENT_POLL_SECONDS": Config.AGENT_POLL_SECONDS,
        "LLM_PROVIDER": resolve_llm_provider() or "not set",
        "CODEX_CMD": Config.CODEX_CMD,
        "CODEX_MODEL": Config.CODEX_MODEL or "default",
        "GEMINI_CMD": Config.GEMINI_CMD,
        "GEMINI_MODEL": Config.GEMINI_MODEL or "default",
        "CLAUDE_CMD": Config.CLAUDE_CMD,
        "CLAUDE_MODEL": Config.CLAUDE_MODEL or "default",
    }
    return render_template(
        "settings_core.html",
        core_config=core_config,
        summary=summary,
        page_title="Settings - Core",
        active_page="settings",
        settings_title="Settings",
        settings_subtitle="Core Configuration",
        settings_section="core",
    )


@bp.get("/settings/provider")
def settings_provider():
    summary = _settings_summary()
    llm_settings = _load_integration_settings("llm")
    enabled_providers = resolve_enabled_llm_providers(llm_settings)
    provider_summary = _provider_summary(
        settings=llm_settings, enabled_providers=enabled_providers
    )
    default_model_summary = _default_model_overview(llm_settings)
    codex_settings = _codex_settings_payload(llm_settings)
    gemini_settings = _gemini_settings_payload(llm_settings)
    claude_settings = _claude_settings_payload(llm_settings)
    provider_details = []
    for provider in LLM_PROVIDERS:
        provider_details.append(
            {
                "id": provider,
                "label": LLM_PROVIDER_LABELS.get(provider, provider),
                "command": _provider_command(provider),
                "model": _provider_model(provider, llm_settings),
                "enabled": provider in enabled_providers,
                "is_default": provider == provider_summary["provider"],
            }
        )
    return render_template(
        "settings_provider.html",
        provider_summary=provider_summary,
        provider_details=provider_details,
        default_model_summary=default_model_summary,
        codex_settings=codex_settings,
        gemini_settings=gemini_settings,
        claude_settings=claude_settings,
        summary=summary,
        page_title="Settings - Provider",
        active_page="settings",
        settings_title="Settings",
        settings_subtitle="Provider Defaults & Auth",
        settings_section="provider",
    )


@bp.post("/settings/provider")
def update_provider_settings():
    default_provider = (request.form.get("default_provider") or "").strip().lower()
    if default_provider and default_provider not in LLM_PROVIDERS:
        flash("Unknown provider selection.", "error")
        return redirect(url_for("agents.settings_provider"))
    enabled: set[str] = set()
    for provider in LLM_PROVIDERS:
        if _as_bool(request.form.get(f"provider_enabled_{provider}")):
            enabled.add(provider)
    if default_provider:
        enabled.add(default_provider)
    payload = {
        f"provider_enabled_{provider}": "true" if provider in enabled else ""
        for provider in LLM_PROVIDERS
    }
    payload["provider"] = default_provider if default_provider in enabled else ""
    _save_integration_settings("llm", payload)
    if not enabled:
        flash("No providers enabled. Agents require a default model or provider.", "info")
    flash("Provider settings updated.", "success")
    return redirect(url_for("agents.settings_provider"))


@bp.post("/settings/provider/codex")
def update_codex_settings():
    api_key = request.form.get("codex_api_key", "")
    payload = {
        "codex_api_key": api_key,
    }
    _save_integration_settings("llm", payload)
    flash("Codex auth settings updated.", "success")
    return redirect(url_for("agents.settings_provider"))


@bp.post("/settings/provider/gemini")
def update_gemini_settings():
    api_key = request.form.get("gemini_api_key", "")
    payload = {
        "gemini_api_key": api_key,
    }
    _save_integration_settings("llm", payload)
    flash("Gemini auth settings updated.", "success")
    return redirect(url_for("agents.settings_provider"))


@bp.post("/settings/provider/claude")
def update_claude_settings():
    api_key = request.form.get("claude_api_key", "")
    payload = {
        "claude_api_key": api_key,
    }
    _save_integration_settings("llm", payload)
    flash("Claude auth settings updated.", "success")
    return redirect(url_for("agents.settings_provider"))


@bp.get("/settings/celery")
def settings_celery():
    summary = _settings_summary()
    celery_config = {
        "CELERY_BROKER_URL": Config.CELERY_BROKER_URL,
        "CELERY_RESULT_BACKEND": Config.CELERY_RESULT_BACKEND,
        "CELERY_REVOKE_ON_STOP": Config.CELERY_REVOKE_ON_STOP,
    }
    broker_options = Config.CELERY_BROKER_TRANSPORT_OPTIONS or {}
    return render_template(
        "settings_celery.html",
        celery_config=celery_config,
        broker_options=broker_options,
        summary=summary,
        page_title="Settings - Celery",
        active_page="settings",
        settings_title="Settings",
        settings_subtitle="Celery Configuration",
        settings_section="celery",
    )


@bp.get("/settings/runtime")
def settings_runtime():
    summary = _settings_summary()
    config = {
        "AGENT_POLL_SECONDS": Config.AGENT_POLL_SECONDS,
        "CELERY_REVOKE_ON_STOP": Config.CELERY_REVOKE_ON_STOP,
    }
    llm_settings = _load_integration_settings("llm")
    enabled_providers = resolve_enabled_llm_providers(llm_settings)
    llm_config = _provider_summary(
        settings=llm_settings, enabled_providers=enabled_providers
    )
    return render_template(
        "settings_runtime.html",
        config=config,
        llm_config=llm_config,
        summary=summary,
        page_title="Settings - Runtime",
        active_page="settings",
        settings_title="Settings",
        settings_subtitle="Runtime Hints",
        settings_section="runtime",
    )


@bp.get("/settings/gitconfig")
def settings_gitconfig():
    summary = _settings_summary()
    gitconfig_path = _gitconfig_path()
    gitconfig_content = ""
    gitconfig_exists = gitconfig_path.exists()
    if gitconfig_exists:
        try:
            gitconfig_content = gitconfig_path.read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError as exc:
            flash(f"Unable to read {gitconfig_path}: {exc}", "error")
    return render_template(
        "settings_gitconfig.html",
        gitconfig_content=gitconfig_content,
        gitconfig_exists=gitconfig_exists,
        gitconfig_path=str(gitconfig_path),
        summary=summary,
        page_title="Settings - GitConfig",
        active_page="settings",
        settings_title="Settings",
        settings_subtitle="Git Config",
        settings_section="gitconfig",
    )


@bp.post("/settings/gitconfig")
def update_gitconfig():
    gitconfig_path = _gitconfig_path()
    gitconfig_content = request.form.get("gitconfig_content", "")
    try:
        gitconfig_path.write_text(gitconfig_content, encoding="utf-8")
    except OSError as exc:
        summary = _settings_summary()
        flash(f"Unable to write {gitconfig_path}: {exc}", "error")
        return render_template(
            "settings_gitconfig.html",
            gitconfig_content=gitconfig_content,
            gitconfig_exists=gitconfig_path.exists(),
            gitconfig_path=str(gitconfig_path),
            summary=summary,
            page_title="Settings - GitConfig",
            active_page="settings",
            settings_title="Settings",
            settings_subtitle="Git Config",
            settings_section="gitconfig",
        )
    flash("Git config saved.", "success")
    return redirect(url_for("agents.settings_gitconfig"))


@bp.get("/settings/integrations")
def settings_integrations():
    summary = _settings_summary()
    github_settings = _load_integration_settings("github")
    jira_settings = _load_integration_settings("jira")
    confluence_settings = _load_integration_settings("confluence")
    github_repo_options: list[str] = []
    selected_repo = github_settings.get("repo")
    if selected_repo:
        github_repo_options = [selected_repo]
    jira_project_options: list[dict[str, str]] = []
    selected_project = jira_settings.get("project_key")
    if selected_project:
        jira_project_options = [
            {"value": selected_project, "label": selected_project}
        ]
    jira_board_options: list[dict[str, str]] = []
    selected_board = jira_settings.get("board")
    if selected_board:
        jira_board_options = [{"value": selected_board, "label": selected_board}]
    confluence_space_options: list[dict[str, str]] = []
    selected_space = confluence_settings.get("space")
    if selected_space:
        confluence_space_options = [{"value": selected_space, "label": selected_space}]
    return render_template(
        "settings_integrations.html",
        github_settings=github_settings,
        jira_settings=jira_settings,
        confluence_settings=confluence_settings,
        github_repo_options=github_repo_options,
        jira_project_options=jira_project_options,
        jira_board_options=jira_board_options,
        confluence_space_options=confluence_space_options,
        github_connected=bool(
            (github_settings.get("pat") or "").strip()
            or (github_settings.get("ssh_key_path") or "").strip()
        ),
        jira_connected=bool(jira_settings.get("api_key")),
        confluence_connected=bool(confluence_settings.get("api_key")),
        summary=summary,
        page_title="Settings - Integrations",
        active_page="settings",
        settings_title="Settings",
        settings_subtitle="Integrations",
        settings_section="integrations",
    )


@bp.post("/settings/integrations/github")
def update_github_settings():
    action = request.form.get("action", "").strip()
    pat = request.form.get("github_pat", "").strip()
    current_settings = _load_integration_settings("github")
    existing_key_path = (current_settings.get("ssh_key_path") or "").strip()
    uploaded_key = request.files.get("github_ssh_key")
    clear_key = request.form.get("github_ssh_key_clear", "").lower() in {"1", "true", "on"}
    logger.info(
        "GitHub settings update action=%s has_pat=%s has_repo=%s",
        action or "save",
        bool(pat),
        "github_repo" in request.form,
    )
    payload = {"pat": pat}
    if "github_repo" in request.form:
        payload["repo"] = request.form.get("github_repo", "").strip()
    if clear_key and existing_key_path:
        existing_path = Path(existing_key_path)
        try:
            if existing_path.is_file() and Path(Config.SSH_KEYS_DIR) in existing_path.parents:
                existing_path.unlink()
        except OSError:
            logger.warning("Failed to remove GitHub SSH key at %s", existing_key_path)
        payload["ssh_key_path"] = ""
        flash("GitHub SSH key removed.", "success")
    elif uploaded_key and uploaded_key.filename:
        key_bytes = uploaded_key.read()
        if not key_bytes:
            flash("Uploaded SSH key is empty.", "error")
        elif len(key_bytes) > 256 * 1024:
            flash("SSH key is too large.", "error")
        else:
            key_path = Path(Config.SSH_KEYS_DIR) / "github_ssh_key.pem"
            try:
                key_path.write_bytes(key_bytes)
                key_path.chmod(0o600)
                payload["ssh_key_path"] = str(key_path)
                flash("GitHub SSH key uploaded.", "success")
            except OSError as exc:
                logger.warning("Failed to save GitHub SSH key: %s", exc)
                flash("Unable to save GitHub SSH key.", "error")
    _save_integration_settings("github", payload)
    if action == "refresh":
        repo_options: list[str] = []
        if pat:
            try:
                logger.info("GitHub refresh: requesting repositories")
                repo_options = _fetch_github_repos(pat)
                if repo_options:
                    logger.info("GitHub refresh: loaded %s repositories", len(repo_options))
                    flash(f"Loaded {len(repo_options)} repositories.", "success")
                else:
                    logger.info("GitHub refresh: no repositories returned")
                    flash("No repositories returned for this PAT.", "info")
            except ValueError as exc:
                logger.warning("GitHub refresh: failed with error=%s", exc)
                flash(str(exc), "error")
        else:
            logger.info("GitHub refresh: missing PAT")
            flash("GitHub PAT is required to refresh repositories.", "error")
        summary = _settings_summary()
        jira_settings = _load_integration_settings("jira")
        confluence_settings = _load_integration_settings("confluence")
        github_settings = _load_integration_settings("github")
        jira_project_options: list[dict[str, str]] = []
        selected_project = jira_settings.get("project_key")
        if selected_project:
            jira_project_options = [
                {"value": selected_project, "label": selected_project}
            ]
        jira_board_options: list[dict[str, str]] = []
        selected_board = jira_settings.get("board")
        if selected_board:
            jira_board_options = [{"value": selected_board, "label": selected_board}]
        confluence_space_options: list[dict[str, str]] = []
        selected_space = confluence_settings.get("space")
        if selected_space:
            confluence_space_options = [
                {"value": selected_space, "label": selected_space}
            ]
        return render_template(
            "settings_integrations.html",
            github_settings=github_settings,
            jira_settings=jira_settings,
            confluence_settings=confluence_settings,
            github_repo_options=repo_options,
            jira_project_options=jira_project_options,
            jira_board_options=jira_board_options,
            confluence_space_options=confluence_space_options,
            github_connected=bool(
                (github_settings.get("pat") or "").strip()
                or (github_settings.get("ssh_key_path") or "").strip()
            ),
            jira_connected=bool(jira_settings.get("api_key")),
            confluence_connected=bool(confluence_settings.get("api_key")),
            summary=summary,
            page_title="Settings - Integrations",
            active_page="settings",
            settings_title="Settings",
            settings_subtitle="Integrations",
            settings_section="integrations",
        )
    flash("GitHub settings updated.", "success")
    return redirect(url_for("agents.settings_integrations"))


@bp.post("/settings/integrations/jira")
def update_jira_settings():
    action = request.form.get("action", "").strip()
    api_key = request.form.get("jira_api_key", "").strip()
    email = request.form.get("jira_email", "").strip()
    site = request.form.get("jira_site", "").strip()
    project_key = request.form.get("jira_project_key", "").strip()
    logger.info(
        "Jira settings update action=%s key_len=%s key_has_colon=%s email_domain=%s site_host=%s has_board=%s",
        action or "save",
        len(api_key),
        ":" in api_key,
        _safe_email_domain(email),
        _safe_site_label(site),
        "jira_board" in request.form,
    )
    payload = {
        "api_key": api_key,
        "email": email,
        "site": site,
        "project_key": project_key,
    }
    if "jira_board" in request.form:
        payload["board"] = request.form.get("jira_board", "").strip()
    _save_integration_settings("jira", payload)
    if action == "refresh":
        board_options: list[dict[str, str]] = []
        project_options: list[dict[str, str]] = []
        if api_key and site:
            try:
                auth_key = _combine_atlassian_key(api_key, email)
                email_valid = True
                if email and "@" not in email:
                    email_valid = False
                    flash(
                        "Jira email must include a full address (name@domain).",
                        "error",
                    )
                needs_email = ":" not in auth_key
                if needs_email:
                    flash(
                        "Jira API key needs an Atlassian email. Enter it above or use email:token.",
                        "error",
                    )
                logger.info(
                    "Jira refresh: starting email_set=%s",
                    bool(email),
                )
                if not email_valid or needs_email:
                    logger.info("Jira refresh: skipped due to email validation")
                else:
                    project_options = _fetch_jira_projects(auth_key, site)
                    if project_options:
                        logger.info(
                            "Jira refresh: loaded %s projects", len(project_options)
                        )
                        flash(f"Loaded {len(project_options)} projects.", "success")
                    else:
                        logger.info("Jira refresh: no projects returned")
                        flash("No projects returned for this Jira key.", "info")
                    if project_key:
                        board_options = _fetch_jira_boards(
                            auth_key, site, project_key
                        )
                        if board_options:
                            logger.info(
                                "Jira refresh: loaded %s boards", len(board_options)
                            )
                            flash(
                                f"Loaded {len(board_options)} boards for {project_key}.",
                                "success",
                            )
                        else:
                            logger.info("Jira refresh: no boards returned")
                            flash(
                                f"No boards returned for project {project_key}.",
                                "info",
                            )
                    else:
                        flash(
                            "Select a Jira project and refresh to load boards.",
                            "info",
                        )
            except ValueError as exc:
                logger.warning("Jira refresh: failed with error=%s", exc)
                flash(str(exc), "error")
        else:
            logger.info("Jira refresh: missing api key or site")
            flash(
                "Jira API key and site URL are required to refresh projects and boards.",
                "error",
            )
        summary = _settings_summary()
        github_settings = _load_integration_settings("github")
        jira_settings = _load_integration_settings("jira")
        confluence_settings = _load_integration_settings("confluence")
        github_repo_options: list[str] = []
        selected_repo = github_settings.get("repo")
        if selected_repo:
            github_repo_options = [selected_repo]
        if project_key and all(
            option.get("value") != project_key for option in project_options
        ):
            project_options.insert(
                0, {"value": project_key, "label": project_key}
            )
        confluence_space_options: list[dict[str, str]] = []
        selected_space = confluence_settings.get("space")
        if selected_space:
            confluence_space_options = [
                {"value": selected_space, "label": selected_space}
            ]
        return render_template(
            "settings_integrations.html",
            github_settings=github_settings,
            jira_settings=jira_settings,
            confluence_settings=confluence_settings,
            github_repo_options=github_repo_options,
            jira_project_options=project_options,
            jira_board_options=board_options,
            confluence_space_options=confluence_space_options,
            github_connected=bool(github_settings.get("pat")),
            jira_connected=bool(api_key),
            confluence_connected=bool(confluence_settings.get("api_key")),
            summary=summary,
            page_title="Settings - Integrations",
            active_page="settings",
            settings_title="Settings",
            settings_subtitle="Integrations",
            settings_section="integrations",
        )
    flash("Jira settings updated.", "success")
    return redirect(url_for("agents.settings_integrations"))


@bp.post("/settings/integrations/confluence")
def update_confluence_settings():
    action = request.form.get("action", "").strip()
    api_key = request.form.get("confluence_api_key", "").strip()
    email = request.form.get("confluence_email", "").strip()
    site = request.form.get("confluence_site", "").strip()
    logger.info(
        "Confluence settings update action=%s key_len=%s key_has_colon=%s email_domain=%s site_host=%s has_space=%s",
        action or "save",
        len(api_key),
        ":" in api_key,
        _safe_email_domain(email),
        _safe_site_label(site),
        "confluence_space" in request.form,
    )
    payload = {"api_key": api_key, "email": email, "site": site}
    if "confluence_space" in request.form:
        payload["space"] = request.form.get("confluence_space", "").strip()
    _save_integration_settings("confluence", payload)
    if action == "refresh":
        space_options: list[dict[str, str]] = []
        if api_key and site:
            try:
                auth_key = _combine_atlassian_key(api_key, email)
                email_valid = True
                if email and "@" not in email:
                    email_valid = False
                    flash(
                        "Confluence email must include a full address (name@domain).",
                        "error",
                    )
                needs_email = ":" not in auth_key
                if needs_email:
                    flash(
                        "Confluence API key needs an Atlassian email. Enter it above or use email:token.",
                        "error",
                    )
                logger.info(
                    "Confluence refresh: starting email_set=%s",
                    bool(email),
                )
                if not email_valid or needs_email:
                    logger.info("Confluence refresh: skipped due to email validation")
                else:
                    space_options = _fetch_confluence_spaces(auth_key, site)
                    if space_options:
                        logger.info(
                            "Confluence refresh: loaded %s spaces", len(space_options)
                        )
                        flash(f"Loaded {len(space_options)} spaces.", "success")
                    else:
                        logger.info("Confluence refresh: no spaces returned")
                        flash("No spaces returned for this Confluence key.", "info")
            except ValueError as exc:
                logger.warning("Confluence refresh: failed with error=%s", exc)
                flash(str(exc), "error")
        else:
            logger.info("Confluence refresh: missing api key or site")
            flash(
                "Confluence API key and site URL are required to refresh spaces.",
                "error",
            )
        summary = _settings_summary()
        github_settings = _load_integration_settings("github")
        jira_settings = _load_integration_settings("jira")
        confluence_settings = _load_integration_settings("confluence")
        github_repo_options: list[str] = []
        selected_repo = github_settings.get("repo")
        if selected_repo:
            github_repo_options = [selected_repo]
        jira_project_options: list[dict[str, str]] = []
        selected_project = jira_settings.get("project_key")
        if selected_project:
            jira_project_options = [
                {"value": selected_project, "label": selected_project}
            ]
        jira_board_options: list[dict[str, str]] = []
        selected_board = jira_settings.get("board")
        if selected_board:
            jira_board_options = [{"value": selected_board, "label": selected_board}]
        return render_template(
            "settings_integrations.html",
            github_settings=github_settings,
            jira_settings=jira_settings,
            confluence_settings=confluence_settings,
            github_repo_options=github_repo_options,
            jira_project_options=jira_project_options,
            jira_board_options=jira_board_options,
            confluence_space_options=space_options,
            github_connected=bool(github_settings.get("pat")),
            jira_connected=bool(jira_settings.get("api_key")),
            confluence_connected=bool(api_key),
            summary=summary,
            page_title="Settings - Integrations",
            active_page="settings",
            settings_title="Settings",
            settings_subtitle="Integrations",
            settings_section="integrations",
        )
    flash("Confluence settings updated.", "success")
    return redirect(url_for("agents.settings_integrations"))
