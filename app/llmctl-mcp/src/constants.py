from __future__ import annotations

import os

from core.models import (
    Agent,
    AgentTask,
    Attachment,
    IntegrationSetting,
    MCPServer,
    Memory,
    Milestone,
    Pipeline,
    PipelineRun,
    PipelineStep,
    Role,
    Run,
    Script,
    SCRIPT_TYPE_INIT,
    SCRIPT_TYPE_POST_INIT,
    SCRIPT_TYPE_POST_RUN,
    SCRIPT_TYPE_PRE_INIT,
    SCRIPT_TYPE_SKILL,
    TaskTemplate,
)

# NOTE: Keep naming consistent with llmctl-studio models.
MODEL_REGISTRY = {
    "mcpserver": MCPServer,
    "mcp_server": MCPServer,
    "mcp_servers": MCPServer,
    "script": Script,
    "scripts": Script,
    "attachment": Attachment,
    "attachments": Attachment,
    "memory": Memory,
    "memories": Memory,
    "integrationsetting": IntegrationSetting,
    "integration_setting": IntegrationSetting,
    "integration_settings": IntegrationSetting,
    "agent": Agent,
    "agents": Agent,
    "autorun": Run,
    "autoruns": Run,
    "run": Run,
    "runs": Run,
    "role": Role,
    "roles": Role,
    "agenttask": AgentTask,
    "agent_task": AgentTask,
    "agent_tasks": AgentTask,
    "tasktemplate": TaskTemplate,
    "task_template": TaskTemplate,
    "task_templates": TaskTemplate,
    "pipeline": Pipeline,
    "pipelines": Pipeline,
    "pipelinestep": PipelineStep,
    "pipeline_step": PipelineStep,
    "pipeline_steps": PipelineStep,
    "pipelinerun": PipelineRun,
    "pipeline_run": PipelineRun,
    "pipeline_runs": PipelineRun,
    "milestone": Milestone,
    "milestones": Milestone,
}

READONLY_COLUMNS = {"id", "created_at", "updated_at"}

DEFAULT_LIMIT = int(os.getenv("LLMCTL_MCP_DEFAULT_LIMIT", "200"))
MAX_LIMIT = int(os.getenv("LLMCTL_MCP_MAX_LIMIT", "1000"))

SCRIPT_TYPE_KEYS = {
    "pre_init": SCRIPT_TYPE_PRE_INIT,
    "init": SCRIPT_TYPE_INIT,
    "post_init": SCRIPT_TYPE_POST_INIT,
    "post_run": SCRIPT_TYPE_POST_RUN,
    "skill": SCRIPT_TYPE_SKILL,
}
