from .shared import *  # noqa: F401,F403

__all__ = ['list_plans', 'new_plan', 'create_plan', 'view_plan', 'edit_plan', 'update_plan', 'delete_plan', 'create_plan_stage', 'update_plan_stage', 'delete_plan_stage', 'create_plan_task', 'update_plan_task', 'delete_plan_task', 'list_milestones', 'new_milestone', 'create_milestone', 'view_milestone', 'edit_milestone', 'update_milestone', 'delete_milestone']

@bp.get("/plans")
def list_plans():
    page = _parse_page(request.args.get("page"))
    per_page = WORKFLOW_LIST_PER_PAGE
    with session_scope() as session:
        total_count = session.execute(select(func.count(Plan.id))).scalar_one()
        pagination = _build_pagination(request.path, page, per_page, total_count)
        offset = (pagination["page"] - 1) * per_page
        rows = session.execute(
            select(
                Plan,
                func.count(func.distinct(PlanStage.id)),
                func.count(PlanTask.id),
            )
            .outerjoin(PlanStage, PlanStage.plan_id == Plan.id)
            .outerjoin(PlanTask, PlanTask.plan_stage_id == PlanStage.id)
            .group_by(Plan.id)
            .order_by(Plan.created_at.desc())
            .limit(per_page)
            .offset(offset)
        ).all()
    plans = [
        {
            "plan": plan,
            "stage_count": int(stage_count or 0),
            "task_count": int(task_count or 0),
        }
        for plan, stage_count, task_count in rows
    ]
    if _workflow_wants_json():
        return {
            "plans": [
                _serialize_plan_list_item(
                    item["plan"],
                    stage_count=int(item["stage_count"]),
                    task_count=int(item["task_count"]),
                )
                for item in plans
            ],
            "pagination": _serialize_workflow_pagination(pagination),
        }
    return render_template(
        "plans.html",
        plans=plans,
        pagination=pagination,
        human_time=_human_time,
        fixed_list_page=True,
        page_title="Plans",
        active_page="plans",
    )

@bp.get("/plans/new")
def new_plan():
    if _workflow_wants_json():
        return {
            "message": "Create plans by adding Plan nodes in a flowchart.",
            "flowcharts_url": url_for("agents.list_flowcharts"),
        }
    flash("Create plans by adding Plan nodes in a flowchart.", "error")
    return redirect(url_for("agents.list_flowcharts"))

@bp.post("/plans")
def create_plan():
    if _workflow_api_request():
        return {
            "error": "Create plans by adding Plan nodes in a flowchart.",
            "reason_code": "FLOWCHART_MANAGED_PLAN_CREATE",
        }, 409
    flash("Create plans by adding Plan nodes in a flowchart.", "error")
    return redirect(url_for("agents.list_flowcharts"))

@bp.get("/plans/<int:plan_id>")
def view_plan(plan_id: int):
    with session_scope() as session:
        plan = (
            session.execute(
                select(Plan)
                .options(selectinload(Plan.stages).selectinload(PlanStage.tasks))
                .where(Plan.id == plan_id)
            )
            .scalars()
            .first()
        )
        if plan is None:
            abort(404)
    stage_count = len(plan.stages)
    task_count = sum(len(stage.tasks) for stage in plan.stages)
    if _workflow_wants_json():
        return {
            "plan": _serialize_plan(plan, include_stages=True),
            "summary": {
                "stage_count": stage_count,
                "task_count": task_count,
            },
        }
    return render_template(
        "plan_detail.html",
        plan=plan,
        stage_count=stage_count,
        task_count=task_count,
        human_time=_human_time,
        page_title=f"Plan - {plan.name}",
        active_page="plans",
    )

@bp.get("/plans/<int:plan_id>/edit")
def edit_plan(plan_id: int):
    with session_scope() as session:
        plan = session.get(Plan, plan_id)
        if plan is None:
            abort(404)
    if _workflow_wants_json():
        return {
            "plan": _serialize_plan(plan),
        }
    return render_template(
        "plan_edit.html",
        plan=plan,
        page_title="Edit Plan",
        active_page="plans",
    )

