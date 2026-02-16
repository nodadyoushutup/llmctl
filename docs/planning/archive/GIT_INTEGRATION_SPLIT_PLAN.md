# Git Integration Split Plan

Goal: separate Git host-level configuration from GitHub integration settings by adding a dedicated Git integrations section/page for editing `~/.gitconfig`.

## Stage 0 - Requirements Gathering

- [x] Interview stakeholder request and lock intent from prompt.
- [x] Confirm Git must be independent from GitHub in integrations.
- [x] Confirm GitLab integration is explicitly out of scope for now.
- [x] Confirm work target: move `gitconfig` editing to Settings -> Integrations -> Git.

## Stage 1 - Code Planning

- [x] Identify current `gitconfig` routes and templates.
- [x] Identify integrations navigation and section-rendering flow.
- [x] Define change set:
  - [x] Add a new `git` integrations section in route metadata + UI nav.
  - [x] Move `gitconfig` form into integrations template under `git`.
  - [x] Repoint form POST to integrations-scoped update route.
  - [x] Remove standalone GitConfig settings nav entry and repoint links.
  - [x] Keep backward compatibility by redirecting legacy `/settings/gitconfig` routes.

## Stage 2 - Backend Wiring

- [x] Add Git section metadata to integrations route map.
- [x] Add `/settings/integrations/git` GET route.
- [x] Add `/settings/integrations/git` POST route for writing `~/.gitconfig`.
- [x] Provide Git context (`gitconfig_path`, `gitconfig_exists`, `gitconfig_content`) via integrations context builder.
- [x] Convert legacy `/settings/gitconfig` GET/POST to redirects/compatibility alias to the new integrations Git page.

## Stage 3 - Template and Navigation Updates

- [x] Add `Git` item to integrations top nav.
- [x] Add `integration_section == "git"` card/form block in `settings_integrations.html`.
- [x] Remove standalone `GitConfig` settings nav item from sidebar.
- [x] Update Settings overview card link to open integrations Git page.
- [x] Remove obsolete standalone template if no longer used.

## Stage 4 - Frontend Visual Verification

- [x] Capture at least one screenshot using `capture_screenshot.sh`.
- [x] Review screenshot to confirm Git section appears under integrations and form renders correctly.
- [x] Keep screenshot artifact under `docs/screenshots/` with required filename pattern.

## Stage 5 - Automated Testing

- [x] Run targeted automated tests or validation commands for modified settings/integrations code.
- [x] Run any fast sanity checks needed to confirm no template/render errors.

## Stage 6 - Docs Updates

- [x] Update this plan checklist to final status.
- [x] Move completed plan from `docs/planning/active/` to `docs/planning/archive/`.
