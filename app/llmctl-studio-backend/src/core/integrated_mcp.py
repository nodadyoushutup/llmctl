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
INTEGRATED_MCP_TRANSPORT = "streamable-http"
INTEGRATED_MCP_PATH = "/mcp"
INTEGRATED_MCP_SERVICE_ENDPOINTS: dict[str, tuple[str, int]] = {
    INTEGRATED_MCP_LLMCTL_KEY: ("llmctl-mcp", 9020),
    INTEGRATED_MCP_GITHUB_KEY: ("llmctl-mcp-github", 8000),
    INTEGRATED_MCP_ATLASSIAN_KEY: ("llmctl-mcp-atlassian", 8000),
    INTEGRATED_MCP_CHROMA_KEY: ("llmctl-mcp-chroma", 8000),
    INTEGRATED_MCP_GOOGLE_CLOUD_KEY: ("llmctl-mcp-google-cloud", 8000),
    INTEGRATED_MCP_GOOGLE_WORKSPACE_KEY: ("llmctl-mcp-google-workspace", 8000),
}
DOCKER_CHROMA_HOST_ALIASES = {"llmctl-chromadb", "chromadb"}
GOOGLE_CLOUD_SERVICE_ACCOUNT_FILE = (
    Path(Config.DATA_DIR) / "credentials" / "google-cloud-service-account.json"
)
GOOGLE_WORKSPACE_SERVICE_ACCOUNT_FILE = (
    Path(Config.DATA_DIR) / "credentials" / "google-workspace-service-account.json"
)
GOOGLE_WORKSPACE_IMPERSONATE_USER_FILE = (
    Path(Config.DATA_DIR) / "credentials" / "google-workspace-impersonate-user.txt"
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
        if server.config_json != config_json:
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
            "description": "System-managed llmctl MCP server hosted in Kubernetes.",
            "config": _llmctl_config(),
        }
    }

    github_pat = _clean(github.get("pat"))
    if github_pat:
        payload[INTEGRATED_MCP_GITHUB_KEY] = {
            "name": "GitHub MCP",
            "description": "System-managed GitHub MCP server from Integration settings.",
            "config": _github_config(),
        }

    atlassian_env = _atlassian_env(jira, confluence)
    if atlassian_env:
        payload[INTEGRATED_MCP_ATLASSIAN_KEY] = {
            "name": "Atlassian MCP",
            "description": "System-managed Atlassian MCP server from Jira/Confluence settings.",
            "config": _atlassian_config(),
        }

    chroma_host, chroma_port, _ = _resolved_chroma_settings(chroma)
    if chroma_host and chroma_port is not None:
        payload[INTEGRATED_MCP_CHROMA_KEY] = {
            "name": "Chroma MCP",
            "description": "System-managed Chroma MCP server from ChromaDB integration settings.",
            "config": _chroma_config(),
        }

    credentials_path = _write_google_cloud_service_account_file(
        google_cloud.get("service_account_json")
    )
    if credentials_path is not None:
        payload[INTEGRATED_MCP_GOOGLE_CLOUD_KEY] = {
            "name": "Google Cloud MCP",
            "description": (
                "System-managed Google Cloud MCP server from Google Cloud integration settings."
            ),
            "config": _google_cloud_config(),
        }

    workspace_credentials_path = _write_google_workspace_service_account_file(
        google_workspace.get("service_account_json")
    )
    if workspace_credentials_path is not None:
        _write_google_workspace_impersonate_user_file(
            google_workspace.get("workspace_delegated_user_email")
        )
        payload[INTEGRATED_MCP_GOOGLE_WORKSPACE_KEY] = {
            "name": "Google Workspace MCP",
            "description": (
                "System-managed Google Workspace MCP server from Google Workspace integration settings."
            ),
            "config": _google_workspace_config(),
        }
    else:
        _remove_google_workspace_impersonate_user_file()

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
    return _integrated_service_config(INTEGRATED_MCP_LLMCTL_KEY)


