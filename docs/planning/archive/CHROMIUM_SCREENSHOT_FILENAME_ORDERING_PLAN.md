# Chromium Screenshot Filename Ordering Plan

## Stage 0 - Requirements Gathering
- [x] Review user request to make screenshot filenames sort chronologically by placing datetime first.
- [x] Confirm required timestamp format is `YYYY-MM-DD-HH-MM-SS`.
- [x] Identify requirement scope: update wherever filename is generated or documented (host skill + repo skill/docs).
- [x] Confirm no additional missing requirements before implementation planning.

## Stage 1 - Code Planning
- [x] Locate filename generation logic in repo and host skill copies.
- [x] Define implementation stages:
  - Stage 2: Update filename generation scripts.
  - Stage 3: Update skill/documentation references.
  - Stage 4: Automated Testing.
  - Stage 5: Docs Updates completion and plan archival.

## Stage 2 - Update Filename Generation
- [x] Update repo screenshot script to emit datetime-first filenames in `YYYY-MM-DD-HH-MM-SS` format.
- [x] Update host screenshot script to emit datetime-first filenames in `YYYY-MM-DD-HH-MM-SS` format.

## Stage 3 - Update Skill/Docs References
- [x] Update repo `codex-skills/chromium-screenshot/SKILL.md` filename format guidance.
- [x] Update host `~/.codex/skills/chromium-screenshot/SKILL.md` filename format guidance.
- [x] Update repo docs (`docs/sphinx/codex_skills.rst`) filename format guidance.
- [x] Confirm AGENTS guidance does not reference the old filename pattern (no AGENTS edit needed).

## Stage 4 - Automated Testing
- [x] Run script-level sanity checks (help output + timestamp/filename smoke checks).
- [x] Verify both script copies produce the expected filename prefix format.

## Stage 5 - Docs Updates
- [x] Ensure documentation reflects final filename convention.
- [x] Mark all plan items complete and move this plan to `docs/planning/archive/`.
