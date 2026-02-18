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

- [x] Define Stage 2 through Stage X based on Stage 0 decisions.
- [x] Freeze inventory strategy (search terms, code paths, exclusion rules, evidence format).
  - [x] Frontend scans: `set*Error|set*Message|set*Info|set*Warning` plus `useFlash|useFlashState` across `app/llmctl-studio-frontend/src/pages`.
  - [x] Backend scan: `flash(...)` usage across Studio route handlers in `app/llmctl-studio-backend/src/web/views.py`.
  - [x] Evidence format: inventory artifact with compliant/non-compliant classification and explicit file references.
- [x] Freeze remediation strategy (flash API usage standards and migration sequencing).
  - [x] Keep inline field-level validation where useful.
  - [x] Route mutation outcome notifications through `useFlash`/`useFlashState`.
  - [x] Prioritize user-visible offenders first (Quick Notes save-defaults path), then normalize create/edit mutation pages.

## Stage 2 - Notification Inventory Audit

- [x] Enumerate all notification emitters in frontend/backend UI paths.
- [x] Classify each emitter as compliant (flash-area) or non-compliant (ad-hoc).
- [x] Produce a prioritized remediation list with file references.
  - [x] Inventory recorded in `docs/planning/archive/FLASH_MESSAGE_AREA_NOTIFICATION_AUDIT_INVENTORY.md`.

## Stage 3 - Flash Message Migration

- [x] Migrate non-compliant notification paths to the shared flash message area.
- [x] Preserve field-level inline validation where appropriate while moving operation-level outcomes to flash.
- [x] Remove or consolidate redundant ad-hoc notification UI.
  - [x] Remediated pages:
    - [x] `app/llmctl-studio-frontend/src/pages/QuickTaskPage.jsx`
    - [x] `app/llmctl-studio-frontend/src/pages/AgentNewPage.jsx`
    - [x] `app/llmctl-studio-frontend/src/pages/NodeNewPage.jsx`
    - [x] `app/llmctl-studio-frontend/src/pages/PlanEditPage.jsx`
    - [x] `app/llmctl-studio-frontend/src/pages/MemoryEditPage.jsx`
    - [x] `app/llmctl-studio-frontend/src/pages/MilestoneEditPage.jsx`
    - [x] `app/llmctl-studio-frontend/src/pages/RagSourceNewPage.jsx`
    - [x] `app/llmctl-studio-frontend/src/pages/RagSourceEditPage.jsx`
    - [x] `app/llmctl-studio-frontend/src/pages/RoleNewPage.jsx`
    - [x] `app/llmctl-studio-frontend/src/pages/RoleEditPage.jsx`
    - [x] `app/llmctl-studio-frontend/src/pages/AgentEditPage.jsx`
    - [x] `app/llmctl-studio-frontend/src/pages/ChatPage.jsx`

## Stage 4 - Enforcement Guardrails

- [x] Add lightweight checks/docs patterns that discourage new non-flash notification paths.
  - [x] Added guardrail script: `scripts/checks/flash_notification_guardrail.py`.
  - [x] Added frontend command: `npm run check:flash-notifications`.
- [x] Add/adjust tests around flash usage for critical notification flows.
  - [x] Guardrail command documented in `app/llmctl-studio-frontend/README.md`.

## Stage 5 - Automated Testing

- [x] Run automated tests/checks relevant to touched frontend/backend notification code.
- [x] Record pass/fail outcomes and any follow-up required.
  - [x] `python3 scripts/checks/flash_notification_guardrail.py` -> passed.
  - [x] `npm --prefix app/llmctl-studio-frontend run check:flash-notifications` -> passed.
  - [x] `npm --prefix app/llmctl-studio-frontend run test` -> passed (`10` files, `81` tests).
  - [x] `npm --prefix app/llmctl-studio-frontend run lint` -> failed due pre-existing `FlowchartWorkspaceEditor.jsx` memoization lint errors; one remaining non-blocking warning in `QuickTaskPage.jsx`.

## Stage 6 - Docs Updates

- [x] Update Sphinx/Read the Docs docs for notification UX and engineering conventions if needed.
  - [x] Updated `app/llmctl-studio-frontend/README.md` with the flash-notification guardrail command.
- [x] If no docs updates are required, record an explicit no-op decision.
  - [x] No Sphinx/Read the Docs content updates required for this frontend notification policy pass.
