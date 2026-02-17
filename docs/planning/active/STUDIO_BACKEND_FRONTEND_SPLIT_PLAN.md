# Studio Backend/Frontend Split Plan

Goal: split Studio into separate backend/frontend services for Kubernetes deployment:
- Backend: existing Flask app (later renamed to `app/llmctl-studio-backend`).
- Frontend: new `app/llmctl-studio-frontend` Vite/React (`.jsx`) app.
- Keep existing backend-rendered GUI until React frontend reaches functional parity and is validated.

## Stage 0 - Requirements Gathering
- [x] Capture initial objective and constraints from the request.
- [x] Confirm final naming/path conventions for backend/frontend app directories and container names.
- [x] Confirm frontend-to-backend integration model (API-only, backend-served static build, or separate host).
- [x] Confirm phased rollout and cutover criteria for removing backend GUI templates.
- [x] Confirm Kubernetes resource topology (deployments/services/ingress split and host/path routing).
- [x] Confirm Gunicorn runtime/env-var requirements and acceptable temporary fallback behavior.
- [x] Confirm requirements are complete and approved to start Stage 1.

## Stage 0 - Interview Notes
- [x] Primary goal is to run two Kubernetes containers/services: one backend and one frontend.
- [x] Backend should remain the existing Flask implementation during transition.
- [x] Frontend should be introduced as a new Vite/React app using `.jsx`.
- [x] Legacy Flask GUI must remain available until React parity is confirmed.
- [x] Post-parity cleanup should remove backend GUI and rename backend package/layout accordingly.
- [x] Kubernetes manifests/overlays must be updated as part of the split.
- [x] Backend should run with Gunicorn configured via Kubernetes env vars where feasible.
- [x] Hosting model selected: same host with path-based routing, using `/web` for frontend and `/api` for backend.
- [x] Naming/path decision: rename backend immediately to `app/llmctl-studio-backend` and create frontend at `app/llmctl-studio-frontend`; target container identities align with `llmctl-studio-backend` and `llmctl-studio-frontend`.
- [x] Cutover gate: remove Flask-rendered GUI only after full parity of all existing GUI routes/pages in React.
- [x] Kubernetes topology: separate backend/frontend Deployments and Services, routed by a single Ingress using `/web` and `/api` paths on the same host.
- [x] Gunicorn policy: Gunicorn is preferred and configured via env vars in Kubernetes, with temporary fallback to Flask (`USE_GUNICORN=false`) allowed only if blockers appear.

## Stage 1 - Code Planning
- [x] Translate approved Stage 0 requirements into Stage 2 through Stage X execution stages.
- [x] Define concrete file-level scope, dependency order, and acceptance criteria per stage.
- [x] Ensure the final two stages are `Automated Testing` and `Docs Updates`.

## Stage 1 - Execution Order
- [x] Stage 2: Backend rename and path migration.
- [x] Stage 3: Backend API boundary hardening (`/api`) while keeping legacy GUI working.
- [x] Stage 4: Frontend app bootstrap (`app/llmctl-studio-frontend`) and API client foundation.
- [x] Stage 5: Frontend parity migration waves (all current GUI pages/features).
- [x] Stage 6: Split containerization for backend/frontend in Kubernetes-only runtime mode.
- [x] Stage 7: Kubernetes resource split (deployments/services/config) for backend/frontend.
- [x] Stage 8: Kubernetes ingress and overlay updates for `/web` and `/api`.
- [x] Stage 9: Full-parity gate verification and backend GUI decommission.
- [x] Stage 10: Automated Testing.
- [x] Stage 11: Docs Updates.

## Stage 2 - Backend Rename and Path Migration
- [x] Move Flask app from `app/llmctl-studio` to `app/llmctl-studio-backend`.
- [x] Update all path references across runtime/build tooling:
- [x] Update runtime bind-mount/build wiring paths for the renamed backend target.
- [x] Update `kubernetes/llmctl-studio/overlays/dev/studio-live-code-patch.yaml` mount paths.
- [x] Update script paths and any direct references in repo configs and docs.
- [x] Validate backend still boots after rename with no behavior change.
- [x] Acceptance criteria: backend starts successfully from renamed path, and no stale `app/llmctl-studio` runtime dependency remains.

