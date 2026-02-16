# Provider Settings Section Split Plan

Goal: mirror Integrations-style section navigation for Providers by splitting provider auth into per-provider pages while preserving a dedicated provider control page for enable/disable/default settings and giving it a clearer nav label.

## Stage 0 - Requirements Gathering
- [x] Interview request intent from stakeholder message.
- [x] Clarify section model required:
  - [x] Keep one provider control page for enabled/disabled/default.
  - [x] Add provider-specific auth pages selected from top-right settings actions.
- [x] Capture naming requirement:
  - [x] Rename nav label for provider control surface to a clearer name.
- [x] Identify constraints/assumptions:
  - [x] Preserve existing provider POST handlers and payload keys.
  - [x] Keep current Integrations behavior unchanged.

## Stage 1 - Code Planning
- [x] Define Stage 2 through Stage 6 implementation tasks.
- [x] Stage 2 scope: add provider section metadata and section-specific settings routes/context.
- [x] Stage 3 scope: refactor provider settings template to Integrations-style topbar section nav and sectioned forms.
- [x] Stage 4 scope: update sidebar/mobile settings nav label for provider controls.
- [x] Stage 5 scope: run automated testing targeted to affected web routes/templates.
- [x] Stage 6 scope: update docs/planning status and archive this plan at completion.

## Stage 2 - Provider Section Routing + Context
- [x] Add provider section registry and renderer in `views.py`.
- [x] Add provider route split (`/settings/provider/<section>`) with controls alias route.
- [x] Ensure each POST route redirects back to its owning provider section.

## Stage 3 - Provider Template Section Split
- [x] Add `topbar_actions` section selector for Providers.
- [x] Split current single provider template into conditional sections:
  - [x] provider controls page (enable/disable/default)
  - [x] codex auth page
  - [x] gemini auth page
  - [x] claude auth page
  - [x] vllm local page
  - [x] vllm remote page
- [x] Keep existing JS behavior for provider-control toggles.

## Stage 4 - Navigation Label Updates
- [x] Rename settings nav label from `Provider` to `Provider Controls`.
- [x] Ensure active-page highlighting still works for all provider sections.

## Stage 5 - Automated Testing
- [x] Run relevant automated tests (or targeted checks) for settings routes/templates.
- [x] Capture frontend screenshot artifact using `chromium-screenshot` skill workflow.

## Stage 6 - Docs Updates
- [x] Update this plan file with final completion status and outcomes.
- [x] Move completed plan to `docs/planning/archive/`.
- [x] Confirm no additional Sphinx/RTD content changes were required for this UI-only update.

## Completion Notes (2026-02-16)
- Implemented sectioned provider settings pages with top-right section actions:
  - `controls`, `codex`, `gemini`, `claude`, `vllm_local`, `vllm_remote`
- Kept provider controls as a dedicated page for enabled/disabled/default settings.
- Updated provider auth/settings POST routes to return users to their respective section pages.
- Updated settings navigation label to `Provider Controls`.
- Automated test run:
  - `.venv/bin/python3 -m pytest app/llmctl-studio/tests/test_skills_stage5.py -q` -> `2 passed`
- Frontend screenshot artifacts reviewed:
  - `docs/screenshots/2026-02-16-11-41-08--settings-provider--controls-page--1920x1080--c082228--34d07a.png`
  - `docs/screenshots/2026-02-16-11-41-21--settings-provider--codex-auth-page--1920x1080--c082228--81723c.png`
- Sphinx/Read the Docs updates:
  - No documentation content changes required for this UI-only navigation restructure.
