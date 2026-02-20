Agent Runtime Migration Runbook
===============================

Purpose
-------

This runbook is the operator/developer guide for the Stage 13-16 migration
cutover from legacy flow execution behavior to the unified agent runtime.

Use this document for:

- migration preflight and cutover sequencing,
- rollback and containment steps,
- API/socket/tool contract references,
- executor split image build/release flow,
- tool-domain ownership boundaries.

Architecture + Ownership
------------------------

Core ownership boundaries:

- ``services/tasks.py``: flowchart run orchestration, node execution dispatch,
  artifact persistence, and run/node status propagation.
- ``services/execution/router.py``: provider/image-class routing for executor
  dispatch requests.
- ``services/execution/kubernetes_executor.py``: Kubernetes Job/Pod lifecycle,
  payload delivery, dispatch confirmation, and result collection.
- ``services/execution/tooling.py``: deterministic tool invocation framework
  (schema enforcement, idempotency/retry controls, fallback envelope).
- ``services/runtime_contracts.py``: canonical contract validation, including
  ``domain:entity:action`` socket event normalization.
- ``services/flow_migration.py``: one-time schema transform, compatibility
  gate, rollback trigger metadata, and migration evidence snapshots.

Tool-domain ownership (runtime side):

- Stage 10 domains: Memory, Plan, Milestone, Decision.
- Stage 11 domains: Workspace/File, Git, Command Execution, RAG.
- Stage 12 domains: Observability/introspection and workflow control actions.

Executor Split Images and Release Flow
--------------------------------------

Runtime classes:

- ``frontier`` -> ``llmctl-executor-frontier`` image family
- ``vllm`` -> ``llmctl-executor-vllm`` image family

Node executor runtime settings support independent image/tag control per class:

- ``k8s_frontier_image`` / ``k8s_frontier_image_tag``
- ``k8s_vllm_image`` / ``k8s_vllm_image_tag``

Build/push commands (Harbor-first policy):

.. code-block:: bash

   scripts/build/harbor.sh \
     --executor-frontier \
     --tag <tag> \
     --registry <registry-host:port>

   scripts/build/harbor.sh \
     --executor-vllm \
     --tag <tag> \
     --registry <registry-host:port>

   scripts/build/harbor.sh \
     --executor-frontier \
     --executor-vllm \
     --tag <tag> \
     --registry <registry-host:port>

Contract Reference Index
------------------------

Runtime contract references:

- Node executor runtime and payload/result contracts:
  :doc:`node_executor_runtime`
- Studio serving/runtime event model and envelope fields:
  :doc:`studio_serving_runtime`
- Specialized node REST/socket/artifact contracts:
  :doc:`specialized_flowchart_nodes`
- API module references:
  :doc:`api/services.execution.contracts`,
  :doc:`api/services.execution.tooling`,
  :doc:`api/services.realtime_events`,
  :doc:`api/services.runtime_contracts`,
  :doc:`api/services.flow_migration`

Migration artifacts and compatibility gate fields:

- ``compatibility_gate.status``
- ``compatibility_gate.blocking_issue_codes``
- ``rollback.required``
- ``rollback.trigger_codes``

Cutover Procedure
-----------------

1. Confirm baseline health:
   - PostgreSQL available for Studio runtime.
   - Integrated system MCP row exists for ``llmctl-mcp``.
   - Redis connectivity available for Socket.IO fan-out.
2. Run flow-migration dry-run and export evidence:

   .. code-block:: bash

      ./.venv/bin/python3 app/llmctl-studio-backend/scripts/migrate_flowchart_runtime_schema.py \
        --export-json data/flow_migration_report.json

3. Apply migration when compatibility gate is ``ready``:

   .. code-block:: bash

      ./.venv/bin/python3 app/llmctl-studio-backend/scripts/migrate_flowchart_runtime_schema.py \
        --apply \
        --export-json data/flow_migration_apply_report.json

4. Enable runtime cutover gate by setting
   ``agent_runtime_cutover_enabled=true`` through runtime settings
   (``POST /api/settings/runtime/node-executor``).
5. Run Stage 15 automated suites used for cutover sign-off:
   - backend contract/integration targeted suite,
   - frontend model + routing tests,
   - migration/execution regression suite.

Rollback Procedure
------------------

1. Disable runtime cutover gate immediately
   (``agent_runtime_cutover_enabled=false``).
2. Use migration evidence ``rollback.trigger_codes`` and pre/post snapshot hashes
   to identify the affected flowcharts.
3. Re-run migration script in dry-run mode for scoped IDs
   (``--flowchart-id <id>``) before any re-apply attempt.
4. Keep strict policy mode enabled unless policy-only warnings are explicitly
   accepted for emergency continuity.

Known Sign-Off Gaps (Stage 15 Inventory)
----------------------------------------

From Stage 15 automated testing evidence, unresolved environment-coupled
failures remain in the full Stage 9 suite and must be accounted for in
production cutover readiness checks:

- system-managed MCP prerequisite failures,
- missing legacy template route dependency in one API view path,
- route-key mismatch case in a node-type behavior test,
- missing Redis broker in local test harness producing publish warnings.

Authoritative references:

- ``docs/planning/archive/CLI_TO_STUDIO_AGENT_RUNTIME_STAGE14_RECONVERGENCE_FREEZE.md``
- ``docs/planning/archive/CLI_TO_STUDIO_AGENT_RUNTIME_STAGE15_AUTOMATED_TESTING_FREEZE.md``