## Stage 3 - Backend API Boundary Hardening (`/api`) with Legacy GUI Retained
- [x] Introduce or enforce `/api` prefix for backend programmatic endpoints used by React.
- [x] Keep existing server-rendered GUI routes active during parity migration (temporary coexistence mode).
- [x] Ensure backend session/auth/CSRF behavior remains correct for both legacy GUI and React API calls.
- [x] Update Socket.IO/API path configuration to remain backend-reachable through ingress path strategy.
- [x] Acceptance criteria: API traffic is cleanly namespaced under `/api`, and legacy GUI continues functioning until Stage 9 cleanup.

## Stage 4 - Frontend App Bootstrap (`app/llmctl-studio-frontend`)
- [x] Create Vite + React app using `.jsx` source files in `app/llmctl-studio-frontend`.
- [x] Add frontend env model for backend base URL/path (`/api`) and realtime endpoint settings.
- [x] Implement base app shell, router, and shared layout/navigation skeleton.
- [x] Add shared HTTP client utilities with consistent error/auth handling.
- [x] Acceptance criteria: frontend app builds/runs and can call backend `/api` health/read endpoints.

## Stage 5 - Frontend Full-Parity Migration Waves
- [x] Build a page-by-page parity checklist derived from current Flask template routes.
- [x] Migrate all existing GUI sections to React in waves (dashboard/list/detail/forms/settings/chat/flowcharts/rag/etc.).
- [x] Preserve behavior parity for mutations, validation, long-running task feedback, and realtime updates.
- [x] Keep backend template UI as fallback until all parity checks are complete.
- [x] Acceptance criteria: every legacy GUI page/flow has equivalent React-native or React-bridge coverage and passes the Stage 5 parity checklist.

## Stage 5 - Wave 1 Progress
- [x] Add parity tracker view and checklist data source in React (`/parity-checklist`).
- [x] Migrate chat activity read flow to React (`/chat/activity` via `/api/chat/activity`).
- [x] Migrate chat thread detail read flow to React (`/chat/threads/:threadId` via `/api/chat/threads/:threadId`).
- [x] Continue Wave 2+ section migrations until full checklist parity is complete.

## Stage 5 - Wave 2 Progress
- [x] Add execution monitor route in React (`/execution-monitor`) with legacy fallback links.
- [x] Wire run detail read flow to `/api/runs/:id`.
- [x] Wire node status read flow to `/api/nodes/:id/status`.
- [x] Expand Wave 2 to full Agents/Runs/Quick+Nodes parity through React-native plus legacy bridge coverage.

## Stage 6 - Split Containerization for Backend/Frontend (Kubernetes-only)
- [x] Backend container:
- [x] Ensure Gunicorn remains default via env vars with temporary `LLMCTL_STUDIO_USE_GUNICORN=false` fallback path.
- [x] Update backend Dockerfile location/path references after rename.
- [x] Frontend container:
- [x] Add Dockerfile for Vite/React build and static serving strategy.
- [x] Add Kubernetes deployment/service wiring for `llmctl-studio-frontend`.
- [x] Wire frontend-to-backend networking in Kubernetes using `/api` reverse proxy assumptions.
- [x] Acceptance criteria: Kubernetes can run backend and frontend as separate workloads with working API calls.

## Stage 7 - Kubernetes Resource Split (Backend + Frontend)
- [x] Add backend-specific manifests (deployment/service/config/secret wiring) under new naming.
- [x] Add frontend-specific manifests (deployment/service and frontend runtime config as needed).
- [x] Update `kubernetes/kustomization.yaml` to include both backend and frontend resources.
- [x] Keep existing dependent services (redis/postgres/chromadb/pgadmin/rbac/pvc) correctly referenced.
- [x] Acceptance criteria: both pods/services deploy cleanly and are independently restartable/scalable.

## Stage 8 - Kubernetes Ingress and Overlay Updates (`/web`, `/api`)
- [x] Add ingress manifest routing same host:
- [x] `/web` -> `llmctl-studio-frontend` service.
- [x] `/api` -> `llmctl-studio-backend` service.
- [x] Update backend/frontend env vars for forwarded headers, external URL scheme, and API/realtime pathing behind ingress.
- [x] Update Minikube live-code overlay to mount renamed backend paths and frontend code paths.
- [x] Acceptance criteria: one host serves frontend at `/web` and backend API at `/api` with stable routing in cluster.

## Stage 8 - Validation Notes
- [x] Verified backend/frontend deployments are healthy with `kubectl -n llmctl rollout status deploy/llmctl-studio-backend` and `kubectl -n llmctl rollout status deploy/llmctl-studio-frontend`.
- [x] Verified split services are active as `NodePort` resources (`llmctl-studio-backend`, `llmctl-studio-frontend`).
- [x] Verified routing on one host: `http://192.168.49.2:30157/web/` returns frontend shell and `http://192.168.49.2:30157/api/health` returns `{"ok":true,"service":"llmctl-studio-backend"}`.

