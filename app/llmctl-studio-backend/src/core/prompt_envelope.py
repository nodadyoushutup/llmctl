from __future__ import annotations

import json
from typing import Any

PROMPT_ENVELOPE_TOP_LEVEL_KEYS = (
    "system_contract",
    "agent_profile",
    "task_context",
    "user_request",
    "output_contract",
)


def parse_prompt_input(raw_prompt: str | None) -> tuple[str, dict[str, Any] | None]:
    if raw_prompt is None:
        return "", None
    stripped = raw_prompt.strip()
    if not stripped:
        return "", None
    if not stripped.startswith("{"):
        return raw_prompt, None
    try:
        payload = json.loads(raw_prompt)
    except json.JSONDecodeError:
        return raw_prompt, None
    if not isinstance(payload, dict):
        return raw_prompt, None
    user_request = extract_user_request(payload)
    return user_request or "", payload


def is_prompt_envelope(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    return all(key in payload for key in PROMPT_ENVELOPE_TOP_LEVEL_KEYS)


def extract_user_request(payload: Any) -> str | None:
    if isinstance(payload, dict):
        value = payload.get("user_request")
        if isinstance(value, str):
            return value
        value = payload.get("prompt")
        if isinstance(value, str):
            return value
        return None
    if isinstance(payload, str):
        return payload
    return None


def build_prompt_envelope(
    *,
    user_request: str,
    system_contract: dict[str, Any] | None = None,
    agent_profile: dict[str, Any] | None = None,
    task_context: dict[str, Any] | None = None,
    output_contract: dict[str, Any] | None = None,
    source_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_system_contract: dict[str, Any] = {}
    resolved_agent_profile: dict[str, Any] = {}
    resolved_task_context: dict[str, Any] = {}
    resolved_output_contract: dict[str, Any] = {}
    resolved_user_request = user_request

    if is_prompt_envelope(source_payload):
        existing = source_payload or {}
        existing_system = existing.get("system_contract")
        existing_agent = existing.get("agent_profile")
        existing_context = existing.get("task_context")
        existing_output = existing.get("output_contract")
        existing_request = existing.get("user_request")
        if isinstance(existing_system, dict):
            resolved_system_contract.update(existing_system)
        if isinstance(existing_agent, dict):
            resolved_agent_profile.update(existing_agent)
        if isinstance(existing_context, dict):
            resolved_task_context.update(existing_context)
        if isinstance(existing_output, dict):
            resolved_output_contract.update(existing_output)
        if isinstance(existing_request, str) and not resolved_user_request:
            resolved_user_request = existing_request
    elif isinstance(source_payload, dict):
        resolved_task_context["input_payload"] = source_payload

    if system_contract:
        resolved_system_contract.update(system_contract)
    if agent_profile:
        resolved_agent_profile.update(agent_profile)
    if task_context:
        resolved_task_context.update(task_context)
    if output_contract:
        resolved_output_contract.update(output_contract)

    return {
        "system_contract": resolved_system_contract,
        "agent_profile": resolved_agent_profile,
        "task_context": resolved_task_context,
        "user_request": resolved_user_request or "",
        "output_contract": resolved_output_contract,
    }


def serialize_prompt_envelope(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)
