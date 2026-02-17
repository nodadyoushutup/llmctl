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
from core.prompt_envelope import build_prompt_envelope, serialize_prompt_envelope

AGENT_BACKEND = os.getenv("AGENT_BACKEND", "codex")
CODEX_CMD = os.getenv("CODEX_CMD", "codex")
CLAUDE_CMD = os.getenv("CLAUDE_CMD", "claude")
OPENAI_CMD = os.getenv("OPENAI_CMD", "openai")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "")
CODEX_MODEL = os.getenv("CODEX_MODEL", "")
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


def _load_role_payload(role: Role) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": role.name,
        "description": role.description or "",
    }
    if role.details_json:
        try:
            details_payload = json.loads(role.details_json)
        except json.JSONDecodeError:
            details_payload = None
        if isinstance(details_payload, dict):
            payload["details"] = details_payload
    return payload


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

    agent_payload = None
    if agent is not None:
        agent_payload = _load_prompt_payload(agent.prompt_json, agent.prompt_text)

    thread_text = read_thread(thread_file)
    system_contract = {"role": _load_role_payload(role_record)}
    agent_profile: dict[str, object] = {}
    if agent is not None:
        agent_profile = {
            "id": agent.id,
            "name": agent.name,
            "description": agent.description or "",
        }
        if isinstance(agent_payload, dict):
            agent_profile.update(agent_payload)
        elif isinstance(agent_payload, str) and agent_payload.strip():
            agent_profile["instructions"] = agent_payload.strip()
    prompt_payload = build_prompt_envelope(
        user_request=thread_text.strip(),
        system_contract=system_contract,
        agent_profile=agent_profile,
        task_context={
            "kind": "thread",
            "role": role,
            "thread_file": str(Path(thread_file).resolve()),
        },
        output_contract={"mode": "conversation"},
    )
    return serialize_prompt_envelope(prompt_payload)


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
