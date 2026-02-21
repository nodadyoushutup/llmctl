from .shared import *  # noqa: F401,F403

__all__ = ['chat_page', 'chat_activity', 'create_chat_thread_route', 'update_chat_thread_route', 'archive_chat_thread_route', 'restore_chat_thread_route', 'clear_chat_thread_route', 'delete_chat_thread_route', 'api_health', 'api_chat_runtime', 'api_create_chat_thread', 'api_chat_thread', 'api_archive_chat_thread', 'api_clear_chat_thread', 'api_chat_thread_config', 'api_chat_activity', 'api_chat_turn', 'list_nodes', 'view_node', 'remove_node_attachment', 'node_status', 'cancel_node', 'retry_node', 'delete_node', 'new_node', 'create_node']


def _task_prompt_input_context(prompt_json: object) -> dict[str, object]:
    if not isinstance(prompt_json, dict):
        return {}
    direct_input_context = prompt_json.get("input_context")
    if isinstance(direct_input_context, dict):
        return direct_input_context
    task_context = prompt_json.get("task_context")
    if not isinstance(task_context, dict):
        return {}
    flowchart_context = task_context.get("flowchart")
    if not isinstance(flowchart_context, dict):
        return {}
    input_context = flowchart_context.get("input_context")
    if not isinstance(input_context, dict):
        return {}
    return input_context


def _task_incoming_connector_context(
    session,
    *,
    task: AgentTask,
    prompt_json: object,
) -> dict[str, object]:
    node_run_id: int | None = None
    context_source = "none"
    input_context: dict[str, object] = {}
    node_run = (
        session.execute(
            select(FlowchartRunNode)
            .where(FlowchartRunNode.agent_task_id == task.id)
            .order_by(FlowchartRunNode.execution_index.desc(), FlowchartRunNode.id.desc())
        )
        .scalars()
        .first()
    )
    if (
        node_run is None
        and task.flowchart_run_id is not None
        and task.flowchart_node_id is not None
    ):
        node_run = (
            session.execute(
                select(FlowchartRunNode)
                .where(
                    FlowchartRunNode.flowchart_run_id == task.flowchart_run_id,
                    FlowchartRunNode.flowchart_node_id == task.flowchart_node_id,
                )
                .order_by(FlowchartRunNode.execution_index.desc(), FlowchartRunNode.id.desc())
            )
            .scalars()
            .first()
        )
    if node_run is not None:
        node_run_id = int(node_run.id)
        input_context = _parse_json_dict(node_run.input_context_json)
        context_source = "flowchart_run_node"
    if not input_context:
        prompt_input_context = _task_prompt_input_context(prompt_json)
        if prompt_input_context:
            input_context = prompt_input_context
            context_source = "task_prompt"
    trigger_sources, pulled_dotted_sources = _flowchart_run_node_context_trace(
        input_context
    )
    upstream_nodes = [
        item
        for item in (input_context.get("upstream_nodes") or [])
        if isinstance(item, dict)
    ]
    dotted_upstream_nodes = [
        item
        for item in (input_context.get("dotted_upstream_nodes") or [])
        if isinstance(item, dict)
    ]
    return {
        "source": context_source,
        "flowchart_run_node_id": node_run_id,
        "input_context": input_context,
        "upstream_nodes": upstream_nodes,
        "dotted_upstream_nodes": dotted_upstream_nodes,
        "context_only_upstream_nodes": dotted_upstream_nodes,
        "trigger_sources": trigger_sources,
        "pulled_dotted_sources": pulled_dotted_sources,
        "context_only_sources": pulled_dotted_sources,
        "trigger_source_count": len(trigger_sources),
        "pulled_dotted_source_count": len(pulled_dotted_sources),
        "context_only_source_count": len(pulled_dotted_sources),
        "has_connector_context": bool(
            upstream_nodes or dotted_upstream_nodes or trigger_sources or pulled_dotted_sources
        ),
    }


_LEFT_PANEL_RESULTS_SUMMARY_KEYS = (
    "message",
    "answer",
    "result",
    "summary",
    "content",
    "action_results",
)
_LEFT_PANEL_OUTPUT_DETAIL_KEYS = (
    "node_type",
    "action",
    "status",
    "memory_id",
    "execution_status",
    "fallback_used",
    "action_prompt_template",
    "additive_prompt",
    "effective_prompt",
)
_LEFT_PANEL_DETERMINISTIC_NODE_TYPES = {
    "decision",
    "milestone",
    "memory",
    "plan",
    "rag",
}
_LEFT_PANEL_NO_INFERRED_PROMPT_NOTICE = "No inferred prompt in deterministic mode."


def _left_panel_label(value: object) -> str:
    return str(value or "").replace("_", " ").strip()


def _left_panel_summary_value(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, list):
        if not value:
            return "-"
        return "\n".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, indent=2, sort_keys=True)
    return str(value)


def _left_panel_parse_record(raw_json: str | None) -> dict[str, object]:
    raw_text = str(raw_json or "").strip()
    if not raw_text or not raw_text.startswith("{"):
        return {}
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _left_panel_task_output_payload(task_output: str) -> dict[str, object]:
    return _left_panel_parse_record(task_output)


def _left_panel_prompt_payload(prompt_json: str | None) -> dict[str, object]:
    return _left_panel_parse_record(prompt_json)


def _left_panel_add_collection_values(
    target: list[str],
    seen: set[str],
    raw_value: object,
) -> None:
    if isinstance(raw_value, str):
        cleaned = raw_value.strip()
        if not cleaned or cleaned in seen:
            return
        seen.add(cleaned)
        target.append(cleaned)
        return
    if isinstance(raw_value, list):
        for item in raw_value:
            _left_panel_add_collection_values(target, seen, item)
        return


