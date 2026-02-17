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
- [x] Agent A owns Wave 2 + Wave 6 routes and related screenshots/signoff.
- [x] Agent B owns Wave 1 + Wave 5 + Wave 7 routes and related screenshots/signoff.
- [x] Completed Wave 3 + Wave 4 remain locked unless a regression is discovered.
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
- [x] Stage 9 Agent A Wave 2 desktop+mobile screenshot set captured (`stage9-agent-a-parity`) for `/agents*`, `/runs*`, `/quick`, `/nodes*`, and `/execution-monitor`.
- [x] Stage 9 Agent A Wave 6 desktop+mobile screenshot set captured (`stage9-agent-a-parity`) for `/settings/core`, `/settings/provider*`, `/settings/runtime*`, `/settings/chat`, and `/settings/integrations*`.
- [x] Stage 9 Agent A Wave 2/Wave 6 legacy baseline screenshot set captured (`stage9-agent-a-baseline`) for desktop + mobile.
- [x] Baseline capture note: legacy backend route `/execution-monitor` renders a legacy `404` page (captured as baseline) because the route is React-native only.
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
- [x] Stage 9 Wave 3 legacy baseline screenshots captured (`stage9-wave3-baseline`) for `/plans*`, `/milestones*`, `/memories*`, and `/task-templates*` (desktop + mobile).
- [x] Stage 9 Wave 3 React parity screenshots captured (`stage9-wave3-parity`) for `/plans*`, `/milestones*`, `/memories*`, and `/task-templates*` (desktop + mobile).
- [x] Stage 9 Wave 3 behavioral parity audit revalidated list row-click behavior, destructive confirms, and CRUD feedback states across planning routes.
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
- [x] Stage 9 Wave 4 signoff screenshot set captured (`stage9-wave4-signoff-live`) for `/flowcharts*` list/new/detail/edit/history/run routes (desktop + mobile):
  - `docs/screenshots/2026-02-17-12-27-33--flowcharts--stage9-wave4-signoff-live--1920x1080--9533b5a--3701f1.png`
  - `docs/screenshots/2026-02-17-12-28-01--flowcharts--stage9-wave4-signoff-live--390x844--9533b5a--b2f13f.png`
  - `docs/screenshots/2026-02-17-12-27-33--flowcharts-new--stage9-wave4-signoff-live--1920x1080--9533b5a--a99a32.png`
  - `docs/screenshots/2026-02-17-12-28-01--flowcharts-new--stage9-wave4-signoff-live--390x844--9533b5a--b36027.png`
  - `docs/screenshots/2026-02-17-12-27-33--flowchart-detail--stage9-wave4-signoff-live--1920x1080--9533b5a--7919d3.png`
  - `docs/screenshots/2026-02-17-12-28-01--flowchart-detail--stage9-wave4-signoff-live--390x844--9533b5a--4b8b97.png`
  - `docs/screenshots/2026-02-17-12-27-46--flowchart-edit--stage9-wave4-signoff-live--1920x1080--9533b5a--f00ca5.png`
  - `docs/screenshots/2026-02-17-12-28-09--flowchart-edit--stage9-wave4-signoff-live--390x844--9533b5a--00c385.png`
  - `docs/screenshots/2026-02-17-12-27-46--flowchart-history--stage9-wave4-signoff-live--1920x1080--9533b5a--95f175.png`
  - `docs/screenshots/2026-02-17-12-28-09--flowchart-history--stage9-wave4-signoff-live--390x844--9533b5a--ae6641.png`
  - `docs/screenshots/2026-02-17-12-27-46--flowchart-history-run--stage9-wave4-signoff-live--1920x1080--9533b5a--5c0911.png`
  - `docs/screenshots/2026-02-17-12-28-10--flowchart-history-run--stage9-wave4-signoff-live--390x844--9533b5a--1120d0.png`
  - `docs/screenshots/2026-02-17-12-27-52--flowchart-run-detail--stage9-wave4-signoff-live--1920x1080--9533b5a--af6337.png`
  - `docs/screenshots/2026-02-17-12-28-15--flowchart-run-detail--stage9-wave4-signoff-live--390x844--9533b5a--c6c4e5.png`
  - Note: local capture environment rendered expected route shells and control states while backend API data endpoints returned `404` in this workspace run.
