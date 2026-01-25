#!/usr/bin/env python3
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from sqlalchemy import select

try:
    import coloredlogs
except ModuleNotFoundError:
    coloredlogs = None

from core.config import Config
from core.db import init_db, init_engine, session_scope
from core.models import Role

REPO_ROOT = Path(__file__).resolve().parents[4]
CONVERSATIONS_DIR = os.getenv("CONVERSATIONS_DIR", "framework/docs/conversations")
PLANNING_DIR = os.getenv("PLANNING_DIR", "framework/docs/planning")
REQUIREMENTS_DIR = os.getenv("REQUIREMENTS_DIR", "framework/docs/requirements")
POLL_SECONDS = float(os.getenv("POLL_SECONDS", "1"))
AGENT_ROLE = os.getenv("AGENT_ROLE", "business-analyst")
AGENT_CLI = os.getenv("AGENT_CLI", "app/llmctl-studio/src/cli/agent-cli.py")
STATE_DIR = os.getenv("STATE_DIR", "data/.agent-state")
LOCK_DIR = os.getenv("LOCK_DIR", "data/.agent-locks")
ALLOW_IDLE_PROMPTS = os.getenv("ALLOW_IDLE_PROMPTS", "false").lower() == "true"
AGENT_NAME = os.getenv("AGENT_NAME")
AGENT_VERBOSE = os.getenv("AGENT_VERBOSE", "true").lower() == "true"
AGENT_LOG_FILE = os.getenv("AGENT_LOG_FILE", "app/llmctl-studio/llmctl-studio.log")
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"
LOG_COLOR = os.getenv("AGENT_LOG_COLOR", "auto").lower()


def _should_colorize(stream: object) -> bool:
    if LOG_COLOR in {"1", "true", "yes", "on", "always"}:
        return True
    if LOG_COLOR in {"0", "false", "no", "off", "never"}:
        return False
    isatty = getattr(stream, "isatty", None)
    if callable(isatty):
        try:
            return bool(isatty())
        except Exception:
            return False
    return False


class AnsiLevelFormatter(logging.Formatter):
    LEVEL_COLORS = {
        logging.DEBUG: "90",
        logging.INFO: "36",
        logging.WARNING: "33",
        logging.ERROR: "31",
        logging.CRITICAL: "41;97",
    }
    RESET = "\x1b[0m"
    PREFIX = "\x1b["

    def format(self, record: logging.LogRecord) -> str:
        original_level = record.levelname
        color = self.LEVEL_COLORS.get(record.levelno)
        if color:
            record.levelname = f"{self.PREFIX}{color}m{original_level}{self.RESET}"
        try:
            return super().format(record)
        finally:
            record.levelname = original_level



def default_agent_name() -> str:
    hostname = os.uname().nodename
    return f"{AGENT_ROLE}-{hostname}-{os.getpid()}"


if not AGENT_NAME:
    AGENT_NAME = default_agent_name()

LOGGER_NAME = f"agent-loop.{AGENT_NAME}"


def resolve_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def role_exists(role_name: str) -> bool:
    init_engine(Config.SQLALCHEMY_DATABASE_URI)
    init_db()
    with session_scope() as session:
        return (
            session.execute(select(Role.id).where(Role.name == role_name)).first()
            is not None
        )


def setup_logging() -> None:
    log_path = resolve_path(AGENT_LOG_FILE)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_level = logging.DEBUG if AGENT_VERBOSE else logging.INFO
    log_format = "%(asctime)s %(levelname)s %(name)s %(message)s"
    log_datefmt = LOG_DATEFMT

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(log_level)

    file_handler = logging.FileHandler(log_path)
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter(log_format, datefmt=log_datefmt))

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(log_level)
    use_color = _should_colorize(stream_handler.stream)
    stream_formatter = (
        AnsiLevelFormatter(log_format, datefmt=log_datefmt)
        if use_color
        else logging.Formatter(log_format, datefmt=log_datefmt)
    )
    stream_handler.setFormatter(stream_formatter)

    logger.handlers = []
    logger.addHandler(file_handler)

    if coloredlogs is not None:
        coloredlogs.install(
            level=log_level,
            logger=logger,
            fmt=log_format,
            datefmt=log_datefmt,
            stream=stream_handler.stream,
            isatty=use_color,
        )
    else:
        logger.addHandler(stream_handler)

    sys.stdout.flush()


def log(message: str) -> None:
    logging.getLogger(LOGGER_NAME).info(message)


def ensure_dirs() -> None:
    resolve_path(STATE_DIR).mkdir(parents=True, exist_ok=True)
    resolve_path(LOCK_DIR).mkdir(parents=True, exist_ok=True)


def lock_thread(thread: Path) -> bool:
    lock_dir = resolve_path(LOCK_DIR) / thread.name
    try:
        lock_dir.mkdir()
        return True
    except FileExistsError:
        return False


def unlock_thread(thread: Path) -> None:
    lock_dir = resolve_path(LOCK_DIR) / thread.name
    try:
        lock_dir.rmdir()
    except FileNotFoundError:
        return
    except OSError:
        return


def record_thread_activity(thread: Path) -> None:
    state_file = resolve_path(STATE_DIR) / thread.name
    state_file.touch()


def thread_has_new_activity(thread: Path) -> bool:
    state_file = resolve_path(STATE_DIR) / thread.name
    if not state_file.exists():
        return True
    return thread.stat().st_mtime > state_file.stat().st_mtime


def thread_has_question(thread: Path) -> bool:
    try:
        return any(line.startswith("Q:") for line in thread.read_text().splitlines())
    except FileNotFoundError:
        return False


