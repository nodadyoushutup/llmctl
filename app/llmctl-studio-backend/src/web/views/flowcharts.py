from .shared import *  # noqa: F401,F403

from core.models import RAGRetrievalAudit

__all__ = ['list_decision_node_artifacts', 'view_decision_node_artifact', 'list_flowcharts', 'new_flowchart', 'create_flowchart', 'view_flowchart', 'view_flowchart_history', 'view_flowchart_history_run', 'edit_flowchart', 'update_flowchart', 'delete_flowchart', 'get_flowchart_graph', 'upsert_flowchart_graph', 'validate_flowchart', 'run_flowchart_route', 'view_flowchart_run', 'flowchart_run_status', 'flowchart_run_trace', 'control_flowchart_run', 'flowchart_runtime_status', 'cancel_flowchart_run', 'get_flowchart_node_utilities', 'set_flowchart_node_model', 'attach_flowchart_node_mcp', 'detach_flowchart_node_mcp', 'attach_flowchart_node_script', 'detach_flowchart_node_script', 'reorder_flowchart_node_scripts']

@bp.get("/flowcharts/<int:flowchart_id>/nodes/<int:flowchart_node_id>/decision-artifacts")
def list_decision_node_artifacts(flowchart_id: int, flowchart_node_id: int):
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    parsed, error_response = _parse_node_artifact_list_params(
        request_id=request_id,
        correlation_id=correlation_id,
    )
    if error_response is not None:
        return error_response
    assert parsed is not None
    with session_scope() as session:
        node = session.get(FlowchartNode, flowchart_node_id)
        if node is None or int(node.flowchart_id) != flowchart_id:
            return _workflow_error_envelope(
                code="not_found",
                message=f"Flowchart node {flowchart_node_id} was not found in flowchart {flowchart_id}.",
                details={"flowchart_id": flowchart_id, "flowchart_node_id": flowchart_node_id},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 404
        if str(node.node_type or "").strip().lower() != FLOWCHART_NODE_TYPE_DECISION:
            return _workflow_error_envelope(
                code="invalid_request",
                message=f"Flowchart node {flowchart_node_id} is not a decision node.",
                details={"flowchart_id": flowchart_id, "flowchart_node_id": flowchart_node_id},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 400
        stmt = select(NodeArtifact).where(
            NodeArtifact.artifact_type == NODE_ARTIFACT_TYPE_DECISION,
            NodeArtifact.flowchart_id == flowchart_id,
            NodeArtifact.flowchart_node_id == flowchart_node_id,
        )
        flowchart_run_id = parsed["flowchart_run_id"]
        flowchart_run_node_id = parsed["flowchart_run_node_id"]
        if isinstance(flowchart_run_id, int):
            stmt = stmt.where(NodeArtifact.flowchart_run_id == flowchart_run_id)
        if isinstance(flowchart_run_node_id, int):
            stmt = stmt.where(NodeArtifact.flowchart_run_node_id == flowchart_run_node_id)
        if parsed["descending"]:
            stmt = stmt.order_by(NodeArtifact.created_at.desc(), NodeArtifact.id.desc())
        else:
            stmt = stmt.order_by(NodeArtifact.created_at.asc(), NodeArtifact.id.asc())
        artifacts = (
            session.execute(stmt.limit(int(parsed["limit"])).offset(int(parsed["offset"])))
            .scalars()
            .all()
        )
    payload: dict[str, object] = {
        "ok": True,
        "flowchart_id": flowchart_id,
        "flowchart_node_id": flowchart_node_id,
        "count": len(artifacts),
        "limit": int(parsed["limit"]),
        "offset": int(parsed["offset"]),
        "items": [_serialize_node_artifact(item) for item in artifacts],
        "request_id": request_id,
    }
    if correlation_id:
        payload["correlation_id"] = correlation_id
    return payload

@bp.get(
    "/flowcharts/<int:flowchart_id>/nodes/<int:flowchart_node_id>/decision-artifacts/<int:artifact_id>"
)
def view_decision_node_artifact(flowchart_id: int, flowchart_node_id: int, artifact_id: int):
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    with session_scope() as session:
        node = session.get(FlowchartNode, flowchart_node_id)
        if node is None or int(node.flowchart_id) != flowchart_id:
            return _workflow_error_envelope(
                code="not_found",
                message=f"Flowchart node {flowchart_node_id} was not found in flowchart {flowchart_id}.",
                details={"flowchart_id": flowchart_id, "flowchart_node_id": flowchart_node_id},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 404
        if str(node.node_type or "").strip().lower() != FLOWCHART_NODE_TYPE_DECISION:
            return _workflow_error_envelope(
                code="invalid_request",
                message=f"Flowchart node {flowchart_node_id} is not a decision node.",
                details={"flowchart_id": flowchart_id, "flowchart_node_id": flowchart_node_id},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 400
        artifact = (
            session.execute(
                select(NodeArtifact).where(
                    NodeArtifact.id == artifact_id,
                    NodeArtifact.artifact_type == NODE_ARTIFACT_TYPE_DECISION,
                    NodeArtifact.flowchart_id == flowchart_id,
                    NodeArtifact.flowchart_node_id == flowchart_node_id,
                )
            )
            .scalars()
            .first()
        )
        if artifact is None:
            return _workflow_error_envelope(
                code="not_found",
                message=(
                    "Decision artifact "
                    f"{artifact_id} was not found for node {flowchart_node_id} in flowchart {flowchart_id}."
                ),
                details={
                    "flowchart_id": flowchart_id,
                    "flowchart_node_id": flowchart_node_id,
                    "artifact_id": artifact_id,
                },
                request_id=request_id,
                correlation_id=correlation_id,
            ), 404
    payload: dict[str, object] = {
        "ok": True,
        "flowchart_id": flowchart_id,
        "flowchart_node_id": flowchart_node_id,
        "item": _serialize_node_artifact(artifact),
        "request_id": request_id,
    }
    if correlation_id:
        payload["correlation_id"] = correlation_id
    return payload

@bp.get("/flowcharts")
def list_flowcharts():
    with session_scope() as session:
        rows = session.execute(
            select(
                Flowchart,
                func.count(func.distinct(FlowchartNode.id)),
                func.count(func.distinct(FlowchartEdge.id)),
                func.count(func.distinct(FlowchartRun.id)),
            )
            .outerjoin(FlowchartNode, FlowchartNode.flowchart_id == Flowchart.id)
            .outerjoin(FlowchartEdge, FlowchartEdge.flowchart_id == Flowchart.id)
            .outerjoin(FlowchartRun, FlowchartRun.flowchart_id == Flowchart.id)
            .group_by(Flowchart.id)
            .order_by(Flowchart.created_at.desc())
        ).all()
    flowcharts = [
        {
            **_serialize_flowchart(flowchart),
            "node_count": int(node_count or 0),
            "edge_count": int(edge_count or 0),
            "run_count": int(run_count or 0),
        }
        for flowchart, node_count, edge_count, run_count in rows
    ]
    if _flowchart_wants_json():
        return {"flowcharts": flowcharts}
    return render_template(
        "flowcharts.html",
        flowcharts=flowcharts,
        page_title="Flowcharts",
        active_page="flowcharts",
    )

@bp.get("/flowcharts/new")
def new_flowchart():
    with session_scope() as session:
        catalog = _flowchart_catalog(session)
    defaults = {
        "max_node_executions": None,
        "max_runtime_minutes": None,
        "max_parallel_nodes": 1,
        "node_types": list(FLOWCHART_NODE_TYPE_CHOICES),
    }
    if _flowchart_wants_json():
        return {"defaults": defaults, "catalog": catalog}
    return render_template(
        "flowchart_new.html",
        defaults=defaults,
        catalog=catalog,
        page_title="Create Flowchart",
        active_page="flowcharts",
    )

@bp.post("/flowcharts")
def create_flowchart():
    payload = _flowchart_request_payload()
    is_api_request = request.is_json or bool(payload) or _flowchart_wants_json()
    name = str((payload.get("name") if payload else request.form.get("name")) or "").strip()
    description = str(
        (payload.get("description") if payload else request.form.get("description")) or ""
    ).strip()
    max_node_executions_raw = (
        payload.get("max_node_executions")
        if payload
        else request.form.get("max_node_executions")
    )
    max_runtime_minutes_raw = (
        payload.get("max_runtime_minutes")
        if payload
        else request.form.get("max_runtime_minutes")
    )
    max_parallel_nodes_raw = (
        payload.get("max_parallel_nodes")
        if payload
        else request.form.get("max_parallel_nodes")
    )
    if not name:
        if is_api_request:
            return {"error": "Flowchart name is required."}, 400
        flash("Flowchart name is required.", "error")
        return redirect(url_for("agents.new_flowchart"))
    try:
        max_node_executions = _coerce_optional_int(
            max_node_executions_raw,
            field_name="max_node_executions",
            minimum=1,
        )
        max_runtime_minutes = _coerce_optional_int(
            max_runtime_minutes_raw,
            field_name="max_runtime_minutes",
            minimum=1,
        )
        max_parallel_nodes = _coerce_optional_int(
            max_parallel_nodes_raw,
            field_name="max_parallel_nodes",
            minimum=1,
        )
    except ValueError as exc:
        if is_api_request:
            return {"error": str(exc)}, 400
        flash(str(exc), "error")
        return redirect(url_for("agents.new_flowchart"))
    if max_parallel_nodes is None:
        max_parallel_nodes = 1

    with session_scope() as session:
        flowchart = Flowchart.create(
            session,
            name=name,
            description=description or None,
            max_node_executions=max_node_executions,
            max_runtime_minutes=max_runtime_minutes,
            max_parallel_nodes=max_parallel_nodes,
        )
        _ensure_flowchart_start_node(session, flowchart_id=flowchart.id)
    flowchart_payload = _serialize_flowchart(flowchart)
    if is_api_request:
        return {"flowchart": flowchart_payload}, 201
    flash("Flowchart created.", "success")
    return redirect(url_for("agents.view_flowchart", flowchart_id=int(flowchart_payload["id"])))

@bp.get("/flowcharts/<int:flowchart_id>")
def view_flowchart(flowchart_id: int):
    wants_json = _flowchart_wants_json()
    selected_node_raw = (request.args.get("node") or "").strip()
    selected_node_id: int | None = None
    active_run_id: int | None = None
    if selected_node_raw:
        try:
            parsed_selected_node_id = int(selected_node_raw)
        except ValueError:
            parsed_selected_node_id = 0
        if parsed_selected_node_id > 0:
            selected_node_id = parsed_selected_node_id
    with session_scope() as session:
        existing_flowchart = session.get(Flowchart, flowchart_id)
        if existing_flowchart is None:
            abort(404)
        _ensure_flowchart_start_node(session, flowchart_id=flowchart_id)
        flowchart = (
            session.execute(
                select(Flowchart)
                .options(
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.mcp_servers),
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.scripts),
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.skills),
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.attachments),
                    selectinload(Flowchart.edges),
                )
                .where(Flowchart.id == flowchart_id)
            )
            .scalars()
            .first()
        )
        runs: list[FlowchartRun] = []
        if wants_json:
            runs = (
                session.execute(
                    select(FlowchartRun)
                    .where(FlowchartRun.flowchart_id == flowchart_id)
                    .order_by(FlowchartRun.created_at.desc())
                    .limit(25)
                )
                .scalars()
                .all()
            )
        catalog = _flowchart_catalog(session)
        validation_errors = _validate_flowchart_graph(flowchart.nodes, flowchart.edges)
        for node in flowchart.nodes:
            if (
                node.node_type in FLOWCHART_NODE_TYPE_WITH_REF
                and node.ref_id is not None
                and not _flowchart_ref_exists(
                    session,
                    node_type=node.node_type,
                    ref_id=node.ref_id,
                )
            ):
                validation_errors.append(
                    f"Node {node.id} ({node.node_type}) ref_id {node.ref_id} does not exist."
                )
        if selected_node_id is not None and all(
            node.id != selected_node_id for node in flowchart.nodes
        ):
            selected_node_id = None
        active_run_id = (
            session.execute(
                select(FlowchartRun.id)
                .where(
                    FlowchartRun.flowchart_id == flowchart_id,
                    FlowchartRun.status.in_(["queued", "running", "stopping", "pausing", "paused"]),
                )
                .order_by(FlowchartRun.created_at.desc(), FlowchartRun.id.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
    flowchart_payload = _serialize_flowchart(flowchart)
    graph_payload = {
        "nodes": [_serialize_flowchart_node(node) for node in flowchart.nodes],
        "edges": [_serialize_flowchart_edge(edge) for edge in flowchart.edges],
    }
    runs_payload = [_serialize_flowchart_run(run) for run in runs]
    validation_payload = {
        "valid": len(validation_errors) == 0,
        "errors": validation_errors,
    }
    if wants_json:
        return {
            "flowchart": flowchart_payload,
            "graph": graph_payload,
            "runs": runs_payload,
            "validation": validation_payload,
        }
    return render_template(
        "flowchart_detail.html",
        flowchart=flowchart_payload,
        graph=graph_payload,
        validation=validation_payload,
        catalog=catalog,
        node_types=list(FLOWCHART_NODE_TYPE_CHOICES),
        rag_palette_state=str(
            ((catalog.get("rag_health") or {}).get("state"))
            or RAG_DOMAIN_HEALTH_UNCONFIGURED
        ),
        selected_node_id=selected_node_id,
        active_run_id=active_run_id,
        page_title=f"Flowchart - {flowchart_payload['name']}",
        active_page="flowcharts",
    )

@bp.get("/flowcharts/<int:flowchart_id>/history")
def view_flowchart_history(flowchart_id: int):
    with session_scope() as session:
        flowchart = session.get(Flowchart, flowchart_id)
        if flowchart is None:
            abort(404)
        start_node_id = (
            session.execute(
                select(FlowchartNode.id)
                .where(
                    FlowchartNode.flowchart_id == flowchart_id,
                    FlowchartNode.node_type == FLOWCHART_NODE_TYPE_START,
                )
                .order_by(FlowchartNode.id.asc())
            )
            .scalars()
            .first()
        )
        run_rows = (
            session.execute(
                select(FlowchartRun, func.count(FlowchartRunNode.id))
                .outerjoin(
                    FlowchartRunNode,
                    FlowchartRunNode.flowchart_run_id == FlowchartRun.id,
                )
                .where(FlowchartRun.flowchart_id == flowchart_id)
                .group_by(FlowchartRun.id)
                .order_by(FlowchartRun.created_at.desc())
            )
            .all()
        )

        run_ids = [run.id for run, _ in run_rows]
        start_counts: dict[int, int] = {}
        if start_node_id is not None and run_ids:
            start_count_rows = (
                session.execute(
                    select(
                        FlowchartRunNode.flowchart_run_id,
                        func.count(FlowchartRunNode.id),
                    )
                    .where(
                        FlowchartRunNode.flowchart_run_id.in_(run_ids),
                        FlowchartRunNode.flowchart_node_id == start_node_id,
                    )
                    .group_by(FlowchartRunNode.flowchart_run_id)
                )
                .all()
            )
            start_counts = {
                int(run_id): int(count or 0) for run_id, count in start_count_rows
            }

    flowchart_payload = _serialize_flowchart(flowchart)
    runs_payload: list[dict[str, object]] = []
    for run, node_run_count in run_rows:
        node_count = int(node_run_count or 0)
        cycle_count = start_counts.get(run.id, 1 if node_count > 0 else 0)
        runs_payload.append(
            {
                **_serialize_flowchart_run(run),
                "node_run_count": node_count,
                "cycle_count": int(cycle_count),
            }
        )

    if _flowchart_wants_json():
        return {
            "flowchart": flowchart_payload,
            "runs": runs_payload,
        }
    return render_template(
        "flowchart_history.html",
        flowchart=flowchart_payload,
        runs=runs_payload,
        status_class=_flowchart_status_class,
        page_title=f"Flowchart History - {flowchart_payload['name']}",
        active_page="flowcharts",
    )

@bp.get("/flowcharts/<int:flowchart_id>/history/<int:run_id>")
def view_flowchart_history_run(flowchart_id: int, run_id: int):
    with session_scope() as session:
        flowchart = session.get(Flowchart, flowchart_id)
        if flowchart is None:
            abort(404)
        flowchart_run = session.get(FlowchartRun, run_id)
        if flowchart_run is None or flowchart_run.flowchart_id != flowchart_id:
            abort(404)
        _backfill_flowchart_node_activity_tasks(
            session,
            flowchart_id=flowchart_id,
            run_id=run_id,
        )

        start_node_id = (
            session.execute(
                select(FlowchartNode.id)
                .where(
                    FlowchartNode.flowchart_id == flowchart_id,
                    FlowchartNode.node_type == FLOWCHART_NODE_TYPE_START,
                )
                .order_by(FlowchartNode.id.asc())
            )
            .scalars()
            .first()
        )

        node_run_rows = (
            session.execute(
                select(FlowchartRunNode, FlowchartNode)
                .join(FlowchartNode, FlowchartNode.id == FlowchartRunNode.flowchart_node_id)
                .where(FlowchartRunNode.flowchart_run_id == run_id)
                .order_by(FlowchartRunNode.created_at.asc(), FlowchartRunNode.id.asc())
            )
            .all()
        )
        artifact_history_by_node_run: dict[int, list[dict[str, object]]] = {}
        artifacts = (
            session.execute(
                select(NodeArtifact)
                .where(NodeArtifact.flowchart_run_id == run_id)
                .order_by(NodeArtifact.created_at.desc(), NodeArtifact.id.desc())
            )
            .scalars()
            .all()
        )
        for artifact in artifacts:
            node_run_id = int(artifact.flowchart_run_node_id or 0)
            if node_run_id <= 0:
                continue
            artifact_history_by_node_run.setdefault(node_run_id, []).append(
                _serialize_node_artifact(artifact)
            )
        node_task_ids = sorted(
            {
                int(node_run.agent_task_id)
                for node_run, _node in node_run_rows
                if node_run.agent_task_id is not None
            }
        )
        node_task_map: dict[int, AgentTask] = {}
        if node_task_ids:
            tasks = (
                session.execute(
                    select(AgentTask).where(AgentTask.id.in_(node_task_ids))
                )
                .scalars()
                .all()
            )
            node_task_map = {int(task.id): task for task in tasks}

    flowchart_payload = _serialize_flowchart(flowchart)
    run_payload = _serialize_flowchart_run(flowchart_run)

    node_runs_payload: list[dict[str, object]] = []
    cycle_index = 0
    for node_run, node in node_run_rows:
        if start_node_id is not None and node_run.flowchart_node_id == start_node_id:
            cycle_index += 1
        if cycle_index == 0:
            cycle_index = 1
        node_runs_payload.append(
            {
                **_serialize_flowchart_run_node(
                    node_run,
                    node_task_map.get(int(node_run.agent_task_id or 0)),
                    artifact_history=artifact_history_by_node_run.get(node_run.id, []),
                ),
                "node_title": node.title or f"{node.node_type} node",
                "node_type": node.node_type,
                "cycle_index": cycle_index,
            }
        )
    cycle_count = cycle_index if cycle_index > 0 else (1 if node_runs_payload else 0)
    run_payload["node_run_count"] = len(node_runs_payload)
    run_payload["cycle_count"] = int(cycle_count)

    if _flowchart_wants_json():
        return {
            "flowchart": flowchart_payload,
            "flowchart_run": run_payload,
            "node_runs": node_runs_payload,
        }
    return render_template(
        "flowchart_history_run_detail.html",
        flowchart=flowchart_payload,
        flowchart_run=run_payload,
        node_runs=node_runs_payload,
        status_class=_flowchart_status_class,
        page_title=f"Flowchart Run {run_id} - {flowchart_payload['name']}",
        active_page="flowcharts",
    )

@bp.get("/flowcharts/<int:flowchart_id>/edit")
def edit_flowchart(flowchart_id: int):
    with session_scope() as session:
        flowchart = session.get(Flowchart, flowchart_id)
        if flowchart is None:
            abort(404)
        catalog = _flowchart_catalog(session)
    flowchart_payload = _serialize_flowchart(flowchart)
    if _flowchart_wants_json():
        return {
            "flowchart": flowchart_payload,
            "catalog": catalog,
        }
    return render_template(
        "flowchart_edit.html",
        flowchart=flowchart_payload,
        catalog=catalog,
        page_title="Edit Flowchart",
        active_page="flowcharts",
    )

@bp.post("/flowcharts/<int:flowchart_id>")
def update_flowchart(flowchart_id: int):
    payload = _flowchart_request_payload()
    is_api_request = request.is_json or bool(payload) or _flowchart_wants_json()
    name = str((payload.get("name") if payload else request.form.get("name")) or "").strip()
    description = str(
        (payload.get("description") if payload else request.form.get("description")) or ""
    ).strip()
    max_node_executions_raw = (
        payload.get("max_node_executions")
        if payload
        else request.form.get("max_node_executions")
    )
    max_runtime_minutes_raw = (
        payload.get("max_runtime_minutes")
        if payload
        else request.form.get("max_runtime_minutes")
    )
    max_parallel_nodes_raw = (
        payload.get("max_parallel_nodes")
        if payload
        else request.form.get("max_parallel_nodes")
    )
    if not name:
        if is_api_request:
            return {"error": "Flowchart name is required."}, 400
        flash("Flowchart name is required.", "error")
        return redirect(url_for("agents.edit_flowchart", flowchart_id=flowchart_id))
    try:
        max_node_executions = _coerce_optional_int(
            max_node_executions_raw,
            field_name="max_node_executions",
            minimum=1,
        )
        max_runtime_minutes = _coerce_optional_int(
            max_runtime_minutes_raw,
            field_name="max_runtime_minutes",
            minimum=1,
        )
        max_parallel_nodes = _coerce_optional_int(
            max_parallel_nodes_raw,
            field_name="max_parallel_nodes",
            minimum=1,
        )
    except ValueError as exc:
        if is_api_request:
            return {"error": str(exc)}, 400
        flash(str(exc), "error")
        return redirect(url_for("agents.edit_flowchart", flowchart_id=flowchart_id))
    if max_parallel_nodes is None:
        max_parallel_nodes = 1

    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.view_flowchart", flowchart_id=flowchart_id)
    )
    with session_scope() as session:
        flowchart = session.get(Flowchart, flowchart_id)
        if flowchart is None:
            abort(404)
        flowchart.name = name
        flowchart.description = description or None
        flowchart.max_node_executions = max_node_executions
        flowchart.max_runtime_minutes = max_runtime_minutes
        flowchart.max_parallel_nodes = max_parallel_nodes
    flowchart_payload = _serialize_flowchart(flowchart)
    if is_api_request:
        return {"flowchart": flowchart_payload}
    flash("Flowchart updated.", "success")
    return redirect(redirect_target)

@bp.post("/flowcharts/<int:flowchart_id>/delete")
def delete_flowchart(flowchart_id: int):
    is_api_request = request.is_json or _flowchart_wants_json()
    next_url = _safe_redirect_target(request.form.get("next"), url_for("agents.list_flowcharts"))
    with session_scope() as session:
        flowchart = session.get(Flowchart, flowchart_id)
        if flowchart is None:
            abort(404)

        node_ids = (
            session.execute(
                select(FlowchartNode.id).where(FlowchartNode.flowchart_id == flowchart_id)
            )
            .scalars()
            .all()
        )
        run_ids = (
            session.execute(
                select(FlowchartRun.id).where(FlowchartRun.flowchart_id == flowchart_id)
            )
            .scalars()
            .all()
        )

        task_ids = set(
            session.execute(
                select(AgentTask.id).where(AgentTask.flowchart_id == flowchart_id)
            )
            .scalars()
            .all()
        )
        if run_ids:
            task_ids.update(
                session.execute(
                    select(AgentTask.id).where(AgentTask.flowchart_run_id.in_(run_ids))
                )
                .scalars()
                .all()
            )
            session.execute(
                delete(FlowchartRunNode).where(FlowchartRunNode.flowchart_run_id.in_(run_ids))
            )
        if node_ids:
            task_ids.update(
                session.execute(
                    select(AgentTask.id).where(AgentTask.flowchart_node_id.in_(node_ids))
                )
                .scalars()
                .all()
            )
            session.execute(
                delete(flowchart_node_mcp_servers).where(
                    flowchart_node_mcp_servers.c.flowchart_node_id.in_(node_ids)
                )
            )
            session.execute(
                delete(flowchart_node_scripts).where(
                    flowchart_node_scripts.c.flowchart_node_id.in_(node_ids)
                )
            )
            session.execute(
                delete(flowchart_node_skills).where(
                    flowchart_node_skills.c.flowchart_node_id.in_(node_ids)
                )
            )
            session.execute(
                delete(flowchart_node_attachments).where(
                    flowchart_node_attachments.c.flowchart_node_id.in_(node_ids)
                )
            )

        if task_ids:
            tasks = (
                session.execute(select(AgentTask).where(AgentTask.id.in_(task_ids)))
                .scalars()
                .all()
            )
            for task in tasks:
                session.delete(task)
        session.execute(delete(FlowchartEdge).where(FlowchartEdge.flowchart_id == flowchart_id))
        if node_ids:
            session.execute(delete(FlowchartNode).where(FlowchartNode.id.in_(node_ids)))
        if run_ids:
            session.execute(delete(FlowchartRun).where(FlowchartRun.id.in_(run_ids)))

        session.delete(flowchart)
    if is_api_request:
        return {"deleted": True, "flowchart_id": flowchart_id}
    flash("Flowchart deleted.", "success")
    return redirect(next_url)

@bp.get("/flowcharts/<int:flowchart_id>/graph")
def get_flowchart_graph(flowchart_id: int):
    with session_scope() as session:
        existing_flowchart = session.get(Flowchart, flowchart_id)
        if existing_flowchart is None:
            abort(404)
        _ensure_flowchart_start_node(session, flowchart_id=flowchart_id)
        flowchart = (
            session.execute(
                select(Flowchart)
                .options(
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.mcp_servers),
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.scripts),
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.skills),
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.attachments),
                    selectinload(Flowchart.edges),
                )
                .where(Flowchart.id == flowchart_id)
            )
            .scalars()
            .first()
        )
        errors = _validate_flowchart_graph(flowchart.nodes, flowchart.edges)
        for node in flowchart.nodes:
            if (
                node.node_type in FLOWCHART_NODE_TYPE_WITH_REF
                and node.ref_id is not None
                and not _flowchart_ref_exists(
                    session,
                    node_type=node.node_type,
                    ref_id=node.ref_id,
                )
            ):
                errors.append(
                    f"Node {node.id} ({node.node_type}) ref_id {node.ref_id} does not exist."
                )
    return {
        "flowchart_id": flowchart_id,
        "nodes": [_serialize_flowchart_node(node) for node in flowchart.nodes],
        "edges": [_serialize_flowchart_edge(edge) for edge in flowchart.edges],
        "validation": {"valid": len(errors) == 0, "errors": errors},
    }

