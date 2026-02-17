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
- [x] Update `kubernetes-overlays/minikube-live-code/studio-live-code-patch.yaml` mount paths.
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
- [ ] Execute final parity audit against all legacy backend GUI pages/routes.
- [ ] Remove backend template-rendered GUI routes/templates/static assets after parity is confirmed.
- [ ] Keep backend focused on API/realtime/service responsibilities only.
- [ ] Perform naming cleanup and dead-code removal linked to retired GUI paths.
- [ ] Acceptance criteria: Flask backend no longer serves GUI pages, React frontend is the only user-facing UI, and parity signoff is complete.

## Stage 10 - Automated Testing
- [ ] Add/update backend tests for API prefixing, auth/session expectations, and realtime route/path behavior.
- [ ] Add/update frontend tests for routing, API integration, and critical user flows.
- [ ] Add/update integration tests that exercise split deployment behavior.
- [ ] Run automated test suite(s) and fix regressions before closure.
- [ ] Acceptance criteria: automated tests pass for backend, frontend, and split integration paths.

## Stage 11 - Docs Updates
- [ ] Update docs for new app structure (`app/llmctl-studio-backend`, `app/llmctl-studio-frontend`).
- [ ] Update container build and Kubernetes usage docs for dual-container Studio deployment.
- [ ] Update Sphinx/Read the Docs content to reflect frontend/backend separation and ingress paths (`/web`, `/api`).
- [ ] Update any developer workflow docs (including Minikube live-code overlay instructions).
- [ ] Acceptance criteria: documentation is consistent with implemented architecture and deployment workflow.
