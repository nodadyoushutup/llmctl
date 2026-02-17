# Kubernetes-Hosted Integrated MCP Servers Plan

Goal: move integrated MCP servers out of the `llmctl-studio` image into Kubernetes Deployments/Services in the same namespace, then switch Studio to DB-backed in-cluster MCP endpoints so Studio no longer needs bundled MCP server runtimes.

## Stage 0 - Requirements Gathering
- [x] Confirm migration scope for integrated MCP servers.
- [x] Confirm Studio-to-MCP connectivity model.
- [x] Confirm initial service-to-service auth/trust model.
- [x] Confirm Kubernetes packaging format for MCP manifests.
- [x] Confirm DB transition strategy for existing integrated MCP rows.
- [x] Confirm rollout strategy.
- [x] Confirm container image sourcing policy.
- [x] Confirm namespace model.
- [x] Confirm MCP record source-of-truth model.
- [x] Confirm requirements are complete and approved to start Stage 1.

## Stage 0 - Interview Notes
- [x] Scope: migrate all integrated MCP servers to Kubernetes-hosted services.
- [x] Connectivity: Studio uses cluster-internal Service DNS only.
- [x] Security posture for first cut: no extra auth between Studio and MCP services inside namespace.
- [x] Manifests format: plain Kubernetes YAML in-repo.
- [x] Existing DB rows: in-place migration update to new in-cluster MCP endpoints.
- [x] Rollout: single coordinated cutover (not phased).
- [x] Image sourcing: hybrid model.
- [x] `llmctl-mcp` uses existing Harbor image.
- [x] Other integrated MCP services use upstream/prebuilt images.
- [x] Namespace: deploy MCP services in same namespace as Studio.
- [x] Source of truth: DB migration + seed defaults.

## Stage 1 - Code Planning
- [x] Translate approved Stage 0 requirements into Stage 2 through Stage X execution stages.
- [x] Define concrete file-level scope, dependency order, and acceptance criteria per stage.
- [x] Ensure the final two stages are `Automated Testing` and `Docs Updates`.

## Stage 1 - Execution Order
- [x] Stage 2: Integrated MCP inventory + endpoint contract.
- [x] Stage 3: Kubernetes manifests for integrated MCP Deployments/Services.
- [x] Stage 4: Studio integrated MCP DB migration + sync refactor to in-cluster URLs.
- [x] Stage 5: Seed defaults alignment for new environments.
- [x] Stage 6: Studio image/runtime decoupling from embedded MCP server binaries.
- [x] Stage 7: Single-cutover wiring and deployment sequencing.
- [x] Stage 8: Automated Testing.
- [x] Stage 9: Docs Updates.

## Stage 2 - Integrated MCP Inventory + Endpoint Contract
- [x] Inventory all integrated MCP server keys currently managed by Studio from `app/llmctl-studio-backend/src/core/integrated_mcp.py`.
- [x] Define canonical Kubernetes service names, ports, and URL paths per integrated server (including `llmctl-mcp` Harbor image reference).
- [x] Define final in-cluster endpoint format for DB records (for example `http://<service>.<namespace>.svc.cluster.local:<port>` with transport metadata).
- [x] Document any integrated key that is currently feature-gated and decide include-now vs deferred behavior.
- [x] Acceptance criteria: one agreed mapping table exists from integrated server key -> image -> Service DNS endpoint -> DB config payload shape.

## Stage 2 - Output: Integrated MCP Contract
- [x] Integrated key inventory from `core/integrated_mcp.py`: `llmctl-mcp`, `github`, `atlassian`, `chroma`, `google-cloud`, `google-workspace`.
- [x] Existing legacy-key normalization retained: `jira` -> `atlassian`.
- [x] Harbor verification completed: project `llmctl` contains repository path `llmctl/llmctl-mcp` (tag publishing handled in rollout/build step).
- [x] Transport capability finding:
- [x] Native HTTP-capable upstream server confirmed: `mcp/atlassian:latest` (`--transport streamable-http`, `--host`, `--port`, `--path`).
- [x] Current upstream images/packages are stdio-first only for `github`, `chroma`, and `google-cloud`; Stage 3 will add HTTP endpoint exposure for these before DB cutover.

