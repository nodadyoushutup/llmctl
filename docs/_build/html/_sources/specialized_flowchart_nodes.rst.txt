Specialized Flowchart Nodes
===========================

This guide documents specialized node behavior for ``memory``, ``plan``,
``milestone``, and ``decision`` nodes, including inspector contracts, runtime
artifact persistence, REST/socket payloads, and MCP alignment.

Inspector Contract
------------------

Specialized nodes use curated inspector controls (generic controls are hidden
for specialized behavior fields):

- ``memory`` requires ``action`` (``add`` or ``retrieve``), supports optional
  ``additive_prompt`` (runtime infers when blank), includes retention controls,
  and requires system-managed ``llmctl-mcp`` binding.
- ``plan`` requires ``action`` (``create_or_update_plan`` or
  ``complete_plan_item``), supports optional ``additive_prompt``, supports
  completion targeting via ``plan_item_id`` or ``stage_key`` + ``task_key`` or
  ``completion_source_path``, and includes retention controls.
- ``milestone`` requires ``action`` (``create_or_update`` or ``mark_complete``),
  supports optional ``additive_prompt``, and includes retention controls.
- ``decision`` synchronizes conditions from solid outgoing connectors (``N``
  solid connectors maps to ``N`` condition entries) and has no MCP dependency
  for evaluation.

Node Artifact Retention
-----------------------

Specialized node artifacts are stored in ``node_artifacts`` with runtime
retention controls from ``FlowchartNode.config_json``:

- ``retention_mode``: ``forever`` | ``ttl`` | ``max_count`` | ``ttl_max_count``
- ``retention_ttl_seconds``: TTL window (defaults to ``3600``)
- ``retention_max_count``: history cap (defaults to ``25``)

Artifacts persist ``request_id`` and ``correlation_id`` for end-to-end tracing.

REST API Contract
-----------------

Under the API prefix (``/api``), specialized artifact history endpoints are:

- ``GET /plans/{plan_id}/artifacts``
- ``GET /plans/{plan_id}/artifacts/{artifact_id}``
- ``GET /memories/{memory_id}/artifacts``
- ``GET /memories/{memory_id}/artifacts/{artifact_id}``
- ``GET /milestones/{milestone_id}/artifacts``
- ``GET /milestones/{milestone_id}/artifacts/{artifact_id}``
- ``GET /flowcharts/{flowchart_id}/nodes/{flowchart_node_id}/decision-artifacts``
- ``GET /flowcharts/{flowchart_id}/nodes/{flowchart_node_id}/decision-artifacts/{artifact_id}``

List endpoints support paging/filtering (`limit`, `offset`, flowchart/run/node
filters where applicable). Success payloads include:

- ``ok``
- identity scope fields (for example ``plan_id`` or ``flowchart_id``)
- ``count``/``limit``/``offset`` for list responses
- ``items`` (list) or ``item`` (detail)
- ``request_id``
- optional ``correlation_id``

Error payloads use the shared envelope:

- ``code``
- ``message``
- ``details``
- ``request_id``
- optional ``correlation_id``

Socket Event Contract
---------------------

Specialized node execution emits run/node and artifact events:

- ``flowchart.node.updated`` includes ``flowchart_id``, ``flowchart_run_id``,
  ``flowchart_node_id``, ``flowchart_node_type``, ``node_run_id``, ``status``,
  ``execution_index``, ``output_state``, ``routing_state``, timing fields, and
  optional ``error``.
- ``flowchart.run.updated`` includes ``flowchart_id``, ``flowchart_run_id``,
  ``status``, and timestamps.
- ``flowchart:node_artifact:persisted`` includes ``flowchart_id``,
  ``flowchart_run_id``, ``flowchart_node_id``, ``flowchart_node_type``,
  ``node_run_id``, ``artifact_id``, ``artifact_type``, ``artifact`` (full
  serialized artifact), ``request_id``, and ``correlation_id``.

Artifact Payload Schemas
------------------------

``memory`` artifact payload:

- ``action``, ``action_prompt_template``, ``internal_action_prompt``
- ``action_results``, ``additive_prompt``, ``inferred_prompt``, ``effective_prompt``
- ``stored_memory``, ``retrieved_memories``, ``mcp_server_keys``, ``routing_state``

``plan`` artifact payload:

- ``action``, ``action_results``, ``additive_prompt``
- ``completion_target``, ``touched``, ``plan``, ``routing_state``

``milestone`` artifact payload:

- ``action``, ``action_results``, ``additive_prompt``, ``checkpoint_hit``
- ``before_milestone``, ``milestone``, ``routing_state``

``decision`` artifact payload:

- ``matched_connector_ids``
- ``evaluations`` (per connector: ``connector_id``, ``condition_text``,
  ``matched``, ``reason``)
- ``no_match``
- ``resolved_route_key``, ``resolved_route_path``, ``routing_state``

MCP Contract Alignment
----------------------

Specialized artifact retrieval is aligned through MCP tools:

- ``llmctl_get_memory(..., include_artifacts=True)``
- ``llmctl_get_plan(..., include_artifacts=True)``
- ``llmctl_get_milestone(..., include_artifacts=True)``
- ``llmctl_get_decision_artifact(...)``
- ``llmctl_get_node_artifact(...)`` (generic artifact listing/detail)

Operator Workflow Guidance
--------------------------

Stage 5 fan-out guidance for this initiative:

1. Default operating mode is serial execution on ``main`` (no feature branches).
2. Freeze shared contracts before any parallel assignment:
   ``node_artifacts`` schema, inspector config keys, API envelope, socket keys.
3. If parallel execution is explicitly requested, keep branchless operation and
   integrate each agent's changes one-at-a-time with test gates between merges.
4. Require Stage 7 integration verification before Stage 8 test signoff.
5. Record screenshot evidence and pass/fail matrix directly in the active plan.
