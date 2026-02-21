# Frontend React Component File Split Structural Refactor Plan

Goal: Perform a structural-only refactor of all React frontend code in this repository by splitting monolithic files along component boundaries, improving organization, and reducing very large multi-thousand-line files without changing behavior.

## Stage 0 - Requirements Gathering

- [x] Capture requested outcome from user.
- [x] Confirm frontend scope boundary.
  - [x] Scope selected: all React frontend code in this repository.
- [x] Confirm strictness for component extraction policy.
  - [x] Policy selected: pragmatic split (extract sizable/reused components; tiny local helpers may remain inline).
- [x] Confirm primary splitting target for decomposition.
  - [x] Target selected: component-first splitting regardless of line count.
- [x] Confirm destination organization model.
  - [x] Organization selected: type-first central component directories, with feature-level subdivision as needed inside those directories.
- [x] Confirm rollout strategy.
  - [x] Strategy selected: single coordinated pass.
- [x] Confirm structural-only change policy for refactor execution.
  - [x] Policy selected: structural + hygiene (allow tiny safe cleanups such as unused imports, dead local variables, and obvious naming cleanup while preserving behavior).
- [x] Confirm import/export policy for post-split component wiring.
  - [x] Policy selected: direct file imports everywhere; update call sites to concrete component files and minimize barrel usage.
- [x] Confirm placement policy for single-component hooks/utilities.
  - [x] Policy selected: centralize by type (hooks in shared hooks directories and utilities in shared utilities directories).
- [x] Confirm refactor scope exclusions.
  - [x] Exclusions selected: include only source React component code; exclude generated files, build artifacts, and external/vendor code.
- [ ] Confirm Stage 0 completion and ask whether to proceed to Stage 1.

## Stage 0 - Interview Notes (Captured)

- [x] User wants a frontend refactor similar to the backend structural refactor style.
- [x] User goal is to avoid massive multi-thousand-line files where possible.
- [x] Scope is all React frontend code in this repository.
- [x] Strictness is pragmatic, not strict-per-component for tiny private helpers.
- [x] Splitting principle is component-first.
- [x] Organization preference is type-first with feature-based subdivision where needed.
- [x] Rollout preference is a single coordinated pass.
- [x] Structural policy is structural + hygiene (safe local cleanups allowed; no intended behavior changes).
- [x] Import policy is direct concrete file imports with minimal barrel usage.
- [x] One-component hooks/utilities should be centralized by type instead of colocated.
- [x] Scope excludes generated/build/vendor code and targets source React components only.
- [x] Process preference (meta): create and update planning doc continuously during Stage 0 interview turns.

## Stage 1 - Code Planning

- [ ] Inventory all React files and component declarations in scope.
- [ ] Define canonical extraction and naming conventions (component files, index/export files, colocated styles/tests/hooks).
- [ ] Define dependency-safe extraction order to minimize merge risk.
- [ ] Define Stage 2 through Stage X execution sequence from Stage 0 decisions.
- [ ] Freeze final two stages:
  - [ ] Automated Testing
  - [ ] Docs Updates

## Stage 2 - Scope-Specific Planning

- [ ] Build concrete target directory map for type-first component organization with feature subdivisions where needed.
- [ ] Map current oversized files to extraction units and destination files.
- [ ] Define shared component promotion rules to avoid duplication.
- [ ] Define acceptance criteria for structural parity and unchanged behavior.

## Stage 3 - Execution Wave 1 (Inventory And Baseline)

- [ ] Capture baseline React file-size/component inventory.
- [ ] Record current lint/type/test baseline for touched frontend areas.
- [ ] Identify first extraction tranche based on component boundaries and import risk.

## Stage 4 - Execution Wave 2 (Component Extractions)

- [ ] Extract components into dedicated files according to Stage 2 map.
- [ ] Rewire imports/exports and preserve behavior.
- [ ] Keep shared layout/pattern reuse aligned with existing frontend standards.
- [ ] Update this plan with progress evidence and tranche completion notes.

## Stage 5 - Automated Testing

- [ ] Run targeted frontend test/lint/type validation for refactored areas.
- [ ] Capture and review at least one frontend verification screenshot artifact.
- [ ] Record command evidence and results in this plan.

## Stage 6 - Docs Updates

- [ ] Update relevant documentation (including Sphinx/Read the Docs references if impacted).
- [ ] Update planning artifact with final execution notes and evidence.
- [ ] Move completed plan from `docs/planning/active/` to `docs/planning/archive/`.