def _left_panel_extract_collections(
    *,
    prompt_payload: dict[str, object],
    quick_context: dict[str, object],
    task_output: str,
) -> list[str]:
    collections: list[str] = []
    seen: set[str] = set()

    _left_panel_add_collection_values(
        collections, seen, quick_context.get("collection")
    )
    _left_panel_add_collection_values(
        collections, seen, quick_context.get("collections")
    )

    _left_panel_add_collection_values(collections, seen, prompt_payload.get("collections"))
    _left_panel_add_collection_values(
        collections, seen, prompt_payload.get("selected_collections")
    )

    task_context = (
        prompt_payload.get("task_context")
        if isinstance(prompt_payload.get("task_context"), dict)
        else {}
    )
    if isinstance(task_context, dict):
        rag_quick = (
            task_context.get("rag_quick_run")
            if isinstance(task_context.get("rag_quick_run"), dict)
            else {}
        )
        if isinstance(rag_quick, dict):
            _left_panel_add_collection_values(collections, seen, rag_quick.get("collection"))
            _left_panel_add_collection_values(collections, seen, rag_quick.get("collections"))
        flowchart_context = (
            task_context.get("flowchart")
            if isinstance(task_context.get("flowchart"), dict)
            else {}
        )
        if isinstance(flowchart_context, dict):
            _left_panel_add_collection_values(
                collections, seen, flowchart_context.get("collections")
            )
            node_config = (
                flowchart_context.get("node_config")
                if isinstance(flowchart_context.get("node_config"), dict)
                else {}
            )
            if isinstance(node_config, dict):
                _left_panel_add_collection_values(
                    collections, seen, node_config.get("collections")
                )

    node_config = (
        prompt_payload.get("node_config")
        if isinstance(prompt_payload.get("node_config"), dict)
        else {}
    )
    if isinstance(node_config, dict):
        _left_panel_add_collection_values(collections, seen, node_config.get("collections"))
    flowchart_node_config = (
        prompt_payload.get("flowchart_node_config")
        if isinstance(prompt_payload.get("flowchart_node_config"), dict)
        else {}
    )
    if isinstance(flowchart_node_config, dict):
        _left_panel_add_collection_values(
            collections, seen, flowchart_node_config.get("collections")
        )

    output_payload = _left_panel_task_output_payload(task_output)
    _left_panel_add_collection_values(collections, seen, output_payload.get("collections"))
    _left_panel_add_collection_values(
        collections, seen, output_payload.get("selected_collections")
    )
    quick_output = (
        output_payload.get("quick_rag")
        if isinstance(output_payload.get("quick_rag"), dict)
        else {}
    )
    if isinstance(quick_output, dict):
        _left_panel_add_collection_values(collections, seen, quick_output.get("collection"))
        _left_panel_add_collection_values(collections, seen, quick_output.get("collections"))

    return collections


def _left_panel_connector_blocks(
    incoming_connector_context: dict[str, object],
) -> list[dict[str, object]]:
    trigger_nodes = [
        item
        for item in (incoming_connector_context.get("upstream_nodes") or [])
        if isinstance(item, dict)
    ]
    context_only_nodes = [
        item
        for item in (incoming_connector_context.get("dotted_upstream_nodes") or [])
        if isinstance(item, dict)
    ]

    blocks: list[dict[str, object]] = []

    for index, node in enumerate(trigger_nodes, start=1):
        blocks.append(
            {
                "id": f"trigger-{index}",
                "label": str(node.get("condition_key") or f"Trigger connector {index}"),
                "classification": "trigger",
                "source_edge_id": node.get("source_edge_id"),
                "source_node_id": node.get("source_node_id"),
                "source_node_type": node.get("source_node_type"),
                "condition_key": node.get("condition_key"),
                "edge_mode": node.get("edge_mode"),
                "output_state": node.get("output_state"),
            }
        )

    for index, node in enumerate(context_only_nodes, start=1):
        blocks.append(
            {
                "id": f"context-only-{index}",
                "label": str(node.get("condition_key") or f"Context only connector {index}"),
                "classification": "context_only",
                "source_edge_id": node.get("source_edge_id"),
                "source_node_id": node.get("source_node_id"),
                "source_node_type": node.get("source_node_type"),
                "condition_key": node.get("condition_key"),
                "edge_mode": node.get("edge_mode"),
                "output_state": node.get("output_state"),
            }
        )

    return blocks


def _left_panel_is_deterministic_prompt_mode(
    *,
    task: AgentTask,
    prompt_payload: dict[str, object],
    output_payload: dict[str, object],
) -> bool:
    node_type_candidates = [
        str(prompt_payload.get("flowchart_node_type") or "").strip().lower(),
        str(output_payload.get("node_type") or "").strip().lower(),
    ]
    for node_type in node_type_candidates:
        if node_type in _LEFT_PANEL_DETERMINISTIC_NODE_TYPES:
            return True
    execution_mode = str(_task_execution_mode(task) or "").strip().lower()
    if execution_mode in {"indexing", "delta_indexing", "query"}:
        return True
    return False


