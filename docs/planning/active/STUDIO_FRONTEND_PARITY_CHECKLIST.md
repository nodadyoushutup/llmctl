# Studio Frontend Parity Checklist

Purpose: track React parity against legacy Flask GUI routes during migration, including functional and visual (legacy-accurate) parity requirements.

Status key:
- `Native React`: page/flow implemented directly in React components.
- `Legacy Bridge`: page/flow served through React shell by mirroring backend GUI route at `/api/...`.
- `Visual Signoff Required`: native route is not cutover-ready until screenshot parity is approved.

## Wave 1 - Core and Chat Read Flows
- [x] Overview shell (`/overview` -> `/overview`) [Native React].
- [x] API diagnostics (`/api/health` + `/api/chat/activity` -> `/api-diagnostics`) [Native React].
- [x] Chat activity list (`/chat/activity` -> `/chat/activity`) [Native React].
- [x] Chat thread detail read (`/chat` thread context -> `/chat/threads/:threadId`) [Native React].

## Wave 2 - Agent Execution Flows
- [x] Runs read monitor in React (`/execution-monitor` -> `/api/runs/:id`) [Native React].
- [x] Nodes status monitor in React (`/execution-monitor` -> `/api/nodes/:id/status`) [Native React].
- [x] Agents full route coverage (`/agents`, `/agents/new`, `/agents/:id`, `/agents/:id/edit`) [Native React].
- [x] Runs full route coverage (`/runs`, `/runs/new`, `/runs/:id`, `/runs/:id/edit`) [Native React].
- [x] Quick+Nodes full route coverage (`/quick`, `/nodes`, `/nodes/new`, `/nodes/:id`) [Native React].

## Wave 3 - Planning and Knowledge Objects
- [x] Plans list/detail/edit + stage/task mutations [Native React].
- [x] Milestones list/detail/edit [Native React].
- [x] Task templates list/detail/edit/delete + flowchart-managed create policy [Native React].
- [x] Memories list/detail/edit/delete + flowchart-managed create policy [Native React].

## Wave 4 - Flowchart System
- [x] Flowchart list/new/detail/edit [Native React].
- [x] Flowchart history and run detail [Native React].
- [x] Flowchart graph/runtime/validation/execution controls [Native React].
- [x] Flowchart node utility/model/mcp/script/skill mutations [Native React].

## Wave 5 - Studio Assets and Catalogs
- [x] Skills CRUD/import/export [Native React].
- [x] Scripts CRUD [Native React].
- [x] Attachments list/detail/file/delete [Native React].
- [x] Models CRUD/default management [Native React].
- [x] MCP server CRUD/detail [Native React].

## Wave 6 - Settings and Runtime Controls
- [x] Roles CRUD [Legacy Bridge].
- [x] Core/provider settings [Native React].
- [x] Runtime/chat settings [Native React].
- [x] Git config + integrated settings sections [Native React].

## Wave 7 - Integrations and RAG Surfaces
- [x] GitHub browser and pull-request review views [Native React].
- [x] Jira/Confluence explorer routes [Native React].
- [x] Chroma collection explorer [Native React].
- [x] RAG chat + sources CRUD and quick index/delta index [Native React].

## Global Parity Gates
- [x] Mutation parity preserved by bridge coverage for not-yet-native routes.
- [x] Validation and error feedback preserved via native or bridge route behavior.
- [x] Long-running task feedback and realtime update parity preserved via native polling on execution routes.
- [x] Every legacy route now has a working React route surface (native or bridge).

## Visual Parity Gates (Hard Block Before Cutover)
- [ ] Legacy baseline screenshots are captured for each user-facing route/state (desktop + mobile).
- [ ] React screenshots match legacy baseline for layout, spacing, typography, colors, and iconography.
- [ ] React interactive states (hover/focus/active/disabled/loading/error/empty) match legacy behavior and styling.
- [ ] Every native route has explicit visual signoff recorded prior to bridge removal.
- [ ] Visual signoff is complete for all remaining waves before legacy GUI removal.

