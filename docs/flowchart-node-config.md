# Flowchart Node Config Schema (Stage 3)

This document defines `flowchart_nodes.config_json` keys used by Stage 3 node behavior handlers.
For connector behavior and rollout guidance, see:
- `docs/FLOWCHART_CONNECTOR_USER_GUIDE.md`
- `docs/FLOWCHART_CONNECTOR_RELEASE_NOTE_2026-02-16.md`
- `docs/FLOWCHART_CONNECTOR_ROLLOUT_2026-02-16.md`

## Shared conventions

- Paths use dot notation (example: `latest_upstream.output_state.structured_output.route_key`).
- All node handlers emit normalized `output_state` and optional `routing_state`.
- `routing_state.route_key` is used for edge routing.
- `routing_state.terminate_run=true` ends the run gracefully.

## Task node (`node_type=task`)

- `route_key_path` (string, optional): path inside task structured output used to populate `routing_state.route_key`.
- `task_name` (string, optional): display name used in task context/output.
- `task_prompt` (string, optional): inline prompt for ad-hoc task nodes.
  - Required when `ref_id` is unset.
  - When both `task_prompt` and `ref_id` are set, `task_prompt` takes precedence.

Behavior:
- Runs LLM with node-selected model.
- Uses inline `task_prompt` when present; otherwise falls back to referenced task template prompt.
- Uses node-attached MCP servers (+ built-in `llmctl-mcp`) only.
- Uses task/node scripts only (task template scripts + node scripts; no agent scripts).
- Persists structured output in `output_state.structured_output`.

## Flowchart node (`node_type=flowchart`)

- `ref_id` (int, required): target flowchart id to launch.

Behavior:
- Queues a new run for the selected flowchart every time this node executes.
- Does not reuse or block on active runs; each activation creates a fresh run.
- Emits triggered run metadata in `output_state`.

## Decision node (`node_type=decision`)

- `route_field_path` (string, optional): path in `input_context` used to read route key.
  - Default: `latest_upstream.output_state.structured_output.route_key`.
- `fallback_condition_key` (string, optional): fallback edge `condition_key` when route key has no direct match.

Behavior:
- No LLM call in normal path.
- Resolves route key in Python.
- Fails when route key is missing/invalid and no fallback route is available.

## Plan node (`node_type=plan`)

- `action` (string): `read` (default) | `update` | `update_completion` | `complete`.
- `patch` (object, optional): completion patch.
  - Supported keys: `mark_plan_complete`, `complete_stage_ids`, `complete_task_ids`.
- `completion_source_path` (string, optional): path in `input_context` to a completion patch object.
- `transform_with_llm` (bool, optional): apply optional semantic transform.
- `transform_prompt` (string, optional): prompt used for optional transform.
- `route_key` (string, optional): static route key.
- `route_key_on_complete` (string, optional): route key override when plan is completed.

Behavior:
- Reads/updates selected plan record (`ref_id`).
- Stores action results in `output_state.action_results`.
- Uses Python data operations by default; optional LLM transform only when enabled.

## Milestone node (`node_type=milestone`)

- `action` (string): `read` (default) | `update` | `checkpoint` | `complete`.
- `patch` (object, optional): partial milestone update.
  - Supported keys: `name`, `description`, `status`, `priority`, `owner`, `progress_percent`, `health`, `latest_update`.
- `completion_source_path` (string, optional): path in `input_context` to a patch object.
- `mark_complete` (bool, optional): mark milestone complete (`status=done`, `progress_percent=100`).
- `loop_checkpoint_every` (int, optional): checkpoint interval by execution count.
- `terminate_on_checkpoint` (bool, optional): terminate run when checkpoint is hit.
- `loop_exit_after_runs` (int, optional): terminate after this node has run N times.
- `terminate_on_complete` (bool, optional): terminate when milestone is complete.
- `terminate_always` (bool, optional): always terminate after this node.
- `transform_with_llm` (bool, optional): optional semantic model pass.
- `transform_prompt` (string, optional): prompt for optional semantic pass.
- `route_key` (string, optional): static route key.
- `route_key_on_terminate` (string, optional): route key override on termination.

Behavior:
- Evaluates and updates milestone state.
- Supports loop checkpoints and loop-exit patterns as first-class config options.
- Can terminate run gracefully via routing state.

## Memory node (`node_type=memory`)

- `action` (string): `fetch` (default) | `store` | `upsert` | `append`.
- `limit` (int, optional): fetch limit (default `10`).
- `query` (string, optional): substring query for fetch.
- `query_source_path` (string, optional): path in `input_context` for query text.
- `text` (string, optional): text to store.
- `text_source_path` (string, optional): path in `input_context` for store text.
- `store_mode` (string, optional): `replace` (default) | `append` for `ref_id` updates.
- `route_key` (string, optional): static route key.

Behavior:
- Fetches by selected memory (`ref_id`) or query pattern.
- Stores/updates memory content.
- Persists retrieved/stored payload in `output_state` for downstream nodes.