def _left_panel_details_rows(
    *,
    task: AgentTask,
    task_output: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [
        {"key": "kind", "label": "Kind", "value": task.kind or "-"},
        {"key": "flowchart_id", "label": "Flowchart", "value": task.flowchart_id or "-"},
        {"key": "flowchart_run_id", "label": "Flowchart run", "value": task.flowchart_run_id or "-"},
        {"key": "flowchart_node_id", "label": "Flowchart node", "value": task.flowchart_node_id or "-"},
        {"key": "model_id", "label": "Model", "value": task.model_id or "-"},
        {"key": "autorun_node", "label": "Autorun node", "value": task.run_task_id or "-"},
        {"key": "celery_task_id", "label": "Celery task", "value": task.celery_task_id or "-"},
        {"key": "current_stage", "label": "Current stage", "value": task.current_stage or "-"},
        {"key": "status", "label": "Status", "value": task.status or "-"},
        {"key": "created_at", "label": "Created", "value": _human_time(task.created_at) or "-"},
        {"key": "started_at", "label": "Started", "value": _human_time(task.started_at) or "-"},
        {"key": "finished_at", "label": "Finished", "value": _human_time(task.finished_at) or "-"},
    ]

    output_payload = _left_panel_task_output_payload(task_output)
    for key in _LEFT_PANEL_OUTPUT_DETAIL_KEYS:
        if key not in output_payload:
            continue
        rows.append(
            {
                "key": key,
                "label": _left_panel_label(key),
                "value": _left_panel_summary_value(output_payload.get(key)),
            }
        )
    return rows


def _build_node_left_panel_payload(
    *,
    task: AgentTask,
    agent: Agent | None,
    prompt_text: str | None,
    prompt_json: str | None,
    task_output: str,
    incoming_connector_context: dict[str, object],
    mcp_servers_payload: list[dict[str, object]],
    quick_context: dict[str, object],
) -> dict[str, object]:
    output_payload = _left_panel_task_output_payload(task_output)
    prompt_payload = _left_panel_prompt_payload(prompt_json)

    summary_rows: list[dict[str, object]] = []
    primary_text = ""
    for key in _LEFT_PANEL_RESULTS_SUMMARY_KEYS:
        if key not in output_payload:
            continue
        value = output_payload.get(key)
        summary_rows.append(
            {
                "key": key,
                "label": _left_panel_label(key),
                "value": _left_panel_summary_value(value),
            }
        )
        if not primary_text and isinstance(value, str) and value.strip():
            primary_text = value.strip()
    action_results_value = output_payload.get("action_results")
    action_results: list[str] = []
    if isinstance(action_results_value, list):
        action_results = [
            str(item).strip()
            for item in action_results_value
            if str(item).strip()
        ]
    elif isinstance(action_results_value, str) and action_results_value.strip():
        action_results = [action_results_value.strip()]
    if not primary_text and action_results:
        primary_text = action_results[0]

    parsed_output_json = False
    formatted_output = task_output
    stripped_output = str(task_output or "").strip()
    if stripped_output:
        try:
            parsed = json.loads(stripped_output)
            formatted_output = json.dumps(parsed, indent=2, sort_keys=True)
            parsed_output_json = True
        except json.JSONDecodeError:
            parsed_output_json = False

    connector_blocks = _left_panel_connector_blocks(incoming_connector_context)
    resolved_input_context = incoming_connector_context.get("input_context")
    if not isinstance(resolved_input_context, dict):
        resolved_input_context = {}

    deterministic_prompt_mode = _left_panel_is_deterministic_prompt_mode(
        task=task,
        prompt_payload=prompt_payload,
        output_payload=output_payload,
    )
    collections = _left_panel_extract_collections(
        prompt_payload=prompt_payload,
        quick_context=quick_context,
        task_output=task_output,
    )

    return {
        "input": {
            "source": str(incoming_connector_context.get("source") or "none"),
            "trigger_source_count": int(
                incoming_connector_context.get("trigger_source_count") or 0
            ),
            "context_only_source_count": int(
                incoming_connector_context.get("context_only_source_count")
                or incoming_connector_context.get("pulled_dotted_source_count")
                or 0
            ),
            "connector_blocks": connector_blocks,
            "resolved_input_context": resolved_input_context,
        },
        "results": {
            "summary_rows": summary_rows,
            "primary_text": primary_text,
            "action_results": action_results,
        },
        "prompt": {
            "provided_prompt_text": prompt_text or "",
            "provided_prompt_fields": prompt_payload,
            "no_inferred_prompt_in_deterministic_mode": deterministic_prompt_mode,
            "notice": (
                _LEFT_PANEL_NO_INFERRED_PROMPT_NOTICE
                if deterministic_prompt_mode
                else ""
            ),
        },
        "agent": {
            "id": int(agent.id) if agent is not None else None,
            "name": str(agent.name or "") if agent is not None else "",
            "link_href": f"/agents/{int(agent.id)}" if agent is not None else "",
        },
        "mcp_servers": {
            "items": mcp_servers_payload,
        },
        "collections": {
            "items": [
                {"id_or_key": collection_name, "name": collection_name}
                for collection_name in collections
            ],
        },
        "raw_json": {
            "formatted_output": formatted_output,
            "is_json": parsed_output_json,
        },
        "details": {
            "rows": _left_panel_details_rows(task=task, task_output=task_output),
        },
    }

@bp.get("/chat")
def chat_page():
    sync_integrated_mcp_servers()
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    models = _load_llm_models()
    mcp_servers = _load_mcp_servers()
    threads = list_chat_threads()
    try:
        selected_thread_id = _coerce_optional_int(
            request.args.get("thread_id"),
            field_name="thread_id",
            minimum=1,
        )
    except ValueError:
        selected_thread_id = None
    selected_thread = None
    if selected_thread_id is not None:
        selected_thread = get_chat_thread(selected_thread_id)
    if selected_thread is not None and str(selected_thread.get("status") or "") != "active":
        selected_thread = None
    if selected_thread is None and threads:
        selected_thread = get_chat_thread(int(threads[0]["id"]))
    rag_health, rag_collections = _chat_rag_health_payload()
    chat_default_settings = _resolved_chat_default_settings(
        models=models,
        mcp_servers=mcp_servers,
        rag_collections=rag_collections,
    )
    return render_template(
        "chat_runtime.html",
        summary=summary,
        page_title="Live Chat",
        active_page="chat",
        models=models,
        mcp_servers=mcp_servers,
        threads=threads,
        selected_thread=selected_thread,
        rag_health=rag_health,
        rag_collections=rag_collections,
        chat_default_settings=chat_default_settings,
        chat_settings=load_chat_runtime_settings_payload(),
        fixed_list_page=True,
    )

@bp.get("/chat/activity")
def chat_activity():
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    event_class = (request.args.get("event_class") or "").strip() or None
    event_type = (request.args.get("event_type") or "").strip() or None
    reason_code = (request.args.get("reason_code") or "").strip() or None
    try:
        thread_id = _coerce_optional_int(
            request.args.get("thread_id"),
            field_name="thread_id",
            minimum=1,
        )
    except ValueError:
        thread_id = None
    events = list_chat_activity(
        event_class=event_class,
        event_type=event_type,
        reason_code=reason_code,
        thread_id=thread_id,
    )
    threads = list_chat_threads(include_archived=True)
    return render_template(
        "chat_activity.html",
        summary=summary,
        page_title="Chat Activity",
        active_page="chat_activity",
        events=events,
        threads=threads,
        selected_event_class=event_class or "",
        selected_event_type=event_type or "",
        selected_reason_code=reason_code or "",
        selected_thread_id=thread_id,
    )

@bp.post("/chat/threads")
def create_chat_thread_route():
    try:
        title = (request.form.get("title") or "").strip() or CHAT_DEFAULT_THREAD_TITLE
        default_settings = load_chat_default_settings_payload()
        default_response_complexity = normalize_chat_response_complexity(
            default_settings.get("default_response_complexity"),
            default=CHAT_RESPONSE_COMPLEXITY_DEFAULT,
        )
        response_complexity = normalize_chat_response_complexity(
            request.form.get("response_complexity"),
            default=default_response_complexity,
        )
        model_id_raw = request.form.get("model_id")
        if model_id_raw is None or not str(model_id_raw).strip():
            default_model_id = default_settings.get("default_model_id")
            if isinstance(default_model_id, int):
                model_id = default_model_id
            else:
                model_id = resolve_default_model_id(_load_integration_settings("llm"))
        else:
            model_id = _coerce_optional_int(
                model_id_raw,
                field_name="model_id",
                minimum=1,
            )
        mcp_values = request.form.getlist("mcp_server_ids")
        if not mcp_values and request.form.get("mcp_selection_present") is None:
            mcp_values = [
                str(value)
                for value in default_settings.get("default_mcp_server_ids", [])
                if isinstance(value, int)
            ]
        mcp_server_ids = _coerce_chat_id_list(
            mcp_values,
            field_name="mcp_server_id",
        )
        rag_values = request.form.getlist("rag_collections")
        if not rag_values and request.form.get("rag_selection_present") is None:
            rag_values = [
                str(value)
                for value in default_settings.get("default_rag_collections", [])
            ]
        rag_collections = _coerce_chat_collection_list(
            rag_values
        )
        thread = create_chat_thread(
            title=title,
            model_id=model_id,
            mcp_server_ids=mcp_server_ids,
            rag_collections=rag_collections,
            response_complexity=response_complexity,
        )
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("agents.chat_page"))
    flash("Chat thread created.", "success")
    return redirect(url_for("agents.chat_page", thread_id=thread["id"]))

