# SDK Workspace Tooling Integration Plan

Goal: enable SDK-based agent runs to read/write cloned workspace files, execute git operations, and run command/test workflows through controlled runtime tools in per-executor ephemeral workspaces.

## Stage 0 - Requirements Gathering

- [x] Confirm initial rollout scope (`codex+gemini+claude`).
- [x] Confirm provider parity requirement (all frontier SDK providers must support MCP servers, tool usage, and cloned-workspace mutation workflows).
- [x] Confirm provider validation constraints (Gemini must be runtime-verified; Claude must be best-effort validated without live auth-required test runs due missing API key).
- [x] Confirm mutation policy defaults (`git branch`, `git commit`, and `git push` allowed by default).
- [x] Confirm pull request workflow requirement (support PR creation when GitHub integration is enabled, using available runtime mechanism).
- [x] Confirm command-execution safety policy (broad command support with guardrails).
- [x] Confirm workspace boundaries (single cloned task workspace only, no cross-workspace access; executor-local ephemeral storage).
- [x] Confirm expected UX/output behavior (how tool actions and errors should appear in task logs/output).
- [x] Confirm acceptance criteria for “done” (minimum end-to-end workflow to prove success).
- [x] Confirm Stage 0 completion and approval to start Stage 1.

## Stage 0 - Interview Notes (Captured)

- [x] User requested a plan to enable SDK-driven workspace editing/testing behaviors.
- [x] Rollout providers locked: `codex + gemini + claude`.
- [x] User requires all three providers functional for SDK execution with MCP server usage, tool usage, and workspace mutation in cloned GitHub workspaces.
- [x] Gemini requirement: verify runtime behavior still works in general as part of this effort.
- [x] Claude constraint: no API key currently available; perform best-effort implementation/code validation and non-auth checks, but do not require live authenticated runtime test execution.
- [x] Git mutation policy locked: full coding autonomy when GitHub integration is enabled (`branch`, `commit`, `push`).
- [x] PR creation is required when possible under GitHub integration.
- [x] Command safety envelope locked: broad command support with runtime guardrails.
- [x] Workspace boundary locked: each executor pod gets isolated ephemeral workspace storage; GitHub clone/edit/test operations happen inside that executor-local filesystem (not shared `data` workspace).
- [x] UX/output behavior locked: full verbose stream in run output (tool call actions, command execution details, outputs, and errors surfaced directly).
- [x] Acceptance criteria locked: for `codex` and `gemini`, a run must spin up an executor pod, clone into executor-local ephemeral workspace, create a branch, apply code changes, commit, push, and create a GitHub PR with full verbose logs.
- [x] Delivery constraint captured: implementation work proceeds on repository `main` branch; runtime git mutations occur inside task workspace clones.

## Stage 1 - Code Planning

- [x] Define tool-calling runtime loop contract for SDK providers (request/response/tool-result iteration).
- [x] Define provider-specific capability matrix and fallback behavior when tools are unsupported.
- [x] Define shared tool schema surface for workspace/git/command domains.
- [x] Define error envelope, correlation/request IDs, and logging/tracing requirements for tool actions.
- [x] Define integration points in `services/tasks.py` and `services/execution/agent_runtime.py`.

### Stage 1 Decisions (Locked 2026-02-21)

- Tool loop contract:
  - Add a shared iterative SDK tool loop in `FrontierAgent.run` (`services/execution/agent_runtime.py`) that executes: `provider response -> parse tool calls -> dispatch tools -> append tool results -> continue`.
  - End loop when provider returns final assistant content with no tool calls, or when an explicit max-iteration guard is reached (default 24 iterations) to prevent runaway loops.
  - Preserve current upstream retry handling (`failed dependency` and `upstream 500`) as outer retries around each provider call cycle.
  - Keep runtime SDK-first and fail-fast: no CLI fallback path for tool execution.
- Provider capability matrix and unsupported behavior:
  - `codex`: supports SDK model output + MCP wiring + SDK tool-loop dispatch.
  - `gemini`: supports SDK model output + SDK tool-loop dispatch; MCP transport remains unsupported.
  - `claude`: supports SDK model output + SDK tool-loop dispatch; MCP transport remains unsupported.
  - Unsupported tool domains/operations return a stable error envelope and terminate the run with non-zero return code.
