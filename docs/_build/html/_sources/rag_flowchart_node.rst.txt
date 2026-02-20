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

Indexing modes (``fresh_index`` and ``delta_index``) emit normalized metadata:

- ``mode``
- ``collections``
- ``retrieval_stats`` (includes ``total_files``/``total_chunks`` when available)
- ``task_current_stage='llm_query'``
- ``task_stage_logs`` with raw indexing lines under ``llm_query``

Node Detail Stage Behavior
--------------------------

For ``Quick RAG`` runs and flowchart ``rag`` node runs, Node Detail stage
rendering keeps stable stage ordering and remaps the ``llm_query`` label using
runtime execution mode:

- ``query`` -> ``LLM Query``
- ``indexing`` -> ``RAG Indexing``
- ``delta_indexing`` -> ``RAG Delta Indexing``

If execution mode is missing or unknown, Node Detail falls back to
``LLM Query`` for compatibility.

For indexing-labeled stages with no log lines yet, Node Detail shows
``Waiting for indexing logs...`` instead of the generic empty log message.

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

Manual source quick runs
------------------------

RAG indexing can also be triggered directly from the Sources UI without using a
flowchart node:

- Sources list rows expose icon-only quick actions for ``Index`` and ``Delta Index``.
- Source detail pages expose the same quick actions.
- Quick actions execute immediately (no confirm modal).
- Duplicate triggers are blocked while a source already has an active index run.

Quick runs are recorded in Node Activity as ``Quick RAG`` entries (with mode
and source context) using existing node activity metadata. They are intentionally
excluded from the workflow ``RAG`` node list because that list is flowchart-node
only.
