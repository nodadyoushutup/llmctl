# Chat Settings UI Refresh Plan

Goal: refresh the Chat settings page to match the site's settings visual language and move save behavior into the shared sticky action header.

## Stage 0 - Requirements Gathering

- [x] Interview request intent from stakeholder message.
- [x] Confirm target surface is `Settings > Chat` (`settings_chat.html`).
- [x] Clarify required interaction change:
  - [x] Add a header action button for save using the base `action_header` block.
- [x] Gather constraints and assumptions:
  - [x] Keep existing POST route and payload field names unchanged.
  - [x] Keep behavior focused on template/UI changes only unless blocked.
  - [x] Align styling with existing settings cards, labels, and input classes.

## Stage 1 - Code Planning

- [x] Define Stage 2 through Stage 5 implementation sequence.
- [x] Stage 2 scope: refactor `settings_chat.html` layout and form styling.
- [x] Stage 3 scope: add sticky header save action wired to form id.
- [x] Stage 4 scope: run automated testing/checks relevant to touched files.
- [x] Stage 5 scope: update docs/planning status, archive completed plan, and record docs impact.

## Stage 2 - Template Refresh

- [x] Replace plain grid/inline form structure with site-consistent card/subcard/form-grid layout.
- [x] Group fields into clear sections (budget allocation, compaction, retrieval/defaults).
- [x] Preserve all current form field names and constraints.

## Stage 3 - Header Save Action

- [x] Add `{% block action_header %}` save button for chat settings.
- [x] Add stable form `id` and wire header button via `form` attribute.
- [x] Remove redundant in-form save button row.

## Stage 4 - Automated Testing

- [x] Run automated checks for affected template/render path.
- [x] Capture and review at least one frontend screenshot artifact via `chromium-screenshot` workflow.

## Stage 5 - Docs Updates

- [x] Record completion notes and outcomes in this plan.
- [x] Move completed plan from `docs/planning/active/` to `docs/planning/archive/`.
- [x] Confirm whether Sphinx/Read the Docs updates are required.

## Completion Notes (2026-02-16)

- Refreshed `settings_chat.html` to use site-aligned card/subcard/form-grid layout and grouped controls.
- Added sticky header save action via `action_header` block, wired to `#chat-runtime-settings-form`.
- Preserved all existing chat runtime POST field names and min/max constraints.
- Automated test run:
  - `.venv/bin/python3 -m pytest app/llmctl-studio/tests/test_chat_runtime_stage8.py -q` -> `9 passed`
- Frontend screenshot artifact captured and reviewed:
  - `docs/screenshots/2026-02-16-11-52-26--settings-chat--refreshed-ui--1920x1080--c082228--9e2363.png`
- Sphinx/Read the Docs updates:
  - No documentation content changes required for this UI-only refresh.
