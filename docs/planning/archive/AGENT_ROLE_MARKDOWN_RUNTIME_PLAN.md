# Agent + Role Markdown Runtime Materialization Plan

**Work checklist instructions**
- Check off each subtask as it is completed.
- Use `- [x]` for done and `- [ ]` for not done.
- Update this file in place as work progresses.
- Keep this plan aligned with `AGENTS.md` planning workflow requirements.

Goal: replace prompt-baked Agent/Role payload injection with a runtime materialization pipeline that compiles canonical markdown artifacts per run, writes provider-native instruction files in run-scoped workspaces, and keeps fallback prompt injection only where native behavior is unavailable. Agent behavior is `Role + Agent (+ Priorities for autorun only)`.

## Decision log (captured on 2026-02-16)

- [x] Provider-native runtime filenames are fixed for frontier providers:
  - [x] Codex: `AGENTS.md`
  - [x] Gemini CLI: `GEMINI.md`
  - [x] Claude Code: `CLAUDE.md`
- [x] Runtime materializes provider files into the run workspace for each execution.
- [x] Each run materializes exactly one provider-native compiled instruction file (`AGENTS.md` / `GEMINI.md` / `CLAUDE.md` / configured filename).
- [x] Non-frontier models use per-model `agent_markdown_filename`.
- [x] Hierarchical repository instruction-file behavior is accepted for phase 1.
- [x] Hard caps are deferred for now; add observability-only size logging first.
- [x] Prompt-envelope fallback remains available where adapter-native behavior is unavailable.
- [x] Roles remain first-class records and are not removed from schema/runtime.
- [x] Agents continue to reference one Role (`agent.role_id`).
- [x] Agents gain ordered Priorities used only for autorun executions.
- [x] Priorities are compiled into provider markdown only for autorun; omitted for one-off/task runs.
- [x] Priority order is deterministic and user-controlled (stored order is preserved in compiled output).
- [x] Agent/Role file-package versioning is deferred until after initial adapter rollout.
- [x] `agent_markdown_filename` is exposed for non-frontier providers (not vLLM-only).
- [x] Hidden filenames are denied for `agent_markdown_filename` (no leading `.`).
- [x] Oversize instruction markdown handling remains warning-only in phase 1.
- [x] Fallback prompt injection is controlled by independent per-provider flags.

## Non-negotiable constraints

- [x] Do not regress existing Agent task and Flowchart node execution behavior.
- [x] Keep provider homes/config run-scoped and isolated from user-global state.
- [x] Do not remove existing repository instruction files during phase 1.
- [x] For template/pipeline updates, treat changes as DB updates unless explicitly asked to update seed data.

## Definition of done

- [x] Runtime resolves Agent + Role sources per run and compiles deterministic markdown artifacts.
- [x] Runtime resolves Agent Priorities and conditionally includes them only for autorun compilation.
- [x] Provider-native files materialize correctly for Codex/Gemini/Claude in run workspace roots.
- [x] Non-frontier runtime supports validated `agent_markdown_filename` behavior.
- [x] Fallback prompt path remains available and auditable where native behavior is unsupported.
- [x] Run records persist instruction resolution/materialization snapshot metadata.
- [x] Isolation guarantees are validated (no cross-run/global config leakage).
- [x] Automated tests cover compiler, adapters, runtime integration, and regressions.
- [x] Sphinx and Read the Docs docs are updated with final behavior.

## Stage 0 - Requirements Gathering

- [x] Capture and lock current architectural intent from existing draft.
- [x] Capture target provider-native file mapping and fallback expectations.
- [x] Capture phase 1 isolation and precedence assumptions.
- [x] Interview and close unresolved requirements before implementation planning:
  - [x] Roles stay in the product and remain assignable to Agents.
  - [x] Agent Priorities are introduced as ordered per-agent entries.
  - [x] Priorities are runtime-compiled into markdown for autorun only.
  - [x] Non-autorun execution omits Priorities and uses Role (+ Agent base instructions).
  - [x] `agent_markdown_filename` is exposed for non-frontier providers as they are added.
  - [x] Deny hidden filenames in addition to charset + `.md` constraints.
  - [x] Oversize markdown handling is warning-only in phase 1.
  - [x] Fallback prompt injection is controlled by independent per-provider flags.

