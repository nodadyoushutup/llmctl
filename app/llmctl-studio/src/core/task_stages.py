from __future__ import annotations

TASK_STAGE_ORDER: list[tuple[str, str]] = [
    ("integration", "Integration"),
    ("pre_init", "Pre Init"),
    ("init", "Init"),
    ("post_init", "Post Init"),
    ("llm_query", "LLM Query"),
    ("post_run", "Post Autorun"),
]

TASK_STAGE_LABELS = dict(TASK_STAGE_ORDER)


def task_stage_label(stage_key: str) -> str:
    return TASK_STAGE_LABELS.get(stage_key, stage_key)
