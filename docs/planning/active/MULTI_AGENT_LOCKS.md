# Multi-Agent Locks

## Active Locks

- agent_id: agent-a
  claims:
    - RMC-0075
    - RMC-0081
    - RMC-0142
    - RMC-0167
    - RMC-0346
    - RMC-0347
  allowed_files:
    - app/llmctl-studio-backend/src/services/tasks.py
    - app/llmctl-studio-backend/src/core/prompt_envelope.py
    - app/llmctl-studio-backend/src/core/quick_node.py
    - app/llmctl-studio-backend/src/services/execution/agent_runtime.py
    - app/llmctl-studio-backend/src/services/execution/agent_info.py
    - app/llmctl-studio-backend/tests/test_flowchart_stage9.py
    - app/llmctl-studio-backend/tests/test_claude_provider_stage8.py
    - app/llmctl-studio-backend/tests/test_agent_runtime_abstraction.py
    - docs/planning/active/MULTI_AGENT_LOCKS.md
    - docs/planning/active/agent-handoffs/agent-a.md
  start_time_utc: 2026-02-20T23:21:47Z
  end_time_utc: 2026-02-21T01:01:15Z
  status: complete

- agent_id: agent-d
  claims:
    - RMC-0175
    - RMC-0180
    - RMC-0182
    - RMC-0348
  allowed_files:
    - app/llmctl-studio-frontend/src/components/FlowchartWorkspaceEditor.jsx
    - app/llmctl-studio-frontend/src/components/FlowchartWorkspaceEditor.test.jsx
    - scripts/audit/claim_guardrails.py
    - scripts/audit/claim_guardrails.sh
    - .github/workflows/ci.yml
    - app/llmctl-studio-backend/tests/test_claim_guardrails.py
    - docs/planning/active/MULTI_AGENT_LOCKS.md
    - docs/planning/active/agent-handoffs/agent-d.md
  start_time_utc: 2026-02-21T01:05:37Z
  end_time_utc: 2026-02-21T01:10:40Z
  status: complete

- agent_id: agent-c
  claims:
    - RMC-0104
    - RMC-0121
    - RMC-0122
    - RMC-0124
    - RMC-0132
  allowed_files:
    - app/llmctl-studio-backend/src/web/views.py
    - app/llmctl-studio-backend/tests/test_model_provider_stage7_contracts.py
    - app/llmctl-studio-frontend/src/pages/ModelsPage.jsx
    - app/llmctl-studio-frontend/src/pages/ModelsPage.test.jsx
    - app/llmctl-studio-frontend/src/lib/studioApi.js
    - app/llmctl-studio-frontend/src/lib/studioApi.test.js
    - docs/planning/active/MULTI_AGENT_LOCKS.md
    - docs/planning/active/agent-handoffs/agent-c.md
  start_time_utc: 2026-02-21T01:14:27Z
  end_time_utc: 2026-02-21T01:21:40Z
  status: complete