## Stage 9 - Full-Parity Gate and Backend GUI Decommission
- [x] Improve bridge routing compatibility so legacy absolute-path navigation works from `/web` bridge mode.
- [ ] Execute final parity audit against all legacy backend GUI pages/routes.
- [ ] Remove backend template-rendered GUI routes/templates/static assets after parity is confirmed.
- [ ] Keep backend focused on API/realtime/service responsibilities only.
- [ ] Perform naming cleanup and dead-code removal linked to retired GUI paths.
- [ ] Acceptance criteria: Flask backend no longer serves GUI pages, React frontend is the only user-facing UI, and parity signoff is complete.

## Stage 9 - Bridge Compatibility Notes
- [x] Updated frontend routing so `/web` lands on legacy `/overview` bridge by default and keeps migration-native pages at explicit routes (for example `/web/migration`).
- [x] Updated frontend Nginx runtime so legacy root paths (for example `/agents`, `/settings/*`, `/runs`, `/chat`) are proxied to backend, restoring legacy in-app navigation behavior when running through frontend NodePort.
- [x] Added frontend server-side redirects for `/` and `/web` to `/web/overview` and set `index.html` `Cache-Control: no-store` to avoid stale bootstrap bundles in browsers.

## Stage 10 - Automated Testing
- [x] Add/update backend tests for API prefixing, auth/session expectations, and realtime route/path behavior.
- [x] Add/update frontend tests for routing, API integration, and critical user flows.
- [x] Add/update integration tests that exercise split deployment behavior.
- [x] Run automated test suite(s) and fix regressions before closure.
- [x] Acceptance criteria: automated tests pass for backend, frontend, and split integration paths.

## Stage 10 - Validation Notes
- [x] Added backend Stage 10 tests at `app/llmctl-studio-backend/tests/test_backend_split_stage10.py` covering API route compatibility, Socket.IO API-prefix aliasing, and API session cookie roundtrip behavior.
- [x] Added split deployment integration tests at `app/llmctl-studio-backend/tests/test_split_deployment_stage10.py` covering ingress path-to-service mappings and frontend nginx split-proxy contract.
- [x] Added frontend automated tests with Vitest at:
- [x] `app/llmctl-studio-frontend/src/App.routing.test.jsx`
- [x] `app/llmctl-studio-frontend/src/lib/httpClient.test.js`
- [x] `app/llmctl-studio-frontend/src/lib/studioApi.test.js`
- [x] Executed checks:
- [x] `.venv/bin/python -m unittest app/llmctl-studio-backend/tests/test_backend_api_boundary_stage3.py app/llmctl-studio-backend/tests/test_socket_proxy_gunicorn_stage9.py app/llmctl-studio-backend/tests/test_backend_split_stage10.py app/llmctl-studio-backend/tests/test_split_deployment_stage10.py`
- [x] `.venv/bin/python -m unittest app/llmctl-studio-backend/tests/test_backend_split_stage10.py app/llmctl-studio-backend/tests/test_split_deployment_stage10.py`
- [x] `cd app/llmctl-studio-frontend && npm run lint`
- [x] `cd app/llmctl-studio-frontend && npm test`
- [x] `cd app/llmctl-studio-frontend && npm run build`

## Stage 11 - Docs Updates
- [ ] Update docs for new app structure (`app/llmctl-studio-backend`, `app/llmctl-studio-frontend`).
- [ ] Update container build and Kubernetes usage docs for dual-container Studio deployment.
- [ ] Update Sphinx/Read the Docs content to reflect frontend/backend separation and ingress paths (`/web`, `/api`).
- [ ] Update any developer workflow docs (including Minikube live-code overlay instructions).
- [ ] Acceptance criteria: documentation is consistent with implemented architecture and deployment workflow.

---

## React-Only Completion Plan (Current Active Scope)

This section supersedes bridge-first execution for all remaining UI migration work.  
Objective: complete full React parity, then remove legacy Jinja/UI paths with no bridge fallback.

## Stage 0 - Requirements Gathering (React-Only Addendum)
- [x] Confirm cutover strategy: parity-first cutover, then hard switch.
- [x] Confirm legacy policy after parity: remove all backend Jinja/UI routes and templates immediately.
- [x] Confirm migration order: core ops first.
- [x] Confirm parity bar: functional parity with selective redesign allowed.
- [x] Confirm execution approval to proceed with planning before implementation.

