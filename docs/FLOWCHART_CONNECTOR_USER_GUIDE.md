# Flowchart Connector User Guide

Last updated: 2026-02-16

This guide describes connector behavior in the Studio flowchart editor/runtime.

## Connector modes

Direction is always `source -> target` for every connector mode.

- `solid`:
  - Triggers target execution.
  - Passes source output/context into the target input context.
- `dotted`:
  - Never triggers target execution.
  - Makes source output available as pull-only context when the target is triggered by another solid edge.

## Decision node routing

- Decision routing reads `condition_key` only from `solid` outgoing edges.
- Dotted edges from decision nodes may exist for context dependencies, but are ignored for route matching.

## Practical examples

### Example 1: Branching fan-out (`1 -> N`)

- `start -> task_a` (`solid`)
- `start -> task_b` (`solid`)
- `start -> task_c` (`solid`)

Result:
- One start execution enqueues executions for `task_a`, `task_b`, and `task_c`.

### Example 2: Shared pull context fan-in

- `source_a -> target_c` (`dotted`)
- `source_b -> target_c` (`dotted`)
- `trigger_d -> target_c` (`solid`)

Result:
- `target_c` runs only when `trigger_d` executes.
- During that run, `target_c` can pull latest successful output from `source_a` and `source_b` in the same flowchart run, if available.

### Example 3: Existing graph migration behavior

- Existing edges are migrated as `solid`.
- Existing flowcharts keep prior trigger behavior without manual edits.

## Anti-patterns and guardrails

### Unbounded fan-out

Risk:
- A node with many solid outputs can create queue pressure and high run volume.

Avoid:
- Keep fan-out explicit and justified.
- Set flowchart guardrails (`max_node_executions`, `max_runtime_minutes`, `max_parallel_nodes`).

### Accidental solid loops

Risk:
- Solid cycles can repeatedly re-enqueue nodes.

Avoid:
- Use dotted edges for observation/context-only links.
- Keep solid cycles intentional and protected by guardrails.

### Mixed edge modes on the same source->target pair

Risk:
- Ambiguous semantics.

System behavior:
- Validation rejects a source->target pair that mixes both `solid` and `dotted`.

### Treating dotted inputs as required blockers

Risk:
- Assuming dotted sources must exist before target execution.

Actual behavior:
- Missing dotted outputs are ignored.
- Target continues with partial context; dotted edges do not gate execution.

## Operator troubleshooting

- Use run history to inspect:
  - `trigger_sources` (what solid trigger caused execution).
  - `pulled_dotted_sources` (what dotted context was pulled at execution time).
