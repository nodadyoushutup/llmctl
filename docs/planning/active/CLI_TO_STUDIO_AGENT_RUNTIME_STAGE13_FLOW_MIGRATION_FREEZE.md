# CLI To Studio Agent Runtime Migration - Stage 13 Flow Migration Tooling Freeze

Date: 2026-02-20
Source stage: `docs/planning/active/CLI_TO_STUDIO_AGENT_RUNTIME_MIGRATION_FANOUT_PLAN.md` (Stage 13)

## Stage 13 Completion Checklist

- [x] Implement one-time flowchart schema transform pipeline for legacy definition migration.
- [x] Implement post-transform validation and dry-run execution checks before migration acceptance.
- [x] Implement compatibility gate reporting for non-migratable or policy-violating flow definitions.
- [x] Implement migration evidence artifacts and rollback-trigger metadata capture.

## 1) One-Time Flowchart Schema Transform Pipeline

Implemented service:

- `app/llmctl-studio-backend/src/services/flow_migration.py`

Delivered pipeline behavior:

- Builds canonical flowchart snapshots (nodes/edges/config) from database state.
- Transforms legacy routing/config patterns into Stage 13 contract-ready snapshots.
- Normalizes invalid/missing edge modes to stable runtime defaults (`solid`).
- Repairs decision connector compatibility by generating/deduplicating connector IDs and rehydrating `decision_conditions`.
- Removes legacy route metadata keys no longer used by canonical routing.

Operational entrypoint:

- `app/llmctl-studio-backend/scripts/migrate_flowchart_runtime_schema.py`

## 2) Post-Transform Validation + Dry-Run Execution Checks

Validation layer in `services/flow_migration.py` now enforces:

- Node type, ref-id, and task prompt invariants.
- Utility binding policy compatibility (model/MCP/script/skill/attachment).
- Decision fallback/no-match policy consistency.
- Fan-in custom count validity and range checks.
- Start/end node topology invariants.

Dry-run execution checks:

- Runs fan-in requirement resolution against transformed config.
- Runs route-resolution simulations through runtime routing helpers (`_resolve_flowchart_outgoing_edges`).
- Surfaces route/fan-in dry-run failures as migration-blocking compatibility issues.

## 3) Compatibility Gate Reporting

Compatibility gate report now includes:

- `status` (`ready` or `blocked`)
- explicit `blocking_issue_codes`
- warning issue codes
- error/warning counts
- full issue payload list with `code`, `message`, `severity`, and node/edge scope metadata

Policy and validation violations are surfaced before apply-mode writes.

## 4) Evidence Artifacts + Rollback Triggers

Per-flow evidence includes:

- contract version + generation timestamp
- pre/post migration snapshots
- pre/post snapshot hashes
- transformed-change indicator
- compatibility gate outcomes
- rollback metadata (`required`, `trigger_codes`, pre/post hashes)

Script output supports durable JSON artifact export via:

- `--export-json <path>`

Rollback trigger metadata is now generated automatically when compatibility gate blocks migration.

## 5) Automated Evidence

Executed suites/commands:

1. `./.venv/bin/python3 -m pytest app/llmctl-studio-backend/tests/test_flow_migration_stage13.py`
2. `./.venv/bin/python3 app/llmctl-studio-backend/scripts/migrate_flowchart_runtime_schema.py --help`
