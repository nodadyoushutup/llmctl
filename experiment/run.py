#!/usr/bin/env python3
"""Debug runner that sends one unified payload to all provider adapters."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Iterable

from agent import (
    AgentConfig,
    AgentRequest,
    MCPServerConfig,
    OutputContract,
    SkillConfig,
    ToolConfig,
    UnifiedAgent,
)


@dataclass(slots=True)
class AgentRunSpec:
    config: AgentConfig
    request: AgentRequest


# -----------------------------
# Debug constants (edit in file)
# -----------------------------
USE_MCP = True
USE_TOOLS = True
USE_SKILLS = True

SHARED_SYSTEM_PROMPT = (
    "You are a concise assistant. "
    "Return practical, direct answers with no filler. "
    "When MCP, tools, or skills are available, use them when they improve factuality."
)
SHARED_USER_PROMPT = (
    "Use the Jira MCP integration to list up to 5 Jira tickets in Done status and include "
    "key, summary, and status. Then test the chromium-screenshot skill by taking a screenshot "
    "of https://www.google.com and report the screenshot artifact path."
)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = "gpt-5.2-codex"
OPENAI_MAX_TOKENS = 1200
OPENAI_OPTIONS = {
    "temperature": 0.2,
    "top_p": 0.95,
    "timeout_seconds": 180,
    # Optional CLI overrides when advanced features are requested:
    # "codex_cmd": "codex",
}

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
GOOGLE_MODEL = "gemini-3-pro-preview"
GOOGLE_MAX_TOKENS = 1200
GOOGLE_OPTIONS = {
    "temperature": 0.2,
    "top_p": 0.95,
    "thinking_budget": 256,
    "timeout_seconds": 180,
    # Optional CLI override:
    # "gemini_cmd": "gemini",
}

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = "claude-sonnet-4-0"
ANTHROPIC_MAX_TOKENS = 1200
ANTHROPIC_OPTIONS = {
    "temperature": 0.2,
    "top_p": 0.95,
    "thinking_budget": 1024,
    "timeout_seconds": 180,
    # Optional CLI override:
    # "claude_cmd": "claude",
}

EXPERIMENT_OUTPUT_CONTRACT = OutputContract(
    type="json_schema",
    schema_name="assistant_response",
    strict=True,
    require_json=True,
    schema={
        "type": "object",
        "required": ["result"],
        "properties": {
            "result": {"type": "string"},
            "next_steps": {
                "type": "array",
                "items": {"type": "string"},
            },
            "notes": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "additionalProperties": True,
    },
)

OPENAI_AGENT_CONFIG = AgentConfig(
    provider="openai",
    api_key=OPENAI_API_KEY,
    model=OPENAI_MODEL,
    max_tokens=OPENAI_MAX_TOKENS,
    provider_options=OPENAI_OPTIONS,
    output_contract=EXPERIMENT_OUTPUT_CONTRACT,
)
GOOGLE_AGENT_CONFIG = AgentConfig(
    provider="google",
    api_key=GOOGLE_API_KEY,
    model=GOOGLE_MODEL,
    max_tokens=GOOGLE_MAX_TOKENS,
    provider_options=GOOGLE_OPTIONS,
    output_contract=EXPERIMENT_OUTPUT_CONTRACT,
)
ANTHROPIC_AGENT_CONFIG = AgentConfig(
    provider="anthropic",
    api_key=ANTHROPIC_API_KEY,
    model=ANTHROPIC_MODEL,
    max_tokens=ANTHROPIC_MAX_TOKENS,
    provider_options=ANTHROPIC_OPTIONS,
    output_contract=EXPERIMENT_OUTPUT_CONTRACT,
)

# Host-side port-forward target for Jira/Atlassian MCP service.
MCP_SERVERS: list[MCPServerConfig] = [
    MCPServerConfig(
        name="jira-mcp-atlassian",
        url="http://127.0.0.1:18000/mcp",
        transport="streamable-http",
        timeout_seconds=60,
        sse_read_timeout_seconds=300,
    )
]

# Host Codex skills are natively consumed by codex CLI. For non-codex runtimes,
# skill content is injected as best-effort context.
SKILLS: list[SkillConfig] = [
    SkillConfig(
        name="chromium-screenshot",
        path=str(
            Path.home()
            / ".codex"
            / "skills"
            / "chromium-screenshot"
            / "SKILL.md"
        ),
        description="Capture deterministic Chromium screenshots for visual verification.",
        enabled=True,
    ),
    SkillConfig(
        name="argocd-commit-push-autosync",
        path=str(
            Path.home()
            / ".codex"
            / "skills"
            / "argocd-commit-push-autosync"
            / "SKILL.md"
        ),
        description="Commit and push before enabling ArgoCD autosync.",
        enabled=True,
    ),
]


def _tool_utc_now(_args: dict[str, Any]) -> dict[str, str]:
    return {"utc_now": datetime.now(timezone.utc).isoformat()}


def _tool_sum_numbers(args: dict[str, Any]) -> dict[str, Any]:
    raw_numbers = args.get("numbers")
    if not isinstance(raw_numbers, list):
        raise ValueError("numbers must be an array of numeric values")
    numbers: list[float] = []
    for item in raw_numbers:
        try:
            numbers.append(float(item))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid number: {item}") from exc
    return {"count": len(numbers), "sum": sum(numbers)}


def _tool_pretty_json(args: dict[str, Any]) -> str:
    return json.dumps(args, indent=2, ensure_ascii=False, sort_keys=True)


TOOLS: list[ToolConfig] = [
    ToolConfig(
        name="utc_now",
        description="Return current UTC timestamp.",
        parameters_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_tool_utc_now,
    ),
    ToolConfig(
        name="sum_numbers",
        description="Return count and sum for numeric array input.",
        parameters_schema={
            "type": "object",
            "properties": {
                "numbers": {
                    "type": "array",
                    "items": {"type": "number"},
                }
            },
            "required": ["numbers"],
            "additionalProperties": False,
        },
        handler=_tool_sum_numbers,
    ),
    ToolConfig(
        name="pretty_json",
        description="Pretty-print a JSON object for inspection.",
        parameters_schema={"type": "object", "additionalProperties": True},
        handler=_tool_pretty_json,
    ),
]

# Per-agent request wiring (tools + MCP + skills are configured here explicitly).
OPENAI_TOOLS = list(TOOLS) if USE_TOOLS else []
GOOGLE_TOOLS = list(TOOLS) if USE_TOOLS else []
ANTHROPIC_TOOLS = list(TOOLS) if USE_TOOLS else []

OPENAI_MCP_SERVERS = list(MCP_SERVERS) if USE_MCP else []
GOOGLE_MCP_SERVERS = list(MCP_SERVERS) if USE_MCP else []
ANTHROPIC_MCP_SERVERS = list(MCP_SERVERS) if USE_MCP else []

OPENAI_SKILLS = list(SKILLS) if USE_SKILLS else []
GOOGLE_SKILLS = list(SKILLS) if USE_SKILLS else []
ANTHROPIC_SKILLS = list(SKILLS) if USE_SKILLS else []

AGENTS_TO_RUN: list[AgentRunSpec] = [
    AgentRunSpec(
        config=OPENAI_AGENT_CONFIG,
        request=AgentRequest(
            model=OPENAI_MODEL,
            system_prompt=SHARED_SYSTEM_PROMPT,
            user_prompt=SHARED_USER_PROMPT,
            tools=OPENAI_TOOLS,
            mcp_servers=OPENAI_MCP_SERVERS,
            skills=OPENAI_SKILLS,
            max_tool_round_trips=4,
        ),
    ),
    AgentRunSpec(
        config=GOOGLE_AGENT_CONFIG,
        request=AgentRequest(
            model=GOOGLE_MODEL,
            system_prompt=SHARED_SYSTEM_PROMPT,
            user_prompt=SHARED_USER_PROMPT,
            tools=GOOGLE_TOOLS,
            mcp_servers=GOOGLE_MCP_SERVERS,
            skills=GOOGLE_SKILLS,
            max_tool_round_trips=4,
        ),
    ),
    # AgentRunSpec(
    #     config=ANTHROPIC_AGENT_CONFIG,
    #     request=AgentRequest(
    #         model=ANTHROPIC_MODEL,
    #         system_prompt=SHARED_SYSTEM_PROMPT,
    #         user_prompt=SHARED_USER_PROMPT,
    #         tools=ANTHROPIC_TOOLS,
    #         mcp_servers=ANTHROPIC_MCP_SERVERS,
    #         skills=ANTHROPIC_SKILLS,
    #         max_tool_round_trips=4,
    #     ),
    # ),
]


def _ensure_required_config(agent_config: AgentConfig) -> None:
    if not agent_config.api_key:
        raise ValueError(
            f"Missing API key for provider '{agent_config.provider}'. "
            "Set env vars (OPENAI_API_KEY / GOOGLE_API_KEY|GEMINI_API_KEY / "
            "ANTHROPIC_API_KEY) or edit constants in experiment/run.py."
        )
    if not agent_config.model:
        raise ValueError(
            f"Missing model for provider '{agent_config.provider}'. "
            "Set the model constant at the top of experiment/run.py."
        )


def _build_request(spec: AgentRunSpec, prompt_override: str | None) -> AgentRequest:
    request_template = spec.request
    return AgentRequest(
        model=request_template.model,
        system_prompt=request_template.system_prompt,
        user_prompt=(prompt_override or request_template.user_prompt).strip(),
        tools=list(request_template.tools),
        mcp_servers=list(request_template.mcp_servers),
        skills=list(request_template.skills),
        max_tool_round_trips=request_template.max_tool_round_trips,
        output_contract=request_template.output_contract,
    )


def _run_agents(agent_specs: Iterable[AgentRunSpec], prompt_override: str | None) -> int:
    has_failures = False

    for spec in agent_specs:
        agent_config = spec.config
        provider = agent_config.provider.strip().lower()
        print(f"\n=== {provider.upper()} | model={agent_config.model} ===")

        try:
            _ensure_required_config(agent_config)
            request = _build_request(spec, prompt_override)
            result = UnifiedAgent(agent_config).run(request)
            print(result.text)
            print(f"\n[backend] {result.backend}")
            print(f"[tool_calls] {len(result.tool_calls)}")
            for index, call in enumerate(result.tool_calls, start=1):
                print(f"  {index}. {call.get('name')} args={json.dumps(call.get('arguments'), ensure_ascii=False)}")
            if result.warnings:
                print("[warnings]")
                for warning in result.warnings:
                    print(f"  - {warning}")
        except Exception as exc:
            has_failures = True
            print(f"ERROR: {exc}")

    return 1 if has_failures else 0


def main() -> int:
    prompt_override = " ".join(sys.argv[1:]).strip() or None
    return _run_agents(AGENTS_TO_RUN, prompt_override)


if __name__ == "__main__":
    raise SystemExit(main())
