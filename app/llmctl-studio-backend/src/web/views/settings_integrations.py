from .shared import *  # noqa: F401,F403

__all__ = ['github_workspace', 'github_pull_request', 'github_pull_request_commits', 'github_pull_request_checks', 'github_pull_request_files', 'github_pull_request_code_review', 'jira_workspace', 'jira_issue_detail', 'confluence_workspace', 'chroma_workspace', 'chroma_collections', 'chroma_collection_detail', 'delete_chroma_collection', 'settings_integrations_git', 'update_integrations_gitconfig', 'settings_integrations', 'settings_integrations_github', 'settings_integrations_jira', 'settings_integrations_confluence', 'settings_integrations_google_drive', 'settings_integrations_google_cloud', 'settings_integrations_google_workspace', 'settings_integrations_huggingface', 'settings_integrations_chroma', 'settings_integrations_rag', 'update_github_settings', 'update_google_drive_settings', 'update_google_cloud_settings', 'update_google_workspace_settings', 'update_huggingface_settings', 'update_chroma_settings', 'update_jira_settings', 'update_confluence_settings']

@bp.get("/github")
def github_workspace():
    is_api_request = _workflow_api_request()
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
    if is_api_request:
        return {
            "workspace": "github",
            "repo": repo,
            "repo_selected": bool(settings.get("repo")),
            "connected": bool(settings.get("pat")),
            "active_tab": tab,
            "pull_requests": pull_requests,
            "pull_request_error": pr_error,
            "pull_request_status": pr_status,
            "pull_request_author": pr_author,
            "pull_request_authors": pr_authors,
            "actions": actions,
            "actions_error": actions_error,
            "code_entries": code_entries,
            "code_file": code_file,
            "code_error": code_error,
            "code_path": code_path,
            "code_parent": code_parent,
            "code_selected_path": code_selected_path,
        }
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

@bp.get("/github/pulls/<int:pr_number>")
def github_pull_request(pr_number: int):
    return _render_github_pull_request_page(
        pr_number,
        "conversation",
        is_api_request=_workflow_api_request(),
    )

@bp.get("/github/pulls/<int:pr_number>/commits")
def github_pull_request_commits(pr_number: int):
    return _render_github_pull_request_page(
        pr_number,
        "commits",
        is_api_request=_workflow_api_request(),
    )

@bp.get("/github/pulls/<int:pr_number>/checks")
def github_pull_request_checks(pr_number: int):
    return _render_github_pull_request_page(
        pr_number,
        "checks",
        is_api_request=_workflow_api_request(),
    )

@bp.get("/github/pulls/<int:pr_number>/files")
def github_pull_request_files(pr_number: int):
    return _render_github_pull_request_page(
        pr_number,
        "files",
        is_api_request=_workflow_api_request(),
    )

@bp.post("/github/pulls/<int:pr_number>/code-review")
def github_pull_request_code_review(pr_number: int):
    is_api_request = _workflow_api_request()
    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None or not isinstance(payload, dict):
        payload = {}
    redirect_target = _safe_redirect_target(
        request.form.get("next"),
        url_for("agents.github_pull_request", pr_number=pr_number),
    )
    settings = _load_integration_settings("github")
    repo = settings.get("repo") or ""
    pat = settings.get("pat") or ""
    if not repo or not pat:
        if is_api_request:
            return {"error": "GitHub repository and PAT are required to run code reviews."}, 400
        flash(
            "GitHub repository and PAT are required to run code reviews.",
            "error",
        )
        return redirect(redirect_target)

    pr_title = (
        str(payload.get("pr_title") or "").strip()
        if is_api_request
        else request.form.get("pr_title", "").strip()
    ) or None
    pr_url = (
        str(payload.get("pr_url") or "").strip()
        if is_api_request
        else request.form.get("pr_url", "").strip()
    ) or None
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

    if is_api_request:
        return {
            "ok": True,
            "task_id": task_id,
            "celery_task_id": celery_task.id,
            "node_url": url_for("agents.view_node", task_id=task_id),
        }, 202
    flash(f"Code review node {task_id} queued.", "success")
    return redirect(url_for("agents.view_node", task_id=task_id))

