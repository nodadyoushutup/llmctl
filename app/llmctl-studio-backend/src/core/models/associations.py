from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer, Table

from core.db import Base

agent_task_scripts = Table(
    "agent_task_scripts",
    Base.metadata,
    Column("agent_task_id", ForeignKey("agent_tasks.id"), primary_key=True),
    Column("script_id", ForeignKey("scripts.id"), primary_key=True),
    Column("position", Integer, nullable=True),
)

agent_task_attachments = Table(
    "agent_task_attachments",
    Base.metadata,
    Column("agent_task_id", ForeignKey("agent_tasks.id"), primary_key=True),
    Column("attachment_id", ForeignKey("attachments.id"), primary_key=True),
)

agent_task_mcp_servers = Table(
    "agent_task_mcp_servers",
    Base.metadata,
    Column("agent_task_id", ForeignKey("agent_tasks.id"), primary_key=True),
    Column("mcp_server_id", ForeignKey("mcp_servers.id"), primary_key=True),
)

flowchart_node_mcp_servers = Table(
    "flowchart_node_mcp_servers",
    Base.metadata,
    Column("flowchart_node_id", ForeignKey("flowchart_nodes.id"), primary_key=True),
    Column("mcp_server_id", ForeignKey("mcp_servers.id"), primary_key=True),
)

flowchart_node_scripts = Table(
    "flowchart_node_scripts",
    Base.metadata,
    Column("flowchart_node_id", ForeignKey("flowchart_nodes.id"), primary_key=True),
    Column("script_id", ForeignKey("scripts.id"), primary_key=True),
    Column("position", Integer, nullable=True),
)

flowchart_node_skills = Table(
    "flowchart_node_skills",
    Base.metadata,
    Column("flowchart_node_id", ForeignKey("flowchart_nodes.id"), primary_key=True),
    Column("skill_id", ForeignKey("skills.id"), primary_key=True),
    Column("position", Integer, nullable=True),
)

flowchart_node_attachments = Table(
    "flowchart_node_attachments",
    Base.metadata,
    Column("flowchart_node_id", ForeignKey("flowchart_nodes.id"), primary_key=True),
    Column("attachment_id", ForeignKey("attachments.id"), primary_key=True),
)

agent_skill_bindings = Table(
    "agent_skill_bindings",
    Base.metadata,
    Column("agent_id", ForeignKey("agents.id"), primary_key=True),
    Column("skill_id", ForeignKey("skills.id"), primary_key=True),
    Column("position", Integer, nullable=False, default=1),
)

chat_thread_mcp_servers = Table(
    "chat_thread_mcp_servers",
    Base.metadata,
    Column("chat_thread_id", ForeignKey("chat_threads.id"), primary_key=True),
    Column("mcp_server_id", ForeignKey("mcp_servers.id"), primary_key=True),
)


