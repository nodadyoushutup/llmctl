from __future__ import annotations

import json
import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import selectinload

from chat.contracts import (
    CHAT_EVENT_CLASS_COMPACTION,
    CHAT_EVENT_CLASS_FAILURE,
    CHAT_EVENT_CLASS_RETRIEVAL_TOOL,
    CHAT_EVENT_CLASS_THREAD,
    CHAT_EVENT_CLASS_TURN,
    CHAT_EVENT_TYPE_COMPACTED,
    CHAT_EVENT_TYPE_FAILED,
    CHAT_EVENT_TYPE_RETRIEVAL_USED,
    CHAT_EVENT_TYPE_THREAD_ARCHIVED,
    CHAT_EVENT_TYPE_THREAD_CLEARED,
    CHAT_EVENT_TYPE_THREAD_CREATED,
    CHAT_EVENT_TYPE_THREAD_DELETED,
    CHAT_EVENT_TYPE_THREAD_RESTORED,
    CHAT_EVENT_TYPE_TOOL_USED,
    CHAT_EVENT_TYPE_TURN_REQUESTED,
    CHAT_EVENT_TYPE_TURN_RESPONDED,
    CHAT_REASON_MCP_FAILED,
    CHAT_REASON_MODEL_FAILED,
    RAG_REASON_RETRIEVAL_FAILED,
    RAG_REASON_UNAVAILABLE,
    RAGHealth,
    RAG_HEALTH_CONFIGURED_HEALTHY,
    RAG_HEALTH_UNCONFIGURED,
    RAGContractError,
    RAGRetrievalRequest,
)
from chat.rag_client import RAGContractClient, get_rag_contract_client
from chat.settings import (
    ChatRuntimeSettings,
    load_chat_default_settings_payload,
    load_chat_runtime_settings,
)
from core.db import session_scope, utcnow
from core.mcp_config import parse_mcp_config
from core.models import (
    CHAT_THREAD_STATUS_ACTIVE,
    CHAT_THREAD_STATUS_ARCHIVED,
    CHAT_TURN_STATUS_FAILED,
    CHAT_TURN_STATUS_SUCCEEDED,
    ChatActivityEvent,
    ChatMessage,
    ChatThread,
    ChatTurn,
    LLMModel,
    MCPServer,
    chat_thread_mcp_servers,
)
from services.integrations import load_integration_settings, resolve_default_model_id
from services.tasks import _run_llm

