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

- [ ] Build a structured findings register with IDs and evidence.
- [ ] Audit categories:
  - [ ] Legacy feature shims/fallbacks still active
  - [ ] Vestigial dead paths (unreachable routes, unused utilities/components)
  - [ ] Terminology mismatches (same concept named differently across FE/BE/MCP)
  - [ ] API/schema contract mismatches
  - [ ] Transitional DB artifacts no longer needed
  - [ ] Test fixtures/coverage still asserting old behavior
- [ ] For each finding, capture:
  - [ ] `finding_id`
  - [ ] location (`file:line`)
  - [ ] category
  - [ ] current behavior
  - [ ] why it is legacy/vestigial/mismatched
  - [ ] risk if left unchanged
  - [ ] recommended fix
  - [ ] estimated cleanup scope (S/M/L)

## Stage 3 - Findings Review, Prioritization, And Cleanup Gate

- [ ] Review findings list with stakeholder.
- [ ] Group findings into cleanup waves (high-risk first).
- [ ] Mark each finding status:
  - [ ] approved for cleanup now
  - [ ] deferred
  - [ ] rejected (keep as-is)
- [ ] Freeze Section A output before Section B starts.

### Findings Register (to populate in Stage 2/3)

| finding_id | category | location | summary | risk | recommendation | status |
| --- | --- | --- | --- | --- | --- | --- |
| F-001 | _tbd_ | _tbd_ | _tbd_ | _tbd_ | _tbd_ | _pending_ |

---

## Section B - Cleanup / Execution

## Stage 4 - Cleanup Wave 1 (Terminology And Contract Alignment)

- [ ] Normalize terminology across FE/BE/MCP for approved findings.
- [ ] Align payload keys/labels/errors/docs where names mismatch.
- [ ] Add compatibility notes only where strictly required.

## Stage 5 - Cleanup Wave 2 (Vestigial / Unused Code Removal)

- [ ] Remove approved dead code, stale routes, unused helpers, and obsolete bindings.
- [ ] Remove obsolete frontend surfaces and stale backend handlers.
- [ ] Remove MCP tools/branches that only support removed legacy concepts.

## Stage 6 - Cleanup Wave 3 (Schema And Migration Hardening)

- [ ] Remove approved legacy schema artifacts and transitional migration paths.
- [ ] Ensure destructive changes are migration-safe and reversible where practical.
- [ ] Validate runtime no longer depends on removed columns/tables/views.

## Stage 7 - Cleanup Wave 4 (Tests And Fixtures Alignment)

- [ ] Update tests to reflect canonical behavior only.
- [ ] Remove tests that assert deprecated/removed flows.
- [ ] Add regression tests for newly cleaned contracts/terminology.

## Stage 8 - Automated Testing

- [ ] Run targeted frontend tests for touched areas.
- [ ] Run backend and MCP automated tests for touched areas.
- [ ] Run lint/type/static checks used by the repo for touched areas.
- [ ] Record failures, fixes, and final pass status.

## Stage 9 - Docs Updates

- [ ] Update Sphinx/Read the Docs content for cleaned terminology/contracts.
- [ ] Update internal planning/changelog notes for removed legacy behavior.
- [ ] Add a short “what was removed and why” summary for future maintainers.

