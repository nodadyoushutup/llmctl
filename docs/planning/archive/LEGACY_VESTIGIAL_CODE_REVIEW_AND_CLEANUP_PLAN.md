# Legacy / Vestigial Code Review And Cleanup Plan

**Work checklist instructions**
- [ ] Check off each task as it is completed (`[x]`).
- [ ] Keep this plan updated in place as findings and cleanup progress.
- [ ] Maintain strict separation: identification first, cleanup second.

Goal: identify and clean legacy, vestigial, unused, and mismatched terminology/code paths across Studio frontend, Studio backend, and MCP with explicit review checkpoints.

## Scope

- [x] In scope:
  - [x] `app/llmctl-studio-frontend`
  - [x] `app/llmctl-studio-backend`
  - [x] `app/llmctl-mcp`
- [x] Out of scope by default:
  - [x] `_legacy/`
  - [x] Archive docs except where needed for migration context
- [x] Include schema/database cleanup tasks where legacy surfaces are confirmed.

## Stage 0 - Requirements Gathering

- [x] Confirm scope boundaries with stakeholder.
- [x] Confirm desired workflow style:
  - [x] audit/findings first
  - [x] cleanup execution second
- [x] Confirm findings should be reviewed in detail before cleanup execution.
- [x] Confirm plan should include code + schema cleanup.

### Stage 0 decisions captured

- [x] Plan must be explicitly segregated into:
  - [x] **Identification / Findings section**
  - [x] **Cleanup / Execution section**
- [x] Cleanup work must follow findings review/sign-off.

## Stage 1 - Code Planning

- [x] Define stage sequence with hard gate between findings and cleanup.
- [x] Define a findings register format to track each issue precisely.
- [x] Define cleanup waves grouped by risk/type.
- [x] Set final two stages to:
  - [x] Automated Testing
  - [x] Docs Updates

---

## Section A - Identification / Findings

## Stage 2 - Repository Audit And Findings Inventory

- [x] Build a structured findings register with IDs and evidence.
- [x] Audit categories:
  - [x] Legacy feature shims/fallbacks still active
  - [x] Vestigial dead paths (unreachable routes, unused utilities/components)
  - [x] Terminology mismatches (same concept named differently across FE/BE/MCP)
  - [x] API/schema contract mismatches
  - [x] Transitional DB artifacts no longer needed
  - [x] Test fixtures/coverage still asserting old behavior
- [x] For each finding, capture:
  - [x] `finding_id`
  - [x] location (`file:line`)
  - [x] category
  - [x] current behavior
  - [x] why it is legacy/vestigial/mismatched
  - [x] risk if left unchanged
  - [x] recommended fix
  - [x] estimated cleanup scope (S/M/L)

## Stage 3 - Findings Review, Prioritization, And Cleanup Gate

- [x] Review findings list with stakeholder.
- [x] Group findings into cleanup waves (high-risk first).
- [x] Mark each finding status:
  - [x] approved for cleanup now
  - [x] deferred
  - [x] rejected (keep as-is)
- [x] Freeze Section A output before Section B starts.

### Findings Register (populated in Stage 2)

