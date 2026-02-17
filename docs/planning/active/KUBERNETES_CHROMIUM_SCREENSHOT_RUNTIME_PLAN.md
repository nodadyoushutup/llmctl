# Kubernetes Chromium Screenshot Runtime Plan

Goal: decouple headless screenshot capture from the `llmctl-studio` image and run it via Kubernetes-native execution so the workflow no longer depends on local Docker.

## Stage 0 - Requirements Gathering
- [x] Capture the primary objective and platform direction from the request.
- [x] Confirm screenshot execution model in Kubernetes (`Job`, one-off `Pod`, or long-running service).
- [x] Confirm screenshot artifact storage target and retention expectations.
- [x] Confirm command interface expected by developers/operators (for example wrapper script, `make` target, or direct `kubectl` usage).
- [x] Confirm namespace and service-DNS rules for target URLs to capture.
- [x] Confirm security and permissions model (ServiceAccount/RBAC, PodSecurity constraints, network policy assumptions).
- [x] Confirm image sourcing and version pinning policy for Chromium runtime.
- [x] Confirm whether Chromium removal from `llmctl-studio` is in-scope for this same change set.
- [ ] Confirm requirements are complete and approved to start Stage 1.

## Stage 0 - Interview Notes
- [x] Objective and direction: Kubernetes-native screenshot execution is preferred over Docker and browser binaries baked into `llmctl-studio`.
- [x] Execution model: use a Kubernetes `Job` for each screenshot capture.
- [x] Artifact strategy: write screenshots to existing Studio data PVC at `/app/data/screenshots`.
- [x] Interface/UX contract: keep the internal `chromium-screenshot` skill interface, but implement it to launch/use an external Kubernetes Chromium container/job and store results in shared data.
- [x] URL targeting: maximize flexibility; default to in-cluster Service DNS, but allow explicit override to ingress host or raw IP-based URL while domains are not yet set up.
- [x] Security policy: run in same namespace with a minimal dedicated ServiceAccount/RBAC scope for screenshot execution lifecycle.
- [x] Image/version policy: use a pinned public Chromium image tag/digest (no `latest`).
- [x] Scope boundary for Studio Dockerfile cleanup: include Chromium removal from `llmctl-studio` in this same implementation.
- [x] Stage progression decision: requirements appear complete; user chose to pause before Stage 1.

## Stage 1 - Code Planning
- [ ] Translate approved Stage 0 requirements into Stage 2 through Stage X execution stages.
- [ ] Define concrete file-level scope, dependency order, and acceptance criteria per stage.
- [ ] Ensure the final two stages are `Automated Testing` and `Docs Updates`.

## Stage 1 - Provisional Execution Order (Draft; finalize after Stage 0)
- [ ] Stage 2: Kubernetes screenshot runtime design and manifest updates.
- [ ] Stage 3: Screenshot capture script refactor to Kubernetes execution flow.
- [ ] Stage 4: Studio skill/runtime integration updates for Kubernetes screenshots.
- [ ] Stage 5: Studio image decoupling from Chromium (if confirmed in scope).
- [ ] Stage 6: Automated Testing.
- [ ] Stage 7: Docs Updates.
