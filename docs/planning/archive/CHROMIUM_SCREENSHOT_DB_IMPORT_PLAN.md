# Chromium Screenshot Skill DB Import Plan

## Stage 0: Requirements Gathering
- [x] Interview request intent from prompt: add host `chromium-screenshot` skill to `llmctl-studio` DB now.
- [x] Confirm scope: database update only (no seed rewrite requested).
- [x] Identify missing requirements and resolve:
  - [x] Use host skill source at `~/.codex/skills/chromium-screenshot`.
  - [x] Use first version `1.0.0` with status `active`.

## Stage 1: Code Planning
- [x] Define execution stages:
  - [x] Stage 2: Build a Studio-compatible bundle from host skill files (`SKILL.md` + `scripts/`).
  - [x] Stage 3: Import bundle into Studio DB with provenance metadata.
  - [x] Stage 4: Verify inserted rows in skills/version/files tables.
  - [x] Stage 5: Automated Testing.
  - [x] Stage 6: Docs Updates.

## Stage 2: Build Compatible Bundle
- [x] Create bundle JSON from host skill while excluding unsupported `agents/` package files.
- [x] Set metadata overrides required by Studio validator (`display_name`, `version`, `status`).

## Stage 3: Import to Database
- [x] Import bundle via `app/llmctl-studio/scripts/import_skill_package.py --apply`.
- [x] Record source reference as `~/.codex/skills/chromium-screenshot`.

## Stage 4: Verification
- [x] Verify `skills` entry exists for `chromium-screenshot`.
- [x] Verify `skill_versions` entry exists for `1.0.0`.
- [x] Verify `skill_files` rows include `SKILL.md` and `scripts/capture_screenshot.sh`.

## Stage 5: Automated Testing
- [x] Run bundle validation with `app/llmctl-studio/scripts/validate_skill_package.py --bundle ...`.
- [x] Confirm import script reports `"ok": true` and `"applied": true`.

## Stage 6: Docs Updates
- [x] Confirm no Sphinx/RTD doc content change required for this one-time DB data import.
- [x] Archive this completed plan.
