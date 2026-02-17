from __future__ import annotations

import logging

from core.integrated_mcp import sync_integrated_mcp_servers
from services.integrations import (
    ensure_node_executor_setting_defaults,
    migrate_node_executor_to_kubernetes_only_settings,
)

logger = logging.getLogger(__name__)


def apply_runtime_migrations() -> None:
    summary = sync_integrated_mcp_servers()
    logger.info(
        "Synchronized integrated MCP servers: created=%s updated=%s deleted=%s",
        summary["created"],
        summary["updated"],
        summary["deleted"],
    )
    ensure_node_executor_setting_defaults()
    node_executor_summary = migrate_node_executor_to_kubernetes_only_settings()
    logger.info(
        "Migrated node executor settings to kubernetes-only: provider_forced=%s deprecated_keys_removed=%s",
        node_executor_summary.get("provider_forced"),
        node_executor_summary.get("deprecated_keys_removed"),
    )
