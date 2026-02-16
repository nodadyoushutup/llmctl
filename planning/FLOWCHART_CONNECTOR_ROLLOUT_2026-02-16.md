# Flowchart Connector Rollout Checklist

Date: 2026-02-16

This checklist is for optional staged rollout in environments where you want a non-prod soak period before full production exposure.

## Stage A: Non-prod enablement

1. Deploy the connector-mode build to a non-production environment.
2. Confirm DB schema includes `flowchart_edges.edge_mode` with default `solid`.
3. Confirm graph save/load accepts `solid|dotted` and rejects invalid values.

## Stage B: Representative validation set

Validate at least one flowchart per scenario:

1. Branching fan-out (`1 -> N` solid outputs).
2. Pull-only fan-in (`A dotted + B dotted -> C`, triggered by a separate solid edge).
3. Decision routing with solid `condition_key` edges and optional dotted context edges.
4. Loop/guardrail behavior (`max_node_executions`, `max_runtime_minutes`, `max_parallel_nodes`).
5. Legacy graph migrated from pre-edge-mode state (all edges treated as solid).

Run automated checks:

```bash
./.venv/bin/python3 -m unittest app/llmctl-studio/tests/test_flowchart_connector_stage6.py
```

## Stage C: Limited production exposure

1. Roll out to a small set of production tenants/workspaces.
2. Monitor:
   - run failure rate
   - average run duration
   - queue depth / scheduler lag
   - frequency of dotted-source-missing diagnostics
3. Confirm no regression in existing flowcharts that were not edited.

## Stage D: Full rollout

1. Expand to all production tenants/workspaces.
2. Publish user-facing connector docs and migration note links.
3. Keep rollback path ready (previous stable image + DB backup snapshot policy).
