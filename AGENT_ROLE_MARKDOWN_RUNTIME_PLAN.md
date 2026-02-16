# Agent + Role Markdown Runtime Materialization Plan

Date: 2026-02-16
Status: Draft
Owner: Runtime / Flowchart execution

## Locked Decisions (2026-02-16)

- Provider-native runtime filenames are fixed for frontier providers:
  - Codex: `AGENTS.md`
  - Gemini CLI: `GEMINI.md`
  - Claude Code: `CLAUDE.md`
- Runtime materializes the provider file into the run workspace for each node execution.
- Non-frontier models (currently vLLM Local/Remote model entries such as Qwen/GLM) get a per-model setting: `agent_markdown_filename`.
- Hierarchical repository instruction-file behavior is accepted for phase 1 (no repository-file isolation/sanitization yet).
- Hard caps are deferred for now; add observability-only size logging first.

## Goal

Replace prompt-baked Agent/Role payload injection with a runtime materialization pipeline that:

- Resolves Agent + Role instructions per node run.
- Compiles canonical markdown artifacts per run.
- Materializes provider-native instruction files into the run workspace/home.
- Runs provider CLIs in run-scoped isolated environments.
- Keeps prompt-envelope fallback only where native file behavior is unavailable.

This extends the same isolation principles already planned for Skills.

## Why

Current behavior relies on embedding `system_contract` and `agent_profile` in prompt envelopes (`app/llmctl-studio/src/services/tasks.py`).

Problems with prompt-only approach:

- Large repeated context payload per run.
- Harder provenance/debug for instruction precedence.
- Provider-specific instruction mechanisms (AGENTS/CLAUDE/GEMINI files) are underused.
- We lose natural ecosystem behavior for hierarchical/local instruction files.

## Non-Goals

- No immediate removal of prompt-envelope logic on day one.
- No migration of every historical Agent/Role record in one cut unless validated.
- No provider-specific instruction behavior emulation beyond documented capabilities.

## Provider Behavior Workshop (What we need to design around)

### OpenAI (Codex)

- Native instruction file: `AGENTS.md`.
- Discovery supports layering at global and project scopes.
- Project discovery walks from project root to current working directory and concatenates root-to-leaf.
- Discovery has a combined byte cap (`project_doc_max_bytes`, default 32 KiB) and fallback filename list support (`project_doc_fallback_filenames`).

Implications:

- Runtime writes generated `AGENTS.md` at run workspace root.
- Run-scoped `CODEX_HOME` is required so global instruction state is isolated per run.
- Keep generated docs compact and deterministic to avoid truncation at byte cap.

### Google (Gemini CLI)

- Default context filename: `GEMINI.md`.
- Hierarchical loading includes global (`~/.gemini/GEMINI.md`), ancestor/project, and subdirectory context files.
- Supports `@file` imports.

Implications:

- Adapter generates `GEMINI.md` in run workspace root.
- Must isolate `HOME`/Gemini settings per run to prevent cross-run global bleed.

### Anthropic (Claude Code)

- Native memory files include `CLAUDE.md` and `.claude/CLAUDE.md`.
- Additional modular rules are supported via `.claude/rules/*.md`.
- Claude loads memory hierarchically (cwd upward) and can include subtree files on demand.
- More specific instructions override broader ones.
- `CLAUDE.local.md` is supported for personal project preferences.

Implications:

- Adapter materializes generated `CLAUDE.md` in run workspace root for phase 1.
- Run-scoped home/config isolation is required to avoid loading unintended user-global memory.
- Keep precedence tests when repository already contains `CLAUDE.md` and/or `.claude/CLAUDE.md`.

### vLLM + Qwen

- vLLM provides OpenAI-compatible Chat/Responses interfaces.
- vLLM chat behavior depends on model chat template support.
- If a model has no chat template, `--chat-template` is required; otherwise chat requests fail.
- Qwen vLLM guidance shows tokenizer-provided chat templates and system-message usage.
- There is no built-in AGENTS/CLAUDE/GEMINI file semantics in vLLM itself.

Implications:

- For non-frontier/vLLM models, use configurable `agent_markdown_filename` from model config.
- Materialize that filename into run workspace for consistency/audit.
- Continue injecting compiled instructions into structured system context for vLLM runtime behavior.

## Architecture Proposal

### Canonical instruction package

Introduce a provider-agnostic package generated per run:

- `ROLE.md` (resolved role guidance)
- `AGENT.md` (resolved agent guidance)
- `INSTRUCTIONS.md` (compiled output with deterministic merge order)
- `manifest.json` (hashes, source ids, versions, size metadata)

Merge order (base -> specific):

1. Global defaults (future)
2. Role markdown
3. Agent markdown
4. Node/task execution overrides
5. Provider adapter suffix/header (if needed)

### Runtime adapter layer

`services/instruction_adapters/` (new)

- `base.py`: interface (`materialize`, `fallback_payload`, `describe`)
- `codex.py`: writes `AGENTS.md`
- `gemini.py`: writes `GEMINI.md`
- `claude.py`: writes `CLAUDE.md`
- `vllm.py`: no native file injection; returns fallback system context mapping

### Execution pipeline integration

In `app/llmctl-studio/src/services/tasks.py` flowchart task node path and agent task path:

1. Resolve Agent + Role source records.
2. Build canonical instruction package.
3. Materialize provider-native files into run workspace/home.
4. Persist resolved metadata on run records.
5. Launch provider CLI with run-scoped env/home.
6. On failure, fallback to prompt-envelope injection if adapter mode is unsupported.
7. Cleanup run-local materialization on completion.

