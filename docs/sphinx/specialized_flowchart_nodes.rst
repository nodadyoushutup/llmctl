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
  ``additive_prompt`` (runtime infers when blank), requires ``mode``
  (``llm_guided`` or ``deterministic``), includes ``Failure`` controls
  (``retry_count`` and ``fallback_enabled``), includes retention controls, and
  requires system-managed ``llmctl-mcp`` binding.
- ``plan`` requires ``mode`` (``llm_guided`` or ``deterministic``), requires
  ``store_mode`` (``append`` | ``replace`` | ``update``), supports optional
  ``additive_prompt``, optional ``patch`` or ``patch_source_path``, includes
  ``Failure`` controls (``retry_count`` and ``fallback_enabled``), and includes
  retention controls.
- ``milestone`` requires ``action`` (``create_or_update`` or ``mark_complete``),
  supports optional ``additive_prompt``, and includes retention controls.
- ``decision`` synchronizes conditions from solid outgoing connectors (``N``
  solid connectors maps to ``N`` condition entries) and has no MCP dependency
  for evaluation.

Graph Save Validation Semantics
-------------------------------

``POST /flowcharts/<flowchart_id>/graph`` accepts graph snapshots and returns:

- ``400`` for structural contract violations (for example missing required
  payload fields, invalid IDs, or invalid edge-mode values),
- ``200`` for accepted snapshots with semantic validation surfaced under
  ``validation.valid``/``validation.errors``.

For specialized nodes:

- memory-node graph writes require ``config.action`` (``add`` or ``retrieve``),
- memory-node graph writes normalize ``config.mode`` to canonical values
  (``llm_guided`` or ``deterministic``) with default ``llm_guided``,
- memory-node graph writes normalize failure controls:
  ``retry_count`` defaults to ``1`` and clamps to ``0..5``,
  ``fallback_enabled`` defaults to ``true``,
- invalid non-empty memory ``config.mode`` values are rejected at save time,
- memory nodes are system-bound to ``llmctl-mcp`` during graph persistence,
- runtime memory-node execution rejects explicit non-system MCP key sets.
- plan-node graph writes require ``config.mode`` with canonical values
  ``llm_guided`` | ``deterministic``,
- plan-node graph writes require ``config.store_mode`` with canonical values
  ``append`` | ``replace`` | ``update``.
- plan-node failure controls default to ``retry_count=1`` and
  ``fallback_enabled=true`` when omitted.

Connector Modes and Attachment Propagation
------------------------------------------

Flowchart graph connectors now use three execution modes:

- ``solid``: Trigger + Context + Attachments
- ``dotted``: Context Only
- ``dashed``: Attachments Only

Runtime propagation semantics:

- Solid connectors trigger downstream execution and pass upstream context plus
  attachment references.
- Context-only connectors do not trigger execution and only contribute context
  payloads into ``input_context.context_only_upstream_nodes``.
- Attachments-only connectors do not trigger execution and only contribute
  attachment references into
  ``input_context.attachment_only_upstream_nodes`` /
  ``input_context.propagated_attachments``.

Plan Node Mode and Store-Mode Semantics
---------------------------------------

Plan-node execution mode is configured per node via ``config.mode``:

- ``deterministic``: primary path applies ``patch``/``patch_source_path``
  payloads (and optional LLM transform patch when configured) through the
  deterministic plan applier.
- ``llm_guided``: primary path requires a strict JSON object patch inferred by
  the LLM and then applies it through the deterministic plan applier.

Plan-node store mode is configured per node via ``config.store_mode``.

Allowed values:

- ``append``: add-only behavior for stages/tasks; existing matched items are not
  mutated and produce warning entries.
- ``replace``: full plan structure overwrite from provided ``patch.stages``
  payload.
- ``update``: targeted mutation-only behavior for existing stages/tasks.

Update matching behavior:

- id-first targeting (``stage_id``/``task_id``)
- key fallback targeting (``stage_key``/``task_key``) when ids are absent
- ambiguous key matches are hard failures
- missing targets are skipped with warning details and
  ``operation_counts.skipped_missing`` increments

Hard-cut migration behavior:

- missing/invalid plan ``mode`` is migrated to ``deterministic``
- legacy ``action=create_or_update_plan`` is migrated to ``store_mode=append``
- legacy ``action=complete_plan_item`` is migrated to ``store_mode=update``
- missing/unknown legacy values default to ``append``
- malformed non-object plan configs fail fast during startup migration
- missing failure controls are migrated to defaults
  (``retry_count=1``, ``fallback_enabled=true``)

Plan failure and degraded semantics:

- Primary plan mode attempts execute ``1 + retry_count`` times.
- Retries apply only to the primary mode.
- If ``fallback_enabled=true`` and primary attempts are exhausted, runtime
  attempts exactly one fallback in the opposite plan mode.
- On fallback success, output includes degraded markers:

  - ``mode_fallback_used=true``,
  - ``failed_mode``,
  - ``fallback_mode``,
  - ``fallback_reason``.

- On fallback failure, runtime raises a hard failure; no second fallback hop is
  attempted.

Memory Node Mode Semantics
--------------------------

Memory-node mode is configured per node and applies to both ``add`` and
``retrieve`` actions.

Allowed values:

- ``llm_guided``: primary path performs strict-JSON LLM inference and then
  executes deterministic persistence/retrieval.
- ``deterministic``: primary path executes existing deterministic behavior
  directly.

Defaults and migration behavior:

- New memory nodes default to ``mode=llm_guided``.
- New memory nodes default to ``retry_count=1`` and
  ``fallback_enabled=true``.
- Startup migration backfills existing ``flowchart_nodes`` rows where
  ``node_type='memory'``:

  - missing or invalid ``mode`` is set to ``llm_guided``,
  - missing failure controls are set to canonical defaults,
  - malformed/non-object ``config_json`` fails fast and aborts startup.

Failure and degraded semantics:

- Primary mode attempts execute ``1 + retry_count`` times.
- Retries apply only to the primary mode.
- If ``fallback_enabled=true`` and primary attempts are exhausted, runtime
  attempts exactly one fallback in the opposite mode.
- On fallback success, output is marked degraded with:

  - ``execution_status=success_with_warning``,
  - ``fallback_used=true``,
  - ``failed_mode``,
  - ``fallback_reason``.

- On fallback failure, runtime raises a hard failure; no second fallback hop is
  attempted.

LLM-guided contracts:

- ``add`` expects strict JSON object output:
  ``text`` (required), optional ``store_mode`` (``append|replace``), optional
  ``confidence`` (advisory ``0..1``).
- ``retrieve`` expects strict JSON object output with optional ``query_text``,
  optional positive ``memory_id``, optional ``limit`` (clamped ``1..50``), and
  optional advisory ``confidence``.

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
- ``execution_status`` (degraded path), ``fallback_used``, ``fallback_reason``,
  ``failed_mode``, ``fallback_mode``
- optional LLM-guided metadata:
  ``llm_guided_add`` / ``llm_guided_retrieve``

``plan`` artifact payload:

- ``mode``, ``store_mode``, ``action_results``, ``additive_prompt``
- ``operation_counts`` (``created``, ``updated``, ``replaced``, ``skipped_missing``)
- ``touched``, ``warnings``, ``errors``
- degraded/mode-fallback evidence:
  ``mode_fallback_used``, ``failed_mode``, ``fallback_mode``, ``fallback_reason``
- ``plan``, ``routing_state``
- optional ``llm_transform_summary``

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