def _github_config() -> dict[str, Any]:
    return _integrated_service_config(INTEGRATED_MCP_GITHUB_KEY)


def _atlassian_config() -> dict[str, Any]:
    return _integrated_service_config(INTEGRATED_MCP_ATLASSIAN_KEY)


def _chroma_config() -> dict[str, Any]:
    return _integrated_service_config(INTEGRATED_MCP_CHROMA_KEY)


def _google_cloud_config() -> dict[str, Any]:
    return _integrated_service_config(INTEGRATED_MCP_GOOGLE_CLOUD_KEY)


def _google_workspace_config() -> dict[str, Any]:
    return _integrated_service_config(INTEGRATED_MCP_GOOGLE_WORKSPACE_KEY)


def _integrated_service_config(server_key: str) -> dict[str, Any]:
    endpoint = INTEGRATED_MCP_SERVICE_ENDPOINTS.get(server_key)
    if endpoint is None:
        raise KeyError(f"No integrated MCP service endpoint configured for {server_key}")
    service_name, port = endpoint
    namespace = _integrated_mcp_namespace()
    return {
        "url": (
            f"http://{service_name}.{namespace}.svc.cluster.local:{port}{INTEGRATED_MCP_PATH}"
        ),
        "transport": INTEGRATED_MCP_TRANSPORT,
    }


def _integrated_mcp_namespace() -> str:
    namespace = _clean(getattr(Config, "NODE_EXECUTOR_K8S_NAMESPACE", ""))
    return namespace or "default"


def _write_google_cloud_service_account_file(raw_json: str | None) -> Path | None:
    return _write_google_service_account_file(
        raw_json,
        target=GOOGLE_CLOUD_SERVICE_ACCOUNT_FILE,
        provider_label="Google Cloud",
    )


def _write_google_workspace_service_account_file(raw_json: str | None) -> Path | None:
    return _write_google_service_account_file(
        raw_json,
        target=GOOGLE_WORKSPACE_SERVICE_ACCOUNT_FILE,
        provider_label="Google Workspace",
    )


def _write_google_workspace_impersonate_user_file(
    delegated_user_email: str | None,
) -> None:
    cleaned = _clean(delegated_user_email)
    target = GOOGLE_WORKSPACE_IMPERSONATE_USER_FILE
    if not cleaned:
        _remove_google_workspace_impersonate_user_file()
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(cleaned + "\n", encoding="utf-8")
        target.chmod(0o600)
    except OSError as exc:
        logger.warning(
            "Unable to persist Google Workspace delegated user file at %s: %s",
            target,
            exc,
        )


def _remove_google_workspace_impersonate_user_file() -> None:
    _remove_file(
        GOOGLE_WORKSPACE_IMPERSONATE_USER_FILE,
        "Google Workspace delegated user file",
    )


def _write_google_service_account_file(
    raw_json: str | None,
    *,
    target: Path,
    provider_label: str,
) -> Path | None:
    parsed = _parse_google_service_account_json(
        raw_json,
        provider_label=provider_label,
    )
    if parsed is None:
        _remove_file(target, f"{provider_label} service account file")
        return None
    normalized = json.dumps(parsed, sort_keys=True, indent=2) + "\n"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(normalized, encoding="utf-8")
        target.chmod(0o600)
    except OSError as exc:
        logger.warning(
            "Unable to persist %s service account file at %s: %s",
            provider_label,
            target,
            exc,
        )
        return None
    return target


def _parse_google_service_account_json(
    raw_json: str | None,
    *,
    provider_label: str,
) -> dict[str, Any] | None:
    cleaned = _clean(raw_json)
    if not cleaned:
        return None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning(
            "%s service account JSON is invalid; skipping MCP setup.",
            provider_label,
        )
        return None
    if not isinstance(parsed, dict):
        logger.warning(
            "%s service account JSON must be an object; skipping MCP setup.",
            provider_label,
        )
        return None
    return parsed


def _remove_file(path: Path, file_label: str) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError as exc:
        logger.warning(
            "Unable to remove %s at %s: %s",
            file_label,
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