@bp.post("/flowcharts/<int:flowchart_id>/graph")
def upsert_flowchart_graph(flowchart_id: int):
    payload = _flowchart_request_payload()
    if not payload:
        graph_json = request.form.get("graph_json", "").strip()
        if graph_json:
            try:
                parsed = json.loads(graph_json)
            except json.JSONDecodeError:
                return {"error": "graph_json must be valid JSON."}, 400
            if isinstance(parsed, dict):
                payload = parsed

    raw_nodes = payload.get("nodes")
    raw_edges = payload.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        return {"error": "Graph payload must contain nodes[] and edges[] arrays."}, 400
    requires_memory_nodes = any(
        isinstance(node, dict)
        and str(node.get("node_type") or "").strip().lower()
        == FLOWCHART_NODE_TYPE_MEMORY
        for node in raw_nodes
    )
    if requires_memory_nodes:
        sync_integrated_mcp_servers()

    try:
        with session_scope() as session:
            flowchart = session.get(Flowchart, flowchart_id)
            if flowchart is None:
                abort(404)

            existing_nodes = (
                session.execute(
                    select(FlowchartNode)
                    .options(
                        selectinload(FlowchartNode.mcp_servers),
                        selectinload(FlowchartNode.scripts),
                        selectinload(FlowchartNode.skills),
                        selectinload(FlowchartNode.attachments),
                    )
                    .where(FlowchartNode.flowchart_id == flowchart_id)
                )
                .scalars()
                .all()
            )
            existing_nodes_by_id = {node.id: node for node in existing_nodes}
            existing_start_node = next(
                (
                    node
                    for node in existing_nodes
                    if node.node_type == FLOWCHART_NODE_TYPE_START
                ),
                None,
            )
            llmctl_mcp_server = (
                session.execute(
                    select(MCPServer).where(
                        MCPServer.server_key == INTEGRATED_MCP_LLMCTL_KEY
                    )
                )
                .scalars()
                .first()
            )
            keep_node_ids: set[int] = set()
            token_to_node_id: dict[str, int] = {}
            node_type_by_id: dict[int, str] = {}
            flowchart_nodes_by_id: dict[int, FlowchartNode] = {}

            for index, raw_node in enumerate(raw_nodes):
                if not isinstance(raw_node, dict):
                    raise ValueError(f"nodes[{index}] must be an object.")
                node_type = str(raw_node.get("node_type") or "").strip().lower()
                if node_type not in FLOWCHART_NODE_TYPE_CHOICES:
                    raise ValueError(f"nodes[{index}] has invalid node_type '{node_type}'.")
                node_id_raw = raw_node.get("id")
                node_id = _coerce_optional_int(node_id_raw, field_name=f"nodes[{index}].id")
                ref_id = _coerce_optional_int(
                    raw_node.get("ref_id"), field_name=f"nodes[{index}].ref_id"
                )
                model_field_present = "model_id" in raw_node
                model_id = _coerce_optional_int(
                    raw_node.get("model_id"), field_name=f"nodes[{index}].model_id"
                )
                x = _coerce_float(raw_node.get("x"), field_name=f"nodes[{index}].x")
                y = _coerce_float(raw_node.get("y"), field_name=f"nodes[{index}].y")
                title = str(raw_node.get("title") or "").strip() or None
                config = raw_node.get("config")
                if config is None and "config_json" in raw_node:
                    config = raw_node.get("config_json")
                if config is None:
                    config_payload: dict[str, object] = {}
                elif isinstance(config, dict):
                    config_payload = config
                else:
                    raise ValueError(f"nodes[{index}].config must be an object.")
                _sanitize_flowchart_node_agent_config(
                    session=session,
                    config_payload=config_payload,
                    field_name=f"nodes[{index}].config.agent_id",
                )
                if node_type == FLOWCHART_NODE_TYPE_TASK:
                    raw_integration_keys = config_payload.get("integration_keys")
                    if raw_integration_keys is not None:
                        if not isinstance(raw_integration_keys, list):
                            raise ValueError(
                                f"nodes[{index}].config.integration_keys must be an array."
                            )
                        (
                            selected_integration_keys,
                            invalid_integration_keys,
                        ) = validate_task_integration_keys(raw_integration_keys)
                        if invalid_integration_keys:
                            raise ValueError(
                                f"nodes[{index}].config.integration_keys contains invalid key(s): "
                                + ", ".join(invalid_integration_keys)
                                + "."
                            )
                        config_payload["integration_keys"] = selected_integration_keys
                    config_payload.pop("route_key_path", None)
                else:
                    config_payload.pop("integration_keys", None)
                if node_type == FLOWCHART_NODE_TYPE_RAG:
                    selected_model_provider: str | None = None
                    if model_id is not None:
                        selected_model = session.get(LLMModel, model_id)
                        if selected_model is None:
                            raise ValueError(f"nodes[{index}].model_id {model_id} was not found.")
                        selected_model_provider = selected_model.provider
                    config_payload = _sanitize_rag_node_config(
                        config_payload,
                        model_provider=selected_model_provider,
                    )
                if node_type == FLOWCHART_NODE_TYPE_MILESTONE:
                    config_payload = _sanitize_milestone_node_config(
                        config_payload,
                        field_prefix=f"nodes[{index}].config",
                    )
                if node_type == FLOWCHART_NODE_TYPE_PLAN:
                    config_payload = _sanitize_plan_node_config(
                        config_payload,
                        field_prefix=f"nodes[{index}].config",
                    )
                if node_type == FLOWCHART_NODE_TYPE_MEMORY:
                    config_payload = _sanitize_memory_node_config(config_payload)
                config_payload = _sanitize_flowchart_node_routing_config(
                    config_payload,
                    field_prefix=f"nodes[{index}].config",
                )

                compatibility_errors = _validate_flowchart_utility_compatibility(
                    node_type,
                    model_id=model_id if model_field_present else None,
                )
                if compatibility_errors:
                    raise ValueError(compatibility_errors[0])

                flowchart_node = (
                    existing_nodes_by_id.get(node_id) if node_id is not None else None
                )
                existing_node_type = flowchart_node.node_type if flowchart_node is not None else None
                existing_ref_id = flowchart_node.ref_id if flowchart_node is not None else None
                if (
                    flowchart_node is None
                    and node_type == FLOWCHART_NODE_TYPE_START
                    and existing_start_node is not None
                ):
                    flowchart_node = existing_start_node
                    existing_node_type = flowchart_node.node_type
                    existing_ref_id = flowchart_node.ref_id
                if flowchart_node is None:
                    flowchart_node = FlowchartNode.create(
                        session,
                        flowchart_id=flowchart_id,
                        node_type=node_type,
                        ref_id=ref_id,
                        title=title,
                        x=x,
                        y=y,
                        config_json=json.dumps(config_payload, sort_keys=True),
                    )
                else:
                    flowchart_node.node_type = node_type
                    if node_type in FLOWCHART_NODE_TYPE_AUTO_REF:
                        if ref_id is not None:
                            flowchart_node.ref_id = ref_id
                        elif existing_node_type == node_type:
                            flowchart_node.ref_id = existing_ref_id
                        else:
                            flowchart_node.ref_id = None
                    else:
                        flowchart_node.ref_id = ref_id
                    flowchart_node.title = title
                    flowchart_node.x = x
                    flowchart_node.y = y
                    flowchart_node.config_json = json.dumps(config_payload, sort_keys=True)
                if node_type in FLOWCHART_NODE_TYPE_AUTO_REF:
                    _ensure_flowchart_auto_ref(session, flowchart_node=flowchart_node)
                if model_field_present:
                    if model_id is not None and session.get(LLMModel, model_id) is None:
                        raise ValueError(f"nodes[{index}].model_id {model_id} was not found.")
                    flowchart_node.model_id = model_id

                if node_type == FLOWCHART_NODE_TYPE_RAG:
                    flowchart_node.mcp_servers = []
                elif node_type == FLOWCHART_NODE_TYPE_MEMORY:
                    if llmctl_mcp_server is None:
                        raise ValueError(
                            "System-managed LLMCTL MCP server is missing. Sync integrations and retry."
                        )
                    flowchart_node.mcp_servers = [llmctl_mcp_server]
                elif "mcp_server_ids" in raw_node:
                    mcp_server_ids_raw = raw_node.get("mcp_server_ids")
                    if not isinstance(mcp_server_ids_raw, list):
                        raise ValueError(f"nodes[{index}].mcp_server_ids must be an array.")
                    mcp_server_ids: list[int] = []
                    for mcp_index, mcp_id_raw in enumerate(mcp_server_ids_raw):
                        mcp_id = _coerce_optional_int(
                            mcp_id_raw,
                            field_name=f"nodes[{index}].mcp_server_ids[{mcp_index}]",
                            minimum=1,
                        )
                        if mcp_id is None:
                            raise ValueError(
                                f"nodes[{index}].mcp_server_ids[{mcp_index}] is invalid."
                            )
                        mcp_server_ids.append(mcp_id)
                    compatibility_errors = _validate_flowchart_utility_compatibility(
                        node_type,
                        model_id=None,
                        mcp_server_ids=mcp_server_ids,
                    )
                    if compatibility_errors:
                        raise ValueError(compatibility_errors[0])
                    selected_servers = (
                        session.execute(select(MCPServer).where(MCPServer.id.in_(mcp_server_ids)))
                        .scalars()
                        .all()
                    )
                    if len(selected_servers) != len(set(mcp_server_ids)):
                        raise ValueError(f"nodes[{index}] contains unknown MCP server IDs.")
                    flowchart_node.mcp_servers = selected_servers

                if "script_ids" in raw_node:
                    script_ids_raw = raw_node.get("script_ids")
                    if not isinstance(script_ids_raw, list):
                        raise ValueError(f"nodes[{index}].script_ids must be an array.")
                    script_ids: list[int] = []
                    for script_index, script_id_raw in enumerate(script_ids_raw):
                        script_id = _coerce_optional_int(
                            script_id_raw,
                            field_name=f"nodes[{index}].script_ids[{script_index}]",
                            minimum=1,
                        )
                        if script_id is None:
                            raise ValueError(
                                f"nodes[{index}].script_ids[{script_index}] is invalid."
                            )
                        script_ids.append(script_id)
                    compatibility_errors = _validate_flowchart_utility_compatibility(
                        node_type,
                        model_id=None,
                        script_ids=script_ids,
                    )
                    if compatibility_errors:
                        raise ValueError(compatibility_errors[0])
                    selected_scripts = (
                        session.execute(select(Script).where(Script.id.in_(script_ids)))
                        .scalars()
                        .all()
                    )
                    if len(selected_scripts) != len(set(script_ids)):
                        raise ValueError(f"nodes[{index}] contains unknown script IDs.")
                    if any(is_legacy_skill_script_type(item.script_type) for item in selected_scripts):
                        raise ValueError(
                            "Legacy script_type=skill records cannot be attached. "
                            "Assign first-class Skills to an Agent instead."
                        )
                    _set_flowchart_node_scripts(session, flowchart_node.id, script_ids)

                if "attachment_ids" in raw_node:
                    attachment_ids_raw = raw_node.get("attachment_ids")
                    if not isinstance(attachment_ids_raw, list):
                        raise ValueError(f"nodes[{index}].attachment_ids must be an array.")
                    attachment_ids: list[int] = []
                    for attachment_index, attachment_id_raw in enumerate(attachment_ids_raw):
                        attachment_id = _coerce_optional_int(
                            attachment_id_raw,
                            field_name=f"nodes[{index}].attachment_ids[{attachment_index}]",
                            minimum=1,
                        )
                        if attachment_id is None:
                            raise ValueError(
                                f"nodes[{index}].attachment_ids[{attachment_index}] is invalid."
                            )
                        attachment_ids.append(attachment_id)
                    if len(attachment_ids) != len(set(attachment_ids)):
                        raise ValueError(f"nodes[{index}].attachment_ids cannot contain duplicates.")
                    compatibility_errors = _validate_flowchart_utility_compatibility(
                        node_type,
                        model_id=None,
                        attachment_ids=attachment_ids,
                    )
                    if compatibility_errors:
                        raise ValueError(compatibility_errors[0])
                    selected_attachments = (
                        session.execute(select(Attachment).where(Attachment.id.in_(attachment_ids)))
                        .scalars()
                        .all()
                    )
                    if len(selected_attachments) != len(set(attachment_ids)):
                        raise ValueError(f"nodes[{index}] contains unknown attachment IDs.")
                    _set_flowchart_node_attachments(session, flowchart_node.id, attachment_ids)

                if "skill_ids" in raw_node:
                    raise ValueError(
                        f"nodes[{index}].skill_ids is no longer writable; assign skills on the Agent."
                    )

                keep_node_ids.add(flowchart_node.id)
                if node_id_raw is not None:
                    token_to_node_id[str(node_id_raw)] = flowchart_node.id
                if raw_node.get("client_id") is not None:
                    token_to_node_id[str(raw_node["client_id"])] = flowchart_node.id
                token_to_node_id[str(flowchart_node.id)] = flowchart_node.id
                node_type_by_id[flowchart_node.id] = flowchart_node.node_type
                flowchart_nodes_by_id[flowchart_node.id] = flowchart_node

            session.execute(delete(FlowchartEdge).where(FlowchartEdge.flowchart_id == flowchart_id))

            decision_connector_ids_by_node: dict[int, list[str]] = {}
            decision_used_connector_ids_by_node: dict[int, set[str]] = {}
            decision_next_connector_index: dict[int, int] = {}

            def _next_decision_connector_id(source_node_id: int) -> str:
                used_ids = decision_used_connector_ids_by_node.setdefault(source_node_id, set())
                next_index = decision_next_connector_index.get(source_node_id, 1)
                while True:
                    candidate = f"connector_{next_index}"
                    next_index += 1
                    if candidate in used_ids:
                        continue
                    used_ids.add(candidate)
                    decision_next_connector_index[source_node_id] = next_index
                    return candidate

            for index, raw_edge in enumerate(raw_edges):
                if not isinstance(raw_edge, dict):
                    raise ValueError(f"edges[{index}] must be an object.")
                source_raw = raw_edge.get("source_node_id")
                target_raw = raw_edge.get("target_node_id")
                if source_raw is None and "source" in raw_edge:
                    source_raw = raw_edge.get("source")
                if target_raw is None and "target" in raw_edge:
                    target_raw = raw_edge.get("target")
                source_node_id = token_to_node_id.get(str(source_raw))
                target_node_id = token_to_node_id.get(str(target_raw))
                if source_node_id is None:
                    raise ValueError(f"edges[{index}].source_node_id is invalid.")
                if target_node_id is None:
                    raise ValueError(f"edges[{index}].target_node_id is invalid.")
                source_handle_id = _coerce_optional_handle_id(
                    raw_edge.get("source_handle_id"),
                    field_name=f"edges[{index}].source_handle_id",
                )
                target_handle_id = _coerce_optional_handle_id(
                    raw_edge.get("target_handle_id"),
                    field_name=f"edges[{index}].target_handle_id",
                )
                if "edge_mode" not in raw_edge:
                    raise ValueError(f"edges[{index}].edge_mode is required.")
                edge_mode = _coerce_flowchart_edge_mode(
                    raw_edge.get("edge_mode"),
                    field_name=f"edges[{index}].edge_mode",
                )
                control_points = _coerce_flowchart_edge_control_points(
                    raw_edge.get("control_points"),
                    field_name=f"edges[{index}].control_points",
                )
                control_point_style = _coerce_flowchart_edge_control_style(
                    raw_edge.get("control_point_style"),
                    field_name=f"edges[{index}].control_point_style",
                )
                condition_key = str(raw_edge.get("condition_key") or "").strip() or None
                source_node_type = node_type_by_id.get(source_node_id, "")
                if (
                    source_node_type == FLOWCHART_NODE_TYPE_DECISION
                    and edge_mode == FLOWCHART_EDGE_MODE_SOLID
                ):
                    used_ids = decision_used_connector_ids_by_node.setdefault(
                        source_node_id, set()
                    )
                    if condition_key is None or condition_key in used_ids:
                        condition_key = _next_decision_connector_id(source_node_id)
                    else:
                        used_ids.add(condition_key)
                    decision_connector_ids_by_node.setdefault(source_node_id, []).append(
                        condition_key
                    )
                label = str(raw_edge.get("label") or "").strip() or None
                FlowchartEdge.create(
                    session,
                    flowchart_id=flowchart_id,
                    source_node_id=source_node_id,
                    target_node_id=target_node_id,
                    source_handle_id=source_handle_id,
                    target_handle_id=target_handle_id,
                    edge_mode=edge_mode,
                    condition_key=condition_key,
                    label=label,
                    control_points_json=(
                        json.dumps(
                            {
                                "points": control_points,
                                "style": control_point_style,
                            },
                            sort_keys=True,
                        )
                        if control_points
                        or control_point_style != FLOWCHART_EDGE_CONTROL_STYLE_HARD
                        else None
                    ),
                )

            for node_id, flowchart_node in flowchart_nodes_by_id.items():
                if flowchart_node.node_type != FLOWCHART_NODE_TYPE_DECISION:
                    continue
                config_payload = _parse_json_dict(flowchart_node.config_json)
                existing_entries = _normalized_decision_conditions(
                    config_payload.get("decision_conditions")
                )
                existing_text_by_connector = {
                    entry["connector_id"]: entry["condition_text"]
                    for entry in existing_entries
                }
                connector_ids = decision_connector_ids_by_node.get(node_id, [])
                config_payload["decision_conditions"] = [
                    {
                        "connector_id": connector_id,
                        "condition_text": existing_text_by_connector.get(connector_id, ""),
                    }
                    for connector_id in connector_ids
                ]
                flowchart_node.config_json = json.dumps(config_payload, sort_keys=True)

            removed_node_ids = set(existing_nodes_by_id).difference(keep_node_ids)
            if removed_node_ids:
                removed_node_run_ids = select(FlowchartRunNode.id).where(
                    FlowchartRunNode.flowchart_node_id.in_(removed_node_ids)
                )
                # Preserve task history rows while allowing removed nodes to be deleted.
                session.execute(
                    update(AgentTask)
                    .where(AgentTask.flowchart_node_id.in_(removed_node_ids))
                    .values(flowchart_node_id=None)
                )
                # Preserve retrieval audit history rows that reference removed run-node rows.
                session.execute(
                    update(RAGRetrievalAudit)
                    .where(
                        RAGRetrievalAudit.flowchart_node_run_id.in_(removed_node_run_ids)
                    )
                    .values(flowchart_node_run_id=None)
                )
                # Historical run-node rows still hold strict FKs to flowchart_nodes.
                session.execute(
                    delete(FlowchartRunNode).where(
                        FlowchartRunNode.flowchart_node_id.in_(removed_node_ids)
                    )
                )
                session.execute(
                    delete(flowchart_node_mcp_servers).where(
                        flowchart_node_mcp_servers.c.flowchart_node_id.in_(removed_node_ids)
                    )
                )
                session.execute(
                    delete(flowchart_node_scripts).where(
                        flowchart_node_scripts.c.flowchart_node_id.in_(removed_node_ids)
                    )
                )
                session.execute(
                    delete(flowchart_node_skills).where(
                        flowchart_node_skills.c.flowchart_node_id.in_(removed_node_ids)
                    )
                )
                session.execute(
                    delete(flowchart_node_attachments).where(
                        flowchart_node_attachments.c.flowchart_node_id.in_(removed_node_ids)
                    )
                )
                session.execute(
                    delete(FlowchartNode).where(FlowchartNode.id.in_(removed_node_ids))
                )

    except ValueError as exc:
        return {"error": str(exc)}, 400

    return get_flowchart_graph(flowchart_id)

