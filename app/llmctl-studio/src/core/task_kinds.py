from __future__ import annotations

QUICK_TASK_KIND = "quick"
LEGACY_CHAT_TASK_KIND = "chat"
QUICK_TASK_KINDS = {QUICK_TASK_KIND, LEGACY_CHAT_TASK_KIND}


def is_quick_task_kind(kind: str | None) -> bool:
    return kind in QUICK_TASK_KINDS


def task_kind_label(kind: str | None) -> str:
    if is_quick_task_kind(kind):
        return "Quick Node"
    if not kind:
        return "task"
    return kind
