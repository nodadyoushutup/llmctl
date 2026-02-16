# Codex Chromium Screenshot Skill Plan

## Stage 0: Requirements Gathering
- [x] Confirm objective: move screenshot workflow guidance out of `AGENTS.md` into a Codex skill used by the top-level developer assistant.
- [x] Confirm scope boundary: do not change internal/in-app skill behavior.
- [x] Confirm deliverable expectations from user prompt:
  - [x] create skill assets and instructions
  - [x] make setup reproducible from the repository
  - [x] wire local Codex environment to use the skill

## Stage 1: Code Planning
- [x] Define execution stages:
  - [x] Stage 2: Create repo-owned skill source files.
  - [x] Stage 3: Add installer/sync script and install into `~/.codex/skills`.
  - [x] Stage 4: Simplify `AGENTS.md` by removing detailed screenshot policy and delegating to the skill.
  - [x] Stage 5: Automated Testing.
  - [x] Stage 6: Docs Updates.

## Stage 2: Create Skill Source
- [x] Add a versioned skill folder under this repo for Chromium screenshot workflows.
- [x] Implement `SKILL.md` with trigger-oriented description and concise operational procedure.
- [x] Add reusable screenshot helper script(s) under skill `scripts/`.
- [x] Add skill UI metadata (`agents/openai.yaml`).

## Stage 3: Install/Sync Automation
- [x] Add a repo script to install/sync project-owned Codex skills into `~/.codex/skills`.
- [x] Run install/sync so `chromium-screenshot` is present in local Codex skills.

## Stage 4: AGENTS Cleanup
- [x] Remove detailed frontend screenshot workflow block from `AGENTS.md`.
- [x] Add a minimal directive to rely on the `chromium-screenshot` skill for screenshot policy.

## Stage 5: Automated Testing
- [x] Validate the skill via `quick_validate.py`.
- [x] Execute screenshot helper script against a safe URL to confirm artifact creation.
- [x] Execute installer script in dry-run and active mode.

## Stage 6: Docs Updates
- [x] Document how to use and install project-owned Codex skills.
- [x] Document screenshot naming/location conventions in project docs (Sphinx/RTD-facing docs tree).
- [x] Move this completed plan to `docs/planning/archive/`.