@bp.post("/chat/threads/<int:thread_id>/config")
def update_chat_thread_route(thread_id: int):
    try:
        response_complexity = normalize_chat_response_complexity(
            request.form.get("response_complexity"),
            default=CHAT_RESPONSE_COMPLEXITY_DEFAULT,
        )
        model_id_raw = request.form.get("model_id")
        if model_id_raw is None:
            existing_thread = get_chat_thread(thread_id)
            model_id = _coerce_optional_int(
                None if existing_thread is None else existing_thread.get("model_id"),
                field_name="model_id",
                minimum=1,
            )
        else:
            model_id = _coerce_optional_int(
                model_id_raw,
                field_name="model_id",
                minimum=1,
            )
        mcp_server_ids = _coerce_chat_id_list(
            request.form.getlist("mcp_server_ids"),
            field_name="mcp_server_id",
        )
        rag_collections = _coerce_chat_collection_list(
            request.form.getlist("rag_collections")
        )
        update_chat_thread_config(
            thread_id,
            model_id=model_id,
            mcp_server_ids=mcp_server_ids,
            rag_collections=rag_collections,
            response_complexity=response_complexity,
        )
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("agents.chat_page", thread_id=thread_id))
    flash("Chat thread settings updated.", "success")
    return redirect(url_for("agents.chat_page", thread_id=thread_id))

@bp.post("/chat/threads/<int:thread_id>/archive")
def archive_chat_thread_route(thread_id: int):
    if not archive_chat_thread(thread_id):
        abort(404)
    flash("Chat thread archived.", "success")
    return redirect(url_for("agents.chat_page"))

@bp.post("/chat/threads/<int:thread_id>/restore")
def restore_chat_thread_route(thread_id: int):
    if not restore_chat_thread(thread_id):
        abort(404)
    flash("Chat thread restored.", "success")
    return redirect(url_for("agents.chat_page", thread_id=thread_id))

@bp.post("/chat/threads/<int:thread_id>/clear")
def clear_chat_thread_route(thread_id: int):
    if not clear_chat_thread(thread_id):
        abort(404)
    flash("Chat thread cleared.", "success")
    return redirect(url_for("agents.chat_page", thread_id=thread_id))

@bp.post("/chat/threads/<int:thread_id>/delete")
def delete_chat_thread_route(thread_id: int):
    if not delete_chat_thread(thread_id):
        abort(404)
    flash("Chat thread deleted.", "success")
    return redirect(url_for("agents.chat_page"))

@bp.get("/api/health")
def api_health():
    return {"ok": True, "service": "llmctl-studio-backend"}

@bp.get("/api/chat/runtime")
def api_chat_runtime():
    models = _load_llm_models()
    mcp_servers = _load_mcp_servers()
    threads = list_chat_threads()
    try:
        selected_thread_id = _coerce_optional_int(
            request.args.get("thread_id"),
            field_name="thread_id",
            minimum=1,
        )
    except ValueError:
        return {"error": "thread_id must be an integer."}, 400
    selected_thread = None
    if selected_thread_id is not None:
        selected_thread = get_chat_thread(selected_thread_id)
    if selected_thread is not None and str(selected_thread.get("status") or "") != "active":
        selected_thread = None
    if selected_thread is None and threads:
        selected_thread = get_chat_thread(int(threads[0]["id"]))
    rag_health, rag_collections = _chat_rag_health_payload()
    chat_default_settings = _resolved_chat_default_settings(
        models=models,
        mcp_servers=mcp_servers,
        rag_collections=rag_collections,
    )
    return {
        "threads": threads,
        "selected_thread_id": (
            int(selected_thread["id"])
            if isinstance(selected_thread, dict) and selected_thread.get("id") is not None
            else None
        ),
        "selected_thread": selected_thread,
        "models": [
            {"id": model.id, "name": model.name, "provider": model.provider}
            for model in models
        ],
        "mcp_servers": [
            {"id": server.id, "name": server.name, "server_key": server.server_key}
            for server in mcp_servers
        ],
        "rag_health": rag_health,
        "rag_collections": rag_collections,
        "chat_default_settings": chat_default_settings,
    }

@bp.post("/api/chat/threads")
def api_create_chat_thread():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return {"error": "Invalid JSON payload."}, 400
    try:
        title = str(payload.get("title") or "").strip() or CHAT_DEFAULT_THREAD_TITLE
        default_settings = load_chat_default_settings_payload()
        default_response_complexity = normalize_chat_response_complexity(
            default_settings.get("default_response_complexity"),
            default=CHAT_RESPONSE_COMPLEXITY_DEFAULT,
        )
        response_complexity = normalize_chat_response_complexity(
            payload.get("response_complexity"),
            default=default_response_complexity,
        )
        model_id_raw = payload.get("model_id")
        if model_id_raw is None or not str(model_id_raw).strip():
            default_model_id = default_settings.get("default_model_id")
            if isinstance(default_model_id, int):
                model_id = default_model_id
            else:
                model_id = resolve_default_model_id(_load_integration_settings("llm"))
        else:
            model_id = _coerce_optional_int(
                model_id_raw,
                field_name="model_id",
                minimum=1,
            )
        mcp_raw = payload.get("mcp_server_ids")
        if mcp_raw is None:
            mcp_values = [
                str(value)
                for value in default_settings.get("default_mcp_server_ids", [])
                if isinstance(value, int)
            ]
        elif isinstance(mcp_raw, list):
            mcp_values = list(mcp_raw)
        else:
            return {"error": "mcp_server_ids must be an array."}, 400
        mcp_server_ids = _coerce_chat_id_list(
            mcp_values,
            field_name="mcp_server_id",
        )
        rag_raw = payload.get("rag_collections")
        if rag_raw is None:
            rag_values = [
                str(value)
                for value in default_settings.get("default_rag_collections", [])
            ]
        elif isinstance(rag_raw, list):
            rag_values = list(rag_raw)
        else:
            return {"error": "rag_collections must be an array."}, 400
        rag_collections = _coerce_chat_collection_list(rag_values)
        thread = create_chat_thread(
            title=title,
            model_id=model_id,
            mcp_server_ids=mcp_server_ids,
            rag_collections=rag_collections,
            response_complexity=response_complexity,
        )
    except ValueError as exc:
        return {"error": str(exc)}, 400
    thread_payload = get_chat_thread(int(thread["id"]))
    return {"ok": True, "thread": thread_payload or thread}

