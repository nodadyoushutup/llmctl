from __future__ import annotations

from dataclasses import dataclass

from services.integrations import load_integration_settings, save_integration_settings

CHAT_RUNTIME_SETTINGS_PROVIDER = "chat_runtime"

CHAT_RUNTIME_DEFAULTS: dict[str, str] = {
    "history_budget_percent": "60",
    "rag_budget_percent": "25",
    "mcp_budget_percent": "15",
    "compaction_trigger_percent": "100",
    "compaction_target_percent": "85",
    "preserve_recent_turns": "4",
    "rag_top_k": "5",
    "default_context_window_tokens": "16000",
    "max_compaction_summary_chars": "2400",
}


def _as_int_range(value: str | None, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int((value or "").strip())
    except (TypeError, ValueError):
        return default
    if parsed < minimum:
        return minimum
    if parsed > maximum:
        return maximum
    return parsed


@dataclass(frozen=True, slots=True)
class ChatRuntimeSettings:
    history_budget_percent: int
    rag_budget_percent: int
    mcp_budget_percent: int
    compaction_trigger_percent: int
    compaction_target_percent: int
    preserve_recent_turns: int
    rag_top_k: int
    default_context_window_tokens: int
    max_compaction_summary_chars: int


def _normalized_settings_values(raw: dict[str, str]) -> dict[str, int]:
    history = _as_int_range(
        raw.get("history_budget_percent"),
        int(CHAT_RUNTIME_DEFAULTS["history_budget_percent"]),
        10,
        90,
    )
    rag = _as_int_range(
        raw.get("rag_budget_percent"),
        int(CHAT_RUNTIME_DEFAULTS["rag_budget_percent"]),
        0,
        80,
    )
    if history + rag > 95:
        rag = max(0, 95 - history)
    mcp = max(0, 100 - history - rag)
    trigger = _as_int_range(
        raw.get("compaction_trigger_percent"),
        int(CHAT_RUNTIME_DEFAULTS["compaction_trigger_percent"]),
        70,
        100,
    )
    target = _as_int_range(
        raw.get("compaction_target_percent"),
        int(CHAT_RUNTIME_DEFAULTS["compaction_target_percent"]),
        40,
        99,
    )
    if target >= trigger:
        target = max(40, trigger - 1)
    return {
        "history_budget_percent": history,
        "rag_budget_percent": rag,
        "mcp_budget_percent": mcp,
        "compaction_trigger_percent": trigger,
        "compaction_target_percent": target,
        "preserve_recent_turns": _as_int_range(
            raw.get("preserve_recent_turns"),
            int(CHAT_RUNTIME_DEFAULTS["preserve_recent_turns"]),
            1,
            20,
        ),
        "rag_top_k": _as_int_range(
            raw.get("rag_top_k"),
            int(CHAT_RUNTIME_DEFAULTS["rag_top_k"]),
            1,
            50,
        ),
        "default_context_window_tokens": _as_int_range(
            raw.get("default_context_window_tokens"),
            int(CHAT_RUNTIME_DEFAULTS["default_context_window_tokens"]),
            1024,
            1000000,
        ),
        "max_compaction_summary_chars": _as_int_range(
            raw.get("max_compaction_summary_chars"),
            int(CHAT_RUNTIME_DEFAULTS["max_compaction_summary_chars"]),
            200,
            10000,
        ),
    }


def load_chat_runtime_settings() -> ChatRuntimeSettings:
    raw = dict(CHAT_RUNTIME_DEFAULTS)
    raw.update(load_integration_settings(CHAT_RUNTIME_SETTINGS_PROVIDER))
    values = _normalized_settings_values(raw)
    return ChatRuntimeSettings(
        history_budget_percent=values["history_budget_percent"],
        rag_budget_percent=values["rag_budget_percent"],
        mcp_budget_percent=values["mcp_budget_percent"],
        compaction_trigger_percent=values["compaction_trigger_percent"],
        compaction_target_percent=values["compaction_target_percent"],
        preserve_recent_turns=values["preserve_recent_turns"],
        rag_top_k=values["rag_top_k"],
        default_context_window_tokens=values["default_context_window_tokens"],
        max_compaction_summary_chars=values["max_compaction_summary_chars"],
    )


def load_chat_runtime_settings_payload() -> dict[str, str]:
    values = load_chat_runtime_settings()
    return {
        "history_budget_percent": str(values.history_budget_percent),
        "rag_budget_percent": str(values.rag_budget_percent),
        "mcp_budget_percent": str(values.mcp_budget_percent),
        "compaction_trigger_percent": str(values.compaction_trigger_percent),
        "compaction_target_percent": str(values.compaction_target_percent),
        "preserve_recent_turns": str(values.preserve_recent_turns),
        "rag_top_k": str(values.rag_top_k),
        "default_context_window_tokens": str(values.default_context_window_tokens),
        "max_compaction_summary_chars": str(values.max_compaction_summary_chars),
    }


def save_chat_runtime_settings(payload: dict[str, str]) -> None:
    merged = dict(CHAT_RUNTIME_DEFAULTS)
    merged.update(payload)
    values = _normalized_settings_values(merged)
    serialized = {key: str(value) for key, value in values.items()}
    save_integration_settings(CHAT_RUNTIME_SETTINGS_PROVIDER, serialized)
