from .shared import *  # noqa: F401,F403

__all__ = ['list_plan_artifacts', 'view_plan_artifact', 'delete_plan_artifact', 'list_memory_artifacts', 'view_memory_artifact', 'delete_memory_artifact', 'list_milestone_artifacts', 'view_milestone_artifact', 'delete_milestone_artifact', 'list_node_artifacts', 'view_node_artifact', 'list_attachments', 'view_attachment', 'view_attachment_file', 'delete_attachment']

@bp.get("/plans/<int:plan_id>/artifacts")
def list_plan_artifacts(plan_id: int):
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    try:
        limit = _coerce_optional_int(request.args.get("limit"), field_name="limit", minimum=1)
        offset = _coerce_optional_int(request.args.get("offset"), field_name="offset", minimum=0)
        flowchart_id = _coerce_optional_int(
            request.args.get("flowchart_id"),
            field_name="flowchart_id",
            minimum=1,
        )
        flowchart_node_id = _coerce_optional_int(
            request.args.get("flowchart_node_id"),
            field_name="flowchart_node_id",
            minimum=1,
        )
        flowchart_run_id = _coerce_optional_int(
            request.args.get("flowchart_run_id"),
            field_name="flowchart_run_id",
            minimum=1,
        )
    except ValueError as exc:
        return _workflow_error_envelope(
            code="invalid_request",
            message=str(exc),
            details={},
            request_id=request_id,
            correlation_id=correlation_id,
        ), 400

    resolved_limit = min(limit if limit is not None else 50, 200)
    resolved_offset = offset if offset is not None else 0
    descending = str(request.args.get("order") or "desc").strip().lower() != "asc"

    with session_scope() as session:
        if session.get(Plan, plan_id) is None:
            return _workflow_error_envelope(
                code="not_found",
                message=f"Plan {plan_id} was not found.",
                details={"plan_id": plan_id},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 404
        artifact_filters = [
            NodeArtifact.artifact_type == NODE_ARTIFACT_TYPE_PLAN,
            NodeArtifact.ref_id == plan_id,
        ]
        if flowchart_id is not None:
            artifact_filters.append(NodeArtifact.flowchart_id == flowchart_id)
        if flowchart_node_id is not None:
            artifact_filters.append(NodeArtifact.flowchart_node_id == flowchart_node_id)
        if flowchart_run_id is not None:
            artifact_filters.append(NodeArtifact.flowchart_run_id == flowchart_run_id)
        total_count = (
            session.execute(
                select(func.count(NodeArtifact.id)).where(*artifact_filters)
            )
            .scalar_one()
        )
        stmt = select(NodeArtifact).where(*artifact_filters)
        if descending:
            stmt = stmt.order_by(NodeArtifact.created_at.desc(), NodeArtifact.id.desc())
        else:
            stmt = stmt.order_by(NodeArtifact.created_at.asc(), NodeArtifact.id.asc())
        artifacts = (
            session.execute(
                stmt.limit(resolved_limit).offset(resolved_offset)
            )
            .scalars()
            .all()
        )
    payload: dict[str, object] = {
        "ok": True,
        "plan_id": plan_id,
        "count": len(artifacts),
        "total_count": int(total_count or 0),
        "limit": resolved_limit,
        "offset": resolved_offset,
        "items": [_serialize_node_artifact(item) for item in artifacts],
        "request_id": request_id,
    }
    if correlation_id:
        payload["correlation_id"] = correlation_id
    return payload

@bp.get("/plans/<int:plan_id>/artifacts/<int:artifact_id>")
def view_plan_artifact(plan_id: int, artifact_id: int):
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    with session_scope() as session:
        if session.get(Plan, plan_id) is None:
            return _workflow_error_envelope(
                code="not_found",
                message=f"Plan {plan_id} was not found.",
                details={"plan_id": plan_id},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 404
        artifact = (
            session.execute(
                select(NodeArtifact).where(
                    NodeArtifact.id == artifact_id,
                    NodeArtifact.artifact_type == NODE_ARTIFACT_TYPE_PLAN,
                    NodeArtifact.ref_id == plan_id,
                )
            )
            .scalars()
            .first()
        )
        if artifact is None:
            return _workflow_error_envelope(
                code="not_found",
                message=f"Plan artifact {artifact_id} was not found for plan {plan_id}.",
                details={"plan_id": plan_id, "artifact_id": artifact_id},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 404
    payload: dict[str, object] = {
        "ok": True,
        "plan_id": plan_id,
        "item": _serialize_node_artifact(artifact),
        "request_id": request_id,
    }
    if correlation_id:
        payload["correlation_id"] = correlation_id
    return payload

@bp.delete("/plans/<int:plan_id>/artifacts/<int:artifact_id>")
def delete_plan_artifact(plan_id: int, artifact_id: int):
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    with session_scope() as session:
        if session.get(Plan, plan_id) is None:
            return _workflow_error_envelope(
                code="not_found",
                message=f"Plan {plan_id} was not found.",
                details={"plan_id": plan_id},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 404
        artifact = (
            session.execute(
                select(NodeArtifact).where(
                    NodeArtifact.id == artifact_id,
                    NodeArtifact.artifact_type == NODE_ARTIFACT_TYPE_PLAN,
                    NodeArtifact.ref_id == plan_id,
                )
            )
            .scalars()
            .first()
        )
        if artifact is None:
            return _workflow_error_envelope(
                code="not_found",
                message=f"Plan artifact {artifact_id} was not found for plan {plan_id}.",
                details={"plan_id": plan_id, "artifact_id": artifact_id},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 404
        session.delete(artifact)
    payload: dict[str, object] = {
        "ok": True,
        "deleted": True,
        "plan_id": plan_id,
        "artifact_id": artifact_id,
        "request_id": request_id,
    }
    if correlation_id:
        payload["correlation_id"] = correlation_id
    return payload

@bp.get("/memories/<int:memory_id>/artifacts")
def list_memory_artifacts(memory_id: int):
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
        if session.get(Memory, memory_id) is None:
            return _workflow_error_envelope(
                code="not_found",
                message=f"Memory {memory_id} was not found.",
                details={"memory_id": memory_id},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 404
        artifact_filters = [
            NodeArtifact.artifact_type == NODE_ARTIFACT_TYPE_MEMORY,
            NodeArtifact.ref_id == memory_id,
        ]
        flowchart_id = parsed["flowchart_id"]
        flowchart_node_id = parsed["flowchart_node_id"]
        flowchart_run_id = parsed["flowchart_run_id"]
        flowchart_run_node_id = parsed["flowchart_run_node_id"]
        if isinstance(flowchart_id, int):
            artifact_filters.append(NodeArtifact.flowchart_id == flowchart_id)
        if isinstance(flowchart_node_id, int):
            artifact_filters.append(NodeArtifact.flowchart_node_id == flowchart_node_id)
        if isinstance(flowchart_run_id, int):
            artifact_filters.append(NodeArtifact.flowchart_run_id == flowchart_run_id)
        if isinstance(flowchart_run_node_id, int):
            artifact_filters.append(NodeArtifact.flowchart_run_node_id == flowchart_run_node_id)
        total_count = (
            session.execute(
                select(func.count(NodeArtifact.id)).where(*artifact_filters)
            )
            .scalar_one()
        )
        stmt = select(NodeArtifact).where(*artifact_filters)
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
        "memory_id": memory_id,
        "count": len(artifacts),
        "total_count": int(total_count or 0),
        "limit": int(parsed["limit"]),
        "offset": int(parsed["offset"]),
        "items": [_serialize_node_artifact(item) for item in artifacts],
        "request_id": request_id,
    }
    if correlation_id:
        payload["correlation_id"] = correlation_id
    return payload

@bp.get("/memories/<int:memory_id>/artifacts/<int:artifact_id>")
def view_memory_artifact(memory_id: int, artifact_id: int):
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    with session_scope() as session:
        if session.get(Memory, memory_id) is None:
            return _workflow_error_envelope(
                code="not_found",
                message=f"Memory {memory_id} was not found.",
                details={"memory_id": memory_id},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 404
        artifact = (
            session.execute(
                select(NodeArtifact).where(
                    NodeArtifact.id == artifact_id,
                    NodeArtifact.artifact_type == NODE_ARTIFACT_TYPE_MEMORY,
                    NodeArtifact.ref_id == memory_id,
                )
            )
            .scalars()
            .first()
        )
        if artifact is None:
            return _workflow_error_envelope(
                code="not_found",
                message=f"Memory artifact {artifact_id} was not found for memory {memory_id}.",
                details={"memory_id": memory_id, "artifact_id": artifact_id},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 404
    payload: dict[str, object] = {
        "ok": True,
        "memory_id": memory_id,
        "item": _serialize_node_artifact(artifact),
        "request_id": request_id,
    }
    if correlation_id:
        payload["correlation_id"] = correlation_id
    return payload

@bp.delete("/memories/<int:memory_id>/artifacts/<int:artifact_id>")
def delete_memory_artifact(memory_id: int, artifact_id: int):
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    with session_scope() as session:
        if session.get(Memory, memory_id) is None:
            return _workflow_error_envelope(
                code="not_found",
                message=f"Memory {memory_id} was not found.",
                details={"memory_id": memory_id},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 404
        artifact = (
            session.execute(
                select(NodeArtifact).where(
                    NodeArtifact.id == artifact_id,
                    NodeArtifact.artifact_type == NODE_ARTIFACT_TYPE_MEMORY,
                    NodeArtifact.ref_id == memory_id,
                )
            )
            .scalars()
            .first()
        )
        if artifact is None:
            return _workflow_error_envelope(
                code="not_found",
                message=f"Memory artifact {artifact_id} was not found for memory {memory_id}.",
                details={"memory_id": memory_id, "artifact_id": artifact_id},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 404
        session.delete(artifact)
    payload: dict[str, object] = {
        "ok": True,
        "deleted": True,
        "memory_id": memory_id,
        "artifact_id": artifact_id,
        "request_id": request_id,
    }
    if correlation_id:
        payload["correlation_id"] = correlation_id
    return payload

@bp.get("/milestones/<int:milestone_id>/artifacts")
def list_milestone_artifacts(milestone_id: int):
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
        if session.get(Milestone, milestone_id) is None:
            return _workflow_error_envelope(
                code="not_found",
                message=f"Milestone {milestone_id} was not found.",
                details={"milestone_id": milestone_id},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 404
        artifact_filters = [
            NodeArtifact.artifact_type == NODE_ARTIFACT_TYPE_MILESTONE,
            NodeArtifact.ref_id == milestone_id,
        ]
        flowchart_id = parsed["flowchart_id"]
        flowchart_node_id = parsed["flowchart_node_id"]
        flowchart_run_id = parsed["flowchart_run_id"]
        flowchart_run_node_id = parsed["flowchart_run_node_id"]
        if isinstance(flowchart_id, int):
            artifact_filters.append(NodeArtifact.flowchart_id == flowchart_id)
        if isinstance(flowchart_node_id, int):
            artifact_filters.append(NodeArtifact.flowchart_node_id == flowchart_node_id)
        if isinstance(flowchart_run_id, int):
            artifact_filters.append(NodeArtifact.flowchart_run_id == flowchart_run_id)
        if isinstance(flowchart_run_node_id, int):
            artifact_filters.append(NodeArtifact.flowchart_run_node_id == flowchart_run_node_id)
        total_count = (
            session.execute(
                select(func.count(NodeArtifact.id)).where(*artifact_filters)
            )
            .scalar_one()
        )
        stmt = select(NodeArtifact).where(*artifact_filters)
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
        "milestone_id": milestone_id,
        "count": len(artifacts),
        "total_count": int(total_count or 0),
        "limit": int(parsed["limit"]),
        "offset": int(parsed["offset"]),
        "items": [_serialize_node_artifact(item) for item in artifacts],
        "request_id": request_id,
    }
    if correlation_id:
        payload["correlation_id"] = correlation_id
    return payload

@bp.get("/milestones/<int:milestone_id>/artifacts/<int:artifact_id>")
def view_milestone_artifact(milestone_id: int, artifact_id: int):
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    with session_scope() as session:
        if session.get(Milestone, milestone_id) is None:
            return _workflow_error_envelope(
                code="not_found",
                message=f"Milestone {milestone_id} was not found.",
                details={"milestone_id": milestone_id},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 404
        artifact = (
            session.execute(
                select(NodeArtifact).where(
                    NodeArtifact.id == artifact_id,
                    NodeArtifact.artifact_type == NODE_ARTIFACT_TYPE_MILESTONE,
                    NodeArtifact.ref_id == milestone_id,
                )
            )
            .scalars()
            .first()
        )
        if artifact is None:
            return _workflow_error_envelope(
                code="not_found",
                message=(
                    f"Milestone artifact {artifact_id} was not found for milestone {milestone_id}."
                ),
                details={"milestone_id": milestone_id, "artifact_id": artifact_id},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 404
    payload: dict[str, object] = {
        "ok": True,
        "milestone_id": milestone_id,
        "item": _serialize_node_artifact(artifact),
        "request_id": request_id,
    }
    if correlation_id:
        payload["correlation_id"] = correlation_id
    return payload

@bp.delete("/milestones/<int:milestone_id>/artifacts/<int:artifact_id>")
def delete_milestone_artifact(milestone_id: int, artifact_id: int):
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    with session_scope() as session:
        if session.get(Milestone, milestone_id) is None:
            return _workflow_error_envelope(
                code="not_found",
                message=f"Milestone {milestone_id} was not found.",
                details={"milestone_id": milestone_id},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 404
        artifact = (
            session.execute(
                select(NodeArtifact).where(
                    NodeArtifact.id == artifact_id,
                    NodeArtifact.artifact_type == NODE_ARTIFACT_TYPE_MILESTONE,
                    NodeArtifact.ref_id == milestone_id,
                )
            )
            .scalars()
            .first()
        )
        if artifact is None:
            return _workflow_error_envelope(
                code="not_found",
                message=(
                    f"Milestone artifact {artifact_id} was not found for milestone {milestone_id}."
                ),
                details={"milestone_id": milestone_id, "artifact_id": artifact_id},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 404
        session.delete(artifact)
    payload: dict[str, object] = {
        "ok": True,
        "deleted": True,
        "milestone_id": milestone_id,
        "artifact_id": artifact_id,
        "request_id": request_id,
    }
    if correlation_id:
        payload["correlation_id"] = correlation_id
    return payload

@bp.get("/artifacts")
def list_node_artifacts():
    workflow_request_id = _workflow_request_id()
    workflow_correlation_id = _workflow_correlation_id()
    parsed, error_response = _parse_node_artifact_list_params(
        request_id=workflow_request_id,
        correlation_id=workflow_correlation_id,
    )
    if error_response is not None:
        return error_response
    assert parsed is not None
    try:
        ref_id = _coerce_optional_int(
            request.args.get("ref_id"),
            field_name="ref_id",
            minimum=1,
        )
    except ValueError as exc:
        return _workflow_error_envelope(
            code="invalid_request",
            message=str(exc),
            details={},
            request_id=workflow_request_id,
            correlation_id=workflow_correlation_id,
        ), 400

    artifact_type_filter = str(request.args.get("artifact_type") or "").strip().lower()
    node_type_filter = str(request.args.get("node_type") or "").strip().lower()
    request_id_filter = str(request.args.get("trace_request_id") or request.args.get("request_id") or "").strip()
    correlation_id_filter = str(
        request.args.get("trace_correlation_id") or request.args.get("correlation_id") or ""
    ).strip()
    if artifact_type_filter and artifact_type_filter not in NODE_ARTIFACT_TYPE_FILTER_CHOICES:
        return _workflow_error_envelope(
            code="invalid_request",
            message="artifact_type is not supported.",
            details={
                "artifact_type": artifact_type_filter,
                "supported": sorted(NODE_ARTIFACT_TYPE_FILTER_CHOICES),
            },
            request_id=workflow_request_id,
            correlation_id=workflow_correlation_id,
        ), 400
    if node_type_filter and node_type_filter not in FLOWCHART_NODE_TYPE_CHOICES:
        return _workflow_error_envelope(
            code="invalid_request",
            message="node_type is not supported.",
            details={
                "node_type": node_type_filter,
                "supported": sorted(FLOWCHART_NODE_TYPE_CHOICES),
            },
            request_id=workflow_request_id,
            correlation_id=workflow_correlation_id,
        ), 400

    with session_scope() as session:
        artifact_filters: list[object] = []
        flowchart_id = parsed["flowchart_id"]
        flowchart_node_id = parsed["flowchart_node_id"]
        flowchart_run_id = parsed["flowchart_run_id"]
        flowchart_run_node_id = parsed["flowchart_run_node_id"]
        if isinstance(flowchart_id, int):
            artifact_filters.append(NodeArtifact.flowchart_id == flowchart_id)
        if isinstance(flowchart_node_id, int):
            artifact_filters.append(NodeArtifact.flowchart_node_id == flowchart_node_id)
        if isinstance(flowchart_run_id, int):
            artifact_filters.append(NodeArtifact.flowchart_run_id == flowchart_run_id)
        if isinstance(flowchart_run_node_id, int):
            artifact_filters.append(NodeArtifact.flowchart_run_node_id == flowchart_run_node_id)
        if artifact_type_filter:
            artifact_filters.append(
                func.lower(NodeArtifact.artifact_type) == artifact_type_filter
            )
        if node_type_filter:
            artifact_filters.append(func.lower(NodeArtifact.node_type) == node_type_filter)
        if isinstance(ref_id, int):
            artifact_filters.append(NodeArtifact.ref_id == ref_id)
        if request_id_filter:
            artifact_filters.append(NodeArtifact.request_id == request_id_filter)
        if correlation_id_filter:
            artifact_filters.append(NodeArtifact.correlation_id == correlation_id_filter)

        total_count = (
            session.execute(select(func.count(NodeArtifact.id)).where(*artifact_filters))
            .scalar_one()
        )
        stmt = select(NodeArtifact).where(*artifact_filters)
        if parsed["descending"]:
            stmt = stmt.order_by(NodeArtifact.created_at.desc(), NodeArtifact.id.desc())
        else:
            stmt = stmt.order_by(NodeArtifact.created_at.asc(), NodeArtifact.id.asc())
        artifacts = (
            session.execute(
                stmt.limit(int(parsed["limit"])).offset(int(parsed["offset"]))
            )
            .scalars()
            .all()
        )
    payload: dict[str, object] = {
        "ok": True,
        "count": len(artifacts),
        "total_count": int(total_count or 0),
        "limit": int(parsed["limit"]),
        "offset": int(parsed["offset"]),
        "filters": {
            "artifact_type": artifact_type_filter or None,
            "node_type": node_type_filter or None,
            "flowchart_id": parsed["flowchart_id"],
            "flowchart_node_id": parsed["flowchart_node_id"],
            "flowchart_run_id": parsed["flowchart_run_id"],
            "flowchart_run_node_id": parsed["flowchart_run_node_id"],
            "ref_id": ref_id,
            "request_id": request_id_filter or None,
            "correlation_id": correlation_id_filter or None,
        },
        "items": [_serialize_node_artifact(item) for item in artifacts],
        "request_id": workflow_request_id,
    }
    if workflow_correlation_id:
        payload["correlation_id"] = workflow_correlation_id
    return payload

@bp.get("/artifacts/<int:artifact_id>")
def view_node_artifact(artifact_id: int):
    workflow_request_id = _workflow_request_id()
    workflow_correlation_id = _workflow_correlation_id()
    with session_scope() as session:
        artifact = session.get(NodeArtifact, artifact_id)
        if artifact is None:
            return _workflow_error_envelope(
                code="not_found",
                message=f"Artifact {artifact_id} was not found.",
                details={"artifact_id": artifact_id},
                request_id=workflow_request_id,
                correlation_id=workflow_correlation_id,
            ), 404
    payload: dict[str, object] = {
        "ok": True,
        "item": _serialize_node_artifact(artifact),
        "request_id": workflow_request_id,
    }
    if workflow_correlation_id:
        payload["correlation_id"] = workflow_correlation_id
    return payload

@bp.get("/attachments")
def list_attachments():
    attachments = _load_attachments()
    if _workflow_wants_json():
        return {
            "attachments": [_serialize_attachment(attachment) for attachment in attachments],
        }
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
    attachment_payload: dict[str, object] | None = None
    task_payload: list[dict[str, object]] = []
    node_payload: list[dict[str, object]] = []
    agents_by_id: dict[int, str] = {}
    flowcharts_by_id: dict[int, str] = {}
    with session_scope() as session:
        attachment = (
            session.execute(
                select(Attachment)
                .options(
                    selectinload(Attachment.tasks),
                    selectinload(Attachment.flowchart_nodes),
                )
                .where(Attachment.id == attachment_id)
            )
            .scalars()
            .first()
        )
        if attachment is None:
            abort(404)
        tasks = list(attachment.tasks)
        flowchart_nodes = list(attachment.flowchart_nodes)

        tasks.sort(key=lambda item: item.created_at or datetime.min, reverse=True)
        flowchart_nodes.sort(key=lambda item: item.updated_at or datetime.min, reverse=True)

        agent_ids = {task.agent_id for task in tasks if task.agent_id is not None}
        flowchart_ids = {
            int(node.flowchart_id)
            for node in flowchart_nodes
            if node.flowchart_id is not None
        }

        if agent_ids:
            rows = session.execute(
                select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids))
            ).all()
            agents_by_id = {row[0]: row[1] for row in rows}

        if flowchart_ids:
            rows = session.execute(
                select(Flowchart.id, Flowchart.name).where(
                    Flowchart.id.in_(flowchart_ids)
                )
            ).all()
            flowcharts_by_id = {row[0]: row[1] for row in rows}
        attachment_payload = _serialize_attachment(attachment)
        task_payload = [
            {
                "id": task.id,
                "agent_id": task.agent_id,
                "agent_name": agents_by_id.get(task.agent_id or 0, ""),
                "status": task.status,
                "prompt": task.prompt,
                "created_at": _human_time(task.created_at),
                "updated_at": _human_time(task.updated_at),
            }
            for task in tasks
        ]
        node_payload = [
            {
                "id": node.id,
                "flowchart_id": node.flowchart_id,
                "flowchart_name": flowcharts_by_id.get(node.flowchart_id or 0, ""),
                "node_type": node.node_type,
                "title": node.title,
                "ref_id": node.ref_id,
                "created_at": _human_time(node.created_at),
                "updated_at": _human_time(node.updated_at),
            }
            for node in flowchart_nodes
        ]

    is_image_attachment = _is_image_attachment(attachment)
    attachment_preview_url = None
    if is_image_attachment and attachment.file_path:
        attachment_preview_url = url_for(
            "agents.view_attachment_file", attachment_id=attachment.id
        )
    if _workflow_wants_json():
        return {
            "attachment": attachment_payload,
            "attachment_preview_url": attachment_preview_url,
            "is_image_attachment": is_image_attachment,
            "tasks": task_payload,
            "flowchart_nodes": node_payload,
            "agents_by_id": agents_by_id,
            "flowcharts_by_id": flowcharts_by_id,
        }

    return render_template(
        "attachment_detail.html",
        attachment=attachment,
        attachment_preview_url=attachment_preview_url,
        is_image_attachment=is_image_attachment,
        tasks=tasks,
        flowchart_nodes=flowchart_nodes,
        agents_by_id=agents_by_id,
        flowcharts_by_id=flowcharts_by_id,
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
    is_api_request = _workflow_api_request()
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
    if is_api_request:
        return {"ok": True}
    flash("Attachment deleted.", "success")
    return redirect(next_url)
