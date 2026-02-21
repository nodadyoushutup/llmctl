# Agent C Handoff

## Scope
- RMC-0104
- RMC-0121
- RMC-0122
- RMC-0124
- RMC-0132

## Claim Status
- `RMC-0104` - `pass`
  - Vertex Gemini config fields were added to backend provider/model contracts and frontend API payloads.
  - Evidence:
    - `app/llmctl-studio-backend/src/web/views.py:323`
    - `app/llmctl-studio-backend/src/web/views.py:2549`
    - `app/llmctl-studio-backend/src/web/views.py:2803`
    - `app/llmctl-studio-backend/src/web/views.py:2876`
    - `app/llmctl-studio-backend/src/web/views.py:19829`
    - `app/llmctl-studio-frontend/src/lib/studioApi.js:1324`
    - `app/llmctl-studio-frontend/src/lib/studioApi.test.js:819`
    - `app/llmctl-studio-backend/tests/test_model_provider_stage7_contracts.py:234`
- `RMC-0121` - `pass`
  - Models list now emits non-blocking compatibility drift notice through shared flash area and shows per-row `Review settings` hint when drift is detected.
  - Evidence:
    - `app/llmctl-studio-frontend/src/pages/ModelsPage.jsx:242`
    - `app/llmctl-studio-frontend/src/pages/ModelsPage.jsx:664`
    - `app/llmctl-studio-frontend/src/pages/ModelsPage.test.jsx:349`
- `RMC-0122` - `insufficient_evidence` (out of editable scope)
  - Assigned allowed-file scope excludes model detail/edit/new pages where header delete placement is implemented (`ModelEditPage`/`ModelNewPage`).
  - No direct changes were made for detail header delete placement in this slice.
- `RMC-0124` - `insufficient_evidence` (out of editable scope)
  - Assigned allowed-file scope excludes model detail/create page action layout files needed for `Save`/`Cancel` header placement.
  - No direct changes were made for detail/create header action placement in this slice.
- `RMC-0132` - `pass`
  - Models list defaults to `25` rows per page, default sort remains `Name ASC`, and pagination controls stay in the panel header controls area.
  - Evidence:
    - `app/llmctl-studio-frontend/src/pages/ModelsPage.jsx:31`
    - `app/llmctl-studio-frontend/src/pages/ModelsPage.jsx:282`
    - `app/llmctl-studio-frontend/src/pages/ModelsPage.test.jsx:320`
    - `app/llmctl-studio-frontend/src/pages/ModelsPage.test.jsx:328`

## Tests Run
- Backend:
  - `~/.codex/skills/llmctl-studio-test-postgres/scripts/run_backend_tests_with_postgres.sh -- .venv/bin/python3 -m unittest app/llmctl-studio-backend/tests/test_model_provider_stage7_contracts.py`
  - Result: `OK` (`Ran 8 tests`)
- Frontend:
  - `cd app/llmctl-studio-frontend && npm test -- src/pages/ModelsPage.test.jsx src/lib/studioApi.test.js`
  - Result: `PASS` (`42 passed`)

## Frontend Screenshot
- Captured and reviewed:
  - `docs/screenshots/2026-02-20-20-20-45--models--agent-c-claims-rmc0104-rmc0132-post-restart--1920x1080--03ad08c--2ce287.png`

## Deploy/Reload
- `kubectl -n llmctl rollout restart deploy/llmctl-studio-frontend`
- `kubectl -n llmctl rollout status deploy/llmctl-studio-frontend` (successful)
- `kubectl -n llmctl rollout restart deploy/llmctl-studio-backend`
- `kubectl -n llmctl rollout status deploy/llmctl-studio-backend` (successful)