@bp.get("/jira")
def jira_workspace():
    is_api_request = _workflow_api_request()
    settings = _load_integration_settings("jira")
    selected_board = (settings.get("board") or "").strip()
    selected_board_label = (settings.get("board_label") or "").strip()
    board = selected_board_label or selected_board or "No board selected"
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
    if api_key and selected_board and settings.get("site"):
        auth_key = _combine_atlassian_key(api_key, email)
        if ":" not in auth_key:
            board_error = (
                "Jira API key needs an Atlassian email. Enter it in settings."
            )
        else:
            try:
                board_info: dict[str, object] | None = None
                if selected_board.isdigit():
                    board_info = _fetch_jira_board_by_id(
                        auth_key, settings.get("site") or "", int(selected_board)
                    )
                else:
                    board_info = _fetch_jira_board_by_name(
                        auth_key, settings.get("site") or "", selected_board
                    )
                if not board_info:
                    board_error = (
                        "Selected Jira board not found. Refresh boards in settings."
                    )
                else:
                    board_name = board_info.get("name")
                    if isinstance(board_name, str) and board_name.strip():
                        board = board_name.strip()
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
    if is_api_request:
        return {
            "workspace": "jira",
            "board": board,
            "site": site,
            "board_selected": bool(selected_board),
            "connected": bool(settings.get("api_key")),
            "board_columns": board_columns,
            "board_unmapped": board_unmapped,
            "board_error": board_error,
            "board_issue_total": board_issue_total,
            "board_type": board_type,
            "board_url": board_url,
            "board_column_count": board_column_count,
        }
    return render_template(
        "jira.html",
        jira_board=board,
        jira_site=site,
        jira_board_selected=bool(selected_board),
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
    is_api_request = _workflow_api_request()
    settings = _load_integration_settings("jira")
    board = (
        (settings.get("board_label") or "").strip()
        or (settings.get("board") or "").strip()
        or "No board selected"
    )
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
    if is_api_request:
        return {
            "workspace": "jira",
            "board": board,
            "site": site,
            "issue": issue,
            "issue_error": issue_error,
            "comments": comments,
            "comments_error": comments_error,
            "page_title": page_title,
        }
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
    is_api_request = _workflow_api_request()
    settings = _load_integration_settings("confluence")
    selected_space = (settings.get("space") or "").strip()
    selected_space_name = selected_space or "No space selected"
    for option in _confluence_space_options(settings):
        option_value = (option.get("value") or "").strip()
        if option_value != selected_space:
            continue
        option_label = (option.get("label") or "").strip()
        if " - " in option_label:
            selected_space_name = option_label.split(" - ", 1)[1].strip() or option_label
        elif option_label:
            selected_space_name = option_label
        break
    site = settings.get("site") or "No site configured"
    api_key = settings.get("api_key") or ""
    email = settings.get("email") or ""
    pages: list[dict[str, object]] = []
    page: dict[str, object] | None = None
    selected_page_id = request.args.get("page", "").strip()
    confluence_error: str | None = None
    if not selected_space:
        confluence_error = "Set a Confluence space in Integrations to load pages."
    if api_key and settings.get("site") and selected_space:
        auth_key = _combine_atlassian_key(api_key, email)
        if ":" not in auth_key:
            confluence_error = (
                "Confluence API key needs an Atlassian email. Enter it in settings."
            )
        else:
            try:
                pages = _fetch_confluence_pages(
                    auth_key,
                    settings.get("site") or "",
                    selected_space,
                )
                if pages:
                    page_id = selected_page_id or pages[0].get("id", "")
                    if page_id:
                        page = _fetch_confluence_page(
                            auth_key,
                            settings.get("site") or "",
                            page_id,
                        )
                elif selected_page_id:
                    page = _fetch_confluence_page(
                        auth_key,
                        settings.get("site") or "",
                        selected_page_id,
                    )
            except ValueError as exc:
                confluence_error = str(exc)
    if is_api_request:
        return {
            "workspace": "confluence",
            "space": selected_space or "No space selected",
            "space_name": selected_space_name,
            "space_key": selected_space,
            "pages": pages,
            "selected_page": page,
            "selected_page_id": selected_page_id or (page.get("id") if page else ""),
            "error": confluence_error,
            "site": site,
            "space_selected": bool(selected_space),
            "connected": bool(settings.get("api_key")),
        }
    return render_template(
        "confluence.html",
        confluence_space=selected_space or "No space selected",
        confluence_space_name=selected_space_name,
        confluence_space_key=selected_space,
        confluence_pages=pages,
        confluence_selected_page=page,
        confluence_page_id=selected_page_id or (page.get("id") if page else ""),
        confluence_error=confluence_error,
        confluence_site=site,
        confluence_space_selected=bool(selected_space),
        confluence_connected=bool(settings.get("api_key")),
        page_title="Confluence",
        active_page="confluence",
    )

@bp.get("/chroma")
def chroma_workspace():
    if _workflow_api_request():
        return redirect(url_for("agents.chroma_collections"))
    return redirect(url_for("agents.chroma_collections"))

@bp.get("/chroma/collections")
def chroma_collections():
    is_api_request = _workflow_api_request()
    chroma_settings = _resolved_chroma_settings()
    if not _chroma_connected(chroma_settings):
        if is_api_request:
            return {"error": "Configure ChromaDB host and port in Integrations first."}, 400
        flash("Configure ChromaDB host and port in Integrations first.", "error")
        return redirect(url_for("agents.settings_integrations_chroma"))

    client, host, port, normalized_hint, error = _chroma_http_client(chroma_settings)
    collections: list[dict[str, object]] = []
    chroma_error: str | None = None
    if error or client is None:
        chroma_error = (
            f"Failed to connect to Chroma at {_chroma_endpoint_label(host, port)}: {error}"
        )
    else:
        try:
            collection_names = _list_collection_names(client.list_collections())
            for collection_name in collection_names:
                count: int | None = None
                metadata: dict[str, object] = {}
                try:
                    collection = client.get_collection(name=collection_name)
                    count = collection.count()
                    raw_metadata = getattr(collection, "metadata", None)
                    if isinstance(raw_metadata, dict):
                        metadata = raw_metadata
                except Exception:
                    pass
                collections.append(
                    {
                        "name": collection_name,
                        "count": count,
                        "metadata_preview": (
                            json.dumps(metadata, sort_keys=True) if metadata else "{}"
                        ),
                    }
                )
        except Exception as exc:
            chroma_error = f"Failed to load collections: {exc}"

    page = _parse_page(request.args.get("page"))
    per_page = _parse_page_size(request.args.get("per_page"))
    total_collections = len(collections)
    total_pages = (
        max(1, (total_collections + per_page - 1) // per_page)
        if total_collections
        else 1
    )
    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page
    paged_collections = collections[offset : offset + per_page]
    pagination_items = _build_pagination_items(page, total_pages)

    if is_api_request:
        return {
            "workspace": "chroma",
            "collections": paged_collections,
            "chroma_error": chroma_error,
            "chroma_host": host,
            "chroma_port": port,
            "chroma_ssl": "enabled" if _as_bool(chroma_settings.get("ssl")) else "disabled",
            "chroma_normalized_hint": normalized_hint,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages,
                "per_page_options": PAGINATION_PAGE_SIZES,
                "total_collections": total_collections,
            },
        }
    return render_template(
        "chroma_collections.html",
        collections=paged_collections,
        chroma_error=chroma_error,
        chroma_host=host,
        chroma_port=port,
        chroma_ssl="enabled" if _as_bool(chroma_settings.get("ssl")) else "disabled",
        chroma_normalized_hint=normalized_hint,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        per_page_options=PAGINATION_PAGE_SIZES,
        total_collections=total_collections,
        pagination_items=pagination_items,
        page_title="ChromaDB Collections",
        active_page="chroma",
    )

@bp.get("/chroma/collections/detail")
def chroma_collection_detail():
    is_api_request = _workflow_api_request()
    collection_name = (request.args.get("name") or "").strip()
    if not collection_name:
        if is_api_request:
            return {"error": "Collection name is required."}, 400
        flash("Collection name is required.", "error")
        return redirect(url_for("agents.chroma_collections"))

    chroma_settings = _resolved_chroma_settings()
    if not _chroma_connected(chroma_settings):
        if is_api_request:
            return {"error": "Configure ChromaDB host and port in Integrations first."}, 400
        flash("Configure ChromaDB host and port in Integrations first.", "error")
        return redirect(url_for("agents.settings_integrations_chroma"))

    client, host, port, normalized_hint, error = _chroma_http_client(chroma_settings)
    if error or client is None:
        if is_api_request:
            return {
                "error": f"Failed to connect to Chroma at {_chroma_endpoint_label(host, port)}: {error}"
            }, 502
        flash(
            f"Failed to connect to Chroma at {_chroma_endpoint_label(host, port)}: {error}",
            "error",
        )
        return redirect(url_for("agents.chroma_collections"))

    try:
        collection = client.get_collection(name=collection_name)
        count = collection.count()
        raw_metadata = getattr(collection, "metadata", None)
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    except Exception as exc:
        if is_api_request:
            return {"error": f"Failed to load collection '{collection_name}': {exc}"}, 502
        flash(f"Failed to load collection '{collection_name}': {exc}", "error")
        return redirect(url_for("agents.chroma_collections"))

    if is_api_request:
        return {
            "workspace": "chroma",
            "collection_name": collection_name,
            "collection_count": count,
            "collection_metadata": metadata,
            "collection_metadata_json": json.dumps(metadata, sort_keys=True, indent=2)
            if metadata
            else "{}",
            "chroma_host": host,
            "chroma_port": port,
            "chroma_ssl": "enabled" if _as_bool(chroma_settings.get("ssl")) else "disabled",
            "chroma_normalized_hint": normalized_hint,
        }
    return render_template(
        "chroma_collection_detail.html",
        collection_name=collection_name,
        collection_count=count,
        collection_metadata=metadata,
        collection_metadata_json=json.dumps(metadata, sort_keys=True, indent=2)
        if metadata
        else "{}",
        chroma_host=host,
        chroma_port=port,
        chroma_ssl="enabled" if _as_bool(chroma_settings.get("ssl")) else "disabled",
        chroma_normalized_hint=normalized_hint,
        page_title=f"ChromaDB - {collection_name}",
        active_page="chroma",
    )

@bp.post("/chroma/collections/delete")
def delete_chroma_collection():
    is_api_request = _workflow_api_request()
    payload = request.get_json(silent=True) if request.is_json else {}
    if payload is None or not isinstance(payload, dict):
        payload = {}
    collection_name = (
        str(payload.get("collection_name") or "").strip()
        if is_api_request
        else request.form.get("collection_name", "").strip()
    )
    next_page = (
        str(payload.get("next") or "").strip().lower()
        if is_api_request
        else request.form.get("next", "").strip().lower()
    )
    if not collection_name:
        if is_api_request:
            return {"error": "Collection name is required."}, 400
        flash("Collection name is required.", "error")
        return redirect(url_for("agents.chroma_collections"))

    chroma_settings = _resolved_chroma_settings()
    if not _chroma_connected(chroma_settings):
        if is_api_request:
            return {"error": "Configure ChromaDB host and port in Integrations first."}, 400
        flash("Configure ChromaDB host and port in Integrations first.", "error")
        return redirect(url_for("agents.settings_integrations_chroma"))

    client, host, port, _, error = _chroma_http_client(chroma_settings)
    if error or client is None:
        if is_api_request:
            return {
                "error": f"Failed to connect to Chroma at {_chroma_endpoint_label(host, port)}: {error}"
            }, 502
        flash(
            f"Failed to connect to Chroma at {_chroma_endpoint_label(host, port)}: {error}",
            "error",
        )
        if next_page == "detail":
            return redirect(
                url_for("agents.chroma_collection_detail", name=collection_name)
            )
        return redirect(url_for("agents.chroma_collections"))

    try:
        client.delete_collection(name=collection_name)
    except Exception as exc:
        if is_api_request:
            return {"error": f"Failed to delete collection '{collection_name}': {exc}"}, 502
        flash(f"Failed to delete collection '{collection_name}': {exc}", "error")
        if next_page == "detail":
            return redirect(
                url_for("agents.chroma_collection_detail", name=collection_name)
            )
        return redirect(url_for("agents.chroma_collections"))

    if is_api_request:
        return {"ok": True, "collection_name": collection_name}
    flash("Collection deleted.", "success")
    return redirect(url_for("agents.chroma_collections"))

@bp.get("/settings/integrations/git")
def settings_integrations_git():
    sync_integrated_mcp_servers()
    return _render_settings_integrations_page("git")

@bp.post("/settings/integrations/git")
def update_integrations_gitconfig():
    gitconfig_path = _gitconfig_path()
    request_payload = _settings_request_payload()
    is_api_request = _workflow_api_request()
    gitconfig_content = _settings_form_value(request_payload, "gitconfig_content")
    try:
        gitconfig_path.write_text(gitconfig_content, encoding="utf-8")
    except OSError as exc:
        if is_api_request:
            return {"error": f"Unable to write {gitconfig_path}: {exc}"}, 500
        flash(f"Unable to write {gitconfig_path}: {exc}", "error")
        return _render_settings_integrations_page(
            "git",
            gitconfig_content=gitconfig_content,
        )
    if is_api_request:
        return {
            "ok": True,
            "gitconfig_path": str(gitconfig_path),
            "gitconfig_exists": gitconfig_path.exists(),
            "gitconfig_content": gitconfig_content,
        }
    flash("Git config saved.", "success")
    return redirect(url_for("agents.settings_integrations_git"))

@bp.get("/settings/integrations")
def settings_integrations():
    return redirect(url_for("agents.settings_integrations_git"))

@bp.get("/settings/integrations/github")
def settings_integrations_github():
    sync_integrated_mcp_servers()
    return _render_settings_integrations_page("github")

@bp.get("/settings/integrations/jira")
def settings_integrations_jira():
    sync_integrated_mcp_servers()
    return _render_settings_integrations_page("jira")

@bp.get("/settings/integrations/confluence")
def settings_integrations_confluence():
    sync_integrated_mcp_servers()
    return _render_settings_integrations_page("confluence")

@bp.get("/settings/integrations/google-drive")
def settings_integrations_google_drive():
    return redirect(url_for("agents.settings_integrations_google_cloud"))

@bp.get("/settings/integrations/google-cloud")
def settings_integrations_google_cloud():
    sync_integrated_mcp_servers()
    return _render_settings_integrations_page("google_cloud")

@bp.get("/settings/integrations/google-workspace")
def settings_integrations_google_workspace():
    sync_integrated_mcp_servers()
    return _render_settings_integrations_page("google_workspace")

@bp.get("/settings/integrations/huggingface")
def settings_integrations_huggingface():
    sync_integrated_mcp_servers()
    return _render_settings_integrations_page("huggingface")

@bp.get("/settings/integrations/chroma")
def settings_integrations_chroma():
    sync_integrated_mcp_servers()
    return _render_settings_integrations_page("chroma")

@bp.get("/settings/integrations/rag")
def settings_integrations_rag():
    return redirect(url_for("agents.settings_runtime_rag"))

@bp.post("/settings/integrations/github")
def update_github_settings():
    request_payload = _settings_request_payload()
    is_api_request = _workflow_api_request()
    action = _settings_form_value(request_payload, "action").strip()
    pat = _settings_form_value(request_payload, "github_pat").strip()
    current_settings = _load_integration_settings("github")
    existing_key_path = (current_settings.get("ssh_key_path") or "").strip()
    uploaded_key = request.files.get("github_ssh_key")
    clear_key = _as_bool(_settings_form_value(request_payload, "github_ssh_key_clear"))
    logger.info(
        "GitHub settings update action=%s has_pat=%s has_repo=%s",
        action or "save",
        bool(pat),
        "github_repo" in request.form or "github_repo" in request_payload,
    )
    payload = {"pat": pat}
    if "github_repo" in request.form or "github_repo" in request_payload:
        payload["repo"] = _settings_form_value(request_payload, "github_repo").strip()
    if clear_key and existing_key_path:
        existing_path = Path(existing_key_path)
        try:
            if existing_path.is_file() and Path(Config.SSH_KEYS_DIR) in existing_path.parents:
                existing_path.unlink()
        except OSError:
            logger.warning("Failed to remove GitHub SSH key at %s", existing_key_path)
        payload["ssh_key_path"] = ""
        if not is_api_request:
            flash("GitHub SSH key removed.", "success")
    elif uploaded_key and uploaded_key.filename:
        key_bytes = uploaded_key.read()
        if not key_bytes:
            if is_api_request:
                return {"error": "Uploaded SSH key is empty."}, 400
            flash("Uploaded SSH key is empty.", "error")
        elif len(key_bytes) > 256 * 1024:
            if is_api_request:
                return {"error": "SSH key is too large."}, 400
            flash("SSH key is too large.", "error")
        else:
            key_path = Path(Config.SSH_KEYS_DIR) / "github_ssh_key.pem"
            try:
                key_path.write_bytes(key_bytes)
                key_path.chmod(0o600)
                payload["ssh_key_path"] = str(key_path)
                if not is_api_request:
                    flash("GitHub SSH key uploaded.", "success")
            except OSError as exc:
                logger.warning("Failed to save GitHub SSH key: %s", exc)
                if is_api_request:
                    return {"error": "Unable to save GitHub SSH key."}, 500
                flash("Unable to save GitHub SSH key.", "error")
    _save_integration_settings("github", payload)
    sync_integrated_mcp_servers()
    if action == "refresh":
        repo_options: list[str] = []
        if pat:
            try:
                logger.info("GitHub refresh: requesting repositories")
                repo_options = _fetch_github_repos(pat)
                if is_api_request:
                    return {
                        "ok": True,
                        "github_repo_options": repo_options,
                        "github_settings": _load_integration_settings("github"),
                    }
                if repo_options:
                    logger.info("GitHub refresh: loaded %s repositories", len(repo_options))
                    flash(f"Loaded {len(repo_options)} repositories.", "success")
                else:
                    logger.info("GitHub refresh: no repositories returned")
                    flash("No repositories returned for this PAT.", "info")
            except ValueError as exc:
                logger.warning("GitHub refresh: failed with error=%s", exc)
                if is_api_request:
                    return {"error": str(exc)}, 400
                flash(str(exc), "error")
        else:
            logger.info("GitHub refresh: missing PAT")
            if is_api_request:
                return {"error": "GitHub PAT is required to refresh repositories."}, 400
            flash("GitHub PAT is required to refresh repositories.", "error")
        if is_api_request:
            return {
                "ok": True,
                "github_repo_options": repo_options,
                "github_settings": _load_integration_settings("github"),
            }
        return _render_settings_integrations_page(
            "github",
            github_repo_options=repo_options,
        )
    if is_api_request:
        return {
            "ok": True,
            "github_settings": _load_integration_settings("github"),
        }
    flash("GitHub settings updated.", "success")
    return redirect(url_for("agents.settings_integrations_github"))

@bp.post("/settings/integrations/google-drive")
def update_google_drive_settings():
    return update_google_cloud_settings()

@bp.post("/settings/integrations/google-cloud")
def update_google_cloud_settings():
    request_payload = _settings_request_payload()
    is_api_request = _workflow_api_request()
    service_account_json = _settings_form_value(
        request_payload,
        "google_cloud_service_account_json",
    ).strip()
    if not service_account_json:
        service_account_json = _settings_form_value(
            request_payload,
            "google_drive_service_account_json",
        ).strip()
    google_cloud_project_id = _settings_form_value(
        request_payload,
        "google_cloud_project_id",
    ).strip()
    if google_cloud_project_id and any(char.isspace() for char in google_cloud_project_id):
        if is_api_request:
            return {"error": "Google Cloud project ID cannot contain spaces."}, 400
        flash("Google Cloud project ID cannot contain spaces.", "error")
        return redirect(url_for("agents.settings_integrations_google_cloud"))

    if service_account_json:
        try:
            _google_drive_service_account_email(service_account_json)
        except ValueError as exc:
            if is_api_request:
                return {"error": str(exc)}, 400
            flash(str(exc), "error")
            return redirect(url_for("agents.settings_integrations_google_cloud"))

    _save_integration_settings(
        GOOGLE_CLOUD_PROVIDER,
        {
            "service_account_json": service_account_json,
            "google_cloud_project_id": google_cloud_project_id,
            # Remove deprecated manual MCP toggle; MCP activation is credential-driven.
            "google_cloud_mcp_enabled": "",
        },
    )
    sync_integrated_mcp_servers()
    if is_api_request:
        return {
            "ok": True,
            "google_cloud_settings": _load_integration_settings(GOOGLE_CLOUD_PROVIDER),
        }
    flash("Google Cloud settings updated.", "success")
    return redirect(url_for("agents.settings_integrations_google_cloud"))

@bp.post("/settings/integrations/google-workspace")
def update_google_workspace_settings():
    request_payload = _settings_request_payload()
    is_api_request = _workflow_api_request()
    service_account_json = _settings_form_value(
        request_payload,
        "workspace_service_account_json",
    ).strip()
    delegated_user_email = _settings_form_value(
        request_payload,
        "workspace_delegated_user_email",
    ).strip()
    if delegated_user_email and any(char.isspace() for char in delegated_user_email):
        if is_api_request:
            return {"error": "Workspace delegated user email cannot contain spaces."}, 400
        flash("Workspace delegated user email cannot contain spaces.", "error")
        return redirect(url_for("agents.settings_integrations_google_workspace"))

    if service_account_json:
        try:
            _google_drive_service_account_email(service_account_json)
        except ValueError as exc:
            if is_api_request:
                return {"error": str(exc)}, 400
            flash(str(exc), "error")
            return redirect(url_for("agents.settings_integrations_google_workspace"))

    _save_integration_settings(
        GOOGLE_WORKSPACE_PROVIDER,
        {
            "service_account_json": service_account_json,
            "workspace_delegated_user_email": delegated_user_email,
            # Remove deprecated manual MCP toggle; MCP activation is credential-driven.
            "google_workspace_mcp_enabled": "",
        },
    )
    sync_integrated_mcp_servers()
    if is_api_request:
        return {
            "ok": True,
            "google_workspace_settings": _load_integration_settings(
                GOOGLE_WORKSPACE_PROVIDER
            ),
        }
    flash("Google Workspace settings updated.", "success")
    return redirect(url_for("agents.settings_integrations_google_workspace"))

@bp.post("/settings/integrations/huggingface")
def update_huggingface_settings():
    request_payload = _settings_request_payload()
    is_api_request = _workflow_api_request()
    token = _settings_form_value(request_payload, "vllm_local_hf_token")
    _save_integration_settings("llm", {"vllm_local_hf_token": token})
    if is_api_request:
        return {"ok": True}
    flash("HuggingFace settings updated.", "success")
    return redirect(url_for("agents.settings_integrations_huggingface"))

@bp.post("/settings/integrations/chroma")
def update_chroma_settings():
    request_payload = _settings_request_payload()
    is_api_request = _workflow_api_request()
    host = _settings_form_value(request_payload, "chroma_host").strip()
    port = _settings_form_value(request_payload, "chroma_port").strip()
    ssl = "true" if _as_bool(_settings_form_value(request_payload, "chroma_ssl")) else "false"
    normalized_hint = None
    if port:
        try:
            parsed_port = int(port)
        except ValueError:
            if is_api_request:
                return {"error": "Chroma port must be a number between 1 and 65535."}, 400
            flash("Chroma port must be a number between 1 and 65535.", "error")
            return redirect(url_for("agents.settings_integrations_chroma"))
        if parsed_port < 1 or parsed_port > 65535:
            if is_api_request:
                return {"error": "Chroma port must be a number between 1 and 65535."}, 400
            flash("Chroma port must be a number between 1 and 65535.", "error")
            return redirect(url_for("agents.settings_integrations_chroma"))
        if host:
            host, parsed_port, normalized_hint = _normalize_chroma_target(host, parsed_port)
        port = str(parsed_port)
    _save_integration_settings(
        "chroma",
        {
            "host": host,
            "port": port,
            "ssl": ssl,
        },
    )
    sync_integrated_mcp_servers()
    if is_api_request:
        return {
            "ok": True,
            "normalized_hint": normalized_hint or "",
            "chroma_settings": _resolved_chroma_settings(),
        }
    if normalized_hint:
        flash(normalized_hint, "info")
    flash("ChromaDB settings updated.", "success")
    return redirect(url_for("agents.settings_integrations_chroma"))

@bp.post("/settings/integrations/jira")
def update_jira_settings():
    request_payload = _settings_request_payload()
    is_api_request = _workflow_api_request()
    existing_settings = _load_integration_settings("jira")
    action = _settings_form_value(request_payload, "action").strip()
    api_key = (
        _settings_form_value(request_payload, "jira_api_key").strip()
        if "jira_api_key" in request.form or "jira_api_key" in request_payload
        else (existing_settings.get("api_key") or "").strip()
    )
    email = (
        _settings_form_value(request_payload, "jira_email").strip()
        if "jira_email" in request.form or "jira_email" in request_payload
        else (existing_settings.get("email") or "").strip()
    )
    site = (
        _settings_form_value(request_payload, "jira_site").strip()
        if "jira_site" in request.form or "jira_site" in request_payload
        else (existing_settings.get("site") or "").strip()
    )
    project_key = (
        _settings_form_value(request_payload, "jira_project_key").strip()
        if "jira_project_key" in request.form or "jira_project_key" in request_payload
        else (existing_settings.get("project_key") or "").strip()
    )
    has_board = "jira_board" in request.form or "jira_board" in request_payload
    board = (
        _settings_form_value(request_payload, "jira_board").strip()
        if has_board
        else (existing_settings.get("board") or "").strip()
    )
    has_board_label = (
        "jira_board_label" in request.form or "jira_board_label" in request_payload
    )
    board_label = (
        _settings_form_value(request_payload, "jira_board_label").strip()
        if has_board_label
        else (existing_settings.get("board_label") or "").strip()
    )
    if not board:
        board_label = ""
    logger.info(
        "Jira settings update action=%s key_len=%s key_has_colon=%s email_domain=%s site_host=%s has_board=%s",
        action or "save",
        len(api_key),
        ":" in api_key,
        _safe_email_domain(email),
        _safe_site_label(site),
        has_board,
    )
    payload = {
        "api_key": api_key,
        "email": email,
        "site": site,
        "project_key": project_key,
        "board": board,
        "board_label": board_label,
    }
    _save_integration_settings("jira", payload)
    sync_integrated_mcp_servers()
    if action == "refresh":
        refreshed_settings = _load_integration_settings("jira")
        board_options: list[dict[str, str]] = _jira_board_options(refreshed_settings)
        project_options: list[dict[str, str]] = _jira_project_options(refreshed_settings)
        cache_updates: dict[str, str] = {}
        if api_key and site:
            try:
                auth_key = _combine_atlassian_key(api_key, email)
                email_valid = True
                if email and "@" not in email:
                    email_valid = False
                    if is_api_request:
                        return {
                            "error": "Jira email must include a full address (name@domain)."
                        }, 400
                    flash(
                        "Jira email must include a full address (name@domain).",
                        "error",
                    )
                needs_email = ":" not in auth_key
                if needs_email:
                    if is_api_request:
                        return {
                            "error": "Jira API key needs an Atlassian email. Enter it above or use email:token."
                        }, 400
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
                        cache_updates["project_options"] = _serialize_option_entries(
                            project_options
                        )
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
                            cache_updates["board_options"] = _serialize_option_entries(
                                board_options
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
                if is_api_request:
                    return {"error": str(exc)}, 400
                flash(str(exc), "error")
        else:
            logger.info("Jira refresh: missing api key or site")
            if is_api_request:
                return {
                    "error": "Jira API key and site URL are required to refresh projects and boards."
                }, 400
            flash(
                "Jira API key and site URL are required to refresh projects and boards.",
                "error",
            )
        selected_board_option: dict[str, str] | None = None
        if project_key and all(
            option.get("value") != project_key for option in project_options
        ):
            project_options.insert(
                0, {"value": project_key, "label": project_key}
            )
        if board and board_options:
            for option in board_options:
                if option.get("value") == board:
                    selected_board_option = option
                    break
            if selected_board_option is None:
                for option in board_options:
                    label = (option.get("label") or "").strip()
                    if label == board or label.startswith(f"{board} ("):
                        candidate_value = (option.get("value") or "").strip()
                        if candidate_value:
                            board = candidate_value
                            selected_board_option = option
                            cache_updates["board"] = board
                        break
        if selected_board_option is not None:
            selected_board_label = (
                (selected_board_option.get("label") or "").strip()
                or (selected_board_option.get("value") or "").strip()
            )
            if selected_board_label and selected_board_label != board_label:
                board_label = selected_board_label
                cache_updates["board_label"] = selected_board_label
        elif board:
            fallback_label = board_label or board
            if all(option.get("value") != board for option in board_options):
                board_options.insert(
                    0,
                    {
                        "value": board,
                        "label": fallback_label,
                    },
                )
        if cache_updates:
            _save_integration_settings("jira", cache_updates)
        refreshed_settings = _load_integration_settings("jira")
        if not project_options:
            project_options = _jira_project_options(refreshed_settings)
        else:
            project_options = _merge_selected_option(
                project_options, refreshed_settings.get("project_key")
            )
        if not board_options:
            board_options = _jira_board_options(refreshed_settings)
        else:
            selected_board = (refreshed_settings.get("board") or "").strip()
            selected_label = (
                (refreshed_settings.get("board_label") or "").strip()
                or selected_board
            )
            if selected_board and all(
                option.get("value") != selected_board for option in board_options
            ):
                board_options.insert(
                    0,
                    {"value": selected_board, "label": selected_label},
                )
        if is_api_request:
            return {
                "ok": True,
                "jira_project_options": project_options,
                "jira_board_options": board_options,
                "jira_settings": refreshed_settings,
            }
        return _render_settings_integrations_page(
            "jira",
            jira_project_options=project_options,
            jira_board_options=board_options,
        )
    if is_api_request:
        return {
            "ok": True,
            "jira_settings": _load_integration_settings("jira"),
        }
    flash("Jira settings updated.", "success")
    return redirect(url_for("agents.settings_integrations_jira"))

@bp.post("/settings/integrations/confluence")
def update_confluence_settings():
    request_payload = _settings_request_payload()
    is_api_request = _workflow_api_request()
    action = _settings_form_value(request_payload, "action").strip()
    existing_settings = _load_integration_settings("confluence")
    jira_settings = _load_integration_settings("jira")
    jira_site = _normalize_confluence_site((jira_settings.get("site") or "").strip())
    api_key = (
        _settings_form_value(request_payload, "confluence_api_key").strip()
        if "confluence_api_key" in request.form or "confluence_api_key" in request_payload
        else (existing_settings.get("api_key") or jira_settings.get("api_key") or "").strip()
    )
    email = (
        _settings_form_value(request_payload, "confluence_email").strip()
        if "confluence_email" in request.form or "confluence_email" in request_payload
        else (existing_settings.get("email") or jira_settings.get("email") or "").strip()
    )
    site = (
        _settings_form_value(request_payload, "confluence_site").strip()
        if "confluence_site" in request.form or "confluence_site" in request_payload
        else (existing_settings.get("site") or jira_site or "").strip()
    )
    site = _normalize_confluence_site(site)
    configured_space = (
        _settings_form_value(request_payload, "confluence_space").strip()
        if "confluence_space" in request.form or "confluence_space" in request_payload
        else (existing_settings.get("space") or "").strip()
    )
    logger.info(
        "Confluence settings update action=%s key_len=%s key_has_colon=%s email_domain=%s site_host=%s has_space=%s",
        action or "save",
        len(api_key),
        ":" in api_key,
        _safe_email_domain(email),
        _safe_site_label(site),
        "confluence_space" in request.form,
    )
    payload = {
        "api_key": api_key,
        "email": email,
        "site": site,
        "space": configured_space,
    }
    _save_integration_settings("confluence", payload)
    sync_integrated_mcp_servers()
    if action == "refresh":
        space_options: list[dict[str, str]] = []
        cache_payload: str | None = None
        if api_key and site:
            try:
                auth_key = _combine_atlassian_key(api_key, email)
                email_valid = True
                if email and "@" not in email:
                    email_valid = False
                    if is_api_request:
                        return {
                            "error": "Confluence email must include a full address (name@domain)."
                        }, 400
                    flash(
                        "Confluence email must include a full address (name@domain).",
                        "error",
                    )
                needs_email = ":" not in auth_key
                if needs_email:
                    if is_api_request:
                        return {
                            "error": "Confluence API key needs an Atlassian email. Enter it above or use email:token."
                        }, 400
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
                    cache_payload = _serialize_option_entries(space_options)
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
                if is_api_request:
                    return {"error": str(exc)}, 400
                flash(str(exc), "error")
        else:
            logger.info("Confluence refresh: missing api key or site")
            if is_api_request:
                return {
                    "error": "Confluence API key and site URL are required to refresh spaces."
                }, 400
            flash(
                "Confluence API key and site URL are required to refresh spaces.",
                "error",
            )
        if cache_payload is not None:
            _save_integration_settings("confluence", {"space_options": cache_payload})
        confluence_settings = _load_integration_settings("confluence")
        if not space_options:
            space_options = _confluence_space_options(confluence_settings)
        else:
            space_options = _merge_selected_option(
                space_options, confluence_settings.get("space")
            )
        if is_api_request:
            return {
                "ok": True,
                "confluence_space_options": space_options,
                "confluence_settings": confluence_settings,
            }
        return _render_settings_integrations_page(
            "confluence",
            confluence_space_options=space_options,
        )
    if is_api_request:
        return {
            "ok": True,
            "confluence_settings": _load_integration_settings("confluence"),
        }
    flash("Confluence settings updated.", "success")
    return redirect(url_for("agents.settings_integrations_confluence"))
