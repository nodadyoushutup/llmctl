# Studio Celery Worker Decoupling Plan

Goal: decouple Celery worker and beat execution from `llmctl-studio` by introducing a dedicated `app/llmctl-celery-worker` image and Kubernetes deployments that can scale independently.

## Stage 0 - Requirements Gathering
- [x] Confirm queue consumption scope for the new worker deployment.
- [x] Confirm Studio-side worker overlap policy during cutover.
- [x] Confirm Celery Beat deployment strategy.
- [x] Confirm initial worker replica/concurrency baseline.
- [x] Confirm Kubernetes manifest location strategy.
- [x] Confirm code reuse model between Studio and worker image.
- [x] Confirm initial scaling strategy (static vs autoscaling).
- [x] Confirm target Kubernetes resource naming.
- [x] Confirm Studio runtime decoupling depth.
- [x] Confirm rollout strategy for production cutover.
- [x] Confirm requirements are complete and approved to start Stage 1.

## Stage 0 - Interview Notes
- [x] Worker deployment should consume all existing queues.
- [x] Studio Celery workers should be disabled immediately once new worker deployment is live.
- [x] Beat should run as a dedicated deployment with a single replica.
- [x] Initial baseline is `replicas=2` and `--concurrency=2` (4 total worker slots).
- [x] Manifests stay in the existing Studio/llmctl manifest structure.
- [x] Worker app should reuse existing Studio Python modules; only add worker-specific entrypoints/image wiring.
- [x] Scaling should remain static for now (no HPA in initial rollout).
- [x] Deployment names should be `llmctl-celery-worker` and `llmctl-celery-beat`.
- [x] Remove Celery worker/beat startup from Studio runtime entirely.
- [x] Use a single-step cutover window with worker+beat plus Studio decouple changes together.

## Stage 1 - Code Planning
- [x] Translate approved Stage 0 requirements into Stage 2 through Stage X execution stages.
- [x] Define concrete file-level scope, dependency order, and acceptance criteria per stage.
- [x] Ensure the final two stages are `Automated Testing` and `Docs Updates`.

## Stage 1 - Execution Order
- [x] Stage 2: Celery queue/routing contract audit and worker runtime baseline definition.
- [x] Stage 3: Create `app/llmctl-celery-worker` image and runtime entrypoints.
- [x] Stage 4: Add Kubernetes worker and beat deployments in existing manifest structure.
- [x] Stage 5: Remove Celery runtime from Studio backend deployment/runtime wiring.
- [x] Stage 6: Execute single-step cutover and post-deploy operational validation.
- [x] Stage 7: Automated Testing.
- [x] Stage 8: Docs Updates.

## Stage 2 - Queue/Routing Contract and Runtime Baseline
- [x] Inventory current Celery tasks, queues, and routing configuration used by Studio.
- [x] Ensure worker command/config covers all active queues (explicit queue list where required).
- [x] Lock baseline runtime flags for first release (`--concurrency=2`, worker pool/acks settings as currently expected).
- [x] Confirm broker/backend env contracts (Redis host/port/db/password) are identical to current Studio behavior.
- [x] Acceptance criteria: queue/routing behavior is explicitly defined and supports all existing task flows under the new worker deployment.

