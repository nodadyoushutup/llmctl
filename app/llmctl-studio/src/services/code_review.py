from __future__ import annotations

import json

from sqlalchemy import select

from core.models import Agent, Role

CODE_REVIEW_ROLE_NAME = "Code Reviewer"
CODE_REVIEW_AGENT_NAME = "Code Reviewer"
CODE_REVIEW_TASK_KIND = "github"
CODE_REVIEW_PASS_EMOJI = "\u2705"
CODE_REVIEW_FAIL_EMOJI = "\u274c"
CODE_REVIEW_ROLE_PROMPT = (
    "You are a Code Reviewer focused on GitHub pull requests.\n"
    "Perform thorough reviews for correctness, edge cases, security, performance, "
    "readability, and tests.\n"
    "Call out concrete issues and risks, and suggest fixes when possible.\n"
    "Cite files and line numbers when available, or include short code blocks with file paths."
)


def ensure_code_reviewer_role(session) -> Role:
    role = (
        session.execute(select(Role).where(Role.name == CODE_REVIEW_ROLE_NAME))
        .scalars()
        .first()
    )
    if role is not None:
        if not role.is_system:
            role.is_system = True
        if not role.description:
            role.description = CODE_REVIEW_ROLE_PROMPT
        if not role.details_json:
            role.details_json = json.dumps(
                {
                    "personality": "Thorough, precise, direct",
                    "focus": "Correctness, risk, tests",
                    "review_style": "Concrete fixes with citations",
                },
                indent=2,
                sort_keys=True,
            )
        return role
    return Role.create(
        session,
        name=CODE_REVIEW_ROLE_NAME,
        description=CODE_REVIEW_ROLE_PROMPT,
        details_json=json.dumps(
            {
                "personality": "Thorough, precise, direct",
                "focus": "Correctness, risk, tests",
                "review_style": "Concrete fixes with citations",
            },
            indent=2,
            sort_keys=True,
        ),
        is_system=True,
    )


def ensure_code_reviewer_agent(session, role: Role | None) -> Agent:
    agent = (
        session.execute(
            select(Agent)
            .where(Agent.name == CODE_REVIEW_AGENT_NAME)
        )
        .scalars()
        .first()
    )
    if agent is None:
        agent_prompt = "Code Reviewer agent used for GitHub pull request reviews."
        prompt_payload = json.dumps(
            {"description": agent_prompt}, indent=2, sort_keys=True
        )
        agent = Agent.create(
            session,
            name=CODE_REVIEW_AGENT_NAME,
            role_id=role.id if role is not None else None,
            description=agent_prompt,
            prompt_json=prompt_payload,
            prompt_text=None,
            autonomous_prompt=None,
            is_system=True,
        )
    else:
        if role is not None and agent.role_id != role.id:
            agent.role_id = role.id
        if not agent.is_system:
            agent.is_system = True
        if not agent.description:
            agent.description = "Code Reviewer agent used for GitHub pull request reviews."
    return agent


def ensure_code_reviewer_defaults(session) -> tuple[Role, Agent]:
    role = ensure_code_reviewer_role(session)
    agent = ensure_code_reviewer_agent(session, role)
    return role, agent
