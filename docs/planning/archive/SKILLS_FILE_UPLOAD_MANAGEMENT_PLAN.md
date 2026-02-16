# Skills File Upload & Editing Plan

Goal: enable Skill authoring/editing with controlled `SKILL.md` editing plus managed file uploads (including assets/docs), while enforcing git-based skill read-only behavior.

## Stage 0 - Requirements Gathering

- [x] Confirm scope includes all skill surfaces: create-from-scratch, local/imported skill editing, and imported-skill post-import file management.
- [x] Confirm upload safety defaults:
  - [x] allow text/code/docs plus small assets.
  - [x] block executables/binaries outside approved list.
  - [x] max 10 MB per uploaded file.
- [x] Confirm file path mapping model:
  - [x] explicit user-provided relative target path per file.
  - [x] server-side path-safe validation.
- [x] Confirm path conflict behavior:
  - [x] per-conflict choice required (`replace`, `keep both`, `skip`).
- [x] Confirm `SKILL.md` authoring mode:
  - [x] plain markdown editor only.
- [x] Confirm file operations allowed in edit UI:
  - [x] upload, rename/move, delete, replace.
- [x] Confirm persistence model:
  - [x] draft-on-form + explicit Save commit.
- [x] Confirm git-source policy:
  - [x] git-based skills are read-only in Studio (no edit/upload/delete/rename).
- [x] Confirm git-source UX:
  - [x] read-only detail experience with explicit banner and hidden edit controls.
- [x] Confirm asset extension allowlist includes combined sets:
  - [x] images (`png`, `jpg`, `jpeg`, `gif`, `webp`, `svg`).
  - [x] data files (`csv`, `tsv`, `yaml`, `yml`).
  - [x] common docs (`pdf`, `docx`, `pptx`).

## Stage 1 - Code Planning

- [x] Inventory current skill CRUD/import routes and skill package validation/materialization paths.
- [x] Define implementation stages and sequence:
  - [x] Stage 2: backend validation + upload parsing + git-read-only guards.
  - [x] Stage 3: skill package/runtime binary-safe handling for allowed non-text uploads.
  - [x] Stage 4: create/edit/detail template updates for draft file management UX.
  - [x] Stage 5: automated test updates/additions for new behavior.
  - [x] Stage 6: frontend visual verification screenshot capture.
  - [x] Stage 7: Automated Testing.
  - [x] Stage 8: Docs Updates.

## Stage 2 - Backend Upload Handling & Access Rules

- [x] Add server-side upload policy validation (extension allowlist, blocked executable types, 10 MB/file).
- [x] Add server-side payload parser for draft file actions:
  - [x] existing file rename/move/delete draft operations.
  - [x] uploaded file target-path mapping + conflict policy parsing.
- [x] Add deterministic conflict application (`replace`, `keep both`, `skip`) and keep-both renaming strategy.
- [x] Add git-based skill mutability guard helper and enforce in edit/update/delete code paths.
- [x] Ensure create/edit routes preserve explicit Save semantics (no writes before submit).

## Stage 3 - Skill Package/Runtime File Encoding Support

- [x] Add binary-safe storage envelope for approved non-text uploads while keeping DB text schema.
- [x] Update package size/checksum logic to compute over decoded payload bytes (text and binary envelope).
- [x] Update runtime skill materialization to write decoded bytes for binary envelope files and text for plain files.
- [x] Keep fallback prompt behavior SKILL.md-only and unchanged.

## Stage 4 - UI Templates for Draft File Management

- [x] Update `skill_new.html` to support:
  - [x] plain `SKILL.md` editor.
  - [x] multi-file upload with editable per-file target path.
  - [x] per-upload conflict mode selection and draft staging.
- [x] Update `skill_edit.html` to support:
  - [x] existing latest-version file list with rename/move/delete draft controls.
  - [x] upload/replace staging and explicit Save submit.
  - [x] path/conflict form payload hidden fields generated via JS.
- [x] Update `skill_detail.html` to show git read-only banner and hide edit controls for git-based skills.
- [x] Keep list/detail table-row interactions compliant with AGENTS list-view behavior.

## Stage 5 - Tests

- [x] Extend skill web route tests for:
  - [x] create-with-upload path mapping and allowlist enforcement.
  - [x] edit draft operations (rename/move/delete/replace) producing new immutable version.
  - [x] per-conflict actions (`replace`, `keep both`, `skip`).
  - [x] git-based skill read-only route enforcement.
- [x] Extend package/runtime tests for binary envelope checksum/size/materialization correctness.

## Stage 6 - Frontend Visual Verification

- [x] Capture at least one Studio screenshot for updated skills create/edit/detail UI using `chromium-screenshot` workflow.
- [x] Store artifact under `docs/screenshots` and record exact path.

## Stage 7 - Automated Testing

- [x] Run targeted skill-related test suites and report pass/fail output.
- [x] Run any additional regression tests required by touched code paths.

## Stage 8 - Docs Updates

- [x] Update Sphinx/RTD docs for skill authoring/editing workflow and upload constraints.
- [x] Document git-based skill read-only behavior and local/imported editable policy.
- [x] Document binary envelope behavior at a high level for operators/developers.