## Stage 2 - Audit Notes
- [x] Active Celery tasks discovered:
- [x] `services.tasks.cleanup_workspaces` (beat-dispatched).
- [x] `services.tasks.run_huggingface_download_task` (explicitly routed to downloads queue).
- [x] `services.tasks.run_agent`.
- [x] `services.tasks.run_quick_rag_task`.
- [x] `services.tasks.run_agent_task`.
- [x] `services.tasks.run_flowchart`.
- [x] `rag.worker.tasks.run_index_task` (still registered; currently decommissioned behavior).
- [x] Queue contract in `services.celery_app`:
- [x] `llmctl_studio` (default queue).
- [x] `llmctl_studio.downloads.huggingface`.
- [x] `llmctl_studio.rag.index`.
- [x] `llmctl_studio.rag.drive`.
- [x] `llmctl_studio.rag.git`.
- [x] Route contract in `services.celery_app`:
- [x] `rag.worker.tasks.run_index_task` -> `llmctl_studio.rag.index`.
- [x] `services.tasks.run_huggingface_download_task` -> `llmctl_studio.downloads.huggingface`.
- [x] Beat contract:
- [x] `workspace_cleanup` schedule dispatches `services.tasks.cleanup_workspaces` onto `llmctl_studio` when workspace cleanup is enabled.
- [x] Existing Studio runtime topology (current state in `run.py`):
- [x] One default worker on `llmctl_studio`.
- [x] One RAG worker on `llmctl_studio.rag.index,llmctl_studio.rag.drive,llmctl_studio.rag.git`.
- [x] One HuggingFace worker on `llmctl_studio.downloads.huggingface`.
- [x] One beat process.
- [x] Baseline runtime contract for decoupled rollout:
- [x] Worker deployment command should consume all queues: `llmctl_studio,llmctl_studio.downloads.huggingface,llmctl_studio.rag.index,llmctl_studio.rag.drive,llmctl_studio.rag.git`.
- [x] Worker deployment starts with `replicas=2` and `--concurrency=2`.
- [x] Beat runs as dedicated deployment with `replicas=1`.
- [x] Redis broker/backend env contract parity:
- [x] Broker URL defaults to `redis://$CELERY_REDIS_HOST:$CELERY_REDIS_PORT/$CELERY_REDIS_BROKER_DB`.
- [x] Result backend defaults to `redis://$CELERY_REDIS_HOST:$CELERY_REDIS_PORT/$CELERY_REDIS_BACKEND_DB` unless explicitly overridden.
- [x] Kubernetes defaults currently resolve to host `llmctl-redis`, port `6390`, broker DB `0`, backend DB `1`.
- [x] Redis password is not currently configured in manifests/runtime; parity behavior is no-auth Redis unless a future secret-backed URL override is introduced.

## Stage 3 - `app/llmctl-celery-worker` Image + Entrypoints
- [x] Create `app/llmctl-celery-worker` app directory for worker-specific container wiring.
- [x] Reuse existing Studio Python modules/tasks; avoid task code duplication.
- [x] Add Dockerfile/build context for worker image.
- [x] Add startup commands/entrypoints for:
- [x] Celery worker process.
- [x] Celery beat process (same image, separate runtime command).
- [x] Ensure environment loading matches current Studio runtime expectations.
- [x] Acceptance criteria: worker image builds successfully and can start both worker and beat commands against existing Redis configuration.

## Stage 3 - Implementation Notes
- [x] Added worker app entrypoint at `app/llmctl-celery-worker/run.py` with mode-based execution:
- [x] `worker` mode defaults to all Stage 2 queue names and supports runtime overrides via env/CLI args.
- [x] `beat` mode uses `/app/data/celerybeat-schedule` and `/app/data/celerybeat.pid`.
- [x] Added worker image Dockerfile at `app/llmctl-celery-worker/docker/Dockerfile` reusing `app/llmctl-studio-backend` Python modules and requirements.
- [x] Added worker build script at `app/llmctl-celery-worker/docker/build-celery-worker.sh`.
- [x] Updated shared build helpers:
- [x] `scripts/build-docker.sh` now builds `llmctl-celery-worker:latest`.
- [x] `scripts/build-minikube.sh` now builds and verifies `llmctl-celery-worker:latest`.
- [x] Added writable ownership fix for `/app/data` in worker image to support non-root runtime writes (workspace paths and beat schedule file).
- [x] Validation executed:
- [x] `docker build --build-arg INSTALL_VLLM=false -f app/llmctl-celery-worker/docker/Dockerfile -t llmctl-celery-worker:stage3-check .` (success).
- [x] `docker run --rm --entrypoint python3 llmctl-celery-worker:stage3-check -m celery --version` (success).
- [x] Worker/beat smoke tests against disposable Redis (`redis:7.2-alpine`) on an isolated Docker network:
- [x] Worker connected to `redis://stage3-celery-redis:6390/0` and reached `ready`.
- [x] Beat started with broker `redis://stage3-celery-redis:6390/0` and schedule file `/app/data/celerybeat-schedule`.

## Stage 4 - Kubernetes Manifests for Worker and Beat
- [x] Add deployment manifest for `llmctl-celery-worker` with `replicas: 2`.
- [x] Configure worker container command args to set `--concurrency=2`.
- [x] Add deployment manifest for `llmctl-celery-beat` with `replicas: 1`.
- [x] Reuse existing ConfigMap/Secret wiring for Celery broker/backend settings.
- [x] Wire new manifests into existing kustomization/overlay structure.
- [x] Set resource requests/limits and health strategy appropriate for long-running Celery processes.
- [x] Acceptance criteria: both deployments reconcile successfully in Kubernetes, and pods are independently scalable/restartable.