Deliverables:
- [x] Baseline requirements captured in this file.
- [x] Remaining Stage 0 requirement questions answered and recorded.

## Stage 0 closed requirement log

- [x] Versioned Agent/Role file-package persistence is deferred until post-rollout hardening.
- [x] Roles are explicitly retained (no Role schema deletion/cutover).
- [x] Agent instruction model is `Role + Agent`; Priorities are a conditional layer for autorun.
- [x] Run-mode compile matrix is locked:
  - [x] autorun -> `Role + Agent + Priorities`
  - [x] non-autorun task/node/quick -> `Role + Agent` (no Priorities)
- [x] Non-frontier providers share `agent_markdown_filename` behavior to avoid future UI/runtime divergence.
- [x] Hidden filenames are disallowed (`.`-prefixed names blocked) to reduce ambiguity and abuse risk.
- [x] Phase 1 oversize behavior is observability + warnings only (no hard reject/truncation policy yet).
- [x] Fallback prompt behavior is feature-flagged per provider for safer incremental cutover.

## Stage 1 - Code Planning

- [x] Define Stage 2 through Stage 5 implementation sequence with exact file touchpoints.
- [x] Define compiler contract (merge order by run mode, normalization, hashing, manifest fields).
- [x] Define adapter contract (`materialize`, `fallback_payload`, `describe`) and provider-specific behavior.
- [x] Define runtime integration points in `app/llmctl-studio/src/services/tasks.py` for agent and flowchart paths.
- [x] Define data-model migration plan for run snapshot metadata fields.
- [x] Define Agent Priorities data model + ordering contract.
- [x] Define rollout, fallback, and rollback strategy.

Deliverables:
- [x] Finalized Stage 2-5 task breakdown plus Stage 6-7 completion criteria.
- [x] File-level architecture map and migration ordering.

### Stage 1 Output (2026-02-16)

#### Stage 2-5 implementation sequence and exact touchpoints

- Stage 2 (compiler + package artifacts):
  - `app/llmctl-studio/src/services/instructions/compiler.py` (new)
  - `app/llmctl-studio/src/services/instructions/package.py` (new)
  - `app/llmctl-studio/src/services/instructions/__init__.py` (new)
  - `app/llmctl-studio/src/services/tasks.py` (wire package build inputs and on-disk target path)
- Stage 3 (provider adapters + model filename setting + priorities surfaces):
  - `app/llmctl-studio/src/services/instruction_adapters/base.py` (new)
  - `app/llmctl-studio/src/services/instruction_adapters/codex.py` (new)
  - `app/llmctl-studio/src/services/instruction_adapters/gemini.py` (new)
  - `app/llmctl-studio/src/services/instruction_adapters/claude.py` (new)
  - `app/llmctl-studio/src/services/instruction_adapters/vllm.py` (new)
  - `app/llmctl-studio/src/services/instruction_adapters/__init__.py` (new)
  - `app/llmctl-studio/src/web/views.py` (`agent_markdown_filename` read/write + validation wiring)
  - `app/llmctl-studio/src/web/templates/model_new.html` (`agent_markdown_filename` input for non-frontier providers)
  - `app/llmctl-studio/src/web/templates/model_edit.html` (`agent_markdown_filename` input for non-frontier providers)
  - `app/llmctl-studio/src/core/models.py` (`AgentPriority` model + `Agent.priorities` relationship)
  - `app/llmctl-studio/src/core/db.py` (`agent_priorities` + run snapshot columns in ensure-schema migration)
  - `app/llmctl-studio/src/web/views.py` (Agent priority create/edit/reorder/delete handlers)
  - `app/llmctl-studio/src/web/templates/agent_detail.html` (or current Agent detail/edit templates for priorities UI)
  - `app/llmctl-studio/src/web/templates/agent_edit.html` (or current Agent detail/edit templates for priorities UI)