@bp.post("/plans/<int:plan_id>")
def update_plan(plan_id: int):
    is_api_request = _workflow_api_request()
    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None or not isinstance(payload, dict):
        payload = {}
    name_raw = payload.get("name") if is_api_request else request.form.get("name", "")
    description_raw = (
        payload.get("description")
        if is_api_request
        else request.form.get("description", "")
    )
    completed_at_raw_obj = (
        payload.get("completed_at")
        if is_api_request
        else request.form.get("completed_at", "")
    )
    name = str(name_raw or "").strip()
    if not name:
        if is_api_request:
            return {"error": "Plan name is required."}, 400
        flash("Plan name is required.", "error")
        return redirect(url_for("agents.edit_plan", plan_id=plan_id))
    description = str(description_raw or "").strip() or None
    completed_at_raw = str(completed_at_raw_obj or "").strip()
    completed_at = _parse_completed_at(completed_at_raw)
    if completed_at_raw and completed_at is None:
        if is_api_request:
            return {"error": "Completed at must be a valid date/time."}, 400
        flash("Completed at must be a valid date/time.", "error")
        return redirect(url_for("agents.edit_plan", plan_id=plan_id))

    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.view_plan", plan_id=plan_id)
    )
    plan_payload: dict[str, object] | None = None
    with session_scope() as session:
        plan = session.get(Plan, plan_id)
        if plan is None:
            abort(404)
        plan.name = name
        plan.description = description
        plan.completed_at = completed_at
        plan_payload = _serialize_plan(plan)

    if is_api_request:
        return {"ok": True, "plan": plan_payload}
    flash("Plan updated.", "success")
    return redirect(redirect_target)

@bp.post("/plans/<int:plan_id>/delete")
def delete_plan(plan_id: int):
    is_api_request = _workflow_api_request()
    next_url = _safe_redirect_target(request.form.get("next"), url_for("agents.list_plans"))
    with session_scope() as session:
        plan = session.get(Plan, plan_id)
        if plan is None:
            abort(404)
        stage_ids = (
            session.execute(select(PlanStage.id).where(PlanStage.plan_id == plan_id))
            .scalars()
            .all()
        )
        if stage_ids:
            session.execute(
                delete(PlanTask).where(PlanTask.plan_stage_id.in_(stage_ids))
            )
        session.execute(delete(PlanStage).where(PlanStage.plan_id == plan_id))
        session.execute(
            delete(NodeArtifact).where(
                NodeArtifact.artifact_type == NODE_ARTIFACT_TYPE_PLAN,
                NodeArtifact.ref_id == plan_id,
            )
        )
        session.delete(plan)
    if is_api_request:
        return {"ok": True}
    flash("Plan deleted.", "success")
    return redirect(next_url)

@bp.post("/plans/<int:plan_id>/stages")
def create_plan_stage(plan_id: int):
    is_api_request = _workflow_api_request()
    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None or not isinstance(payload, dict):
        payload = {}
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.view_plan", plan_id=plan_id)
    )
    name_raw = payload.get("name") if is_api_request else request.form.get("name", "")
    description_raw = (
        payload.get("description")
        if is_api_request
        else request.form.get("description", "")
    )
    completed_at_raw_obj = (
        payload.get("completed_at")
        if is_api_request
        else request.form.get("completed_at", "")
    )
    name = str(name_raw or "").strip()
    if not name:
        if is_api_request:
            return {"error": "Stage name is required."}, 400
        flash("Stage name is required.", "error")
        return redirect(redirect_target)
    description = str(description_raw or "").strip() or None
    completed_at_raw = str(completed_at_raw_obj or "").strip()
    completed_at = _parse_completed_at(completed_at_raw)
    if completed_at_raw and completed_at is None:
        if is_api_request:
            return {"error": "Stage completed at must be a valid date/time."}, 400
        flash("Stage completed at must be a valid date/time.", "error")
        return redirect(redirect_target)

    stage_payload: dict[str, object] | None = None
    with session_scope() as session:
        plan = session.get(Plan, plan_id)
        if plan is None:
            abort(404)
        max_position = session.execute(
            select(func.max(PlanStage.position)).where(PlanStage.plan_id == plan_id)
        ).scalar_one()
        stage = PlanStage.create(
            session,
            plan_id=plan_id,
            name=name,
            description=description,
            position=(max_position or 0) + 1,
            completed_at=completed_at,
        )
        stage_payload = _serialize_plan_stage(stage)

    if is_api_request:
        return {"ok": True, "stage": stage_payload}, 201
    flash("Plan stage added.", "success")
    return redirect(redirect_target)