## Stage 0 - Interview Notes (React-Only Addendum)
- [x] User selected parity-first cutover (no big-bang cut now).
- [x] User selected hard removal of legacy UI after parity is complete.
- [x] User selected migration order: Core ops first.
- [x] User selected parity bar: functional parity + selective redesign.
- [x] User requested plan update first so implementation progress can be tracked cleanly.

## Stage 1 - Code Planning (React-Only Execution Design)
- [x] Define execution stages for remaining React migration.
- [x] Define route/domain tracker to mark what is built and verified.
- [x] Define cutover gate criteria before deleting legacy UI.
- [x] Ensure final two stages are `Automated Testing` then `Docs Updates`.

## Stage 1 - Execution Order (React-Only)
- [x] Stage 2: Agents migration (full list/detail/create/edit/delete + role/priority/skill bindings).
- [x] Stage 3: Runs, quick tasks, and node execution surfaces.
- [x] Stage 4: Task templates, plans, milestones, and memories.
- [x] Stage 5: Flowcharts (editor, runtime, history, run detail, node operations).
- [ ] Stage 6: Settings, provider/runtime/chat config, and integrations.
- [ ] Stage 7: Skills, scripts, attachments, models, MCP servers.
- [ ] Stage 8: RAG pages and external tools surfaces (GitHub/Jira/Confluence/Chroma).
- [ ] Stage 9: React-only routing hardening and bridge decommission prep.
- [ ] Stage 10: Legacy backend GUI removal and backend API-only cleanup.
- [ ] Stage 11: Automated Testing.
- [ ] Stage 12: Docs Updates.

## React Baseline Already Implemented
- [x] Migration hub shell route (`/migration`).
- [x] Parity checklist route (`/parity-checklist`).
- [x] Chat activity route (`/chat/activity`).
- [x] Chat thread route (`/chat/threads/:threadId`).
- [x] Execution monitor route (`/execution-monitor`).
- [x] Backend/frontend split runtime (`/web` + `/api`) is already in place.

## Stage 2 - Agents Migration
- [x] Add/verify API contracts for agent list/detail/create/update/delete and related bindings.
- [x] Implement React routes/pages for agents list/detail/new/edit.
- [x] Implement React mutations for create/update/delete and relation updates.
- [x] Preserve list behavior requirements (clickable rows, interactive element exclusions, icon-only actions).
- [x] Mark Agents parity complete in tracker.

## Stage 3 - Runs, Quick Tasks, Nodes
- [x] Migrate `/runs` list/detail/new/edit to fully native React.
- [x] Migrate quick task and node status/task lifecycle flows.
- [x] Ensure long-running status and realtime feedback parity.
- [x] Mark Runs/Quick/Nodes parity complete in tracker.

## Stage 3 - Completion Notes
- [x] Added native React routes/pages for runs: `/runs`, `/runs/new`, `/runs/:runId`, `/runs/:runId/edit`.
- [x] Added native React routes/pages for nodes: `/nodes`, `/nodes/new`, `/nodes/:nodeId`.
- [x] Added native React route/page for quick tasks: `/quick`.
- [x] Added Stage 3 API client coverage and tests in frontend (`studioApi.js`, `studioApi.test.js`).
- [x] Added polling-based long-running feedback parity on run/node detail and active nodes list.
- [x] Updated parity tracker entries to mark Runs and Quick Tasks + Nodes as migrated.

## Stage 4 - Templates, Plans, Milestones, Memories
- [x] Migrate task templates list/detail/new/edit/delete.
- [x] Migrate plans and milestones CRUD/detail flows.
- [x] Migrate memories list/detail/new/edit/delete.
- [x] Mark domain parity complete in tracker.

## Stage 4 - Completion Notes
- [x] Added backend API-mode JSON coverage for plans, plan stages/tasks, milestones, memories, and task-template routes/mutations.
- [x] Added native React routes/pages for:
- [x] Plans: `/plans`, `/plans/new`, `/plans/:planId`, `/plans/:planId/edit`.
- [x] Milestones: `/milestones`, `/milestones/new`, `/milestones/:milestoneId`, `/milestones/:milestoneId/edit`.
- [x] Memories: `/memories`, `/memories/new`, `/memories/:memoryId`, `/memories/:memoryId/edit`.
- [x] Task templates: `/task-templates`, `/task-templates/new`, `/task-templates/:templateId`, `/task-templates/:templateId/edit`.
- [x] Updated parity tracker entries to mark Wave 3 domains as migrated.
- [x] Added icon-only React list actions for milestones and memories while keeping `table-row-link` navigation behavior.