| finding_id | category | location | summary | risk | recommendation | status |
| --- | --- | --- | --- | --- | --- | --- |
| F-001 | API/schema contract mismatch | `app/llmctl-mcp/src/tools.py:448`, `app/llmctl-mcp/src/tools.py:1135`, `app/llmctl-mcp/src/tools.py:1140`, `app/llmctl-mcp/src/tools.py:1165`, `app/llmctl-studio-backend/src/web/views.py:467`, `app/llmctl-studio-backend/src/web/views.py:6972` | MCP still allows task `ref_id` fallback (`ref_id` or `config.task_prompt`) while backend treats task as prompt-only and disallows `ref_id`. | High | Remove MCP task `ref_id` fallback path and align MCP validation/persistence to backend contract (`config.task_prompt` only for task nodes). | completed_cleanup |
| F-002 | Legacy compatibility shim still active | `app/llmctl-studio-backend/src/web/views.py:1046`, `app/llmctl-studio-backend/src/web/views.py:16278`, `app/llmctl-studio-backend/src/web/views.py:16575`, `app/llmctl-studio-frontend/src/pages/SettingsRuntimePage.jsx:166`, `app/llmctl-studio-frontend/src/pages/SettingsRuntimePage.jsx:338`, `app/llmctl-studio-frontend/src/lib/studioApi.js:1085` | Node skill binding compatibility mode (`warn`/`reject`) remains exposed in backend + frontend runtime settings. | Medium | Retire compatibility mode surface, harden canonical behavior, and remove mode update/read endpoints once cleanup wave starts. | completed_cleanup |
| F-003 | Vestigial deprecated API surface | `app/llmctl-studio-backend/src/web/views.py:12049`, `app/llmctl-studio-backend/src/web/views.py:12091`, `app/llmctl-studio-backend/src/web/views.py:12125` | Deprecated node-skill mutation routes still exist and return warning/reject payloads instead of performing canonical writes. | Medium | Remove deprecated routes (or convert to explicit gone/unsupported response during transition), then remove callers. | completed_cleanup |
| F-004 | Cross-service behavior mismatch | `app/llmctl-mcp/src/tools.py:311`, `app/llmctl-mcp/src/tools.py:2109`, `app/llmctl-mcp/src/tools.py:2147`, `app/llmctl-mcp/src/tools.py:2165`, `app/llmctl-mcp/src/tools.py:2208`, `app/llmctl-mcp/src/tools.py:2262` | MCP still directly mutates `flowchart_node_skills` via bind/unbind/reorder tools. | High | Remove MCP node-skill mutation tools and table-writer helper; route skill ownership through canonical agent-level bindings only. | completed_cleanup |
| F-005 | Transitional DB artifact still active | `app/llmctl-studio-backend/src/core/db.py:1857`, `app/llmctl-studio-backend/src/core/db.py:1944`, `app/llmctl-studio-backend/src/core/db.py:1959`, `app/llmctl-studio-backend/src/core/db.py:1974` | Transitional migration objects for deprecated node-skill bindings are still created/executed (`legacy_unmapped_node_skills`, reject triggers, migration routine). | Medium | Define retirement criteria and remove transitional schema + migration code once data retention/export decision is approved. | completed_cleanup |
| F-006 | Vestigial CLI compatibility flag | `app/llmctl-studio-backend/scripts/update_mcp_stdio_configs.py:60` | `--llmctl-stdio-tap` is explicitly documented as a no-op compatibility flag. | Low | Remove the no-op flag and update any docs/scripts that still pass it. | completed_cleanup |
| F-007 | Test fixture terminology/shape drift | `app/llmctl-studio-frontend/src/components/FlowchartWorkspaceEditor.test.jsx:143` | Task-node test fixture still passes `ref_id: null` despite task nodes being prompt-driven in current contract. | Low | Remove unnecessary task `ref_id` fixture usage and keep tests aligned with canonical task payload shape. | completed_cleanup |
| F-008 | Legacy task-template migration hook still in startup path | `app/llmctl-studio-backend/src/core/db.py:354`, `app/llmctl-studio-backend/src/core/db.py:1554` | DB init still runs `_drop_task_template_schema` and carries explicit `task_template*` cleanup logic every startup. | Low | Retire this migration hook once upgrade window closes and document historical removal in archived migration notes. | completed_cleanup |

### Stage 3 Prioritization Output (Approved)

| wave | findings | rationale |
| --- | --- | --- |
| Wave 1 - Contract hardening | F-001 | Highest-risk cross-service contract mismatch. |
| Wave 2 - Obsolete mutation surface removal | F-003, F-004 | Remove deprecated backend routes and MCP node-skill mutation tools. |
| Wave 3 - Compatibility/runtime shim removal | F-002, F-006 | Remove remaining compatibility toggles and no-op flags. |
| Wave 4 - Schema cleanup | F-005, F-008 | Remove transitional DB artifacts and leftover task-template migration hook. |
| Wave 5 - Test alignment | F-007 | Align fixtures with canonical task-node shape. |

### Stage 2 Detailed Finding Notes

#### F-001
- Current behavior: MCP validation and graph-upsert logic still accept task `ref_id` as valid fallback (`ref_id` or `config.task_prompt`) and persists `ref_id` onto `flowchart_nodes`.
- Why legacy/mismatched: Studio backend validation treats task nodes as prompt-only and rejects any `ref_id` for node types outside `FLOWCHART_NODE_TYPE_WITH_REF`.
- Risk if unchanged: task-template-era semantics can be reintroduced through MCP, creating FE/BE/MCP contract divergence and confusing validation errors.
- Estimated cleanup scope: `M`.

#### F-002
- Current behavior: Runtime settings API and UI still publish and persist `node_skill_binding_mode`.
- Why legacy/mismatched: this is a transitional deprecation shim that keeps non-canonical node-level skill binding behavior configurable.
- Risk if unchanged: permanent compatibility surface and inconsistent operational expectations.
- Estimated cleanup scope: `M`.

#### F-003
- Current behavior: deprecated node-level skill attach/detach/reorder routes remain callable.
- Why legacy/mismatched: endpoint surface still exists for flows that are intended to be removed.
- Risk if unchanged: external callers can continue depending on obsolete endpoints; cleanup gets harder over time.
- Estimated cleanup scope: `M`.