@bp.get("/flowcharts/<int:flowchart_id>/validate")
def validate_flowchart(flowchart_id: int):
    with session_scope() as session:
        flowchart = (
            session.execute(
                select(Flowchart)
                .options(
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.mcp_servers),
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.scripts),
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.skills),
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.attachments),
                    selectinload(Flowchart.edges),
                )
                .where(Flowchart.id == flowchart_id)
            )
            .scalars()
            .first()
        )
        if flowchart is None:
            abort(404)
        errors = _validate_flowchart_graph(flowchart.nodes, flowchart.edges)
        for node in flowchart.nodes:
            if (
                node.node_type in FLOWCHART_NODE_TYPE_WITH_REF
                and node.ref_id is not None
                and not _flowchart_ref_exists(
                    session,
                    node_type=node.node_type,
                    ref_id=node.ref_id,
                )
            ):
                errors.append(
                    f"Node {node.id} ({node.node_type}) ref_id {node.ref_id} does not exist."
                )
    return {
        "flowchart_id": flowchart_id,
        "valid": len(errors) == 0,
        "errors": errors,
    }

@bp.post("/flowcharts/<int:flowchart_id>/run")
def run_flowchart_route(flowchart_id: int):
    validation_errors: list[str] = []
    with session_scope() as session:
        flowchart = (
            session.execute(
                select(Flowchart)
                .options(
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.mcp_servers),
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.scripts),
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.skills),
                    selectinload(Flowchart.nodes).selectinload(FlowchartNode.attachments),
                    selectinload(Flowchart.edges),
                )
                .where(Flowchart.id == flowchart_id)
            )
            .scalars()
            .first()
        )
        if flowchart is None:
            abort(404)
        validation_errors = _validate_flowchart_graph(flowchart.nodes, flowchart.edges)
        for node in flowchart.nodes:
            if (
                node.node_type in FLOWCHART_NODE_TYPE_WITH_REF
                and node.ref_id is not None
                and not _flowchart_ref_exists(
                    session,
                    node_type=node.node_type,
                    ref_id=node.ref_id,
                )
            ):
                validation_errors.append(
                    f"Node {node.id} ({node.node_type}) ref_id {node.ref_id} does not exist."
                )
        if validation_errors:
            return {
                "error": "Flowchart graph validation failed.",
                "validation": {"valid": False, "errors": validation_errors},
            }, 400
        flowchart_run = FlowchartRun.create(
            session,
            flowchart_id=flowchart_id,
            status="queued",
        )
        run_id = flowchart_run.id

    async_result = run_flowchart.delay(flowchart_id, run_id)
    flowchart_run_payload: dict[str, object]
    with session_scope() as session:
        flowchart_run = session.get(FlowchartRun, run_id)
        if flowchart_run is None:
            abort(404)
        flowchart_run.celery_task_id = async_result.id
        flowchart_run_payload = _serialize_flowchart_run(flowchart_run)
    return {
        "flowchart_run": {
            **flowchart_run_payload,
            "validation": {"valid": True, "errors": []},
        }
    }, 202

