from __future__ import annotations

QUICK_TASK_KIND = "quick"
LEGACY_CHAT_TASK_KIND = "chat"
QUICK_TASK_KINDS = {QUICK_TASK_KIND, LEGACY_CHAT_TASK_KIND}
RAG_QUICK_INDEX_TASK_KIND = "rag_quick_index"
RAG_QUICK_DELTA_TASK_KIND = "rag_quick_delta_index"
RAG_QUICK_TASK_KINDS = {
    RAG_QUICK_INDEX_TASK_KIND,
    RAG_QUICK_DELTA_TASK_KIND,
}


def is_quick_task_kind(kind: str | None) -> bool:
    return kind in QUICK_TASK_KINDS


def is_quick_rag_task_kind(kind: str | None) -> bool:
    return kind in RAG_QUICK_TASK_KINDS


def task_kind_label(kind: str | None) -> str:
    if kind == RAG_QUICK_INDEX_TASK_KIND:
        return "Quick RAG • Index"
    if kind == RAG_QUICK_DELTA_TASK_KIND:
        return "Quick RAG • Delta Index"
    if is_quick_task_kind(kind):
        return "Quick Node"
    if not kind:
        return "task"
    return kind
