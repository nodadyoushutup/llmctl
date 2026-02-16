# Provider Settings Action Bar Plan

Goal: Add a consistent action bar below the top nav on all provider settings pages and move provider page action buttons into that shared bar.

## Stage 0 - Requirements Gathering

- [x] Confirm scope from request:
  - [x] Apply to provider settings pages (`controls`, `codex`, `gemini`, `claude`, `vllm_local`, `vllm_remote`).
  - [x] Add action bar below nav (use base `action_header` block).
  - [x] Move save actions from in-form button rows into this bar.
- [x] Clarify interaction model and constraints:
  - [x] Keep provider section nav in `topbar_actions`.
  - [x] Keep form submission behavior unchanged (POST routes and field names).
  - [x] Ensure only the active provider section renders its action button.
- [x] Record open questions and resolution:
  - [x] No blocking ambiguities for implementation from current request.

## Stage 1 - Code Planning

- [x] Define template changes:
  - [x] Add `{% block action_header %}` in `settings_provider.html` with section-specific submit buttons.
  - [x] Assign stable `id` to each section form and wire action bar button `form` attributes.
  - [x] Remove section-level in-form `.form-actions` save rows.
- [x] Define verification approach:
  - [x] Run automated checks applicable to touched files.
  - [x] Capture and review frontend screenshot artifact via `scripts/capture_screenshot.sh`.

## Stage 2 - Template Implementation

- [x] Implement provider action header block and form-id wiring.
- [x] Remove redundant in-form save action rows.
- [x] Validate rendered sections still submit correctly.

## Stage 3 - Frontend Visual Verification

- [x] Capture at least one screenshot reflecting the updated provider settings action bar.
- [x] Review screenshot artifact and keep only relevant artifacts for this change.

## Stage 4 - Automated Testing

- [x] Run automated test/check command(s) relevant to this change.
- [x] Confirm commands pass or document failures.
  - [x] `./.venv/bin/python3 -m pytest app/llmctl-studio/tests/test_skills_stage5.py -q` -> `2 passed`

## Stage 5 - Docs Updates

- [x] Update docs if needed for behavior/UI changes.
- [x] If no docs changes are needed, explicitly record that decision.
  - [x] No Sphinx/RTD docs changes required; UI behavior updated in-place and verified with screenshot artifacts.
