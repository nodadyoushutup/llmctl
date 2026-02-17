# Vault Secrets GitOps Plan

Goal: deploy HashiCorp Vault via ArgoCD, initialize/unseal it, create secrets in Vault, and wire Kubernetes workloads to consume those secrets.

## Stage 0 - Requirements Gathering
- [x] Capture initial objective and constraints from the request.
- [x] Confirm environment scope for initial rollout (dev-only vs multi-environment).
- [x] Confirm Vault deployment mode and storage backend for this phase.
- [x] Confirm how Kubernetes workloads should consume Vault secrets (injection vs sync).
- [x] Confirm authentication/bootstrap ownership and operational boundaries.
- [x] Confirm migration scope for existing Kubernetes secrets.
- [x] Confirm custody location for Vault init artifacts (unseal keys/root token) for dev operations.
- [ ] Confirm requirements are complete and approved to start Stage 1.

## Stage 0 - Interview Notes
- [x] User wants HashiCorp Vault added as an ArgoCD-managed Helm application.
- [x] User wants the workflow to include Vault bootstrap (init/unseal), secret creation, and downstream Kubernetes usage.
- [x] Environment scope for this implementation is dev-only.
- [x] Vault mode for dev is single-node with Raft integrated storage.
- [x] Workload secret consumption pattern is External Secrets Operator syncing Vault secrets into Kubernetes Secrets.
- [x] Bootstrap model is manual init/unseal for dev, plus an operational script/job in namespace for seal/unseal actions.
- [x] Migration scope is all current secret consumers under `kubernetes/`.
- [x] For ease of dev operations, Vault init artifacts will be stored in a Kubernetes Secret in the Vault namespace so seal/unseal jobs can run in-cluster.

## Stage 1 - Code Planning
- [ ] Define Stage 2 through Stage X implementation stages from approved requirements.
- [ ] Define file-level scope and dependency order for ArgoCD + Vault integration.
- [ ] Ensure the final two stages are `Automated Testing` and `Docs Updates`.

## Stage 2 - Pending (to be defined in Stage 1)
- [ ] Placeholder until Stage 1 finalizes the execution plan.

## Stage 3 - Automated Testing
- [ ] Add or update automated checks validating Vault ArgoCD manifests and secret-consumption wiring.
- [ ] Execute relevant automated tests/linting and resolve failures.
- [ ] Acceptance criteria: automated checks pass for the new Vault integration scope.

## Stage 4 - Docs Updates
- [ ] Update Kubernetes/ArgoCD docs for Vault deployment, bootstrap workflow, and secret usage pattern.
- [ ] Update Sphinx/Read the Docs docs to reflect the new secrets architecture and operator workflow.
- [ ] Acceptance criteria: docs align with implemented Vault-based secret management.