def infer_role(thread: Path) -> str:
    try:
        for line in thread.read_text().splitlines():
            if line.startswith("Role:"):
                return line.split(":", 1)[1].strip()
    except FileNotFoundError:
        return AGENT_ROLE
    return AGENT_ROLE


def role_is_threaded() -> bool:
    return AGENT_ROLE in {"business-analyst", "user"}


def list_dir_markdown(directory: str) -> list[Path]:
    resolved = resolve_path(directory)
    if not resolved.exists():
        return []
    return sorted(resolved.glob("*.md"))


def list_threads() -> list[Path]:
    return list_dir_markdown(CONVERSATIONS_DIR)


def list_requirements() -> list[Path]:
    return list_dir_markdown(REQUIREMENTS_DIR)


def list_plans() -> list[Path]:
    return list_dir_markdown(PLANNING_DIR)


def plan_status(plan: Path) -> str:
    try:
        for line in plan.read_text().splitlines():
            if line.lower().startswith("- status:"):
                return line.split(":", 1)[1].strip().lower()
    except FileNotFoundError:
        return ""
    return ""


def plan_owner(plan: Path) -> str:
    try:
        for line in plan.read_text().splitlines():
            if line.lower().startswith("- owner:"):
                return line.split(":", 1)[1].strip()
    except FileNotFoundError:
        return "unassigned"
    return "unassigned"


def plan_has_owner(plan: Path) -> bool:
    owner = plan_owner(plan).lower()
    return owner not in {"", "unassigned"}


def claim_plan_owner(plan: Path) -> bool:
    if plan_has_owner(plan):
        return False

    try:
        lines = plan.read_text().splitlines()
    except FileNotFoundError:
        return False

    updated = False
    new_lines: list[str] = []
    for line in lines:
        if line.lower().startswith("- owner:"):
            new_lines.append(f"- Owner: {AGENT_NAME}")
            updated = True
        else:
            new_lines.append(line)

    if not updated:
        new_lines.append(f"- Owner: {AGENT_NAME}")

    tmp_path = plan.with_suffix(plan.suffix + ".tmp")
    tmp_path.write_text("\n".join(new_lines) + "\n")
    tmp_path.replace(plan)
    return True


def list_ready_plans() -> list[Path]:
    return [plan for plan in list_plans() if "ready" in plan_status(plan)]


def list_unowned_ready_plans() -> list[Path]:
    return [plan for plan in list_ready_plans() if not plan_has_owner(plan)]


def list_blocked_plans() -> list[Path]:
    return [plan for plan in list_plans() if "blocked" in plan_status(plan)]


def list_qa_plans() -> list[Path]:
    return [plan for plan in list_plans() if "needs qa" in plan_status(plan)]


def find_pending_threads() -> list[Path]:
    return [thread for thread in list_threads() if thread_has_question(thread)]


def discover_targets() -> list[Path]:
    if AGENT_ROLE in {"business-analyst", "user"}:
        return list_threads()
    if AGENT_ROLE == "coder":
        return list_unowned_ready_plans()
    if AGENT_ROLE == "qa":
        return list_qa_plans()
    if AGENT_ROLE == "tech-lead":
        return list_requirements() + list_blocked_plans()
    return list_threads()


def run_agent_prompt(prompt_file: Path, role: str) -> None:
    agent_cli_path = resolve_path(AGENT_CLI)
    log(f"Running agent CLI for {prompt_file.name} as role '{role}'")
    subprocess.run([str(agent_cli_path), role, str(prompt_file)], check=False)


def validate_agent_role() -> None:
    if not role_exists(AGENT_ROLE):
        raise ValueError(f"Unsupported AGENT_ROLE: {AGENT_ROLE}")


def main() -> None:
    validate_agent_role()
    ensure_dirs()
    setup_logging()
    log(
        f"Starting loop role={AGENT_ROLE}, name={AGENT_NAME}, poll={POLL_SECONDS}s, "
        f"cli={AGENT_CLI}, allow_idle={ALLOW_IDLE_PROMPTS}"
    )
    log(
        "Paths: "
        f"conversations={resolve_path(CONVERSATIONS_DIR)}, "
        f"planning={resolve_path(PLANNING_DIR)}, "
        f"requirements={resolve_path(REQUIREMENTS_DIR)}, "
        f"state={resolve_path(STATE_DIR)}, locks={resolve_path(LOCK_DIR)}"
    )
    try:
        while True:
            if role_is_threaded():
                threads = list_threads() if ALLOW_IDLE_PROMPTS else find_pending_threads()
            else:
                threads = discover_targets()

            log(f"Discovered {len(threads)} target(s) to consider")
            processed = False
            for thread in threads:
                if not thread_has_new_activity(thread):
                    continue

                if role_is_threaded():
                    if not ALLOW_IDLE_PROMPTS and not thread_has_question(thread):
                        record_thread_activity(thread)
                        continue
                    role = infer_role(thread)
                else:
                    role = AGENT_ROLE

                if lock_thread(thread):
                    try:
                        log(f"Processing {thread.name} as role '{role}'")
                        if AGENT_ROLE == "coder":
                            claim_plan_owner(thread)
                        run_agent_prompt(thread, role)
                        record_thread_activity(thread)
                        processed = True
                    finally:
                        unlock_thread(thread)

            if not processed:
                log(f"No runnable targets. Sleeping for {POLL_SECONDS}s")
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        log("Shutting down on Ctrl+C")


if __name__ == "__main__":
    main()
