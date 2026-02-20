# Runtime Migration Critical Gap Triage

Date: 2026-02-20
Status: Draft (Stage 4)
Source matrix: `docs/planning/active/RUNTIME_MIGRATION_CLAIM_EVIDENCE_MATRIX.md`

## 1) Failed Claim Severity Ranking

Current failed claims (from matrix status `fail`):

1. `RMC-0054` (Critical)
- Claim: all-node artifact persistence contract across node types.
- Why critical: this is a migration contract-level guarantee used for auditability/debugability.
- Evidence:
  - `app/llmctl-studio-backend/src/core/models.py:175`
  - `app/llmctl-studio-backend/src/services/tasks.py:6100`
  - `app/llmctl-studio-backend/src/services/tasks.py:10374`

2. `RMC-0154` (Critical)
- Claim: every node run must persist a traceable artifact record.
- Why critical: explicit invariant in Stage 0 decisions and migration plan.
- Evidence:
  - `app/llmctl-studio-backend/src/core/models.py:175`
  - `app/llmctl-studio-backend/src/services/tasks.py:10374`
  - `app/llmctl-studio-backend/src/services/tasks.py:10439`

3. `RMC-0345` (Critical)
- Claim: frontier provider execution in `services/tasks.py` must be SDK/router-only (no `codex|gemini|claude` CLI subprocess execution).
- Why critical: frontier executor image intentionally excludes these CLIs; any CLI invocation causes hard runtime failure.
- Evidence:
  - `app/llmctl-studio-backend/src/services/tasks.py:4131`
  - `app/llmctl-studio-backend/src/services/tasks.py:4336`
  - `app/llmctl-studio-backend/src/services/tasks.py:4382`
  - `app/llmctl-studio-backend/tests/test_flowchart_stage9.py:3082`
  - `app/llmctl-studio-backend/tests/test_claude_provider_stage8.py:104`

## 2) Immediate Fix Queue (Critical First)

1. Extend node artifact model/contracts to include missing node classes (`task`, `rag`, and required control-node policy decisions).
2. Add persistence writers and success-path invocation for missing node classes in runtime execution flow.
3. Expose artifact retrieval surfaces for newly persisted artifact types (API + run/node detail payload parity).
4. Add frontend artifact detail/history coverage for newly exposed artifact types where user navigation is expected.
5. Add guardrail tests enforcing all-node artifact invariant as hard gate.
6. Run frontier executor smoke for `llm_call` and flowchart task node paths without CLI binaries on PATH, then close `RMC-0345`.

## 3) Pre-Implementation Acceptance Tests (Required Before Code Changes)

For `RMC-0054`:

- Add backend test: for a flowchart run containing `task`, `rag`, `plan`, `milestone`, `memory`, `decision`, assert at least one `NodeArtifact` row exists per node run type expected by policy.
- Add backend test: artifact payload contract validation exists per added artifact type and includes request/correlation + contract/idempotency metadata.
- Add API test: list/detail endpoints expose persisted artifacts for new types with filtering by `flowchart_run_id` and `flowchart_run_node_id`.

For `RMC-0154`:

- Add invariant test: each succeeded node run in representative mixed-node workflow has non-empty `artifact_history`.
- Add failure-mode test: invariant behavior is explicit for node types intentionally excluded (if any), with contract-documented rationale; otherwise test fails.
- Add regression test: decision/memory/milestone/plan existing artifact behavior remains unchanged.

## 4) Locked Remediation Order

1. Backend model + runtime persistence + contracts.
2. Backend API/query surfaces + run detail serialization.
3. Frontend route/detail/history surfaces.
4. Invariant/contract automated tests and guardrails.
5. Re-evaluate matrix statuses and only then proceed to non-critical claim remediation.
