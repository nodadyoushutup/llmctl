MCP-Driven Integration Auto-Apply
=================================

Overview
--------

Studio now treats MCP server selection as the authoritative source for
integration context in:

- Node create (``/nodes/new``)
- Quick Node run + defaults (``/quick``, ``/quick/settings``)
- Chat session runtime (``/chat``, ``/api/chat/runtime``)

Manual integration selection is removed from Node/Quick React controls.

Static Mapping Contract (Phase 1)
---------------------------------

The backend resolver (`services.mcp_integrations`) applies a static
``mcp_server_key -> integration_keys`` map:

- ``github`` -> ``github``
- ``atlassian`` -> ``jira``, ``confluence``
- ``jira`` (legacy key) -> ``jira``, ``confluence``
- ``google-cloud`` -> ``google_cloud``
- ``google-workspace`` -> ``google_workspace``
- ``chroma`` -> ``chroma``
- ``llmctl-mcp`` -> no integration mapping

Unknown/custom MCP server keys do not map to integrations in this phase.

Resolution And Validation
-------------------------

For each selected MCP server key, Studio resolves:

- mapped integration keys
- configured integration keys
- skipped integration keys
- warning messages

Validation is soft-fail: execution continues with configured integrations,
and missing/invalid integrations are skipped with warnings.

Warning Semantics
-----------------

Warnings follow this shape:

- ``Skipping integration '<integration_key>' for <mcp_key>: <reason>.``

Examples of reasons include missing repo defaults, incomplete Jira/Confluence
site credentials/defaults, or incomplete Google/Chroma settings.

Runtime/API Surfaces
--------------------

Node + Quick create responses include derived integration metadata:

- ``selected_integration_keys``
- ``integration_warnings``

Chat runtime/config responses also expose selected integration state:

- ``selected_mcp_server_keys``
- ``selected_integration_keys``
- ``integration_warnings``

Task runtime output metadata carries:

- ``integration_keys``
- ``integration_warnings``

Future Limitation
-----------------

Custom MCP server integration mapping is not configurable yet.
A follow-up design note is tracked in:

- ``docs/planning/pending/CUSTOM_MCP_INTEGRATION_SETTINGS_FUTURE_NOTE.md``