#### F-004
- Current behavior: MCP exposes bind/unbind/reorder flowchart-node-skill tools and directly writes `flowchart_node_skills`.
- Why legacy/mismatched: this bypasses backend deprecation posture and keeps removed ownership model writable.
- Risk if unchanged: cross-service inconsistency and accidental reactivation of node-level skill ownership.
- Estimated cleanup scope: `M`.

#### F-005
- Current behavior: DB bootstrap still provisions transitional artifacts and migration logic for deprecated node-skill mappings.
- Why legacy/mismatched: transitional structures are still active despite canonical ownership shift.
- Risk if unchanged: extra schema/runtime complexity and long-tail maintenance burden.
- Estimated cleanup scope: `M`.

#### F-006
- Current behavior: compatibility CLI switch remains but does nothing.
- Why legacy/mismatched: interface preserved only for historical callers.
- Risk if unchanged: operator confusion and stale invocation patterns.
- Estimated cleanup scope: `S`.

#### F-007
- Current behavior: test payload for task node still includes `ref_id: null`.
- Why legacy/mismatched: keeps old payload shape in fixtures.
- Risk if unchanged: test signals imply `ref_id` is still part of task contract.
- Estimated cleanup scope: `S`.

#### F-008
- Current behavior: task-template drop routine is still called from DB initialization.
- Why legacy/mismatched: task-template removal is complete functionally, but migration cleanup logic remains active.
- Risk if unchanged: lingering terminology and startup migration noise.
- Estimated cleanup scope: `S`.

---

## Section B - Cleanup / Execution

## Stage 4 - Cleanup Wave 1 (Terminology And Contract Alignment)

- [x] Normalize terminology across FE/BE/MCP for approved findings.
- [x] Align payload keys/labels/errors/docs where names mismatch.
- [x] Add compatibility notes only where strictly required.

## Stage 5 - Cleanup Wave 2 (Vestigial / Unused Code Removal)

- [x] Remove approved dead code, stale routes, unused helpers, and obsolete bindings.
- [x] Remove obsolete frontend surfaces and stale backend handlers.
- [x] Remove MCP tools/branches that only support removed legacy concepts.

## Stage 6 - Cleanup Wave 3 (Schema And Migration Hardening)

- [x] Remove approved legacy schema artifacts and transitional migration paths.
- [x] Ensure destructive changes are migration-safe and reversible where practical.
- [x] Validate runtime no longer depends on removed columns/tables/views.

## Stage 7 - Cleanup Wave 4 (Tests And Fixtures Alignment)

- [x] Update tests to reflect canonical behavior only.
- [x] Remove tests that assert deprecated/removed flows.
- [x] Add regression tests for newly cleaned contracts/terminology.

## Stage 8 - Automated Testing

- [x] Run targeted frontend tests for touched areas.
- [x] Run backend and MCP automated tests for touched areas.
- [x] Run lint/type/static checks used by the repo for touched areas.
- [x] Record failures, fixes, and final pass status.

### Stage 8 execution notes

- Frontend tests: `vitest` passed for:
  - `src/lib/studioApi.test.js`
  - `src/components/FlowchartWorkspaceEditor.test.jsx`
- Backend + MCP tests: passed via Postgres wrapper:
  - `app/llmctl-studio-backend/tests/test_skills_stage5.py`
  - `app/llmctl-studio-backend/tests/test_skills_stage6.py`
  - `app/llmctl-mcp/tests/test_flowchart_stage9_mcp.py`
- Test harness updates applied during execution:
  - Stage 5/6 backend tests now use ephemeral PostgreSQL schemas instead of SQLite.
  - MCP Stage 9 test now uses ephemeral PostgreSQL schema isolation.
  - Removed brittle Stage 5 assertions that depended on missing legacy server-rendered templates (`skills.html`, `skill_detail.html`, `skill_import.html`), while preserving CRUD behavior checks.
- Static checks:
  - `python3 -m py_compile` passed for touched backend/MCP Python files.
  - `rg` sweep found no remaining references to removed legacy compatibility symbols in active app/sphinx/script/test paths.

## Stage 9 - Docs Updates

- [x] Update Sphinx/Read the Docs content for cleaned terminology/contracts.
- [x] Update internal planning/changelog notes for removed legacy behavior.
- [x] Add a short “what was removed and why” summary for future maintainers.

### Stage 9 summary

- Removed deprecated node-skill compatibility modes/routes and MCP node-skill mutation tools.
- Enforced canonical graph contract: task nodes require `config.task_prompt`; node-level `skill_ids` writes are rejected.
- Removed transitional DB migration/trigger artifacts for deprecated node-skill bindings.
- Removed lingering task-template schema drop hook and obsolete CLI compatibility flag.
- Updated Sphinx docs to remove `node_skill_binding_mode` compatibility language and document canonical Agent-level binding contract:
  - `docs/sphinx/agent_skill_binding.rst`
  - `docs/sphinx/provider_runtime.rst`
