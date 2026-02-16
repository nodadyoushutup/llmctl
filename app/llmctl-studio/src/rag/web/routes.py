"""Route contracts for Stage 2 RAG namespace planning."""

from __future__ import annotations

from rag.contracts import RAG_API_ROUTE_PREFIX, RAG_WEB_ROUTE_PREFIX

RAG_PAGE_CHAT = f"{RAG_WEB_ROUTE_PREFIX}/chat"
RAG_PAGE_SOURCES = f"{RAG_WEB_ROUTE_PREFIX}/sources"
RAG_PAGE_INDEX_JOBS = f"{RAG_WEB_ROUTE_PREFIX}/index-jobs"

RAG_API_INDEX_NOW = f"{RAG_API_ROUTE_PREFIX}/sources/<int:source_id>/index"
RAG_API_PAUSE_SOURCE = f"{RAG_API_ROUTE_PREFIX}/sources/<int:source_id>/pause"
RAG_API_RESUME_SOURCE = f"{RAG_API_ROUTE_PREFIX}/sources/<int:source_id>/resume"
RAG_API_TASK_STATUS = f"{RAG_API_ROUTE_PREFIX}/tasks/status"
RAG_API_CHAT = f"{RAG_API_ROUTE_PREFIX}/chat"
RAG_API_GITHUB_REPOS = f"{RAG_API_ROUTE_PREFIX}/github/repos"
RAG_API_DRIVE_VERIFY = f"{RAG_API_ROUTE_PREFIX}/google-drive/verify"
RAG_API_CHROMA_TEST = f"{RAG_API_ROUTE_PREFIX}/chroma/test"
