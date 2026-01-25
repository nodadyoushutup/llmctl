#!/usr/bin/env python3
import json
import os
import subprocess
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from sqlalchemy import select

from core.config import Config
from core.db import init_db, init_engine, session_scope
from core.models import Agent, Role

AGENT_BACKEND = os.getenv("AGENT_BACKEND", "codex")
CODEX_CMD = os.getenv("CODEX_CMD", "codex")
CLAUDE_CMD = os.getenv("CLAUDE_CMD", "claude")
OPENAI_CMD = os.getenv("OPENAI_CMD", "openai")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "")
CODEX_MODEL = os.getenv("CODEX_MODEL", "")
CODEX_SKIP_GIT_REPO_CHECK = (
    os.getenv("CODEX_SKIP_GIT_REPO_CHECK", "false").lower() == "true"
)
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "")
AGENT_ID = os.getenv("AGENT_ID")
AGENT_NAME = os.getenv("AGENT_NAME")


def build_model_args(model_name: str) -> list[str]:
    return ["--model", model_name] if model_name else []


def read_thread(thread_file: str) -> str:
    path = Path(thread_file)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.read_text()


def _load_prompt_payload(prompt_json: str | None, prompt_text: str | None) -> object | None:
    if prompt_json:
        try:
            return json.loads(prompt_json)
        except json.JSONDecodeError:
            pass
    if prompt_text:
        return prompt_text
    return prompt_json


def _format_payload(payload: object | None) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload.strip()
    return json.dumps(payload, indent=2, sort_keys=True)


def _load_role(role_name: str) -> Role | None:
    with session_scope() as session:
        return (
            session.execute(select(Role).where(Role.name == role_name))
            .scalars()
            .first()
        )


def _load_agent() -> Agent | None:
    with session_scope() as session:
        if AGENT_ID and AGENT_ID.isdigit():
            agent = session.get(Agent, int(AGENT_ID))
            if agent is not None:
                return agent
        if AGENT_NAME:
            return (
                session.execute(select(Agent).where(Agent.name == AGENT_NAME))
                .scalars()
                .first()
            )
    return None


def _load_agent_for_role(role_id: int) -> Agent | None:
    with session_scope() as session:
        agents = (
            session.execute(
                select(Agent)
                .where(Agent.role_id == role_id)
                .order_by(Agent.created_at.desc())
                .limit(2)
            )
            .scalars()
            .all()
        )
    if len(agents) == 1:
        return agents[0]
    return None


def build_prompt(role: str, thread_file: str) -> str:
    init_engine(Config.SQLALCHEMY_DATABASE_URI)
    init_db()
    agent = _load_agent()
    role_record = _load_role(role)
    if agent is not None and agent.role is not None:
        if role_record is None or agent.role_id != role_record.id:
            role_record = agent.role
            role = role_record.name
    if role_record is None:
        raise RuntimeError(f"Role not found in database: {role}")

    if agent is None:
        agent = _load_agent_for_role(role_record.id)

    role_payload = _load_prompt_payload(
        role_record.prompt_json, role_record.prompt_text
    )
    if role_payload is None:
        raise RuntimeError(f"Role prompt is empty in database: {role_record.name}")

    agent_payload = None
    if agent is not None:
        agent_payload = _load_prompt_payload(agent.prompt_json, agent.prompt_text)

    thread_text = read_thread(thread_file)
    parts = [
        f"Role: {role}",
        "Role Prompt:\n" + _format_payload(role_payload),
    ]
    if agent is not None:
        parts.append(f"Agent: {agent.name}")
    if agent_payload is not None:
        parts.append("Agent Prompt:\n" + _format_payload(agent_payload))
    parts.append("Conversation Thread:\n" + thread_text.strip())
    return "\n\n".join(parts).strip() + "\n"


def main() -> int:
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <role> <thread-file>", file=sys.stderr)
        return 1

    role = sys.argv[1]
    thread_file = sys.argv[2]

    try:
        prompt = build_prompt(role, thread_file)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if AGENT_BACKEND == "codex":
        cmd = [CODEX_CMD, "exec"] + build_model_args(CODEX_MODEL)
        if CODEX_SKIP_GIT_REPO_CHECK:
            cmd.append("--skip-git-repo-check")
        return subprocess.run(cmd, input=prompt, text=True).returncode
    if AGENT_BACKEND == "claude":
        cmd = [CLAUDE_CMD, "run", "--role", role] + build_model_args(CLAUDE_MODEL)
    elif AGENT_BACKEND == "openai":
        cmd = [OPENAI_CMD, "run", "--role", role] + build_model_args(OPENAI_MODEL)
    else:
        print(f"Unknown AGENT_BACKEND: {AGENT_BACKEND}", file=sys.stderr)
        return 2

    return subprocess.run(cmd, input=prompt, text=True).returncode


if __name__ == "__main__":
    raise SystemExit(main())
