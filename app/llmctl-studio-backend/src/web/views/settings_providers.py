from .shared import *  # noqa: F401,F403

__all__ = ['create_role', 'settings', 'list_roles', 'new_role', 'view_role', 'edit_role', 'update_role', 'delete_role', 'settings_core', 'settings_provider', 'list_providers', 'view_provider', 'settings_provider_codex', 'settings_provider_gemini', 'settings_provider_claude', 'settings_provider_vllm_local', 'settings_provider_vllm_remote', 'update_provider_settings', 'update_codex_settings', 'update_gemini_settings', 'update_claude_settings', 'update_vllm_local_settings', 'start_vllm_local_qwen_download', 'start_vllm_local_huggingface_download', 'vllm_local_huggingface_download_status', 'toggle_vllm_local_qwen_model', 'download_vllm_local_huggingface_model', 'delete_vllm_local_huggingface_model', 'update_vllm_remote_settings', 'settings_celery', 'settings_runtime', 'settings_runtime_rag', 'settings_runtime_chat', 'settings_chat', 'update_chat_default_settings_route', 'update_chat_runtime_settings_route', 'update_instruction_runtime_settings_route', 'update_node_executor_runtime_settings_route', 'node_executor_runtime_effective_config_route', 'settings_gitconfig', 'update_gitconfig', 'update_rag_settings']

@bp.post("/roles")
def create_role():
    is_api_request = _agent_api_request()
    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None or not isinstance(payload, dict):
        payload = {}
    name = str(
        payload.get("name") if is_api_request else request.form.get("name", "")
    ).strip()
    description = str(
        payload.get("description")
        if is_api_request
        else request.form.get("description", "")
    ).strip()
    raw_details = str(
        payload.get("details_json")
        if is_api_request
        else request.form.get("details_json", "")
    ).strip()
    details_payload = payload.get("details") if is_api_request else None

    if not description:
        if is_api_request:
            return {"error": "Role description is required."}, 400
        flash("Role description is required.", "error")
        return redirect(url_for("agents.new_role"))

    try:
        if details_payload is not None:
            if not isinstance(details_payload, dict):
                raise ValueError("Role details must be a JSON object.")
            formatted_details = json.dumps(details_payload, indent=2, sort_keys=True)
        else:
            formatted_details = _parse_role_details(raw_details)
    except json.JSONDecodeError as exc:
        if is_api_request:
            return {"error": f"Invalid JSON: {exc.msg}"}, 400
        flash(f"Invalid JSON: {exc.msg}", "error")
        return redirect(url_for("agents.new_role"))
    except ValueError as exc:
        if is_api_request:
            return {"error": str(exc)}, 400
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

    if is_api_request:
        return {"role": _serialize_role_detail(role)}, 201
    flash("Role created.", "success")
    return redirect(url_for("agents.view_role", role_id=role.id))

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
        "DATABASE_FILENAME": _database_filename_setting(),
        "CODEX_MODEL": Config.CODEX_MODEL or "default",
        "VLLM_LOCAL_CMD": Config.VLLM_LOCAL_CMD,
        "VLLM_LOCAL_CUSTOM_MODELS_DIR": Config.VLLM_LOCAL_CUSTOM_MODELS_DIR,
        "VLLM_REMOTE_BASE_URL": Config.VLLM_REMOTE_BASE_URL or "not set",
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
        active_page="settings_overview",
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
        role_ids = [role.id for role in roles]
        binding_count_by_role_id: dict[int, int] = {}
        if role_ids:
            binding_rows = session.execute(
                select(Agent.role_id, func.count(Agent.id))
                .where(Agent.role_id.in_(role_ids))
                .group_by(Agent.role_id)
            ).all()
            binding_count_by_role_id = {
                int(role_id): int(count)
                for role_id, count in binding_rows
                if role_id is not None
            }
    if _agents_wants_json():
        return {
            "roles": [
                _serialize_role_list_item(
                    role,
                    binding_count=binding_count_by_role_id.get(role.id, 0),
                )
                for role in roles
            ],
            "pagination": pagination,
            "total_count": total_count,
        }
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
    if _agents_wants_json():
        return {
            "role": {
                "name": "",
                "description": "",
                "details": {},
                "details_json": "{}",
            }
        }
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
        assigned_agents = (
            session.execute(
                select(Agent)
                .where(Agent.role_id == role_id)
                .order_by(Agent.name.asc(), Agent.id.asc())
            )
            .scalars()
            .all()
        )
    if _agents_wants_json():
        return {
            "role": _serialize_role_detail(role, assigned_agents=assigned_agents),
        }
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
    if _agents_wants_json():
        return {
            "role": _serialize_role_detail(role),
        }
    return render_template(
        "role_edit.html",
        role=role,
        page_title=f"Edit Role - {role.name}",
        active_page="roles",
    )