@bp.get("/flowcharts/runs/<int:run_id>")
def view_flowchart_run(run_id: int):
    artifact_history_by_node_run: dict[int, list[dict[str, object]]] = {}
    with session_scope() as session:
        flowchart_run = session.get(FlowchartRun, run_id)
        if flowchart_run is None:
            abort(404)
        flowchart = session.get(Flowchart, flowchart_run.flowchart_id)
        node_runs = (
            session.execute(
                select(FlowchartRunNode)
                .where(FlowchartRunNode.flowchart_run_id == run_id)
                .order_by(
                    FlowchartRunNode.execution_index.asc(),
                    FlowchartRunNode.created_at.asc(),
                    FlowchartRunNode.id.asc(),
                )
            )
            .scalars()
            .all()
        )
        artifacts = (
            session.execute(
                select(NodeArtifact)
                .where(NodeArtifact.flowchart_run_id == run_id)
                .order_by(NodeArtifact.created_at.desc(), NodeArtifact.id.desc())
            )
            .scalars()
            .all()
        )
        for artifact in artifacts:
            node_run_id = artifact.flowchart_run_node_id
            if node_run_id is None:
                continue
            artifact_history_by_node_run.setdefault(node_run_id, []).append(
                _serialize_node_artifact(artifact)
            )
    return {
        "flowchart_run": _serialize_flowchart_run(flowchart_run),
        "flowchart": _serialize_flowchart(flowchart) if flowchart is not None else None,
        "node_runs": [
            _serialize_flowchart_run_node(
                node_run,
                artifact_history=artifact_history_by_node_run.get(node_run.id, []),
            )
            for node_run in node_runs
        ],
    }