@bp.get("/api/chat/threads/<int:thread_id>")
def api_chat_thread(thread_id: int):
    payload = get_chat_thread(thread_id)
    if payload is None:
        return {"error": "Thread not found."}, 404
    return payload

@bp.post("/api/chat/threads/<int:thread_id>/archive")
def api_archive_chat_thread(thread_id: int):
    if not archive_chat_thread(thread_id):
        return {"error": "Thread not found."}, 404
    return {"ok": True, "thread_id": thread_id}

@bp.post("/api/chat/threads/<int:thread_id>/clear")
def api_clear_chat_thread(thread_id: int):
    if not clear_chat_thread(thread_id):
        return {"error": "Thread not found."}, 404
    payload = get_chat_thread(thread_id)
    if payload is None:
        return {"error": "Thread not found."}, 404
    return {"ok": True, "thread": payload}

@bp.post("/api/chat/threads/<int:thread_id>/config")
def api_chat_thread_config(thread_id: int):
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return {"error": "Invalid JSON payload."}, 400

    model_id_raw = payload.get("model_id")
    try:
        model_id = _coerce_optional_int(
            model_id_raw if model_id_raw is not None else None,
            field_name="model_id",
            minimum=1,
        )
    except ValueError as exc:
        return {"error": str(exc)}, 400

    response_complexity = normalize_chat_response_complexity(
        payload.get("response_complexity"),
        default=CHAT_RESPONSE_COMPLEXITY_DEFAULT,
    )

    mcp_raw = payload.get("mcp_server_ids")
    if mcp_raw is None:
        mcp_values: list[object] = []
    elif isinstance(mcp_raw, list):
        mcp_values = list(mcp_raw)
    else:
        return {"error": "mcp_server_ids must be an array."}, 400
    try:
        mcp_server_ids = _coerce_chat_id_list(
            mcp_values,
            field_name="mcp_server_id",
        )
    except ValueError as exc:
        return {"error": str(exc)}, 400

    rag_raw = payload.get("rag_collections")
    if rag_raw is None:
        rag_values: list[object] = []
    elif isinstance(rag_raw, list):
        rag_values = list(rag_raw)
    else:
        return {"error": "rag_collections must be an array."}, 400
    rag_collections = _coerce_chat_collection_list(rag_values)

    try:
        update_chat_thread_config(
            thread_id,
            model_id=model_id,
            mcp_server_ids=mcp_server_ids,
            rag_collections=rag_collections,
            response_complexity=response_complexity,
        )
    except ValueError as exc:
        return {"error": str(exc)}, 400

    thread_payload = get_chat_thread(thread_id)
    if thread_payload is None:
        return {"error": "Thread not found."}, 404
    return {"ok": True, "thread": thread_payload}

@bp.get("/api/chat/activity")
def api_chat_activity():
    event_class = (request.args.get("event_class") or "").strip() or None
    event_type = (request.args.get("event_type") or "").strip() or None
    reason_code = (request.args.get("reason_code") or "").strip() or None
    limit = _parse_positive_int(request.args.get("limit"), 200)
    try:
        thread_id = _coerce_optional_int(
            request.args.get("thread_id"),
            field_name="thread_id",
            minimum=1,
        )
    except ValueError:
        return {"error": "thread_id must be an integer."}, 400
    events = list_chat_activity(
        event_class=event_class,
        event_type=event_type,
        reason_code=reason_code,
        thread_id=thread_id,
        limit=limit,
    )
    return {
        "events": events,
        "threads": list_chat_threads(include_archived=True),
        "filters": {
            "event_class": event_class or "",
            "event_type": event_type or "",
            "reason_code": reason_code or "",
            "thread_id": thread_id,
            "limit": limit,
        },
        "meta": {"total": len(events)},
    }

@bp.post("/api/chat/threads/<int:thread_id>/turn")
def api_chat_turn(thread_id: int):
    payload = request.get_json(silent=True) or {}
    for key in ("model_id", "mcp_server_ids", "rag_collections", "response_complexity"):
        if key in payload:
            return {
                "error": (
                    "Model, response complexity, MCP, and RAG selectors "
                    "are session-scoped only."
                ),
                "reason_code": CHAT_REASON_SELECTOR_SCOPE,
            }, 400
    message = str(payload.get("message") or "").strip()
    if not message:
        return {"error": "Message is required."}, 400
    try:
        result = execute_chat_turn(thread_id=thread_id, message=message)
    except ValueError as exc:
        return {"error": str(exc)}, 400
    thread_payload = get_chat_thread(thread_id)
    if result.ok:
        return {
            "ok": True,
            "thread_id": result.thread_id,
            "turn_id": result.turn_id,
            "request_id": result.request_id,
            "reply": result.reply,
            "thread": thread_payload,
        }
    status_code = 500
    if result.reason_code == "RAG_UNAVAILABLE_FOR_SELECTED_COLLECTIONS":
        status_code = 503
    elif result.reason_code == "RAG_RETRIEVAL_EXECUTION_FAILED":
        status_code = 502
    return {
        "ok": False,
        "thread_id": result.thread_id,
        "turn_id": result.turn_id,
        "request_id": result.request_id,
        "reason_code": result.reason_code,
        "error": result.error,
        "rag_health_state": result.rag_health_state,
        "selected_collections": result.selected_collections,
        "thread": thread_payload,
    }, status_code

