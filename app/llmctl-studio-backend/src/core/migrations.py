from __future__ import annotations

import logging

from core.integrated_mcp import sync_integrated_mcp_servers
from services.integrations import ensure_node_executor_setting_defaults

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
