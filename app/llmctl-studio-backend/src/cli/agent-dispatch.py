#!/usr/bin/env python3
import os
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from sqlalchemy import select

from core.config import Config
from core.db import init_db, init_engine, session_scope
from core.models import Role

AGENT_CLI = os.getenv("AGENT_CLI", "app/llmctl-studio-backend/src/cli/agent-cli.py")
DEFAULT_ROLE = os.getenv("DEFAULT_ROLE", "business-analyst")


def infer_role(thread_file: Path) -> str:
    try:
        for line in thread_file.read_text().splitlines():
            if line.startswith("Role:"):
                return line.split(":", 1)[1].strip()
    except FileNotFoundError:
        return DEFAULT_ROLE
    return DEFAULT_ROLE


def role_exists(role_name: str) -> bool:
    init_engine(Config.SQLALCHEMY_DATABASE_URI)
    init_db()
    with session_scope() as session:
        return (
            session.execute(select(Role.id).where(Role.name == role_name)).first()
            is not None
        )


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <thread-file>", file=sys.stderr)
        return 1

    thread_file = Path(sys.argv[1])
    if not thread_file.exists():
        print(f"Thread file not found: {thread_file}", file=sys.stderr)
        return 1

    role = infer_role(thread_file)
    if not role_exists(role):
        print(f"Unknown role: {role}", file=sys.stderr)
        return 2

    return os.spawnlp(os.P_WAIT, AGENT_CLI, AGENT_CLI, role, str(thread_file))


if __name__ == "__main__":
    raise SystemExit(main())
