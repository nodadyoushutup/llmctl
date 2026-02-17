# MCP Server TOML to JSON Migration Plan

Goal: eliminate TOML usage for MCP server configuration and persistence, using JSON end-to-end (including database values).

## Stage 0 - Requirements Gathering
- [x] Confirm target database storage type for migrated values.
- [x] Confirm migration rollout style and compatibility expectations.
- [x] Confirm read/write API contract changes (JSON-only vs transitional compatibility).
- [x] Confirm scope boundaries for TOML removal (code paths, dependencies, docs, seeds).
- [x] Confirm success criteria and rollback expectations.
- [x] Confirm requirements are complete and approved to start Stage 1.

## Stage 0 - Interview Notes
- [x] Database target selected: Postgres `JSONB` for MCP server values.
- [x] Rollout style selected: hard cutover migration (convert existing TOML rows once, then JSON-only read/write).
- [x] API/input contract selected: JSON-only immediately; reject TOML input after cutover.
- [x] Seed decision: migrate MCP seed/bootstrap payloads to JSON in this change.
- [x] Scope boundary selected: strict TOML removal for MCP config across runtime, web/API handlers, seeds, integrated sync, scripts, tests, and docs.
- [x] Migration safety policy: if any existing MCP row is malformed/unparseable, fail migration and abort deployment.

## Stage 1 - Code Planning
- [x] Translate approved Stage 0 requirements into Stage 2 through Stage X execution stages.
- [x] Define concrete file-level scope, dependency order, and acceptance criteria per stage.
- [x] Ensure the final two stages are `Automated Testing` and `Docs Updates`.

## Stage 1 - Execution Order
- [x] Stage 2: Database + model cutover to `JSONB` for `mcp_servers.config_json` with fail-fast migration behavior.
- [x] Stage 3: MCP config utility conversion to JSON-only parsing/validation/rendering semantics (no TOML parsing or rendering).
- [x] Stage 4: MCP runtime/web/seed/integrated code path migration to JSON-native values and strict JSON input handling.
- [x] Stage 5: Script + test updates for JSON-only MCP config behavior.
- [x] Stage 6: Automated Testing.
- [x] Stage 7: Docs Updates.

## Stage 2 - DB + Model JSONB Cutover
- [x] Update ORM model type for `MCPServer.config_json` to JSON-native (`JSONB`).
- [x] Add schema migration logic that converts existing `mcp_servers.config_json` values from legacy TOML/JSON text into normalized `JSONB`.
- [x] Fail migration immediately if any row cannot be parsed/converted.
- [x] Ensure new schema creation path defines `mcp_servers.config_json` as `JSONB NOT NULL`.
- [x] Acceptance criteria: `mcp_servers.config_json` is `JSONB`, existing rows are converted, and malformed rows abort migration.

## Stage 3 - MCP Config Utility JSON-Only Conversion
- [x] Remove TOML parser/renderer behavior from `core.mcp_config`.
- [x] Keep/adjust validation and override flattening behavior for JSON objects.
- [x] Ensure parse errors are JSON-focused and explicit.
- [x] Acceptance criteria: MCP config utility accepts JSON payloads only and produces validated dicts for downstream use.

## Stage 4 - Runtime/Web/Seed/Integrated MCP Path Migration
- [x] Update MCP create/edit handlers to validate JSON-only input and persist JSON-native values.
- [x] Update runtime/task paths to consume MCP config values as JSON objects from DB.
- [x] Update integrated MCP sync and seed logic to build/store JSON objects (no TOML intermediate representation).
- [x] Remove MCP TOML-specific assumptions/messages from backend flows.
- [x] Acceptance criteria: MCP CRUD + runtime execution paths operate JSON-only with DB-backed `JSONB` values.

## Stage 5 - Scripts + Tests Alignment
- [x] Update MCP-related scripts to use JSON-only config handling.
- [x] Update/add tests to cover JSON-only acceptance and TOML rejection behavior.
- [x] Update DB migration tests (or equivalent coverage) for conversion + fail-fast semantics.
- [x] Acceptance criteria: automated coverage reflects JSON-only MCP behavior and guards against TOML regressions.

## Stage 6 - Automated Testing
- [ ] Run targeted backend test suites for MCP/web/runtime/seed/integration paths.
- [x] Run any necessary lint/type checks relevant to touched code.
- [x] Fix regressions discovered by automated checks.
- [ ] Acceptance criteria: all executed automated checks pass.

## Stage 7 - Docs Updates
- [x] Update backend/docs references from TOML MCP config to JSON MCP config.
- [x] Update examples/snippets for MCP server configuration payloads.
- [x] Ensure Sphinx/Read the Docs pages reflect JSON-only MCP config behavior.
- [x] Acceptance criteria: documentation consistently describes JSON-only MCP config semantics and `JSONB` persistence.
