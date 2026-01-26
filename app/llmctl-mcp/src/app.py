from __future__ import annotations

import os

from fastmcp import FastMCP

from core.config import Config
from core.db import init_db, init_engine

from tools import register

# Initialize database engine on module import.
init_engine(Config.SQLALCHEMY_DATABASE_URI)
init_db()

mcp = FastMCP("llmctl-mcp", json_response=True)
register(mcp)


def run() -> None:
    host = os.getenv("LLMCTL_MCP_HOST", "0.0.0.0")
    port = int(os.getenv("LLMCTL_MCP_PORT", "9020"))
    path = os.getenv("LLMCTL_MCP_PATH", "/mcp")
    transport = os.getenv("LLMCTL_MCP_TRANSPORT", "http")
    mcp.run(transport=transport, host=host, port=port, path=path)
