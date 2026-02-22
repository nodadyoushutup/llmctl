from .shared import *  # noqa: F401,F403

__all__ = ['index', 'dashboard', 'list_agents', 'new_agent', 'create_agent', 'view_agent', 'edit_agent', 'update_agent', 'attach_agent_skill', 'detach_agent_skill', 'move_agent_skill', 'create_agent_priority', 'update_agent_priority', 'move_agent_priority', 'delete_agent_priority', 'start_agent', 'stop_agent', 'delete_agent', 'start_run', 'cancel_run', 'end_run', 'delete_run', 'new_run', 'view_run', 'edit_run', 'update_run', 'create_run', 'runs', 'quick_task', 'update_quick_task_defaults', 'create_quick_task']

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
    if _agents_wants_json():
        return {
            "agents": [
                _serialize_agent_list_item(
                    agent,
                    role_name=roles_by_id.get(agent.role_id),
                    status=agent_status_by_id.get(agent.id, "stopped"),
                )
                for agent in agents
            ],
            "summary": summary,
        }
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
    if _agents_wants_json():
        return {"roles": [_serialize_role_option(role) for role in roles]}
    return render_template(
        "agent_new.html",
        roles=roles,
        page_title="Create Agent",
        active_page="agents",
    )

@bp.post("/agents")
def create_agent():
    is_api_request = _agent_api_request()
    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None or not isinstance(payload, dict):
        payload = {}
    name_raw = payload.get("name") if is_api_request else request.form.get("name", "")
    description_raw = (
        payload.get("description") if is_api_request else request.form.get("description", "")
    )
    role_raw = payload.get("role_id") if is_api_request else request.form.get("role_id", "")
    name = str(name_raw or "").strip()
    description = str(description_raw or "").strip()

    if not description:
        if is_api_request:
            return {"error": "Agent description is required."}, 400
        flash("Agent description is required.", "error")
        return redirect(url_for("agents.new_agent"))

    if not name:
        name = "Untitled Agent"

    try:
        role_id = _coerce_optional_int(role_raw, field_name="role_id", minimum=1)
    except ValueError:
        if is_api_request:
            return {"error": "Role must be a number."}, 400
        role_id = None
        if role_raw:
            flash("Role must be a number.", "error")
            return redirect(url_for("agents.new_agent"))
    role_name: str | None = None
    with session_scope() as session:
        if role_id is not None:
            role = session.get(Role, role_id)
            if role is None:
                if is_api_request:
                    return {"error": "Role not found."}, 404
                flash("Role not found.", "error")
                return redirect(url_for("agents.new_agent"))
            role_name = role.name
        prompt_payload = {"description": description}
        prompt_json = json.dumps(prompt_payload, indent=2, sort_keys=True)
        agent = Agent.create(
            session,
            name=name,
            role_id=role_id,
            description=description,
            prompt_json=prompt_json,
            prompt_text=None,
            autonomous_prompt=None,
            is_system=False,
        )
        payload = _serialize_agent_list_item(
            agent,
            role_name=role_name,
            status="stopped",
        )

    if is_api_request:
        return {"agent": payload}, 201
    agent_id = int(payload["id"])
    flash(f"Agent {agent_id} created.", "success")
    return redirect(url_for("agents.view_agent", agent_id=agent_id))

@bp.get("/agents/<int:agent_id>")
def view_agent(agent_id: int):
    wants_json = _agents_wants_json()
    roles = _load_roles()
    roles_by_id = {role.id: role.name for role in roles}
    with session_scope() as session:
        agent = (
            session.execute(
                select(Agent)
                .options(
                    selectinload(Agent.priorities),
                    selectinload(Agent.skills).selectinload(Skill.versions),
                )
                .where(Agent.id == agent_id)
            )
            .scalars()
            .one_or_none()
        )
        if agent is None:
            abort(404)
        priorities = _ordered_agent_priorities(agent)
        assigned_skills = _ordered_agent_skills(agent)
        assigned_skill_ids = {skill.id for skill in assigned_skills}
        available_skills: list[Skill] = []
        if wants_json:
            available_skills = (
                session.execute(
                    select(Skill)
                    .options(selectinload(Skill.versions))
                    .where(Skill.status != SKILL_STATUS_ARCHIVED)
                    .order_by(Skill.display_name.asc(), Skill.name.asc(), Skill.id.asc())
                )
                .scalars()
                .all()
            )
            available_skills = [
                skill for skill in available_skills if skill.id not in assigned_skill_ids
            ]
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
    agent_status_by_id = _agent_status_by_id([agent.id])
    agent_status = agent_status_by_id.get(agent.id, "stopped")
    if wants_json:
        return {
            "agent": _serialize_agent_list_item(
                agent,
                role_name=roles_by_id.get(agent.role_id),
                status=agent_status,
            ),
            "active_run_id": active_run_id,
            "roles": [_serialize_role_option(role) for role in roles],
            "priorities": [_serialize_agent_priority(priority) for priority in priorities],
            "assigned_skills": [_serialize_agent_skill(skill) for skill in assigned_skills],
            "available_skills": [_serialize_agent_skill(skill) for skill in available_skills],
        }
    return render_template(
        "agent_detail.html",
        agent=agent,
        priorities=priorities,
        assigned_skills=assigned_skills,
        agent_status=agent_status,
        roles_by_id=roles_by_id,
        human_time=_human_time,
        page_title=f"Agent - {agent.name}",
        active_page="agents",
        agent_section="overview",
    )