### Stage 2 Mapping Table (Agreed Contract)
| Integrated key | Deployment image/runtime contract | K8s Service name | Port/path | Canonical DB `url` value | Status decision |
| --- | --- | --- | --- | --- | --- |
| `llmctl-mcp` | Harbor image: `<harbor-registry>/llmctl/llmctl-mcp:<tag>` | `llmctl-mcp` | `9020` + `/mcp` | `http://llmctl-mcp.<namespace>.svc.cluster.local:9020/mcp` | Include in cutover |
| `github` | Upstream server image: `mcp/github:latest` with Stage 3 HTTP exposure wrapper | `llmctl-mcp-github` | `8000` + `/mcp` | `http://llmctl-mcp-github.<namespace>.svc.cluster.local:8000/mcp` | Include in cutover (requires Stage 3 wrapper) |
| `atlassian` | Upstream server image: `mcp/atlassian:latest` (native streamable-http mode) | `llmctl-mcp-atlassian` | `8000` + `/mcp` | `http://llmctl-mcp-atlassian.<namespace>.svc.cluster.local:8000/mcp` | Include in cutover |
| `chroma` | Upstream server image: `mcp/chroma:latest` with Stage 3 HTTP exposure wrapper | `llmctl-mcp-chroma` | `8000` + `/mcp` | `http://llmctl-mcp-chroma.<namespace>.svc.cluster.local:8000/mcp` | Include in cutover (requires Stage 3 wrapper) |
| `google-cloud` | Upstream package runtime (`@google-cloud/gcloud-mcp`) with Stage 3 HTTP exposure wrapper | `llmctl-mcp-google-cloud` | `8000` + `/mcp` | `http://llmctl-mcp-google-cloud.<namespace>.svc.cluster.local:8000/mcp` | Include in cutover (requires Stage 3 wrapper) |
| `google-workspace` | No active runtime path yet in current codebase | `llmctl-mcp-google-workspace` (reserved) | `8000` + `/mcp` (reserved) | Reserved | Deferred (feature-gated in code) |

- [x] Final DB payload shape for integrated rows in migration/seed stages:
- [x] `{"url":"http://<service>.<namespace>.svc.cluster.local:<port>/mcp","transport":"streamable-http"}`.
- [x] Optional HTTP headers field remains available for future auth hardening: `headers`.

## Stage 3 - Kubernetes Manifests for Integrated MCP Deployments/Services
- [x] Add one Deployment + Service manifest per integrated MCP server under `kubernetes/` using plain YAML.
- [x] Implement HTTP endpoint exposure for stdio-only upstream MCP servers (`github`, `chroma`, `google-cloud`) so Stage 2 URL contracts resolve in-cluster.
- [x] Add/extend ConfigMap and Secret wiring for upstream MCP containers that require provider credentials.
- [x] Add Harbor image pull configuration for `llmctl-mcp` deployment where required.
- [x] Update `kubernetes/kustomization.yaml` to include all new MCP manifests.
- [x] Ensure resource names are consistent with Studio namespace-local DNS usage.
- [x] Acceptance criteria: `kubectl apply -k kubernetes` includes all MCP services and each integrated MCP pod becomes Ready.

Stage 3 implementation note:
- [x] `google-workspace` remains intentionally deferred (feature-gated in current backend logic); Stage 3 creates Deployments/Services for active integrated servers only.
- [x] Server-side dry-run check completed: `kubectl apply -k kubernetes --dry-run=server`.
- [x] Live cluster rollout check completed for active integrated MCP Deployments:
- [x] `kubectl -n llmctl get deploy llmctl-mcp llmctl-mcp-github llmctl-mcp-atlassian llmctl-mcp-chroma llmctl-mcp-google-cloud`.

