from .shared import *  # noqa: F401,F403

__all__ = ['list_mcps', 'list_models', 'new_model', 'create_model', 'view_model', 'edit_model', 'update_model', 'update_default_model', 'delete_model', 'new_mcp', 'create_mcp', 'edit_mcp', 'update_mcp', 'delete_mcp', 'view_mcp', 'list_scripts', 'list_skills', 'new_skill', 'create_skill', 'import_skill', 'import_skill_submit', 'view_skill', 'edit_skill', 'update_skill', 'export_skill', 'delete_skill', 'list_memories', 'new_memory', 'create_memory', 'view_memory', 'view_memory_history', 'edit_memory', 'update_memory', 'delete_memory', 'new_script', 'create_script', 'view_script', 'edit_script', 'update_script', 'delete_script']

@bp.get("/mcps")
def list_mcps():
    sync_integrated_mcp_servers()
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    mcp_servers = _load_mcp_servers()
    integrated_mcp_servers, custom_mcp_servers = _split_mcp_servers_by_type(mcp_servers)
    if _workflow_wants_json():
        return {
            "integrated_mcp_servers": [
                _serialize_mcp_server(server, include_config=True)
                for server in integrated_mcp_servers
            ],
            "custom_mcp_servers": [
                _serialize_mcp_server(server, include_config=True)
                for server in custom_mcp_servers
            ],
            "summary": summary,
        }
    return render_template(
        "mcps.html",
        integrated_mcp_servers=integrated_mcp_servers,
        custom_mcp_servers=custom_mcp_servers,
        summary=summary,
        human_time=_human_time,
        page_title="MCP Servers",
        active_page="mcps",
    )