- Stage 4 (runtime integration + persistence):
  - `app/llmctl-studio/src/services/tasks.py` (`_execute_agent_task`, `_execute_flowchart_task_node`, helper extraction)
  - `app/llmctl-studio/src/core/models.py` (`AgentTask`/`FlowchartRunNode`/`Run` snapshot fields as finalized)
  - `app/llmctl-studio/src/core/db.py` (schema add for finalized snapshot fields)
- Stage 5 (cutover, observability, hardening):
  - `app/llmctl-studio/src/services/tasks.py` (native-vs-fallback mode logging + warning-only size telemetry)
  - `app/llmctl-studio/src/web/views.py` and `app/llmctl-studio/src/web/templates/settings_runtime.html` (provider feature flags if surfaced in settings)
  - `app/llmctl-studio/src/services/integrations.py` (provider flag load/save helpers if persisted in integration settings)

#### Compiler contract (locked)

- Inputs:
  - role source (`role_id`, role markdown/body)
  - agent source (`agent_id`, agent markdown/body)
  - ordered priority entries (only if run mode is autorun)
  - runtime overrides (`task`/`flowchart node` overrides)
  - provider context (`provider`, adapter descriptor)
- Canonical file package:
  - always `ROLE.md`, `AGENT.md`, `INSTRUCTIONS.md`, `manifest.json`
  - `PRIORITIES.md` only when `run_mode=autorun` and at least one priority exists
- Merge order is stable and locked:
  - role markdown
  - agent markdown
  - priorities markdown (autorun only)
  - runtime/node overrides
  - provider adapter header/suffix
- Normalization rules:
  - UTF-8 text output, newline normalized to `\n`
  - trailing whitespace trimmed per line
  - single trailing newline at EOF
  - deterministic section headings and separator format
- Hashing + manifest:
  - SHA-256 for each artifact
  - package hash is SHA-256 of canonical JSON manifest payload (sorted keys, compact separators)
  - manifest fields include source ids/versions, run mode, provider, file sizes, artifact hashes, timestamp, package version

#### Adapter contract (locked)

- Interface:
  - `materialize(compiled, workspace, runtime_home, codex_home) -> AdapterMaterializationResult`
  - `fallback_payload(compiled) -> dict[str, object] | str`
  - `describe() -> AdapterDescriptor`
- Behavior by provider:
  - Codex adapter writes `AGENTS.md` in run workspace root and reports native mode.
  - Gemini adapter writes `GEMINI.md` in run workspace root and reports native mode.
  - Claude adapter writes `CLAUDE.md` in run workspace root and reports native mode.
  - vLLM adapter writes configured filename when valid and always returns fallback payload for system/user context path.
- Adapter result contract:
  - `mode` (`native` or `fallback`)
  - `adapter` (adapter name/id)
  - `materialized_paths` (absolute paths written during run)
  - optional warning fields (for oversize and fallback downgrades)

#### Runtime integration contract (locked)

- `_execute_agent_task` integration order:
  - resolve agent+role(+priorities for autorun) before `_run_llm`
  - compile + package into `<workspace>/.llmctl/instructions/`
  - call adapter materialization after workspace/home are prepared and before LLM launch
  - if adapter mode is fallback, inject fallback payload into current prompt-envelope path
  - persist resolved snapshot metadata on run-associated record before execution
- `_execute_flowchart_task_node` integration order:
  - when node resolves an agent, apply same compile/materialize path
  - enforce non-autorun behavior (`Role + Agent`, no priorities)
  - persist node-run instruction snapshot metadata parallel to skill snapshot fields
- Existing prompt-envelope behavior remains as fallback path for unsupported/native-failure scenarios.

#### Data model migration plan (locked)

- `AgentTask` snapshot fields (task + autorun execution trace):
  - `resolved_role_id`
  - `resolved_role_version`
  - `resolved_agent_id`
  - `resolved_agent_version`
  - `resolved_instruction_manifest_hash`
  - `instruction_adapter_mode`
  - `instruction_materialized_paths_json`