## Stage 9 - Execution Tracker

### Parallel Ownership Model (Two Agents)
- [x] Parallel execution uses route-family ownership; each agent completes both visual and behavioral parity for owned waves.
- [ ] Agent A owns Wave 2 + Wave 6 routes and related screenshots/signoff.
- [ ] Agent B owns Wave 1 + Wave 5 + Wave 7 routes and related screenshots/signoff.
- [ ] Completed Wave 3 + Wave 4 remain locked unless a regression is discovered.
- [ ] Shared-file lock required before editing cross-cutting files:
- [ ] `app/llmctl-studio-frontend/src/components/AppLayout.jsx`
- [ ] `app/llmctl-studio-frontend/src/styles.css`
- [ ] `app/llmctl-studio-frontend/src/App.jsx`
- [ ] `app/llmctl-studio-frontend/src/lib/studioApi.js`
- [ ] `app/llmctl-studio-frontend/src/lib/studioApi.test.js`
- [ ] `app/llmctl-studio-frontend/src/parity/checklist.js`
- [ ] Merge policy: one slice PR per agent, then rebase before starting next slice.

### Current Iteration Notes (2026-02-17)
- [x] Legacy shell structure ported into React (`AppLayout`) with grouped left-nav sections, collapsible section toggles, and icon affordances.
- [x] Legacy base visual tokens ported into shared React stylesheet (typography, gradients, card geometry, table/badge/button/status primitives).
- [x] Stage 9 shell parity screenshots captured:
  - `docs/screenshots/2026-02-17-09-32-37--overview--stage9-shell-parity--1920x1080--6c88ada--9af588.png`
  - `docs/screenshots/2026-02-17-09-37-32--agents--stage9-shell-parity-v2--1920x1080--6c88ada--1f33ae.png`
- [x] Stage 9 Slice 2 `/runs` parity screenshot captured:
  - `docs/screenshots/2026-02-17-09-45-37--runs--stage9-slice2-parity--1920x1080--6c88ada--6e40d4.png`
- [x] Stage 9 Slice 2 `/nodes` parity screenshot captured:
  - `docs/screenshots/2026-02-17-09-51-57--nodes--stage9-slice2-parity--1920x1080--6c88ada--e9f3fa.png`
- [x] Stage 9 Slice 2 `/quick` parity screenshot captured:
  - `docs/screenshots/2026-02-17-10-04-02--quick--stage9-slice2-parity--1920x1080--6c88ada--35f187.png`
- [x] Stage 9 Slice 2 `/execution-monitor` parity screenshot captured:
  - `docs/screenshots/2026-02-17-10-04-02--execution-monitor--stage9-slice2-parity--1920x1080--6c88ada--2c2ad6.png`
- [x] Stage 9 Slice 3 `/chat/activity` parity screenshot captured:
  - `docs/screenshots/2026-02-17-10-23-32--chat-activity--stage9-slice3-parity--1920x1080--6c88ada--45880a.png`
- [x] Stage 9 Slice 3 `/execution-monitor` parity screenshot recaptured after monitor default-load fix:
  - `docs/screenshots/2026-02-17-10-23-32--execution-monitor--stage9-slice3-parity--1920x1080--6c88ada--431358.png`
- [x] Stage 9 Slice 3 `/plans` parity screenshot captured:
  - `docs/screenshots/2026-02-17-10-39-23--plans--stage9-slice3-parity--1920x1080--6c88ada--eba1ec.png`
- [x] Stage 9 Slice 3 `/milestones` parity screenshot captured:
  - `docs/screenshots/2026-02-17-10-39-23--milestones--stage9-slice3-parity--1920x1080--6c88ada--d5abe3.png`
- [x] Stage 9 Slice 3 `/memories` parity screenshot captured:
  - `docs/screenshots/2026-02-17-10-39-23--memories--stage9-slice3-parity--1920x1080--6c88ada--3f3018.png`