@bp.get("/flowcharts/runs/<int:run_id>/status")
def flowchart_run_status(run_id: int):
    with session_scope() as session:
        flowchart_run = session.get(FlowchartRun, run_id)
        if flowchart_run is None:
            abort(404)
        rows = session.execute(
            select(FlowchartRunNode.status, func.count(FlowchartRunNode.id))
            .where(FlowchartRunNode.flowchart_run_id == run_id)
            .group_by(FlowchartRunNode.status)
        ).all()
        warning_rows = (
            session.execute(
                select(
                    FlowchartRunNode.id,
                    FlowchartRunNode.flowchart_node_id,
                    FlowchartRunNode.degraded_reason,
                    FlowchartRunNode.updated_at,
                )
                .where(
                    FlowchartRunNode.flowchart_run_id == run_id,
                    FlowchartRunNode.degraded_status.is_(True),
                )
                .order_by(FlowchartRunNode.updated_at.desc(), FlowchartRunNode.id.desc())
                .limit(25)
            )
            .all()
        )
    counts = {str(status): int(count or 0) for status, count in rows}
    warnings = [
        {
            "flowchart_run_node_id": int(node_run_id),
            "flowchart_node_id": int(flowchart_node_id),
            "message": str(degraded_reason or "degraded_execution"),
            "updated_at": _human_time(updated_at),
        }
        for node_run_id, flowchart_node_id, degraded_reason, updated_at in warning_rows
    ]
    return {
        "id": flowchart_run.id,
        "status": flowchart_run.status,
        "created_at": _human_time(flowchart_run.created_at),
        "started_at": _human_time(flowchart_run.started_at),
        "finished_at": _human_time(flowchart_run.finished_at),
        "counts": counts,
        "warning_count": len(warnings),
        "warnings": warnings,
    }