@bp.post("/settings/roles/<int:role_id>")
@bp.post("/roles/<int:role_id>")
def update_role(role_id: int):
    is_api_request = _agent_api_request()
    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None or not isinstance(payload, dict):
        payload = {}
    name = str(
        payload.get("name") if is_api_request else request.form.get("name", "")
    ).strip()
    description = str(
        payload.get("description")
        if is_api_request
        else request.form.get("description", "")
    ).strip()
    raw_details = str(
        payload.get("details_json")
        if is_api_request
        else request.form.get("details_json", "")
    ).strip()
    details_payload = payload.get("details") if is_api_request else None

    if not description:
        if is_api_request:
            return {"error": "Role description is required."}, 400
        flash("Role description is required.", "error")
        return redirect(url_for("agents.edit_role", role_id=role_id))

    try:
        if details_payload is not None:
            if not isinstance(details_payload, dict):
                raise ValueError("Role details must be a JSON object.")
            formatted_details = json.dumps(details_payload, indent=2, sort_keys=True)
        else:
            formatted_details = _parse_role_details(raw_details)
    except json.JSONDecodeError as exc:
        if is_api_request:
            return {"error": f"Invalid JSON: {exc.msg}"}, 400
        flash(f"Invalid JSON: {exc.msg}", "error")
        return redirect(url_for("agents.edit_role", role_id=role_id))
    except ValueError as exc:
        if is_api_request:
            return {"error": str(exc)}, 400
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
        assigned_agents = (
            session.execute(
                select(Agent)
                .where(Agent.role_id == role_id)
                .order_by(Agent.name.asc(), Agent.id.asc())
            )
            .scalars()
            .all()
        )

    if is_api_request:
        return {
            "role": _serialize_role_detail(role, assigned_agents=assigned_agents),
        }
    flash("Role updated.", "success")
    return redirect(url_for("agents.view_role", role_id=role_id))

@bp.post("/settings/roles/<int:role_id>/delete")
@bp.post("/roles/<int:role_id>/delete")
def delete_role(role_id: int):
    is_api_request = _agent_api_request()
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

    if is_api_request:
        return {
            "ok": True,
            "deleted_role_id": role_id,
            "removed_from_agent_count": len(assigned_agents),
        }
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
        "DATABASE_FILENAME": _database_filename_setting(),
        "SQLALCHEMY_DATABASE_URI": Config.SQLALCHEMY_DATABASE_URI,
        "AGENT_POLL_SECONDS": Config.AGENT_POLL_SECONDS,
        "LLM_PROVIDER": resolve_llm_provider() or "not set",
        "CODEX_CMD": Config.CODEX_CMD,
        "CODEX_MODEL": Config.CODEX_MODEL or "default",
        "GEMINI_CMD": Config.GEMINI_CMD,
        "GEMINI_MODEL": Config.GEMINI_MODEL or "default",
        "CLAUDE_CMD": Config.CLAUDE_CMD,
        "CLAUDE_MODEL": Config.CLAUDE_MODEL or "default",
        "VLLM_LOCAL_CMD": Config.VLLM_LOCAL_CMD,
        "VLLM_REMOTE_BASE_URL": Config.VLLM_REMOTE_BASE_URL or "not set",
        "VLLM_LOCAL_CUSTOM_MODELS_DIR": Config.VLLM_LOCAL_CUSTOM_MODELS_DIR,
    }
    if _workflow_wants_json():
        return {
            "core_config": core_config,
            "summary": summary,
        }
    return render_template(
        "settings_core.html",
        core_config=core_config,
        summary=summary,
        page_title="Settings - Core",
        active_page="settings_core",
    )

@bp.get("/settings/provider")
@bp.get("/settings/provider/controls")
def settings_provider():
    return _render_settings_provider_page("controls")

@bp.get("/providers")
def list_providers():
    if not _workflow_wants_json():
        return redirect(url_for("agents.settings_provider"))
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    try:
        query = _parse_provider_list_query()
    except ValueError as exc:
        return _workflow_error_envelope(
            code="invalid_request",
            message=str(exc),
            details={},
            request_id=request_id,
            correlation_id=correlation_id,
        ), 400
    context = _settings_provider_context()
    provider_rows = [
        dict(row)
        for row in (context.get("provider_details") or [])
        if isinstance(row, dict)
    ]
    search_text = str(query["search_text"])
    if search_text:
        provider_rows = [
            row
            for row in provider_rows
            if search_text in str(row.get("id") or "").strip().lower()
            or search_text in str(row.get("label") or "").strip().lower()
            or search_text in str(row.get("model") or "").strip().lower()
        ]
    enabled_filter = str(query["enabled_filter"])
    if enabled_filter:
        enabled_flag = enabled_filter == "true"
        provider_rows = [
            row for row in provider_rows if bool(row.get("enabled")) == enabled_flag
        ]

    sort_by = str(query["sort_by"])
    reverse = str(query["sort_order"]) == "desc"

    def _sort_key(row: dict[str, object]) -> tuple[int, str]:
        value = row.get(sort_by)
        if isinstance(value, bool):
            return (0, "1" if value else "0")
        return (1, str(value or "").strip().lower())

    provider_rows = sorted(provider_rows, key=_sort_key, reverse=reverse)
    total_count = len(provider_rows)
    page = int(query["page"])
    per_page = int(query["per_page"])
    start = (page - 1) * per_page
    items = provider_rows[start : start + per_page]
    return _workflow_success_payload(
        payload={
            "providers": items,
            "count": len(items),
            "total_count": total_count,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "has_prev": page > 1,
                "has_next": page * per_page < total_count,
            },
            "filters": {
                "search": search_text,
                "enabled": enabled_filter,
            },
            "sort": {
                "by": sort_by,
                "order": str(query["sort_order"]),
            },
            "provider_summary": context.get("provider_summary") or {},
        },
        request_id=request_id,
        correlation_id=correlation_id,
    )

@bp.get("/providers/<provider_id>")
def view_provider(provider_id: str):
    if not _workflow_wants_json():
        return redirect(url_for("agents.settings_provider"))
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    normalized = _normalize_provider_id(provider_id)
    context = _settings_provider_context()
    details_index = _provider_details_index(context)
    if normalized not in details_index:
        return _workflow_error_envelope(
            code="not_found",
            message=f"Provider '{provider_id}' was not found.",
            details={"provider": provider_id},
            request_id=request_id,
            correlation_id=correlation_id,
        ), 404
    settings_by_provider = {
        "codex": context.get("codex_settings") or {},
        "gemini": context.get("gemini_settings") or {},
        "claude": context.get("claude_settings") or {},
        "vllm_local": context.get("vllm_local_settings") or {},
        "vllm_remote": context.get("vllm_remote_settings") or {},
    }
    return _workflow_success_payload(
        payload={
            "provider": details_index[normalized],
            "provider_settings": settings_by_provider.get(normalized, {}),
            "provider_summary": context.get("provider_summary") or {},
        },
        request_id=request_id,
        correlation_id=correlation_id,
    )