- [x] Stage 9 Slice 3 `/task-templates` parity screenshot captured:
  - `docs/screenshots/2026-02-17-10-39-23--task-templates--stage9-slice3-parity--1920x1080--6c88ada--7bcb53.png`
- [x] Stage 9 Slice 3 planning detail/edit parity rework complete:
  - `/plans/:planId` + `/plans/:planId/edit`
  - `/milestones/:milestoneId` + `/milestones/:milestoneId/edit`
  - `/memories/:memoryId` + `/memories/:memoryId/edit`
  - `/task-templates/:templateId` + `/task-templates/:templateId/edit`
- [x] Stage 9 Slice 3 `/plans/:planId` parity screenshot captured:
  - `docs/screenshots/2026-02-17-11-03-06--plans-detail--stage9-slice3-parity--1920x1080--6c88ada--572e8e.png`
- [x] Stage 9 Slice 3 `/plans/:planId/edit` parity screenshot captured:
  - `docs/screenshots/2026-02-17-11-03-08--plans-edit--stage9-slice3-parity--1920x1080--6c88ada--cc9e7f.png`
- [x] Stage 9 Slice 3 `/milestones/:milestoneId` parity screenshot captured:
  - `docs/screenshots/2026-02-17-11-03-09--milestones-detail--stage9-slice3-parity--1920x1080--6c88ada--a32a21.png`
- [x] Stage 9 Slice 3 `/milestones/:milestoneId/edit` parity screenshot captured:
  - `docs/screenshots/2026-02-17-11-03-10--milestones-edit--stage9-slice3-parity--1920x1080--6c88ada--b622da.png`
- [x] Stage 9 Slice 3 `/memories/:memoryId` parity screenshot captured:
  - `docs/screenshots/2026-02-17-11-03-12--memories-detail--stage9-slice3-parity--1920x1080--6c88ada--b95c4f.png`
- [x] Stage 9 Slice 3 `/memories/:memoryId/edit` parity screenshot captured:
  - `docs/screenshots/2026-02-17-11-03-13--memories-edit--stage9-slice3-parity--1920x1080--6c88ada--73150a.png`
- [x] Stage 9 Slice 3 `/task-templates/:templateId` parity screenshot captured:
  - `docs/screenshots/2026-02-17-11-03-14--task-templates-detail--stage9-slice3-parity--1920x1080--6c88ada--a980bd.png`
- [x] Stage 9 Slice 3 `/task-templates/:templateId/edit` parity screenshot captured:
  - `docs/screenshots/2026-02-17-11-03-15--task-templates-edit--stage9-slice3-parity--1920x1080--6c88ada--fbd8c1.png`
- [x] Screenshot capture note: `/web/*` headless captures were blank in Chromium; Slice 3 detail/edit screenshots were captured from local Vite (`http://127.0.0.1:4173`) to validate visual output.
- [x] Stage 9 Slice 4 flowchart parity rework complete:
  - `/flowcharts`
  - `/flowcharts/new`
  - `/flowcharts/:flowchartId`
  - `/flowcharts/:flowchartId/edit`
  - `/flowcharts/:flowchartId/history`
  - `/flowcharts/:flowchartId/history/:runId`
  - `/flowcharts/runs/:runId`
- [x] Stage 9 Slice 4 `/flowcharts` parity screenshot captured:
  - `docs/screenshots/2026-02-17-11-40-38--flowcharts--stage9-slice4-parity--1920x1080--6c88ada--12b022.png`
- [x] Stage 9 Slice 4 `/flowcharts/new` parity screenshot captured:
  - `docs/screenshots/2026-02-17-11-39-23--flowcharts-new--stage9-slice4-parity--1920x1080--6c88ada--335a2a.png`
- [x] Stage 9 Slice 4 `/flowcharts/:flowchartId` parity screenshot captured:
  - `docs/screenshots/2026-02-17-11-39-24--flowchart-detail--stage9-slice4-parity--1920x1080--6c88ada--ec366e.png`
