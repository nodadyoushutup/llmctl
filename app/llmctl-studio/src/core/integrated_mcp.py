from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import Config
from core.db import session_scope
from core.mcp_config import render_mcp_config
from core.models import (
    IntegrationSetting,
    MCP_SERVER_TYPE_INTEGRATED,
    MCPServer,
)

INTEGRATED_MCP_LLMCTL_KEY = "llmctl-mcp"
INTEGRATED_MCP_GITHUB_KEY = "github"
INTEGRATED_MCP_ATLASSIAN_KEY = "atlassian"
INTEGRATED_MCP_CHROMA_KEY = "chroma"
INTEGRATED_MCP_GOOGLE_CLOUD_KEY = "google-cloud"
INTEGRATED_MCP_GOOGLE_WORKSPACE_KEY = "google-workspace"
LEGACY_ATLASSIAN_KEY = "jira"
DOCKER_CHROMA_HOST_ALIASES = {"llmctl-chromadb", "chromadb"}
GOOGLE_CLOUD_SERVICE_ACCOUNT_FILE = (
    Path(Config.DATA_DIR) / "credentials" / "google-cloud-service-account.json"
)
logger = logging.getLogger(__name__)


def sync_integrated_mcp_servers() -> dict[str, int]:
    with session_scope() as session:
        return sync_integrated_mcp_servers_in_session(session)


def sync_integrated_mcp_servers_in_session(session: Session) -> dict[str, int]:
    summary = {"created": 0, "updated": 0, "deleted": 0}
    desired = _desired_integrated_server_payloads(session)
    existing = {
        server.server_key: server
        for server in session.execute(select(MCPServer)).scalars().all()
    }

    legacy = existing.get(LEGACY_ATLASSIAN_KEY)
    if legacy is not None:
        atlassian = existing.get(INTEGRATED_MCP_ATLASSIAN_KEY)
        if atlassian is None:
            legacy.server_key = INTEGRATED_MCP_ATLASSIAN_KEY
            legacy.name = "Atlassian MCP"
            existing.pop(LEGACY_ATLASSIAN_KEY, None)
            existing[INTEGRATED_MCP_ATLASSIAN_KEY] = legacy
            summary["updated"] += 1
        else:
            if legacy.agents:
                legacy.agents = []
            session.delete(legacy)
            existing.pop(LEGACY_ATLASSIAN_KEY, None)
            summary["deleted"] += 1

    for key in (
        INTEGRATED_MCP_GITHUB_KEY,
        INTEGRATED_MCP_ATLASSIAN_KEY,
        INTEGRATED_MCP_CHROMA_KEY,
        INTEGRATED_MCP_GOOGLE_CLOUD_KEY,
        INTEGRATED_MCP_GOOGLE_WORKSPACE_KEY,
    ):
        if key in desired:
            continue
        server = existing.get(key)
        if server is None:
            continue
        if server.agents:
            server.agents = []
        session.delete(server)
        existing.pop(key, None)
        summary["deleted"] += 1

    for key, payload in desired.items():
        server = existing.get(key)
        config_json = render_mcp_config(key, payload["config"])
        if server is None:
            MCPServer.create(
                session,
                name=payload["name"],
                server_key=key,
                description=payload["description"],
                config_json=config_json,
                server_type=MCP_SERVER_TYPE_INTEGRATED,
            )
            summary["created"] += 1
            continue

        changed = False
        if server.name != payload["name"]:
            server.name = payload["name"]
            changed = True
        if server.description != payload["description"]:
            server.description = payload["description"]
            changed = True
        if (server.server_type or "").strip().lower() != MCP_SERVER_TYPE_INTEGRATED:
            server.server_type = MCP_SERVER_TYPE_INTEGRATED
            changed = True
        if (server.config_json or "").strip() != config_json.strip():
            server.config_json = config_json
            changed = True
        if changed:
            summary["updated"] += 1

    return summary


