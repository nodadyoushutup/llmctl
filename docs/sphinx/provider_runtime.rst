Provider Runtime
================

Overview
--------

Studio provider routing is DB-backed through integration settings
(``provider='llm'``). Provider auth/config updates are written to the DB and
read by runtime execution paths.

For Kubernetes-only node execution routing and execution contract details, see
:doc:`node_executor_runtime`.

Claude Runtime Readiness
------------------------

Claude execution uses ``CLAUDE_CMD`` (default: ``claude``) and performs a
runtime readiness check before Claude runs:

- command must be discoverable on ``PATH`` (or configured via ``CLAUDE_CMD``)
- version check uses ``claude --version``

If the CLI is not ready, behavior is controlled by:

- ``CLAUDE_CLI_AUTO_INSTALL`` (default: ``false``)
- ``CLAUDE_CLI_REQUIRE_READY`` (default: ``true``)
- ``CLAUDE_CLI_INSTALL_SCRIPT``
  (default: ``scripts/install/install-claude-cli.sh``)

When auto-install is enabled, Studio runs the configured install script and
re-checks readiness.

Claude Auth Policy
------------------

Claude auth key resolution is DB-first with environment fallback:

1. ``integration_settings(provider='llm', key='claude_api_key')``
2. ``ANTHROPIC_API_KEY`` environment variable

Key requirement policy:

- ``CLAUDE_AUTH_REQUIRE_API_KEY`` (default: ``true``)

Provider Settings UI surfaces Claude diagnostics for:

- CLI readiness (installed/path/version/error)
- auth readiness/source
- auto-install and fail-fast policy flags

Claude Model Defaults
---------------------

Claude model selection supports curated defaults plus freeform IDs.

Curated suggestions are surfaced in model create/edit forms, and custom
model IDs are still accepted for Claude provider models.

vLLM Local HuggingFace Downloads
--------------------------------

vLLM Local provider settings include HuggingFace download actions backed by
``integration_settings(provider='llm')`` values:

- ``vllm_local_hf_token``: optional HuggingFace token (``hf_*``)
- ``vllm_local_model``: selected discovered local default model

Behavior:

- ``Download Qwen`` always stays available and uses ``vllm_local_hf_token``
  automatically when present; otherwise it downloads anonymously.
- Generic HuggingFace model download controls are shown only when
  ``vllm_local_hf_token`` is configured.
- Generic downloads require repo ID format ``owner/model`` and auto-generate
  the local directory from the model name component.
- If the generated local directory already contains model files, Studio skips
  download and reports the model as already present.

Google Cloud + Workspace Integrations
-------------------------------------

Google integrations are split across two DB-backed providers:

- ``integration_settings(provider='google_cloud')`` for Google Cloud service
  account JSON, optional project ID, and Cloud integrated MCP enablement.
- ``integration_settings(provider='google_workspace')`` for Workspace service
  account JSON, optional delegated user email, and Workspace MCP scaffold
  controls.

Legacy ``provider='google_drive'`` rows are auto-migrated into the split
providers on settings read/write paths. Drive indexing/runtime credential
checks now resolve service account JSON from ``google_workspace``.

Workspace MCP behavior is intentionally guarded in this stage: settings are
stored and surfaced in UI, but runtime integrated MCP server creation remains
disabled until a supported Workspace MCP service-account execution path is
finalized.

Integrated MCP Runtime (Kubernetes)
-----------------------------------

Integrated MCP servers are now Kubernetes service endpoints, not local
executables inside the Studio container.

Runtime synchronization is system-managed through
``core.integrated_mcp.sync_integrated_mcp_servers()``. Integrated rows use
``server_type='integrated'`` with JSON payload shape:

- ``{"url":"http://<service>.<namespace>.svc.cluster.local:<port>/mcp","transport":"streamable-http"}``

Current endpoint contract:

- ``llmctl-mcp`` -> ``http://llmctl-mcp.<namespace>.svc.cluster.local:9020/mcp``
- ``github`` -> ``http://llmctl-mcp-github.<namespace>.svc.cluster.local:8000/mcp``
- ``atlassian`` -> ``http://llmctl-mcp-atlassian.<namespace>.svc.cluster.local:8000/mcp``
- ``chroma`` -> ``http://llmctl-mcp-chroma.<namespace>.svc.cluster.local:8000/mcp``
- ``google-cloud`` -> ``http://llmctl-mcp-google-cloud.<namespace>.svc.cluster.local:8000/mcp``

Namespace comes from ``LLMCTL_NODE_EXECUTOR_K8S_NAMESPACE`` (fallback:
``default``).

Lifecycle/ordering:

1. ``apply_runtime_migrations()`` runs at Studio startup and synchronizes
   integrated MCP rows first (including rewriting legacy command/stdio payloads
   and normalizing legacy key ``jira`` -> ``atlassian``).
2. ``seed_defaults()`` then runs and calls the integrated MCP seed hook so
   fresh databases get the same endpoint contract without overriding valid
   migrated integrated rows.

Credential split:

- Studio integration settings remain DB-backed.
- Kubernetes MCP Deployments read provider credentials from Kubernetes Secrets
  (for example ``llmctl-mcp-secrets``), not from Studio-local embedded MCP
  binaries.

Agent Skill Binding Contract
----------------------------

Runtime enforces Agent-level skill ownership:

- node-level ``skill_ids`` graph writes are rejected
- skills must be bound to Agents and resolved through node agent references

See :doc:`agent_skill_binding` for binding behavior and migration notes.
