from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from core.config import Config
from core.integrated_mcp import (
    INTEGRATED_MCP_ATLASSIAN_KEY,
    INTEGRATED_MCP_CHROMA_KEY,
    INTEGRATED_MCP_GITHUB_KEY,
    INTEGRATED_MCP_GOOGLE_CLOUD_KEY,
    INTEGRATED_MCP_GOOGLE_WORKSPACE_KEY,
    INTEGRATED_MCP_LLMCTL_KEY,
    LEGACY_ATLASSIAN_KEY,
)
from services.integrations import load_integration_settings

MCP_SERVER_INTEGRATION_MAP: dict[str, tuple[str, ...]] = {
    INTEGRATED_MCP_GITHUB_KEY: ("github",),
    INTEGRATED_MCP_ATLASSIAN_KEY: ("jira", "confluence"),
    LEGACY_ATLASSIAN_KEY: ("jira", "confluence"),
    INTEGRATED_MCP_GOOGLE_CLOUD_KEY: ("google_cloud",),
    INTEGRATED_MCP_GOOGLE_WORKSPACE_KEY: ("google_workspace",),
    INTEGRATED_MCP_CHROMA_KEY: ("chroma",),
    INTEGRATED_MCP_LLMCTL_KEY: tuple(),
}


@dataclass(slots=True)
class ResolvedMcpIntegrations:
    selected_mcp_server_keys: list[str]
    mapped_integration_keys: list[str]
    configured_integration_keys: list[str]
    skipped_integration_keys: list[str]
    warnings: list[str]


def normalize_mcp_server_keys(values: Iterable[str] | None) -> list[str]:
    if values is None:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = str(value or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(key)
    return normalized


def map_mcp_servers_to_integration_keys(
    selected_mcp_server_keys: Iterable[str] | None,
) -> list[str]:
    mapped: list[str] = []
    seen: set[str] = set()
    for mcp_key in normalize_mcp_server_keys(selected_mcp_server_keys):
        for integration_key in MCP_SERVER_INTEGRATION_MAP.get(mcp_key, tuple()):
            key = str(integration_key or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            mapped.append(key)
    return mapped


def _credential_pair_valid(email: str, api_key: str) -> bool:
    cleaned_email = str(email or "").strip()
    cleaned_api_key = str(api_key or "").strip()
    if not cleaned_api_key:
        return False
    if ":" in cleaned_api_key:
        user, token = cleaned_api_key.split(":", 1)
        return bool((user.strip() or cleaned_email) and token.strip())
    return bool(cleaned_email)


def _integration_configuration_status(integration_key: str) -> tuple[bool, str]:
    key = str(integration_key or "").strip().lower()

    if key == "github":
        settings = load_integration_settings("github")
        repo = str(settings.get("repo") or "").strip()
        return (
            bool(repo),
            "GitHub repo is not configured.",
        )

    if key == "jira":
        settings = load_integration_settings("jira")
        site = str(settings.get("site") or "").strip()
        project_key = str(settings.get("project_key") or "").strip()
        board = str(settings.get("board") or "").strip()
        email = str(settings.get("email") or "").strip()
        api_key = str(settings.get("api_key") or "").strip()
        return (
            bool(site and (project_key or board or _credential_pair_valid(email, api_key))),
            "Jira defaults are incomplete (expected site plus project/board or API credentials).",
        )

    if key == "confluence":
        settings = load_integration_settings("confluence")
        site = str(settings.get("site") or "").strip()
        space = str(settings.get("space") or "").strip()
        email = str(settings.get("email") or "").strip()
        api_key = str(settings.get("api_key") or "").strip()
        return (
            bool(site and (space or _credential_pair_valid(email, api_key))),
            "Confluence defaults are incomplete (expected site plus space or API credentials).",
        )

    if key == "google_cloud":
        settings = load_integration_settings("google_cloud")
        project_id = str(settings.get("google_cloud_project_id") or "").strip()
        service_account_json = str(settings.get("service_account_json") or "").strip()
        return (
            bool(project_id or service_account_json),
            "Google Cloud integration settings are incomplete.",
        )

    if key == "google_workspace":
        settings = load_integration_settings("google_workspace")
        delegated_user = str(
            settings.get("workspace_delegated_user_email") or ""
        ).strip()
        service_account_json = str(settings.get("service_account_json") or "").strip()
        return (
            bool(delegated_user or service_account_json),
            "Google Workspace integration settings are incomplete.",
        )

    if key == "chroma":
        settings = load_integration_settings("chroma")
        host = str(settings.get("host") or "").strip() or str(Config.CHROMA_HOST or "").strip()
        port = str(settings.get("port") or "").strip() or str(Config.CHROMA_PORT or "").strip()
        return (
            bool(host and port),
            "Chroma host/port settings are incomplete.",
        )

    return False, f"Unsupported integration mapping '{key}'."


def resolve_effective_integrations_from_mcp(
    selected_mcp_server_keys: Iterable[str] | None,
) -> ResolvedMcpIntegrations:
    selected_keys = normalize_mcp_server_keys(selected_mcp_server_keys)
    mapped_keys = map_mcp_servers_to_integration_keys(selected_keys)
    configured_keys: list[str] = []
    skipped_keys: list[str] = []
    warnings: list[str] = []

    reason_by_integration: dict[str, str] = {}
    mcp_by_integration: dict[str, list[str]] = {}
    for mcp_key in selected_keys:
        for integration_key in MCP_SERVER_INTEGRATION_MAP.get(mcp_key, tuple()):
            mcp_list = mcp_by_integration.setdefault(integration_key, [])
            if mcp_key not in mcp_list:
                mcp_list.append(mcp_key)

    for integration_key in mapped_keys:
        configured, reason = _integration_configuration_status(integration_key)
        if configured:
            configured_keys.append(integration_key)
            continue
        skipped_keys.append(integration_key)
        reason_by_integration[integration_key] = reason

    for integration_key in skipped_keys:
        mcp_keys = mcp_by_integration.get(integration_key, [])
        mcp_label = ", ".join(mcp_keys) if mcp_keys else "selected MCP servers"
        warnings.append(
            f"Skipping integration '{integration_key}' for {mcp_label}: "
            f"{reason_by_integration.get(integration_key, 'integration is not configured')}."
        )

    return ResolvedMcpIntegrations(
        selected_mcp_server_keys=selected_keys,
        mapped_integration_keys=mapped_keys,
        configured_integration_keys=configured_keys,
        skipped_integration_keys=skipped_keys,
        warnings=warnings,
    )