@bp.post("/plans/<int:plan_id>/stages/<int:stage_id>")
def update_plan_stage(plan_id: int, stage_id: int):
    is_api_request = _workflow_api_request()
    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None or not isinstance(payload, dict):
        payload = {}
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.view_plan", plan_id=plan_id)
    )
    name_raw = payload.get("name") if is_api_request else request.form.get("name", "")
    description_raw = (
        payload.get("description")
        if is_api_request
        else request.form.get("description", "")
    )
    completed_at_raw_obj = (
        payload.get("completed_at")
        if is_api_request
        else request.form.get("completed_at", "")
    )
    name = str(name_raw or "").strip()
    if not name:
        if is_api_request:
            return {"error": "Stage name is required."}, 400
        flash("Stage name is required.", "error")
        return redirect(redirect_target)
    description = str(description_raw or "").strip() or None
    completed_at_raw = str(completed_at_raw_obj or "").strip()
    completed_at = _parse_completed_at(completed_at_raw)
    if completed_at_raw and completed_at is None:
        if is_api_request:
            return {"error": "Stage completed at must be a valid date/time."}, 400
        flash("Stage completed at must be a valid date/time.", "error")
        return redirect(redirect_target)

    stage_payload: dict[str, object] | None = None
    with session_scope() as session:
        stage = session.get(PlanStage, stage_id)
        if stage is None or stage.plan_id != plan_id:
            abort(404)
        stage.name = name
        stage.description = description
        stage.completed_at = completed_at
        stage_payload = _serialize_plan_stage(stage)

    if is_api_request:
        return {"ok": True, "stage": stage_payload}
    flash("Plan stage updated.", "success")
    return redirect(redirect_target)

@bp.post("/plans/<int:plan_id>/stages/<int:stage_id>/delete")
def delete_plan_stage(plan_id: int, stage_id: int):
    is_api_request = _workflow_api_request()
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.view_plan", plan_id=plan_id)
    )
    with session_scope() as session:
        stage = session.get(PlanStage, stage_id)
        if stage is None or stage.plan_id != plan_id:
            abort(404)
        session.execute(delete(PlanTask).where(PlanTask.plan_stage_id == stage_id))
        session.delete(stage)
    if is_api_request:
        return {"ok": True}
    flash("Plan stage deleted.", "success")
    return redirect(redirect_target)

@bp.post("/plans/<int:plan_id>/stages/<int:stage_id>/tasks")
def create_plan_task(plan_id: int, stage_id: int):
    is_api_request = _workflow_api_request()
    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None or not isinstance(payload, dict):
        payload = {}
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.view_plan", plan_id=plan_id)
    )
    name_raw = payload.get("name") if is_api_request else request.form.get("name", "")
    description_raw = (
        payload.get("description")
        if is_api_request
        else request.form.get("description", "")
    )
    completed_at_raw_obj = (
        payload.get("completed_at")
        if is_api_request
        else request.form.get("completed_at", "")
    )
    name = str(name_raw or "").strip()
    if not name:
        if is_api_request:
            return {"error": "Task name is required."}, 400
        flash("Task name is required.", "error")
        return redirect(redirect_target)
    description = str(description_raw or "").strip() or None
    completed_at_raw = str(completed_at_raw_obj or "").strip()
    completed_at = _parse_completed_at(completed_at_raw)
    if completed_at_raw and completed_at is None:
        if is_api_request:
            return {"error": "Task completed at must be a valid date/time."}, 400
        flash("Task completed at must be a valid date/time.", "error")
        return redirect(redirect_target)

    task_payload: dict[str, object] | None = None
    with session_scope() as session:
        stage = session.get(PlanStage, stage_id)
        if stage is None or stage.plan_id != plan_id:
            abort(404)
        max_position = session.execute(
            select(func.max(PlanTask.position)).where(PlanTask.plan_stage_id == stage_id)
        ).scalar_one()
        task = PlanTask.create(
            session,
            plan_stage_id=stage_id,
            name=name,
            description=description,
            position=(max_position or 0) + 1,
            completed_at=completed_at,
        )
        task_payload = _serialize_plan_task(task)

    if is_api_request:
        return {"ok": True, "task": task_payload}, 201
    flash("Plan task added.", "success")
    return redirect(redirect_target)