## Stage 4 - Studio Integrated MCP DB Migration + Sync Refactor
- [ ] Refactor integrated MCP payload generation in `app/llmctl-studio-backend/src/core/integrated_mcp.py` from local `command`/`stdio` assumptions to Kubernetes service `url` endpoints.
- [ ] Add in-place migration logic in `app/llmctl-studio-backend/src/core/db.py` (or existing runtime migration path) to rewrite existing integrated `mcp_servers.config_json` rows to new in-cluster endpoint payloads.
- [ ] Keep migration idempotent so repeated startups do not churn unchanged rows.
- [ ] Preserve integrated server type semantics and legacy key normalization behavior (for example old `jira` key handling).
- [ ] Acceptance criteria: existing installations auto-update integrated MCP rows to in-cluster URL configs without manual DB edits.

## Stage 5 - Seed Defaults Alignment for New Environments
- [ ] Add/update MCP seed defaults in `app/llmctl-studio-backend/src/core/seed.py` to create expected integrated MCP records for fresh databases.
- [ ] Ensure seed behavior does not override valid migrated records unexpectedly.
- [ ] Align startup migration/seed ordering in `app/llmctl-studio-backend/src/core/migrations.py` and app boot path so migration + seed defaults are consistent.
- [ ] Acceptance criteria: fresh environment gets correct integrated MCP endpoints from seed; existing environments retain migrated rows cleanly.

## Stage 6 - Studio Image/Runtime Decoupling from Embedded MCP Servers
- [ ] Remove integrated MCP server runtime installs from `app/llmctl-studio-backend/docker/Dockerfile` that are no longer needed inside Studio.
- [ ] Remove Studio image coupling to local `app/llmctl-mcp` runtime dependencies where no longer required.
- [ ] Update `app/llmctl-studio-backend/src/services/tasks.py` to stop hardcoded local `llmctl-mcp` command injection and use DB-managed integrated MCP config behavior.
- [ ] Update Kubernetes overlays/runtime configuration only where needed to keep local development behavior coherent with the new DB-managed integrated MCP model.
- [ ] Acceptance criteria: Studio image size decreases and Studio no longer depends on embedded MCP server executables for integrated MCP operation.

## Stage 7 - Single-Cutover Wiring and Deployment Sequencing
- [ ] Update Studio runtime configuration (`kubernetes/studio-configmap.yaml` and related settings) for any new integrated MCP endpoint/env assumptions.
- [ ] Define and implement one-release deployment order: MCP services available before Studio applies DB migration/sync.
- [ ] Add rollback-safe toggles or fallback logic for cutover failure handling where feasible.
- [ ] Acceptance criteria: one coordinated deployment switches integrated MCP usage to Kubernetes services with no manual patching between steps.

## Stage 8 - Automated Testing
- [ ] Add/update backend tests for integrated MCP sync behavior and DB migration rewrite semantics.
- [ ] Add/update tests for seed defaults + migration interaction (fresh DB and existing DB paths).
- [ ] Validate Kubernetes manifest rendering and applyability (`kubectl kustomize` / server-side dry-run as available).
- [ ] Run targeted automated test suites and fix regressions.
- [ ] Acceptance criteria: all executed automated checks for this migration path pass.

## Stage 9 - Docs Updates
- [ ] Update Kubernetes docs in `kubernetes/README.md` for new MCP Deployments/Services, required secrets, and cutover expectations.
- [ ] Update architecture/runtime docs to describe Studio->MCP in-cluster service model and removal of bundled MCP runtimes.
- [ ] Update Sphinx/Read the Docs content to reflect Kubernetes-hosted integrated MCP operations and seed/migration behavior.
- [ ] Acceptance criteria: docs consistently describe the new Kubernetes-first integrated MCP architecture and operator workflow.