@bp.get("/nodes", endpoint="list_nodes")
def list_nodes():
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
        status_values = {
            value
            for value in session.execute(select(AgentTask.status).distinct())
            .scalars()
            .all()
            if value
        }
        node_type_values = {
            normalized
            for normalized in (
                _normalize_flowchart_node_type(value)
                for value in session.execute(
                    select(FlowchartNode.node_type)
                    .join(AgentTask, AgentTask.flowchart_node_id == FlowchartNode.id)
                    .distinct()
                )
                .scalars()
                .all()
            )
            if normalized
        }
        for kind_value in (
            value
            for value in session.execute(select(AgentTask.kind).distinct())
            .scalars()
            .all()
            if value
        ):
            normalized = _flowchart_node_type_from_task_kind(kind_value)
            if normalized:
                node_type_values.add(normalized)

    node_type_filter_raw = (
        request.args.get("node_type") or request.args.get("kind") or ""
    ).strip()
    normalized_node_type_filter = _normalize_flowchart_node_type(node_type_filter_raw)
    node_type_filter = (
        normalized_node_type_filter
        if normalized_node_type_filter in node_type_values
        else None
    )
    status_filter_raw = (request.args.get("status") or "").strip()
    status_filter = status_filter_raw if status_filter_raw in status_values else None
    agent_filter = None
    agent_filter_raw = request.args.get("agent_id")
    if agent_filter_raw:
        candidate = _parse_positive_int(agent_filter_raw, 0)
        if candidate in filter_agent_ids:
            agent_filter = candidate
    flowchart_node_filter_raw = request.args.get("flowchart_node_id")
    flowchart_node_filter = None
    if flowchart_node_filter_raw:
        candidate = _parse_positive_int(flowchart_node_filter_raw, 0)
        if candidate > 0:
            flowchart_node_filter = candidate

    status_order = {
        "pending": 0,
        "queued": 1,
        "running": 2,
        "succeeded": 3,
        "failed": 4,
        "canceled": 5,
    }
    node_type_options = [
        {"value": node_type, "label": node_type.replace("_", " ")}
        for node_type in sorted(node_type_values)
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
        node_type=node_type_filter,
        status=status_filter,
        flowchart_node_id=flowchart_node_filter,
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
    flowchart_node_ids = {
        task.flowchart_node_id
        for task in tasks
        if task.flowchart_node_id is not None
    }
    flowchart_node_types_by_id: dict[int, str] = {}
    flowchart_node_names_by_id: dict[int, str] = {}
    if flowchart_node_ids:
        with session_scope() as session:
            rows = session.execute(
                select(
                    FlowchartNode.id,
                    FlowchartNode.node_type,
                    FlowchartNode.title,
                    FlowchartNode.config_json,
                ).where(
                    FlowchartNode.id.in_(flowchart_node_ids)
                )
            ).all()
        for row in rows:
            node_id = int(row[0])
            node_type = str(row[1] or "").strip().lower()
            title = str(row[2] or "").strip()
            config = _parse_json_dict(row[3])
            inline_name = config.get("task_name")
            task_name = str(inline_name).strip() if isinstance(inline_name, str) else ""
            if not task_name:
                task_name = title
            if not task_name:
                type_label = (node_type or "node").replace("_", " ")
                task_name = f"{type_label} node"
            flowchart_node_types_by_id[node_id] = node_type
            flowchart_node_names_by_id[node_id] = task_name
    task_node_types: dict[int, str | None] = {}
    task_node_names: dict[int, str] = {}
    for task in tasks:
        flowchart_node_type = (
            _normalize_flowchart_node_type(
                flowchart_node_types_by_id.get(task.flowchart_node_id)
            )
            if task.flowchart_node_id is not None
            else None
        )
        resolved_node_type = flowchart_node_type or _flowchart_node_type_from_task_kind(
            task.kind
        )
        if not resolved_node_type and is_quick_rag_task_kind(task.kind):
            resolved_node_type = FLOWCHART_NODE_TYPE_RAG
        task_node_types[task.id] = resolved_node_type
        if task.flowchart_node_id is not None:
            task_node_names[task.id] = flowchart_node_names_by_id.get(
                task.flowchart_node_id, f"Node {task.flowchart_node_id}"
            )
        elif is_quick_rag_task_kind(task.kind):
            task_node_names[task.id] = _quick_rag_task_display_name(task)
        elif is_quick_task_kind(task.kind):
            task_node_names[task.id] = "Quick node"
        else:
            task_node_names[task.id] = "-"
    current_url = request.full_path
    if current_url.endswith("?"):
        current_url = current_url[:-1]
    if _nodes_wants_json():
        task_payload = [
            _serialize_node_list_item(
                task,
                agent_name=str(agents_by_id.get(task.agent_id) or ""),
                node_type=task_node_types.get(task.id),
                node_name=task_node_names.get(task.id, "-"),
            )
            for task in tasks
        ]
        return {
            "tasks": task_payload,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages,
                "total_tasks": total_tasks,
                "per_page_options": list(TASKS_PER_PAGE_OPTIONS),
                "items": pagination_items,
            },
            "filter_options": {
                "agent": agent_filter_options,
                "node_type": node_type_options,
                "status": task_status_options,
            },
            "filters": {
                "agent_id": agent_filter,
                "node_type": node_type_filter,
                "status": status_filter,
                "flowchart_node_id": flowchart_node_filter,
            },
        }
    return render_template(
        "tasks.html",
        tasks=tasks,
        agents_by_id=agents_by_id,
        task_node_types=task_node_types,
        task_node_names=task_node_names,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total_tasks=total_tasks,
        per_page_options=TASKS_PER_PAGE_OPTIONS,
        pagination_items=pagination_items,
        agent_filter_options=agent_filter_options,
        node_type_options=node_type_options,
        task_status_options=task_status_options,
        quick_rag_task_kinds=[
            RAG_QUICK_INDEX_TASK_KIND,
            RAG_QUICK_DELTA_TASK_KIND,
        ],
        agent_filter=agent_filter,
        node_type_filter=node_type_filter,
        status_filter=status_filter,
        flowchart_node_filter=flowchart_node_filter,
        current_url=current_url,
        summary=summary,
        human_time=_human_time,
        page_title="Nodes",
        active_page="nodes",
    )