@bp.get("/agents/<int:agent_id>/edit")
def edit_agent(agent_id: int):
    roles = _load_roles()
    with session_scope() as session:
        agent = (
            session.execute(
                select(Agent)
                .options(
                    selectinload(Agent.priorities),
                    selectinload(Agent.skills).selectinload(Skill.versions),
                )
                .where(Agent.id == agent_id)
            )
            .scalars()
            .one_or_none()
        )
        if agent is None:
            abort(404)
        priorities = _ordered_agent_priorities(agent)
        assigned_skills = _ordered_agent_skills(agent)
        assigned_skill_ids = {skill.id for skill in assigned_skills}
        available_skills = (
            session.execute(
                select(Skill)
                .options(selectinload(Skill.versions))
                .where(Skill.status != SKILL_STATUS_ARCHIVED)
                .order_by(Skill.display_name.asc(), Skill.name.asc(), Skill.id.asc())
            )
            .scalars()
            .all()
        )
        available_skills = [
            skill for skill in available_skills if skill.id not in assigned_skill_ids
        ]
    return render_template(
        "agent_edit.html",
        agent=agent,
        roles=roles,
        priorities=priorities,
        assigned_skills=assigned_skills,
        available_skills=available_skills,
        page_title=f"Edit Agent - {agent.name}",
        active_page="agents",
    )

