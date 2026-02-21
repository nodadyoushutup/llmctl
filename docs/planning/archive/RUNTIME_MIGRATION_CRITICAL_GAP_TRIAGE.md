# Runtime Migration Critical Gap Triage

Date: 2026-02-21
Status: Updated (no unresolved claims)
Source matrix: `docs/planning/archive/RUNTIME_MIGRATION_CLAIM_EVIDENCE_MATRIX.md`

## 1) Failed Claim Severity Ranking

Current failed claims (from matrix status `fail`):

- None.

Matrix now reports `fail: 0` and `insufficient_evidence: 0` (no remaining unresolved claims).

## 2) RMC-0345 Closure Evidence

- Runtime cutover evidence:
  - `app/llmctl-studio-backend/src/services/tasks.py:4130`
  - `app/llmctl-studio-backend/src/services/tasks.py:4350`
  - `app/llmctl-studio-backend/src/services/tasks.py:4396`
  - `app/llmctl-studio-backend/src/services/tasks.py:4412`
  - `app/llmctl-studio-backend/src/services/tasks.py:4420`
- Guardrail + smoke tests:
  - `app/llmctl-studio-backend/tests/test_flowchart_stage9.py:3082`
  - `app/llmctl-studio-backend/tests/test_flowchart_stage9.py:3136`
  - `app/llmctl-studio-backend/tests/test_flowchart_stage9.py:3183`
  - `app/llmctl-studio-backend/tests/test_claude_provider_stage8.py:104`
- Postgres-backed command evidence:
  - `docs/planning/archive/RUNTIME_MIGRATION_FULL_CLAIM_AUDIT_REMEDIATION_PLAN.md:148`
  - `docs/planning/archive/RUNTIME_MIGRATION_FULL_CLAIM_AUDIT_REMEDIATION_PLAN.md:149`

## 3) Recently Closed Critical Claims

- `RMC-0054`: closed as `pass` in matrix with all-node artifact persistence evidence.
  - `app/llmctl-studio-backend/src/services/tasks.py:6463`
  - `app/llmctl-studio-backend/src/services/tasks.py:6479`
  - `app/llmctl-studio-backend/src/services/tasks.py:10940`
  - `app/llmctl-studio-backend/tests/test_flowchart_stage9.py:843`
  - `app/llmctl-studio-backend/tests/test_flowchart_stage9.py:1123`

- `RMC-0154`: closed as `pass` in matrix with node-run invariant evidence.
  - `app/llmctl-studio-backend/src/services/tasks.py:10940`
  - `app/llmctl-studio-backend/tests/test_flowchart_stage9.py:843`
  - `app/llmctl-studio-backend/tests/test_flowchart_stage9.py:1110`
  - `app/llmctl-studio-backend/tests/test_flowchart_stage9.py:1131`

- `RMC-0345`: closed as `pass` in matrix after targeted Postgres-backed guardrail/smoke execution.
  - `app/llmctl-studio-backend/tests/test_flowchart_stage9.py:3183`
  - `docs/planning/archive/RUNTIME_MIGRATION_FULL_CLAIM_AUDIT_REMEDIATION_PLAN.md:149`

- `RMC-0346`, `RMC-0347`, `RMC-0348`: closed as `pass` in matrix with typed agent abstraction and claim guardrail hard-gate evidence.
  - `app/llmctl-studio-backend/src/services/execution/agent_info.py:7`
  - `app/llmctl-studio-backend/src/services/execution/agent_runtime.py:10`
  - `scripts/audit/claim_guardrails.py:126`
  - `.github/workflows/ci.yml:10`

- `RMC-0081`: closed as `pass` in matrix with explicit schema-repair retry loop + terminal fail-after-max behavior.
  - `app/llmctl-studio-backend/src/services/tasks.py:6862`
  - `app/llmctl-studio-backend/src/services/tasks.py:6932`
  - `app/llmctl-studio-backend/src/services/tasks.py:8551`
  - `app/llmctl-studio-backend/src/services/tasks.py:8642`
  - `app/llmctl-studio-backend/tests/test_flowchart_stage9.py:1426`
  - `app/llmctl-studio-backend/tests/test_flowchart_stage9.py:1513`

- `RMC-0142`: closed as `pass` in matrix with dedicated optional plan transform summary path and separate structured patch handling.
  - `app/llmctl-studio-backend/src/services/tasks.py:8948`
  - `app/llmctl-studio-backend/src/services/tasks.py:8951`
  - `app/llmctl-studio-backend/src/services/tasks.py:8963`
  - `app/llmctl-studio-backend/src/services/tasks.py:9073`
  - `app/llmctl-studio-backend/src/services/tasks.py:9192`
  - `app/llmctl-studio-backend/tests/test_flowchart_stage9.py:3023`
  - `app/llmctl-studio-backend/tests/test_flowchart_stage9.py:3081`

- `RMC-0075`: closed as `pass` in matrix with production typed-agent abstraction parity evidence.
  - `app/llmctl-studio-backend/src/services/execution/agent_info.py:8`
  - `app/llmctl-studio-backend/src/services/tasks.py:3446`
  - `app/llmctl-studio-backend/src/services/tasks.py:3513`
  - `app/llmctl-studio-backend/src/services/tasks.py:3969`
  - `app/llmctl-studio-backend/tests/test_agent_runtime_abstraction.py:53`
  - `app/llmctl-studio-backend/tests/test_agent_runtime_abstraction.py:84`

- `RMC-0104`: closed as `pass` in matrix with Gemini Vertex settings and runtime branching evidence.
  - `app/llmctl-studio-backend/src/services/execution/agent_runtime.py:225`
  - `app/llmctl-studio-backend/src/services/tasks.py:2000`
  - `app/llmctl-studio-frontend/src/pages/SettingsProviderPage.jsx:139`
  - `app/llmctl-studio-frontend/src/pages/SettingsProviderPage.test.jsx:73`
  - `app/llmctl-studio-backend/tests/test_agent_runtime_abstraction.py:108`

- Residual insufficient-evidence claims closed to `pass`: `RMC-0121`, `RMC-0122`, `RMC-0124`, `RMC-0132`, `RMC-0143`, `RMC-0175`, `RMC-0180`, `RMC-0182`.
  - `docs/planning/archive/RUNTIME_MIGRATION_CLAIM_EVIDENCE_MATRIX.md:10`
  - `docs/planning/archive/RUNTIME_MIGRATION_CLAIM_EVIDENCE_MATRIX.md:12`
  - `app/llmctl-studio-frontend/src/pages/ModelEditPage.jsx:171`
  - `app/llmctl-studio-frontend/src/pages/ModelNewPage.jsx:168`
  - `app/llmctl-studio-frontend/src/pages/ModelsPage.jsx:260`
  - `app/llmctl-studio-backend/src/services/execution/tool_domains.py:604`
  - `app/llmctl-studio-frontend/src/components/FlowchartWorkspaceEditor.jsx:1952`

## 4) Locked Remediation Order

1. No remaining remediation work in this triage scope.
2. Keep claim statuses locked to `pass` unless regression evidence appears.