def _desired_integrated_server_payloads(
    session: Session,
) -> dict[str, dict[str, Any]]:
    github = _load_provider_settings(session, "github")
    jira = _load_provider_settings(session, "jira")
    confluence = _load_provider_settings(session, "confluence")
    chroma = _load_provider_settings(session, "chroma")
    google_cloud = _load_provider_settings(session, "google_cloud")
    if not google_cloud:
        google_cloud = _load_provider_settings(session, "google_drive")
    google_workspace = _load_provider_settings(session, "google_workspace")

    payload: dict[str, dict[str, Any]] = {
        INTEGRATED_MCP_LLMCTL_KEY: {
            "name": "LLMCTL MCP",
            "description": "System-provided llmctl MCP server bundled with Studio.",
            "config": _llmctl_config(),
        }
    }

    github_pat = _clean(github.get("pat"))
    if github_pat:
        payload[INTEGRATED_MCP_GITHUB_KEY] = {
            "name": "GitHub MCP",
            "description": "System-managed GitHub MCP server from Integration settings.",
            "config": _github_config(github_pat),
        }

    atlassian_env = _atlassian_env(jira, confluence)
    if atlassian_env:
        payload[INTEGRATED_MCP_ATLASSIAN_KEY] = {
            "name": "Atlassian MCP",
            "description": "System-managed Atlassian MCP server from Jira/Confluence settings.",
            "config": _atlassian_config(atlassian_env),
        }

    chroma_host, chroma_port, chroma_ssl = _resolved_chroma_settings(chroma)
    if chroma_host and chroma_port is not None:
        payload[INTEGRATED_MCP_CHROMA_KEY] = {
            "name": "Chroma MCP",
            "description": "System-managed Chroma MCP server from ChromaDB integration settings.",
            "config": _chroma_config(
                host=chroma_host,
                port=chroma_port,
                ssl=chroma_ssl,
            ),
        }

    google_cloud_mcp_enabled = _as_bool_default(
        google_cloud.get("google_cloud_mcp_enabled"), default=True
    )
    google_cloud_project_id = _clean(google_cloud.get("google_cloud_project_id"))
    if google_cloud_mcp_enabled:
        credentials_path = _write_google_cloud_service_account_file(
            google_cloud.get("service_account_json")
        )
        if credentials_path is not None:
            payload[INTEGRATED_MCP_GOOGLE_CLOUD_KEY] = {
                "name": "Google Cloud MCP",
                "description": (
                    "System-managed Google Cloud MCP server from Google Cloud integration settings."
                ),
                "config": _google_cloud_config(
                    credentials_path=credentials_path,
                    project_id=google_cloud_project_id,
                ),
            }
    else:
        _remove_google_cloud_service_account_file(GOOGLE_CLOUD_SERVICE_ACCOUNT_FILE)

    google_workspace_mcp_enabled = _as_bool_default(
        google_workspace.get("google_workspace_mcp_enabled"),
        default=False,
    )
    google_workspace_service_account_json = _clean(
        google_workspace.get("service_account_json")
    )
    if google_workspace_mcp_enabled and google_workspace_service_account_json:
        logger.info(
            "Google Workspace MCP requested but runtime activation is guarded "
            "until a supported service-account server path is finalized."
        )

    return payload


def _load_provider_settings(session: Session, provider: str) -> dict[str, str]:
    rows = (
        session.execute(
            select(IntegrationSetting).where(IntegrationSetting.provider == provider)
        )
        .scalars()
        .all()
    )
    return {row.key: row.value for row in rows}


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _as_bool(value: str | None) -> bool:
    return _clean(value).lower() in {"1", "true", "yes", "on"}


def _as_bool_default(value: str | None, *, default: bool) -> bool:
    raw = _clean(value).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _parse_port(value: str | None) -> int | None:
    raw = _clean(value)
    if not raw:
        return None
    try:
        port = int(raw)
    except ValueError:
        return None
    if port < 1 or port > 65535:
        return None
    return port


def _normalize_chroma_target(host: str, port: int) -> tuple[str, int, str | None]:
    if host.lower() in DOCKER_CHROMA_HOST_ALIASES and port != 8000:
        return (
            "llmctl-chromadb",
            8000,
            "Using llmctl-chromadb:8000 inside Docker. Host-mapped ports are for host access only.",
        )
    if host.lower() in DOCKER_CHROMA_HOST_ALIASES:
        return "llmctl-chromadb", port, None
    return host, port, None


def _resolved_chroma_settings(chroma: dict[str, str]) -> tuple[str, int | None, bool]:
    host = _clean(chroma.get("host")) or _clean(Config.CHROMA_HOST)
    port_raw = _clean(chroma.get("port")) or _clean(Config.CHROMA_PORT)
    port = _parse_port(port_raw)
    if host and port is not None:
        host, port, _ = _normalize_chroma_target(host, port)
    ssl_raw = _clean(chroma.get("ssl"))
    if not ssl_raw:
        ssl_raw = _clean(Config.CHROMA_SSL)
    return host, port, _as_bool(ssl_raw)


