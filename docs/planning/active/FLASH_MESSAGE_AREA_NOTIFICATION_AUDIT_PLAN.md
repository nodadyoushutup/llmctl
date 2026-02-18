# Flash Message Area Notification Audit Plan

Goal: Ensure all user-facing operation notifications are emitted through the shared flash message area and eliminate ad-hoc notification paths.

## Stage 0 - Requirements Gathering

- [x] Capture requested outcome from user report.
- [x] Add/update agent guidance so future changes default to flash-area notifications.
- [x] Confirm audit scope boundaries with user (frontend pages only vs frontend + backend-rendered templates).
  - [x] Scope selected: Studio full surface (React + backend-rendered Studio routes/templates).
- [x] Confirm whether this effort is audit-and-plan only or includes immediate code remediation.
  - [x] Execution mode selected: audit plus immediate remediation.
- [x] Confirm whether we should add enforcement guardrails (lint/check/test) as part of this work.
  - [x] Guardrail mode selected: add guardrails now.
- [x] Confirm Stage 0 completion with user and ask whether to proceed to Stage 1.

## Stage 1 - Code Planning

- [ ] Define Stage 2 through Stage X based on Stage 0 decisions.
- [ ] Freeze inventory strategy (search terms, code paths, exclusion rules, evidence format).
- [ ] Freeze remediation strategy (flash API usage standards and migration sequencing).

## Stage 2 - Notification Inventory Audit

- [ ] Enumerate all notification emitters in frontend/backend UI paths.
- [ ] Classify each emitter as compliant (flash-area) or non-compliant (ad-hoc).
- [ ] Produce a prioritized remediation list with file references.

## Stage 3 - Flash Message Migration

- [ ] Migrate non-compliant notification paths to the shared flash message area.
- [ ] Preserve field-level inline validation where appropriate while moving operation-level outcomes to flash.
- [ ] Remove or consolidate redundant ad-hoc notification UI.

## Stage 4 - Enforcement Guardrails

- [ ] Add lightweight checks/docs patterns that discourage new non-flash notification paths.
- [ ] Add/adjust tests around flash usage for critical notification flows.

## Stage 5 - Automated Testing

- [ ] Run automated tests/checks relevant to touched frontend/backend notification code.
- [ ] Record pass/fail outcomes and any follow-up required.

## Stage 6 - Docs Updates

- [ ] Update Sphinx/Read the Docs docs for notification UX and engineering conventions if needed.
- [ ] If no docs updates are required, record an explicit no-op decision.