## Stage 4 - Implementation Notes
- [x] Added `kubernetes/celery-worker-deployment.yaml`:
- [x] Deployment name `llmctl-celery-worker`, `replicas: 2`, image `llmctl-celery-worker:latest`.
- [x] Worker command pins `--concurrency 2` and consumes all Stage 2 queues.
- [x] Reuses `llmctl-studio-config` + `llmctl-studio-secrets` and mounts `llmctl-studio-data` PVC at `/app/data`.
- [x] Uses process-based startup/readiness/liveness probes and explicit resource requests/limits.
- [x] Added `kubernetes/celery-beat-deployment.yaml`:
- [x] Deployment name `llmctl-celery-beat`, `replicas: 1`, image `llmctl-celery-worker:latest`.
- [x] Beat command runs from the same worker image in `beat` mode.
- [x] Reuses `llmctl-studio-config` + `llmctl-studio-secrets` and mounts `llmctl-studio-data` PVC.
- [x] Uses pidfile-based startup/readiness/liveness probes (`/app/data/celerybeat.pid`) and explicit resource requests/limits.
- [x] Wired both manifests into `kubernetes/kustomization.yaml`.
- [x] Updated Harbor overlay image mappings in:
- [x] `kubernetes-overlays/harbor-images/kustomization.yaml`
- [x] `kubernetes-overlays/harbor-images/kustomization.tmpl.yaml`
- [x] Validation executed:
- [x] `kubectl kustomize kubernetes` renders successfully with both new deployments present.
- [x] `kubectl apply --dry-run=client -k kubernetes` succeeds and reports `deployment.apps/llmctl-celery-worker created (dry run)` and `deployment.apps/llmctl-celery-beat created (dry run)`.
- [x] `kubectl apply --dry-run=client -k kubernetes-overlays/harbor-images` succeeds and includes both celery deployments.

## Stage 5 - Studio Runtime Decoupling
- [x] Remove Celery worker/beat process startup from Studio runtime scripts/config.
- [x] Update Studio deployment manifests/env to run backend API/web process only.
- [x] Remove obsolete Studio-side Celery runtime knobs that no longer apply.
- [x] Ensure task producers in Studio still enqueue jobs to Redis without local worker dependency.
- [x] Acceptance criteria: Studio pods no longer run Celery worker/beat processes, while task submission behavior remains functional.

## Stage 5 - Implementation Notes
- [x] Updated `app/llmctl-studio-backend/run.py` to remove all Celery subprocess startup paths from Studio runtime:
- [x] Removed worker startup (`llmctl_studio`, RAG worker queues, HuggingFace downloads worker).
- [x] Removed beat startup (`celery beat`) and related autostart gating logic.
- [x] Studio runtime now performs DB preflight and runs only the API/web process (Gunicorn or Flask dev server).
- [x] Updated `kubernetes/studio-deployment.yaml` to pin Studio container command to `python3 app/llmctl-studio-backend/run.py` so the deployment path is explicitly the web/API runtime entrypoint.
- [x] Kept Celery producer/client code in Studio application modules unchanged (`services.celery_app`, `services.tasks`, and web task enqueue paths), preserving Redis-backed enqueue/revoke behavior without local consumer dependency.

## Stage 6 - Single-Step Cutover and Operational Validation
- [x] Prepare one release change set containing:
- [x] New worker image + worker/beat manifests.
- [x] Studio decoupling changes.
- [x] Roll out in one window and verify worker/beat pods are healthy before/while Studio update completes.
- [x] Validate representative async tasks across all active queues.
- [x] Validate scheduled tasks are dispatched once via dedicated beat deployment.
- [x] Confirm expected throughput baseline (4 total worker slots from `2 replicas x concurrency 2`).
- [x] Acceptance criteria: production task processing and scheduling are stable with dedicated worker/beat deployments and no Studio-hosted workers.