@bp.post("/plans/<int:plan_id>/stages/<int:stage_id>/tasks/<int:task_id>")
def update_plan_task(plan_id: int, stage_id: int, task_id: int):
    is_api_request = _workflow_api_request()
    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None or not isinstance(payload, dict):
        payload = {}
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.view_plan", plan_id=plan_id)
    )
    name_raw = payload.get("name") if is_api_request else request.form.get("name", "")
    description_raw = (
        payload.get("description")
        if is_api_request
        else request.form.get("description", "")
    )
    completed_at_raw_obj = (
        payload.get("completed_at")
        if is_api_request
        else request.form.get("completed_at", "")
    )
    name = str(name_raw or "").strip()
    if not name:
        if is_api_request:
            return {"error": "Task name is required."}, 400
        flash("Task name is required.", "error")
        return redirect(redirect_target)
    description = str(description_raw or "").strip() or None
    completed_at_raw = str(completed_at_raw_obj or "").strip()
    completed_at = _parse_completed_at(completed_at_raw)
    if completed_at_raw and completed_at is None:
        if is_api_request:
            return {"error": "Task completed at must be a valid date/time."}, 400
        flash("Task completed at must be a valid date/time.", "error")
        return redirect(redirect_target)

    task_payload: dict[str, object] | None = None
    with session_scope() as session:
        stage = session.get(PlanStage, stage_id)
        task = session.get(PlanTask, task_id)
        if (
            stage is None
            or stage.plan_id != plan_id
            or task is None
            or task.plan_stage_id != stage_id
        ):
            abort(404)
        task.name = name
        task.description = description
        task.completed_at = completed_at
        task_payload = _serialize_plan_task(task)

    if is_api_request:
        return {"ok": True, "task": task_payload}
    flash("Plan task updated.", "success")
    return redirect(redirect_target)

@bp.post("/plans/<int:plan_id>/stages/<int:stage_id>/tasks/<int:task_id>/delete")
def delete_plan_task(plan_id: int, stage_id: int, task_id: int):
    is_api_request = _workflow_api_request()
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.view_plan", plan_id=plan_id)
    )
    with session_scope() as session:
        stage = session.get(PlanStage, stage_id)
        task = session.get(PlanTask, task_id)
        if (
            stage is None
            or stage.plan_id != plan_id
            or task is None
            or task.plan_stage_id != stage_id
        ):
            abort(404)
        session.delete(task)
    if is_api_request:
        return {"ok": True}
    flash("Plan task deleted.", "success")
    return redirect(redirect_target)

@bp.get("/milestones")
def list_milestones():
    page = _parse_page(request.args.get("page"))
    per_page = WORKFLOW_LIST_PER_PAGE
    with session_scope() as session:
        total_count = session.execute(select(func.count(Milestone.id))).scalar_one()
        pagination = _build_pagination(request.path, page, per_page, total_count)
        offset = (pagination["page"] - 1) * per_page
        milestones = (
            session.execute(
                select(Milestone)
                .order_by(
                    Milestone.completed.asc(),
                    Milestone.due_date.is_(None),
                    Milestone.due_date.asc(),
                    Milestone.created_at.desc(),
                )
                .limit(per_page)
                .offset(offset)
            )
            .scalars()
            .all()
        )
    if _workflow_wants_json():
        return {
            "milestones": [_serialize_milestone(milestone) for milestone in milestones],
            "pagination": _serialize_workflow_pagination(pagination),
            "options": {
                "status": [
                    {"value": value, "label": label}
                    for value, label in MILESTONE_STATUS_OPTIONS
                ],
                "priority": [
                    {"value": value, "label": label}
                    for value, label in MILESTONE_PRIORITY_OPTIONS
                ],
                "health": [
                    {"value": value, "label": label}
                    for value, label in MILESTONE_HEALTH_OPTIONS
                ],
            },
        }
    return render_template(
        "milestones.html",
        milestones=milestones,
        pagination=pagination,
        human_time=_human_time,
        **_milestone_template_context(),
        fixed_list_page=True,
        page_title="Milestones",
        active_page="milestones",
    )

