# DB To Kubernetes Secrets Alignment Tentative Plan

Goal: define a safe path to align integration credentials stored in the Studio database with Kubernetes runtime secrets so MCP deployments stay in sync with configured values.

## Stage 0 - Requirements Gathering

- [ ] Run Stage 0 interview with the user one question per turn and explicit options.
- [ ] Confirm source-of-truth model (`DB-only`, `K8s-only`, or `DB primary with K8s projection`).
- [ ] Confirm write behavior expectations (`push on save`, `scheduled reconciliation`, or `manual sync`).
- [ ] Confirm scope for providers and secret domains (GitHub, Jira, Confluence, Google, Chroma, LLM provider keys).
- [ ] Confirm security and compliance constraints (encryption, redaction, audit logging, RBAC boundaries, namespace scope).
- [ ] Confirm failure policy (`fail closed`, `best-effort with warnings`, retry/backoff, alerting).
- [ ] Confirm Stage 0 completeness and ask whether to proceed.

## Stage 1 - Code Planning

- [ ] Define detailed Stage 2 through Stage X implementation stages from approved Stage 0 answers.
- [ ] Freeze file-level scope across backend, runtime services, and Kubernetes manifests.
- [ ] Define acceptance criteria for each stage, including reconciliation correctness and observability.
- [ ] Confirm migration strategy and rollback approach.
- [ ] Confirm final two stages remain `Automated Testing` and `Docs Updates`.

## Stage 2 - Current-State Inventory And Contracts

- [ ] Inventory DB integration settings schema and all current secret consumers in runtime.
- [ ] Inventory all Kubernetes secrets/configmaps currently used by MCP and related workloads.
- [ ] Define normalized key mapping contract (`db_key -> k8s_secret_name/key`).
- [ ] Define canonical error envelope and event/log metadata for sync operations.

## Stage 3 - Sync Design And Ownership Model

- [ ] Design sync ownership model for projected Kubernetes secrets.
- [ ] Define idempotent reconciliation flow and conflict handling.
- [ ] Define reconciliation triggers (settings update hooks, startup sync, periodic reconciliation).
- [ ] Define drift detection and repair behavior.

## Stage 4 - Secret Projection Implementation

- [ ] Implement backend service layer to project validated DB settings into Kubernetes secrets.
- [ ] Add guarded writes with retry/backoff and structured failure reporting.
- [ ] Add per-provider secret projection logic with explicit required/optional key handling.
- [ ] Add dry-run and diagnostics mode for operator validation.

## Stage 5 - Runtime Wiring And Operational Safeguards

- [ ] Wire MCP/integration startup checks to report missing projected secrets clearly.
- [ ] Add audit trail for secret projection actions (who/when/what keys changed, redacted values).
- [ ] Add runtime health/status surfaces for projection state and drift warnings.
- [ ] Add rollback and break-glass operational procedure.

## Stage 6 - Migration And Rollout Strategy

- [ ] Define staged rollout path from current manual secret management to managed projection.
- [ ] Define backward compatibility window and cutover criteria.
- [ ] Define emergency disable switch for projection subsystem.
- [ ] Validate expected behavior across dev/staging/prod namespaces.

## Stage 7 - Automated Testing

- [ ] Add unit tests for key mapping, validation, idempotency, and failure handling.
- [ ] Add integration tests for DB write -> Kubernetes secret projection flow.
- [ ] Add contract tests for secret consumers (MCP pods/services) using projected keys.
- [ ] Add regression tests for drift detection and reconciliation recovery.

## Stage 8 - Docs Updates

- [ ] Update Sphinx/RTD docs for secret ownership, projection flow, and operational runbooks.
- [ ] Document key mapping contracts and provider-specific requirements.
- [ ] Document observability, alerting, and troubleshooting guidance.
- [ ] Document migration, rollback, and operator safety procedures.