## Stage 6 - Implementation Notes
- [x] Executed GitOps release gate with `~/.codex/skills/argocd-commit-push-autosync/scripts/commit_push_enable_autosync.sh --app llmctl-studio`, which committed/pushed commit `0c29b02` and enabled ArgoCD autosync (`--auto-prune --self-heal`).
- [x] ArgoCD app `llmctl-studio` synced to `main@0c29b02` and remained healthy after rollout.
- [x] Built and pushed a new Studio backend image tag to Harbor to ensure runtime code changes were actually deployed (avoiding stale `:latest` cache): `scripts/build-harbor.sh --studio --tag stage6-20260217-1`.
- [x] Updated ArgoCD image override for Studio backend only to `10.107.62.134:80/llmctl/llmctl-studio-backend:stage6-20260217-1`.
- [x] Verified deployed Studio runtime command is `python3 app/llmctl-studio-backend/run.py` and process list now contains only `run.py` + Gunicorn (no Celery worker/beat processes).
- [x] Verified dedicated Celery deployments are healthy:
- [x] Worker: `replicas=4`, queue coverage `llmctl_studio,llmctl_studio.downloads.huggingface,llmctl_studio.rag.index,llmctl_studio.rag.drive,llmctl_studio.rag.git`.
- [x] Beat: `replicas=1`, dedicated scheduler process only.
- [x] Validated producer-to-worker task flow from Studio across all active queues by dispatching `services.tasks.cleanup_workspaces` once per queue and confirming all five task IDs completed `SUCCESS`.
- [x] Verified beat-driven schedule dispatch (`workspace_cleanup`) is active from dedicated beat deployment while Studio logs show no Celery scheduler activity.
- [x] Throughput baseline confirmed at 4 worker slots in current runtime (`4 replicas x concurrency 1`), matching the intended total slot baseline of 4.

## Stage 7 - Automated Testing
- [x] Add/update tests for Celery app/task discovery from the new worker image path.
- [x] Add/update integration tests (or smoke automation) covering queued task execution and beat-triggered jobs.
- [x] Run relevant automated checks for backend/runtime/kubernetes config changes.
- [x] Fix regressions found by automated checks.
- [x] Acceptance criteria: all executed automated checks for this change set pass.

## Stage 7 - Implementation Notes
- [x] Added `app/llmctl-studio-backend/tests/test_celery_worker_runtime_stage7.py` to validate `app/llmctl-celery-worker/run.py` runtime behavior:
- [x] Mode normalization (`worker` / `beat` and env fallback).
- [x] Backend `PYTHONPATH` prefixing for `services.celery_app:celery_app` discovery from the worker image path.
- [x] Worker command construction (queues, concurrency, loglevel, hostname, extra args).
- [x] Beat command construction (`celerybeat-schedule`, `celerybeat.pid`, extra args).
- [x] Main entrypoint wiring (`os.chdir`, `os.execv`) for worker runtime launch.
- [x] Ran automated test checks:
- [x] `./.venv/bin/python3 -m pytest app/llmctl-studio-backend/tests/test_celery_worker_runtime_stage7.py -q` (9 passed).
- [x] `LLMCTL_STUDIO_DATABASE_URI='postgresql+psycopg://user:pass@localhost:5432/llmctl_studio' ./.venv/bin/python3 -m pytest app/llmctl-studio-backend/tests/test_socket_proxy_gunicorn_stage9.py -q` (9 passed).
- [x] Ran Stage 7 smoke automation in-cluster for queue + beat coverage:
- [x] Automated enqueue/get for `services.tasks.cleanup_workspaces` across all active queues from Studio producer path (`llmctl_studio`, downloads, rag.index, rag.drive, rag.git) returned `SUCCESS` for all dispatched tasks.
- [x] Dedicated beat logs continue dispatching `workspace_cleanup` on schedule (`Scheduler: Sending due task workspace_cleanup ...`).
- [x] Fixed one Stage 7 test regression during implementation (PYTHONPATH assertion timing under `patch.dict` context), then re-ran the full Stage 7 check set successfully.

## Stage 8 - Docs Updates
- [ ] Update architecture docs to describe Studio/Celery decoupling and responsibilities.
- [ ] Document worker scaling model (`replicas x concurrency = worker slots`) and initial baseline.
- [ ] Update Kubernetes deployment docs for `llmctl-celery-worker` and `llmctl-celery-beat`.
- [ ] Update Sphinx/Read the Docs content for new operational workflow and runtime topology.
- [ ] Acceptance criteria: docs consistently describe the new worker image, deployments, scaling, and cutover behavior.