- Shared tool schema surface:
  - Normalize provider tool-call payloads into a common shape: `{call_id, tool_name, domain, operation, args}`.
  - Supported deterministic tool names map to existing handlers in `services/execution/tool_domains.py`:
    - `deterministic.workspace` -> `run_workspace_tool` (operations from `WORKSPACE_OPERATIONS`).
    - `deterministic.git` -> `run_git_tool` (operations from `GIT_OPERATIONS`).
    - `deterministic.command` -> `run_command_tool` (operations from `COMMAND_OPERATIONS`).
  - Tool dispatch context must be built from `ToolDomainContext(workspace_root, execution_id, request_id, correlation_id)` so path confinement and idempotency controls are applied uniformly.
- Error envelope and tracing:
  - Standardize SDK tool-loop errors as: `{code, message, details, retryable, request_id, correlation_id}`.
  - Tool call cycle logging must include `provider`, `tool_name`, `operation`, `call_id`, `request_id`, `correlation_id`, and cycle index.
  - Preserve deterministic tooling trace envelopes produced by `invoke_deterministic_tool`; surface summaries in task logs and `ExecutionResult.output_state` metadata where available.
- Integration points (implementation map):
  - `app/llmctl-studio-backend/src/services/execution/agent_runtime.py`:
    - Extend `FrontierAgentRequest` with workspace and dispatch context required by tool domains.
    - Implement provider-specific tool-call parsing adapters and shared loop execution in `FrontierAgent.run`.
  - `app/llmctl-studio-backend/src/services/tasks.py`:
    - Wire task/flowchart workspace + request context (`request_id`, `execution_id`, `node_id`, `mcp_server_keys`) into `_run_frontier_llm_sdk` -> `FrontierAgentRequest`.
    - Ensure router path and in-process executor path supply identical tool-loop context.
  - `app/llmctl-studio-backend/src/services/execution/tool_domains.py`:
    - Reuse existing domain handlers as the single dispatch backend for workspace/git/command operations in SDK loops.

## Stage 2 - Scope-Specific Planning

- [x] Freeze scope for first implementation slice (provider coverage, operations enabled, safety constraints).
- [x] Freeze rollout controls (feature flag(s), defaults, and runtime settings exposure if needed).
- [x] Freeze required end-to-end scenarios and explicit acceptance criteria.

### Stage 2 Decisions (Locked 2026-02-21)

- First implementation slice scope:
  - Provider coverage: `codex`, `gemini`, `claude` in the shared SDK tool loop.
  - Tool domains in scope: `workspace`, `git`, `command` only for this slice.
  - Out of scope for this slice: introducing new tool domains, altering RAG domain behavior, or adding CLI fallback runtime paths.
  - Domain operation surface in scope:
    - `workspace`: operations currently defined by `WORKSPACE_OPERATIONS`.
    - `git`: operations currently defined by `GIT_OPERATIONS`.
    - `command`: operations currently defined by `COMMAND_OPERATIONS`.
  - Safety constraints locked:
    - Enforce workspace-root confinement via `ToolDomainContext.resolved_workspace_root()` and `_resolve_workspace_path(...)`.
    - Enforce execution-time bounds using existing command/git timeout controls.
    - Keep execution SDK-first/fail-fast with no legacy compatibility fallback path.
- Rollout controls:
  - Reuse existing runtime cutover controls; no new runtime setting introduced in this stage.
  - Primary gate: node executor runtime setting `agent_runtime_cutover_enabled`.
  - Node-level override remains supported via `__agent_runtime_cutover_enabled` in node config.
  - Default behavior remains unchanged until cutover is enabled; tool-loop behavior activates only on frontier SDK path.
- Required end-to-end scenarios and acceptance criteria:
  - `codex` and `gemini` required success path:
    - run in executor pod-local workspace;
    - create/switch branch;
    - apply workspace edits;
    - run at least one command/test;
    - commit and push;
    - create PR when GitHub integration supports it.
  - `claude` required implementation parity with best-effort non-auth validation; authenticated runtime execution is not a blocking requirement for completion.
  - Required observability:
    - tool call cycle logs include provider + tool metadata + request/correlation identifiers;
    - deterministic tool trace envelope preserved in outputs.
  - Unsupported capability behavior must be explicit and stable:
    - unsupported MCP transport/tool usage returns deterministic structured errors (no silent downgrade).

## Stage 3 - Execution: SDK Tool Loop Foundation

- [x] Implement shared SDK tool-calling loop support in frontier runtime adapter.
- [x] Implement tool call parsing, dispatch, tool result serialization, and retry/termination handling.
- [x] Add structured observability for each tool call cycle.

## Stage 4 - Execution: Tool Domain Runtime Wiring

- [x] Wire `workspace`, `git`, and `command` tool domains into the SDK loop using existing domain handlers.
- [x] Bind tool domain context to task workspace root and enforce path confinement.
- [x] Normalize tool errors into stable runtime error envelopes.