- `FlowchartRunNode` receives parallel instruction snapshot fields for node-scoped execution audits.
- `Run` receives summary-level resolved fields if needed for top-level autorun diagnostics; `AgentTask` remains source-of-truth per execution.
- `core/db.py` adds fields with additive `_ensure_columns` migrations only (no destructive migration in phase 1).

#### Agent priorities model and ordering contract (locked)

- New table: `agent_priorities`
  - `id`, `agent_id`, `position`, `content`, `created_at`, `updated_at`
- Ordering:
  - compile order is ascending `position`, tie-break by `id`
  - reorder endpoint writes contiguous positions
  - runtime never re-sorts alphabetically or by timestamp
- Inclusion rules:
  - autorun includes priorities section
  - non-autorun excludes priorities section even when priorities exist

#### Rollout, fallback, and rollback strategy (locked)

- Per-provider feature flags:
  - `instruction_native_enabled_<provider>`
  - `instruction_fallback_enabled_<provider>`
- Runtime behavior:
  - if native enabled and adapter succeeds -> native mode
  - if native fails and fallback enabled -> fallback mode + warning log
  - if native fails and fallback disabled -> task failure (explicit operator-facing error)
- Rollback:
  - disable native flag for provider to return to prompt-envelope only path
  - retain compiler/package emission logs for diagnosis during rollback
- Phase 1 size policy:
  - warning-only telemetry for compiled markdown sizes; no hard reject/truncation
- Stage 6/7 completion criteria locked:
  - Stage 6 must cover compiler, adapters, runtime integration, run-mode matrix, and isolation regressions.
  - Stage 7 must update operator/runtime/model docs plus Sphinx/Read the Docs/changelog.

## Stage 2 - Canonical Compiler and Packaging

- [x] Implement compiler module for deterministic instruction assembly.
- [x] Generate run-local canonical package artifacts:
  - [x] `ROLE.md`
  - [x] `AGENT.md`
  - [x] `PRIORITIES.md` (only when autorun and priorities exist)
  - [x] `INSTRUCTIONS.md`
  - [x] `manifest.json` (hashes, source ids, version metadata, size metadata)
- [x] Compile `INSTRUCTIONS.md` as the single source for provider-native file emission.
- [x] Enforce merge order (base -> specific):
  - [x] role markdown
  - [x] agent markdown
  - [x] agent priorities (autorun only)
  - [x] runtime/node overrides
  - [x] provider adapter suffix/header (when required)
- [x] Materialize package into run-local `.llmctl/instructions/`.

Deliverables:
- [x] Deterministic compiler + package writer with stable hashing behavior.

## Stage 3 - Provider Adapters and Non-Frontier Filename Setting

- [x] Add instruction adapter layer in `services/instruction_adapters/`:
  - [x] `base.py`
  - [x] `codex.py` (`AGENTS.md`)
  - [x] `gemini.py` (`GEMINI.md`)
  - [x] `claude.py` (`CLAUDE.md`)
  - [x] `vllm.py` (fallback system-context mapping + optional filename materialization behavior)
- [x] Add non-frontier model setting `agent_markdown_filename`:
  - [x] parser/writer in `app/llmctl-studio/src/web/views.py`
  - [x] create form in `app/llmctl-studio/src/web/templates/model_new.html`
  - [x] edit form in `app/llmctl-studio/src/web/templates/model_edit.html`
  - [x] runtime resolver integration in `app/llmctl-studio/src/services/tasks.py`
- [x] Enforce filename validation:
  - [x] charset `[A-Za-z0-9._-]`
  - [x] `.md` suffix
  - [x] deny leading `.` (no hidden filenames)
- [x] Add Agent Priorities product surfaces:
  - [x] schema for ordered priorities linked to `agents`
  - [x] create/edit/reorder/delete in Agent UI
  - [x] serialization for runtime compiler consumption

