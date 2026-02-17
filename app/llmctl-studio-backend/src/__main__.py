#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import select

from core.config import Config
from core.db import init_db, init_engine, session_scope
from core.models import Role

REPO_ROOT = Path(__file__).resolve().parents[3]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LLMCTL Studio CLI")
    parser.add_argument("--role")
    parser.add_argument("--backend", choices=["codex", "claude", "openai"])
    parser.add_argument("--name")
    parser.add_argument("--idle", action="store_true")
    parser.add_argument("--poll", type=float)
    parser.add_argument(
        "--agent-cli", default="app/llmctl-studio-backend/src/cli/agent-cli.py"
    )
    parser.add_argument("--loop", default="app/llmctl-studio-backend/src/cli/agent-loop.py")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging in the agent loop for visibility.",
    )
    return parser.parse_args()


def prompt_role() -> str:
    roles = load_roles()
    if not roles:
        raise ValueError("No roles found in the database.")
    print("Select a role:")
    for index, role in enumerate(roles, start=1):
        print(f"{index}) {role}")
    selection = input("Role number: ").strip()
    if not selection.isdigit():
        raise ValueError("Invalid selection")
    index = int(selection)
    if index < 1 or index > len(roles):
        raise ValueError("Invalid selection")
    return roles[index - 1]


def load_roles() -> list[str]:
    init_engine(Config.SQLALCHEMY_DATABASE_URI)
    init_db()
    with session_scope() as session:
        return [
            role.name
            for role in session.execute(select(Role).order_by(Role.name.asc()))
            .scalars()
            .all()
        ]


def run_loop(env: dict[str, str], loop_path: str) -> int:
    try:
        return subprocess.call([sys.executable, loop_path], env=env)
    except KeyboardInterrupt:
        return 0


def resolve_repo_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def main() -> int:
    args = parse_args()
    if args.role:
        roles = load_roles()
        if args.role not in roles:
            print(f"Role not found in database: {args.role}", file=sys.stderr)
            return 1
        role = args.role
    else:
        role = prompt_role()

    env = os.environ.copy()
    env["AGENT_ROLE"] = role

    if args.backend:
        env["AGENT_BACKEND"] = args.backend
    if args.name:
        env["AGENT_NAME"] = args.name
    if args.idle:
        env["ALLOW_IDLE_PROMPTS"] = "true"
    if args.poll is not None:
        env["POLL_SECONDS"] = str(args.poll)
    if args.agent_cli:
        agent_cli_path = resolve_repo_path(args.agent_cli)
        if not agent_cli_path.exists():
            print(f"Agent CLI not found: {agent_cli_path}", file=sys.stderr)
            return 1
        env["AGENT_CLI"] = str(agent_cli_path)
    if args.verbose:
        env["AGENT_VERBOSE"] = "true"

    loop_path = resolve_repo_path(args.loop)
    if not loop_path.exists():
        print(f"Agent loop not found: {loop_path}", file=sys.stderr)
        print("Use --loop to point at the correct agent-loop.py file.", file=sys.stderr)
        return 1

    return run_loop(env, str(loop_path))


if __name__ == "__main__":
    raise SystemExit(main())
