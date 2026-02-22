# UI Header Consistency Plan

## Goal
Establish a consistent header system across Studio pages, starting with top-level page/panel headers, then migrate targeted screens safely.

## Stage 0 - Requirements Gathering
- [x] Confirm first-pass page scope for header consistency work.
- [x] Confirm canonical header layout rules (title, metadata, actions, spacing, alignment).
- [x] Confirm interaction expectations (icon-only actions, responsive collapse behavior, sticky vs non-sticky).
- [x] Confirm visual constraints (density, typography, border treatment, background treatment).
- [x] Confirm acceptance criteria and sign-off workflow for Stage 0 completion.
- [x] Confirm Stage 0 is complete and ask whether to proceed to Stage 1.

## Stage 0 - Interview Notes
- [x] Initial request captured: create a new UI consistency plan starting with headers.
- [x] Scope decision: `Full sweep` for all Studio pages with headers (user selected option 1).
- [x] Header structure decision: `Compact` with no metadata line for now (user selected option 1 with metadata excluded).
- [x] Interaction decision: sticky headers accepted, with page model set to fixed-height panels that fill content area and avoid page scrolling; when space is tight, use inner navigation/panel structures (like Settings) instead of expanding page scroll.
- [x] Visual treatment decision: `Minimal line` header baseline (transparent background, bottom divider, tight spacing).
- [x] Done criteria decision: `Strict` - every in-scope page header migrated with no legacy header variants remaining (user selected option 1).
- [x] Stage 0 completion gate: user approved proceeding to Stage 1 (`option 2`).

## Stage 1 - Code Planning
- [x] Inventory all current header implementations/components/CSS patterns.
- [x] Define shared header primitives and composition patterns.
- [x] Define Stage 3+ implementation stages based on approved Stage 0 requirements.
- [x] Ensure final two stages remain `Automated Testing` and `Docs Updates`.

Stage 1 inventory summary:
- `PanelHeader` exists as current shared primitive (`components/PanelHeader.jsx`) and is already used in list/fixed pages and chat panels.
- Legacy/alternate header variants remain widespread via `.card-header` + `.section-title`, direct `<h2>` blocks, and bespoke wrappers (for example provider/settings, flowchart detail toolbar header, and chat-specific header classes).
- Header styling is split across `.panel-header*`, `.card-header`, `.provider-settings-header`, `.chat-panel-header`, and flowchart/node detail header blocks in `styles.css`.
- Migration must converge all page-level/panel-level headers onto one compact variant family and remove redundant legacy header structures under strict completion criteria.

## Stage 2 - Scope-Specific Planning
- [x] Define the header consistency spec for this workstream.
- [x] Map each in-scope page family to migration approach and shared component usage.
- [x] Define explicit out-of-scope items for this pass.

Stage 2 scope-specific header spec:
- Canonical header: compact, title-only, no metadata line, icon-only actions, minimal-line treatment (transparent background + bottom divider).
- Layout policy: fixed-height page model; no page-level scrolling; headers may be sticky but should not rely on page scroll behavior.
- Density target: compact row height (roughly current 44-48px profile), tight horizontal spacing, consistent left/right alignment across all pages.
- Action policy: icon-only controls in header action area; destructive actions remain explicit and consistent with existing danger affordances.

Stage 2 migration map:
- Family A (already near-target): list/fixed pages using `PanelHeader`; normalize variants and remove per-page drift.
- Family B (legacy card headers): pages using `.card-header`/`.section-title`; migrate to shared header primitive.
- Family C (bespoke headers): chat panels, flowchart detail header, settings/provider/integration headers, node/artifact detail headers; adapt to shared compact header contract with route-specific action composition only.
- Family D (detail/new/edit pages with direct `<h2>` headings): migrate to shared header wrapper, preserving existing actions/navigation behavior.

Stage 2 explicit out-of-scope:
- Non-header content redesign (tables/forms/panel body structures) except where required to attach standardized headers.
- Copy/IA rewrites beyond minimal title normalization needed for consistency.
- New notification systems or non-header UX pattern changes.

## Stage 3 - Shared Header Foundation
- [x] Implement/update shared header building blocks and shared styles.
- [x] Add/update examples/usages in representative pages.

