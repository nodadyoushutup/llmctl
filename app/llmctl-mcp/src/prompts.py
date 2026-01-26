from __future__ import annotations

import json

from core.models import Agent
from services.code_review import (
    CODE_REVIEW_FAIL_EMOJI,
    CODE_REVIEW_PASS_EMOJI,
    CODE_REVIEW_ROLE_PROMPT,
)
from services.tasks import OUTPUT_INSTRUCTIONS_ONE_OFF, _build_agent_prompt_payload


def _build_code_review_prompt(
    repo: str,
    pr_number: int,
    pr_title: str | None,
    pr_url: str | None,
    role_prompt: str | None = None,
) -> str:
    pr_label = f"{repo}#{pr_number}" if repo else f"#{pr_number}"
    base_prompt = role_prompt.strip() if role_prompt else CODE_REVIEW_ROLE_PROMPT
    lines = [
        base_prompt,
        "",
        f"Pull request to review: {pr_label}",
    ]
    if pr_title:
        lines.append(f"Title: {pr_title}")
    if pr_url:
        lines.append(f"URL: {pr_url}")
    lines.extend(
        [
            "",
            "Requirements:",
            "- Use the GitHub MCP tools to read the PR, diff, and relevant files.",
            "- Leave feedback as a comment on the pull request (not just in this response).",
            (
                f"- Start the comment with {CODE_REVIEW_PASS_EMOJI} pass "
                f"or {CODE_REVIEW_FAIL_EMOJI} fail."
            ),
            "- Cite explicit files/lines or include short code blocks with file paths.",
            "- Do a full, proper code review every time.",
            "- If you cannot post a comment, explain why in your output.",
        ]
    )
    return "\n".join(lines)


def _build_quick_task_prompt(agent: Agent, prompt: str) -> str:
    payload: dict[str, object] = {
        "prompt": prompt,
        "output_instructions": OUTPUT_INSTRUCTIONS_ONE_OFF,
    }
    agent_payload = _build_agent_prompt_payload(agent, include_autoprompt=False)
    if agent_payload:
        payload["agent"] = agent_payload
    return json.dumps(payload, indent=2, sort_keys=True)