- [x] Stage 9 Agent B Wave 1/5/7 parity screenshots captured (desktop + mobile):
  - `docs/screenshots/2026-02-17-12-07-25--overview--stage9-agent-b-parity--1920x1080--e23efc0--f5417c.png`
  - `docs/screenshots/2026-02-17-12-07-26--overview--stage9-agent-b-parity--390x844--e23efc0--14dd38.png`
  - `docs/screenshots/2026-02-17-12-07-27--parity-checklist--stage9-agent-b-parity--1920x1080--e23efc0--5bde53.png`
  - `docs/screenshots/2026-02-17-12-07-28--parity-checklist--stage9-agent-b-parity--390x844--e23efc0--031dd4.png`
  - `docs/screenshots/2026-02-17-12-07-29--api-diagnostics--stage9-agent-b-parity--1920x1080--e23efc0--c63887.png`
  - `docs/screenshots/2026-02-17-12-07-30--api-diagnostics--stage9-agent-b-parity--390x844--e23efc0--603926.png`
  - `docs/screenshots/2026-02-17-12-07-31--chat-activity--stage9-agent-b-parity--1920x1080--e23efc0--409893.png`
  - `docs/screenshots/2026-02-17-12-07-32--chat-activity--stage9-agent-b-parity--390x844--e23efc0--98e5a1.png`
  - `docs/screenshots/2026-02-17-12-07-33--chat-thread--stage9-agent-b-parity--1920x1080--e23efc0--f9b4ab.png`
  - `docs/screenshots/2026-02-17-12-07-34--chat-thread--stage9-agent-b-parity--390x844--e23efc0--17cc79.png`
  - `docs/screenshots/2026-02-17-12-07-35--skills--stage9-agent-b-parity--1920x1080--e23efc0--11588a.png`
  - `docs/screenshots/2026-02-17-12-07-36--skills--stage9-agent-b-parity--390x844--e23efc0--657b36.png`
  - `docs/screenshots/2026-02-17-12-07-37--scripts--stage9-agent-b-parity--1920x1080--e23efc0--177d1f.png`
  - `docs/screenshots/2026-02-17-12-07-38--scripts--stage9-agent-b-parity--390x844--e23efc0--7771e0.png`
  - `docs/screenshots/2026-02-17-12-07-39--attachments--stage9-agent-b-parity--1920x1080--e23efc0--42c2c1.png`
  - `docs/screenshots/2026-02-17-12-07-40--attachments--stage9-agent-b-parity--390x844--e23efc0--d33ff6.png`
  - `docs/screenshots/2026-02-17-12-07-41--models--stage9-agent-b-parity--1920x1080--e23efc0--62b243.png`
  - `docs/screenshots/2026-02-17-12-07-42--models--stage9-agent-b-parity--390x844--e23efc0--92bbcd.png`
  - `docs/screenshots/2026-02-17-12-07-43--mcps--stage9-agent-b-parity--1920x1080--e23efc0--ac18c2.png`
  - `docs/screenshots/2026-02-17-12-07-44--mcps--stage9-agent-b-parity--390x844--e23efc0--1e65ee.png`
  - `docs/screenshots/2026-02-17-12-07-45--rag-chat--stage9-agent-b-parity--1920x1080--e23efc0--65c68f.png`
  - `docs/screenshots/2026-02-17-12-07-46--rag-chat--stage9-agent-b-parity--390x844--e23efc0--441e29.png`
  - `docs/screenshots/2026-02-17-12-07-47--rag-sources--stage9-agent-b-parity--1920x1080--e23efc0--9574cd.png`
  - `docs/screenshots/2026-02-17-12-07-48--rag-sources--stage9-agent-b-parity--390x844--e23efc0--8afc24.png`
  - `docs/screenshots/2026-02-17-12-07-49--github--stage9-agent-b-parity--1920x1080--e23efc0--fcf121.png`
  - `docs/screenshots/2026-02-17-12-07-50--github--stage9-agent-b-parity--390x844--e23efc0--924946.png`
  - `docs/screenshots/2026-02-17-12-07-51--jira--stage9-agent-b-parity--1920x1080--e23efc0--96befd.png`
  - `docs/screenshots/2026-02-17-12-07-52--jira--stage9-agent-b-parity--390x844--e23efc0--aaf9aa.png`
  - `docs/screenshots/2026-02-17-12-07-53--confluence--stage9-agent-b-parity--1920x1080--e23efc0--5377f4.png`
  - `docs/screenshots/2026-02-17-12-07-54--confluence--stage9-agent-b-parity--390x844--e23efc0--b75257.png`
  - `docs/screenshots/2026-02-17-12-07-55--chroma-collections--stage9-agent-b-parity--1920x1080--e23efc0--750ca4.png`
  - `docs/screenshots/2026-02-17-12-07-56--chroma-collections--stage9-agent-b-parity--390x844--e23efc0--052636.png`
  - `docs/screenshots/2026-02-17-12-21-46--skills-new--stage9-agent-b-parity-extra--1920x1080--59fefe7--1aa6ff.png`
  - `docs/screenshots/2026-02-17-12-22-04--skills-new--stage9-agent-b-parity-extra--390x844--59fefe7--870c63.png`
  - `docs/screenshots/2026-02-17-12-21-46--skills-import--stage9-agent-b-parity-extra--1920x1080--59fefe7--45b83b.png`
  - `docs/screenshots/2026-02-17-12-22-04--skills-import--stage9-agent-b-parity-extra--390x844--59fefe7--00f1e7.png`
  - `docs/screenshots/2026-02-17-12-21-46--scripts-new--stage9-agent-b-parity-extra--1920x1080--59fefe7--dbcf12.png`
  - `docs/screenshots/2026-02-17-12-22-04--scripts-new--stage9-agent-b-parity-extra--390x844--59fefe7--317384.png`
  - `docs/screenshots/2026-02-17-12-21-56--models-new--stage9-agent-b-parity-extra--1920x1080--59fefe7--718903.png`
  - `docs/screenshots/2026-02-17-12-22-15--models-new--stage9-agent-b-parity-extra--390x844--59fefe7--14a892.png`
  - `docs/screenshots/2026-02-17-12-21-56--mcps-new--stage9-agent-b-parity-extra--1920x1080--59fefe7--68fa29.png`
  - `docs/screenshots/2026-02-17-12-22-15--mcps-new--stage9-agent-b-parity-extra--390x844--59fefe7--44433a.png`
  - `docs/screenshots/2026-02-17-12-21-56--rag-source-new--stage9-agent-b-parity-extra--1920x1080--59fefe7--83708f.png`
  - `docs/screenshots/2026-02-17-12-22-15--rag-source-new--stage9-agent-b-parity-extra--390x844--59fefe7--27e509.png`