def _llmctl_config() -> dict[str, Any]:
    run_path = Path(__file__).resolve().parents[4] / "app" / "llmctl-mcp" / "run.py"
    return {
        "command": "python3",
        "args": [str(run_path)],
        "env": {"LLMCTL_MCP_TRANSPORT": "stdio"},
    }


def _github_config(pat: str) -> dict[str, Any]:
    return {
        "command": "mcp-server-github",
        "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": pat},
    }


def _atlassian_config(env: dict[str, str]) -> dict[str, Any]:
    return {
        "command": "mcp-atlassian",
        "args": ["--transport", "stdio"],
        "env": {key: env[key] for key in sorted(env)},
    }


def _chroma_config(*, host: str, port: int, ssl: bool) -> dict[str, Any]:
    wrapper_path = Path(__file__).resolve().parent / "chroma_mcp_stdio_wrapper.py"
    return {
        "command": "python3",
        "args": [
            str(wrapper_path),
            "--client-type",
            "http",
            "--host",
            host,
            "--port",
            str(port),
            "--ssl",
            "true" if ssl else "false",
        ],
    }


def _google_cloud_config(
    *,
    credentials_path: Path,
    project_id: str,
) -> dict[str, Any]:
    env = {
        "GOOGLE_APPLICATION_CREDENTIALS": str(credentials_path),
        "CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE": str(credentials_path),
    }
    if project_id:
        env["GOOGLE_CLOUD_PROJECT"] = project_id
        env["GCP_PROJECT_ID"] = project_id
        env["CLOUDSDK_CORE_PROJECT"] = project_id
    return {
        "command": "gcloud-mcp",
        "env": {key: env[key] for key in sorted(env)},
    }


def _write_google_cloud_service_account_file(raw_json: str | None) -> Path | None:
    cleaned = _clean(raw_json)
    target = GOOGLE_CLOUD_SERVICE_ACCOUNT_FILE
    if not cleaned:
        _remove_google_cloud_service_account_file(target)
        return None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("Google Cloud service account JSON is invalid; skipping MCP setup.")
        _remove_google_cloud_service_account_file(target)
        return None
    if not isinstance(parsed, dict):
        logger.warning(
            "Google Cloud service account JSON must be an object; skipping MCP setup."
        )
        _remove_google_cloud_service_account_file(target)
        return None
    normalized = json.dumps(parsed, sort_keys=True, indent=2) + "\n"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(normalized, encoding="utf-8")
        target.chmod(0o600)
    except OSError as exc:
        logger.warning(
            "Unable to persist Google Cloud service account file at %s: %s",
            target,
            exc,
        )
        return None
    return target


def _remove_google_cloud_service_account_file(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError as exc:
        logger.warning(
            "Unable to remove Google Cloud service account file at %s: %s",
            path,
            exc,
        )


def _credential_parts(api_key: str, email: str) -> tuple[str, str]:
    if ":" in api_key:
        username, token = api_key.split(":", 1)
        return _clean(username) or _clean(email), _clean(token)
    return _clean(email), _clean(api_key)


def _atlassian_env(
    jira: dict[str, str],
    confluence: dict[str, str],
) -> dict[str, str]:
    env: dict[str, str] = {}

    jira_site = _clean(jira.get("site"))
    jira_user, jira_token = _credential_parts(
        _clean(jira.get("api_key")),
        _clean(jira.get("email")),
    )
    if jira_site and jira_user and jira_token:
        env["JIRA_URL"] = jira_site
        env["JIRA_USERNAME"] = jira_user
        env["JIRA_API_TOKEN"] = jira_token

    confluence_site = _clean(confluence.get("site"))
    confluence_user, confluence_token = _credential_parts(
        _clean(confluence.get("api_key")),
        _clean(confluence.get("email")),
    )
    if confluence_site and confluence_user and confluence_token:
        env["CONFLUENCE_URL"] = confluence_site
        env["CONFLUENCE_USERNAME"] = confluence_user
        env["CONFLUENCE_API_TOKEN"] = confluence_token

    return env