CHAT_CONTEXT_CHARS_PER_TOKEN = 4
CHAT_DEFAULT_THREAD_TITLE = "New Chat"
CHAT_LEGACY_DEFAULT_THREAD_TITLE = "New chat"
CHAT_AUTO_TITLE_MAX_CHARS = 72
CHAT_TITLE_SMALL_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "but",
    "by",
    "for",
    "from",
    "in",
    "nor",
    "of",
    "on",
    "or",
    "per",
    "so",
    "the",
    "to",
    "via",
    "with",
    "yet",
}
CHAT_TITLE_ACRONYMS = {
    "api",
    "cli",
    "cpu",
    "css",
    "gpu",
    "html",
    "http",
    "https",
    "json",
    "jwt",
    "llm",
    "mcp",
    "rag",
    "sdk",
    "sql",
    "ssh",
    "tcp",
    "tls",
    "udp",
    "ui",
    "url",
    "ux",
    "xml",
    "yaml",
}
CHAT_TITLE_LEADING_PATTERNS = (
    r"^(?:can|could|would|will)\s+you\s+",
    r"^please\s+",
    r"^help\s+me\s+(?:with\s+)?",
    r"^i\s+need\s+(?:help\s+)?(?:to\s+|with\s+)?",
    r"^i\s+want\s+to\s+",
    r"^is\s+there\s+(?:a|an|any)\s+way\s+(?:to\s+)?",
    r"^how\s+do\s+i\s+",
    r"^what(?:'s|\s+is)\s+the\s+best\s+way\s+to\s+",
    r"^we\s+could\s+",
)
CHAT_RESPONSE_COMPLEXITY_LOW = "low"
CHAT_RESPONSE_COMPLEXITY_MEDIUM = "medium"
CHAT_RESPONSE_COMPLEXITY_HIGH = "high"
CHAT_RESPONSE_COMPLEXITY_EXTRA_HIGH = "extra_high"
CHAT_RESPONSE_COMPLEXITY_CHOICES = (
    CHAT_RESPONSE_COMPLEXITY_LOW,
    CHAT_RESPONSE_COMPLEXITY_MEDIUM,
    CHAT_RESPONSE_COMPLEXITY_HIGH,
    CHAT_RESPONSE_COMPLEXITY_EXTRA_HIGH,
)
CHAT_RESPONSE_COMPLEXITY_ALIASES = {
    "concise": CHAT_RESPONSE_COMPLEXITY_LOW,
    "brief": CHAT_RESPONSE_COMPLEXITY_LOW,
    "balanced": CHAT_RESPONSE_COMPLEXITY_MEDIUM,
    "detailed": CHAT_RESPONSE_COMPLEXITY_HIGH,
    "verbose": CHAT_RESPONSE_COMPLEXITY_HIGH,
    "extra high": CHAT_RESPONSE_COMPLEXITY_EXTRA_HIGH,
    "extra-high": CHAT_RESPONSE_COMPLEXITY_EXTRA_HIGH,
    "extra": CHAT_RESPONSE_COMPLEXITY_EXTRA_HIGH,
    "very_high": CHAT_RESPONSE_COMPLEXITY_EXTRA_HIGH,
}
CHAT_RESPONSE_COMPLEXITY_LABELS = {
    CHAT_RESPONSE_COMPLEXITY_LOW: "Low",
    CHAT_RESPONSE_COMPLEXITY_MEDIUM: "Medium",
    CHAT_RESPONSE_COMPLEXITY_HIGH: "High",
    CHAT_RESPONSE_COMPLEXITY_EXTRA_HIGH: "Extra High",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_json_load(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _safe_json_dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def normalize_response_complexity(
    value: str | None,
    *,
    default: str = CHAT_RESPONSE_COMPLEXITY_MEDIUM,
) -> str:
    candidate = str(value or "").strip().lower()
    candidate = candidate.replace("-", "_").replace(" ", "_")
    candidate = CHAT_RESPONSE_COMPLEXITY_ALIASES.get(candidate, candidate)
    if candidate in CHAT_RESPONSE_COMPLEXITY_CHOICES:
        return candidate
    if default in CHAT_RESPONSE_COMPLEXITY_CHOICES:
        return default
    return CHAT_RESPONSE_COMPLEXITY_MEDIUM


def response_complexity_label(value: str | None) -> str:
    normalized = normalize_response_complexity(value)
    return CHAT_RESPONSE_COMPLEXITY_LABELS.get(
        normalized, CHAT_RESPONSE_COMPLEXITY_LABELS[CHAT_RESPONSE_COMPLEXITY_MEDIUM]
    )


def _estimate_tokens(text: str) -> int:
    cleaned = (text or "").strip()
    if not cleaned:
        return 0
    return max(1, math.ceil(len(cleaned) / CHAT_CONTEXT_CHARS_PER_TOKEN))


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _select_title_candidate(message: str) -> str:
    parts = [
        _collapse_whitespace(part)
        for part in re.split(r"(?<=[.!?])\s+|\n+", message)
    ]
    candidates = [part for part in parts if part]
    if not candidates:
        return message
    question = next((part for part in candidates if "?" in part), None)
    selected = question if question else candidates[0]
    return selected.strip().strip(".,!?")


def _strip_prompt_prefixes(text: str) -> str:
    value = text
    while value:
        updated = value
        for pattern in CHAT_TITLE_LEADING_PATTERNS:
            updated = re.sub(pattern, "", updated, flags=re.IGNORECASE).strip()
        if updated == value:
            break
        value = updated
    return value


def _title_case_word(word: str, index: int, last_index: int) -> str:
    if not word:
        return word
    match = re.match(r"^([^A-Za-z0-9]*)(.*?)([^A-Za-z0-9]*)$", word)
    if not match:
        return word
    lead, core, tail = match.groups()
    if not core:
        return word
    lower_core = core.lower()
    if lower_core in CHAT_TITLE_ACRONYMS:
        transformed = lower_core.upper()
    elif any(ch.isupper() for ch in core[1:]) or any(ch.isdigit() for ch in core):
        transformed = core
    elif index not in (0, last_index) and lower_core in CHAT_TITLE_SMALL_WORDS:
        transformed = lower_core
    else:
        transformed = lower_core.capitalize()
    return f"{lead}{transformed}{tail}"


def _smart_title_case(text: str) -> str:
    words = text.split(" ")
    if not words:
        return text
    last_index = len(words) - 1
    return " ".join(
        _title_case_word(word, idx, last_index)
        for idx, word in enumerate(words)
    )


def _truncate_title(title: str, *, max_chars: int) -> str:
    if len(title) <= max_chars:
        return title
    cutoff = max(1, max_chars - 3)
    clipped = title[:cutoff].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0].rstrip(" ,;:-")
    if not clipped:
        clipped = title[:cutoff].rstrip()
    return f"{clipped}..."


def _derive_thread_title(message: str) -> str:
    cleaned = _collapse_whitespace(message)
    if not cleaned:
        return CHAT_DEFAULT_THREAD_TITLE
    candidate = _select_title_candidate(cleaned)
    candidate = _strip_prompt_prefixes(candidate)
    candidate = _collapse_whitespace(candidate.strip(" \"'`*_"))
    if not candidate:
        return CHAT_DEFAULT_THREAD_TITLE
    candidate = _smart_title_case(candidate)
    return _truncate_title(candidate, max_chars=CHAT_AUTO_TITLE_MAX_CHARS)


def _unique_ordered(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return ordered


def _parse_model_config(raw: str | None) -> dict[str, Any]:
    payload = _safe_json_load(raw)
    return payload if isinstance(payload, dict) else {}


def _resolve_thread_default_model(session) -> LLMModel | None:
    candidate_ids: list[int] = []
    chat_defaults = load_chat_default_settings_payload()
    chat_default_id = chat_defaults.get("default_model_id")
    if isinstance(chat_default_id, int):
        candidate_ids.append(chat_default_id)

    llm_default_id = resolve_default_model_id(load_integration_settings("llm"))
    if isinstance(llm_default_id, int) and llm_default_id not in candidate_ids:
        candidate_ids.append(llm_default_id)

    for model_id in candidate_ids:
        model = session.get(LLMModel, model_id)
        if model is not None:
            return model

    return (
        session.execute(select(LLMModel).order_by(LLMModel.created_at.desc()).limit(1))
        .scalars()
        .first()
    )


def _model_context_window_tokens(
    model: LLMModel,
    settings: ChatRuntimeSettings,
) -> int:
    config = _parse_model_config(model.config_json)
    for key in ("context_window_tokens", "context_window", "max_context_tokens"):
        value = config.get(key)
        if value is None:
            continue
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return settings.default_context_window_tokens


def _parse_summary_text(raw_json: str | None) -> str:
    payload = _safe_json_load(raw_json)
    if not isinstance(payload, dict):
        return ""
    text = payload.get("summary_text")
    return text.strip() if isinstance(text, str) else ""


def _build_compaction_summary(
    messages: list[ChatMessage],
    existing_summary: str,
    max_chars: int,
) -> str:
    parts: list[str] = []
    if existing_summary.strip():
        parts.append(existing_summary.strip())
    for message in messages:
        role = "User" if message.role == "user" else "Assistant"
        excerpt = (message.content or "").strip().replace("\n", " ")
        if len(excerpt) > 220:
            excerpt = f"{excerpt[:217]}..."
        if excerpt:
            parts.append(f"- {role}: {excerpt}")
    summary = "\n".join(parts).strip()
    if len(summary) <= max_chars:
        return summary
    if max_chars < 10:
        return summary[:max_chars]
    return f"{summary[: max_chars - 3].rstrip()}..."


def _render_history_block(summary_text: str, messages: list[ChatMessage]) -> str:
    chunks: list[str] = []
    if summary_text.strip():
        chunks.append(f"Conversation summary:\n{summary_text.strip()}")
    if messages:
        lines: list[str] = []
        for item in messages:
            label = "User" if item.role == "user" else "Assistant"
            lines.append(f"{label}: {item.content}")
        chunks.append("Recent conversation:\n" + "\n".join(lines))
    return "\n\n".join(chunks).strip()


def _serialize_thread_row(thread: ChatThread) -> dict[str, Any]:
    rag_payload = _safe_json_load(thread.selected_rag_collections_json)
    rag_collections = rag_payload if isinstance(rag_payload, list) else []
    normalized_complexity = normalize_response_complexity(thread.response_complexity)
    return {
        "id": thread.id,
        "title": thread.title,
        "status": thread.status,
        "model_id": thread.model_id,
        "model_name": thread.model.name if thread.model is not None else None,
        "response_complexity": normalized_complexity,
        "response_complexity_label": response_complexity_label(normalized_complexity),
        "rag_collections": [str(item) for item in rag_collections if str(item).strip()],
        "mcp_servers": [
            {"id": server.id, "name": server.name, "server_key": server.server_key}
            for server in thread.mcp_servers
        ],
        "last_activity_at": thread.last_activity_at,
        "updated_at": thread.updated_at,
        "created_at": thread.created_at,
    }


def _record_activity(
    session,
    *,
    thread_id: int,
    event_class: str,
    event_type: str,
    turn_id: int | None = None,
    reason_code: str | None = None,
    message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ChatActivityEvent:
    return ChatActivityEvent.create(
        session,
        thread_id=thread_id,
        turn_id=turn_id,
        event_class=event_class,
        event_type=event_type,
        reason_code=reason_code,
        message=message,
        metadata_json=_safe_json_dump(metadata or {}),
    )


def list_threads(include_archived: bool = False) -> list[dict[str, Any]]:
    with session_scope() as session:
        stmt = (
            select(ChatThread)
            .options(
                selectinload(ChatThread.model),
                selectinload(ChatThread.mcp_servers),
            )
            .order_by(
                ChatThread.last_activity_at.desc().nullslast(),
                ChatThread.updated_at.desc(),
            )
        )
        if not include_archived:
            stmt = stmt.where(ChatThread.status == CHAT_THREAD_STATUS_ACTIVE)
        rows = session.execute(stmt).scalars().all()
        return [_serialize_thread_row(row) for row in rows]


def get_thread(thread_id: int) -> dict[str, Any] | None:
    with session_scope() as session:
        thread = (
            session.execute(
                select(ChatThread)
                .options(
                    selectinload(ChatThread.model),
                    selectinload(ChatThread.mcp_servers),
                    selectinload(ChatThread.messages),
                    selectinload(ChatThread.turns),
                )
                .where(ChatThread.id == thread_id)
            )
            .scalars()
            .first()
        )
        if thread is None:
            return None
        row = _serialize_thread_row(thread)
        row["messages"] = [
            {
                "id": item.id,
                "role": item.role,
                "content": item.content,
                "created_at": item.created_at,
            }
            for item in thread.messages
        ]
        summary_text = _parse_summary_text(thread.compaction_summary_json)
        row["compaction_summary_text"] = summary_text
        latest_turn = thread.turns[-1] if thread.turns else None
        row["latest_turn"] = (
            {
                "id": latest_turn.id,
                "status": latest_turn.status,
                "reason_code": latest_turn.reason_code,
                "context_usage_before": latest_turn.context_usage_before,
                "context_usage_after": latest_turn.context_usage_after,
                "context_limit_tokens": latest_turn.context_limit_tokens,
                "compaction_applied": bool(latest_turn.compaction_applied),
                "created_at": latest_turn.created_at,
            }
            if latest_turn is not None
            else None
        )
        return row


def create_thread(
    *,
    title: str,
    model_id: int | None,
    mcp_server_ids: list[int] | None = None,
    rag_collections: list[str] | None = None,
    response_complexity: str | None = None,
) -> dict[str, Any]:
    with session_scope() as session:
        selected_model_id = model_id
        if selected_model_id is not None:
            if session.get(LLMModel, selected_model_id) is None:
                raise ValueError("Selected model does not exist.")
        selected_mcp_ids = [int(item) for item in (mcp_server_ids or [])]
        selected_servers: list[MCPServer] = []
        if selected_mcp_ids:
            selected_servers = (
                session.execute(select(MCPServer).where(MCPServer.id.in_(selected_mcp_ids)))
                .scalars()
                .all()
            )
            if len(selected_servers) != len(set(selected_mcp_ids)):
                raise ValueError("One or more selected MCP servers do not exist.")
            by_id = {item.id: item for item in selected_servers}
            selected_servers = [by_id[item] for item in selected_mcp_ids if item in by_id]
        thread = ChatThread.create(
            session,
            title=(title or "").strip() or CHAT_DEFAULT_THREAD_TITLE,
            status=CHAT_THREAD_STATUS_ACTIVE,
            model_id=selected_model_id,
            response_complexity=normalize_response_complexity(response_complexity),
            selected_rag_collections_json=_safe_json_dump(
                _unique_ordered([str(item) for item in (rag_collections or [])])
            ),
            compaction_summary_json=_safe_json_dump({}),
            last_activity_at=utcnow(),
        )
        thread.mcp_servers = selected_servers
        _record_activity(
            session,
            thread_id=thread.id,
            event_class=CHAT_EVENT_CLASS_THREAD,
            event_type=CHAT_EVENT_TYPE_THREAD_CREATED,
        )
        session.flush()
        return _serialize_thread_row(thread)


def update_thread_config(
    thread_id: int,
    *,
    model_id: int | None,
    mcp_server_ids: list[int],
    rag_collections: list[str],
    response_complexity: str | None,
) -> dict[str, Any]:
    with session_scope() as session:
        thread = (
            session.execute(
                select(ChatThread)
                .options(selectinload(ChatThread.mcp_servers), selectinload(ChatThread.model))
                .where(ChatThread.id == thread_id)
            )
            .scalars()
            .first()
        )
        if thread is None:
            raise ValueError("Thread not found.")
        if model_id is not None and session.get(LLMModel, model_id) is None:
            raise ValueError("Selected model does not exist.")
        selected_servers: list[MCPServer] = []
        if mcp_server_ids:
            selected_servers = (
                session.execute(select(MCPServer).where(MCPServer.id.in_(mcp_server_ids)))
                .scalars()
                .all()
            )
            if len(selected_servers) != len(set(mcp_server_ids)):
                raise ValueError("One or more selected MCP servers do not exist.")
            by_id = {server.id: server for server in selected_servers}
            selected_servers = [by_id[item] for item in mcp_server_ids if item in by_id]
        thread.model_id = model_id
        thread.response_complexity = normalize_response_complexity(response_complexity)
        thread.selected_rag_collections_json = _safe_json_dump(_unique_ordered(rag_collections))
        thread.mcp_servers = selected_servers
        thread.updated_at = _now()
        session.flush()
        return _serialize_thread_row(thread)


def archive_thread(thread_id: int) -> bool:
    with session_scope() as session:
        thread = session.get(ChatThread, thread_id)
        if thread is None:
            return False
        thread.status = CHAT_THREAD_STATUS_ARCHIVED
        _record_activity(
            session,
            thread_id=thread.id,
            event_class=CHAT_EVENT_CLASS_THREAD,
            event_type=CHAT_EVENT_TYPE_THREAD_ARCHIVED,
        )
        return True


def restore_thread(thread_id: int) -> bool:
    with session_scope() as session:
        thread = session.get(ChatThread, thread_id)
        if thread is None:
            return False
        thread.status = CHAT_THREAD_STATUS_ACTIVE
        _record_activity(
            session,
            thread_id=thread.id,
            event_class=CHAT_EVENT_CLASS_THREAD,
            event_type=CHAT_EVENT_TYPE_THREAD_RESTORED,
        )
        return True


def clear_thread(thread_id: int) -> bool:
    with session_scope() as session:
        thread = session.get(ChatThread, thread_id)
        if thread is None:
            return False
        session.execute(
            update(ChatActivityEvent)
            .where(ChatActivityEvent.thread_id == thread_id)
            .values(turn_id=None)
        )
        session.execute(delete(ChatMessage).where(ChatMessage.thread_id == thread_id))
        session.execute(delete(ChatTurn).where(ChatTurn.thread_id == thread_id))
        thread.compaction_summary_json = _safe_json_dump({})
        thread.last_activity_at = _now()
        _record_activity(
            session,
            thread_id=thread.id,
            event_class=CHAT_EVENT_CLASS_THREAD,
            event_type=CHAT_EVENT_TYPE_THREAD_CLEARED,
        )
        return True


def delete_thread(thread_id: int) -> bool:
    with session_scope() as session:
        thread = session.get(ChatThread, thread_id)
        if thread is None:
            return False
        _record_activity(
            session,
            thread_id=thread.id,
            event_class=CHAT_EVENT_CLASS_THREAD,
            event_type=CHAT_EVENT_TYPE_THREAD_DELETED,
        )
        session.flush()
        session.delete(thread)
        return True


def list_activity(
    *,
    event_class: str | None = None,
    event_type: str | None = None,
    reason_code: str | None = None,
    thread_id: int | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    with session_scope() as session:
        stmt = (
            select(ChatActivityEvent, ChatThread.title)
            .join(ChatThread, ChatThread.id == ChatActivityEvent.thread_id)
            .order_by(ChatActivityEvent.created_at.desc())
            .limit(max(1, min(limit, 1000)))
        )
        if event_class:
            stmt = stmt.where(ChatActivityEvent.event_class == event_class)
        if event_type:
            stmt = stmt.where(ChatActivityEvent.event_type == event_type)
        if reason_code:
            stmt = stmt.where(ChatActivityEvent.reason_code == reason_code)
        if thread_id is not None:
            stmt = stmt.where(ChatActivityEvent.thread_id == thread_id)
        rows = session.execute(stmt).all()
        payload: list[dict[str, Any]] = []
        for event, title in rows:
            metadata = _safe_json_load(event.metadata_json)
            payload.append(
                {
                    "id": event.id,
                    "thread_id": event.thread_id,
                    "thread_title": title,
                    "turn_id": event.turn_id,
                    "event_class": event.event_class,
                    "event_type": event.event_type,
                    "reason_code": event.reason_code,
                    "message": event.message,
                    "metadata": metadata if isinstance(metadata, dict) else {},
                    "created_at": event.created_at,
                }
            )
        return payload


@dataclass(slots=True)
class TurnResult:
    ok: bool
    thread_id: int
    turn_id: int
    request_id: str
    reply: str | None = None
    reason_code: str | None = None
    error: str | None = None
    rag_health_state: str = RAG_HEALTH_UNCONFIGURED
    selected_collections: list[str] = field(default_factory=list)


def _build_prompt(
    *,
    history_block: str,
    retrieval_context: list[str],
    selected_rag_collections: list[str],
    selected_mcp_server_keys: list[str],
    response_complexity: str,
    user_message: str,
) -> str:
    normalized_complexity = normalize_response_complexity(response_complexity)
    if normalized_complexity == CHAT_RESPONSE_COMPLEXITY_LOW:
        complexity_instruction = (
            "Response complexity: LOW. Keep a natural, conversational tone. Be concise "
            "and direct, focusing on essentials only."
        )
    elif normalized_complexity == CHAT_RESPONSE_COMPLEXITY_MEDIUM:
        complexity_instruction = (
            "Response complexity: MEDIUM. Keep a natural, conversational tone with a "
            "balanced level of detail. Do not force a fixed output template."
        )
    elif normalized_complexity == CHAT_RESPONSE_COMPLEXITY_HIGH:
        complexity_instruction = (
            "Response complexity: HIGH. Keep a natural, conversational tone while "
            "providing detailed explanations, reasoning, and relevant caveats."
        )
    else:
        complexity_instruction = (
            "Response complexity: EXTRA HIGH. Keep a natural, conversational tone while "
            "being exhaustive and completeness-focused. Use comprehensive Markdown "
            "tables when requested or when tabular format clearly improves clarity, and "
            "ensure requested fields are not omitted."
        )
    sections = [
        "You are a helpful assistant in a multi-turn chat session.",
        "Respond directly to the latest user message.",
        complexity_instruction,
        (
            "Use Markdown when it improves clarity (headings, lists, tables, and "
            "fenced code blocks)."
        ),
    ]
    if history_block:
        sections.append(history_block)
    if selected_rag_collections:
        sections.append(
            "RAG collections are selected for this session. Use only the retrieved "
            "context for repository/file facts. Do not inspect local files, tools, "
            "or prior knowledge for those facts. If retrieved context is missing or "
            "insufficient, say so explicitly."
        )
    if retrieval_context:
        blocks = [f"[{idx}] {text}" for idx, text in enumerate(retrieval_context, start=1)]
        sections.append("Retrieved context:\n" + "\n".join(blocks))
    if selected_mcp_server_keys:
        sections.append(
            "Enabled MCP servers for this session: "
            + ", ".join(selected_mcp_server_keys)
            + "."
        )
    sections.append(f"Latest user message:\n{user_message}")
    return "\n\n".join(sections).strip()


def execute_turn(
    *,
    thread_id: int,
    message: str,
    rag_client: RAGContractClient | None = None,
) -> TurnResult:
    cleaned_message = (message or "").strip()
    if not cleaned_message:
        raise ValueError("Message is required.")
    client = rag_client or get_rag_contract_client()
    settings = load_chat_runtime_settings()
    request_id = uuid.uuid4().hex
    with session_scope() as session:
        thread = (
            session.execute(
                select(ChatThread)
                .options(
                    selectinload(ChatThread.messages),
                    selectinload(ChatThread.mcp_servers),
                    selectinload(ChatThread.model),
                )
                .where(ChatThread.id == thread_id)
            )
            .scalars()
            .first()
        )
        if thread is None:
            raise ValueError("Thread not found.")
        model = thread.model
        if model is None:
            model = _resolve_thread_default_model(session)
            if model is None:
                raise ValueError("No models available for Chat.")
            thread.model_id = model.id
            thread.model = model
        selected_response_complexity = normalize_response_complexity(
            thread.response_complexity
        )
        thread.response_complexity = selected_response_complexity

        selected_rag_collections_payload = _safe_json_load(thread.selected_rag_collections_json)
        selected_rag_collections = (
            _unique_ordered([str(item) for item in selected_rag_collections_payload])
            if isinstance(selected_rag_collections_payload, list)
            else []
        )
        mcp_servers = list(thread.mcp_servers)
        selected_mcp_keys = [server.server_key for server in mcp_servers]
        user_message = ChatMessage.create(
            session,
            thread_id=thread.id,
            role="user",
            content=cleaned_message,
            token_estimate=_estimate_tokens(cleaned_message),
            metadata_json=_safe_json_dump({}),
        )
        turn = ChatTurn.create(
            session,
            thread_id=thread.id,
            request_id=request_id,
            model_id=model.id,
            user_message_id=user_message.id,
            status=CHAT_TURN_STATUS_FAILED,
            selected_rag_collections_json=_safe_json_dump(selected_rag_collections),
            selected_mcp_server_keys_json=_safe_json_dump(selected_mcp_keys),
            rag_health_state=RAG_HEALTH_UNCONFIGURED,
        )
        _record_activity(
            session,
            thread_id=thread.id,
            turn_id=turn.id,
            event_class=CHAT_EVENT_CLASS_TURN,
            event_type=CHAT_EVENT_TYPE_TURN_REQUESTED,
            metadata={
                "request_id": request_id,
                "model_id": model.id,
                "response_complexity": selected_response_complexity,
                "selected_collections": selected_rag_collections,
                "selected_mcp_servers": selected_mcp_keys,
            },
        )

        rag_health_error: RAGContractError | None = None
        try:
            rag_health = client.health()
        except RAGContractError as exc:
            rag_health_error = exc
            rag_health = RAGHealth(
                state=RAG_HEALTH_UNCONFIGURED,
                provider="unknown",
                error=str(exc),
            )
        except Exception as exc:
            rag_health_error = RAGContractError(
                reason_code=RAG_REASON_RETRIEVAL_FAILED,
                message="RAG health check failed unexpectedly.",
                metadata={"exception_type": type(exc).__name__},
            )
            rag_health = RAGHealth(
                state=RAG_HEALTH_UNCONFIGURED,
                provider="unknown",
                error=str(exc),
            )

        turn.rag_health_state = rag_health.state
        if selected_rag_collections and rag_health_error is not None:
            turn.reason_code = rag_health_error.reason_code or RAG_REASON_RETRIEVAL_FAILED
            turn.error_message = str(rag_health_error)
            turn.runtime_metadata_json = _safe_json_dump(
                {
                    "rag_health_state": rag_health.state,
                    "selected_collections": selected_rag_collections,
                    "provider": rag_health.provider,
                    "metadata": rag_health_error.metadata,
                }
            )
            _record_activity(
                session,
                thread_id=thread.id,
                turn_id=turn.id,
                event_class=CHAT_EVENT_CLASS_FAILURE,
                event_type=CHAT_EVENT_TYPE_FAILED,
                reason_code=turn.reason_code,
                message=turn.error_message,
                metadata={
                    "rag_health_state": rag_health.state,
                    "selected_collections": selected_rag_collections,
                    "provider": rag_health.provider,
                    "metadata": rag_health_error.metadata,
                },
            )
            thread.last_activity_at = _now()
            return TurnResult(
                ok=False,
                thread_id=thread.id,
                turn_id=turn.id,
                request_id=request_id,
                reason_code=turn.reason_code,
                error=turn.error_message,
                rag_health_state=rag_health.state,
                selected_collections=selected_rag_collections,
            )
        if (
            selected_rag_collections
            and rag_health.state != RAG_HEALTH_CONFIGURED_HEALTHY
        ):
            turn.reason_code = RAG_REASON_UNAVAILABLE
            turn.error_message = "RAG is unavailable for selected collections."
            turn.runtime_metadata_json = _safe_json_dump(
                {
                    "rag_health_state": rag_health.state,
                    "selected_collections": selected_rag_collections,
                    "provider": rag_health.provider,
                }
            )
            _record_activity(
                session,
                thread_id=thread.id,
                turn_id=turn.id,
                event_class=CHAT_EVENT_CLASS_FAILURE,
                event_type=CHAT_EVENT_TYPE_FAILED,
                reason_code=RAG_REASON_UNAVAILABLE,
                message=turn.error_message,
                metadata={
                    "rag_health_state": rag_health.state,
                    "selected_collections": selected_rag_collections,
                    "provider": rag_health.provider,
                },
            )
            thread.last_activity_at = _now()
            return TurnResult(
                ok=False,
                thread_id=thread.id,
                turn_id=turn.id,
                request_id=request_id,
                reason_code=RAG_REASON_UNAVAILABLE,
                error=turn.error_message,
                rag_health_state=rag_health.state,
                selected_collections=selected_rag_collections,
            )

        retrieval_context: list[str] = []
        citation_records: list[dict[str, Any]] = []
        retrieval_stats: dict[str, Any] = {}
        if selected_rag_collections:
            try:
                retrieval = client.retrieve(
                    RAGRetrievalRequest(
                        question=cleaned_message,
                        collections=selected_rag_collections,
                        top_k=settings.rag_top_k,
                        model_id=str(model.id),
                        request_id=request_id,
                    )
                )
            except RAGContractError as exc:
                turn.reason_code = exc.reason_code or RAG_REASON_RETRIEVAL_FAILED
                turn.error_message = str(exc)
                turn.runtime_metadata_json = _safe_json_dump(
                    {
                        "metadata": exc.metadata,
                        "selected_collections": selected_rag_collections,
                    }
                )
                _record_activity(
                    session,
                    thread_id=thread.id,
                    turn_id=turn.id,
                    event_class=CHAT_EVENT_CLASS_FAILURE,
                    event_type=CHAT_EVENT_TYPE_FAILED,
                    reason_code=turn.reason_code,
                    message=turn.error_message,
                    metadata=exc.metadata,
                )
                thread.last_activity_at = _now()
                return TurnResult(
                    ok=False,
                    thread_id=thread.id,
                    turn_id=turn.id,
                    request_id=request_id,
                    reason_code=turn.reason_code,
                    error=turn.error_message,
                    rag_health_state=rag_health.state,
                    selected_collections=selected_rag_collections,
                )
            except Exception as exc:
                turn.reason_code = RAG_REASON_RETRIEVAL_FAILED
                turn.error_message = "RAG retrieval failed unexpectedly."
                turn.runtime_metadata_json = _safe_json_dump(
                    {
                        "selected_collections": selected_rag_collections,
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc),
                    }
                )
                _record_activity(
                    session,
                    thread_id=thread.id,
                    turn_id=turn.id,
                    event_class=CHAT_EVENT_CLASS_FAILURE,
                    event_type=CHAT_EVENT_TYPE_FAILED,
                    reason_code=turn.reason_code,
                    message=turn.error_message,
                    metadata={
                        "selected_collections": selected_rag_collections,
                        "exception_type": type(exc).__name__,
                    },
                )
                thread.last_activity_at = _now()
                return TurnResult(
                    ok=False,
                    thread_id=thread.id,
                    turn_id=turn.id,
                    request_id=request_id,
                    reason_code=turn.reason_code,
                    error=turn.error_message,
                    rag_health_state=rag_health.state,
                    selected_collections=selected_rag_collections,
                )
            retrieval_context = [item for item in retrieval.retrieval_context if item.strip()]
            citation_records = [item for item in retrieval.citation_records if isinstance(item, dict)]
            retrieval_stats = retrieval.retrieval_stats
            _record_activity(
                session,
                thread_id=thread.id,
                turn_id=turn.id,
                event_class=CHAT_EVENT_CLASS_RETRIEVAL_TOOL,
                event_type=CHAT_EVENT_TYPE_RETRIEVAL_USED,
                metadata={
                    "provider": rag_health.provider,
                    "collections": selected_rag_collections,
                    "retrieval_stats": retrieval_stats,
                    "citation_count": len(citation_records),
                },
            )
            if not retrieval_context:
                turn.reason_code = RAG_REASON_UNAVAILABLE
                turn.error_message = "No retrieval context was found for selected collections."
                turn.runtime_metadata_json = _safe_json_dump(
                    {
                        "selected_collections": selected_rag_collections,
                        "retrieval_stats": retrieval_stats,
                    }
                )
                _record_activity(
                    session,
                    thread_id=thread.id,
                    turn_id=turn.id,
                    event_class=CHAT_EVENT_CLASS_FAILURE,
                    event_type=CHAT_EVENT_TYPE_FAILED,
                    reason_code=turn.reason_code,
                    message=turn.error_message,
                    metadata={
                        "selected_collections": selected_rag_collections,
                        "retrieval_stats": retrieval_stats,
                    },
                )
                thread.last_activity_at = _now()
                return TurnResult(
                    ok=False,
                    thread_id=thread.id,
                    turn_id=turn.id,
                    request_id=request_id,
                    reason_code=turn.reason_code,
                    error=turn.error_message,
                    rag_health_state=rag_health.state,
                    selected_collections=selected_rag_collections,
                )

        if selected_mcp_keys:
            _record_activity(
                session,
                thread_id=thread.id,
                turn_id=turn.id,
                event_class=CHAT_EVENT_CLASS_RETRIEVAL_TOOL,
                event_type=CHAT_EVENT_TYPE_TOOL_USED,
                metadata={"selected_mcp_servers": selected_mcp_keys},
            )

        context_limit_tokens = _model_context_window_tokens(model, settings)
        rag_tokens = _estimate_tokens("\n".join(retrieval_context))
        summary_text = _parse_summary_text(thread.compaction_summary_json)
        history_messages = list(thread.messages)
        history_without_current = [item for item in history_messages if item.id != user_message.id]
        keep_message_count = max(0, settings.preserve_recent_turns * 2)
        recent_messages = (
            history_without_current[-keep_message_count:]
            if keep_message_count > 0
            else []
        )
        history_block = _render_history_block(summary_text, recent_messages)
        history_tokens = _estimate_tokens(history_block)
        user_tokens = _estimate_tokens(cleaned_message)
        mcp_tokens = 0
        context_usage_before = history_tokens + rag_tokens + mcp_tokens + user_tokens
        trigger_tokens = math.floor(
            context_limit_tokens * (settings.compaction_trigger_percent / 100.0)
        )
        target_tokens = math.floor(
            context_limit_tokens * (settings.compaction_target_percent / 100.0)
        )
        compaction_applied = False
        compaction_metadata: dict[str, Any] = {}
        if context_usage_before >= trigger_tokens and history_without_current:
            compactable = (
                history_without_current[:-keep_message_count]
                if keep_message_count > 0
                else history_without_current
            )
            if compactable:
                summary_text = _build_compaction_summary(
                    compactable,
                    summary_text,
                    settings.max_compaction_summary_chars,
                )
                compaction_payload = {
                    "summary_text": summary_text,
                    "compacted_message_ids": [item.id for item in compactable],
                    "compacted_at": _now().isoformat(),
                    "request_id": request_id,
                }
                thread.compaction_summary_json = _safe_json_dump(compaction_payload)
                recent_messages = (
                    history_without_current[-keep_message_count:]
                    if keep_message_count > 0
                    else []
                )
                history_block = _render_history_block(summary_text, recent_messages)
                history_tokens = _estimate_tokens(history_block)
                while (
                    recent_messages
                    and history_tokens + rag_tokens + mcp_tokens + user_tokens > target_tokens
                ):
                    recent_messages = recent_messages[1:]
                    history_block = _render_history_block(summary_text, recent_messages)
                    history_tokens = _estimate_tokens(history_block)
                context_usage_before = history_tokens + rag_tokens + mcp_tokens + user_tokens
                compaction_applied = True
                compaction_metadata = {
                    "compacted_message_count": len(compactable),
                    "preserved_message_count": len(recent_messages),
                    "target_tokens": target_tokens,
                }
                _record_activity(
                    session,
                    thread_id=thread.id,
                    turn_id=turn.id,
                    event_class=CHAT_EVENT_CLASS_COMPACTION,
                    event_type=CHAT_EVENT_TYPE_COMPACTED,
                    metadata=compaction_metadata,
                )

        prompt = _build_prompt(
            history_block=history_block,
            retrieval_context=retrieval_context,
            selected_rag_collections=selected_rag_collections,
            selected_mcp_server_keys=selected_mcp_keys,
            response_complexity=selected_response_complexity,
            user_message=cleaned_message,
        )
        mcp_configs: dict[str, dict[str, Any]] = {}
        try:
            for server in mcp_servers:
                mcp_configs[server.server_key] = parse_mcp_config(
                    server.config_json,
                    server_key=server.server_key,
                )
        except ValueError as exc:
            turn.reason_code = CHAT_REASON_MCP_FAILED
            turn.error_message = str(exc)
            _record_activity(
                session,
                thread_id=thread.id,
                turn_id=turn.id,
                event_class=CHAT_EVENT_CLASS_FAILURE,
                event_type=CHAT_EVENT_TYPE_FAILED,
                reason_code=turn.reason_code,
                message=turn.error_message,
            )
            thread.last_activity_at = _now()
            return TurnResult(
                ok=False,
                thread_id=thread.id,
                turn_id=turn.id,
                request_id=request_id,
                reason_code=turn.reason_code,
                error=turn.error_message,
                rag_health_state=rag_health.state,
                selected_collections=selected_rag_collections,
            )

        model_config = _parse_model_config(model.config_json)
        try:
            llm_result = _run_llm(
                model.provider,
                prompt,
                mcp_configs,
                model_config=model_config,
            )
        except Exception as exc:
            turn.reason_code = CHAT_REASON_MCP_FAILED if selected_mcp_keys else CHAT_REASON_MODEL_FAILED
            turn.error_message = str(exc)
            _record_activity(
                session,
                thread_id=thread.id,
                turn_id=turn.id,
                event_class=CHAT_EVENT_CLASS_FAILURE,
                event_type=CHAT_EVENT_TYPE_FAILED,
                reason_code=turn.reason_code,
                message=turn.error_message,
            )
            thread.last_activity_at = _now()
            return TurnResult(
                ok=False,
                thread_id=thread.id,
                turn_id=turn.id,
                request_id=request_id,
                reason_code=turn.reason_code,
                error=turn.error_message,
                rag_health_state=rag_health.state,
                selected_collections=selected_rag_collections,
            )

        reply = (llm_result.stdout or "").strip()
        if llm_result.returncode != 0:
            turn.reason_code = CHAT_REASON_MCP_FAILED if selected_mcp_keys else CHAT_REASON_MODEL_FAILED
            turn.error_message = (llm_result.stderr or "").strip() or f"Model exited with code {llm_result.returncode}."
            _record_activity(
                session,
                thread_id=thread.id,
                turn_id=turn.id,
                event_class=CHAT_EVENT_CLASS_FAILURE,
                event_type=CHAT_EVENT_TYPE_FAILED,
                reason_code=turn.reason_code,
                message=turn.error_message,
                metadata={
                    "return_code": llm_result.returncode,
                    "stderr": (llm_result.stderr or "").strip(),
                },
            )
            thread.last_activity_at = _now()
            return TurnResult(
                ok=False,
                thread_id=thread.id,
                turn_id=turn.id,
                request_id=request_id,
                reason_code=turn.reason_code,
                error=turn.error_message,
                rag_health_state=rag_health.state,
                selected_collections=selected_rag_collections,
            )

        assistant_message = ChatMessage.create(
            session,
            thread_id=thread.id,
            role="assistant",
            content=reply,
            token_estimate=_estimate_tokens(reply),
            metadata_json=_safe_json_dump({}),
        )
        context_usage_after = (
            history_tokens
            + rag_tokens
            + mcp_tokens
            + user_tokens
            + _estimate_tokens(reply)
        )
        turn.assistant_message_id = assistant_message.id
        turn.status = CHAT_TURN_STATUS_SUCCEEDED
        turn.reason_code = None
        turn.error_message = None
        turn.context_limit_tokens = context_limit_tokens
        turn.context_usage_before = context_usage_before
        turn.context_usage_after = context_usage_after
        turn.history_tokens = history_tokens
        turn.rag_tokens = rag_tokens
        turn.mcp_tokens = mcp_tokens
        turn.compaction_applied = compaction_applied
        turn.compaction_metadata_json = _safe_json_dump(compaction_metadata)
        turn.citation_metadata_json = _safe_json_dump(citation_records)
        turn.runtime_metadata_json = _safe_json_dump(
            {
                "rag_health_state": rag_health.state,
                "selected_collections": selected_rag_collections,
                "selected_mcp_servers": selected_mcp_keys,
                "response_complexity": selected_response_complexity,
                "retrieval_stats": retrieval_stats,
            }
        )
        _record_activity(
            session,
            thread_id=thread.id,
            turn_id=turn.id,
            event_class=CHAT_EVENT_CLASS_TURN,
            event_type=CHAT_EVENT_TYPE_TURN_RESPONDED,
            metadata={
                "request_id": request_id,
                "model_id": model.id,
                "context_usage_before": context_usage_before,
                "context_usage_after": context_usage_after,
                "context_limit_tokens": context_limit_tokens,
            },
        )
        thread.last_activity_at = _now()
        normalized_title = str(thread.title or "").strip().casefold()
        default_titles = {
            CHAT_DEFAULT_THREAD_TITLE.casefold(),
            CHAT_LEGACY_DEFAULT_THREAD_TITLE.casefold(),
        }
        if normalized_title in default_titles:
            thread.title = _derive_thread_title(cleaned_message)
        return TurnResult(
            ok=True,
            thread_id=thread.id,
            turn_id=turn.id,
            request_id=request_id,
            reply=reply,
            rag_health_state=rag_health.state,
            selected_collections=selected_rag_collections,
        )


def total_thread_count() -> int:
    with session_scope() as session:
        return (
            session.execute(select(func.count(ChatThread.id)))
            .scalar_one()
        )


def prune_archived_threads() -> int:
    with session_scope() as session:
        archived_ids = [
            row[0]
            for row in session.execute(
                select(ChatThread.id).where(ChatThread.status == CHAT_THREAD_STATUS_ARCHIVED)
            ).all()
        ]
        if not archived_ids:
            return 0
        session.execute(
            delete(chat_thread_mcp_servers).where(
                chat_thread_mcp_servers.c.chat_thread_id.in_(archived_ids)
            )
        )
        deleted = session.execute(
            delete(ChatThread).where(ChatThread.id.in_(archived_ids))
        )
        return int(deleted.rowcount or 0)
