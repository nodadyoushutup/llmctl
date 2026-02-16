Changelog
=========

2026-02-16
----------

- Added first-class Launch Chat runtime with durable thread sessions.
- Added session-scoped model, MCP, and optional RAG collection selectors.
- Added context budgeting and automatic compaction at configured usage limits.
- Added clear-in-place thread reset behavior.
- Added Chat activity/audit surfaces and event taxonomy.
- Added Chat runtime API routes and contract-boundary RAG client.
- Migrated RAG indexing/retrieval orchestration to first-class ``rag`` flowchart nodes.
- Added shared Chat/RAG contract endpoints at ``/api/rag/contract/*`` with compatibility aliases.
- Removed standalone RAG Index Jobs surfaces from active Studio navigation/runtime paths.
- Added real-time RAG integration-health gating for flowchart ``rag`` node palette visibility/execution.
