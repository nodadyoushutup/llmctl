from __future__ import annotations

from datetime import datetime


def source_scheduler_enabled() -> bool:
    """Stage 6 cutover: standalone source scheduler is retired."""
    return False


def source_scheduler_poll_seconds() -> float:
    return 0.0


def run_scheduled_source_indexes_once(*, now: datetime | None = None) -> int:
    _ = now
    return 0


def start_source_scheduler() -> None:
    return


def stop_source_scheduler(timeout: float = 2.0) -> None:
    _ = timeout
    return