@bp.get("/milestones/new")
def new_milestone():
    if _workflow_wants_json():
        return {
            "message": "Create milestones by adding Milestone nodes in a flowchart.",
            "flowcharts_url": url_for("agents.list_flowcharts"),
        }
    flash("Create milestones by adding Milestone nodes in a flowchart.", "error")
    return redirect(url_for("agents.list_flowcharts"))

@bp.post("/milestones")
def create_milestone():
    if _workflow_api_request():
        return {
            "error": "Create milestones by adding Milestone nodes in a flowchart.",
            "reason_code": "FLOWCHART_MANAGED_MILESTONE_CREATE",
        }, 409
    flash("Create milestones by adding Milestone nodes in a flowchart.", "error")
    return redirect(url_for("agents.list_flowcharts"))

@bp.get("/milestones/<int:milestone_id>")
def view_milestone(milestone_id: int):
    with session_scope() as session:
        milestone = session.get(Milestone, milestone_id)
        if milestone is None:
            abort(404)
    if _workflow_wants_json():
        return {
            "milestone": _serialize_milestone(milestone),
        }
    return render_template(
        "milestone_detail.html",
        milestone=milestone,
        human_time=_human_time,
        **_milestone_template_context(),
        page_title=f"Milestone - {milestone.name}",
        active_page="milestones",
    )

@bp.get("/milestones/<int:milestone_id>/edit")
def edit_milestone(milestone_id: int):
    with session_scope() as session:
        milestone = session.get(Milestone, milestone_id)
        if milestone is None:
            abort(404)
    if _workflow_wants_json():
        return {
            "milestone": _serialize_milestone(milestone),
            "options": {
                "status": [
                    {"value": value, "label": label}
                    for value, label in MILESTONE_STATUS_OPTIONS
                ],
                "priority": [
                    {"value": value, "label": label}
                    for value, label in MILESTONE_PRIORITY_OPTIONS
                ],
                "health": [
                    {"value": value, "label": label}
                    for value, label in MILESTONE_HEALTH_OPTIONS
                ],
            },
        }
    return render_template(
        "milestone_edit.html",
        milestone=milestone,
        **_milestone_template_context(),
        page_title=f"Edit Milestone - {milestone.name}",
        active_page="milestones",
    )

@bp.post("/milestones/<int:milestone_id>")
def update_milestone(milestone_id: int):
    is_api_request = _workflow_api_request()
    source_payload = request.get_json(silent=True) if request.is_json else {}
    if source_payload is None or not isinstance(source_payload, dict):
        source_payload = {}
    payload, error = _read_milestone_form(source_payload if is_api_request else None)
    if error or payload is None:
        if is_api_request:
            return {"error": error or "Invalid milestone payload."}, 400
        flash(error or "Invalid milestone payload.", "error")
        return redirect(url_for("agents.edit_milestone", milestone_id=milestone_id))
    milestone_payload: dict[str, object] | None = None
    with session_scope() as session:
        milestone = session.get(Milestone, milestone_id)
        if milestone is None:
            abort(404)
        for field, value in payload.items():
            setattr(milestone, field, value)
        milestone_payload = _serialize_milestone(milestone)
    if is_api_request:
        return {"ok": True, "milestone": milestone_payload}
    flash("Milestone updated.", "success")
    return redirect(url_for("agents.view_milestone", milestone_id=milestone_id))

@bp.post("/milestones/<int:milestone_id>/delete")
def delete_milestone(milestone_id: int):
    is_api_request = _workflow_api_request()
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_milestones")
    )
    with session_scope() as session:
        milestone = session.get(Milestone, milestone_id)
        if milestone is None:
            abort(404)
        session.delete(milestone)
    if is_api_request:
        return {"ok": True}
    flash("Milestone deleted.", "success")
    return redirect(next_url)
