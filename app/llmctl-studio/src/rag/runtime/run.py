from __future__ import annotations

from rag.web.scheduler import start_source_scheduler, stop_source_scheduler


def start_rag_runtime() -> None:
    start_source_scheduler()


def stop_rag_runtime() -> None:
    stop_source_scheduler()