Deliverables:
- [x] Working provider adapter set with validated filename configuration support.

## Stage 4 - Runtime Integration and Persistence

- [x] Integrate compiler + adapters into:
  - [x] `_execute_agent_task`
  - [x] `_execute_flowchart_task_node`
- [x] Enforce conditional compile behavior:
  - [x] autorun => include Priorities in generated provider markdown
  - [x] non-autorun => omit Priorities from generated provider markdown
  - [x] preserve explicit Priority ordering in compiled markdown
- [x] Apply run-scoped workspace/home materialization and cleanup behavior.
- [x] Preserve prompt-envelope fallback path for unsupported/native-failure scenarios.
- [x] Persist run snapshot fields:
  - [x] `resolved_role_id`
  - [x] `resolved_role_version`
  - [x] `resolved_agent_id`
  - [x] `resolved_agent_version`
  - [x] `resolved_instruction_manifest_hash`
  - [x] `instruction_adapter_mode`
  - [x] `instruction_materialized_paths_json`

Deliverables:
- [x] End-to-end runtime path using native file materialization where available.

## Stage 5 - Cutover, Hardening, and Observability

- [x] Enable native adapter mode by default for supported providers.
- [x] Keep fallback mode feature-flagged for rollback safety.
- [x] Add observability for instruction materialization size/paths and adapter mode.
- [x] Validate isolation and security behavior:
  - [x] no writes outside run-local workspace/home
  - [x] no global mutable config writes during execution
  - [x] evaluate `@file`/path traversal exposure in accepted phase 1 behavior
- [x] Run high-concurrency validation (`>=100` parallel runs) with zero cross-run leakage.

Deliverables:
- [x] Production-ready rollout posture with rollback controls and observability.

## Stage 6 - Automated Testing

- [x] Unit tests:
  - [x] compiler merge order, normalization, hashing
  - [x] manifest content and deterministic output
  - [x] adapter path generation and file content behavior
  - [x] filename validation for `agent_markdown_filename`
  - [x] priorities-included for autorun and priorities-omitted for non-autorun
  - [x] priority ordering is preserved in compiled output
- [x] Integration tests:
  - [x] Codex loads generated `<run_workspace>/AGENTS.md`
  - [x] Gemini loads generated `<run_workspace>/GEMINI.md`
  - [x] Claude loads generated `<run_workspace>/CLAUDE.md`
  - [x] vLLM/non-frontier materializes configured filename and receives fallback system context
  - [x] runtime snapshots persist expected metadata fields
  - [x] Role + Agent compile works when no priorities are configured
  - [x] Role + Agent + Priorities compile works for autorun
  - [x] provider-native file content matches expected run-mode matrix for codex/gemini/claude
- [x] Regression/stress tests:
  - [x] existing prompt-envelope behavior preserved under fallback
  - [x] non-agent runtime behavior unaffected
  - [x] parallel-run isolation under load

Deliverables:
- [x] Green automated suite for compiler, adapters, runtime integration, and regression coverage.

## Stage 7 - Docs Updates

- [x] Update runtime architecture docs for instruction compilation/materialization flow.
- [x] Update operator docs for provider-native files and fallback behavior.
- [x] Update model configuration docs for `agent_markdown_filename`.
- [x] Update Sphinx documentation pages.
- [x] Update Read the Docs content and release notes/changelog.

Deliverables:
- [x] Documentation fully reflects production behavior and rollout guidance.

## References

- OpenAI Codex AGENTS docs: https://developers.openai.com/codex/guides/agents-md
- OpenAI Codex announcement: https://openai.com/index/introducing-codex/
- Gemini CLI context docs: https://google-gemini.github.io/gemini-cli/docs/cli/gemini-md.html
- Claude memory docs: https://code.claude.com/docs/en/memory
- vLLM OpenAI-compatible server docs: https://docs.vllm.ai/en/latest/serving/openai_compatible_server/
- Qwen vLLM deployment docs: https://qwen.readthedocs.io/en/v2.5/deployment/vllm.html
