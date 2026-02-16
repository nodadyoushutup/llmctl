"""Stage 2 architecture contracts for the Studio-owned RAG stack.

These constants lock naming and ownership boundaries before Stage 3 schema and
runtime implementation work.
"""

from __future__ import annotations

RAG_DB_TABLE_SOURCES = "rag_sources"
RAG_DB_TABLE_SOURCE_FILE_STATES = "rag_source_file_states"
RAG_DB_TABLE_SETTINGS = "rag_settings"
RAG_DB_TABLE_RETRIEVAL_AUDITS = "rag_retrieval_audits"

RAG_QUEUE_NAMESPACE = "llmctl_studio.rag"
RAG_QUEUE_INDEX = f"{RAG_QUEUE_NAMESPACE}.index"
RAG_QUEUE_DRIVE = f"{RAG_QUEUE_NAMESPACE}.drive"
RAG_QUEUE_GIT = f"{RAG_QUEUE_NAMESPACE}.git"

RAG_SCHEDULE_MODE_FRESH = "fresh"
RAG_SCHEDULE_MODE_DELTA = "delta"
RAG_SCHEDULE_MODE_CHOICES = (
    RAG_SCHEDULE_MODE_FRESH,
    RAG_SCHEDULE_MODE_DELTA,
)

RAG_TRIGGER_MANUAL = "manual"
RAG_TRIGGER_SCHEDULED = "scheduled"
RAG_TRIGGER_CHOICES = (
    RAG_TRIGGER_MANUAL,
    RAG_TRIGGER_SCHEDULED,
)

RAG_WEB_ROUTE_PREFIX = "/rag"
RAG_API_ROUTE_PREFIX = "/api/rag"
RAG_TEMPLATE_SUBDIR = "rag"
RAG_STATIC_SUBDIR = "rag"

RAG_NAV_SECTION_LABEL = "RAG"
RAG_NAV_PAGE_CHAT = "Chat"
RAG_NAV_PAGE_SOURCES = "Sources"
RAG_NAV_PAGE_LABELS = (
    RAG_NAV_PAGE_CHAT,
    RAG_NAV_PAGE_SOURCES,
)