@bp.get("/flowcharts/runs/<int:run_id>/trace")
def flowchart_run_trace(run_id: int):
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    include_arg = str(request.args.get("include") or "all").strip().lower()
    include_tokens = {
        token.strip().lower()
        for token in include_arg.split(",")
        if token.strip()
    }
    if not include_tokens or "all" in include_tokens:
        include_tokens = {"run", "node", "tool", "artifact", "failure", "timeline"}
    invalid_tokens = include_tokens.difference(
        {"run", "node", "tool", "artifact", "failure", "timeline"}
    )
    if invalid_tokens:
        return (
            _workflow_error_envelope(
                code="invalid_request",
                message="include contains unsupported trace surfaces.",
                details={"unsupported": sorted(invalid_tokens)},
                request_id=request_id,
                correlation_id=correlation_id,
            ),
            400,
        )

    status_arg = str(request.args.get("status") or "").strip().lower()
    status_filters = {
        token.strip()
        for token in status_arg.split(",")
        if token.strip()
    }
    trace_request_filter = _flowchart_trace_text(
        request.args.get("trace_request_id") or request.args.get("request_id")
    )
    trace_correlation_filter = _flowchart_trace_text(
        request.args.get("trace_correlation_id") or request.args.get("correlation_id")
    )
    try:
        limit = _coerce_optional_int(
            request.args.get("limit"),
            field_name="limit",
            minimum=1,
        )
        offset = _coerce_optional_int(
            request.args.get("offset"),
            field_name="offset",
            minimum=0,
        )
        flowchart_node_id = _coerce_optional_int(
            request.args.get("flowchart_node_id"),
            field_name="flowchart_node_id",
            minimum=1,
        )
        flowchart_run_node_id = _coerce_optional_int(
            request.args.get("flowchart_run_node_id"),
            field_name="flowchart_run_node_id",
            minimum=1,
        )
        agent_task_id = _coerce_optional_int(
            request.args.get("agent_task_id"),
            field_name="agent_task_id",
            minimum=1,
        )
        degraded_only = _flowchart_trace_optional_bool(request.args.get("degraded_only"))
    except ValueError as exc:
        return (
            _workflow_error_envelope(
                code="invalid_request",
                message=str(exc),
                details={},
                request_id=request_id,
                correlation_id=correlation_id,
            ),
            400,
        )

    resolved_limit = min(limit if limit is not None else FLOWCHART_TRACE_DEFAULT_LIMIT, FLOWCHART_TRACE_MAX_LIMIT)
    resolved_offset = offset if offset is not None else 0
    artifact_type_filter = _flowchart_trace_text(request.args.get("artifact_type"))
    if artifact_type_filter:
        artifact_type_filter = artifact_type_filter.lower()

    logger.info(
        "Flowchart trace query run_id=%s request_id=%s correlation_id=%s include=%s limit=%s offset=%s",
        run_id,
        request_id,
        correlation_id,
        ",".join(sorted(include_tokens)),
        resolved_limit,
        resolved_offset,
    )

    node_rows: list[FlowchartRunNode] = []
    artifacts: list[NodeArtifact] = []
    flowchart_run: FlowchartRun | None = None
    with session_scope() as session:
        flowchart_run = session.get(FlowchartRun, run_id)
        if flowchart_run is None:
            abort(404)
        node_stmt = select(FlowchartRunNode).where(FlowchartRunNode.flowchart_run_id == run_id)
        if flowchart_node_id is not None:
            node_stmt = node_stmt.where(FlowchartRunNode.flowchart_node_id == flowchart_node_id)
        if flowchart_run_node_id is not None:
            node_stmt = node_stmt.where(FlowchartRunNode.id == flowchart_run_node_id)
        if agent_task_id is not None:
            node_stmt = node_stmt.where(FlowchartRunNode.agent_task_id == agent_task_id)
        if degraded_only is True:
            node_stmt = node_stmt.where(FlowchartRunNode.degraded_status.is_(True))
        if degraded_only is False:
            node_stmt = node_stmt.where(FlowchartRunNode.degraded_status.is_(False))
        node_rows = (
            session.execute(
                node_stmt.order_by(
                    FlowchartRunNode.execution_index.asc(),
                    FlowchartRunNode.created_at.asc(),
                    FlowchartRunNode.id.asc(),
                )
            )
            .scalars()
            .all()
        )
        artifact_stmt = select(NodeArtifact).where(NodeArtifact.flowchart_run_id == run_id)
        if flowchart_node_id is not None:
            artifact_stmt = artifact_stmt.where(NodeArtifact.flowchart_node_id == flowchart_node_id)
        if flowchart_run_node_id is not None:
            artifact_stmt = artifact_stmt.where(
                NodeArtifact.flowchart_run_node_id == flowchart_run_node_id
            )
        if artifact_type_filter:
            artifact_stmt = artifact_stmt.where(
                func.lower(NodeArtifact.artifact_type) == artifact_type_filter
            )
        if trace_request_filter:
            artifact_stmt = artifact_stmt.where(NodeArtifact.request_id == trace_request_filter)
        if trace_correlation_filter:
            artifact_stmt = artifact_stmt.where(
                NodeArtifact.correlation_id == trace_correlation_filter
            )
        artifacts = (
            session.execute(
                artifact_stmt.order_by(NodeArtifact.created_at.desc(), NodeArtifact.id.desc())
            )
            .scalars()
            .all()
        )

    node_items: list[dict[str, object]] = []
    tool_items: list[dict[str, object]] = []
    failure_items: list[dict[str, object]] = []
    timeline_buffer: list[tuple[datetime, dict[str, object]]] = []
    for node_row in node_rows:
        output_state = _parse_json_dict(node_row.output_state_json)
        routing_state = _parse_json_dict(node_row.routing_state_json)
        trace_request_id, trace_correlation_id = _flowchart_trace_request_identity(
            output_state=output_state,
            routing_state=routing_state,
        )
        warnings = _flowchart_trace_warning_entries(
            node_run=node_row,
            output_state=output_state,
            routing_state=routing_state,
        )
        if trace_request_filter and trace_request_filter != trace_request_id:
            continue
        if trace_correlation_filter and trace_correlation_filter != trace_correlation_id:
            continue
        if status_filters and _normalize_flowchart_run_status(node_row.status) not in status_filters:
            continue
        node_item = {
            **_serialize_flowchart_run_node(node_row),
            "request_id": trace_request_id,
            "correlation_id": trace_correlation_id,
            "warnings": warnings,
        }
        node_items.append(node_item)
        tooling_payload = (
            output_state.get("deterministic_tooling")
            if isinstance(output_state.get("deterministic_tooling"), dict)
            else routing_state.get("deterministic_tooling")
            if isinstance(routing_state.get("deterministic_tooling"), dict)
            else {}
        )
        if isinstance(tooling_payload, dict) and tooling_payload:
            tool_items.append(
                {
                    "flowchart_run_node_id": node_row.id,
                    "flowchart_node_id": node_row.flowchart_node_id,
                    "agent_task_id": node_row.agent_task_id,
                    "execution_index": node_row.execution_index,
                    "tool_name": tooling_payload.get("tool_name"),
                    "operation": tooling_payload.get("operation"),
                    "execution_status": tooling_payload.get("execution_status"),
                    "fallback_used": bool(tooling_payload.get("fallback_used")),
                    "warnings": list(tooling_payload.get("warnings") or []),
                    "request_id": _flowchart_trace_text(
                        tooling_payload.get("request_id") or trace_request_id
                    ),
                    "correlation_id": _flowchart_trace_text(
                        tooling_payload.get("correlation_id") or trace_correlation_id
                    ),
                    "updated_at": _human_time(node_row.updated_at),
                }
            )
        if _normalize_flowchart_run_status(node_row.status) in {"failed", "error"} or str(
            node_row.error or ""
        ).strip():
            failure_items.append(
                {
                    "flowchart_run_node_id": node_row.id,
                    "flowchart_node_id": node_row.flowchart_node_id,
                    "agent_task_id": node_row.agent_task_id,
                    "status": node_row.status,
                    "error": node_row.error or "",
                    "degraded_status": bool(node_row.degraded_status),
                    "degraded_reason": node_row.degraded_reason,
                    "request_id": trace_request_id,
                    "correlation_id": trace_correlation_id,
                    "updated_at": _human_time(node_row.updated_at),
                }
            )
        timeline_timestamp = (
            node_row.finished_at
            or node_row.started_at
            or node_row.updated_at
            or node_row.created_at
        )
        if timeline_timestamp is not None:
            timeline_buffer.append(
                (
                    timeline_timestamp,
                    {
                        "event_type": "flowchart_node_status",
                        "flowchart_run_node_id": node_row.id,
                        "flowchart_node_id": node_row.flowchart_node_id,
                        "status": node_row.status,
                        "error": node_row.error or "",
                        "warning_count": len(warnings),
                        "request_id": trace_request_id,
                        "correlation_id": trace_correlation_id,
                        "timestamp": _human_time(timeline_timestamp),
                    },
                )
            )
            for warning in warnings:
                timeline_buffer.append(
                    (
                        timeline_timestamp,
                        {
                            "event_type": "flowchart_warning",
                            "flowchart_run_node_id": node_row.id,
                            "flowchart_node_id": node_row.flowchart_node_id,
                            "warning": warning,
                            "request_id": trace_request_id,
                            "correlation_id": trace_correlation_id,
                            "timestamp": _human_time(timeline_timestamp),
                        },
                    )
                )

    artifact_items = [_serialize_node_artifact(item) for item in artifacts]
    for artifact in artifacts:
        timeline_timestamp = artifact.updated_at or artifact.created_at
        if timeline_timestamp is None:
            continue
        timeline_buffer.append(
            (
                timeline_timestamp,
                {
                    "event_type": "flowchart_node_artifact",
                    "artifact_id": artifact.id,
                    "artifact_type": artifact.artifact_type,
                    "flowchart_node_id": artifact.flowchart_node_id,
                    "flowchart_run_node_id": artifact.flowchart_run_node_id,
                    "request_id": _flowchart_trace_text(artifact.request_id),
                    "correlation_id": _flowchart_trace_text(artifact.correlation_id),
                    "timestamp": _human_time(timeline_timestamp),
                },
            )
        )

    if flowchart_run.created_at is not None:
        timeline_buffer.append(
            (
                flowchart_run.created_at,
                {
                    "event_type": "flowchart_run_created",
                    "status": flowchart_run.status,
                    "flowchart_run_id": flowchart_run.id,
                    "timestamp": _human_time(flowchart_run.created_at),
                    "request_id": request_id,
                    "correlation_id": correlation_id,
                },
            )
        )
    if flowchart_run.started_at is not None:
        timeline_buffer.append(
            (
                flowchart_run.started_at,
                {
                    "event_type": "flowchart_run_started",
                    "status": flowchart_run.status,
                    "flowchart_run_id": flowchart_run.id,
                    "timestamp": _human_time(flowchart_run.started_at),
                    "request_id": request_id,
                    "correlation_id": correlation_id,
                },
            )
        )
    if flowchart_run.finished_at is not None:
        timeline_buffer.append(
            (
                flowchart_run.finished_at,
                {
                    "event_type": "flowchart_run_finished",
                    "status": flowchart_run.status,
                    "flowchart_run_id": flowchart_run.id,
                    "timestamp": _human_time(flowchart_run.finished_at),
                    "request_id": request_id,
                    "correlation_id": correlation_id,
                },
            )
        )

    timeline_items = [
        item
        for _timestamp, item in sorted(
            timeline_buffer,
            key=lambda payload: payload[0],
            reverse=True,
        )
    ]
    if status_filters:
        timeline_items = [
            item
            for item in timeline_items
            if _normalize_flowchart_run_status(item.get("status")) in status_filters
            or str(item.get("event_type") or "").strip() == "flowchart_warning"
        ]
    if trace_request_filter:
        timeline_items = [
            item for item in timeline_items if trace_request_filter == item.get("request_id")
        ]
    if trace_correlation_filter:
        timeline_items = [
            item
            for item in timeline_items
            if trace_correlation_filter == item.get("correlation_id")
        ]

    run_warning_count = sum(1 for item in node_items if bool(item.get("degraded_status"))) + sum(
        1 for item in node_items if bool(item.get("warnings"))
    )

    empty_surface = _flowchart_trace_paginate([], limit=resolved_limit, offset=resolved_offset)
    return {
        "ok": True,
        "request_id": request_id,
        "correlation_id": correlation_id,
        "flowchart_run": {
            **_serialize_flowchart_run(flowchart_run),
            "warning_count": run_warning_count,
        },
        "filters": {
            "include": sorted(include_tokens),
            "status": sorted(status_filters),
            "flowchart_node_id": flowchart_node_id,
            "flowchart_run_node_id": flowchart_run_node_id,
            "agent_task_id": agent_task_id,
            "artifact_type": artifact_type_filter,
            "trace_request_id": trace_request_filter,
            "trace_correlation_id": trace_correlation_filter,
            "degraded_only": degraded_only,
        },
        "limits": {
            "limit": resolved_limit,
            "offset": resolved_offset,
            "max_limit": FLOWCHART_TRACE_MAX_LIMIT,
        },
        "run_trace": _flowchart_trace_paginate(
            [
                {
                    **_serialize_flowchart_run(flowchart_run),
                    "request_id": request_id,
                    "correlation_id": correlation_id,
                    "warning_count": run_warning_count,
                }
            ],
            limit=resolved_limit,
            offset=resolved_offset,
        )
        if "run" in include_tokens
        else empty_surface,
        "node_trace": _flowchart_trace_paginate(
            node_items,
            limit=resolved_limit,
            offset=resolved_offset,
        )
        if "node" in include_tokens
        else empty_surface,
        "tool_trace": _flowchart_trace_paginate(
            tool_items,
            limit=resolved_limit,
            offset=resolved_offset,
        )
        if "tool" in include_tokens
        else empty_surface,
        "artifact_trace": _flowchart_trace_paginate(
            artifact_items,
            limit=resolved_limit,
            offset=resolved_offset,
        )
        if "artifact" in include_tokens
        else empty_surface,
        "failure_trace": _flowchart_trace_paginate(
            failure_items,
            limit=resolved_limit,
            offset=resolved_offset,
        )
        if "failure" in include_tokens
        else empty_surface,
        "timeline": _flowchart_trace_paginate(
            timeline_items,
            limit=resolved_limit,
            offset=resolved_offset,
        )
        if "timeline" in include_tokens
        else empty_surface,
    }