@bp.post("/agents/<int:agent_id>")
def update_agent(agent_id: int):
    is_api_request = _agent_api_request()
    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None or not isinstance(payload, dict):
        payload = {}
    name_raw = payload.get("name") if is_api_request else request.form.get("name", "")
    description_raw = (
        payload.get("description") if is_api_request else request.form.get("description", "")
    )
    role_raw = payload.get("role_id") if is_api_request else request.form.get("role_id", "")
    name = str(name_raw or "").strip()
    description = str(description_raw or "").strip()

    if not description:
        if is_api_request:
            return {"error": "Agent description is required."}, 400
        flash("Agent description is required.", "error")
        return redirect(url_for("agents.edit_agent", agent_id=agent_id))

    try:
        role_id = _coerce_optional_int(role_raw, field_name="role_id", minimum=1)
    except ValueError:
        if is_api_request:
            return {"error": "Role must be a number."}, 400
        role_id = None
        if role_raw:
            flash("Role must be a number.", "error")
            return redirect(url_for("agents.edit_agent", agent_id=agent_id))

    role_name: str | None = None
    with session_scope() as session:
        agent = session.get(Agent, agent_id)
        if agent is None:
            abort(404)
        if role_id is not None:
            role = session.get(Role, role_id)
            if role is None:
                if is_api_request:
                    return {"error": "Role not found."}, 404
                flash("Role not found.", "error")
                return redirect(url_for("agents.edit_agent", agent_id=agent_id))
            role_name = role.name
        if not name:
            name = agent.name or "Untitled Agent"
        prompt_payload = {"description": description}
        prompt_json = json.dumps(prompt_payload, indent=2, sort_keys=True)
        agent.name = name
        agent.description = description
        agent.prompt_json = prompt_json
        agent.prompt_text = None
        agent.autonomous_prompt = None
        agent.role_id = role_id
        active_run_status = (
            session.execute(
                select(Run.status)
                .where(
                    Run.agent_id == agent.id,
                    Run.status.in_(RUN_ACTIVE_STATUSES),
                )
                .order_by(Run.created_at.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        payload = _serialize_agent_list_item(
            agent,
            role_name=role_name,
            status=active_run_status or "stopped",
        )

    if is_api_request:
        return {"agent": payload}
    flash("Agent updated.", "success")
    return redirect(url_for("agents.view_agent", agent_id=agent_id))

@bp.post("/agents/<int:agent_id>/skills")
def attach_agent_skill(agent_id: int):
    is_api_request = _agent_api_request()
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.edit_agent", agent_id=agent_id)
    )
    payload = _flowchart_request_payload()
    raw_skill_id = payload.get("skill_id") if payload else request.form.get("skill_id")
    try:
        skill_id = _coerce_optional_int(raw_skill_id, field_name="skill_id", minimum=1)
    except ValueError as exc:
        if is_api_request:
            return {"error": str(exc)}, 400
        flash(str(exc), "error")
        return redirect(redirect_target)
    if skill_id is None:
        if is_api_request:
            return {"error": "skill_id is required."}, 400
        flash("skill_id is required.", "error")
        return redirect(redirect_target)

    assigned = False
    with session_scope() as session:
        agent = (
            session.execute(
                select(Agent).options(selectinload(Agent.skills)).where(Agent.id == agent_id)
            )
            .scalars()
            .one_or_none()
        )
        if agent is None:
            abort(404)
        skill = session.get(Skill, skill_id)
        if skill is None:
            if is_api_request:
                return {"error": f"Skill {skill_id} was not found."}, 404
            flash(f"Skill {skill_id} was not found.", "error")
            return redirect(redirect_target)
        if (skill.status or SKILL_STATUS_ACTIVE) == SKILL_STATUS_ARCHIVED:
            if is_api_request:
                return {"error": f"Skill {skill_id} is archived and cannot be assigned."}, 400
            flash(f"Skill {skill_id} is archived and cannot be assigned.", "error")
            return redirect(redirect_target)

        ordered_ids = [item.id for item in _ordered_agent_skills(agent)]
        if skill_id not in ordered_ids:
            ordered_ids.append(skill_id)
            _set_agent_skills(session, agent_id, ordered_ids)
            assigned = True
            if is_api_request:
                return {"ok": True, "assigned": True}
            flash("Skill assigned.", "success")
        else:
            if is_api_request:
                return {"ok": True, "assigned": False}
            flash("Skill already assigned.", "info")

    if is_api_request:
        return {"ok": True, "assigned": assigned}
    return redirect(redirect_target)

@bp.post("/agents/<int:agent_id>/skills/<int:skill_id>/delete")
def detach_agent_skill(agent_id: int, skill_id: int):
    is_api_request = _agent_api_request()
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.edit_agent", agent_id=agent_id)
    )
    with session_scope() as session:
        agent = (
            session.execute(
                select(Agent).options(selectinload(Agent.skills)).where(Agent.id == agent_id)
            )
            .scalars()
            .one_or_none()
        )
        if agent is None:
            abort(404)
        ordered_ids = [item.id for item in _ordered_agent_skills(agent) if item.id != skill_id]
        _set_agent_skills(session, agent_id, ordered_ids)
    if is_api_request:
        return {"ok": True}
    flash("Skill removed.", "success")
    return redirect(redirect_target)

@bp.post("/agents/<int:agent_id>/skills/<int:skill_id>/move")
def move_agent_skill(agent_id: int, skill_id: int):
    is_api_request = _agent_api_request()
    direction = (request.form.get("direction") or "").strip().lower()
    if not direction and request.is_json:
        payload = request.get_json(silent=True) or {}
        if isinstance(payload, dict):
            direction = str(payload.get("direction") or "").strip().lower()
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.edit_agent", agent_id=agent_id)
    )
    if direction not in {"up", "down"}:
        if is_api_request:
            return {"error": "Invalid skill reorder direction."}, 400
        flash("Invalid skill reorder direction.", "error")
        return redirect(redirect_target)

    with session_scope() as session:
        agent = (
            session.execute(
                select(Agent).options(selectinload(Agent.skills)).where(Agent.id == agent_id)
            )
            .scalars()
            .one_or_none()
        )
        if agent is None:
            abort(404)
        ordered_ids = [item.id for item in _ordered_agent_skills(agent)]
        index = next((idx for idx, item_id in enumerate(ordered_ids) if item_id == skill_id), None)
        if index is None:
            abort(404)
        if direction == "up" and index > 0:
            ordered_ids[index - 1], ordered_ids[index] = ordered_ids[index], ordered_ids[index - 1]
        elif direction == "down" and index < len(ordered_ids) - 1:
            ordered_ids[index + 1], ordered_ids[index] = ordered_ids[index], ordered_ids[index + 1]
        _set_agent_skills(session, agent_id, ordered_ids)

    if is_api_request:
        return {"ok": True}
    return redirect(redirect_target)

@bp.post("/agents/<int:agent_id>/priorities")
def create_agent_priority(agent_id: int):
    is_api_request = _agent_api_request()
    content = request.form.get("content", "").strip()
    if not content and request.is_json:
        payload = request.get_json(silent=True) or {}
        if isinstance(payload, dict):
            content = str(payload.get("content") or "").strip()
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.edit_agent", agent_id=agent_id)
    )
    if not content:
        if is_api_request:
            return {"error": "Priority content is required."}, 400
        flash("Priority content is required.", "error")
        return redirect(redirect_target)
    with session_scope() as session:
        agent = (
            session.execute(
                select(Agent)
                .options(selectinload(Agent.priorities))
                .where(Agent.id == agent_id)
            )
            .scalars()
            .one_or_none()
        )
        if agent is None:
            abort(404)
        position = len(_ordered_agent_priorities(agent)) + 1
        AgentPriority.create(
            session,
            agent_id=agent_id,
            position=position,
            content=content,
        )
    if is_api_request:
        return {"ok": True}, 201
    flash("Priority added.", "success")
    return redirect(redirect_target)