## Stage 5 - Execution: Task Runtime Integration

- [x] Ensure flowchart/task execution paths pass required workspace context into SDK tool loop runs.
- [x] Ensure executor startup provisions isolated ephemeral workspace storage and clone targets that pod-local workspace root.
- [x] Ensure cloned GitHub workspace workflows are tool-accessible during task execution inside executor-local ephemeral storage.
- [x] Persist tool execution evidence into run/task metadata where required.

## Stage 6 - Execution: Provider Rollout Slice

- [x] Implement SDK tool-loop support for `codex`, `gemini`, and `claude`.
- [x] Validate provider capability parity for MCP server usage, tool usage, and workspace mutation workflows.
- [x] Enforce explicit provider-level unsupported-tool behavior.

## Stage 7 - Automated Testing

- [x] Add unit tests for SDK tool loop behavior (single tool call, multi-step tool loops, error handling).
- [x] Add integration tests for workspace/git/command tool dispatch from SDK runs.
- [x] Add end-to-end test(s) proving repo workflow for `codex` and `gemini` (`branch -> edit -> test -> commit -> push -> PR creation`) with full verbose output assertions.
- [x] Run Gemini runtime verification coverage (general functionality plus tool/workspace flows).
- [x] Run Claude best-effort non-auth validation and explicitly document auth-blocked coverage gaps.
- [x] Run targeted backend suites and record results.

### Stage 7 Evidence (2026-02-21)

- Added SDK loop unit/integration/e2e coverage in:
  - `app/llmctl-studio-backend/tests/test_agent_runtime_abstraction.py`
  - `app/llmctl-studio-backend/tests/test_node_executor_stage6.py`
- Ran targeted suites:
  - `.venv/bin/python -m pytest app/llmctl-studio-backend/tests/test_agent_runtime_abstraction.py` (26 passed)
  - `.venv/bin/python -m pytest app/llmctl-studio-backend/tests/test_tool_domains_stage11.py` (4 passed)
  - `.venv/bin/python -m pytest app/llmctl-studio-backend/tests/test_node_executor_stage6.py` (21 passed)
  - `.venv/bin/python -m pytest app/llmctl-studio-backend/tests/test_frontier_cli_runtime_guardrail.py` (4 passed)
  - `.venv/bin/python -m pytest app/llmctl-studio-backend/tests/test_flowchart_stage9.py -k "run_llm_frontier_routes_via_execution_router_without_cli_subprocess or run_llm_frontier_executor_context_uses_sdk_without_cli_subprocess or run_frontier_llm_sdk_codex_includes_mcp_tools_in_openai_request or run_frontier_llm_sdk_codex_rejects_non_http_mcp_config or run_llm_frontier_sdk_dispatches_to_runtime_abstraction"` (4 passed)
  - `.venv/bin/python -m pytest app/llmctl-studio-backend/tests/test_agent_runtime_abstraction.py -k "gemini or repo_workflow_e2e_gemini or run_frontier_llm_sdk_dispatches_workspace_tool_via_domain_handler or run_frontier_llm_sdk_dispatches_git_tool_via_domain_handler or run_frontier_llm_sdk_dispatches_command_tool_via_domain_handler"` (9 passed)
  - `.venv/bin/python -m pytest app/llmctl-studio-backend/tests/test_agent_runtime_abstraction.py -k "claude or non_codex"` (2 passed)
  - `LLMCTL_STUDIO_DATABASE_URI='postgresql+psycopg://llmctl:llmctl@127.0.0.1:15432/llmctl_studio' .venv/bin/python -m pytest app/llmctl-studio-backend/tests/test_claude_provider_stage8.py -k "resolve_claude_auth or claude_cli_diagnostics or ensure_claude_cli_ready or run_llm_claude"` (6 passed)
- Claude auth-blocked coverage gap:
  - Live authenticated Claude SDK execution remains blocked in this environment due missing real `ANTHROPIC_API_KEY`; validation remains best-effort via non-auth/unit/runtime-path coverage.

## Stage 8 - Docs Updates

- [x] Update runtime docs for SDK tool-calling behavior and provider capability matrix.
- [x] Update operator/developer docs for guardrails, defaults, and rollout flags.
- [x] Update planning artifact with final decisions and evidence links.

### Stage 8 Evidence (2026-02-21)

- Runtime/operator/developer docs updated:
  - `docs/sphinx/node_executor_runtime.rst`
  - `docs/sphinx/changelog.rst`
- Planning artifact updated with final Stage 7 test evidence and Claude auth-blocked coverage note:
  - `docs/planning/active/SDK_WORKSPACE_TOOLING_INTEGRATION_PLAN.md`
