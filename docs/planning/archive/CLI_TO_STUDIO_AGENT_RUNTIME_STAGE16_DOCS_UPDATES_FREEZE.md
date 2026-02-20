# CLI To Studio Agent Runtime Migration - Stage 16 Docs Updates Freeze

Date: 2026-02-20
Source stage: `docs/planning/archive/CLI_TO_STUDIO_AGENT_RUNTIME_MIGRATION_SEQUENTIAL_PLAN.md` (Stage 16)

## Stage 16 Completion Checklist

- [x] Update Sphinx and Read the Docs content for runtime architecture, contracts, and operator workflows.
- [x] Update internal developer docs for executor split images, build/release flow, and tool-domain ownership.
- [x] Update API/socket/tool contract references and migration runbook documentation.
- [x] Archive finalized planning and implementation notes with links to test evidence and rollout checklist artifacts.

## 1) Sphinx / Read the Docs Updates

Updated runtime/operator documentation:

- `docs/sphinx/index.rst`
  - Added `agent_runtime_migration_runbook` to Runtime Guides.
- `docs/sphinx/agent_runtime_migration_runbook.rst`
  - Added cutover/rollback runbook covering architecture ownership, split executor images, contract references, migration commands, and sign-off gap inventory.
- `docs/sphinx/node_executor_runtime.rst`
  - Added split image setting keys (`k8s_frontier_image*`, `k8s_vllm_image*`) and `agent_runtime_cutover_enabled` gate coverage.
  - Added Harbor build/release command policy for frontier/vLLM executor images.
  - Added runtime/tool-domain ownership boundary notes.
- `docs/sphinx/studio_serving_runtime.rst`
  - Added explicit pointer to the Stage 13-16 migration runbook.
- `docs/sphinx/changelog.rst`
  - Added `2026-02-20` entry for Stage 16 documentation completion.

## 2) API / Socket / Tool Contract Reference Updates

Added API reference docs:

- `docs/sphinx/api/services.execution.tooling.rst`
- `docs/sphinx/api/services.runtime_contracts.rst`
- `docs/sphinx/api/services.flow_migration.rst`

Updated API toctrees:

- `docs/sphinx/api/services.execution.rst`
  - Added `services.execution.tooling`.
- `docs/sphinx/api/services.rst`
  - Added `services.runtime_contracts` and `services.flow_migration`.

## 3) Finalized Plan + Evidence Archive Links

Final migration evidence and checklist artifacts:

- Stage 14 reconvergence and rollout checklist artifact:
  `docs/planning/archive/CLI_TO_STUDIO_AGENT_RUNTIME_STAGE14_RECONVERGENCE_FREEZE.md`
- Stage 15 automated test evidence and unresolved failure inventory:
  `docs/planning/archive/CLI_TO_STUDIO_AGENT_RUNTIME_STAGE15_AUTOMATED_TESTING_FREEZE.md`
- Stage 16 docs update artifact (this file):
  `docs/planning/archive/CLI_TO_STUDIO_AGENT_RUNTIME_STAGE16_DOCS_UPDATES_FREEZE.md`

Finalized migration planning artifacts are archived from `docs/planning/active/`
to `docs/planning/archive/` as part of Stage 16 completion.