@bp.post("/flowcharts/runs/<int:run_id>/control")
def control_flowchart_run(run_id: int):
    payload = _flowchart_request_payload()
    wants_json = request.is_json or bool(payload) or _flowchart_wants_json()
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    action = str(
        payload.get("action")
        or request.form.get("action")
        or request.args.get("action")
        or ""
    ).strip().lower()
    if action not in FLOWCHART_RUN_CONTROL_ACTIONS:
        return (
            _workflow_error_envelope(
                code="invalid_request",
                message=(
                    "action is required and must be one of "
                    + ", ".join(sorted(FLOWCHART_RUN_CONTROL_ACTIONS))
                    + "."
                ),
                details={},
                request_id=request_id,
                correlation_id=correlation_id,
            ),
            400,
        )

    force_value = payload.get("force")
    if force_value is None:
        force_value = request.form.get("force")
    if force_value is None:
        force_value = request.args.get("force")
    force = _flowchart_as_bool(force_value)
    force_new = _flowchart_as_bool(
        payload.get("force_new")
        if payload.get("force_new") is not None
        else request.form.get("force_new")
        if request.form.get("force_new") is not None
        else request.args.get("force_new")
    )
    replay_idempotency_key = _flowchart_trace_text(
        payload.get("idempotency_key")
        or request.headers.get("X-Idempotency-Key")
        or request.headers.get("Idempotency-Key")
    ) or f"default:{action}:{run_id}"
    rewind_to_node_run_id = None
    try:
        rewind_to_node_run_id = _coerce_optional_int(
            payload.get("rewind_to_node_run_id")
            if "rewind_to_node_run_id" in payload
            else request.args.get("rewind_to_node_run_id"),
            field_name="rewind_to_node_run_id",
            minimum=1,
        )
    except ValueError as exc:
        return (
            _workflow_error_envelope(
                code="invalid_request",
                message=str(exc),
                details={},
                request_id=request_id,
                correlation_id=correlation_id,
            ),
            400,
        )

    flowchart_id: int | None = None
    response_payload: dict[str, object]
    revoke_actions: list[tuple[str, bool]] = []
    replay_dispatch_run_id: int | None = None
    replay_run_payload: dict[str, object] | None = None
    status_before = ""
    updated = False
    applied_action = "none"
    control_warnings: list[dict[str, str]] = []

    with session_scope() as session:
        flowchart_run = session.get(FlowchartRun, run_id)
        if flowchart_run is None:
            abort(404)
        flowchart_id = int(flowchart_run.flowchart_id)
        status_before = _normalize_flowchart_run_status(flowchart_run.status)

        if action == "cancel":
            response_payload, revoke_actions = _control_cancel_flowchart_run(
                session,
                run_id=run_id,
                flowchart_run=flowchart_run,
                force=force,
            )
            updated = bool(response_payload.get("updated"))
            applied_action = str(response_payload.get("action") or "none")
        elif action == "pause":
            if status_before in {"running", "stopping"}:
                flowchart_run.status = "pausing"
                updated = True
                applied_action = "pausing"
            elif status_before == "queued":
                flowchart_run.status = "paused"
                updated = True
                applied_action = "paused"
            elif status_before in {"pausing", "paused"}:
                applied_action = status_before
            else:
                applied_action = "noop"
            response_payload = {
                "flowchart_run": _serialize_flowchart_run(flowchart_run),
                "updated": updated,
                "action": applied_action,
            }
        elif action == "resume":
            if status_before in {"paused", "pausing"}:
                flowchart_run.status = "running"
                flowchart_run.started_at = flowchart_run.started_at or utcnow()
                updated = True
                applied_action = "running"
            elif status_before == "running":
                applied_action = "running"
            else:
                applied_action = "noop"
            response_payload = {
                "flowchart_run": _serialize_flowchart_run(flowchart_run),
                "updated": updated,
                "action": applied_action,
            }
        else:
            replay_marker = (
                _flowchart_parse_replay_marker(flowchart_run.celery_task_id)
                if not force_new
                else None
            )
            if replay_marker is not None and replay_marker[0] == action:
                existing_replay = session.get(FlowchartRun, replay_marker[1])
                if existing_replay is not None:
                    replay_run_payload = _serialize_flowchart_run(existing_replay)
                    applied_action = "replay_existing"
            if replay_run_payload is None and status_before in FLOWCHART_RUN_ACTIVE_STATUSES:
                applied_action = "noop_active"
            elif replay_run_payload is None:
                accepted = (
                    True
                    if force_new
                    else register_runtime_idempotency_key(
                        f"flowchart_run_control:{action}:{run_id}",
                        replay_idempotency_key,
                    )
                )
                if not accepted and not force_new:
                    applied_action = "idempotent_noop"
                    replay_marker = _flowchart_parse_replay_marker(flowchart_run.celery_task_id)
                    if replay_marker is not None:
                        existing_replay = session.get(FlowchartRun, replay_marker[1])
                        if existing_replay is not None:
                            replay_run_payload = _serialize_flowchart_run(existing_replay)
                            applied_action = "replay_existing"
                else:
                    replay_run = FlowchartRun.create(
                        session,
                        flowchart_id=flowchart_id,
                        status="queued",
                    )
                    replay_dispatch_run_id = int(replay_run.id)
                    replay_run_payload = _serialize_flowchart_run(replay_run)
                    flowchart_run.celery_task_id = _flowchart_build_replay_marker(
                        action=action,
                        replay_run_id=replay_dispatch_run_id,
                    )
                    updated = True
                    applied_action = "replay_queued"
                    if action in {"skip", "rewind"}:
                        control_warnings.append(
                            {
                                "code": "replay_from_start",
                                "message": (
                                    "Exact partial execution control is unavailable; "
                                    "replayed from flowchart start."
                                ),
                            }
                        )
            response_payload = {
                "flowchart_run": _serialize_flowchart_run(flowchart_run),
                "updated": updated,
                "action": applied_action,
                "replay_run": replay_run_payload,
                "rewind_to_node_run_id": rewind_to_node_run_id,
            }

    if replay_dispatch_run_id is not None and flowchart_id is not None:
        try:
            async_result = run_flowchart.delay(flowchart_id, replay_dispatch_run_id)
            with session_scope() as session:
                replay_run = session.get(FlowchartRun, replay_dispatch_run_id)
                if replay_run is not None:
                    replay_run.celery_task_id = async_result.id
                    replay_run_payload = _serialize_flowchart_run(replay_run)
                    response_payload["replay_run"] = replay_run_payload
        except Exception as exc:
            logger.exception(
                "Failed to queue replay run %s for source run %s",
                replay_dispatch_run_id,
                run_id,
            )
            with session_scope() as session:
                replay_run = session.get(FlowchartRun, replay_dispatch_run_id)
                if replay_run is not None:
                    replay_run.status = "failed"
                    replay_run.finished_at = utcnow()
                    response_payload["replay_run"] = _serialize_flowchart_run(replay_run)
            control_warnings.append(
                {
                    "code": "replay_queue_failed",
                    "message": str(exc) or "Failed to queue replay run.",
                }
            )

    for task_id, terminate in revoke_actions:
        try:
            if terminate:
                celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
            else:
                celery_app.control.revoke(task_id)
        except Exception as exc:
            logger.warning("Failed to revoke flowchart task %s: %s", task_id, exc)

    if flowchart_id is not None:
        emit_contract_event(
            event_type="flowchart.run.updated",
            entity_kind="flowchart_run",
            entity_id=run_id,
            room_keys=[f"flowchart:{flowchart_id}", f"flowchart_run:{run_id}"],
            payload={
                "flowchart_id": flowchart_id,
                "flowchart_run_id": run_id,
                "requested_action": action,
                "applied_action": applied_action,
                "status_before": status_before,
                "status_after": (
                    (response_payload.get("flowchart_run") or {}).get("status")
                    if isinstance(response_payload.get("flowchart_run"), dict)
                    else None
                ),
                "updated": bool(response_payload.get("updated")),
                "replay_run_id": (
                    (response_payload.get("replay_run") or {}).get("id")
                    if isinstance(response_payload.get("replay_run"), dict)
                    else None
                ),
                "warnings": list(control_warnings),
            },
            runtime=None,
            request_id=request_id,
            correlation_id=correlation_id,
        )

    logger.info(
        "Flowchart run control action=%s run_id=%s updated=%s request_id=%s correlation_id=%s",
        action,
        run_id,
        bool(response_payload.get("updated")),
        request_id,
        correlation_id,
    )

    response_payload = {
        **response_payload,
        "requested_action": action,
        "applied_action": applied_action,
        "idempotent": not bool(response_payload.get("updated")),
        "request_id": request_id,
        "correlation_id": correlation_id,
        "warnings": control_warnings,
    }

    if wants_json:
        return response_payload

    default_next = (
        url_for("agents.view_flowchart_history_run", flowchart_id=flowchart_id, run_id=run_id)
        if flowchart_id is not None
        else url_for("agents.list_flowcharts")
    )
    redirect_target = _safe_redirect_target(request.form.get("next"), default_next)
    if action == "cancel":
        if response_payload.get("action") == "canceled":
            flash("Flowchart force stop requested.", "success")
        elif response_payload.get("action") == "stopped":
            flash("Flowchart stopped.", "success")
        elif response_payload.get("action") == "stopping":
            flash("Flowchart stop requested. It will stop after the current node finishes.", "success")
        else:
            flash("Flowchart run is not active.", "info")
    elif action == "pause":
        if response_payload.get("action") in {"pausing", "paused"}:
            flash("Flowchart pause requested.", "success")
        else:
            flash("Flowchart run cannot be paused in its current state.", "info")
    elif action == "resume":
        if response_payload.get("action") == "running":
            flash("Flowchart resumed.", "success")
        else:
            flash("Flowchart run is not paused.", "info")
    else:
        if isinstance(response_payload.get("replay_run"), dict):
            flash(
                f"Replay run {response_payload['replay_run'].get('id')} queued.",
                "success",
            )
        else:
            flash("No replay action was applied.", "info")
    return redirect(redirect_target)

