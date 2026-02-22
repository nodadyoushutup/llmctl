Studio UI Header Conventions
============================

Studio page and panel headers use a single compact contract so every route has
consistent density, spacing, and action placement.

Canonical Header Contract
-------------------------

- Use ``PanelHeader`` for page-entry and panel-entry headers.
- Keep headers title-only by default (no metadata line in the header row).
- Keep header actions in the right-side action area only.
- Prefer icon-only controls for compact action sets.
- Use the minimal-line treatment:
  - transparent header background
  - bottom divider
  - compact row spacing

Layout Expectations
-------------------

- Studio content pages use fixed-height panel layouts that fill the content area.
- Avoid page-level scrolling for header/body composition; when more controls are
  needed, use inner panel navigation/sections.
- Do not reintroduce legacy wrapper rows such as ``title-row`` or other one-off
  header containers.

Guardrails
----------

Run the frontend header consistency check before merge:

.. code-block:: bash

   cd app/llmctl-studio-frontend
   npm run check:header-consistency

