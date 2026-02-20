# List Views

- Rows open the detail view when clicked (use `table-row-link` + `data-href`).
- Ignore clicks on interactive elements (`a`, `button`, `input`, `select`, `textarea`, `label`, `summary`, `details`).
- Actions are icon-only buttons (delete uses trash + confirm).
- Avoid redundant ID or updated columns when the row already links to detail.
- When asked to update templates or pipelines, treat it as a database update unless explicitly requested to update the seed.
- Use `python3` in commands and examples instead of `python`.

# Flash Message Area

- Route user-facing operation notifications (success, error, warning, info) through the shared flash message area.
- In React pages/components, use the shared flash mechanism (`FlashProvider`/`useFlash`) instead of per-page ad-hoc banners for operation outcomes.
- Avoid introducing new one-off notification UI patterns (custom inline save banners, toast systems, or `alert()` calls) for mutation results.
- Keep inline field-level validation near inputs when needed, but send operation-level outcomes to the flash message area.
- When touching existing notification code, migrate non-flash operation messages to the shared flash message area unless there is a documented exception.

# Hard-Cut Runtime Policy

- Do not implement or preserve legacy compatibility paths for runtime/provider behavior unless explicitly requested by the user.
- Do not add fallback execution modes for provider/runtime migrations (for example CLI fallback, legacy image fallback, or silent downgrade behavior).
- For provider/runtime changes, use Python SDK-first execution and fail fast with explicit errors when required SDK/runtime prerequisites are missing.
- When replacing a legacy path, remove the deprecated path and UI affordances in the same change rather than keeping both.

# Planning Workflow

- Store in-progress plans in `docs/planning/active/`.
- Store completed plans in `docs/planning/archive/`.
- Store audit inventory markdown for audits in `docs/planning/audit/`.
- When a plan reaches completion, move it from `docs/planning/active/` to `docs/planning/archive/` immediately without waiting for explicit instruction.
- Plans must be multi-stage and written as task lists with checkboxes (`[ ]` for pending, `[x]` for complete).
- Update plan checkboxes as work is completed; keep status current during execution.
- Plan development is expected to take multiple prompts.
- Stage 0 is always **Requirements Gathering**.
- Stage 0 must include interviewing, asking clarifying questions, and gathering missing requirements before implementation planning.
- Stage 0 interviewing is mandatory and must be run as an interactive interview with the user.
- Ask Stage 0 questions one-by-one (single question per turn), not as a batch list.
- For each Stage 0 question, provide explicit options the user can pick from, while still allowing custom answers.
- Continue Stage 0 interview until requirements are complete and the plan is workable.
- Do not start Stage 1 while Stage 0 is incomplete; continue interviewing until Stage 0 is sound.
- When Stage 0 appears complete, explicitly tell the user planning can start and ask whether to continue interviewing or proceed.
- Stage 1 is always **Code Planning**.
- Stage 2 is always **Audit Plan Creation** and must produce an audit plan against the agreed work scope.
- Stage 2 audit plans must closely follow the existing repository audit-plan format (for example `docs/planning/archive/FLASH_MESSAGE_AREA_NOTIFICATION_AUDIT_PLAN.md` and `docs/planning/active/RUNTIME_MIGRATION_FULL_CLAIM_AUDIT_REMEDIATION_PLAN.md`): clear title/goal metadata, stage-based checkbox tasks, explicit decisions/evidence notes, and concrete file references.
- When the scope is claim-based auditing, Stage 2 must also produce or update:
  - `docs/planning/audit/<WORKSTREAM>_CLAIM_INVENTORY.md`
  - `docs/planning/active/<WORKSTREAM>_CLAIM_EVIDENCE_MATRIX.md`
- Claim-based Stage 2 artifacts should mirror the structure used by `docs/planning/audit/RUNTIME_MIGRATION_CLAIM_INVENTORY.md` and `docs/planning/active/RUNTIME_MIGRATION_CLAIM_EVIDENCE_MATRIX.md`.
- Claim inventory requirements:
  - Include metadata (`Date`, `Status`, source note), source coverage summary, domain summary, and invariant summary.
  - Use stable claim IDs (`<PREFIX>-NNNN`) and do not renumber existing IDs after publication.
  - Keep claims atomic (one verifiable behavior/assertion per claim row).
  - Include source traceability for every claim (`source` path plus line number).
- Claim evidence matrix requirements:
  - Include at least these columns: `claim_id`, `source`, `line`, `domain`, `invariant`, `code_evidence`, `test_evidence`, `ui_api_evidence`, `status`, `severity`, `notes`.
  - Allowed `status` values are only `pass`, `fail`, or `insufficient_evidence`.
  - Any `pass` or `fail` entry must cite concrete file references with line numbers; `TBD` is only valid for `insufficient_evidence`.
  - Any `fail` entry must include a short remediation note that can be translated into an execution-stage task.
- Claim audit closure rules:
  - During **Audit Plan Review**, reconcile Stage 3+ implementation status against the claim evidence matrix, not just checklist completion.
  - During **Audit Remediation Planning**, create explicit correction stages for all `critical` and `high` failed claims before **Automated Testing**.
  - Do not mark the plan complete while unresolved `critical` claim failures remain.
- Stage 3 through Stage X are execution stages for implementation work; create as many as needed to complete the task.
- Before **Automated Testing**, include a required **Audit Plan Review** stage that evaluates implementation progress against the Stage 2 audit plan.
- After **Audit Plan Review**, include a required **Audit Remediation Planning** stage that determines required code actions and creates additional correction stages as needed.
- Execute all correction stages created by **Audit Remediation Planning** before proceeding to **Automated Testing**.
- The final two stages are always:
  - **Automated Testing**
  - **Docs Updates** (including Sphinx and Read the Docs documentation updates)
