Studio Backend Module Layout
============================

Overview
--------

The Studio backend structural refactor now uses package-oriented module layout
for large backend domains while preserving runtime behavior and route contracts.

Current Layout (Key Areas)
--------------------------

- ``app/llmctl-studio-backend/src/web/views/`` is now a package split by route
  domain:

  - ``agents_runs.py``
  - ``chat_nodes.py``
  - ``plans_milestones.py``
  - ``flowcharts.py``
  - ``models_mcps.py``
  - ``artifacts_attachments.py``
  - ``settings_providers.py``
  - ``settings_integrations.py``
  - ``shared.py`` (shared serializers/parsers/formatters and utility helpers)

- ``app/llmctl-studio-backend/src/core/models/`` is now a package rather than a
  monolithic single file.

- ``app/llmctl-studio-backend/src/services/task_utils/`` contains extracted
  task-side JSON/path coercion helpers.

- ``app/llmctl-studio-backend/src/web/view_helpers/`` contains extracted
  route-display helpers used by web views.

Compatibility Contract
----------------------

- Public route contracts remain unchanged:
  - same blueprint and endpoint names
  - same URL/method mappings
  - same request/response envelopes
  - same flash-message behavior

- Import surface ``web.views`` remains stable through package exports in
  ``app/llmctl-studio-backend/src/web/views/__init__.py``.

Vestigial CLI Paths Removed
---------------------------

The following non-load-bearing backend CLI-era paths were removed:

- ``app/llmctl-studio-backend/src/__main__.py``
- ``app/llmctl-studio-backend/src/cli/__init__.py``
- ``app/llmctl-studio-backend/src/cli/agent-cli.py``
- ``app/llmctl-studio-backend/src/cli/agent-dispatch.py``
- ``app/llmctl-studio-backend/src/cli/agent-loop.py``

Runtime startup remains service-driven via web and worker entrypoints, not
these legacy CLI paths.
