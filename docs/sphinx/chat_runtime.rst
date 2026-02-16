Launch Chat Runtime
===================

Overview
--------

Launch Chat is a first-class runtime for multi-turn sessions with durable
thread history. Each thread owns session-scoped selectors:

- model (`LLMModel`)
- MCP server set (`MCPServer`)
- optional RAG collection set

Thread Lifecycle
----------------

Thread actions:

- create
- open/select
- archive
- restore
- clear (in-place context/history reset)
- hard delete

Clear deletes thread messages/turns and resets compaction summary state while
keeping the thread record.

RAG Contract Boundary
---------------------

Chat integrates with RAG exclusively through the contract client in
`chat.rag_client`:

- health
- collection discovery
- retrieval request/response

If selected collections exist and RAG health is not
`configured_healthy`, turns fail with
`RAG_UNAVAILABLE_FOR_SELECTED_COLLECTIONS`.

Current integration mode:

- default runtime uses a stub contract client (safe fallback)
- real HTTP contract mode is enabled via `CHAT_RAG_CONTRACT_BASE_URL`

Context Budgeting And Compaction
--------------------------------

Global chat runtime settings define budget percentages and compaction policy.
Defaults:

- history: 60%
- RAG: 25%
- MCP/tool: 15%
- compaction trigger: 100%
- compaction target: 85%

When a turn reaches trigger usage, Chat compacts older messages into a summary,
preserves recent turns, and continues below target usage when possible.

Audit And Activity
------------------

Chat audit schema records:

- thread lifecycle events
- turn request/response events
- retrieval/tool usage events
- failure events with reason codes
- compaction events

Citation/source metadata is persisted in DB audit fields only. It is not
shown in chat response UI and is not injected into model context assembly.

HTTP Surfaces
-------------

UI routes:

- `/chat`
- `/chat/activity`

JSON routes:

- `/api/chat/threads/<thread_id>`
- `/api/chat/threads/<thread_id>/turn`
- `/api/chat/activity`

Per-turn selector overrides (`model_id`, `mcp_server_ids`, `rag_collections`)
are rejected with `CHAT_SESSION_SCOPE_SELECTOR_OVERRIDE`.