@bp.post("/agents/<int:agent_id>/priorities/<int:priority_id>")
def update_agent_priority(agent_id: int, priority_id: int):
    is_api_request = _agent_api_request()
    content = request.form.get("content", "").strip()
    if not content and request.is_json:
        payload = request.get_json(silent=True) or {}
        if isinstance(payload, dict):
            content = str(payload.get("content") or "").strip()
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.edit_agent", agent_id=agent_id)
    )
    if not content:
        if is_api_request:
            return {"error": "Priority content is required."}, 400
        flash("Priority content is required.", "error")
        return redirect(redirect_target)
    with session_scope() as session:
        priority = session.get(AgentPriority, priority_id)
        if priority is None or priority.agent_id != agent_id:
            abort(404)
        priority.content = content
    if is_api_request:
        return {"ok": True}
    flash("Priority updated.", "success")
    return redirect(redirect_target)

@bp.post("/agents/<int:agent_id>/priorities/<int:priority_id>/move")
def move_agent_priority(agent_id: int, priority_id: int):
    is_api_request = _agent_api_request()
    direction = (request.form.get("direction") or "").strip().lower()
    if not direction and request.is_json:
        payload = request.get_json(silent=True) or {}
        if isinstance(payload, dict):
            direction = str(payload.get("direction") or "").strip().lower()
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.edit_agent", agent_id=agent_id)
    )
    if direction not in {"up", "down"}:
        if is_api_request:
            return {"error": "Invalid priority reorder direction."}, 400
        flash("Invalid priority reorder direction.", "error")
        return redirect(redirect_target)
    with session_scope() as session:
        agent = (
            session.execute(
                select(Agent)
                .options(selectinload(Agent.priorities))
                .where(Agent.id == agent_id)
            )
            .scalars()
            .one_or_none()
        )
        if agent is None:
            abort(404)
        priorities = _ordered_agent_priorities(agent)
        index = next(
            (entry_index for entry_index, item in enumerate(priorities) if item.id == priority_id),
            None,
        )
        if index is None:
            abort(404)
        if direction == "up" and index > 0:
            priorities[index - 1], priorities[index] = priorities[index], priorities[index - 1]
        elif direction == "down" and index < len(priorities) - 1:
            priorities[index + 1], priorities[index] = priorities[index], priorities[index + 1]
        _reindex_agent_priorities(priorities)
    if is_api_request:
        return {"ok": True}
    return redirect(redirect_target)

@bp.post("/agents/<int:agent_id>/priorities/<int:priority_id>/delete")
def delete_agent_priority(agent_id: int, priority_id: int):
    is_api_request = _agent_api_request()
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.edit_agent", agent_id=agent_id)
    )
    with session_scope() as session:
        agent = (
            session.execute(
                select(Agent)
                .options(selectinload(Agent.priorities))
                .where(Agent.id == agent_id)
            )
            .scalars()
            .one_or_none()
        )
        if agent is None:
            abort(404)
        priorities = _ordered_agent_priorities(agent)
        priority = next((item for item in priorities if item.id == priority_id), None)
        if priority is None:
            abort(404)
        session.delete(priority)
        priorities = [item for item in priorities if item.id != priority_id]
        _reindex_agent_priorities(priorities)
    if is_api_request:
        return {"ok": True}
    flash("Priority deleted.", "success")
    return redirect(redirect_target)

@bp.post("/agents/<int:agent_id>/start")
def start_agent(agent_id: int):
    is_api_request = _agent_api_request()
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
            if is_api_request:
                return {
                    "error": "Autorun is already enabled for this agent.",
                    "run_id": active_run_id,
                }, 409
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
            if is_api_request:
                return {"error": "Run not found after start."}, 500
            return redirect(fallback_target)
        run.task_id = task.id
        agent = session.get(Agent, run.agent_id)
        if agent is not None:
            agent.task_id = task.id

    if is_api_request:
        return {"ok": True, "run_id": run_id, "task_id": task.id}
    flash("Autorun enabled.", "success")
    return redirect(url_for("agents.view_run", run_id=run_id))

@bp.post("/agents/<int:agent_id>/stop")
def stop_agent(agent_id: int):
    is_api_request = _agent_api_request()
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
            if is_api_request:
                return {"ok": True, "already_stopped": True}
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

    if is_api_request:
        return {
            "ok": True,
            "already_stopped": False,
            "task_id": task_id,
            "revoke_requested": bool(task_id and Config.CELERY_REVOKE_ON_STOP),
        }
    flash("Autorun disable requested.", "success")
    return redirect(redirect_target)

@bp.post("/agents/<int:agent_id>/delete")
def delete_agent(agent_id: int):
    is_api_request = _agent_api_request()
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
            if is_api_request:
                return {"error": "Disable autorun before deleting."}, 409
            flash("Disable autorun before deleting.", "error")
            return redirect(next_url)
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

    if is_api_request:
        return {"ok": True, "detached_task_count": task_count}
    flash("Agent deleted.", "success")
    if task_count:
        flash(f"Detached from {task_count} task(s).", "info")
    return redirect(next_url)