## Stage 4 - Family A Migration (PanelHeader Normalization)
- [x] Normalize all existing `PanelHeader` usages to compact title-only conventions.
- [x] Remove per-page header class drift where shared class coverage is sufficient.

## Stage 5 - Family B Migration (Legacy Card Headers)
- [x] Replace `.card-header` + `.section-title` page/panel headers with shared compact header primitive.
- [x] Keep body content behavior unchanged while removing legacy header-only wrappers.

## Stage 6 - Family C Migration (Bespoke Headers)
- [x] Migrate bespoke chat/flowchart/settings/detail header implementations to shared compact header contract.
- [x] Preserve route-specific action sets while removing duplicate bespoke header scaffolding.

## Stage 7 - Family D Migration (Direct H2 Detail/New/Edit Headers)
- [x] Migrate remaining direct `<h2>` page-entry headers to shared compact header wrappers.
- [x] Eliminate remaining legacy page-level header variants.

## Stage 8 - Header Cleanup And Strictness Enforcement
- [x] Remove obsolete header CSS blocks and dead markup paths superseded by shared primitives.
- [x] Add guardrails (tests/checks) ensuring new one-off header variants are not reintroduced.

## Stage 9 - Automated Testing
- [x] Run frontend tests covering changed header components/pages.
- [x] Run additional lint/build checks needed for confidence.

## Stage 10 - Docs Updates
- [x] Update relevant Sphinx/Read the Docs pages for UI/header conventions.
- [x] Archive this plan in `docs/planning/archive/` after completion.

## Execution Notes (2026-02-21)
- Completed migration pass from legacy `title-row` to `PanelHeader` for model/mcp/skill/script list+detail+new+edit pages, including related tests (`ModelNewPage.test.jsx`, `ModelEditPage.test.jsx`).
- Guardrail check passes: `npm run check:header-consistency`.
- Frontend validation passes: `npm run test -- src/pages/ModelNewPage.test.jsx src/pages/ModelEditPage.test.jsx src/pages/ChatPage.test.jsx` and `npm run build`.
- Frontend rollout restarted and healthy: `kubectl -n llmctl rollout restart deploy/llmctl-studio-frontend` + rollout status success.
- Visual verification captured and reviewed:
  - `docs/screenshots/2026-02-21-18-50-03--models--panel-header-migration-after-restart--1920x1080--7cb3953--d9cf47.png`
- Remaining Stage 7 scope: direct `title-row` page-entry headers still present on 38 pages (for example flowchart detail/edit families, run/plan/memory/milestone detail/edit/new families, integrations/workspace pages, and several agent/role/attachment pages).
- Completed Stage 7 full sweep:
  - Migrated all remaining `title-row` page-entry headers to `PanelHeader` across agent/role/run/rag/jira/github/chroma/settings/confluence/attachments/node/execution pages.
  - Migrated invalid-state page-entry `<h2>` branches to `PanelHeader` where applicable.
  - Removed obsolete `.title-row`, `.title-row h2`, and unused `.section-title` CSS blocks from `styles.css`.
  - Verified zero residual legacy page-level header wrappers with `rg -n "title-row" app/llmctl-studio-frontend/src -S` (no matches).
- Final validation for this pass:
  - `npm run check:header-consistency` (pass)
  - `npm run test -- src/pages/ChatPage.test.jsx` (pass)
  - `npm run build` (pass)
  - Frontend rollout restart + health check:
    - `kubectl -n llmctl rollout restart deploy/llmctl-studio-frontend`
    - `kubectl -n llmctl rollout status deploy/llmctl-studio-frontend`
- Visual verification artifacts:
  - `docs/screenshots/2026-02-21-19-23-26--chat-thread-21--header-plan-final--1920x1080--6cc7fdc--c6297c.png`
  - `docs/screenshots/2026-02-21-19-23-26--flowcharts-1--header-plan-reference--1920x1080--6cc7fdc--7eaa44.png`
- Stage 10 docs updates:
  - Added `docs/sphinx/studio_ui_header_conventions.rst`.
  - Added `studio_ui_header_conventions` to `docs/sphinx/index.rst` Runtime Guides toctree.
