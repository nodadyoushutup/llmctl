# List Views

- Rows open the detail view when clicked (use `table-row-link` + `data-href`).
- Ignore clicks on interactive elements (`a`, `button`, `input`, `select`, `textarea`, `label`, `summary`, `details`).
- Actions are icon-only buttons (delete uses trash + confirm).
- Avoid redundant ID or updated columns when the row already links to detail.
- When asked to update templates or pipelines, treat it as a database update unless explicitly requested to update the seed.
- Use `python3` in commands and examples instead of `python`.

# Planning Workflow

- Store in-progress plans in `docs/planning/active/`.
- Store completed plans in `docs/planning/archive/`.
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
- Stage 1 defines and creates Stage 2 through Stage X based on the required code changes.
- Stage 2 through Stage X are execution stages for implementation work; create as many as needed to complete the task.
- The final two stages are always:
  - **Automated Testing**
  - **Docs Updates** (including Sphinx and Read the Docs documentation updates)
- Do not include separate **Manual Testing** or **Rollout** stages; manual verification is implied after plan-complete automated work.
- Workflow order:
  - Complete Stage 0 first.
  - Then complete Stage 1 to produce Stage 2-X.
  - Then execute Stage 2-X.
  - Always finish with Automated Testing, then Docs Updates.

# Frontend Visual Testing

- Use the host-installed Codex skill `chromium-screenshot` (from `~/.codex/skills`) for frontend screenshot capture policy, naming conventions, and cleanup workflow.
- For frontend-impacting changes, capture and review at least one screenshot and mention the artifact path in the final update.

# Docker Reload Behavior

- If a task changes only UI files (templates, CSS, JS, or other frontend assets), restart the impacted web container so changes are visible immediately.
- For Studio UI changes, run `docker compose -f docker/docker-compose.yml restart llmctl-studio`.
- If a task changes only Python files, run the impacted Flask service in debug mode so it auto-reloads on save.
- For Python-only Studio changes, run `FLASK_DEBUG=true docker compose -f docker/docker-compose.yml up -d --force-recreate --no-deps llmctl-studio`.
- For Python-only RAG changes, run `FLASK_DEBUG=true docker compose -f docker/docker-compose.yml up -d --force-recreate --no-deps llmctl-rag`.
