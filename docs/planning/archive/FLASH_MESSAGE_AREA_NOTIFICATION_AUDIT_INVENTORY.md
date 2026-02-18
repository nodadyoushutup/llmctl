# Flash Message Area Notification Inventory

## Audit Scope

- Studio full surface (React pages + backend Studio routes)

## Inventory Method

- Frontend scan for local notification-like setter patterns (`set*Error`, `set*Message`, `set*Info`, `set*Warning`).
- Frontend scan for flash usage (`useFlash`, `useFlashState`).
- Backend scan for server-side flash emission (`flash(...)`) in Studio routes.

## Classification

### Compliant

- Backend Studio route mutations in `app/llmctl-studio-backend/src/web/views.py` already emit notifications through Flask `flash(...)`.
- Frontend pages with notification-like local setters are now all wired to flash hooks (`useFlash`/`useFlashState`).
  - Verified by `python3 scripts/checks/flash_notification_guardrail.py`.

### Previously Non-Compliant (Remediated)

- `app/llmctl-studio-frontend/src/pages/QuickTaskPage.jsx`
- `app/llmctl-studio-frontend/src/pages/AgentNewPage.jsx`
- `app/llmctl-studio-frontend/src/pages/NodeNewPage.jsx`
- `app/llmctl-studio-frontend/src/pages/PlanEditPage.jsx`
- `app/llmctl-studio-frontend/src/pages/MemoryEditPage.jsx`
- `app/llmctl-studio-frontend/src/pages/MilestoneEditPage.jsx`
- `app/llmctl-studio-frontend/src/pages/RagSourceNewPage.jsx`
- `app/llmctl-studio-frontend/src/pages/RagSourceEditPage.jsx`
- `app/llmctl-studio-frontend/src/pages/RoleNewPage.jsx`
- `app/llmctl-studio-frontend/src/pages/RoleEditPage.jsx`
- `app/llmctl-studio-frontend/src/pages/AgentEditPage.jsx`
- `app/llmctl-studio-frontend/src/pages/ChatPage.jsx`

## Notes

- Inline field-level validation is intentionally retained where appropriate (for example required input checks before submission).
- Operation-level mutation outcomes now route through flash message hooks in remediated pages.
