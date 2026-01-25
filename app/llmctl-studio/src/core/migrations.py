from __future__ import annotations

import logging

from sqlalchemy import select

from core.config import Config
from core.db import session_scope
from core.mcp_config import parse_mcp_config, render_mcp_config
from core.models import MCPServer

logger = logging.getLogger(__name__)


def apply_runtime_migrations() -> None:
    _sync_github_mcp_url()


def _sync_github_mcp_url() -> None:
    url = (Config.GITHUB_MCP_URL or "").strip()
    if not url:
        return
    transport = "streamable-http"
    with session_scope() as session:
        server = (
            session.execute(
                select(MCPServer).where(MCPServer.server_key == "github")
            )
            .scalars()
            .first()
        )
        if server is None:
            return
        try:
            config = parse_mcp_config(server.config_json, server_key="github")
        except Exception as exc:
            logger.warning("Failed to parse GitHub MCP config: %s", exc)
            return
        if config.get("url") == url and config.get("transport") == transport:
            return
        config.pop("command", None)
        config.pop("args", None)
        config["url"] = url
        config["transport"] = transport
        server.config_json = render_mcp_config("github", config)