### Model settings for non-frontier filenames

Add model-config setting for non-frontier providers:

- key: `agent_markdown_filename`
- allowed charset: `[A-Za-z0-9._-]`
- must end with `.md`
- default for vLLM models: `AGENTS.md`

UI/runtime integration points:

- Config parser/writer: `app/llmctl-studio/src/web/views.py` (`_model_config_payload`)
- Create form: `app/llmctl-studio/src/web/templates/model_new.html`
- Edit form: `app/llmctl-studio/src/web/templates/model_edit.html`
- Runtime resolver: `app/llmctl-studio/src/services/tasks.py`

## Data Model and Persistence

Add run-level snapshot fields for Agent/Role materialization (mirroring skills snapshot pattern):

- `resolved_role_id`
- `resolved_role_version`
- `resolved_agent_id`
- `resolved_agent_version`
- `resolved_instruction_manifest_hash`
- `instruction_adapter_mode` (`native`, `fallback`)
- `instruction_materialized_paths_json`

Optional future package tables (if versioning is required like Skills):

- `role_versions`, `role_files`
- `agent_versions`, `agent_files`

## Rollout Stages

### Stage 0 - RFC + behavior lock

- Finalize canonical merge order and precedence rules.
- Accept repository/native hierarchical instruction files for phase 1 (no sanitization).
- Defer hard caps; add size logging/warnings only.
- Define observability contract.

### Stage 1 - Canonical compiler

- Build `services/instructions.py` with deterministic compiler.
- Unit tests for merge order, hashing, normalization.
- Write package into run-local `.llmctl/instructions/`.

### Stage 2 - Provider adapters

- Implement Codex/Gemini/Claude/vLLM adapters.
- Add adapter-level integration tests with temporary workspaces.
- Validate no writes outside run-local workspace/home.

### Stage 3 - Runtime integration

- Hook adapters into `_execute_agent_task` and `_execute_flowchart_task_node`.
- Preserve existing prompt-envelope behavior as fallback path.
- Persist run snapshots and adapter mode.

### Stage 4 - Cutover

- Default to native adapter mode where supported.
- Keep fallback mode guarded by feature flag.
- Remove direct Agent/Role prompt-baking from normal path after burn-in.

### Stage 5 - Hardening

- Concurrency tests (>=100 simultaneous runs).
- Cross-provider regression suite.
- Security review of path traversal/import behavior.

## Precedence and Conflict Rules (Proposed)

- Direct user/system runtime instructions always highest priority.
- Runtime-generated provider file is written at workspace root using provider-native default name.
- Existing repo instruction files are not removed or rewritten in phase 1.
- Hierarchical loading behavior from provider CLIs is accepted in phase 1.
- Deterministic precedence hardening is deferred to a later isolation phase.

## Naming and Location Strategy (Proposed)

- Canonical internal package location: `.llmctl/instructions/`
- Codex materialization:
  - Workspace: `<run_workspace>/AGENTS.md`
  - Run home: `<run_codex_home>/AGENTS.md` only when global defaults are intentionally used.
- Gemini materialization:
  - Workspace: `<run_workspace>/GEMINI.md`
  - Run settings: `<run_home>/.gemini/settings.json` (no filename override needed in phase 1).
- Claude materialization:
  - Workspace: `<run_workspace>/CLAUDE.md`
  - Optional modular support deferred.
- vLLM/Qwen materialization:
  - Workspace: `<run_workspace>/<agent_markdown_filename>` from model config
  - Runtime mapping: structured system message in chat payload.

## Security and Isolation Requirements

- Every node run has unique workspace + provider home.
- No global mutable config writes during execution.
- External import mechanisms (`@file`) are constrained to run workspace unless explicitly allowed.
- Cleanup removes all run-local instruction artifacts after completion (except retained debug snapshots if configured).

## Testing Strategy

- Unit:
  - Compiler merge order.
  - Markdown normalization and hashing.
  - Adapter path generation and file content checks.
- Integration:
  - Codex loads generated `<run_workspace>/AGENTS.md`.
  - Gemini loads generated `<run_workspace>/GEMINI.md`.
  - Claude loads generated `<run_workspace>/CLAUDE.md`.
  - vLLM/Qwen materializes configured `<agent_markdown_filename>`.
  - vLLM/Qwen receives compiled system instructions via messages.
- Stress:
  - 100 parallel runs with disjoint Agent/Role payloads and zero cross-run leakage.

## Open Questions

- Should Agent/Role become fully versioned file packages now, or after initial adapter rollout?
- For non-frontier models, should `agent_markdown_filename` be shown only for vLLM providers or for all non-frontier providers as they are added?
- Should we enforce stronger filename constraints (for example deny hidden files) beyond charset + `.md` suffix?
- Should we add only a soft warning threshold for oversized instruction markdown in phase 1?
- Should fallback prompt injection be disabled per-provider behind independent flags?

## References

- OpenAI Codex AGENTS docs: https://developers.openai.com/codex/guides/agents-md
- OpenAI Codex announcement (AGENTS mention): https://openai.com/index/introducing-codex/
- Gemini CLI context docs: https://google-gemini.github.io/gemini-cli/docs/cli/gemini-md.html
- Claude memory docs: https://code.claude.com/docs/en/memory
- vLLM OpenAI-compatible server docs: https://docs.vllm.ai/en/latest/serving/openai_compatible_server/
- Qwen vLLM deployment docs: https://qwen.readthedocs.io/en/v2.5/deployment/vllm.html