- [x] Stage 9 Slice 4 `/flowcharts/:flowchartId/edit` parity screenshot captured:
  - `docs/screenshots/2026-02-17-11-39-25--flowchart-edit--stage9-slice4-parity--1920x1080--6c88ada--e2aebd.png`
- [x] Stage 9 Slice 4 `/flowcharts/:flowchartId/history` parity screenshot captured:
  - `docs/screenshots/2026-02-17-11-39-25--flowchart-history--stage9-slice4-parity--1920x1080--6c88ada--64d0d3.png`
- [x] Stage 9 Slice 4 `/flowcharts/:flowchartId/history/:runId` parity screenshot captured:
  - `docs/screenshots/2026-02-17-11-39-27--flowchart-history-run--stage9-slice4-parity--1920x1080--6c88ada--e55f18.png`
- [x] Stage 9 Slice 4 `/flowcharts/runs/:runId` parity screenshot captured:
  - `docs/screenshots/2026-02-17-11-39-28--flowchart-run-detail--stage9-slice4-parity--1920x1080--6c88ada--e3d422.png`

### Baseline Capture Completion
- [ ] Wave 1 baseline set captured (desktop + mobile).
- [ ] Wave 2 baseline set captured (desktop + mobile).
- [ ] Wave 3 baseline set captured (desktop + mobile).
- [ ] Wave 4 baseline set captured (desktop + mobile).
- [ ] Wave 5 baseline set captured (desktop + mobile).
- [ ] Wave 6 baseline set captured (desktop + mobile).
- [ ] Wave 7 baseline set captured (desktop + mobile).

### Visual Signoff by Route Family
- [ ] Wave 1 visual signoff complete (Agent B) (`/overview`, `/parity-checklist`, `/api-diagnostics`, `/chat/activity`, `/chat/threads/:threadId`).
- [ ] Wave 2 visual signoff complete (Agent A) (`/agents*`, `/runs*`, `/quick`, `/nodes*`, `/execution-monitor`).
- [ ] Wave 3 visual signoff complete (`/plans*`, `/milestones*`, `/memories*`, `/task-templates*`).
- [ ] Wave 4 visual signoff complete (`/flowcharts*` list/detail/edit/history/run).
- [ ] Wave 5 visual signoff complete (Agent B) (`/skills*`, `/scripts*`, `/attachments*`, `/models*`, `/mcps*`).
- [ ] Wave 6 visual signoff complete (Agent A) (`/settings/core`, `/settings/provider*`, `/settings/runtime*`, `/settings/chat`, `/settings/integrations*`).
- [ ] Wave 7 visual signoff complete (Agent B) (`/rag*`, `/github*`, `/jira*`, `/confluence`, `/chroma*`).

### Behavioral Signoff by Route Family
- [ ] Wave 1 behavior signoff complete (Agent B) (navigation, read-only flows, loading/error states).
- [ ] Wave 2 behavior signoff complete (Agent A) (execution lifecycle, status updates, row/action interactions).
- [ ] Wave 3 behavior signoff complete (CRUD and plan stage/task mutation behavior).
- [ ] Wave 4 behavior signoff complete (graph/runtime/history and node utility behavior).
- [ ] Wave 5 behavior signoff complete (Agent B) (asset CRUD/import/export/detail behavior).
- [ ] Wave 6 behavior signoff complete (Agent A) (settings mutation/validation and provider/integration behavior).
- [ ] Wave 7 behavior signoff complete (Agent B) (RAG source lifecycle, chat behavior, external workspace drill-down behavior).

### Cross-Cutting Hard Gates
- [ ] List row-click behavior parity confirmed (`table-row-link`, interactive element exclusions) across all list views.
- [ ] Icon-only action behavior parity confirmed (edit/delete/play buttons, confirmations, disable/busy behavior).
- [ ] Mutation feedback parity confirmed (success banners, validation errors, failed request states).
- [ ] Realtime/long-running feedback parity confirmed (runs/nodes/flowcharts/RAG quick index).
- [ ] Responsive parity confirmed (desktop + mobile layout and overflow behavior) across all waves.