## Stage 5 - Flowcharts
- [x] Migrate flowchart list/detail/new/edit.
- [x] Migrate node graph editing operations and connector behavior.
- [x] Migrate flowchart run/history/detail surfaces and actions.
- [x] Mark Flowcharts parity complete in tracker.

## Stage 5 - Completion Notes
- [x] Added native React routes/pages for `/flowcharts`, `/flowcharts/new`, `/flowcharts/:flowchartId`, `/flowcharts/:flowchartId/edit`.
- [x] Added native React history and run-detail routes/pages for `/flowcharts/:flowchartId/history`, `/flowcharts/:flowchartId/history/:runId`, and `/flowcharts/runs/:runId`.
- [x] Added frontend API client coverage for flowchart list/detail/new/edit/delete, graph read/write/validate, runtime/run/cancel, history/run detail, and node utility mutations.
- [x] Wired flowchart route coverage directly in React router/app nav (no flowchart bridge route dependency).
- [x] Updated parity tracker entries/docs to mark Wave 4 flowchart system as `Native React`.

## Stage 6 - Settings and Integrations
- [ ] Migrate settings core/provider/runtime/chat pages to React.
- [ ] Migrate integrations settings and validation UX.
- [ ] Preserve functional behavior for provider-specific controls and runtime flags.
- [ ] Mark Settings/Integrations parity complete in tracker.

## Stage 7 - Skills/Scripts/Attachments/Models/MCP
- [ ] Migrate skills management flows.
- [ ] Migrate scripts and attachments CRUD/detail flows.
- [ ] Migrate model and MCP server management pages.
- [ ] Mark these domains parity complete in tracker.

## Stage 8 - RAG and External Tools
- [ ] Migrate RAG chat and source management pages.
- [ ] Migrate GitHub/Jira/Confluence/Chroma surfaces to React.
- [ ] Preserve connectivity validation and error handling parity.
- [ ] Mark RAG/External parity complete in tracker.

## Stage 9 - React-Only Routing Hardening
- [ ] Remove React iframe bridge route usage from app router.
- [ ] Remove bridge-focused frontend navigation/runtime notes.
- [ ] Ensure unknown routes use React 404 handling.
- [ ] Verify all previously bridged routes are now native React routes.

## Stage 10 - Legacy Backend GUI Removal
- [ ] Delete backend template-rendered GUI route handlers.
- [ ] Delete backend Jinja templates and legacy static UI assets.
- [ ] Remove frontend nginx legacy route proxy fallback behavior.
- [ ] Keep backend focused on API/realtime/service responsibilities only.
- [ ] Validate no user-facing GUI route is served from Flask templates.

## Stage 10 - Hard Cutover Gate
- [ ] Every legacy page/flow has a native React equivalent.
- [ ] Every legacy mutation flow has React parity coverage.
- [ ] Realtime and long-running feedback parity is verified.
- [ ] Bridge/iframe fallback is removed from runtime behavior.
- [ ] Backend GUI template surface is removed.

## Stage 11 - Automated Testing
- [ ] Add/update backend API tests for all newly migrated domains.
- [ ] Add/update frontend route/component/API integration tests across migrated domains.
- [ ] Add/update split deployment integration tests for React-only runtime.
- [ ] Run automated suite and resolve regressions.
- [ ] Acceptance criteria: backend, frontend, and split integration suites pass.

## Stage 12 - Docs Updates
- [ ] Update docs to declare React as the only Studio UI.
- [ ] Remove bridge/legacy UI documentation and migration-temporary guidance.
- [ ] Update Sphinx/Read the Docs architecture and route documentation.
- [ ] Update developer workflows for React-only Studio operations.
- [ ] Acceptance criteria: docs match final React-only architecture and runtime.

## React Domain Tracker
- [x] Agents
- [x] Runs
- [x] Quick Tasks / Nodes
- [x] Task Templates
- [x] Plans
- [x] Milestones
- [x] Memories
- [x] Flowcharts
- [ ] Settings Core/Provider
- [ ] Settings Runtime/Chat
- [ ] Integrations
- [ ] Skills
- [ ] Scripts
- [ ] Attachments
- [ ] Models
- [ ] MCP Servers
- [ ] RAG Chat/Sources
- [ ] External Tools (GitHub/Jira/Confluence/Chroma)
