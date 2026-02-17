# MCP Server TOML to JSON Migration Plan

Goal: eliminate TOML usage for MCP server configuration and persistence, using JSON end-to-end (including database values).

## Stage 0 - Requirements Gathering
- [x] Confirm target database storage type for migrated values.
- [x] Confirm migration rollout style and compatibility expectations.
- [x] Confirm read/write API contract changes (JSON-only vs transitional compatibility).
- [ ] Confirm scope boundaries for TOML removal (code paths, dependencies, docs, seeds).
- [ ] Confirm success criteria and rollback expectations.
- [ ] Confirm requirements are complete and approved to start Stage 1.

## Stage 0 - Interview Notes
- [x] Database target selected: Postgres `JSONB` for MCP server values.
- [x] Rollout style selected: hard cutover migration (convert existing TOML rows once, then JSON-only read/write).
- [x] API/input contract selected: JSON-only immediately; reject TOML input after cutover.

## Stage 1 - Code Planning
- [ ] Translate approved Stage 0 requirements into Stage 2 through Stage X execution stages.
- [ ] Define concrete file-level scope, dependency order, and acceptance criteria per stage.
- [ ] Ensure the final two stages are `Automated Testing` and `Docs Updates`.