@bp.get("/flowcharts/<int:flowchart_id>/runtime")
def flowchart_runtime_status(flowchart_id: int):
    active_run_id: int | None = None
    active_run_status: str | None = None
    running_node_ids: list[int] = []
    with session_scope() as session:
        flowchart = session.get(Flowchart, flowchart_id)
        if flowchart is None:
            abort(404)
        active_run = (
            session.execute(
                select(FlowchartRun)
                .where(
                    FlowchartRun.flowchart_id == flowchart_id,
                    FlowchartRun.status.in_(["queued", "running", "stopping", "pausing", "paused"]),
                )
                .order_by(FlowchartRun.created_at.desc(), FlowchartRun.id.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if active_run is None:
            return {
                "flowchart_id": flowchart_id,
                "active_run_id": None,
                "active_run_status": None,
                "running_node_ids": [],
            }
        active_run_id = int(active_run.id)
        active_run_status = str(active_run.status or "")
        running_node_ids = [
            int(node_id)
            for node_id in session.execute(
                select(FlowchartRunNode.flowchart_node_id)
                .where(
                    FlowchartRunNode.flowchart_run_id == active_run_id,
                    FlowchartRunNode.status == "running",
                )
                .order_by(
                    FlowchartRunNode.execution_index.asc(),
                    FlowchartRunNode.created_at.asc(),
                    FlowchartRunNode.id.asc(),
                )
            )
            .scalars()
            .all()
            if isinstance(node_id, int) and node_id > 0
        ]
    return {
        "flowchart_id": flowchart_id,
        "active_run_id": active_run_id,
        "active_run_status": active_run_status,
        "running_node_ids": running_node_ids,
    }

@bp.post("/flowcharts/runs/<int:run_id>/cancel")
def cancel_flowchart_run(run_id: int):
    payload = _flowchart_request_payload()
    wants_json = request.is_json or bool(payload) or _flowchart_wants_json()
    force_value = payload.get("force")
    if force_value is None:
        force_value = request.form.get("force")
    if force_value is None:
        force_value = request.args.get("force")
    force = _flowchart_as_bool(force_value)

    revoke_actions: list[tuple[str, bool]] = []
    action = "none"
    updated = False
    flowchart_id: int | None = None
    with session_scope() as session:
        flowchart_run = session.get(FlowchartRun, run_id)
        if flowchart_run is None:
            abort(404)
        flowchart_id = flowchart_run.flowchart_id
        now = utcnow()
        current_status = str(flowchart_run.status or "").strip().lower()

        if force:
            if current_status in {"queued", "running", "stopping", "pausing", "paused"}:
                action = "canceled"
                updated = True
                flowchart_run.status = "canceled"
                flowchart_run.finished_at = now
                if flowchart_run.celery_task_id:
                    revoke_actions.append((flowchart_run.celery_task_id, True))

                node_runs = (
                    session.execute(
                        select(FlowchartRunNode).where(FlowchartRunNode.flowchart_run_id == run_id)
                    )
                    .scalars()
                    .all()
                )
                for node_run in node_runs:
                    if node_run.status in {"queued", "running", "pending"}:
                        node_run.status = "canceled"
                        node_run.finished_at = now

                tasks = (
                    session.execute(select(AgentTask).where(AgentTask.flowchart_run_id == run_id))
                    .scalars()
                    .all()
                )
                for task in tasks:
                    if task.status in {"pending", "queued", "running"}:
                        task.status = "canceled"
                        task.finished_at = now
                        if not task.error:
                            task.error = "Canceled by user."
                    if task.celery_task_id:
                        revoke_actions.append((task.celery_task_id, True))
        else:
            if current_status == "queued":
                action = "stopped"
                updated = True
                flowchart_run.status = "stopped"
                flowchart_run.finished_at = now
                if flowchart_run.celery_task_id:
                    revoke_actions.append((flowchart_run.celery_task_id, False))
            elif current_status in {"running", "pausing", "paused"}:
                action = "stopping"
                updated = True
                flowchart_run.status = "stopping"
            elif current_status == "stopping":
                action = "stopping"

        response_payload = {
            "flowchart_run": _serialize_flowchart_run(flowchart_run),
            "force": force,
            "updated": updated,
            "action": action,
            "canceled": action == "canceled",
            "stop_requested": action in {"stopping", "stopped"},
        }

    for task_id, terminate in revoke_actions:
        try:
            if terminate:
                celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
            else:
                celery_app.control.revoke(task_id)
        except Exception as exc:
            logger.warning("Failed to revoke flowchart task %s: %s", task_id, exc)

    if wants_json:
        return response_payload

    default_next = (
        url_for("agents.view_flowchart_history_run", flowchart_id=flowchart_id, run_id=run_id)
        if flowchart_id is not None
        else url_for("agents.list_flowcharts")
    )
    redirect_target = _safe_redirect_target(request.form.get("next"), default_next)
    if response_payload["action"] == "canceled":
        flash("Flowchart force stop requested.", "success")
    elif response_payload["action"] == "stopped":
        flash("Flowchart stopped.", "success")
    elif response_payload["action"] == "stopping":
        flash("Flowchart stop requested. It will stop after the current node finishes.", "success")
    else:
        flash("Flowchart run is not active.", "info")
    return redirect(redirect_target)

@bp.get("/flowcharts/<int:flowchart_id>/nodes/<int:node_id>/utilities")
def get_flowchart_node_utilities(flowchart_id: int, node_id: int):
    with session_scope() as session:
        flowchart_node = (
            session.execute(
                select(FlowchartNode)
                .options(
                    selectinload(FlowchartNode.mcp_servers),
                    selectinload(FlowchartNode.scripts),
                    selectinload(FlowchartNode.attachments),
                )
                .where(FlowchartNode.id == node_id)
            )
            .scalars()
            .first()
        )
        if flowchart_node is None or flowchart_node.flowchart_id != flowchart_id:
            abort(404)
        compatibility_errors = _validate_flowchart_utility_compatibility(
            flowchart_node.node_type,
            model_id=flowchart_node.model_id,
            mcp_server_ids=[server.id for server in flowchart_node.mcp_servers],
            script_ids=[script.id for script in flowchart_node.scripts],
            attachment_ids=[attachment.id for attachment in flowchart_node.attachments],
        )
        return {
            "node": _serialize_flowchart_node(flowchart_node),
            "catalog": _flowchart_catalog(session),
            "validation": {
                "valid": len(compatibility_errors) == 0,
                "errors": compatibility_errors,
            },
        }

@bp.post("/flowcharts/<int:flowchart_id>/nodes/<int:node_id>/model")
def set_flowchart_node_model(flowchart_id: int, node_id: int):
    payload = _flowchart_request_payload()
    model_id_raw = payload.get("model_id") if payload else request.form.get("model_id")
    try:
        model_id = _coerce_optional_int(model_id_raw, field_name="model_id", minimum=1)
    except ValueError as exc:
        return {"error": str(exc)}, 400

    with session_scope() as session:
        flowchart_node = session.get(FlowchartNode, node_id)
        if flowchart_node is None or flowchart_node.flowchart_id != flowchart_id:
            abort(404)
        errors = _validate_flowchart_utility_compatibility(
            flowchart_node.node_type,
            model_id=model_id,
        )
        if errors:
            return {"error": errors[0]}, 400
        if model_id is not None and session.get(LLMModel, model_id) is None:
            return {"error": f"Model {model_id} was not found."}, 404
        if (
            flowchart_node.node_type == FLOWCHART_NODE_TYPE_RAG
            and model_id is not None
        ):
            selected_model = session.get(LLMModel, model_id)
            rag_config = _parse_json_dict(flowchart_node.config_json)
            rag_mode = str(rag_config.get("mode") or "").strip().lower()
            if rag_mode in {RAG_NODE_MODE_FRESH_INDEX, RAG_NODE_MODE_DELTA_INDEX}:
                if selected_model is None or not _is_rag_embedding_model_provider(
                    selected_model.provider
                ):
                    return {
                        "error": (
                            "Index modes require an embedding-capable model provider "
                            "(codex or gemini)."
                        )
                    }, 400
        flowchart_node.model_id = model_id
        return {"node": _serialize_flowchart_node(flowchart_node)}

@bp.post("/flowcharts/<int:flowchart_id>/nodes/<int:node_id>/mcp-servers")
def attach_flowchart_node_mcp(flowchart_id: int, node_id: int):
    payload = _flowchart_request_payload()
    mcp_id_raw = payload.get("mcp_server_id") if payload else request.form.get("mcp_server_id")
    try:
        mcp_id = _coerce_optional_int(mcp_id_raw, field_name="mcp_server_id", minimum=1)
    except ValueError as exc:
        return {"error": str(exc)}, 400
    if mcp_id is None:
        return {"error": "mcp_server_id is required."}, 400

    with session_scope() as session:
        flowchart_node = (
            session.execute(
                select(FlowchartNode)
                .options(selectinload(FlowchartNode.mcp_servers))
                .where(FlowchartNode.id == node_id)
            )
            .scalars()
            .first()
        )
        if flowchart_node is None or flowchart_node.flowchart_id != flowchart_id:
            abort(404)
        errors = _validate_flowchart_utility_compatibility(
            flowchart_node.node_type,
            model_id=None,
            mcp_server_ids=[mcp_id],
        )
        if errors:
            return {"error": errors[0]}, 400
        server = session.get(MCPServer, mcp_id)
        if server is None:
            return {"error": f"MCP server {mcp_id} was not found."}, 404
        existing = {item.id for item in flowchart_node.mcp_servers}
        if server.id not in existing:
            flowchart_node.mcp_servers.append(server)
        return {"node": _serialize_flowchart_node(flowchart_node)}

@bp.post("/flowcharts/<int:flowchart_id>/nodes/<int:node_id>/mcp-servers/<int:mcp_id>/delete")
def detach_flowchart_node_mcp(flowchart_id: int, node_id: int, mcp_id: int):
    with session_scope() as session:
        flowchart_node = (
            session.execute(
                select(FlowchartNode)
                .options(selectinload(FlowchartNode.mcp_servers))
                .where(FlowchartNode.id == node_id)
            )
            .scalars()
            .first()
        )
        if flowchart_node is None or flowchart_node.flowchart_id != flowchart_id:
            abort(404)
        for server in list(flowchart_node.mcp_servers):
            if server.id == mcp_id:
                flowchart_node.mcp_servers.remove(server)
        return {"node": _serialize_flowchart_node(flowchart_node)}

@bp.post("/flowcharts/<int:flowchart_id>/nodes/<int:node_id>/scripts")
def attach_flowchart_node_script(flowchart_id: int, node_id: int):
    payload = _flowchart_request_payload()
    script_id_raw = payload.get("script_id") if payload else request.form.get("script_id")
    try:
        script_id = _coerce_optional_int(script_id_raw, field_name="script_id", minimum=1)
    except ValueError as exc:
        return {"error": str(exc)}, 400
    if script_id is None:
        return {"error": "script_id is required."}, 400

    with session_scope() as session:
        flowchart_node = (
            session.execute(
                select(FlowchartNode)
                .options(
                    selectinload(FlowchartNode.scripts),
                    selectinload(FlowchartNode.skills),
                )
                .where(FlowchartNode.id == node_id)
            )
            .scalars()
            .first()
        )
        if flowchart_node is None or flowchart_node.flowchart_id != flowchart_id:
            abort(404)
        errors = _validate_flowchart_utility_compatibility(
            flowchart_node.node_type,
            model_id=None,
            script_ids=[script_id],
        )
        if errors:
            return {"error": errors[0]}, 400
        script = session.get(Script, script_id)
        if script is None:
            return {"error": f"Script {script_id} was not found."}, 404
        if is_legacy_skill_script_type(script.script_type):
            return {
                "error": (
                    "Legacy script_type=skill records cannot be attached. "
                    "Assign first-class Skills on an Agent."
                )
            }, 400
        ordered_ids = [item.id for item in flowchart_node.scripts]
        if script_id not in ordered_ids:
            ordered_ids.append(script_id)
            _set_flowchart_node_scripts(session, node_id, ordered_ids)
        refreshed = (
            session.execute(
                select(FlowchartNode)
                .options(
                    selectinload(FlowchartNode.scripts),
                    selectinload(FlowchartNode.skills),
                )
                .where(FlowchartNode.id == node_id)
            )
            .scalars()
            .first()
        )
        return {"node": _serialize_flowchart_node(refreshed)}

@bp.post("/flowcharts/<int:flowchart_id>/nodes/<int:node_id>/scripts/<int:script_id>/delete")
def detach_flowchart_node_script(flowchart_id: int, node_id: int, script_id: int):
    with session_scope() as session:
        flowchart_node = (
            session.execute(
                select(FlowchartNode)
                .options(
                    selectinload(FlowchartNode.scripts),
                    selectinload(FlowchartNode.skills),
                )
                .where(FlowchartNode.id == node_id)
            )
            .scalars()
            .first()
        )
        if flowchart_node is None or flowchart_node.flowchart_id != flowchart_id:
            abort(404)
        ordered_ids = [item.id for item in flowchart_node.scripts if item.id != script_id]
        _set_flowchart_node_scripts(session, node_id, ordered_ids)
        refreshed = (
            session.execute(
                select(FlowchartNode)
                .options(
                    selectinload(FlowchartNode.scripts),
                    selectinload(FlowchartNode.skills),
                )
                .where(FlowchartNode.id == node_id)
            )
            .scalars()
            .first()
        )
        return {"node": _serialize_flowchart_node(refreshed)}

@bp.post("/flowcharts/<int:flowchart_id>/nodes/<int:node_id>/scripts/reorder")
def reorder_flowchart_node_scripts(flowchart_id: int, node_id: int):
    payload = _flowchart_request_payload()
    script_ids_raw = payload.get("script_ids")
    if script_ids_raw is None:
        raw_values = [value.strip() for value in request.form.getlist("script_ids")]
        script_ids_raw = raw_values
    if not isinstance(script_ids_raw, list):
        return {"error": "script_ids must be an array."}, 400

    script_ids: list[int] = []
    for index, script_id_raw in enumerate(script_ids_raw):
        try:
            script_id = _coerce_optional_int(
                script_id_raw,
                field_name=f"script_ids[{index}]",
                minimum=1,
            )
        except ValueError as exc:
            return {"error": str(exc)}, 400
        if script_id is None:
            return {"error": f"script_ids[{index}] is invalid."}, 400
        script_ids.append(script_id)

    if len(script_ids) != len(set(script_ids)):
        return {"error": "script_ids cannot contain duplicates."}, 400

    with session_scope() as session:
        flowchart_node = (
            session.execute(
                select(FlowchartNode)
                .options(
                    selectinload(FlowchartNode.scripts),
                    selectinload(FlowchartNode.skills),
                )
                .where(FlowchartNode.id == node_id)
            )
            .scalars()
            .first()
        )
        if flowchart_node is None or flowchart_node.flowchart_id != flowchart_id:
            abort(404)
        errors = _validate_flowchart_utility_compatibility(
            flowchart_node.node_type,
            model_id=None,
            script_ids=script_ids,
        )
        if errors:
            return {"error": errors[0]}, 400
        if any(is_legacy_skill_script_type(script.script_type) for script in flowchart_node.scripts):
            return {
                "error": (
                    "Legacy script_type=skill records cannot be reordered; "
                    "migrate to first-class Skills."
                )
            }, 400
        existing_ids = {script.id for script in flowchart_node.scripts}
        if set(script_ids) != existing_ids:
            return {
                "error": "script_ids must include each attached script exactly once."
            }, 400
        _set_flowchart_node_scripts(session, node_id, script_ids)
        refreshed = (
            session.execute(
                select(FlowchartNode)
                .options(
                    selectinload(FlowchartNode.scripts),
                    selectinload(FlowchartNode.skills),
                )
                .where(FlowchartNode.id == node_id)
            )
            .scalars()
            .first()
        )
        return {"node": _serialize_flowchart_node(refreshed)}