@bp.post("/runs/<int:run_id>/start")
def start_run(run_id: int):
    if _stage3_api_request():
        return {
            "error": "Autoruns are managed from the agent.",
            "reason_code": "AGENT_MANAGED_AUTORUN",
        }, 409
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            abort(404)
        target = url_for("agents.view_agent", agent_id=run.agent_id)
    flash("Autoruns are managed from the agent.", "info")
    return redirect(target)

@bp.post("/runs/<int:run_id>/cancel")
def cancel_run(run_id: int):
    if _stage3_api_request():
        return {
            "error": "Autoruns are managed from the agent.",
            "reason_code": "AGENT_MANAGED_AUTORUN",
        }, 409
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            abort(404)
        target = url_for("agents.view_agent", agent_id=run.agent_id)
    flash("Autoruns are managed from the agent.", "info")
    return redirect(target)

@bp.post("/runs/<int:run_id>/end")
def end_run(run_id: int):
    if _stage3_api_request():
        return {
            "error": "Autoruns are managed from the agent.",
            "reason_code": "AGENT_MANAGED_AUTORUN",
        }, 409
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            abort(404)
        target = url_for("agents.view_agent", agent_id=run.agent_id)
    flash("Autoruns are managed from the agent.", "info")
    return redirect(target)

@bp.post("/runs/<int:run_id>/delete")
def delete_run(run_id: int):
    is_api_request = _stage3_api_request()
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.runs")
    )
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            abort(404)
        if run.status in RUN_ACTIVE_STATUSES:
            if is_api_request:
                return {"error": "Disable autorun before deleting."}, 409
            flash("Disable autorun before deleting.", "error")
            return redirect(next_url)
        session.execute(
            update(AgentTask)
            .where(AgentTask.run_id == run_id)
            .values(run_id=None)
        )
        session.delete(run)
    if is_api_request:
        return {"ok": True}
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
    if _run_wants_json():
        return {
            "message": "Autoruns are created when you enable autorun on an agent.",
            "selected_agent_id": selected_agent,
            "agents": [_serialize_agent_list_item(agent) for agent in agents],
        }
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
                )
                .order_by(AgentTask.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
        run_tasks: list[AgentTask] = []
        provider_filter = (request.args.get("provider") or "").strip().lower()
        dispatch_status_filter = (
            request.args.get("dispatch_status") or ""
        ).strip().lower()
        fallback_filter = (request.args.get("fallback_attempted") or "").strip().lower()
        fallback_filter_value: bool | None = None
        if fallback_filter in {"true", "1", "yes", "on"}:
            fallback_filter_value = True
        elif fallback_filter in {"false", "0", "no", "off"}:
            fallback_filter_value = False
        loops_completed = 0
        if run_task_id:
            task_query = select(AgentTask).where(
                AgentTask.run_task_id == run_task_id,
                AgentTask.run_id == run_id,
            )
            count_query = select(func.count(AgentTask.id)).where(
                AgentTask.run_task_id == run_task_id,
                AgentTask.run_id == run_id,
            )
            if provider_filter in {"workspace", "docker", "kubernetes"}:
                task_query = task_query.where(AgentTask.final_provider == provider_filter)
                count_query = count_query.where(AgentTask.final_provider == provider_filter)
            if dispatch_status_filter in {
                "dispatch_pending",
                "dispatch_submitted",
                "dispatch_confirmed",
                "dispatch_failed",
                "fallback_started",
            }:
                task_query = task_query.where(AgentTask.dispatch_status == dispatch_status_filter)
                count_query = count_query.where(AgentTask.dispatch_status == dispatch_status_filter)
            if fallback_filter_value is not None:
                task_query = task_query.where(
                    AgentTask.fallback_attempted.is_(fallback_filter_value)
                )
                count_query = count_query.where(
                    AgentTask.fallback_attempted.is_(fallback_filter_value)
                )
            run_tasks = (
                session.execute(task_query.order_by(AgentTask.created_at.desc()).limit(50))
                .scalars()
                .all()
            )
            loops_completed = session.execute(count_query).scalar_one()
    run_max_loops = run.run_max_loops or 0
    run_is_forever = run_max_loops < 1
    loops_remaining = (
        None if run_is_forever else max(run_max_loops - loops_completed, 0)
    )
    run_tasks_payload = [_serialize_run_task(task) for task in run_tasks]
    if _run_wants_json():
        return {
            "run": {
                "id": run.id,
                "agent_id": run.agent_id,
                "name": run.name,
                "status": run.status,
                "task_id": run.task_id,
                "last_run_task_id": run.last_run_task_id,
                "run_max_loops": run_max_loops,
                "created_at": _human_time(run.created_at),
                "last_started_at": _human_time(run.last_started_at),
                "last_stopped_at": _human_time(run.last_stopped_at),
                "updated_at": _human_time(run.updated_at),
            },
            "agent": {
                "id": agent.id,
                "name": agent.name,
            },
            "run_task_id": run_task_id,
            "loops_completed": int(loops_completed),
            "loops_remaining": loops_remaining,
            "run_is_forever": run_is_forever,
            "run_tasks": run_tasks_payload,
            "filters": {
                "provider": provider_filter,
                "dispatch_status": dispatch_status_filter,
                "fallback_attempted": (
                    ""
                    if fallback_filter_value is None
                    else ("true" if fallback_filter_value else "false")
                ),
            },
        }
    return render_template(
        "run_detail.html",
        run=run,
        agent=agent,
        run_task_id=run_task_id,
        run_tasks=run_tasks_payload,
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
    if _run_wants_json():
        return {
            "message": "Autoruns are managed from the agent.",
            "run": _serialize_run_list_item(run),
            "agent": _serialize_agent_list_item(agent),
            "agents": [_serialize_agent_list_item(item) for item in agents],
            "run_max_loops": run_max_loops,
            "run_is_forever": run_is_forever,
        }
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
    if _stage3_api_request():
        return {
            "error": "Autoruns are managed from the agent.",
            "reason_code": "AGENT_MANAGED_AUTORUN",
        }, 409
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            abort(404)
        target = url_for("agents.view_agent", agent_id=run.agent_id)
    flash("Autoruns are managed from the agent.", "info")
    return redirect(target)

@bp.post("/runs")
def create_run():
    if _stage3_api_request():
        return {
            "error": "Autoruns are created automatically when you enable autorun on an agent.",
            "reason_code": "AGENT_MANAGED_AUTORUN",
        }, 409
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
    if _run_wants_json():
        return {
            "runs": [_serialize_run_list_item(run) for run in runs],
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages,
                "total_runs": total_runs,
                "per_page_options": list(RUNS_PER_PAGE_OPTIONS),
                "items": pagination_items,
            },
        }
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
    sync_integrated_mcp_servers()
    agents = _load_agents()
    models = _load_llm_models()
    mcp_servers = _load_mcp_servers()
    integration_options = _build_node_integration_options()
    rag_collections_contract = rag_list_collection_contract()
    rag_collection_rows = rag_collections_contract.get("collections")
    if not isinstance(rag_collection_rows, list):
        rag_collection_rows = []
    rag_collections = [
        {
            "id": str(item.get("id") or "").strip(),
            "name": str(item.get("name") or "").strip(),
            "status": str(item.get("status") or "").strip() or "",
        }
        for item in rag_collection_rows
        if isinstance(item, dict)
        and str(item.get("id") or "").strip()
        and str(item.get("name") or "").strip()
    ]
    quick_default_settings = _resolved_quick_default_settings(
        agents=agents,
        models=models,
        mcp_servers=mcp_servers,
        integration_options=integration_options,
        rag_collections=rag_collections,
    )
    _, summary = _agent_rollup(agents)
    if _nodes_wants_json():
        return {
            "agents": [_serialize_agent_list_item(agent) for agent in agents],
            "models": [
                {
                    "id": model.id,
                    "name": model.name,
                    "provider": model.provider,
                }
                for model in models
            ],
            "mcp_servers": [
                {
                    "id": server.id,
                    "name": server.name,
                    "server_key": server.server_key,
                }
                for server in mcp_servers
            ],
            "integration_options": integration_options,
            "rag_collections": rag_collections,
            "default_agent_id": quick_default_settings["default_agent_id"],
            "default_model_id": quick_default_settings["default_model_id"],
            "selected_mcp_server_ids": quick_default_settings["default_mcp_server_ids"],
            "selected_rag_collections": quick_default_settings["default_rag_collections"],
            "selected_integration_keys": quick_default_settings["default_integration_keys"],
            "quick_default_settings": quick_default_settings,
        }
    return render_template(
        "quick_task.html",
        agents=agents,
        models=models,
        mcp_servers=mcp_servers,
        integration_options=integration_options,
        rag_collections=rag_collections,
        default_agent_id=quick_default_settings["default_agent_id"],
        default_model_id=quick_default_settings["default_model_id"],
        selected_mcp_server_ids=quick_default_settings["default_mcp_server_ids"],
        selected_rag_collections=quick_default_settings["default_rag_collections"],
        selected_integration_keys=quick_default_settings["default_integration_keys"],
        summary=summary,
        page_title="Quick Node",
        active_page="quick",
        fixed_list_page=True,
    )

@bp.post("/quick/settings")
def update_quick_task_defaults():
    request_payload = _settings_request_payload()
    is_api_request = _stage3_api_request()

    def _quick_settings_error(message: str, status_code: int = 400):
        if is_api_request:
            return {"error": message}, status_code
        flash(message, "error")
        return redirect(url_for("agents.quick_task"))

    agents = _load_agents()
    models = _load_llm_models()
    mcp_servers = _load_mcp_servers()
    integration_options = _build_node_integration_options()
    rag_collections_contract = rag_list_collection_contract()
    rag_collection_rows = rag_collections_contract.get("collections")
    if not isinstance(rag_collection_rows, list):
        rag_collection_rows = []
    rag_collections = [
        {
            "id": str(item.get("id") or "").strip(),
            "name": str(item.get("name") or "").strip(),
            "status": str(item.get("status") or "").strip() or "",
        }
        for item in rag_collection_rows
        if isinstance(item, dict)
        and str(item.get("id") or "").strip()
        and str(item.get("name") or "").strip()
    ]
    rag_ids = {
        str(item.get("id") or "").strip()
        for item in rag_collections
        if str(item.get("id") or "").strip()
    }
    agent_ids = {agent.id for agent in agents}
    model_ids = {model.id for model in models}
    mcp_ids = {server.id for server in mcp_servers}
    integration_option_keys = {
        str(option.get("key") or "").strip()
        for option in integration_options
        if str(option.get("key") or "").strip()
    }

    selected_agent_id = _coerce_optional_int(
        _settings_form_value(request_payload, "default_agent_id"),
        field_name="default_agent_id",
        minimum=1,
    )
    if selected_agent_id is not None and selected_agent_id not in agent_ids:
        return _quick_settings_error("Default agent selection is invalid.")

    selected_model_id = _coerce_optional_int(
        _settings_form_value(request_payload, "default_model_id"),
        field_name="default_model_id",
        minimum=1,
    )
    if selected_model_id is not None and selected_model_id not in model_ids:
        return _quick_settings_error("Default model selection is invalid.")

    selected_mcp_server_ids = _coerce_chat_id_list(
        _settings_form_list(request_payload, "default_mcp_server_ids"),
        field_name="default_mcp_server_id",
    )
    if any(server_id not in mcp_ids for server_id in selected_mcp_server_ids):
        return _quick_settings_error("Default MCP server selection is invalid.")

    selected_rag_collections = _coerce_chat_collection_list(
        _settings_form_list(request_payload, "default_rag_collections")
    )
    if any(collection_id not in rag_ids for collection_id in selected_rag_collections):
        return _quick_settings_error("Default collection selection is invalid.")

    integration_raw_values: list[str] = []
    for raw_value in _settings_form_list(request_payload, "default_integration_keys"):
        for item in str(raw_value or "").split(","):
            cleaned = item.strip()
            if cleaned:
                integration_raw_values.append(cleaned)
    selected_integration_keys, invalid_integration_keys = validate_task_integration_keys(
        integration_raw_values
    )
    if invalid_integration_keys:
        return _quick_settings_error("Default integration selection is invalid.")
    if any(key not in integration_option_keys for key in selected_integration_keys):
        return _quick_settings_error("Default integration selection is invalid.")

    _save_integration_settings(
        QUICK_DEFAULT_SETTINGS_PROVIDER,
        {
            "default_agent_id": str(selected_agent_id or ""),
            "default_model_id": str(selected_model_id or ""),
            "default_mcp_server_ids": ",".join(
                str(server_id) for server_id in selected_mcp_server_ids
            ),
            "default_rag_collections": ",".join(selected_rag_collections),
            "default_integration_keys": ",".join(selected_integration_keys),
        },
    )
    quick_default_settings = _resolved_quick_default_settings(
        agents=agents,
        models=models,
        mcp_servers=mcp_servers,
        integration_options=integration_options,
        rag_collections=rag_collections,
    )
    if is_api_request:
        return {
            "ok": True,
            "quick_default_settings": quick_default_settings,
        }
    flash("Quick node defaults updated.", "success")
    return redirect(url_for("agents.quick_task"))

@bp.post("/quick")
def create_quick_task():
    is_api_request = _stage3_api_request()
    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None or not isinstance(payload, dict):
        payload = {}

    def _quick_error(message: str, status_code: int = 400):
        if is_api_request:
            return {"error": message}, status_code
        flash(message, "error")
        return redirect(url_for("agents.quick_task"))

    if request.is_json:
        agent_id_raw = str(payload.get("agent_id") or "").strip()
        model_id_raw = str(payload.get("model_id") or "").strip()
        mcp_raw = payload.get("mcp_server_ids")
        mcp_server_ids_raw = []
        if isinstance(mcp_raw, list):
            mcp_server_ids_raw = [str(value).strip() for value in mcp_raw]
        elif mcp_raw not in (None, ""):
            return _quick_error("mcp_server_ids must be an array.")
        integration_raw = payload.get("integration_keys")
        if integration_raw is None:
            integration_raw = []
        if not isinstance(integration_raw, list):
            return _quick_error("integration_keys must be an array.")
        selected_integration_keys, invalid_keys = validate_task_integration_keys(
            [str(value).strip() for value in integration_raw]
        )
        integration_error = "Integration selection is invalid." if invalid_keys else None
        rag_raw = payload.get("rag_collections")
        if rag_raw is None:
            rag_raw = []
        if not isinstance(rag_raw, list):
            return _quick_error("rag_collections must be an array.")
        selected_rag_collections = _coerce_chat_collection_list(
            [str(value).strip() for value in rag_raw]
        )
        prompt = str(payload.get("prompt") or "").strip()
        uploads = []
    else:
        agent_id_raw = request.form.get("agent_id", "").strip()
        model_id_raw = request.form.get("model_id", "").strip()
        mcp_server_ids_raw = [
            value.strip() for value in request.form.getlist("mcp_server_ids")
        ]
        selected_integration_keys, integration_error = _parse_node_integration_selection()
        selected_rag_collections = _coerce_chat_collection_list(
            [value.strip() for value in request.form.getlist("rag_collections")]
        )
        prompt = request.form.get("prompt", "").strip()
        uploads = request.files.getlist("attachments")
    if not prompt:
        return _quick_error("Prompt is required.")
    if integration_error:
        return _quick_error(integration_error)
    rag_collections_contract = rag_list_collection_contract()
    rag_collection_rows = rag_collections_contract.get("collections")
    if not isinstance(rag_collection_rows, list):
        rag_collection_rows = []
    rag_ids = {
        str(item.get("id") or "").strip()
        for item in rag_collection_rows
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    if any(collection_id not in rag_ids for collection_id in selected_rag_collections):
        return _quick_error("Collection selection is invalid.")

    try:
        with session_scope() as session:
            models = (
                session.execute(select(LLMModel).order_by(LLMModel.created_at.desc()))
                .scalars()
                .all()
            )
            if not models:
                return _quick_error("Create at least one model before sending a quick node.", 409)
            model_ids = {model.id for model in models}
            selected_model_id = _coerce_optional_int(
                model_id_raw,
                field_name="model_id",
                minimum=1,
            )
            if selected_model_id is None:
                selected_model_id = _quick_node_default_model_id(models)
            if selected_model_id is None:
                return _quick_error("Model is required.")
            if selected_model_id not in model_ids:
                return _quick_error("Select a valid model.")
            agent_id: int | None = None
            agent: Agent | None = None
            if agent_id_raw:
                agent_id = _coerce_optional_int(
                    agent_id_raw,
                    field_name="agent_id",
                    minimum=1,
                )
                if agent_id is None:
                    return _quick_error("Select a valid agent.")
                agent = session.get(Agent, agent_id)
                if agent is None:
                    return _quick_error("Agent not found.", 404)
            selected_mcp_ids: list[int] = []
            for raw_id in mcp_server_ids_raw:
                if not raw_id:
                    continue
                parsed_id = _coerce_optional_int(
                    raw_id,
                    field_name="mcp_server_id",
                    minimum=1,
                )
                if parsed_id is None:
                    return _quick_error("Invalid MCP server selection.")
                if parsed_id not in selected_mcp_ids:
                    selected_mcp_ids.append(parsed_id)
            selected_mcp_servers: list[MCPServer] = []
            if selected_mcp_ids:
                selected_mcp_servers = (
                    session.execute(
                        select(MCPServer).where(MCPServer.id.in_(selected_mcp_ids))
                    )
                    .scalars()
                    .all()
                )
                if len(selected_mcp_servers) != len(selected_mcp_ids):
                    return _quick_error("One or more MCP servers were not found.", 404)
                mcp_by_id = {server.id: server for server in selected_mcp_servers}
                selected_mcp_servers = [
                    mcp_by_id[mcp_id] for mcp_id in selected_mcp_ids
                ]
            system_contract = build_quick_node_system_contract()
            agent_profile = build_quick_node_agent_profile()
            if agent is not None:
                system_contract = {}
                if agent.role_id and agent.role is not None:
                    system_contract["role"] = _build_role_payload(agent.role)
                agent_profile = _build_agent_payload(agent)
            quick_task_context: dict[str, object] = {"kind": QUICK_TASK_KIND}
            if selected_rag_collections:
                quick_task_context["rag_collections"] = selected_rag_collections
            prompt_payload = serialize_prompt_envelope(
                build_prompt_envelope(
                    user_request=prompt,
                    system_contract=system_contract,
                    agent_profile=agent_profile,
                    task_context=quick_task_context,
                    output_contract=build_one_off_output_contract(),
                )
            )
            task = AgentTask.create(
                session,
                agent_id=agent_id,
                model_id=selected_model_id,
                status="queued",
                prompt=prompt_payload,
                kind=QUICK_TASK_KIND,
                integration_keys_json=serialize_task_integration_keys(
                    selected_integration_keys
                ),
            )
            task.mcp_servers = selected_mcp_servers
            attachments = _save_uploaded_attachments(session, uploads)
            _attach_attachments(task, attachments)
            task_id = task.id
    except ValueError as exc:
        return _quick_error(str(exc) or "Invalid quick node configuration.")
    except OSError as exc:
        logger.exception("Failed to save quick node attachments")
        return _quick_error(str(exc) or "Failed to save attachments.")

    celery_task = run_agent_task.delay(task_id)

    with session_scope() as session:
        task = session.get(AgentTask, task_id)
        if task is not None:
            task.celery_task_id = celery_task.id

    if is_api_request:
        return {"ok": True, "task_id": task_id, "celery_task_id": celery_task.id}, 201
    flash(f"Quick node {task_id} queued.", "success")
    return redirect(url_for("agents.view_node", task_id=task_id))