### Baseline Capture Completion
- [x] Wave 1 baseline set captured (desktop + mobile).
- [x] Wave 2 baseline set captured (desktop + mobile).
- [x] Wave 3 baseline set captured (desktop + mobile).
- [x] Wave 4 baseline set captured (desktop + mobile).
- [x] Wave 5 baseline set captured (desktop + mobile).
- [x] Wave 6 baseline set captured (desktop + mobile).
- [x] Wave 7 baseline set captured (desktop + mobile).

### Visual Signoff by Route Family
- [x] Wave 1 visual signoff complete (Agent B) (`/overview`, `/parity-checklist`, `/api-diagnostics`, `/chat/activity`, `/chat/threads/:threadId`).
- [x] Wave 2 visual signoff complete (Agent A) (`/agents*`, `/runs*`, `/quick`, `/nodes*`, `/execution-monitor`).
- [x] Wave 3 visual signoff complete (`/plans*`, `/milestones*`, `/memories*`, `/task-templates*`).
- [x] Wave 4 visual signoff complete (`/flowcharts*` list/detail/edit/history/run).
- [x] Wave 5 visual signoff complete (Agent B) (`/skills*`, `/scripts*`, `/attachments*`, `/models*`, `/mcps*`).
- [x] Wave 6 visual signoff complete (Agent A) (`/settings/core`, `/settings/provider*`, `/settings/runtime*`, `/settings/chat`, `/settings/integrations*`).
- [x] Wave 7 visual signoff complete (Agent B) (`/rag*`, `/github*`, `/jira*`, `/confluence`, `/chroma*`).

### Behavioral Signoff by Route Family
- [x] Wave 1 behavior signoff complete (Agent B) (navigation, read-only flows, loading/error states).
- [x] Wave 2 behavior signoff complete (Agent A) (execution lifecycle, status updates, row/action interactions).
- [x] Wave 3 behavior signoff complete (CRUD and plan stage/task mutation behavior).
- [x] Wave 4 behavior signoff complete (graph/runtime/history and node utility behavior).
- [x] Wave 5 behavior signoff complete (Agent B) (asset CRUD/import/export/detail behavior).
- [x] Wave 6 behavior signoff complete (Agent A) (settings mutation/validation and provider/integration behavior).
- [x] Wave 7 behavior signoff complete (Agent B) (RAG source lifecycle, chat behavior, external workspace drill-down behavior).

### Cross-Cutting Hard Gates
- [ ] List row-click behavior parity confirmed (`table-row-link`, interactive element exclusions) across all list views.
- [ ] Icon-only action behavior parity confirmed (edit/delete/play buttons, confirmations, disable/busy behavior).
- [ ] Mutation feedback parity confirmed (success banners, validation errors, failed request states).
- [ ] Realtime/long-running feedback parity confirmed (runs/nodes/flowcharts/RAG quick index).
- [ ] Responsive parity confirmed (desktop + mobile layout and overflow behavior) across all waves.