@bp.get("/nodes/<int:task_id>", endpoint="view_node")
def view_node(task_id: int):
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    selected_integration_labels: list[str] = []
    task_integrations_legacy_default = False
    incoming_connector_context: dict[str, object] = {}
    with session_scope() as session:
        task = (
            session.execute(
                select(AgentTask)
                .options(
                    selectinload(AgentTask.scripts),
                    selectinload(AgentTask.attachments),
                    selectinload(AgentTask.mcp_servers),
                )
                .where(AgentTask.id == task_id)
            )
            .scalars()
            .first()
        )
        if task is None:
            abort(404)
        _sync_quick_rag_task_from_index_job(session, task)
        agent = None
        if task.agent_id is not None:
            agent = (
                session.execute(
                    select(Agent)
                    .where(Agent.id == task.agent_id)
                )
                .scalars()
                .first()
            )
        stage_entries = _build_stage_entries(task)
        prompt_text, prompt_json = _parse_task_prompt(task.prompt)
        incoming_connector_context = _task_incoming_connector_context(
            session,
            task=task,
            prompt_json=prompt_json,
        )
        task_output = _task_output_for_display(task.output)
        selected_integration_keys = parse_task_integration_keys(task.integration_keys_json)
        if selected_integration_keys is None:
            task_integrations_legacy_default = True
            selected_integration_labels = [
                TASK_INTEGRATION_LABELS[key]
                for key in sorted(TASK_INTEGRATION_KEYS)
            ]
        else:
            selected_integration_labels = [
                TASK_INTEGRATION_LABELS[key]
                for key in sorted(selected_integration_keys)
                if key in TASK_INTEGRATION_LABELS
            ]
    if _nodes_wants_json():
        task_runtime = _serialize_node_executor_metadata(task)
        mcp_servers_payload = [
            {
                "id": server.id,
                "name": server.name,
                "server_key": server.server_key,
            }
            for server in task.mcp_servers
        ]
        quick_context = _quick_rag_task_context(task)
        left_panel = _build_node_left_panel_payload(
            task=task,
            agent=agent,
            prompt_text=prompt_text,
            prompt_json=prompt_json,
            task_output=task_output,
            incoming_connector_context=incoming_connector_context,
            mcp_servers_payload=mcp_servers_payload,
            quick_context=quick_context,
        )
        return {
            "task": {
                "id": task.id,
                "status": task.status,
                "kind": task.kind,
                "agent_id": task.agent_id,
                "model_id": task.model_id,
                "flowchart_id": task.flowchart_id,
                "flowchart_run_id": task.flowchart_run_id,
                "flowchart_node_id": task.flowchart_node_id,
                "run_task_id": task.run_task_id,
                "celery_task_id": task.celery_task_id,
                "created_at": _human_time(task.created_at),
                "started_at": _human_time(task.started_at),
                "finished_at": _human_time(task.finished_at),
                "current_stage": task.current_stage or "",
                "error": task.error or "",
                "output": task_output,
                **task_runtime,
            },
            "agent": (
                {
                    "id": agent.id,
                    "name": agent.name,
                }
                if agent is not None
                else None
            ),
            "prompt_text": prompt_text,
            "prompt_json": prompt_json,
            "stage_entries": stage_entries,
            "selected_integration_labels": selected_integration_labels,
            "task_integrations_legacy_default": task_integrations_legacy_default,
            "incoming_connector_context": incoming_connector_context,
            "left_panel": left_panel,
            "scripts": [
                {
                    "id": script.id,
                    "file_name": script.file_name,
                    "script_type": script.script_type,
                }
                for script in task.scripts
            ],
            "attachments": [
                {
                    "id": attachment.id,
                    "file_name": attachment.file_name,
                    "file_path": attachment.file_path,
                    "content_type": attachment.content_type,
                }
                for attachment in task.attachments
            ],
            "mcp_servers": mcp_servers_payload,
            "quick_context": quick_context,
            "is_quick_task": is_quick_task_kind(task.kind),
            "is_quick_rag_task": is_quick_rag_task_kind(task.kind),
        }
    return render_template(
        "task_detail.html",
        task=task,
        task_output=task_output,
        is_quick_task=is_quick_task_kind(task.kind),
        is_quick_rag_task=is_quick_rag_task_kind(task.kind),
        quick_rag_task_context=_quick_rag_task_context(task),
        agent=agent,
        stage_entries=stage_entries,
        prompt_text=prompt_text,
        prompt_json=prompt_json,
        selected_integration_labels=selected_integration_labels,
        task_integrations_legacy_default=task_integrations_legacy_default,
        summary=summary,
        page_title=f"Node {task_id}",
        active_page="nodes",
    )

@bp.post(
    "/nodes/<int:task_id>/attachments/<int:attachment_id>/remove",
    endpoint="remove_node_attachment",
)
def remove_node_attachment(task_id: int, attachment_id: int):
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.view_node", task_id=task_id)
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
            flash("Attachment not found on this node.", "error")
            return redirect(redirect_target)
        task.attachments.remove(attachment)
        session.flush()
        removed_path = _delete_attachment_if_unused(session, attachment)
    if removed_path:
        remove_attachment_file(removed_path)
    flash("Attachment removed.", "success")
    return redirect(redirect_target)

@bp.get("/nodes/<int:task_id>/status", endpoint="node_status")
def node_status(task_id: int):
    with session_scope() as session:
        task = session.get(AgentTask, task_id)
        if task is None:
            abort(404)
        _sync_quick_rag_task_from_index_job(session, task)
        task_runtime = _serialize_node_executor_metadata(task)
        return {
            "id": task.id,
            "status": task.status,
            "run_task_id": task.run_task_id,
            "celery_task_id": task.celery_task_id,
            "prompt_length": len(task.prompt) if task.prompt else 0,
            "output": _task_output_for_display(task.output),
            "error": task.error or "",
            "current_stage": task.current_stage or "",
            "stage_logs": _parse_stage_logs(task.stage_logs),
            "stage_entries": _build_stage_entries(task),
            "started_at": _human_time(task.started_at),
            "finished_at": _human_time(task.finished_at),
            "created_at": _human_time(task.created_at),
            **task_runtime,
        }

@bp.post("/nodes/<int:task_id>/cancel", endpoint="cancel_node")
def cancel_node(task_id: int):
    is_api_request = _stage3_api_request()
    redirect_target = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_nodes")
    )
    with session_scope() as session:
        task = session.get(AgentTask, task_id)
        if task is None:
            abort(404)
        if task.status not in {"queued", "running"}:
            if is_api_request:
                return {"ok": True, "already_stopped": True}
            flash("Node is not running.", "info")
            return redirect(redirect_target)
        if task.celery_task_id and Config.CELERY_REVOKE_ON_STOP:
            celery_app.control.revoke(
                task.celery_task_id, terminate=True, signal="SIGTERM"
            )
        task.status = "canceled"
        task.error = "Canceled by user."
        task.finished_at = utcnow()
    if is_api_request:
        return {"ok": True, "already_stopped": False}
    flash("Node cancel requested.", "success")
    return redirect(redirect_target)

@bp.post("/nodes/<int:task_id>/retry", endpoint="retry_node")
def retry_node(task_id: int):
    is_api_request = _stage3_api_request()
    next_target = request.form.get("next")
    with session_scope() as session:
        source_task = (
            session.execute(
                select(AgentTask)
                .options(
                    selectinload(AgentTask.attachments),
                    selectinload(AgentTask.mcp_servers),
                )
                .where(AgentTask.id == task_id)
            )
            .scalars()
            .first()
        )
        if source_task is None:
            abort(404)
        retry_task = AgentTask.create(
            session,
            agent_id=source_task.agent_id,
            model_id=source_task.model_id,
            status="queued",
            prompt=source_task.prompt or "",
            kind=source_task.kind,
            integration_keys_json=source_task.integration_keys_json,
        )
        retry_task.attachments = list(source_task.attachments or [])
        retry_task.mcp_servers = list(source_task.mcp_servers or [])
        session.flush()
        _clone_task_scripts(session, source_task.id, retry_task.id)
        retry_task_id = int(retry_task.id)

    celery_task = run_agent_task.delay(retry_task_id)

    with session_scope() as session:
        retry_task = session.get(AgentTask, retry_task_id)
        if retry_task is not None:
            retry_task.celery_task_id = celery_task.id

    if is_api_request:
        return {
            "ok": True,
            "task_id": retry_task_id,
            "celery_task_id": celery_task.id,
            "source_task_id": task_id,
        }, 201
    redirect_target = _safe_redirect_target(
        next_target,
        url_for("agents.view_node", task_id=retry_task_id),
    )
    flash(f"Node {retry_task_id} queued.", "success")
    return redirect(redirect_target)