- Do not include separate **Manual Testing** or **Rollout** stages; manual verification is implied after plan-complete automated work.
- Workflow order:
  - Complete Stage 0 first.
  - Then complete Stage 1 to define planning/execution stages.
  - Complete Stage 2 (**Audit Plan Creation**) against the work scope.
  - Execute Stage 3 through Stage X implementation stages.
  - Before testing, run **Audit Plan Review**.
  - Then run **Audit Remediation Planning** and create/execute any additional correction stages it defines.
  - Always finish with **Automated Testing**, then **Docs Updates**.

# Frontend Visual Testing

- Use the host-installed Codex skill `chromium-screenshot` (from `~/.codex/skills`) for frontend screenshot capture policy, naming conventions, and cleanup workflow.
- For frontend-impacting changes, capture and review at least one screenshot and mention the artifact path in the final update.

# React Component Performance

- When creating React components, design for low render/prop churn and stable updates so the UI stays optimized, responsive, and never feels slow or clunky.
- When identifying repeated UI patterns, prioritize refactoring into reusable shared components instead of duplicating implementations.
- For major layout structures (page shells, panels, section headers, list/detail scaffolding), reuse the same shared layout components to keep behavior and visuals consistent across the app.
- Avoid one-off component designs when an existing shared component can be reused or extended cleanly.
- Prefer reusable CSS classes and shared style patterns over one-off CSS blocks; keep styling DRY and consistent.
- Aim to implement components and styling correctly the first time, emphasizing maintainability, reuse, and predictable UX.

# React + Flask Data Flow

- Frontend-to-backend flow uses HTTP APIs (`GET`, `POST`, `PATCH`, `DELETE`) for reads and mutations; do not treat sockets as the primary command path.
- Backend-to-frontend flow uses socket emits for async updates, job progress, and server-pushed state changes.
- Define and keep stable contracts for each endpoint and socket event (payload shape, required fields, error format).
- Use consistent socket event names in `domain:entity:action` format.
- Design backend mutations and event handling to be idempotent where possible; include dedupe or correlation identifiers for async workflows.
- Centralize API and socket access in shared frontend services/hooks rather than wiring network logic directly in leaf components.
- Propagate correlation/request IDs across HTTP requests, backend processing, and socket events for traceability.
- Use a consistent loading, empty, and error-state UX pattern across screens.

# Flask API Design For React

- Build Flask app routes as API-first JSON interfaces with consistent status code semantics.
- Validate request and response schemas so frontend payload shapes stay predictable.
- Use one standard error response envelope with stable keys (for example: `code`, `message`, `details`, `request_id`).
- Return canonical updated resource state after successful mutations when practical.
- Support list endpoints with pagination, filtering, and sorting; avoid unbounded collection responses.
- Emit socket events only after successful persistence/commit so pushed state is authoritative.
- Include `request_id`/`correlation_id` in logs, API responses, and socket payloads for end-to-end tracing.
- Keep auth, CORS, and CSRF behavior explicit and consistent across endpoints.
- Add/maintain backend contract tests for API responses and socket payload structures used by React.

# ArgoCD GitOps Workflow

- Use the host-installed Codex skill `argocd-commit-push-autosync` (from `~/.codex/skills`) when a task is ready to restart/redeploy/sync in an ArgoCD-monitored repo.
- Enforce order: commit and push current workspace repository changes first, then enable ArgoCD autosync.
- Run `~/.codex/skills/argocd-commit-push-autosync/scripts/commit_push_enable_autosync.sh --app <argocd-app-name>`.
- Default ArgoCD behavior for this workflow is autosync enablement with `--auto-prune --self-heal` (no immediate one-off sync).

# Multi-Agent Git Workspace

- Multiple agents may work in this repository at the same time; unrelated or unexpected file changes can be assumed to come from other active agents.
- Do not treat unrelated git diffs or untracked files as immediate blockers while executing assigned work.
- Do not revert or delete unrelated changes unless explicitly instructed.
- If a workflow requires committing the current workspace state, it is acceptable to include unrelated/unknown files in the commit when necessary.

# Kubernetes Reload Behavior

- If a task changes only UI files (templates, CSS, JS, or other frontend assets), restart the impacted Kubernetes deployment so changes are visible immediately.
- For Studio UI changes, run `kubectl -n llmctl rollout restart deploy/llmctl-studio-frontend` and `kubectl -n llmctl rollout status deploy/llmctl-studio-frontend`.
- If the change touches backend-rendered APIs or Python server code used by the UI, also run `kubectl -n llmctl rollout restart deploy/llmctl-studio-backend` and `kubectl -n llmctl rollout status deploy/llmctl-studio-backend`.
- For Python-only Studio live-code changes, use the `llmctl-studio-live-redeploy` skill workflow to restart the Kubernetes deployment.
- For Python-only RAG changes, restart the corresponding Kubernetes deployment instead of Docker Compose.

# Image Build Command Policy

- When giving image build/push instructions, always provide `scripts/build/harbor.sh` commands first.
- Do not suggest app-level image build scripts (for example under `app/*/build-*.sh`) unless explicitly asked for those scripts.
- Include the exact Harbor-oriented command(s) with explicit flags (such as `--executor`, `--executor-base`, `--tag`, `--registry`) when applicable.
