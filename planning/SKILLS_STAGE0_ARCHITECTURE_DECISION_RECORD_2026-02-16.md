# Skills Stage 0 Architecture Decision Record (2026-02-16)

Status: accepted

Scope: llmctl Studio Skills migration (`Skill Script` -> first-class Skills).

## Context

The legacy runtime path treats skills as script records (`script_type=skill`) and injects them into prompt payloads. Stage 1 schema work is complete for first-class skill entities (`skills`, `skill_versions`, `skill_files`, `flowchart_node_skills`), but Stage 0 required scope and behavior lock for runtime and rollout.

This ADR is the source of truth for Stage 0 decisions referenced by `planning/SKILLS_SYSTEM_MIGRATION_PLAN.md`.

## Decisions

1. Attachment model for v1

- Attachments are node-level only.
- Task-template and agent-level attachment models are deferred.

2. Binding and resolution model

- Skill bindings are defined on reusable entities and snapshotted per run.
- Manual per-run skill assignment is out of normal runtime scope (override APIs may be added later).

3. Merge/precedence order

- Effective precedence order is:
  - system defaults
  - workspace/project
  - entity-attached
- In v1, entity-attached bindings are the only active layer; system/workspace layers are reserved but not independently managed yet.
- Duplicate slug collisions resolve by precedence layer, then deterministic in-layer ordering (`position ASC`, `skill.name ASC`).

4. Context-budget policy

- `SKILL.md` max size: `64 KiB`.
- Max single file size: `256 KiB`.
- Max skill package total size: `1 MiB`.
- `references/*` and `assets/*` are lazy-loaded and never eagerly copied into fallback prompt text.
- Fallback prompt/context injection caps:
  - `12,000` characters per skill
  - `32,000` characters total per run

5. Runtime isolation policy

- Each node run must use a run-local workspace named `run-<flowchart_run_node_id>-<token>`.
- Provider config homes must be run-local (`HOME`, `CODEX_HOME`, and provider-scoped config roots where supported).
- Runtime execution must not mutate shared user/global config paths.

6. Runtime mode

- v1 default is process-isolated execution.
- Containerized node executor is deferred to v1.x.

7. Conflict handling and determinism

- Duplicate skill slug is rejected by `skills.name` uniqueness.
- Duplicate version for the same skill is rejected by unique (`skill_id`, `version`).
- Resolver and adapter materialization order must be deterministic and logged.

8. Native provider targets

- v1 native skill targets:
  - Codex
  - Claude Code
  - Gemini CLI
- Non-native providers use deterministic fallback injection from the same canonical package.

9. GA success criteria ownership

- GA criteria are defined in `planning/SKILLS_SYSTEM_MIGRATION_PLAN.md` under `Acceptance criteria`.

## v1 scope and non-goals

In scope:

- First-class skill entities and immutable versioned files.
- Node-level attachment and deterministic per-run snapshotting.
- Native adapter path for Codex/Claude/Gemini plus deterministic fallback for non-native providers.
- Run-local workspace/provider-home isolation.

Out of scope for v1:

- Task-template and agent attachment models.
- Remote skill registries and sync.
- Secrets reference model inside skill packages.
- Containerized node execution as default runtime.

## Consequences

- Stage 2 must enforce the size/path policies in validation and import/export.
- Stage 3/4 must implement run-local isolation and deterministic adapter behavior.
- Stage 6/7 must remove legacy runtime compatibility path rather than retaining dual-mode execution.
