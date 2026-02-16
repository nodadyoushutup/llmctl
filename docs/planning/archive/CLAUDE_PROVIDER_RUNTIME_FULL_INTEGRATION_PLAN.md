# Claude Provider Runtime Full Integration Plan

Goal: fully operationalize Claude as a first-class provider in Studio, including runtime CLI availability, provider readiness checks, Claude model creation flows, and native runtime artifacts (`CLAUDE.md` + Claude skill materialization).

## Stage 0 - Requirements Gathering
- [x] Capture stakeholder objective from request:
  - [x] Claude must be usable as a runtime provider now.
  - [x] Claude CLI must be installable/available at runtime.
  - [x] Claude-backed models must be creatable and runnable.
  - [x] Runtime must materialize Claude-native instruction/skill artifacts.
- [x] Audit current implementation surface and identify existing Claude support.
- [x] Identify major gaps to close:
  - [x] No runtime bootstrap path currently guarantees `claude` CLI availability.
  - [x] No explicit provider-health/install diagnostics for Claude in settings.
  - [x] Claude install scripts exist but are not wired into startup/runtime workflow.
- [x] Interview and lock runtime install policy:
  - [x] Install timing: lazy check on first Claude execution (with optional auto-install).
  - [x] Failure policy: fail-fast by default, warning-only if explicitly disabled.
  - [x] Version policy: track latest in container build/install path.
  - [x] Network policy: install failure is surfaced clearly; fail/continue follows policy flag.
- [x] Interview and lock authentication policy for runtime:
  - [x] API key policy default: required (`CLAUDE_AUTH_REQUIRE_API_KEY=true`).
  - [x] Secret precedence: DB (`claude_api_key`) first, then `ANTHROPIC_API_KEY`.
- [x] Interview and lock model catalog/default policy:
  - [x] Curated Claude model defaults are surfaced in UI/model options.
  - [x] Freeform model IDs remain allowed for Claude.
- [x] Confirm deployment scope:
  - [x] Docker runtime image includes Claude CLI install path.
  - [x] Workspace/host path remains supported through runtime CLI checks and env policy flags.

## Stage 1 - Code Planning
- [x] Finalize Stage 2 through Stage 8 after Stage 0 decisions are locked.
- [x] Confirm touched modules and ownership boundaries:
  - [x] runtime/bootstrap scripts and task execution checks
  - [x] Docker image/build startup path
  - [x] provider settings/backend readiness surface
  - [x] model creation/edit defaults for Claude
  - [x] runtime execution/instruction-skill materialization verification
- [x] Define concrete acceptance criteria for each execution stage.

## Stage 2 - Runtime Claude CLI Bootstrap
- [x] Wire Claude install/check into runtime bootstrap path so `claude` is present when task execution starts.
- [x] Add deterministic command-path/version detection (`claude --version`) with clear logs.
- [x] Add configurable behavior flags for install/check policy.
- [x] Ensure bootstrap logic is idempotent and safe to run repeatedly.

## Stage 3 - Container and Deployment Wiring
- [x] Update Studio container/runtime startup wiring so Claude CLI availability survives rebuild/restart workflows.
- [x] Ensure docker-compose/dev path exposes required env for Claude runtime execution.
- [x] Validate runtime user/path permissions for Claude binary and config directories.

## Stage 4 - Provider Readiness and Settings UX
- [x] Add Claude provider diagnostics in settings context (installed/version/auth readiness).
- [x] Surface actionable status and failure messages in provider UI.
- [x] Keep provider updates as DB-backed integration setting writes (no seed coupling).

## Stage 5 - Claude Model Provider Flow Hardening
- [x] Verify/create Claude model create/edit/view behavior with consistent defaults.
- [x] Add/lock Claude default model option strategy (curated + custom entry policy).
- [x] Ensure default-provider/default-model resolution behaves correctly when Claude is selected.

## Stage 6 - Runtime Native Artifacts (`CLAUDE.md` + Skills)
- [x] Verify and harden Claude native instruction adapter path so `CLAUDE.md` is materialized for each run.
- [x] Verify and harden Claude skill adapter path (`$HOME/.claude/skills`) in runtime home isolation.
- [x] Ensure fallback behavior remains correct when native materialization is disabled/fails.
- [x] Confirm runtime observability persists instruction/skill adapter mode and materialized paths.

## Stage 7 - Automated Testing
- [x] Add/extend tests for Claude bootstrap/install readiness behavior.
- [x] Add/extend tests for provider settings diagnostics and Claude model create/edit flow.
- [x] Add/extend tests for runtime `CLAUDE.md` + Claude skills materialization behavior.
- [x] Run targeted automated test suites for touched modules.

## Stage 8 - Docs Updates
- [x] Update docs for Claude provider setup/runtime requirements and failure modes.
- [x] Update Sphinx/Read the Docs documentation for Claude runtime/provider configuration.
- [x] Update this plan with completion notes and final verification commands.
- [x] Move completed plan from `docs/planning/active/` to `docs/planning/archive/`.

## Stage 0 Interview Queue
- [x] Should Claude CLI installation happen automatically at Studio startup, or only when a Claude task is first executed?
  - [x] Decision: lazy on first Claude execution; optional auto-install.
- [x] Do you want strict version pinning for Claude CLI, or always track latest available release?
  - [x] Decision: track latest by default.
- [x] If Claude install/check fails at runtime, should task execution hard-fail immediately or degrade with a clear warning?
  - [x] Decision: hard-fail by default; configurable warning-only fallback.
- [x] Should Claude model names be freeform, or constrained to a curated allowlist by default?
  - [x] Decision: curated suggestions + freeform allowed.

## Completion Notes
- Added Claude runtime bootstrap/readiness/auth policy in `app/llmctl-studio/src/services/tasks.py`.
- Added Claude runtime policy flags in `app/llmctl-studio/src/core/config.py`.
- Added Claude readiness diagnostics in provider settings UI:
  - `app/llmctl-studio/src/web/views.py`
  - `app/llmctl-studio/src/web/templates/settings_provider.html`
- Added curated Claude model defaults while preserving freeform entry:
  - `app/llmctl-studio/src/web/views.py`
  - `app/llmctl-studio/src/web/templates/model_new.html`
  - `app/llmctl-studio/src/web/templates/model_edit.html`
- Added container/deploy wiring for Claude install and runtime policy env:
  - `app/llmctl-studio/docker/Dockerfile`
  - `docker/docker-compose.yml`
- Added Claude-focused automated tests in:
  - `app/llmctl-studio/tests/test_claude_provider_stage8.py`
- Added Sphinx docs:
  - `docs/sphinx/provider_runtime.rst`
  - `docs/sphinx/index.rst`
  - `docs/sphinx/changelog.rst`

## Verification Commands
- `python3 -m py_compile app/llmctl-studio/src/core/config.py app/llmctl-studio/src/services/tasks.py app/llmctl-studio/src/web/views.py app/llmctl-studio/tests/test_claude_provider_stage8.py`
- `docker exec llmctl-studio bash -lc "PYTHONPATH=/app/app/llmctl-studio/src python3 - <<'PY' ... PY"` (Claude runtime smoke assertions)
- `docker restart llmctl-studio`
- `codex-skills/chromium-screenshot/scripts/capture_screenshot.sh --url http://localhost:5055/settings/provider/claude --route settings-provider --state claude-runtime-diagnostics --viewport 1920x1080 --out-dir docs/screenshots --root /home/nodadyoushutup/llmctl`

## Frontend Artifact
- `docs/screenshots/2026-02-16-12-15-22--settings-provider--claude-runtime-diagnostics--1920x1080--c082228--cab27c.png`
