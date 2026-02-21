# Studio Backend Structural Refactor Plan

Goal: Perform a structural-only refactor of `app/llmctl-studio-backend/src` by splitting oversized modules into smaller packages/files, preserving behavior, and removing confirmed vestigial CLI-era backend paths that are no longer load-bearing.

## Stage 0 - Requirements Gathering

- [x] Capture requested outcome from user report.
- [x] Confirm exact Stage 0 scope boundaries for this first workstream (`llmctl-studio-backend` only vs cross-repo prep).
  - [x] Scope selected: `llmctl-studio-backend` only.
- [x] Confirm hard definition of "structural-only" change policy (allowed vs disallowed edits).
  - [x] Policy selected: strict move-only (move/split files + import rewiring only; no behavior/signature changes).
- [x] Confirm target decomposition standard (class-per-file defaults, utility grouping rules, package layout conventions).
  - [x] Standard selected: class-per-file by default; tiny tightly related classes may share one file.
  - [x] Utility convention selected: domain-focused utility modules per package (`parsing.py`, `validation.py`, `serialization.py`).
- [x] Confirm vestigial CLI removal policy (prove-not-used threshold + deletion strategy).
  - [x] Removal threshold selected: require explicit proof of no runtime references (`rg`, import/call-path verification, and green tests) before deletion.
- [x] Confirm rollout strategy (single large PR vs staged waves by domain/package).
  - [x] Rollout selected: staged waves by backend domain/package with checkpoints each wave.
- [x] Confirm concrete file-size targets for extracted modules/packages.
  - [x] No numeric line-count caps; decompose by logical ownership and cohesion.
  - [x] Allow large files when they contain a single coherent class/module; split when multiple classes/domains are mixed.
- [x] Confirm import-compatibility policy during staged extraction waves.
  - [x] Policy selected: no compatibility shims; update all imports in-wave and fail fast on misses.
- [ ] Confirm Stage 0 completion with user and ask whether to proceed to Stage 1.

## Stage 1 - Code Planning

- [ ] Define Stage 2 through Stage X based on Stage 0 decisions.
- [ ] Define module inventory strategy for oversized files and dependency mapping.
- [ ] Define import-migration sequencing that minimizes merge risk and behavior drift.
- [ ] Define lightweight audit checkpoints embedded in each execution stage.
- [ ] Freeze final two stages:
  - [ ] Automated Testing
  - [ ] Docs Updates

## Stage 2 - Scope-Specific Planning

- [ ] Build the backend structural decomposition map by package/domain.
- [ ] Define per-domain extraction units (classes, helpers, constants, serializers, route handlers).
- [ ] Define acceptance criteria for each extraction unit (no logic changes, import parity, test parity).
- [ ] Define CLI vestigiality verification checklist for candidate removals.

## Stage 3 - Execution Wave 1 (Inventory And Baseline)

- [ ] Produce file-size and symbol inventory for oversized backend modules.
- [ ] Capture baseline automated test targets for touched domains.
- [ ] Record extraction order and owner notes in this plan.
- [ ] Perform audit checkpoint: verify baseline is reproducible and evidence-backed.

## Stage 4 - Execution Wave 2 (Core Module Extractions)

- [ ] Extract first domain set into new packages/files.
- [ ] Keep import surfaces stable or provide minimal compatibility shims only if required within this wave.
- [ ] Run targeted verification after each extraction batch.
- [ ] Perform audit checkpoint: verify moved symbols and imports are behavior-equivalent.

## Stage 5 - Execution Wave 3 (Route/Service Extractions)

- [ ] Extract additional oversized route/service modules into structured subpackages.
- [ ] Normalize loose helper functions into focused utility modules.
- [ ] Remove temporary extraction scaffolding that is no longer needed.
- [ ] Perform audit checkpoint: verify API behavior and event contracts remain unchanged.

## Stage 6 - Execution Wave 4 (Vestigial CLI Path Removal)

- [ ] Identify and prove vestigial CLI-era backend paths using code references and runtime call paths.
- [ ] Remove only paths confirmed non-load-bearing for SDK-first runtime.
- [ ] Remove/adjust related UI or configuration affordances if present in backend scope.
- [ ] Perform audit checkpoint: verify no remaining backend dependencies on removed vestigial paths.

## Stage 7 - Automated Testing

- [ ] Run backend automated tests relevant to refactored modules.
- [ ] Run static checks for touched backend Python files.
- [ ] Record pass/fail and remediation notes.

## Stage 8 - Docs Updates

- [ ] Update Sphinx/Read the Docs docs for backend module layout and any removed CLI vestiges.
- [ ] Update internal planning notes with final package map and extraction summary.
- [ ] If no docs updates are needed for a touched area, record explicit no-op decision.