@bp.get("/settings/provider/codex")
def settings_provider_codex():
    return _render_settings_provider_page("codex")

@bp.get("/settings/provider/gemini")
def settings_provider_gemini():
    return _render_settings_provider_page("gemini")

@bp.get("/settings/provider/claude")
def settings_provider_claude():
    return _render_settings_provider_page("claude")

@bp.get("/settings/provider/vllm-local")
def settings_provider_vllm_local():
    return _render_settings_provider_page("vllm_local")

@bp.get("/settings/provider/vllm-remote")
def settings_provider_vllm_remote():
    return _render_settings_provider_page("vllm_remote")

@bp.post("/settings/provider")
def update_provider_settings():
    payload = _settings_request_payload()
    is_api_request = _workflow_api_request()
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    default_provider = (
        _settings_form_value(payload, "default_provider") or ""
    ).strip().lower()
    if default_provider and default_provider not in LLM_PROVIDERS:
        if is_api_request:
            return _workflow_error_envelope(
                code="invalid_request",
                message="Unknown provider selection.",
                details={"provider": default_provider},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 400
        flash("Unknown provider selection.", "error")
        return redirect(url_for("agents.settings_provider"))
    enabled: set[str] = set()
    for provider in LLM_PROVIDERS:
        if _as_bool(_settings_form_value(payload, f"provider_enabled_{provider}")):
            enabled.add(provider)
    if default_provider:
        enabled.add(default_provider)
    payload = {
        f"provider_enabled_{provider}": "true" if provider in enabled else ""
        for provider in LLM_PROVIDERS
    }
    payload["provider"] = default_provider if default_provider in enabled else ""
    _save_integration_settings("llm", payload)
    selected_provider = payload["provider"]
    if is_api_request:
        response_payload = {
            "provider": selected_provider,
            "enabled_providers": sorted(enabled),
        }
        _emit_model_provider_event(
            event_type="config:provider:updated",
            entity_kind="provider",
            entity_id=selected_provider or "controls",
            payload=response_payload,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        return _workflow_success_payload(
            payload=response_payload,
            request_id=request_id,
            correlation_id=correlation_id,
        )
    if not enabled:
        flash("No providers enabled. Agents require a default model or provider.", "info")
    flash("Provider settings updated.", "success")
    return redirect(url_for("agents.settings_provider"))

@bp.post("/settings/provider/codex")
def update_codex_settings():
    payload = _settings_request_payload()
    is_api_request = _workflow_api_request()
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    api_key = _settings_form_value(payload, "codex_api_key")
    payload = {
        "codex_api_key": api_key,
    }
    _save_integration_settings("llm", payload)
    if is_api_request:
        response_payload = {"provider": "codex"}
        _emit_model_provider_event(
            event_type="config:provider:updated",
            entity_kind="provider",
            entity_id="codex",
            payload=response_payload,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        return _workflow_success_payload(
            payload=response_payload,
            request_id=request_id,
            correlation_id=correlation_id,
        )
    flash("Codex auth settings updated.", "success")
    return redirect(url_for("agents.settings_provider_codex"))

@bp.post("/settings/provider/gemini")
def update_gemini_settings():
    payload = _settings_request_payload()
    is_api_request = _workflow_api_request()
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    api_key = _settings_form_value(payload, "gemini_api_key")
    use_vertex_ai = _as_bool(_settings_form_value(payload, "gemini_use_vertex_ai"))
    project = _settings_form_value(payload, "gemini_project").strip()
    location = _settings_form_value(payload, "gemini_location").strip()
    payload = {
        "gemini_api_key": api_key,
        "gemini_use_vertex_ai": "true" if use_vertex_ai else "",
        "gemini_project": project,
        "gemini_location": location,
    }
    _save_integration_settings("llm", payload)
    if is_api_request:
        response_payload = {
            "provider": "gemini",
            "provider_settings": _gemini_settings_payload(payload),
        }
        _emit_model_provider_event(
            event_type="config:provider:updated",
            entity_kind="provider",
            entity_id="gemini",
            payload=response_payload,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        return _workflow_success_payload(
            payload=response_payload,
            request_id=request_id,
            correlation_id=correlation_id,
        )
    flash("Gemini auth settings updated.", "success")
    return redirect(url_for("agents.settings_provider_gemini"))

@bp.post("/settings/provider/claude")
def update_claude_settings():
    payload = _settings_request_payload()
    is_api_request = _workflow_api_request()
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    api_key = _settings_form_value(payload, "claude_api_key")
    payload = {
        "claude_api_key": api_key,
    }
    _save_integration_settings("llm", payload)
    if is_api_request:
        response_payload = {"provider": "claude"}
        _emit_model_provider_event(
            event_type="config:provider:updated",
            entity_kind="provider",
            entity_id="claude",
            payload=response_payload,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        return _workflow_success_payload(
            payload=response_payload,
            request_id=request_id,
            correlation_id=correlation_id,
        )
    flash("Claude auth settings updated.", "success")
    return redirect(url_for("agents.settings_provider_claude"))

@bp.post("/settings/provider/vllm-local")
def update_vllm_local_settings():
    request_payload = _settings_request_payload()
    is_api_request = _workflow_api_request()
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    local_model = _settings_form_value(request_payload, "vllm_local_model")
    discovered_local_values = {item["value"] for item in discover_vllm_local_models()}
    local_model_clean = local_model.strip()
    if local_model_clean and local_model_clean not in discovered_local_values:
        if is_api_request:
            return _workflow_error_envelope(
                code="invalid_request",
                message="vLLM local model must be selected from discovered local models.",
                details={"provider": "vllm_local", "model": local_model_clean},
                request_id=request_id,
                correlation_id=correlation_id,
            ), 400
        flash("vLLM local model must be selected from discovered local models.", "error")
        return redirect(url_for("agents.settings_provider_vllm_local"))
    payload = {
        "vllm_local_model": local_model_clean,
        # Local provider runs in-container through CLI; clear deprecated HTTP fields.
        "vllm_local_base_url": "",
        "vllm_local_api_key": "",
    }
    if (
        "vllm_local_hf_token" in request.form
        or "vllm_local_hf_token" in request_payload
    ):
        payload["vllm_local_hf_token"] = _settings_form_value(
            request_payload, "vllm_local_hf_token"
        )
    _save_integration_settings("llm", payload)
    if is_api_request:
        response_payload = {"provider": "vllm_local"}
        _emit_model_provider_event(
            event_type="config:provider:updated",
            entity_kind="provider",
            entity_id="vllm_local",
            payload=response_payload,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        return _workflow_success_payload(
            payload=response_payload,
            request_id=request_id,
            correlation_id=correlation_id,
        )
    flash("vLLM Local settings updated.", "success")
    return redirect(url_for("agents.settings_provider_vllm_local"))

@bp.post("/settings/provider/vllm-local/qwen/start")
def start_vllm_local_qwen_download():
    llm_settings = _load_integration_settings("llm")
    huggingface_token = _vllm_local_huggingface_token(llm_settings)
    if _qwen_model_downloaded():
        return {
            "ok": False,
            "error": "Qwen model is already downloaded. Use remove to delete it first.",
        }, 409

    job, created = _start_huggingface_download_job(
        kind="qwen",
        model_id=_qwen_model_id(),
        model_dir_name=_qwen_model_dir_name(),
        token=huggingface_token,
        model_container_path=_qwen_model_container_path(),
    )
    return {
        "ok": True,
        "created": created,
        "message": "Qwen download started." if created else "Qwen download already in progress.",
        "download_job": job,
        "status_url": url_for(
            "agents.vllm_local_huggingface_download_status",
            job_id=str(job.get("id") or ""),
        ),
    }, 202

@bp.post("/settings/provider/vllm-local/huggingface/start")
def start_vllm_local_huggingface_download():
    llm_settings = _load_integration_settings("llm")
    huggingface_token = _vllm_local_huggingface_token(llm_settings)
    if not huggingface_token:
        return {
            "ok": False,
            "error": "Set and save a HuggingFace token before downloading arbitrary models.",
        }, 400

    model_id = _normalize_huggingface_repo_id(
        request.form.get("vllm_local_hf_model_id", "")
    )
    if not model_id:
        return {
            "ok": False,
            "error": "HuggingFace model ID must use owner/model format.",
        }, 400

    model_dir_name = _huggingface_model_dir_name(model_id)
    model_directory = _vllm_local_model_directory(model_dir_name)
    if _model_directory_has_downloaded_contents(model_directory):
        model_container_path = _vllm_local_model_container_path(model_dir_name)
        return {
            "ok": False,
            "error": f"{model_id} already exists at {model_directory} ({model_container_path}).",
        }, 409

    job, created = _start_huggingface_download_job(
        kind="huggingface",
        model_id=model_id,
        model_dir_name=model_dir_name,
        token=huggingface_token,
        model_container_path=_vllm_local_model_container_path(model_dir_name),
    )
    return {
        "ok": True,
        "created": created,
        "message": (
            f"{model_id} download started."
            if created
            else f"{model_id} download already in progress."
        ),
        "download_job": job,
        "status_url": url_for(
            "agents.vllm_local_huggingface_download_status",
            job_id=str(job.get("id") or ""),
        ),
    }, 202

@bp.get("/settings/provider/vllm-local/downloads/<job_id>")
def vllm_local_huggingface_download_status(job_id: str):
    job = _get_huggingface_download_job(job_id.strip())
    if job is None:
        abort(404)
    return {"download_job": job}

@bp.post("/settings/provider/vllm-local/qwen")
def toggle_vllm_local_qwen_model():
    llm_settings = _load_integration_settings("llm")
    huggingface_token = _vllm_local_huggingface_token(llm_settings)
    action = (request.form.get("qwen_action") or "").strip().lower()
    if action not in {"download", "remove"}:
        flash("Unknown Qwen action.", "error")
        return redirect(url_for("agents.settings_integrations_huggingface"))
    if action == "download":
        if _qwen_model_downloaded():
            flash("Qwen model is already downloaded.", "info")
            return redirect(url_for("agents.settings_integrations_huggingface"))
        try:
            job, created = _start_huggingface_download_job(
                kind="qwen",
                model_id=_qwen_model_id(),
                model_dir_name=_qwen_model_dir_name(),
                token=huggingface_token,
                model_container_path=_qwen_model_container_path(),
            )
        except Exception:
            logger.exception("Failed to queue Qwen download.")
            flash("Failed to queue Qwen download.", "error")
        else:
            if created:
                flash(
                    f"Qwen download queued in background (job {job.get('id')}).",
                    "success",
                )
            else:
                flash("Qwen download is already in progress.", "info")
        return redirect(url_for("agents.settings_integrations_huggingface"))

    try:
        removed = _remove_qwen_model_directory()
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("agents.settings_integrations_huggingface"))
    except OSError as exc:
        logger.exception("Failed to remove Qwen directory.")
        flash(f"Failed to remove Qwen model files: {exc}", "error")
        return redirect(url_for("agents.settings_integrations_huggingface"))

    if removed:
        configured_model = (llm_settings.get("vllm_local_model") or "").strip()
        if configured_model in {str(_qwen_model_directory()), _qwen_model_container_path()}:
            _save_integration_settings("llm", {"vllm_local_model": ""})
        flash("Qwen model removed.", "success")
    else:
        flash("Qwen model directory is already absent.", "info")
    return redirect(url_for("agents.settings_integrations_huggingface"))

@bp.post("/settings/provider/vllm-local/huggingface")
def download_vllm_local_huggingface_model():
    llm_settings = _load_integration_settings("llm")
    huggingface_token = _vllm_local_huggingface_token(llm_settings)
    if not huggingface_token:
        flash(
            "Set and save a HuggingFace token before downloading arbitrary HuggingFace models.",
            "error",
        )
        return redirect(url_for("agents.settings_integrations_huggingface"))

    model_id = _normalize_huggingface_repo_id(
        request.form.get("vllm_local_hf_model_id", "")
    )
    if not model_id:
        flash("HuggingFace model ID must use owner/model format.", "error")
        return redirect(url_for("agents.settings_integrations_huggingface"))

    model_dir_name = _huggingface_model_dir_name(model_id)
    model_directory = _vllm_local_model_directory(model_dir_name)
    model_container_path = _vllm_local_model_container_path(model_dir_name)
    if _model_directory_has_downloaded_contents(model_directory):
        flash(
            f"{model_id} already exists at {model_directory} ({model_container_path}).",
            "info",
        )
        return redirect(url_for("agents.settings_integrations_huggingface"))

    try:
        job, created = _start_huggingface_download_job(
            kind="huggingface",
            model_id=model_id,
            model_dir_name=model_dir_name,
            token=huggingface_token,
            model_container_path=model_container_path,
        )
    except Exception:
        logger.exception("Failed to queue HuggingFace model download.")
        flash("Failed to queue HuggingFace model download.", "error")
    else:
        if created:
            flash(f"{model_id} download queued in background (job {job.get('id')}).", "success")
        else:
            flash(f"{model_id} download is already in progress.", "info")
    return redirect(url_for("agents.settings_integrations_huggingface"))

@bp.post("/settings/provider/vllm-local/huggingface/delete")
def delete_vllm_local_huggingface_model():
    model_dir_name = _normalize_vllm_local_model_dir_name(
        request.form.get("model_dir_name")
    )
    if not model_dir_name:
        flash("Model directory name is required.", "error")
        return redirect(url_for("agents.settings_integrations_huggingface"))

    model_entry = _find_downloaded_vllm_local_model(model_dir_name)
    if model_entry is None:
        flash("Model directory is already absent.", "info")
        return redirect(url_for("agents.settings_integrations_huggingface"))

    try:
        removed = _remove_vllm_local_model_directory(model_dir_name)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("agents.settings_integrations_huggingface"))
    except OSError as exc:
        logger.exception("Failed to remove HuggingFace model directory.")
        flash(f"Failed to remove downloaded model files: {exc}", "error")
        return redirect(url_for("agents.settings_integrations_huggingface"))

    if not removed:
        flash("Model directory is already absent.", "info")
        return redirect(url_for("agents.settings_integrations_huggingface"))

    llm_settings = _load_integration_settings("llm")
    configured_model = (llm_settings.get("vllm_local_model") or "").strip()
    configured_matches = {
        str(model_entry.get("value") or "").strip(),
        str(model_entry.get("target_dir") or "").strip(),
        str(model_entry.get("container_path") or "").strip(),
    }
    configured_matches.discard("")
    if configured_model and configured_model in configured_matches:
        _save_integration_settings("llm", {"vllm_local_model": ""})

    label = str(model_entry.get("label") or model_dir_name).strip() or model_dir_name
    flash(f"Removed downloaded model: {label}.", "success")
    return redirect(url_for("agents.settings_integrations_huggingface"))

@bp.post("/settings/provider/vllm-remote")
def update_vllm_remote_settings():
    payload = _settings_request_payload()
    is_api_request = _workflow_api_request()
    request_id = _workflow_request_id()
    correlation_id = _workflow_correlation_id()
    remote_base_url = _settings_form_value(payload, "vllm_remote_base_url")
    remote_api_key = _settings_form_value(payload, "vllm_remote_api_key")
    remote_model = _settings_form_value(payload, "vllm_remote_model")
    remote_models = _settings_form_value(payload, "vllm_remote_models")
    payload = {
        "vllm_remote_base_url": remote_base_url,
        "vllm_remote_api_key": remote_api_key,
        "vllm_remote_model": remote_model,
        "vllm_remote_models": remote_models,
    }
    _save_integration_settings("llm", payload)
    if is_api_request:
        response_payload = {"provider": "vllm_remote"}
        _emit_model_provider_event(
            event_type="config:provider:updated",
            entity_kind="provider",
            entity_id="vllm_remote",
            payload=response_payload,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        return _workflow_success_payload(
            payload=response_payload,
            request_id=request_id,
            correlation_id=correlation_id,
        )
    flash("vLLM Remote settings updated.", "success")
    return redirect(url_for("agents.settings_provider_vllm_remote"))

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
        active_page="settings_celery",
    )

@bp.get("/settings/runtime")
@bp.get("/settings/runtime/node")
def settings_runtime():
    return _render_settings_runtime_page("node")

@bp.get("/settings/runtime/rag")
def settings_runtime_rag():
    return _render_settings_runtime_page("rag")

@bp.get("/settings/runtime/chat")
def settings_runtime_chat():
    return _render_settings_runtime_page("chat")

@bp.get("/settings/chat")
def settings_chat():
    summary = _settings_summary()
    models = _load_llm_models()
    mcp_servers = _load_mcp_servers()
    rag_health, rag_collections = _chat_rag_health_payload()
    chat_default_settings = _resolved_chat_default_settings(
        models=models,
        mcp_servers=mcp_servers,
        rag_collections=rag_collections,
    )
    if _workflow_wants_json():
        return {
            "models": [
                {
                    "id": model.id,
                    "name": model.name,
                    "description": model.description,
                    "provider": model.provider,
                    "provider_label": LLM_PROVIDER_LABELS.get(
                        model.provider, model.provider
                    ),
                    "model_name": _model_display_name(model),
                    "created_at": _human_time(model.created_at),
                    "updated_at": _human_time(model.updated_at),
                }
                for model in models
            ],
            "mcp_servers": [
                {
                    "id": server.id,
                    "name": server.name,
                    "description": server.description,
                    "server_key": server.server_key,
                    "server_type": server.server_type,
                    "created_at": _human_time(server.created_at),
                    "updated_at": _human_time(server.updated_at),
                }
                for server in mcp_servers
            ],
            "rag_health": rag_health,
            "rag_collections": rag_collections,
            "chat_default_settings": chat_default_settings,
            "chat_runtime_settings": load_chat_runtime_settings_payload(),
            "summary": summary,
        }
    return render_template(
        "settings_chat.html",
        models=models,
        mcp_servers=mcp_servers,
        rag_health=rag_health,
        rag_collections=rag_collections,
        chat_default_settings=chat_default_settings,
        chat_runtime_settings=load_chat_runtime_settings_payload(),
        summary=summary,
        page_title="Settings - Chat",
        active_page="settings_chat",
    )

@bp.post("/settings/chat/defaults")
def update_chat_default_settings_route():
    payload = _settings_request_payload()
    is_api_request = _workflow_api_request()
    models = _load_llm_models()
    mcp_servers = _load_mcp_servers()
    model_ids = {model.id for model in models}
    mcp_ids = {server.id for server in mcp_servers}
    selected_model_id = _coerce_optional_int(
        _settings_form_value(payload, "default_model_id"),
        field_name="default_model_id",
        minimum=1,
    )
    if selected_model_id is not None and selected_model_id not in model_ids:
        if is_api_request:
            return {"error": "Default model selection is invalid."}, 400
        flash("Default model selection is invalid.", "error")
        return redirect(url_for("agents.settings_chat"))
    selected_mcp_server_ids = _coerce_chat_id_list(
        _settings_form_list(payload, "default_mcp_server_ids"),
        field_name="default_mcp_server_id",
    )
    if any(server_id not in mcp_ids for server_id in selected_mcp_server_ids):
        if is_api_request:
            return {"error": "Default MCP server selection is invalid."}, 400
        flash("Default MCP server selection is invalid.", "error")
        return redirect(url_for("agents.settings_chat"))
    rag_health, rag_collections = _chat_rag_health_payload()
    available_rag_ids = {
        str(item.get("id") or "").strip()
        for item in rag_collections
        if str(item.get("id") or "").strip()
    }
    selected_rag_collections = _coerce_chat_collection_list(
        _settings_form_list(payload, "default_rag_collections")
    )
    if selected_rag_collections and (
        rag_health.get("state") != "configured_healthy" or not available_rag_ids
    ):
        if is_api_request:
            return {"error": "RAG defaults are unavailable until RAG is healthy."}, 400
        flash("RAG defaults are unavailable until RAG is healthy.", "error")
        return redirect(url_for("agents.settings_chat"))
    if any(collection_id not in available_rag_ids for collection_id in selected_rag_collections):
        if is_api_request:
            return {"error": "Default RAG collection selection is invalid."}, 400
        flash("Default RAG collection selection is invalid.", "error")
        return redirect(url_for("agents.settings_chat"))
    selected_default_response_complexity = normalize_chat_response_complexity(
        _settings_form_value(payload, "default_response_complexity"),
        default=CHAT_RESPONSE_COMPLEXITY_DEFAULT,
    )
    save_chat_default_settings(
        {
            "default_model_id": str(selected_model_id or ""),
            "default_response_complexity": selected_default_response_complexity,
            "default_mcp_server_ids": [
                str(server_id) for server_id in selected_mcp_server_ids
            ],
            "default_rag_collections": selected_rag_collections,
        }
    )
    if is_api_request:
        return {
            "ok": True,
            "chat_default_settings": _resolved_chat_default_settings(
                models=models,
                mcp_servers=mcp_servers,
                rag_collections=rag_collections,
            ),
        }
    flash("Chat default settings updated.", "success")
    return redirect(url_for("agents.settings_chat"))

@bp.post("/settings/runtime/chat")
def update_chat_runtime_settings_route():
    settings_payload = _settings_request_payload()
    is_api_request = _workflow_api_request()
    payload = {
        "history_budget_percent": _settings_form_value(
            settings_payload, "history_budget_percent"
        ),
        "rag_budget_percent": _settings_form_value(settings_payload, "rag_budget_percent"),
        "mcp_budget_percent": _settings_form_value(settings_payload, "mcp_budget_percent"),
        "compaction_trigger_percent": _settings_form_value(
            settings_payload, "compaction_trigger_percent"
        ),
        "compaction_target_percent": _settings_form_value(
            settings_payload, "compaction_target_percent"
        ),
        "preserve_recent_turns": _settings_form_value(
            settings_payload, "preserve_recent_turns"
        ),
        "rag_top_k": _settings_form_value(settings_payload, "rag_top_k"),
        "default_context_window_tokens": _settings_form_value(
            settings_payload,
            "default_context_window_tokens",
        ),
        "max_compaction_summary_chars": _settings_form_value(
            settings_payload,
            "max_compaction_summary_chars",
        ),
    }
    save_chat_runtime_settings(payload)
    if is_api_request:
        return {
            "ok": True,
            "chat_runtime_settings": load_chat_runtime_settings_payload(),
        }
    flash("Chat runtime settings updated.", "success")
    if _settings_form_value(settings_payload, "return_to").strip().lower() == "runtime":
        return redirect(url_for("agents.settings_runtime_chat"))
    return redirect(url_for("agents.settings_chat"))

@bp.post("/settings/runtime/instructions")
def update_instruction_runtime_settings_route():
    request_payload = _settings_request_payload()
    is_api_request = _workflow_api_request()
    payload: dict[str, str] = {}
    for provider in LLM_PROVIDERS:
        native_key = f"instruction_native_enabled_{provider}"
        fallback_key = f"instruction_fallback_enabled_{provider}"
        payload[native_key] = (
            "true" if _as_bool(_settings_form_value(request_payload, native_key)) else ""
        )
        payload[fallback_key] = (
            "true"
            if _as_bool(_settings_form_value(request_payload, fallback_key))
            else ""
        )
    _save_integration_settings("llm", payload)
    if is_api_request:
        return {
            "ok": True,
            "instruction_runtime_flags": _instruction_runtime_flags(
                _load_integration_settings("llm")
            ),
        }
    flash("Instruction runtime adapter flags updated.", "success")
    return redirect(url_for("agents.settings_runtime"))

@bp.post("/settings/runtime/node-executor")
def update_node_executor_runtime_settings_route():
    request_payload = _settings_request_payload()
    is_api_request = _workflow_api_request()
    # Auth is not available yet. Once RBAC ships, limit this endpoint to admins.
    requested_provider = _settings_form_value(request_payload, "provider").strip().lower()
    if requested_provider and requested_provider != "kubernetes":
        if is_api_request:
            return {"error": "Node executor provider must be kubernetes."}, 400
        flash("Node executor provider must be kubernetes.", "error")
        return redirect(url_for("agents.settings_runtime"))
    legacy_image_keys = ("k8s_image", "k8s_image_tag")
    if any(
        key in request_payload or key in request.form
        for key in legacy_image_keys
    ):
        message = (
            "Legacy node executor image fields are not supported. "
            "Use k8s_frontier_image/k8s_frontier_image_tag instead."
        )
        if is_api_request:
            return {"error": message}, 400
        flash(message, "error")
        return redirect(url_for("agents.settings_runtime"))
    kubeconfig_value = _settings_form_value(request_payload, "k8s_kubeconfig")
    kubeconfig_clear = _as_bool(
        _settings_form_value(request_payload, "k8s_kubeconfig_clear")
    )
    payload = {
        "provider": "kubernetes",
        "dispatch_timeout_seconds": _settings_form_value(
            request_payload, "dispatch_timeout_seconds"
        ),
        "execution_timeout_seconds": _settings_form_value(
            request_payload, "execution_timeout_seconds"
        ),
        "log_collection_timeout_seconds": _settings_form_value(
            request_payload,
            "log_collection_timeout_seconds",
        ),
        "cancel_grace_timeout_seconds": _settings_form_value(
            request_payload,
            "cancel_grace_timeout_seconds",
        ),
        "cancel_force_kill_enabled": (
            "true"
            if _as_bool(_settings_form_value(request_payload, "cancel_force_kill_enabled"))
            else "false"
        ),
        "workspace_identity_key": _settings_form_value(
            request_payload, "workspace_identity_key"
        ),
        "agent_runtime_cutover_enabled": (
            "true"
            if _as_bool(_settings_form_value(request_payload, "agent_runtime_cutover_enabled"))
            else "false"
        ),
        "k8s_namespace": _settings_form_value(request_payload, "k8s_namespace"),
        "k8s_frontier_image": _settings_form_value(
            request_payload, "k8s_frontier_image"
        ),
        "k8s_frontier_image_tag": _settings_form_value(
            request_payload, "k8s_frontier_image_tag"
        ),
        "k8s_vllm_image": _settings_form_value(request_payload, "k8s_vllm_image"),
        "k8s_vllm_image_tag": _settings_form_value(
            request_payload, "k8s_vllm_image_tag"
        ),
        "k8s_in_cluster": (
            "true" if _as_bool(_settings_form_value(request_payload, "k8s_in_cluster")) else "false"
        ),
        "k8s_service_account": _settings_form_value(
            request_payload, "k8s_service_account"
        ),
        "k8s_gpu_limit": _settings_form_value(request_payload, "k8s_gpu_limit"),
        "k8s_job_ttl_seconds": _settings_form_value(
            request_payload, "k8s_job_ttl_seconds"
        ),
        "k8s_image_pull_secrets_json": _settings_form_value(
            request_payload,
            "k8s_image_pull_secrets_json",
        ),
    }
    optional_split_image_keys = (
        "k8s_frontier_image",
        "k8s_frontier_image_tag",
        "k8s_vllm_image",
        "k8s_vllm_image_tag",
    )
    for optional_key in optional_split_image_keys:
        if optional_key in request_payload or optional_key in request.form:
            continue
        payload.pop(optional_key, None)
    if kubeconfig_clear:
        payload["k8s_kubeconfig"] = ""
    elif kubeconfig_value.strip():
        payload["k8s_kubeconfig"] = kubeconfig_value
    try:
        save_node_executor_settings(payload)
    except ValueError as exc:
        if is_api_request:
            return {"error": str(exc)}, 400
        flash(str(exc), "error")
        return redirect(url_for("agents.settings_runtime"))
    if is_api_request:
        return {
            "ok": True,
            "node_executor_settings": load_node_executor_settings(),
        }
    flash("Node executor runtime settings updated.", "success")
    return redirect(url_for("agents.settings_runtime"))

@bp.get("/settings/runtime/node-executor/effective")
def node_executor_runtime_effective_config_route():
    return {"node_executor": node_executor_effective_config_summary()}

@bp.get("/settings/gitconfig")
def settings_gitconfig():
    return redirect(url_for("agents.settings_integrations_git"))

@bp.post("/settings/gitconfig")
def update_gitconfig():
    return update_integrations_gitconfig()

@bp.post("/settings/runtime/rag")
@bp.post("/settings/integrations/rag")
def update_rag_settings():
    request_payload = _settings_request_payload()
    is_api_request = _workflow_api_request()
    defaults = _rag_default_settings()
    db_provider = _normalize_rag_db_provider(
        _settings_form_value(request_payload, "rag_db_provider")
    )
    embed_provider = _normalize_rag_model_provider(
        _settings_form_value(request_payload, "rag_embed_provider")
    )
    chat_provider = _normalize_rag_model_provider(
        _settings_form_value(request_payload, "rag_chat_provider")
    )
    chat_response_style = _normalize_rag_chat_response_style(
        _settings_form_value(request_payload, "rag_chat_response_style")
    )
    chat_temperature = _coerce_rag_float_str(
        _settings_form_value(request_payload, "rag_chat_temperature"),
        float(defaults.get("chat_temperature") or 0.2),
        minimum=0.0,
        maximum=2.0,
    )
    openai_embed_model = _coerce_rag_model_choice(
        _settings_form_value(request_payload, "rag_openai_embed_model"),
        default=defaults["openai_embed_model"],
        choices=RAG_OPENAI_EMBED_MODEL_OPTIONS,
    )
    gemini_embed_model = _coerce_rag_model_choice(
        _settings_form_value(request_payload, "rag_gemini_embed_model"),
        default=defaults["gemini_embed_model"],
        choices=RAG_GEMINI_EMBED_MODEL_OPTIONS,
    )
    openai_chat_model = _coerce_rag_model_choice(
        _settings_form_value(request_payload, "rag_openai_chat_model"),
        default=defaults["openai_chat_model"],
        choices=RAG_OPENAI_CHAT_MODEL_OPTIONS,
    )
    gemini_chat_model = _coerce_rag_model_choice(
        _settings_form_value(request_payload, "rag_gemini_chat_model"),
        default=defaults["gemini_chat_model"],
        choices=RAG_GEMINI_CHAT_MODEL_OPTIONS,
    )
    payload = {
        "db_provider": db_provider,
        "embed_provider": embed_provider,
        "chat_provider": chat_provider,
        # RAG runtime auth uses Provider settings as source-of-truth.
        "openai_api_key": "",
        "gemini_api_key": "",
        "openai_embed_model": openai_embed_model,
        "gemini_embed_model": gemini_embed_model,
        "openai_chat_model": openai_chat_model,
        "gemini_chat_model": gemini_chat_model,
        "chat_temperature": chat_temperature,
        "openai_chat_temperature": chat_temperature,
        "chat_response_style": chat_response_style,
        "chat_top_k": _coerce_rag_int_str(
            _settings_form_value(request_payload, "rag_chat_top_k"),
            int(defaults.get("chat_top_k") or 5),
            minimum=1,
            maximum=20,
        ),
        "chat_max_history": _coerce_rag_int_str(
            _settings_form_value(request_payload, "rag_chat_max_history"),
            int(defaults.get("chat_max_history") or 8),
            minimum=1,
            maximum=50,
        ),
        "chat_max_context_chars": _coerce_rag_int_str(
            _settings_form_value(request_payload, "rag_chat_max_context_chars"),
            int(defaults.get("chat_max_context_chars") or 12000),
            minimum=1000,
            maximum=1000000,
        ),
        "chat_snippet_chars": _coerce_rag_int_str(
            _settings_form_value(request_payload, "rag_chat_snippet_chars"),
            int(defaults.get("chat_snippet_chars") or 600),
            minimum=100,
            maximum=10000,
        ),
        "chat_context_budget_tokens": _coerce_rag_int_str(
            _settings_form_value(request_payload, "rag_chat_context_budget_tokens"),
            int(defaults.get("chat_context_budget_tokens") or 8000),
            minimum=256,
            maximum=100000,
        ),
        "index_parallel_workers": _coerce_rag_int_str(
            _settings_form_value(request_payload, "rag_index_parallel_workers"),
            int(defaults.get("index_parallel_workers") or 1),
            minimum=1,
            maximum=64,
        ),
        "embed_parallel_requests": _coerce_rag_int_str(
            _settings_form_value(request_payload, "rag_embed_parallel_requests"),
            int(defaults.get("embed_parallel_requests") or 1),
            minimum=1,
            maximum=64,
        ),
    }
    _save_rag_settings("rag", payload)

    chroma_ready = _chroma_connected(_resolved_chroma_settings())
    if is_api_request:
        return {
            "ok": True,
            "warning": (
                "RAG settings saved. Configure ChromaDB host and port before indexing or chat."
                if db_provider == "chroma" and not chroma_ready
                else ""
            ),
            "rag_settings": _effective_rag_settings(),
        }
    if db_provider == "chroma" and not chroma_ready:
        flash(
            "RAG settings saved. Configure ChromaDB host and port before indexing or chat.",
            "warning",
        )
    else:
        flash("RAG settings updated.", "success")
    return redirect(url_for("agents.settings_runtime_rag"))
