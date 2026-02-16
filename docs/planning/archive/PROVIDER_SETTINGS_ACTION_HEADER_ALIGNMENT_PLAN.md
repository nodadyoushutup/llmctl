# Provider Settings Action Header Alignment Plan

Goal: Right-align the provider settings action-header save button so it appears on the right side of the header bar.

## Stage 0 - Requirements Gathering

- [x] Capture user requirement:
  - [x] Move provider settings header action button to the right side of the header/screen.
- [x] Scope confirmation:
  - [x] Applies to provider settings action header (`settings_provider.html`).
  - [x] Keep existing submit behavior and labels unchanged.

## Stage 1 - Code Planning

- [x] Implementation plan:
  - [x] Update `action_header` markup to right-align button container.
  - [x] Avoid route/view or form payload changes.
- [x] Verification plan:
  - [x] Capture frontend screenshot artifact after update.
  - [x] Run a lightweight automated check command.

## Stage 2 - Template Implementation

- [x] Right-align provider action-header button container.
- [x] Confirm section-specific submit buttons still render.

## Stage 3 - Frontend Visual Verification

- [x] Capture and review screenshot showing right-aligned header button.

## Stage 4 - Automated Testing

- [x] Run relevant automated checks.
- [x] Record pass/fail.
  - [x] `./.venv/bin/python3 -m pytest app/llmctl-studio/tests/test_skills_stage5.py -q` -> `2 passed`

## Stage 5 - Docs Updates

- [x] Update docs if needed.
- [x] If no docs updates are needed, record that explicitly.
  - [x] No Sphinx/RTD docs updates required for this alignment-only UI adjustment.
