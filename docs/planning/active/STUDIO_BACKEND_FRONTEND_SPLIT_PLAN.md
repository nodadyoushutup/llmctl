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
- [x] Stage 6: Split containerization for backend/frontend in Docker Compose.
- [x] Stage 7: Kubernetes resource split (deployments/services/config) for backend/frontend.
- [x] Stage 8: Kubernetes ingress and overlay updates for `/web` and `/api`.
- [x] Stage 9: Full-parity gate verification and backend GUI decommission.
- [x] Stage 10: Automated Testing.
- [x] Stage 11: Docs Updates.

## Stage 2 - Backend Rename and Path Migration
- [ ] Move Flask app from `app/llmctl-studio` to `app/llmctl-studio-backend`.
- [ ] Update all path references across runtime/build tooling:
- [ ] Update `docker/docker-compose.yml` bind mounts and build Dockerfile path.
- [ ] Update `kubernetes-overlays/minikube-live-code/studio-live-code-patch.yaml` mount paths.
- [ ] Update script paths and any direct references in repo configs and docs.
- [ ] Validate backend still boots after rename with no behavior change.
- [ ] Acceptance criteria: backend starts successfully from renamed path, and no stale `app/llmctl-studio` runtime dependency remains.

## Stage 3 - Backend API Boundary Hardening (`/api`) with Legacy GUI Retained
- [ ] Introduce or enforce `/api` prefix for backend programmatic endpoints used by React.
- [ ] Keep existing server-rendered GUI routes active during parity migration (temporary coexistence mode).
- [ ] Ensure backend session/auth/CSRF behavior remains correct for both legacy GUI and React API calls.
- [ ] Update Socket.IO/API path configuration to remain backend-reachable through ingress path strategy.
- [ ] Acceptance criteria: API traffic is cleanly namespaced under `/api`, and legacy GUI continues functioning until Stage 9 cleanup.

## Stage 4 - Frontend App Bootstrap (`app/llmctl-studio-frontend`)
- [ ] Create Vite + React app using `.jsx` source files in `app/llmctl-studio-frontend`.
- [ ] Add frontend env model for backend base URL/path (`/api`) and realtime endpoint settings.
- [ ] Implement base app shell, router, and shared layout/navigation skeleton.
- [ ] Add shared HTTP client utilities with consistent error/auth handling.
- [ ] Acceptance criteria: frontend app builds/runs and can call backend `/api` health/read endpoints.

## Stage 5 - Frontend Full-Parity Migration Waves
- [ ] Build a page-by-page parity checklist derived from current Flask template routes.
- [ ] Migrate all existing GUI sections to React in waves (dashboard/list/detail/forms/settings/chat/flowcharts/rag/etc.).
- [ ] Preserve behavior parity for mutations, validation, long-running task feedback, and realtime updates.
- [ ] Keep backend template UI as fallback until all parity checks are complete.
- [ ] Acceptance criteria: every legacy GUI page/flow has an equivalent React implementation and passes parity checklist.

## Stage 6 - Split Containerization for Backend/Frontend
- [ ] Backend container:
- [ ] Ensure Gunicorn remains default via env vars with temporary `LLMCTL_STUDIO_USE_GUNICORN=false` fallback path.
- [ ] Update backend Dockerfile location/path references after rename.
- [ ] Frontend container:
- [ ] Add Dockerfile for Vite/React build and static serving strategy.
- [ ] Add `llmctl-studio-frontend` service to `docker/docker-compose.yml`.
- [ ] Wire frontend-to-backend networking in Compose using `/api` routing assumptions.
- [ ] Acceptance criteria: `docker compose` can run backend and frontend as separate containers with working API calls.

## Stage 7 - Kubernetes Resource Split (Backend + Frontend)
- [ ] Add backend-specific manifests (deployment/service/config/secret wiring) under new naming.
- [ ] Add frontend-specific manifests (deployment/service and frontend runtime config as needed).
- [ ] Update `kubernetes/kustomization.yaml` to include both backend and frontend resources.
- [ ] Keep existing dependent services (redis/postgres/chromadb/pgadmin/rbac/pvc) correctly referenced.
- [ ] Acceptance criteria: both pods/services deploy cleanly and are independently restartable/scalable.

## Stage 8 - Kubernetes Ingress and Overlay Updates (`/web`, `/api`)
- [ ] Add ingress manifest routing same host:
- [ ] `/web` -> `llmctl-studio-frontend` service.
- [ ] `/api` -> `llmctl-studio-backend` service.
- [ ] Update backend/frontend env vars for forwarded headers, external URL scheme, and API/realtime pathing behind ingress.
- [ ] Update Minikube live-code overlay to mount renamed backend paths and frontend code paths.
- [ ] Acceptance criteria: one host serves frontend at `/web` and backend API at `/api` with stable routing in cluster.

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
- [ ] Update Docker Compose and Kubernetes usage docs for dual-container Studio deployment.
- [ ] Update Sphinx/Read the Docs content to reflect frontend/backend separation and ingress paths (`/web`, `/api`).
- [ ] Update any developer workflow docs (including Minikube live-code overlay instructions).
- [ ] Acceptance criteria: documentation is consistent with implemented architecture and deployment workflow.