@bp.get("/models")
def list_models():
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    try:
        query = _parse_model_list_query()
    except ValueError as exc:
        if _workflow_wants_json():
            return _workflow_error_envelope(
                code="invalid_request",
                message=str(exc),
                details={},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 400
        flash(str(exc), "error")
        return redirect(url_for("agents.list_models"))

    provider_filter = str(query["provider_filter"])
    if provider_filter and provider_filter not in LLM_PROVIDERS:
        message = f"Unknown provider filter '{provider_filter}'."
        if _workflow_wants_json():
            return _workflow_error_envelope(
                code="invalid_request",
                message=message,
                details={"provider": provider_filter},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 400
        flash(message, "error")
        return redirect(url_for("agents.list_models"))

    with session_scope() as session:
        filters = []
        if provider_filter:
            filters.append(LLMModel.provider == provider_filter)
        search_text = str(query["search_text"])
        if search_text:
            pattern = f"%{search_text.lower()}%"
            filters.append(
                or_(
                    func.lower(LLMModel.name).like(pattern),
                    func.lower(func.coalesce(LLMModel.description, "")).like(pattern),
                    func.lower(LLMModel.provider).like(pattern),
                )
            )

        total_count = int(
            session.scalar(select(func.count(LLMModel.id)).where(*filters)) or 0
        )
        sort_by = str(query["sort_by"])
        sort_order = str(query["sort_order"])
        sort_column = MODEL_LIST_SORT_FIELDS[sort_by]
        stmt = select(LLMModel).where(*filters)
        if sort_order == "asc":
            stmt = stmt.order_by(sort_column.asc(), LLMModel.id.asc())
        else:
            stmt = stmt.order_by(sort_column.desc(), LLMModel.id.desc())

        page = int(query["page"])
        per_page = query["per_page"]
        if isinstance(per_page, int):
            offset = (page - 1) * per_page
            stmt = stmt.limit(per_page).offset(offset)
        models = session.execute(stmt).scalars().all()

    llm_settings = _load_integration_settings("llm")
    default_model_id = resolve_default_model_id(llm_settings)
    model_rows = [
        _serialize_model(model, default_model_id=default_model_id)
        for model in models
    ]
    drifted_count = sum(
        1
        for item in model_rows
        if isinstance(item.get("compatibility"), dict)
        and bool((item.get("compatibility") or {}).get("drift_detected"))
    )
    resolved_per_page = int(per_page) if isinstance(per_page, int) else max(1, len(model_rows) or total_count or 1)
    pagination_payload = {
        "page": int(query["page"]),
        "per_page": resolved_per_page,
        "has_prev": int(query["page"]) > 1,
        "has_next": int(query["page"]) * resolved_per_page < total_count,
    }
    payload = {
        "models": model_rows,
        "default_model_id": default_model_id,
        "count": len(model_rows),
        "total_count": total_count,
        "pagination": pagination_payload,
        "filters": {
            "search": str(query["search_text"]),
            "provider": provider_filter,
        },
        "sort": {
            "by": str(query["sort_by"]),
            "order": str(query["sort_order"]),
        },
        "compatibility_summary": {
            "drifted_count": drifted_count,
            "in_sync_count": len(model_rows) - drifted_count,
        },
    }
    if _workflow_wants_json():
        return _workflow_success_payload(
            payload=payload,
            request_id=request_id,
            correlation_id=correlation_id,
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
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    model_options = _provider_model_options()
    local_vllm_models = discover_vllm_local_models()
    codex_default_model = _codex_default_model(model_options.get("codex"))
    vllm_local_default_model = _vllm_local_default_model(local_vllm_models)
    vllm_remote_default_model = _vllm_remote_default_model()
    if _workflow_wants_json():
        return _workflow_success_payload(
            payload={
                "provider_options": _provider_options(),
                "selected_provider": "codex",
                "codex_config": _codex_model_config_defaults(
                    {},
                    default_model=codex_default_model,
                ),
                "gemini_config": _gemini_model_config_defaults({}),
                "claude_config": _simple_model_config_defaults({}),
                "vllm_local_config": _vllm_local_model_config_defaults(
                    {},
                    default_model=vllm_local_default_model,
                ),
                "vllm_remote_config": _vllm_remote_model_config_defaults(
                    {},
                    default_model=vllm_remote_default_model,
                ),
                "vllm_local_models": local_vllm_models,
                "model_options": model_options,
            },
            request_id=request_id,
            correlation_id=correlation_id,
        )
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
        vllm_local_config=_vllm_local_model_config_defaults(
            {},
            default_model=vllm_local_default_model,
        ),
        vllm_remote_config=_vllm_remote_model_config_defaults(
            {},
            default_model=vllm_remote_default_model,
        ),
        vllm_local_models=local_vllm_models,
        model_options=model_options,
        page_title="Create Model",
        active_page="models",
    )

@bp.post("/models")
def create_model():
    is_api_request = _workflow_api_request()
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None or not isinstance(payload, dict):
        payload = {}
    name_raw = payload.get("name") if is_api_request else request.form.get("name", "")
    description_raw = (
        payload.get("description")
        if is_api_request
        else request.form.get("description", "")
    )
    provider_raw = (
        payload.get("provider")
        if is_api_request
        else request.form.get("provider")
    )
    name = str(name_raw or "").strip()
    description = str(description_raw or "").strip()
    provider = str(provider_raw or "").strip().lower()

    if not name:
        if is_api_request:
            return _workflow_error_envelope(
                code="invalid_request",
                message="Model name is required.",
                details={},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 400
        flash("Model name is required.", "error")
        return redirect(url_for("agents.new_model"))
    if provider not in LLM_PROVIDERS:
        if is_api_request:
            return _workflow_error_envelope(
                code="invalid_request",
                message="Unknown provider selection.",
                details={"provider": provider},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 400
        flash("Unknown provider selection.", "error")
        return redirect(url_for("agents.new_model"))

    config_payload: dict[str, object]
    if is_api_request and "config" in payload:
        raw_config = payload.get("config")
        if isinstance(raw_config, dict):
            config_payload = raw_config
        elif isinstance(raw_config, str):
            try:
                parsed_config = json.loads(raw_config)
            except json.JSONDecodeError:
                return _workflow_error_envelope(
                    code="invalid_request",
                    message="config must be valid JSON.",
                    details={},
                    request_id=request_id,
                    correlation_id=correlation_id,
                ), 400
            if not isinstance(parsed_config, dict):
                return _workflow_error_envelope(
                    code="invalid_request",
                    message="config must be an object.",
                    details={},
                    request_id=request_id,
                    correlation_id=correlation_id,
                ), 400
            config_payload = parsed_config
        else:
            return _workflow_error_envelope(
                code="invalid_request",
                message="config must be an object.",
                details={},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 400
    else:
        config_source = (
            {key: ("" if value is None else str(value)) for key, value in payload.items()}
            if is_api_request
            else request.form
        )
        config_payload = _model_config_payload(provider, config_source)

    markdown_filename_error = _apply_model_markdown_filename_validation(
        provider,
        config_payload,
    )
    if markdown_filename_error:
        if is_api_request:
            return _workflow_error_envelope(
                code="invalid_request",
                message=markdown_filename_error,
                details={},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 400
        flash(markdown_filename_error, "error")
        return redirect(url_for("agents.new_model"))
    model_options = _provider_model_options()
    model_name = str(config_payload.get("model") or "").strip()
    if provider == "codex" and not _model_option_allowed(provider, model_name, model_options):
        if is_api_request:
            return _workflow_error_envelope(
                code="invalid_request",
                message="Codex model must be selected from the configured options.",
                details={"provider": provider, "model": model_name},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 400
        flash("Codex model must be selected from the configured options.", "error")
        return redirect(url_for("agents.new_model"))
    if provider == "vllm_local" and not _model_option_allowed(
        provider,
        model_name,
        model_options,
    ):
        if is_api_request:
            return _workflow_error_envelope(
                code="invalid_request",
                message=(
                    "vLLM Local model must be selected from the discovered local model options."
                ),
                details={"provider": provider, "model": model_name},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 400
        flash(
            "vLLM Local model must be selected from the discovered local model options.",
            "error",
        )
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
    model_payload = _serialize_model(model, include_config=True)

    if is_api_request:
        _emit_model_provider_event(
            event_type="config:model:created",
            entity_kind="model",
            entity_id=model.id,
            payload={"model": model_payload},
            request_id=request_id,
            correlation_id=correlation_id,
        )
        return _workflow_success_payload(
            payload={"model": model_payload},
            request_id=request_id,
            correlation_id=correlation_id,
        ), 201
    flash(f"Model {model.id} created.", "success")
    return redirect(url_for("agents.view_model", model_id=model.id))

@bp.get("/models/<int:model_id>")
def view_model(model_id: int):
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    is_api_request = _workflow_api_request()
    llm_settings = _load_integration_settings("llm")
    default_model_id = resolve_default_model_id(llm_settings)
    model_payload: dict[str, object] | None = None
    node_payload: list[dict[str, object]] = []
    task_payload: list[dict[str, object]] = []
    flowcharts_by_id: dict[int, str] = {}
    with session_scope() as session:
        model = session.get(LLMModel, model_id)
        if model is None:
            if is_api_request:
                return _workflow_error_envelope(
                    code="not_found",
                    message=f"Model {model_id} was not found.",
                    details={"model_id": model_id},
                    request_id=request_id,
                    correlation_id=correlation_id,
                ), 404
            abort(404)
        attached_nodes = (
            session.execute(
                select(FlowchartNode)
                .where(FlowchartNode.model_id == model_id)
                .order_by(FlowchartNode.created_at.desc())
            )
            .scalars()
            .all()
        )
        attached_tasks = (
            session.execute(
                select(AgentTask)
                .where(AgentTask.model_id == model_id)
                .order_by(AgentTask.created_at.desc())
            )
            .scalars()
            .all()
        )
        flowcharts_by_id: dict[int, str] = {}
        flowchart_ids = {
            node.flowchart_id for node in attached_nodes if node.flowchart_id is not None
        }
        if flowchart_ids:
            rows = session.execute(
                select(Flowchart.id, Flowchart.name).where(Flowchart.id.in_(flowchart_ids))
            ).all()
            flowcharts_by_id = {row[0]: row[1] for row in rows}
        model_payload = _serialize_model(
            model,
            default_model_id=default_model_id,
            include_config=True,
        )
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
            for node in attached_nodes
        ]
        task_payload = [
            {
                "id": task.id,
                "agent_id": task.agent_id,
                "run_id": task.run_id,
                "status": task.status,
                "prompt": task.prompt,
                "created_at": _human_time(task.created_at),
                "updated_at": _human_time(task.updated_at),
            }
            for task in attached_tasks
        ]
    assert model_payload is not None
    if _workflow_wants_json():
        return _workflow_success_payload(
            payload={
                "model": model_payload,
                "attached_nodes": node_payload,
                "attached_tasks": task_payload,
                "flowcharts_by_id": flowcharts_by_id,
                "is_default": bool(model_payload.get("is_default")),
            },
            request_id=request_id,
            correlation_id=correlation_id,
        )
    is_default = bool(model_payload.get("is_default"))
    formatted_config = str(model_payload.get("config_json") or "{}")
    provider_label = str(model_payload.get("provider_label") or "")
    return render_template(
        "model_detail.html",
        model=model,
        provider_label=provider_label,
        model_name=_model_display_name(model),
        config_json=formatted_config,
        attached_nodes=attached_nodes,
        attached_tasks=attached_tasks,
        flowcharts_by_id=flowcharts_by_id,
        is_default=is_default,
        page_title=f"Model - {model.name}",
        active_page="models",
    )

@bp.get("/models/<int:model_id>/edit")
def edit_model(model_id: int):
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    is_api_request = _workflow_api_request()
    with session_scope() as session:
        model = session.get(LLMModel, model_id)
        if model is None:
            if is_api_request:
                return _workflow_error_envelope(
                    code="not_found",
                    message=f"Model {model_id} was not found.",
                    details={"model_id": model_id},
                    request_id=request_id,
                    correlation_id=correlation_id,
                ), 404
            abort(404)
    config = _decode_model_config(model.config_json)
    model_options = _provider_model_options()
    local_vllm_models = discover_vllm_local_models()
    codex_default_model = _codex_default_model(model_options.get("codex"))
    vllm_local_default_model = _vllm_local_default_model(local_vllm_models)
    vllm_remote_default_model = _vllm_remote_default_model()
    if _workflow_wants_json():
        return _workflow_success_payload(
            payload={
                "model": _serialize_model(model, include_config=True),
                "provider_options": _provider_options(),
                "selected_provider": model.provider,
                "codex_config": _codex_model_config_defaults(
                    config if model.provider == "codex" else {},
                    default_model=codex_default_model,
                ),
                "gemini_config": _gemini_model_config_defaults(
                    config if model.provider == "gemini" else {}
                ),
                "claude_config": _simple_model_config_defaults(
                    config if model.provider == "claude" else {}
                ),
                "vllm_local_config": _vllm_local_model_config_defaults(
                    config if model.provider == "vllm_local" else {},
                    default_model=vllm_local_default_model,
                ),
                "vllm_remote_config": _vllm_remote_model_config_defaults(
                    config if model.provider == "vllm_remote" else {},
                    default_model=vllm_remote_default_model,
                ),
                "vllm_local_models": local_vllm_models,
                "model_options": model_options,
            },
            request_id=request_id,
            correlation_id=correlation_id,
        )
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
        vllm_local_config=_vllm_local_model_config_defaults(
            config if model.provider == "vllm_local" else {},
            default_model=vllm_local_default_model,
        ),
        vllm_remote_config=_vllm_remote_model_config_defaults(
            config if model.provider == "vllm_remote" else {},
            default_model=vllm_remote_default_model,
        ),
        vllm_local_models=local_vllm_models,
        model_options=model_options,
        page_title=f"Edit Model - {model.name}",
        active_page="models",
    )

@bp.post("/models/<int:model_id>")
def update_model(model_id: int):
    is_api_request = _workflow_api_request()
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None or not isinstance(payload, dict):
        payload = {}
    name_raw = payload.get("name") if is_api_request else request.form.get("name", "")
    description_raw = (
        payload.get("description")
        if is_api_request
        else request.form.get("description", "")
    )
    provider_raw = (
        payload.get("provider")
        if is_api_request
        else request.form.get("provider")
    )
    name = str(name_raw or "").strip()
    description = str(description_raw or "").strip()
    provider = str(provider_raw or "").strip().lower()

    if not name:
        if is_api_request:
            return _workflow_error_envelope(
                code="invalid_request",
                message="Model name is required.",
                details={},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 400
        flash("Model name is required.", "error")
        return redirect(url_for("agents.edit_model", model_id=model_id))
    if provider not in LLM_PROVIDERS:
        if is_api_request:
            return _workflow_error_envelope(
                code="invalid_request",
                message="Unknown provider selection.",
                details={"provider": provider},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 400
        flash("Unknown provider selection.", "error")
        return redirect(url_for("agents.edit_model", model_id=model_id))

    config_payload: dict[str, object]
    if is_api_request and "config" in payload:
        raw_config = payload.get("config")
        if isinstance(raw_config, dict):
            config_payload = raw_config
        elif isinstance(raw_config, str):
            try:
                parsed_config = json.loads(raw_config)
            except json.JSONDecodeError:
                return _workflow_error_envelope(
                    code="invalid_request",
                    message="config must be valid JSON.",
                    details={},
                    request_id=request_id,
                    correlation_id=correlation_id,
                ), 400
            if not isinstance(parsed_config, dict):
                return _workflow_error_envelope(
                    code="invalid_request",
                    message="config must be an object.",
                    details={},
                    request_id=request_id,
                    correlation_id=correlation_id,
                ), 400
            config_payload = parsed_config
        else:
            return _workflow_error_envelope(
                code="invalid_request",
                message="config must be an object.",
                details={},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 400
    else:
        config_source = (
            {key: ("" if value is None else str(value)) for key, value in payload.items()}
            if is_api_request
            else request.form
        )
        config_payload = _model_config_payload(provider, config_source)

    markdown_filename_error = _apply_model_markdown_filename_validation(
        provider,
        config_payload,
    )
    if markdown_filename_error:
        if is_api_request:
            return _workflow_error_envelope(
                code="invalid_request",
                message=markdown_filename_error,
                details={},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 400
        flash(markdown_filename_error, "error")
        return redirect(url_for("agents.edit_model", model_id=model_id))
    model_options = _provider_model_options()
    model_name = str(config_payload.get("model") or "").strip()
    if provider == "codex" and not _model_option_allowed(provider, model_name, model_options):
        if is_api_request:
            return _workflow_error_envelope(
                code="invalid_request",
                message="Codex model must be selected from the configured options.",
                details={"provider": provider, "model": model_name},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 400
        flash("Codex model must be selected from the configured options.", "error")
        return redirect(url_for("agents.edit_model", model_id=model_id))
    if provider == "vllm_local" and not _model_option_allowed(
        provider,
        model_name,
        model_options,
    ):
        if is_api_request:
            return _workflow_error_envelope(
                code="invalid_request",
                message=(
                    "vLLM Local model must be selected from the discovered local model options."
                ),
                details={"provider": provider, "model": model_name},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 400
        flash(
            "vLLM Local model must be selected from the discovered local model options.",
            "error",
        )
        return redirect(url_for("agents.edit_model", model_id=model_id))
    config_json = json.dumps(config_payload, indent=2, sort_keys=True)

    with session_scope() as session:
        model = session.get(LLMModel, model_id)
        if model is None:
            if is_api_request:
                return _workflow_error_envelope(
                    code="not_found",
                    message=f"Model {model_id} was not found.",
                    details={"model_id": model_id},
                    request_id=request_id,
                    correlation_id=correlation_id,
                ), 404
            abort(404)
        model.name = name
        model.description = description or None
        model.provider = provider
        model.config_json = config_json
    model_payload = _serialize_model(model, include_config=True)

    if is_api_request:
        _emit_model_provider_event(
            event_type="config:model:updated",
            entity_kind="model",
            entity_id=model.id,
            payload={"model": model_payload},
            request_id=request_id,
            correlation_id=correlation_id,
        )
        return _workflow_success_payload(
            payload={"model": model_payload},
            request_id=request_id,
            correlation_id=correlation_id,
        )
    flash("Model updated.", "success")
    return redirect(url_for("agents.view_model", model_id=model_id))

@bp.post("/models/default")
def update_default_model():
    is_api_request = _workflow_api_request()
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None or not isinstance(payload, dict):
        payload = {}
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_models")
    )
    model_raw = (
        str(payload.get("model_id") or "").strip()
        if is_api_request
        else request.form.get("model_id", "").strip()
    )
    if not model_raw.isdigit():
        if is_api_request:
            return _workflow_error_envelope(
                code="invalid_request",
                message="Model selection required.",
                details={},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 400
        flash("Model selection required.", "error")
        return redirect(next_url)
    model_id = int(model_raw)
    make_default = (
        bool(payload.get("is_default"))
        if is_api_request
        else _as_bool(request.form.get("is_default"))
    )
    with session_scope() as session:
        model = session.get(LLMModel, model_id)
        if model is None:
            if is_api_request:
                return _workflow_error_envelope(
                    code="not_found",
                    message="Model not found.",
                    details={"model_id": model_id},
                    request_id=request_id,
                    correlation_id=correlation_id,
                ), 404
            flash("Model not found.", "error")
            return redirect(next_url)
    if make_default:
        payload = {
            "default_model_id": str(model_id),
            f"provider_enabled_{model.provider}": "true",
        }
        _save_integration_settings("llm", payload)
        if is_api_request:
            _emit_model_provider_event(
                event_type="config:model:default_updated",
                entity_kind="model",
                entity_id=model_id,
                payload={"default_model_id": model_id, "is_default": True},
                request_id=request_id,
                correlation_id=correlation_id,
            )
            return _workflow_success_payload(
                payload={"default_model_id": model_id},
                request_id=request_id,
                correlation_id=correlation_id,
            )
        flash("Default model updated.", "success")
    else:
        _save_integration_settings("llm", {"default_model_id": ""})
        if is_api_request:
            _emit_model_provider_event(
                event_type="config:model:default_updated",
                entity_kind="model",
                entity_id=model_id,
                payload={"default_model_id": None, "is_default": False},
                request_id=request_id,
                correlation_id=correlation_id,
            )
            return _workflow_success_payload(
                payload={"default_model_id": None},
                request_id=request_id,
                correlation_id=correlation_id,
            )
        flash("Default model cleared.", "success")
    return redirect(next_url)

@bp.post("/models/<int:model_id>/delete")
def delete_model(model_id: int):
    is_api_request = _workflow_api_request()
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_models")
    )
    deleted_model_payload: dict[str, object] | None = None
    with session_scope() as session:
        model = session.get(LLMModel, model_id)
        if model is None:
            if is_api_request:
                return _workflow_error_envelope(
                    code="not_found",
                    message=f"Model {model_id} was not found.",
                    details={"model_id": model_id},
                    request_id=request_id,
                    correlation_id=correlation_id,
                ), 404
            abort(404)
        deleted_model_payload = _serialize_model(model, include_config=True)
        attached_node_count = int(
            session.scalar(
                select(func.count()).select_from(FlowchartNode).where(FlowchartNode.model_id == model_id)
            )
            or 0
        )
        attached_task_count = int(
            session.scalar(
                select(func.count()).select_from(AgentTask).where(AgentTask.model_id == model_id)
            )
            or 0
        )
        attached_thread_count = int(
            session.scalar(
                select(func.count()).select_from(ChatThread).where(ChatThread.model_id == model_id)
            )
            or 0
        )
        attached_turn_count = int(
            session.scalar(
                select(func.count()).select_from(ChatTurn).where(ChatTurn.model_id == model_id)
            )
            or 0
        )
        if attached_node_count:
            session.execute(
                update(FlowchartNode).where(FlowchartNode.model_id == model_id).values(model_id=None)
            )
        if attached_task_count:
            session.execute(update(AgentTask).where(AgentTask.model_id == model_id).values(model_id=None))
        if attached_thread_count:
            session.execute(
                update(ChatThread).where(ChatThread.model_id == model_id).values(model_id=None)
            )
        if attached_turn_count:
            session.execute(update(ChatTurn).where(ChatTurn.model_id == model_id).values(model_id=None))
        session.delete(model)

    detached_count = (
        attached_node_count
        + attached_task_count
        + attached_thread_count
        + attached_turn_count
    )
    default_cleared = False
    llm_settings = _load_integration_settings("llm")
    if resolve_default_model_id(llm_settings) == model_id:
        _save_integration_settings("llm", {"default_model_id": ""})
        default_cleared = True
    if is_api_request:
        _emit_model_provider_event(
            event_type="config:model:deleted",
            entity_kind="model",
            entity_id=model_id,
            payload={
                "model": deleted_model_payload or {"id": model_id},
                "detached_count": detached_count,
                "default_model_cleared": default_cleared,
            },
            request_id=request_id,
            correlation_id=correlation_id,
        )
        return _workflow_success_payload(
            payload={
                "detached_count": detached_count,
                "default_model_cleared": default_cleared,
            },
            request_id=request_id,
            correlation_id=correlation_id,
        )
    flash("Model deleted.", "success")
    if detached_count:
        flash(f"Detached from {detached_count} binding(s).", "info")
    if default_cleared:
        flash("Default model cleared.", "info")
    return redirect(next_url)

@bp.get("/mcps/new")
def new_mcp():
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    if _workflow_wants_json():
        return {
            "summary": summary,
            "mcp": {
                "name": "",
                "server_key": "",
                "description": "",
                "config_json": "{}",
            },
        }
    return render_template(
        "mcp_new.html",
        summary=summary,
        page_title="Create Custom MCP Server",
        active_page="mcps",
    )

@bp.post("/mcps")
def create_mcp():
    is_api_request = _workflow_api_request()
    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None or not isinstance(payload, dict):
        payload = {}
    name = str(payload.get("name") if is_api_request else request.form.get("name", "")).strip()
    server_key = str(
        payload.get("server_key") if is_api_request else request.form.get("server_key", "")
    ).strip()
    description = str(
        payload.get("description")
        if is_api_request
        else request.form.get("description", "")
    ).strip()
    if is_api_request and "config" in payload and "config_json" not in payload:
        raw_config_value = payload.get("config")
        raw_config = (
            json.dumps(raw_config_value, indent=2, sort_keys=True)
            if isinstance(raw_config_value, dict)
            else str(raw_config_value or "")
        )
    else:
        raw_config = str(
            payload.get("config_json")
            if is_api_request
            else request.form.get("config_json", "")
        ).strip()

    if not name or not server_key:
        if is_api_request:
            return {"error": "Name and server key are required."}, 400
        flash("Name and server key are required.", "error")
        return redirect(url_for("agents.new_mcp"))
    if not raw_config:
        if is_api_request:
            return {"error": "MCP config JSON is required."}, 400
        flash("MCP config JSON is required.", "error")
        return redirect(url_for("agents.new_mcp"))
    if server_key in SYSTEM_MANAGED_MCP_SERVER_KEYS:
        if is_api_request:
            return {
                "error": f"Server key '{server_key}' is system-managed and cannot be created manually."
            }, 400
        flash(
            f"Server key '{server_key}' is system-managed and cannot be created manually.",
            "error",
        )
        return redirect(url_for("agents.new_mcp"))

    try:
        validate_server_key(server_key)
        formatted_config = format_mcp_config(raw_config, server_key=server_key)
    except ValueError as exc:
        if is_api_request:
            return {"error": str(exc)}, 400
        flash(str(exc), "error")
        return redirect(url_for("agents.new_mcp"))

    with session_scope() as session:
        existing = session.execute(
            select(MCPServer).where(MCPServer.server_key == server_key)
        ).scalar_one_or_none()
        if existing is not None:
            if is_api_request:
                return {"error": "Server key is already in use."}, 409
            flash("Server key is already in use.", "error")
            return redirect(url_for("agents.new_mcp"))
        mcp = MCPServer.create(
            session,
            name=name,
            server_key=server_key,
            description=description or None,
            config_json=formatted_config,
            server_type=MCP_SERVER_TYPE_CUSTOM,
        )

    if is_api_request:
        return {"ok": True, "mcp_server": _serialize_mcp_server(mcp, include_config=True)}, 201
    flash(f"MCP server {mcp.id} created.", "success")
    return redirect(url_for("agents.view_mcp", mcp_id=mcp.id))

@bp.get("/mcps/<int:mcp_id>/edit")
def edit_mcp(mcp_id: int):
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    mcp_payload: dict[str, object] | None = None
    with session_scope() as session:
        mcp_server = session.get(MCPServer, mcp_id)
        if mcp_server is None:
            abort(404)
        if mcp_server.is_integrated:
            if _workflow_wants_json():
                return {
                    "error": "Integrated MCP servers are managed from Integrations settings."
                }, 409
            flash("Integrated MCP servers are managed from Integrations settings.", "error")
            return redirect(url_for("agents.view_mcp", mcp_id=mcp_id))
        mcp_payload = _serialize_mcp_server(mcp_server, include_config=True)
    assert mcp_payload is not None
    if _workflow_wants_json():
        return {
            "mcp_server": mcp_payload,
            "summary": summary,
        }
    return render_template(
        "mcp_edit.html",
        mcp_server=mcp_server,
        mcp_config_json=_format_json_object_for_display(mcp_server.config_json),
        summary=summary,
        page_title=f"Edit Custom MCP Server - {mcp_server.name}",
        active_page="mcps",
    )

@bp.post("/mcps/<int:mcp_id>")
def update_mcp(mcp_id: int):
    is_api_request = _workflow_api_request()
    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None or not isinstance(payload, dict):
        payload = {}
    name = str(payload.get("name") if is_api_request else request.form.get("name", "")).strip()
    server_key = str(
        payload.get("server_key") if is_api_request else request.form.get("server_key", "")
    ).strip()
    description = str(
        payload.get("description")
        if is_api_request
        else request.form.get("description", "")
    ).strip()
    if is_api_request and "config" in payload and "config_json" not in payload:
        raw_config_value = payload.get("config")
        raw_config = (
            json.dumps(raw_config_value, indent=2, sort_keys=True)
            if isinstance(raw_config_value, dict)
            else str(raw_config_value or "")
        )
    else:
        raw_config = str(
            payload.get("config_json")
            if is_api_request
            else request.form.get("config_json", "")
        ).strip()

    if not name or not server_key:
        if is_api_request:
            return {"error": "Name and server key are required."}, 400
        flash("Name and server key are required.", "error")
        return redirect(url_for("agents.edit_mcp", mcp_id=mcp_id))
    if not raw_config:
        if is_api_request:
            return {"error": "MCP config JSON is required."}, 400
        flash("MCP config JSON is required.", "error")
        return redirect(url_for("agents.edit_mcp", mcp_id=mcp_id))

    try:
        validate_server_key(server_key)
        formatted_config = format_mcp_config(raw_config, server_key=server_key)
    except ValueError as exc:
        if is_api_request:
            return {"error": str(exc)}, 400
        flash(str(exc), "error")
        return redirect(url_for("agents.edit_mcp", mcp_id=mcp_id))

    updated_payload: dict[str, object] | None = None
    with session_scope() as session:
        mcp = session.get(MCPServer, mcp_id)
        if mcp is None:
            abort(404)
        if mcp.is_integrated:
            if is_api_request:
                return {
                    "error": "Integrated MCP servers are managed from Integrations settings."
                }, 409
            flash("Integrated MCP servers are managed from Integrations settings.", "error")
            return redirect(url_for("agents.view_mcp", mcp_id=mcp_id))
        if (
            server_key in SYSTEM_MANAGED_MCP_SERVER_KEYS
            and server_key != mcp.server_key
        ):
            if is_api_request:
                return {
                    "error": f"Server key '{server_key}' is system-managed and cannot be edited manually."
                }, 400
            flash(
                f"Server key '{server_key}' is system-managed and cannot be edited manually.",
                "error",
            )
            return redirect(url_for("agents.edit_mcp", mcp_id=mcp_id))
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
            if is_api_request:
                return {"error": "Server key is already in use."}, 409
            flash("Server key is already in use.", "error")
            return redirect(url_for("agents.edit_mcp", mcp_id=mcp_id))
        mcp.name = name
        mcp.server_key = server_key
        mcp.description = description or None
        mcp.config_json = formatted_config
        updated_payload = _serialize_mcp_server(mcp, include_config=True)

    if is_api_request:
        return {"ok": True, "mcp_server": updated_payload}
    flash("MCP server updated.", "success")
    return redirect(url_for("agents.view_mcp", mcp_id=mcp_id))

@bp.post("/mcps/<int:mcp_id>/delete")
def delete_mcp(mcp_id: int):
    is_api_request = _workflow_api_request()
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_mcps")
    )
    with session_scope() as session:
        mcp = session.get(MCPServer, mcp_id)
        if mcp is None:
            abort(404)
        if mcp.is_integrated:
            if is_api_request:
                return {"error": "Integrated MCP servers cannot be deleted."}, 409
            flash("Integrated MCP servers cannot be deleted.", "error")
            return redirect(next_url)
        attached_nodes = list(mcp.flowchart_nodes)
        attached_tasks = list(mcp.tasks)
        if attached_nodes:
            mcp.flowchart_nodes = []
        if attached_tasks:
            mcp.tasks = []
        session.delete(mcp)

    detached_count = len(attached_nodes) + len(attached_tasks)
    if is_api_request:
        return {"ok": True, "detached_count": detached_count}
    flash("MCP server deleted.", "success")
    if detached_count:
        flash(f"Detached from {detached_count} binding(s).", "info")
    return redirect(next_url)

@bp.get("/mcps/<int:mcp_id>")
def view_mcp(mcp_id: int):
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    mcp_payload: dict[str, object] | None = None
    node_payload: list[dict[str, object]] = []
    task_payload: list[dict[str, object]] = []
    flowcharts_by_id: dict[int, str] = {}
    with session_scope() as session:
        mcp_server = (
            session.execute(
                select(MCPServer)
                .options(
                    selectinload(MCPServer.flowchart_nodes),
                    selectinload(MCPServer.tasks),
                )
                .where(MCPServer.id == mcp_id)
            )
            .scalars()
            .first()
        )
        if mcp_server is None:
            abort(404)
        attached_nodes = list(mcp_server.flowchart_nodes)
        attached_tasks = list(mcp_server.tasks)
        flowchart_ids = {
            node.flowchart_id for node in attached_nodes if node.flowchart_id is not None
        }
        if flowchart_ids:
            rows = session.execute(
                select(Flowchart.id, Flowchart.name).where(Flowchart.id.in_(flowchart_ids))
            ).all()
            flowcharts_by_id = {row[0]: row[1] for row in rows}
        mcp_payload = _serialize_mcp_server(mcp_server, include_config=True)
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
            for node in attached_nodes
        ]
        task_payload = [
            {
                "id": task.id,
                "agent_id": task.agent_id,
                "run_id": task.run_id,
                "status": task.status,
                "prompt": task.prompt,
                "created_at": _human_time(task.created_at),
                "updated_at": _human_time(task.updated_at),
            }
            for task in attached_tasks
        ]
    assert mcp_payload is not None
    if _workflow_wants_json():
        return {
            "mcp_server": mcp_payload,
            "attached_nodes": node_payload,
            "attached_tasks": task_payload,
            "flowcharts_by_id": flowcharts_by_id,
            "summary": summary,
        }
    return render_template(
        "mcp_detail.html",
        mcp_server=mcp_server,
        mcp_config_json=_format_json_object_for_display(mcp_server.config_json),
        attached_nodes=attached_nodes,
        attached_tasks=attached_tasks,
        flowcharts_by_id=flowcharts_by_id,
        summary=summary,
        human_time=_human_time,
        page_title=mcp_server.name,
        active_page="mcps",
    )

@bp.get("/scripts")
def list_scripts():
    scripts = _load_scripts()
    if _workflow_wants_json():
        return {
            "scripts": [_serialize_script(script) for script in scripts],
            "script_types": _serialize_choice_options(SCRIPT_TYPE_WRITE_CHOICES),
        }
    return render_template(
        "scripts.html",
        scripts=scripts,
        human_time=_human_time,
        page_title="Scripts",
        active_page="scripts",
    )

@bp.get("/skills")
def list_skills():
    skills = _load_skills()
    skill_rows: list[dict[str, object]] = [_serialize_skill(skill) for skill in skills]
    if _workflow_wants_json():
        return {
            "skills": skill_rows,
            "skill_status_options": _serialize_choice_options(SKILL_STATUS_OPTIONS),
        }
    return render_template(
        "skills.html",
        skills=skill_rows,
        human_time=_human_time,
        page_title="Skills",
        active_page="skills",
    )

@bp.get("/skills/new")
def new_skill():
    if _workflow_wants_json():
        return {
            "skill_status_options": _serialize_choice_options(SKILL_STATUS_OPTIONS),
            "upload_conflict_options": ["ask", "replace", "keep_both", "skip"],
            "max_upload_bytes": SKILL_UPLOAD_MAX_FILE_BYTES,
        }
    return render_template(
        "skill_new.html",
        skill_status_options=SKILL_STATUS_OPTIONS,
        upload_conflict_options=["ask", "replace", "keep_both", "skip"],
        max_upload_bytes=SKILL_UPLOAD_MAX_FILE_BYTES,
        page_title="Create Skill",
        active_page="skills",
    )

@bp.post("/skills")
def create_skill():
    is_api_request = _workflow_api_request()
    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None or not isinstance(payload, dict):
        payload = {}
    name = str(payload.get("name") if is_api_request else request.form.get("name", "")).strip()
    display_name = str(
        payload.get("display_name")
        if is_api_request
        else request.form.get("display_name", "")
    ).strip()
    description = str(
        payload.get("description")
        if is_api_request
        else request.form.get("description", "")
    ).strip()
    version = str(
        payload.get("version") if is_api_request else request.form.get("version", "")
    ).strip()
    status = str(
        payload.get("status") if is_api_request else request.form.get("status", "")
    ).strip().lower() or SKILL_STATUS_ACTIVE
    skill_md = str(
        payload.get("skill_md") if is_api_request else request.form.get("skill_md", "")
    )
    source_ref = str(
        payload.get("source_ref")
        if is_api_request
        else request.form.get("source_ref", "")
    ).strip()
    extra_files_raw = (
        payload.get("extra_files_json", payload.get("extra_files", ""))
        if is_api_request
        else request.form.get("extra_files_json", "")
    )
    if isinstance(extra_files_raw, list):
        extra_files_json = json.dumps(extra_files_raw)
    else:
        extra_files_json = str(extra_files_raw or "")

    extra_files, parse_error = _parse_skill_extra_files(extra_files_json)
    if parse_error:
        if is_api_request:
            return {"error": parse_error}, 400
        flash(parse_error, "error")
        return redirect(url_for("agents.new_skill"))
    upload_entries, upload_error = _collect_skill_upload_entries()
    if upload_error:
        if is_api_request:
            return {"error": upload_error}, 400
        flash(upload_error, "error")
        return redirect(url_for("agents.new_skill"))

    if not skill_md.strip():
        skill_md = _default_skill_markdown(
            name=name or "skill",
            display_name=display_name or "Skill",
            description=description or "Describe how and when this skill should be used.",
            version=version or "1.0.0",
            status=status or SKILL_STATUS_ACTIVE,
        )

    draft_file_map: dict[str, str] = {"SKILL.md": skill_md}
    for raw_path, content in extra_files:
        normalized_path = _normalize_skill_relative_path(raw_path)
        if not normalized_path:
            message = "Extra file paths must be relative and path-safe."
            if is_api_request:
                return {"error": message}, 400
            flash(message, "error")
            return redirect(url_for("agents.new_skill"))
        path_error = _skill_upload_path_error(normalized_path)
        if path_error:
            if is_api_request:
                return {"error": path_error}, 400
            flash(path_error, "error")
            return redirect(url_for("agents.new_skill"))
        if normalized_path in draft_file_map:
            message = f"Duplicate file path in extra files: {normalized_path}"
            if is_api_request:
                return {"error": message}, 400
            flash(message, "error")
            return redirect(url_for("agents.new_skill"))
        draft_file_map[normalized_path] = content
    draft_file_map, conflict_error = _apply_skill_upload_conflicts(draft_file_map, upload_entries)
    if conflict_error:
        if is_api_request:
            return {"error": conflict_error}, 400
        flash(conflict_error, "error")
        return redirect(url_for("agents.new_skill"))

    files = list(draft_file_map.items())
    metadata_overrides = {
        "name": name,
        "display_name": display_name,
        "description": description,
        "version": version,
        "status": status,
    }

    try:
        package = build_skill_package(files, metadata_overrides=metadata_overrides)
    except SkillPackageValidationError as exc:
        errors = format_validation_errors(exc.errors)
        message = str(errors[0].get("message") or "Skill package validation failed.")
        if is_api_request:
            return {"error": message, "validation_errors": errors}, 400
        flash(message, "error")
        return redirect(url_for("agents.new_skill"))

    created_payload: dict[str, object] | None = None
    try:
        with session_scope() as session:
            result = import_skill_package_to_db(
                session,
                package,
                source_type="ui",
                source_ref=source_ref or "web:create",
                actor=None,
            )
            skill = session.get(Skill, result.skill_id)
            if skill is None:
                abort(404)
            created_payload = _serialize_skill(skill)
            skill_id = result.skill_id
    except ValueError as exc:
        if is_api_request:
            return {"error": str(exc)}, 400
        flash(str(exc), "error")
        return redirect(url_for("agents.new_skill"))

    if is_api_request:
        return {"ok": True, "skill_id": skill_id, "skill": created_payload}, 201
    flash("Skill created.", "success")
    return redirect(url_for("agents.view_skill", skill_id=skill_id))

@bp.get("/skills/import")
def import_skill():
    if _workflow_wants_json():
        return {
            "preview": None,
            "validation_errors": [],
            "form_values": {},
        }
    return render_template(
        "skill_import.html",
        preview=None,
        validation_errors=[],
        form_values={},
        page_title="Import Skill",
        active_page="skills",
    )

@bp.post("/skills/import")
def import_skill_submit():
    is_api_request = _workflow_api_request()
    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None or not isinstance(payload, dict):
        payload = {}
    action = str(
        payload.get("action") if is_api_request else (request.form.get("action") or "preview")
    ).strip().lower()
    source_kind = str(
        payload.get("source_kind")
        if is_api_request
        else (request.form.get("source_kind") or "upload")
    ).strip().lower()
    local_path = str(
        payload.get("local_path")
        if is_api_request
        else request.form.get("local_path", "")
    ).strip()
    source_ref = str(
        payload.get("source_ref")
        if is_api_request
        else request.form.get("source_ref", "")
    ).strip()
    actor = str(
        payload.get("actor") if is_api_request else request.form.get("actor", "")
    ).strip()
    git_url = str(
        payload.get("git_url") if is_api_request else request.form.get("git_url", "")
    ).strip()

    form_values = {
        "source_kind": source_kind,
        "local_path": local_path,
        "source_ref": source_ref,
        "actor": actor,
        "git_url": git_url,
    }

    package: SkillPackage
    try:
        if source_kind == "upload":
            if is_api_request:
                bundle_payload = str(
                    payload.get("bundle_payload", payload.get("bundle_json", ""))
                )
                if not bundle_payload.strip():
                    return {"error": "Bundle upload is required."}, 400
                package = load_skill_bundle(bundle_payload)
            else:
                uploaded = request.files.get("bundle_file")
                if uploaded is None or not uploaded.filename:
                    flash("Bundle upload is required.", "error")
                    return redirect(url_for("agents.import_skill"))
                bundle_payload = uploaded.read().decode("utf-8", errors="replace")
                package = load_skill_bundle(bundle_payload)
        elif source_kind == "path":
            if not local_path:
                if is_api_request:
                    return {"error": "Local path is required."}, 400
                flash("Local path is required.", "error")
                return redirect(url_for("agents.import_skill"))
            package = build_skill_package_from_directory(local_path)
        elif source_kind == "git":
            if is_api_request:
                return {"error": "Git-based skill import is deferred to v1.1."}, 409
            flash("Git-based skill import is deferred to v1.1.", "error")
            return redirect(url_for("agents.import_skill"))
        else:
            if is_api_request:
                return {"error": "Unknown import source."}, 400
            flash("Unknown import source.", "error")
            return redirect(url_for("agents.import_skill"))
    except SkillPackageValidationError as exc:
        if is_api_request:
            return {
                "error": "Skill package validation failed.",
                "validation_errors": format_validation_errors(exc.errors),
                "form_values": form_values,
            }, 400
        return render_template(
            "skill_import.html",
            preview=None,
            validation_errors=format_validation_errors(exc.errors),
            form_values=form_values,
            page_title="Import Skill",
            active_page="skills",
        )

    preview = _build_skill_preview(package)

    if action == "import":
        try:
            with session_scope() as session:
                result = import_skill_package_to_db(
                    session,
                    package,
                    source_type="import",
                    source_ref=source_ref or source_kind,
                    actor=actor or None,
                )
                skill_id = result.skill_id
        except ValueError as exc:
            if is_api_request:
                return {
                    "error": str(exc),
                    "preview": preview,
                    "validation_errors": [],
                    "form_values": form_values,
                }, 400
            flash(str(exc), "error")
            return render_template(
                "skill_import.html",
                preview=preview,
                validation_errors=[],
                form_values=form_values,
                page_title="Import Skill",
                active_page="skills",
            )
        if is_api_request:
            return {"ok": True, "skill_id": skill_id, "preview": preview}
        flash("Skill imported.", "success")
        return redirect(url_for("agents.view_skill", skill_id=skill_id))

    if is_api_request:
        return {
            "preview": preview,
            "validation_errors": [],
            "form_values": form_values,
        }
    return render_template(
        "skill_import.html",
        preview=preview,
        validation_errors=[],
        form_values=form_values,
        page_title="Import Skill",
        active_page="skills",
    )

@bp.get("/skills/<int:skill_id>")
def view_skill(skill_id: int):
    requested_version = request.args.get("version", "").strip()
    skill_payload: dict[str, object] | None = None
    version_payload: list[dict[str, object]] = []
    attached_agents_payload: list[dict[str, object]] = []
    with session_scope() as session:
        skill = (
            session.execute(
                select(Skill)
                .options(
                    selectinload(Skill.versions).selectinload(SkillVersion.files),
                    selectinload(Skill.agents),
                )
                .where(Skill.id == skill_id)
            )
            .scalars()
            .first()
        )
        if skill is None:
            abort(404)

        versions = sorted(list(skill.versions or []), key=lambda item: item.id or 0, reverse=True)
        selected_version = None
        if requested_version:
            for entry in versions:
                if entry.version == requested_version:
                    selected_version = entry
                    break
        if selected_version is None and versions:
            selected_version = versions[0]

        attached_agents = sorted(
            list(skill.agents or []),
            key=lambda item: (item.name or "").lower(),
        )
        skill_payload = _serialize_skill(skill)
        version_payload = [
            {
                "id": entry.id,
                "version": entry.version,
                "manifest_hash": entry.manifest_hash or "",
                "created_at": _human_time(entry.created_at),
                "updated_at": _human_time(entry.updated_at),
            }
            for entry in versions
        ]
        attached_agents_payload = [
            {
                "id": agent.id,
                "name": agent.name,
                "description": agent.description or "",
                "status": _agent_status(agent),
                "created_at": _human_time(agent.created_at),
                "updated_at": _human_time(agent.updated_at),
            }
            for agent in attached_agents
        ]

    preview = None
    if selected_version is not None:
        preview = {
            "version_id": selected_version.id,
            "version": selected_version.version,
            "manifest_hash": selected_version.manifest_hash or "",
            "manifest": _parse_json_dict(selected_version.manifest_json),
            "files": [
                {
                    "id": entry.id,
                    "path": entry.path,
                    "size_bytes": entry.size_bytes,
                    "checksum": entry.checksum,
                    "is_binary": is_binary_skill_content(entry.content or ""),
                    "content_preview": _skill_file_preview_content(entry.content or ""),
                }
                for entry in sorted(list(selected_version.files or []), key=lambda item: item.path)
            ],
            "skill_md": _skill_file_content(selected_version, "SKILL.md"),
        }
    assert skill_payload is not None
    if _workflow_wants_json():
        return {
            "skill": skill_payload,
            "versions": version_payload,
            "selected_version": selected_version.version if selected_version is not None else None,
            "preview": preview,
            "attached_agents": attached_agents_payload,
            "skill_is_git_read_only": bool(skill_payload.get("is_git_read_only")),
        }

    return render_template(
        "skill_detail.html",
        skill=skill,
        versions=versions,
        selected_version=selected_version,
        preview=preview,
        attached_agents=attached_agents,
        skill_is_git_read_only=_is_git_based_skill(skill),
        human_time=_human_time,
        page_title=f"Skill - {skill.display_name}",
        active_page="skills",
    )

@bp.get("/skills/<int:skill_id>/edit")
def edit_skill(skill_id: int):
    response_payload: dict[str, object] | None = None
    with session_scope() as session:
        skill = (
            session.execute(
                select(Skill)
                .options(selectinload(Skill.versions).selectinload(SkillVersion.files))
                .where(Skill.id == skill_id)
            )
            .scalars()
            .first()
        )
        if skill is None:
            abort(404)
        if _is_git_based_skill(skill):
            if _workflow_wants_json():
                return {
                    "error": "Git-based skills are read-only in Studio. Edit the source repo instead."
                }, 409
            flash("Git-based skills are read-only in Studio. Edit the source repo instead.", "info")
            return redirect(url_for("agents.view_skill", skill_id=skill_id))
        latest_version = _latest_skill_version(skill)
        latest_non_skill_files = []
        if latest_version is not None:
            for entry in sorted(list(latest_version.files or []), key=lambda item: item.path):
                if entry.path == "SKILL.md":
                    continue
                latest_non_skill_files.append(
                    {
                        "path": entry.path,
                        "size_bytes": entry.size_bytes,
                        "is_binary": is_binary_skill_content(entry.content or ""),
                    }
                )
        response_payload = {
            "skill": _serialize_skill(skill),
            "latest_version": (
                {
                    "id": latest_version.id,
                    "version": latest_version.version,
                    "manifest_hash": latest_version.manifest_hash or "",
                    "created_at": _human_time(latest_version.created_at),
                    "updated_at": _human_time(latest_version.updated_at),
                }
                if latest_version is not None
                else None
            ),
            "latest_skill_md": _skill_file_content(latest_version, "SKILL.md"),
            "latest_non_skill_files": latest_non_skill_files,
            "skill_status_options": _serialize_choice_options(SKILL_STATUS_OPTIONS),
            "upload_conflict_options": ["ask", "replace", "keep_both", "skip"],
            "max_upload_bytes": SKILL_UPLOAD_MAX_FILE_BYTES,
        }
    if _workflow_wants_json():
        return response_payload or {}
    return render_template(
        "skill_edit.html",
        skill=skill,
        latest_version=latest_version,
        latest_skill_md=_skill_file_content(latest_version, "SKILL.md"),
        latest_non_skill_files=latest_non_skill_files,
        skill_status_options=SKILL_STATUS_OPTIONS,
        upload_conflict_options=["ask", "replace", "keep_both", "skip"],
        max_upload_bytes=SKILL_UPLOAD_MAX_FILE_BYTES,
        page_title=f"Edit Skill - {skill.display_name}",
        active_page="skills",
    )

@bp.post("/skills/<int:skill_id>")
def update_skill(skill_id: int):
    is_api_request = _workflow_api_request()
    if is_api_request:
        payload = request.get_json(silent=True) if request.is_json else {}
        if payload is None or not isinstance(payload, dict):
            payload = {}
        display_name = str(payload.get("display_name", "")).strip()
        description = str(payload.get("description", "")).strip()
        status = str(payload.get("status", "")).strip().lower()
        new_version = str(payload.get("new_version", "")).strip()
        new_skill_md = str(payload.get("new_skill_md", ""))
        existing_files_raw = payload.get("existing_files_json", payload.get("existing_files", ""))
        extra_files_raw = payload.get("extra_files_json", payload.get("extra_files", ""))
        source_ref = str(payload.get("source_ref", "")).strip()

        existing_files_json = (
            json.dumps(existing_files_raw)
            if isinstance(existing_files_raw, list)
            else str(existing_files_raw or "")
        )
        extra_files_json = (
            json.dumps(extra_files_raw)
            if isinstance(extra_files_raw, list)
            else str(extra_files_raw or "")
        )

        if status not in SKILL_STATUS_CHOICES:
            return {"error": "Select a valid skill status."}, 400
        extra_files, parse_error = _parse_skill_extra_files(extra_files_json)
        if parse_error:
            return {"error": parse_error}, 400
        upload_entries: list[dict[str, object]] = []

        try:
            with session_scope() as session:
                skill = (
                    session.execute(
                        select(Skill)
                        .options(selectinload(Skill.versions).selectinload(SkillVersion.files))
                        .where(Skill.id == skill_id)
                    )
                    .scalars()
                    .first()
                )
                if skill is None:
                    abort(404)
                if _is_git_based_skill(skill):
                    return {
                        "error": "Git-based skills are read-only in Studio. Edit the source repo instead."
                    }, 409
                if not display_name:
                    return {"error": "Display name is required."}, 400
                if not description:
                    return {"error": "Description is required."}, 400

                latest_version = _latest_skill_version(skill)
                latest_skill_md = _skill_file_content(latest_version, "SKILL.md")
                latest_non_skill_map: dict[str, str] = {}
                if latest_version is not None:
                    latest_non_skill_map = {
                        str(entry.path): str(entry.content or "")
                        for entry in sorted(list(latest_version.files or []), key=lambda item: item.path)
                        if str(entry.path) != "SKILL.md"
                    }
                existing_actions, existing_error = _parse_skill_existing_files_draft(
                    existing_files_json,
                    existing_paths=set(latest_non_skill_map.keys()),
                )
                if existing_error:
                    return {"error": existing_error}, 400

                draft_non_skill_map: dict[str, str] = {}
                occupied_paths: set[str] = set()
                existing_changed = False
                for action in existing_actions:
                    original_path = str(action["original_path"])
                    delete_flag = bool(action["delete"])
                    if delete_flag:
                        existing_changed = True
                        continue
                    target_path = str(action["path"])
                    if target_path in occupied_paths:
                        return {"error": f"Duplicate target path in existing file draft: {target_path}"}, 400
                    if target_path != original_path:
                        existing_changed = True
                        rename_path_error = _skill_upload_path_error(target_path)
                        if rename_path_error:
                            return {"error": rename_path_error}, 400
                    occupied_paths.add(target_path)
                    draft_non_skill_map[target_path] = latest_non_skill_map[original_path]

                legacy_extra_changed = False
                for raw_path, content in extra_files:
                    normalized_path = _normalize_skill_relative_path(raw_path)
                    if not normalized_path:
                        return {"error": "Extra file paths must be relative and path-safe."}, 400
                    path_error = _skill_upload_path_error(normalized_path)
                    if path_error:
                        return {"error": path_error}, 400
                    if normalized_path in draft_non_skill_map:
                        return {"error": f"Duplicate file path: {normalized_path}"}, 400
                    legacy_extra_changed = True
                    draft_non_skill_map[normalized_path] = content

                pre_upload_map = dict(draft_non_skill_map)
                draft_non_skill_map, conflict_error = _apply_skill_upload_conflicts(
                    draft_non_skill_map,
                    upload_entries,
                )
                if conflict_error:
                    return {"error": conflict_error}, 400
                upload_changed = draft_non_skill_map != pre_upload_map

                staged_skill_md = new_skill_md
                if new_version:
                    if not staged_skill_md.strip():
                        staged_skill_md = (
                            latest_skill_md
                            or _default_skill_markdown(
                                name=skill.name,
                                display_name=display_name,
                                description=description,
                                version=new_version,
                                status=status,
                            )
                        )
                    skill.display_name = display_name
                    skill.description = description
                    skill.status = status
                    skill.updated_by = None
                    files = [("SKILL.md", staged_skill_md), *list(draft_non_skill_map.items())]
                    package = build_skill_package(
                        files,
                        metadata_overrides={
                            "name": skill.name,
                            "display_name": display_name,
                            "description": description,
                            "version": new_version,
                            "status": status,
                        },
                    )
                    import_skill_package_to_db(
                        session,
                        package,
                        source_type=(
                            skill.source_type
                            if (skill.source_type or "").strip().lower() in SKILL_MUTABLE_SOURCE_TYPES
                            else "ui"
                        ),
                        source_ref=source_ref or skill.source_ref or f"web:skill:{skill_id}",
                        actor=None,
                    )
                else:
                    staged_skill_md = staged_skill_md or latest_skill_md
                    changed_non_skill_paths = set(draft_non_skill_map.keys()) != set(latest_non_skill_map.keys())
                    changed_non_skill_content = any(
                        draft_non_skill_map.get(path) != latest_non_skill_map.get(path)
                        for path in set(draft_non_skill_map.keys()) | set(latest_non_skill_map.keys())
                    )
                    has_file_changes = (
                        existing_changed
                        or changed_non_skill_paths
                        or changed_non_skill_content
                        or upload_changed
                        or legacy_extra_changed
                        or (staged_skill_md != latest_skill_md)
                    )
                    if has_file_changes:
                        return {
                            "error": "New version is required to publish SKILL.md or file changes."
                        }, 400
                    skill.display_name = display_name
                    skill.description = description
                    skill.status = status
                    skill.updated_by = None
                updated_payload = _serialize_skill(skill)
        except SkillPackageValidationError as exc:
            errors = format_validation_errors(exc.errors)
            message = str(errors[0].get("message") or "Skill package validation failed.")
            return {"error": message, "validation_errors": errors}, 400
        except ValueError as exc:
            return {"error": str(exc)}, 400
        return {"ok": True, "skill": updated_payload}

    display_name = request.form.get("display_name", "").strip()
    description = request.form.get("description", "").strip()
    status = request.form.get("status", "").strip().lower()
    new_version = request.form.get("new_version", "").strip()
    new_skill_md = request.form.get("new_skill_md", "")
    existing_files_json = request.form.get("existing_files_json", "")
    extra_files_json = request.form.get("extra_files_json", "")
    source_ref = request.form.get("source_ref", "").strip()

    if status not in SKILL_STATUS_CHOICES:
        flash("Select a valid skill status.", "error")
        return redirect(url_for("agents.edit_skill", skill_id=skill_id))

    extra_files, parse_error = _parse_skill_extra_files(extra_files_json)
    if parse_error:
        flash(parse_error, "error")
        return redirect(url_for("agents.edit_skill", skill_id=skill_id))
    upload_entries, upload_error = _collect_skill_upload_entries()
    if upload_error:
        flash(upload_error, "error")
        return redirect(url_for("agents.edit_skill", skill_id=skill_id))

    try:
        with session_scope() as session:
            skill = (
                session.execute(
                    select(Skill)
                    .options(selectinload(Skill.versions).selectinload(SkillVersion.files))
                    .where(Skill.id == skill_id)
                )
                .scalars()
                .first()
            )
            if skill is None:
                abort(404)
            if _is_git_based_skill(skill):
                flash("Git-based skills are read-only in Studio. Edit the source repo instead.", "error")
                return redirect(url_for("agents.view_skill", skill_id=skill_id))

            if not display_name:
                flash("Display name is required.", "error")
                return redirect(url_for("agents.edit_skill", skill_id=skill_id))
            if not description:
                flash("Description is required.", "error")
                return redirect(url_for("agents.edit_skill", skill_id=skill_id))

            latest_version = _latest_skill_version(skill)
            latest_skill_md = _skill_file_content(latest_version, "SKILL.md")
            latest_non_skill_map: dict[str, str] = {}
            if latest_version is not None:
                latest_non_skill_map = {
                    str(entry.path): str(entry.content or "")
                    for entry in sorted(list(latest_version.files or []), key=lambda item: item.path)
                    if str(entry.path) != "SKILL.md"
                }
            existing_actions, existing_error = _parse_skill_existing_files_draft(
                existing_files_json,
                existing_paths=set(latest_non_skill_map.keys()),
            )
            if existing_error:
                flash(existing_error, "error")
                return redirect(url_for("agents.edit_skill", skill_id=skill_id))

            draft_non_skill_map: dict[str, str] = {}
            occupied_paths: set[str] = set()
            existing_changed = False
            for action in existing_actions:
                original_path = str(action["original_path"])
                delete_flag = bool(action["delete"])
                if delete_flag:
                    existing_changed = True
                    continue
                target_path = str(action["path"])
                if target_path in occupied_paths:
                    flash(f"Duplicate target path in existing file draft: {target_path}", "error")
                    return redirect(url_for("agents.edit_skill", skill_id=skill_id))
                if target_path != original_path:
                    existing_changed = True
                    rename_path_error = _skill_upload_path_error(target_path)
                    if rename_path_error:
                        flash(rename_path_error, "error")
                        return redirect(url_for("agents.edit_skill", skill_id=skill_id))
                occupied_paths.add(target_path)
                draft_non_skill_map[target_path] = latest_non_skill_map[original_path]

            legacy_extra_changed = False
            for raw_path, content in extra_files:
                normalized_path = _normalize_skill_relative_path(raw_path)
                if not normalized_path:
                    flash("Extra file paths must be relative and path-safe.", "error")
                    return redirect(url_for("agents.edit_skill", skill_id=skill_id))
                path_error = _skill_upload_path_error(normalized_path)
                if path_error:
                    flash(path_error, "error")
                    return redirect(url_for("agents.edit_skill", skill_id=skill_id))
                if normalized_path in draft_non_skill_map:
                    flash(f"Duplicate file path: {normalized_path}", "error")
                    return redirect(url_for("agents.edit_skill", skill_id=skill_id))
                legacy_extra_changed = True
                draft_non_skill_map[normalized_path] = content

            pre_upload_map = dict(draft_non_skill_map)
            draft_non_skill_map, conflict_error = _apply_skill_upload_conflicts(
                draft_non_skill_map,
                upload_entries,
            )
            if conflict_error:
                flash(conflict_error, "error")
                return redirect(url_for("agents.edit_skill", skill_id=skill_id))
            upload_changed = draft_non_skill_map != pre_upload_map

            staged_skill_md = new_skill_md
            if new_version:
                if not staged_skill_md.strip():
                    staged_skill_md = (
                        latest_skill_md
                        or _default_skill_markdown(
                            name=skill.name,
                            display_name=display_name,
                            description=description,
                            version=new_version,
                            status=status,
                        )
                    )
                skill.display_name = display_name
                skill.description = description
                skill.status = status
                skill.updated_by = None
                files = [("SKILL.md", staged_skill_md), *list(draft_non_skill_map.items())]
                package = build_skill_package(
                    files,
                    metadata_overrides={
                        "name": skill.name,
                        "display_name": display_name,
                        "description": description,
                        "version": new_version,
                        "status": status,
                    },
                )
                import_skill_package_to_db(
                    session,
                    package,
                    source_type=(
                        skill.source_type
                        if (skill.source_type or "").strip().lower() in SKILL_MUTABLE_SOURCE_TYPES
                        else "ui"
                    ),
                    source_ref=source_ref or skill.source_ref or f"web:skill:{skill_id}",
                    actor=None,
                )
            else:
                staged_skill_md = staged_skill_md or latest_skill_md
                changed_non_skill_paths = set(draft_non_skill_map.keys()) != set(latest_non_skill_map.keys())
                changed_non_skill_content = any(
                    draft_non_skill_map.get(path) != latest_non_skill_map.get(path)
                    for path in set(draft_non_skill_map.keys()) | set(latest_non_skill_map.keys())
                )
                has_file_changes = (
                    existing_changed
                    or changed_non_skill_paths
                    or changed_non_skill_content
                    or upload_changed
                    or legacy_extra_changed
                    or (staged_skill_md != latest_skill_md)
                )
                if has_file_changes:
                    flash(
                        "New version is required to publish SKILL.md or file changes.",
                        "error",
                    )
                    return redirect(url_for("agents.edit_skill", skill_id=skill_id))
                skill.display_name = display_name
                skill.description = description
                skill.status = status
                skill.updated_by = None
    except SkillPackageValidationError as exc:
        errors = format_validation_errors(exc.errors)
        message = str(errors[0].get("message") or "Skill package validation failed.")
        flash(message, "error")
        return redirect(url_for("agents.edit_skill", skill_id=skill_id))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("agents.edit_skill", skill_id=skill_id))

    flash("Skill updated.", "success")
    return redirect(url_for("agents.view_skill", skill_id=skill_id))

@bp.get("/skills/<int:skill_id>/export")
def export_skill(skill_id: int):
    requested_version = request.args.get("version", "").strip() or None
    with session_scope() as session:
        try:
            package = export_skill_package_from_db(
                session,
                skill_id=skill_id,
                version=requested_version,
            )
        except ValueError:
            abort(404)
    payload = serialize_skill_bundle(package, pretty=True).encode("utf-8")
    file_name = f"{package.metadata.name}-{package.metadata.version}.skill.json"
    return send_file(
        BytesIO(payload),
        mimetype="application/json",
        as_attachment=True,
        download_name=file_name,
    )

@bp.post("/skills/<int:skill_id>/delete")
def delete_skill(skill_id: int):
    is_api_request = _workflow_api_request()
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_skills")
    )
    with session_scope() as session:
        skill = (
            session.execute(
                select(Skill)
                .options(
                    selectinload(Skill.flowchart_nodes),
                    selectinload(Skill.agents),
                )
                .where(Skill.id == skill_id)
            )
            .scalars()
            .first()
        )
        if skill is None:
            abort(404)
        if _is_git_based_skill(skill):
            if is_api_request:
                return {
                    "error": "Git-based skills are read-only in Studio and cannot be deleted here."
                }, 409
            flash("Git-based skills are read-only in Studio and cannot be deleted here.", "error")
            return redirect(url_for("agents.view_skill", skill_id=skill_id))
        attached_nodes = list(skill.flowchart_nodes or [])
        attached_agents = list(skill.agents or [])
        if attached_nodes:
            skill.flowchart_nodes = []
        if attached_agents:
            skill.agents = []
        session.delete(skill)

    if is_api_request:
        return {
            "ok": True,
            "detached_node_count": len(attached_nodes),
            "detached_agent_count": len(attached_agents),
        }
    flash("Skill deleted.", "success")
    if attached_nodes:
        flash(f"Detached from {len(attached_nodes)} flowchart node binding(s).", "info")
    if attached_agents:
        flash(f"Detached from {len(attached_agents)} agent binding(s).", "info")
    return redirect(next_url)

@bp.get("/memories")
def list_memories():
    page = _parse_page(request.args.get("page"))
    per_page = WORKFLOW_LIST_PER_PAGE
    with session_scope() as session:
        memory_node_filters = (
            FlowchartNode.node_type == FLOWCHART_NODE_TYPE_MEMORY,
            FlowchartNode.ref_id.is_not(None),
        )
        total_count = (
            session.execute(
                select(func.count(FlowchartNode.id))
                .select_from(FlowchartNode)
                .join(Memory, Memory.id == FlowchartNode.ref_id)
                .where(*memory_node_filters)
            )
            .scalar_one()
        )
        pagination = _build_pagination(request.path, page, per_page, total_count)
        offset = (pagination["page"] - 1) * per_page
        rows = session.execute(
            select(FlowchartNode, Flowchart.name, Memory)
            .join(Flowchart, Flowchart.id == FlowchartNode.flowchart_id)
            .join(Memory, Memory.id == FlowchartNode.ref_id)
            .where(*memory_node_filters)
            .order_by(
                FlowchartNode.updated_at.desc(),
                FlowchartNode.id.desc(),
            )
            .limit(per_page)
            .offset(offset)
        ).all()
        memories = [
            _serialize_memory_node_row(memory, flowchart_node, flowchart_name=flowchart_name)
            for flowchart_node, flowchart_name, memory in rows
        ]
    if _workflow_wants_json():
        return {
            "memories": memories,
            "pagination": _serialize_workflow_pagination(pagination),
        }
    return render_template(
        "memories.html",
        memories=memories,
        pagination=pagination,
        human_time=_human_time,
        fixed_list_page=True,
        page_title="Memories",
        active_page="memories",
    )

@bp.get("/memories/new")
def new_memory():
    if _workflow_wants_json():
        return {
            "message": "Create memories by adding Memory nodes in a flowchart.",
            "flowcharts_url": url_for("agents.list_flowcharts"),
        }
    flash("Create memories by adding Memory nodes in a flowchart.", "error")
    return redirect(url_for("agents.list_flowcharts"))

@bp.post("/memories")
def create_memory():
    if _workflow_api_request():
        return {
            "error": "Create memories by adding Memory nodes in a flowchart.",
            "reason_code": "FLOWCHART_MANAGED_MEMORY_CREATE",
        }, 409
    flash("Create memories by adding Memory nodes in a flowchart.", "error")
    return redirect(url_for("agents.list_flowcharts"))

@bp.get("/memories/<int:memory_id>")
def view_memory(memory_id: int):
    with session_scope() as session:
        memory = session.get(Memory, memory_id)
        if memory is None:
            abort(404)
    if _workflow_wants_json():
        return {"memory": _serialize_memory(memory)}
    return render_template(
        "memory_detail.html",
        memory=memory,
        human_time=_human_time,
        page_title="Memory",
        active_page="memories",
    )

@bp.get("/memories/<int:memory_id>/history")
def view_memory_history(memory_id: int):
    page = _parse_page(request.args.get("page"))
    per_page = WORKFLOW_LIST_PER_PAGE
    flowchart_node_id = _parse_positive_int(request.args.get("flowchart_node_id"), 0)
    if flowchart_node_id < 1:
        flowchart_node_id = None
    request_id = f"memory-history-{memory_id}-{uuid.uuid4().hex}"
    correlation_id = f"memory-{memory_id}"
    with session_scope() as session:
        memory = session.get(Memory, memory_id)
        if memory is None:
            abort(404)
        artifact_filters = [
            NodeArtifact.artifact_type == NODE_ARTIFACT_TYPE_MEMORY,
            NodeArtifact.ref_id == memory_id,
        ]
        if flowchart_node_id is not None:
            artifact_filters.append(NodeArtifact.flowchart_node_id == flowchart_node_id)
        artifact_count = (
            session.execute(
                select(func.count(NodeArtifact.id)).where(*artifact_filters)
            )
            .scalar_one()
        )
        pagination = _build_pagination(request.path, page, per_page, artifact_count)
        offset = (pagination["page"] - 1) * per_page
        artifacts = (
            session.execute(
                select(NodeArtifact)
                .where(*artifact_filters)
                .order_by(NodeArtifact.created_at.desc(), NodeArtifact.id.desc())
                .limit(per_page)
                .offset(offset)
            )
            .scalars()
            .all()
        )
    return {
        "memory": _serialize_memory(memory),
        "flowchart_node_id": flowchart_node_id,
        "artifacts": [_serialize_node_artifact(item) for item in artifacts],
        "pagination": _serialize_workflow_pagination(pagination),
        "request_id": request_id,
        "correlation_id": correlation_id,
    }

@bp.get("/memories/<int:memory_id>/edit")
def edit_memory(memory_id: int):
    with session_scope() as session:
        memory = session.get(Memory, memory_id)
        if memory is None:
            abort(404)
    if _workflow_wants_json():
        return {"memory": _serialize_memory(memory)}
    return render_template(
        "memory_edit.html",
        memory=memory,
        page_title="Edit Memory",
        active_page="memories",
    )

@bp.post("/memories/<int:memory_id>")
def update_memory(memory_id: int):
    is_api_request = _workflow_api_request()
    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None or not isinstance(payload, dict):
        payload = {}
    description_raw = (
        payload.get("description")
        if is_api_request
        else request.form.get("description", "")
    )
    description = str(description_raw or "").strip()
    if not description:
        if is_api_request:
            return {"error": "Description is required."}, 400
        flash("Description is required.", "error")
        return redirect(url_for("agents.edit_memory", memory_id=memory_id))

    memory_payload: dict[str, object] | None = None
    with session_scope() as session:
        memory = session.get(Memory, memory_id)
        if memory is None:
            abort(404)
        memory.description = description
        memory_payload = _serialize_memory(memory)

    if is_api_request:
        return {"ok": True, "memory": memory_payload}
    flash("Memory updated.", "success")
    return redirect(url_for("agents.view_memory", memory_id=memory_id))

@bp.post("/memories/<int:memory_id>/delete")
def delete_memory(memory_id: int):
    is_api_request = _workflow_api_request()
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_memories")
    )
    with session_scope() as session:
        memory = session.get(Memory, memory_id)
        if memory is None:
            abort(404)
        session.delete(memory)

    if is_api_request:
        return {"ok": True}
    flash("Memory deleted.", "success")
    return redirect(next_url)

@bp.get("/scripts/new")
def new_script():
    if _workflow_wants_json():
        return {
            "script_types": _serialize_choice_options(SCRIPT_TYPE_WRITE_CHOICES),
            "script": {
                "file_name": "",
                "description": "",
                "script_type": SCRIPT_TYPE_WRITE_CHOICES[0][0]
                if SCRIPT_TYPE_WRITE_CHOICES
                else "",
                "content": "",
            },
        }
    return render_template(
        "script_new.html",
        script_types=SCRIPT_TYPE_WRITE_CHOICES,
        page_title="Create Script",
        active_page="scripts",
    )

@bp.post("/scripts")
def create_script():
    is_api_request = _workflow_api_request()
    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None or not isinstance(payload, dict):
        payload = {}
    file_name = str(
        payload.get("file_name")
        if is_api_request
        else request.form.get("file_name", "")
    ).strip()
    description = str(
        payload.get("description")
        if is_api_request
        else request.form.get("description", "")
    ).strip()
    script_type = str(
        payload.get("script_type")
        if is_api_request
        else request.form.get("script_type", "")
    ).strip()
    content = str(
        payload.get("content")
        if is_api_request
        else request.form.get("content", "")
    )
    uploaded_file = request.files.get("script_file")

    if not is_api_request and uploaded_file and uploaded_file.filename:
        file_name = file_name or uploaded_file.filename
        content_bytes = uploaded_file.read()
        content = content_bytes.decode("utf-8", errors="replace")

    file_name = Path(file_name).name if file_name else ""
    if not file_name or file_name in {".", ".."}:
        if is_api_request:
            return {"error": "File name is required."}, 400
        flash("File name is required.", "error")
        return redirect(url_for("agents.new_script"))
    if script_type not in SCRIPT_TYPE_LABELS:
        if is_api_request:
            return {"error": "Select a valid script type."}, 400
        flash("Select a valid script type.", "error")
        return redirect(url_for("agents.new_script"))
    try:
        ensure_legacy_skill_script_writable(script_type)
    except ValueError as exc:
        if is_api_request:
            return {"error": str(exc)}, 400
        flash(str(exc), "error")
        return redirect(url_for("agents.new_script"))
    if not content or not content.strip():
        if is_api_request:
            return {"error": "Script content is required."}, 400
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
        if is_api_request:
            return {"error": "Failed to write the script file."}, 500
        flash("Failed to write the script file.", "error")
        return redirect(url_for("agents.new_script"))

    if is_api_request:
        return {"ok": True, "script": _serialize_script(script, include_content=True)}, 201
    flash(f"Script {script.id} created.", "success")
    return redirect(url_for("agents.view_script", script_id=script.id))

@bp.get("/scripts/<int:script_id>")
def view_script(script_id: int):
    script_payload: dict[str, object] | None = None
    task_payload: list[dict[str, object]] = []
    node_payload: list[dict[str, object]] = []
    flowcharts_by_id: dict[int, str] = {}
    with session_scope() as session:
        script = (
            session.execute(
                select(Script)
                .options(
                    selectinload(Script.tasks),
                    selectinload(Script.flowchart_nodes),
                )
                .where(Script.id == script_id)
            )
            .scalars()
            .first()
        )
        if script is None:
            abort(404)
        attached_tasks = list(script.tasks)
        attached_nodes = list(script.flowchart_nodes)
        flowchart_ids = {
            node.flowchart_id for node in attached_nodes if node.flowchart_id is not None
        }
        if flowchart_ids:
            rows = session.execute(
                select(Flowchart.id, Flowchart.name).where(Flowchart.id.in_(flowchart_ids))
            ).all()
            flowcharts_by_id = {row[0]: row[1] for row in rows}
        script_content = _read_script_content(script)
        script_payload = _serialize_script(script, include_content=True)
        task_payload = [
            {
                "id": task.id,
                "agent_id": task.agent_id,
                "run_id": task.run_id,
                "status": task.status,
                "prompt": task.prompt,
                "created_at": _human_time(task.created_at),
                "updated_at": _human_time(task.updated_at),
            }
            for task in attached_tasks
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
            for node in attached_nodes
        ]
    if _workflow_wants_json():
        return {
            "script": script_payload,
            "attached_tasks": task_payload,
            "attached_nodes": node_payload,
            "flowcharts_by_id": flowcharts_by_id,
        }
    return render_template(
        "script_detail.html",
        script=script,
        script_content=script_content,
        attached_tasks=attached_tasks,
        attached_nodes=attached_nodes,
        flowcharts_by_id=flowcharts_by_id,
        human_time=_human_time,
        page_title=f"Script - {script.file_name}",
        active_page="scripts",
    )

@bp.get("/scripts/<int:script_id>/edit")
def edit_script(script_id: int):
    script_payload: dict[str, object] | None = None
    with session_scope() as session:
        script = session.get(Script, script_id)
        if script is None:
            abort(404)
        script_content = _read_script_content(script)
        script_payload = _serialize_script(script, include_content=True)
    if _workflow_wants_json():
        return {
            "script": script_payload,
            "script_types": _serialize_choice_options(SCRIPT_TYPE_WRITE_CHOICES),
        }
    return render_template(
        "script_edit.html",
        script=script,
        script_content=script_content,
        script_types=SCRIPT_TYPE_WRITE_CHOICES,
        page_title=f"Edit Script - {script.file_name}",
        active_page="scripts",
    )

@bp.post("/scripts/<int:script_id>")
def update_script(script_id: int):
    is_api_request = _workflow_api_request()
    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None or not isinstance(payload, dict):
        payload = {}
    file_name = str(
        payload.get("file_name")
        if is_api_request
        else request.form.get("file_name", "")
    ).strip()
    description = str(
        payload.get("description")
        if is_api_request
        else request.form.get("description", "")
    ).strip()
    script_type = str(
        payload.get("script_type")
        if is_api_request
        else request.form.get("script_type", "")
    ).strip()
    content = str(
        payload.get("content")
        if is_api_request
        else request.form.get("content", "")
    )
    uploaded_file = request.files.get("script_file")

    if not is_api_request and uploaded_file and uploaded_file.filename:
        file_name = file_name or uploaded_file.filename
        content_bytes = uploaded_file.read()
        content = content_bytes.decode("utf-8", errors="replace")

    updated_payload: dict[str, object] | None = None
    try:
        with session_scope() as session:
            script = session.get(Script, script_id)
            if script is None:
                abort(404)
            if not file_name:
                file_name = script.file_name
            file_name = Path(file_name).name if file_name else ""
            if not file_name or file_name in {".", ".."}:
                if is_api_request:
                    return {"error": "File name is required."}, 400
                flash("File name is required.", "error")
                return redirect(url_for("agents.edit_script", script_id=script_id))
            if script_type not in SCRIPT_TYPE_LABELS:
                if is_api_request:
                    return {"error": "Select a valid script type."}, 400
                flash("Select a valid script type.", "error")
                return redirect(url_for("agents.edit_script", script_id=script_id))
            try:
                ensure_legacy_skill_script_writable(script_type)
            except ValueError as exc:
                if is_api_request:
                    return {"error": str(exc)}, 400
                flash(str(exc), "error")
                return redirect(url_for("agents.edit_script", script_id=script_id))
            if not content or not content.strip():
                if is_api_request:
                    return {"error": "Script content is required."}, 400
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
            updated_payload = _serialize_script(script, include_content=True)
    except OSError:
        logger.exception("Failed to write script %s to disk", script_id)
        if is_api_request:
            return {"error": "Failed to write the script file."}, 500
        flash("Failed to write the script file.", "error")
        return redirect(url_for("agents.edit_script", script_id=script_id))

    if is_api_request:
        return {"ok": True, "script": updated_payload}
    flash("Script updated.", "success")
    return redirect(url_for("agents.view_script", script_id=script_id))

@bp.post("/scripts/<int:script_id>/delete")
def delete_script(script_id: int):
    is_api_request = _workflow_api_request()
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_scripts")
    )
    with session_scope() as session:
        script = session.get(Script, script_id)
        if script is None:
            abort(404)
        script_path = script.file_path
        attached_tasks = list(script.tasks)
        attached_nodes = list(script.flowchart_nodes)
        if attached_tasks:
            script.tasks = []
        if attached_nodes:
            script.flowchart_nodes = []
        session.delete(script)

    detached_count = len(attached_tasks) + len(attached_nodes)
    if is_api_request:
        remove_script_file(script_path)
        return {"ok": True, "detached_count": detached_count}
    flash("Script deleted.", "success")
    if detached_count:
        flash(f"Detached from {detached_count} binding(s).", "info")
    remove_script_file(script_path)
    return redirect(next_url)
