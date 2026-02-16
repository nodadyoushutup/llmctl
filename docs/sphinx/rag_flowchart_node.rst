RAG Flowchart Node
==================

The RAG runtime has migrated from standalone Index Jobs to a first-class
``rag`` flowchart node.

Runtime modes
-------------

- ``fresh_index``: rebuild selected collection(s).
- ``delta_index``: incremental index for selected collection(s).
- ``query``: retrieval + synthesis output for downstream nodes.

Node config schema
------------------

Required keys:

- ``mode``: ``fresh_index`` | ``delta_index`` | ``query``
- ``collections``: one or more selected collection ids/names

Query mode keys:

- ``question_prompt`` (required)
- ``top_k`` (optional, default ``5``)

Runtime contract
----------------

``query`` mode emits normalized output payload fields:

- ``answer``
- ``retrieval_context``
- ``retrieval_stats``
- ``synthesis_error``
- ``mode``
- ``collections``

Citation/source snippets are audit-only in v1 and are not emitted in runtime
payload/context.

Integration-health gating
-------------------------

RAG node visibility and execution are gated by real-time RAG health:

- ``unconfigured``: palette hidden
- ``configured_unhealthy``: palette visible but disabled
- ``configured_healthy``: palette enabled

Runs containing RAG nodes perform pre-run validation and fail fast when health
is not ``configured_healthy``.

Contract endpoints
------------------

The shared RAG contract surfaces used by Chat are:

- ``GET /api/rag/contract/health``
- ``GET /api/rag/contract/collections``
- ``POST /api/rag/contract/retrieve``

Legacy aliases remain available at ``/api/rag/{health,collections,retrieve}``
for compatibility.
