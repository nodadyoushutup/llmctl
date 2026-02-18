from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

RAG_HEALTH_UNCONFIGURED = "unconfigured"
RAG_HEALTH_CONFIGURED_UNHEALTHY = "configured_unhealthy"
RAG_HEALTH_CONFIGURED_HEALTHY = "configured_healthy"
RAG_HEALTH_STATES = (
    RAG_HEALTH_UNCONFIGURED,
    RAG_HEALTH_CONFIGURED_UNHEALTHY,
    RAG_HEALTH_CONFIGURED_HEALTHY,
)

RAG_REASON_UNAVAILABLE = "RAG_UNAVAILABLE_FOR_SELECTED_COLLECTIONS"
RAG_REASON_RETRIEVAL_FAILED = "RAG_RETRIEVAL_EXECUTION_FAILED"
CHAT_REASON_MCP_FAILED = "CHAT_MCP_EXECUTION_FAILED"
CHAT_REASON_MODEL_FAILED = "CHAT_MODEL_EXECUTION_FAILED"
CHAT_REASON_SELECTOR_SCOPE = "CHAT_SESSION_SCOPE_SELECTOR_OVERRIDE"

CHAT_EVENT_CLASS_THREAD = "thread_lifecycle"
CHAT_EVENT_CLASS_TURN = "turn"
CHAT_EVENT_CLASS_RETRIEVAL_TOOL = "retrieval_tool_usage"
CHAT_EVENT_CLASS_FAILURE = "failure"
CHAT_EVENT_CLASS_COMPACTION = "compaction"

CHAT_EVENT_TYPE_THREAD_CREATED = "created"
CHAT_EVENT_TYPE_THREAD_ARCHIVED = "archived"
CHAT_EVENT_TYPE_THREAD_RESTORED = "restored"
CHAT_EVENT_TYPE_THREAD_DELETED = "deleted"
CHAT_EVENT_TYPE_THREAD_CLEARED = "cleared"
CHAT_EVENT_TYPE_TURN_REQUESTED = "turn_requested"
CHAT_EVENT_TYPE_TURN_RESPONDED = "turn_responded"
CHAT_EVENT_TYPE_RETRIEVAL_USED = "retrieval_used"
CHAT_EVENT_TYPE_TOOL_USED = "tool_used"
CHAT_EVENT_TYPE_FAILED = "failed"
CHAT_EVENT_TYPE_COMPACTED = "compacted"


@dataclass(slots=True)
class RAGHealth:
    state: str = RAG_HEALTH_UNCONFIGURED
    provider: str = "chroma"
    error: str | None = None


@dataclass(slots=True)
class RAGCollection:
    id: str
    name: str
    provider: str = "chroma"
    status: str | None = None


@dataclass(slots=True)
class RAGRetrievalRequest:
    question: str
    collections: list[str]
    top_k: int | None = None
    model_id: str = ""
    request_id: str = ""
    synthesize_answer: bool = True


@dataclass(slots=True)
class RAGRetrievalResponse:
    answer: str | None = None
    retrieval_context: list[str] = field(default_factory=list)
    retrieval_stats: dict[str, Any] = field(default_factory=dict)
    synthesis_error: dict[str, Any] | None = None
    mode: str = "query"
    collections: list[str] = field(default_factory=list)
    citation_records: list[dict[str, Any]] = field(default_factory=list)


class RAGContractError(RuntimeError):
    def __init__(
        self,
        *,
        reason_code: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.metadata = metadata or {}
