Provider Runtime
================

Overview
--------

Studio provider routing is DB-backed through integration settings
(``provider='llm'``). Provider auth/config updates are written to the DB and
read by runtime execution paths.

For node execution provider routing (``workspace|docker|kubernetes``),
fallback semantics, and execution contract details, see
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

Agent Skill Binding Compatibility Mode
--------------------------------------

Runtime settings also expose ``node_skill_binding_mode`` for legacy client
compatibility during Agent-only skill binding cutover:

- ``warn``: ignore node-level ``skill_ids`` writes and emit deprecation metadata/logs.
- ``reject``: return explicit validation errors for node-level ``skill_ids`` writes.

See :doc:`agent_skill_binding` for full Agent/node binding behavior and
migration notes.