@bp.post("/nodes/<int:task_id>/delete", endpoint="delete_node")
def delete_node(task_id: int):
    is_api_request = _stage3_api_request()
    next_url = _safe_redirect_target(
        request.form.get("next"), url_for("agents.list_nodes")
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
    if is_api_request:
        return {"ok": True}
    flash("Node deleted.", "success")
    return redirect(next_url)

@bp.get("/nodes/new", endpoint="new_node")
def new_node():
    agents = _load_agents()
    _, summary = _agent_rollup(agents)
    scripts = _load_scripts()
    scripts_by_type = _group_scripts_by_type(scripts)
    selected_scripts_by_type = {script_type: [] for script_type in SCRIPT_TYPE_FIELDS}
    integration_options = _build_node_integration_options()
    default_selected_integration_keys = [
        str(option["key"])
        for option in integration_options
        if bool(option.get("connected"))
    ]
    if _nodes_wants_json():
        script_options = [
            {
                "id": script.id,
                "file_name": script.file_name,
                "script_type": script.script_type,
            }
            for script in scripts
        ]
        return {
            "agents": [_serialize_agent_list_item(agent) for agent in agents],
            "scripts": script_options,
            "script_type_fields": SCRIPT_TYPE_FIELDS,
            "script_type_choices": [
                {"value": value, "label": label}
                for value, label in SCRIPT_TYPE_WRITE_CHOICES
            ],
            "integration_options": integration_options,
            "selected_integration_keys": default_selected_integration_keys,
        }
    return render_template(
        "new_task.html",
        agents=agents,
        scripts_by_type=scripts_by_type,
        selected_scripts_by_type=selected_scripts_by_type,
        script_type_fields=SCRIPT_TYPE_FIELDS,
        script_type_choices=SCRIPT_TYPE_WRITE_CHOICES,
        integration_options=integration_options,
        selected_integration_keys=default_selected_integration_keys,
        summary=summary,
        page_title="New Node",
        active_page="nodes",
    )

@bp.post("/nodes/new", endpoint="create_node")
def create_node():
    is_api_request = _stage3_api_request()
    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None or not isinstance(payload, dict):
        payload = {}

    def _node_error(message: str, status_code: int = 400):
        if is_api_request:
            return {"error": message}, status_code
        flash(message, "error")
        return redirect(url_for("agents.new_node"))

    if request.is_json:
        agent_id_raw = str(payload.get("agent_id") or "").strip()
        prompt = str(payload.get("prompt") or "").strip()
        uploads = []
        script_ids_by_type = {script_type: [] for script_type in SCRIPT_TYPE_FIELDS}
        raw_script_map = payload.get("script_ids_by_type")
        if raw_script_map is not None:
            if not isinstance(raw_script_map, dict):
                return _node_error("script_ids_by_type must be an object.")
            for script_type in SCRIPT_TYPE_FIELDS:
                raw_values = raw_script_map.get(script_type) or []
                if not isinstance(raw_values, list):
                    return _node_error("Script selection is invalid.")
                parsed_values: list[int] = []
                for raw_value in raw_values:
                    try:
                        parsed = _coerce_optional_int(raw_value, field_name="script_id", minimum=1)
                    except ValueError:
                        return _node_error("Script selection is invalid.")
                    if parsed is None:
                        continue
                    parsed_values.append(parsed)
                script_ids_by_type[script_type] = parsed_values
        raw_legacy_ids = payload.get("script_ids") or []
        if not isinstance(raw_legacy_ids, list):
            return _node_error("script_ids must be an array.")
        legacy_ids: list[int] = []
        for raw_value in raw_legacy_ids:
            try:
                parsed = _coerce_optional_int(raw_value, field_name="script_id", minimum=1)
            except ValueError:
                return _node_error("Script selection is invalid.")
            if parsed is None:
                continue
            legacy_ids.append(parsed)
        script_error = None
        raw_integrations = payload.get("integration_keys") or []
        if not isinstance(raw_integrations, list):
            return _node_error("integration_keys must be an array.")
        selected_integration_keys, invalid_keys = validate_task_integration_keys(
            [str(value).strip() for value in raw_integrations]
        )
        integration_error = "Integration selection is invalid." if invalid_keys else None
    else:
        agent_id_raw = request.form.get("agent_id", "").strip()
        prompt = request.form.get("prompt", "").strip()
        uploads = request.files.getlist("attachments")
        script_ids_by_type, legacy_ids, script_error = _parse_script_selection()
        selected_integration_keys, integration_error = _parse_node_integration_selection()

    if not agent_id_raw:
        return _node_error("Select an agent.")
    try:
        agent_id = int(agent_id_raw)
    except ValueError:
        return _node_error("Select a valid agent.")
    if not prompt:
        return _node_error("Prompt is required.")
    if script_error:
        return _node_error(script_error)
    if integration_error:
        return _node_error(integration_error)

    try:
        with session_scope() as session:
            agent = session.get(Agent, agent_id)
            if agent is None:
                return _node_error("Agent not found.", 404)
            script_ids_by_type, script_error = _resolve_script_selection(
                session,
                script_ids_by_type,
                legacy_ids,
            )
            if script_error:
                return _node_error(script_error)
            task = AgentTask.create(
                session,
                agent_id=agent_id,
                status="queued",
                prompt=prompt,
                integration_keys_json=serialize_task_integration_keys(
                    selected_integration_keys
                ),
            )
            _set_task_scripts(session, task.id, script_ids_by_type)
            attachments = _save_uploaded_attachments(session, uploads)
            _attach_attachments(task, attachments)
            task_id = task.id
    except (OSError, ValueError) as exc:
        logger.exception("Failed to save task attachments")
        return _node_error(str(exc) or "Failed to save attachments.")

    celery_task = run_agent_task.delay(task_id)

    with session_scope() as session:
        task = session.get(AgentTask, task_id)
        if task is not None:
            task.celery_task_id = celery_task.id

    if is_api_request:
        return {"ok": True, "task_id": task_id, "celery_task_id": celery_task.id}, 201
    flash(f"Node {task_id} queued.", "success")
    return redirect(url_for("agents.list_nodes"))
