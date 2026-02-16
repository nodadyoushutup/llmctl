Codex Skills (Project-Owned)
============================

Use project-owned Codex skills to control assistant behavior during development without changing in-app/runtime skill systems.

Skill Source Of Truth
---------------------

- Store project-owned Codex skills in ``codex-skills/``.
- Keep each skill self-contained with ``SKILL.md`` and optional ``scripts/``, ``references/``, ``assets/``, and ``agents/openai.yaml``.
- Do not mix these with llmctl in-app skills/runtime bindings.

Install Or Sync Skills
----------------------

Install all project-owned Codex skills into the local Codex home:

.. code-block:: bash

   scripts/install_codex_skills.sh

Preview what would be installed:

.. code-block:: bash

   scripts/install_codex_skills.sh --dry-run

Install one skill only:

.. code-block:: bash

   scripts/install_codex_skills.sh --skill chromium-screenshot

The install destination is ``${CODEX_HOME:-$HOME/.codex}/skills``.
Restart Codex after installation to ensure new skills are discoverable.

Chromium Screenshot Skill
-------------------------

The ``chromium-screenshot`` skill standardizes frontend screenshot verification artifacts.

- Output directory: ``docs/screenshots/``
- Filename format:
  ``<route-or-page>--<state>--<viewport>--<YYYYMMDD-HHMMSS>--<gitsha7>--<hash6>.png``
- Capture command:

.. code-block:: bash

   codex-skills/chromium-screenshot/scripts/capture_screenshot.sh \
     --url http://localhost:5000/settings \
     --route settings-runtime \
     --state validation-error \
     --viewport 1920x1080 \
     --out-dir docs/screenshots

For frontend-impacting work, capture at least one screenshot and mention artifact paths in the task summary.
