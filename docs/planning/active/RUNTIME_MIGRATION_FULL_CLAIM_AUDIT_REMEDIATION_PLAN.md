# Runtime Migration Full Claim Audit + Remediation Plan

Date: 2026-02-20
Status: In Progress
Owner: Codex + User

## Stage 0 - Requirements Gathering

- [x] Confirm audit breadth.
- [x] Confirm execution mode after audit findings.
- [x] Confirm closure strictness.
- [x] Confirm Stage 0 completion and get approval to proceed to Stage 1.

Stage 0 decisions:

- Scope: Full migration claim audit.
- Mode: Audit plus immediate critical fixes.
- Gate: Hard gate. No completion without code evidence and passing automated tests.

## Stage 1 - Code Planning

- [x] Define the evidence model for each checked migration-plan claim (`claim -> code -> tests -> UI/API proof`).
- [x] Define execution stages for claim extraction, evidence mapping, remediation, gating, and closure.
- [x] Sequence work so critical gaps are fixed immediately after discovery.
- [x] Ensure final stages are `Automated Testing` then `Docs Updates`.

## Stage 2 - Claim Inventory + Normalization

- [ ] Enumerate every checked claim across active runtime migration planning docs.
- [ ] Normalize claims into a canonical inventory with stable IDs and source references.
- [ ] Classify claims by domain (`backend`, `api`, `frontend`, `contracts`, `ops`, `testing`, `docs`).
- [ ] Mark claims that define invariants (must-have behaviors) versus informational claims.

## Stage 3 - Evidence Matrix Construction

- [ ] Build a claim evidence matrix under `docs/planning/active/` linking each claim ID to:
- [ ] Code paths that implement the claim.
- [ ] Automated tests that prove the claim.
- [ ] API/UI/runtime evidence for user-visible behavior when applicable.
- [ ] Mark each claim as `pass`, `fail`, or `insufficient evidence`.

## Stage 4 - Critical Gap Triage + Immediate Fix Queue

- [ ] Rank all failed claims by severity (`critical`, `high`, `medium`, `low`).
- [ ] Define immediate fix queue for `critical` items, starting with artifact invariant drift.
- [ ] Convert each critical claim into concrete acceptance tests before implementation.
- [ ] Lock a remediation order that preserves runtime safety and deterministic behavior.

## Stage 5 - Critical Backend Remediation

- [ ] Implement backend fixes for critical failed claims.
- [ ] For artifact invariants, add missing node artifact types/persistence paths for required node classes.
- [ ] Ensure contract/version/idempotency metadata is persisted consistently for new artifact writes.
- [ ] Preserve backward compatibility or add explicit migration behavior where needed.

## Stage 6 - API + Frontend Remediation

- [ ] Implement/extend API endpoints needed to expose corrected runtime state.
- [ ] Implement frontend surfaces for corrected artifact visibility and navigation parity.
- [ ] Ensure list/detail row-link and action behaviors remain compliant with AGENTS instructions.
- [ ] Route operation-level outcomes through shared flash messages where mutations are added or changed.

## Stage 7 - Hard-Gate Guardrail Implementation

- [ ] Add automated guardrails that prevent checked plan claims without supporting tests.
- [ ] Add claim-to-test linkage checks (or equivalent machine-checkable mapping).
- [ ] Add CI failure conditions for unresolved critical/high failed claims.
- [ ] Ensure guardrails are documented and executable by contributors.

## Stage 8 - Remaining Claim Remediation (High/Medium/Low)

- [ ] Fix remaining non-critical failed claims in priority order.
- [ ] Add or update tests for each remediated claim.
- [ ] Re-run evidence matrix and update claim status as fixes land.
- [ ] Leave no checked claim in `fail` or `insufficient evidence`.

## Stage 9 - Automated Testing

- [ ] Run full backend test coverage for runtime contracts, artifacts, routing, and APIs.
- [ ] Run frontend tests for artifact and navigation behaviors affected by remediations.
- [ ] Run targeted end-to-end regression for representative workflows across node types.
- [ ] Record command evidence and results in the active planning artifact.

## Stage 10 - Docs Updates

- [ ] Update runtime migration plan docs to reflect corrected implementation truth.
- [ ] Update Sphinx/Read the Docs content for artifact invariants and operator expectations.
- [ ] Publish the final claim evidence matrix with pass/fail closure evidence.
- [ ] Move this plan to `docs/planning/archive/` once all stages are complete.

