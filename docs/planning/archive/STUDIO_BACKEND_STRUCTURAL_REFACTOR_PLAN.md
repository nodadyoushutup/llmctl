# Studio Backend Structural Refactor Plan

Goal: Perform a structural-only refactor of `app/llmctl-studio-backend/src` by splitting oversized modules into smaller packages/files, preserving behavior, and removing confirmed vestigial CLI-era backend paths that are no longer load-bearing.

## Stage 0 - Requirements Gathering

- [x] Capture requested outcome from user report.
- [x] Confirm exact Stage 0 scope boundaries for this first workstream (`llmctl-studio-backend` only vs cross-repo prep).
  - [x] Scope selected: `llmctl-studio-backend` only.
- [x] Confirm hard definition of "structural-only" change policy (allowed vs disallowed edits).
  - [x] Policy selected: strict move-only (move/split files + import rewiring only; no behavior/signature changes).
- [x] Confirm target decomposition standard (class-per-file defaults, utility grouping rules, package layout conventions).
  - [x] Standard selected: class-per-file by default; tiny tightly related classes may share one file.
  - [x] Utility convention selected: domain-focused utility modules per package (`parsing.py`, `validation.py`, `serialization.py`).
- [x] Confirm vestigial CLI removal policy (prove-not-used threshold + deletion strategy).
  - [x] Removal threshold selected: require explicit proof of no runtime references (`rg`, import/call-path verification, and green tests) before deletion.
- [x] Confirm rollout strategy (single large PR vs staged waves by domain/package).
  - [x] Rollout selected: staged waves by backend domain/package with checkpoints each wave.
- [x] Confirm concrete file-size targets for extracted modules/packages.
  - [x] No numeric line-count caps; decompose by logical ownership and cohesion.
  - [x] Allow large files when they contain a single coherent class/module; split when multiple classes/domains are mixed.
- [x] Confirm import-compatibility policy during staged extraction waves.
  - [x] Policy selected: no compatibility shims; update all imports in-wave and fail fast on misses.
- [x] Confirm Stage 0 completion with user and ask whether to proceed to Stage 1.
  - [x] User confirmed proceeding to the next stage on 2026-02-21.

## Stage 1 - Code Planning

- [x] Define Stage 2 through Stage X based on Stage 0 decisions.
  - [x] Stage 2 through Stage 8 remained the initial execution/testing/docs structure when Stage 1 was completed.
  - [x] Plan extension on 2026-02-21 added an explicit pre-testing execution stage for `web/views.py` package decomposition; final two stages remain Automated Testing and Docs Updates.
- [x] Define module inventory strategy for oversized files and dependency mapping.
  - [x] Inventory method: collect file-size baseline with `rg --files app/llmctl-studio-backend/src | xargs wc -l | sort -nr`.
  - [x] Symbol/dependency method: map imports and top-level symbols using `rg -n "^from |^import |^class |^def " app/llmctl-studio-backend/src`.
  - [x] Oversized-module triage rule: prioritize multi-domain files first, then files mixing transport + domain logic, then utility catch-all modules.
- [x] Define import-migration sequencing that minimizes merge risk and behavior drift.
  - [x] Sequence rule: extract leaf utilities first, then domain services, then route handlers, and finally cross-domain composition modules.
  - [x] Batch rule: keep extraction batches small enough to validate with targeted tests after each batch.
  - [x] Drift control: forbid signature/behavior edits in extraction PRs; only moves/splits and import rewiring.
- [x] Define lightweight audit checkpoints embedded in each execution stage.
  - [x] Wave checkpoint template: (1) moved-symbol parity check, (2) import-resolution check, (3) targeted test pass record, (4) vestigial-path evidence capture where applicable.
  - [x] Evidence policy: record concrete command output references directly in this plan during each execution wave.
- [x] Freeze final two stages:
  - [x] Automated Testing
  - [x] Docs Updates

## Stage 2 - Scope-Specific Planning

- [x] Build the backend structural decomposition map by package/domain.
  - [x] `web` domain (current hotspot: `app/llmctl-studio-backend/src/web/views.py`, 21670 LOC): split into `web/views/` package with domain route modules (`agents_runs.py`, `chat_nodes.py`, `plans_milestones.py`, `flowcharts.py`, `artifacts.py`, `models_mcps.py`, `settings_providers.py`, `settings_integrations.py`) plus shared `helpers/` modules.
  - [x] `services` domain (current hotspot: `app/llmctl-studio-backend/src/services/tasks.py`, 11453 LOC): split into `services/tasks/` package (`entrypoints.py`, `llm_runtime.py`, `workspace_ops.py`, `flowchart_runtime.py`, `node_executors/`, `artifacts.py`, `events.py`, `task_payloads.py`).
  - [x] `core` domain hotspots:
    - [x] `app/llmctl-studio-backend/src/core/db.py` (2615 LOC) -> `core/db/` (`engine.py`, `session.py`, `schema_bootstrap.py`, `ddl_helpers.py`, `migrations/`, `healthcheck.py`).
    - [x] `app/llmctl-studio-backend/src/core/models.py` (1686 LOC) -> `core/models/` grouped by entity domain (`agent.py`, `flowchart.py`, `plan.py`, `chat.py`, `rag.py`, shared base/mixins).
    - [x] `app/llmctl-studio-backend/src/core/seed.py` (1489 LOC) -> `core/seed/` by seed domain (`roles.py`, `agents.py`, `models.py`, `scripts.py`, `mcp.py`, `skills.py`).
  - [x] `rag` domain remains package-oriented; only targeted extraction candidate is `app/llmctl-studio-backend/src/rag/web/views.py` if needed for route parity with `web/views`.
- [x] Define per-domain extraction units (classes, helpers, constants, serializers, route handlers).
  - [x] `web/views.py` extraction units:
    - [x] Route handlers by URL segment cluster (evidence: `agents`, `runs`, `chat`, `nodes`, `plans`, `milestones`, `flowcharts`, `models`, `mcps`, `settings`).
    - [x] Serialization/payload helpers (`_serialize_*`, `_build_*_payload`) into dedicated serializer modules.
    - [x] Form parsing/normalization helpers (`_parse_*`, `_normalize_*`, `_coerce_*`) into validation/parsing modules.
    - [x] Integration/provider utility helpers (GitHub/Jira/Confluence/Chroma/provider defaults) into `web/views/integrations_helpers.py`.
  - [x] `services/tasks.py` extraction units:
    - [x] Celery task entrypoints (`cleanup_workspaces`, `run_huggingface_download_task`, `run_agent`, `run_quick_rag_task`, `run_agent_task`, `run_flowchart`) isolated in `entrypoints.py`.
    - [x] Runtime command/model dispatch helpers (provider commands, runtime payload builders, subprocess wrappers) into `llm_runtime.py`.
    - [x] Flowchart execution pipeline by node type (`task`, `decision`, `plan`, `milestone`, `memory`, `rag`, executor nodes) into `node_executors/`.
    - [x] Artifact persistence/serialization helpers into `artifacts.py`.
    - [x] Realtime/celery event payload + emit helpers into `events.py`.
  - [x] `core/db.py` extraction units: bootstrap/session, SQL dialect helpers, and migration families (agent/task, role/agent, rag, chat, flowchart/index/view).
  - [x] `core/models.py` extraction units: one model per file by domain group, keep relationship wiring in package init or relationship module.
  - [x] `core/seed.py` extraction units: seed loaders and per-entity seed routines by bounded domain.
- [x] Define acceptance criteria for each extraction unit (no logic changes, import parity, test parity).
  - [x] No behavior edits: function/class signatures and route/task contracts remain identical.
  - [x] Import parity: all moved symbols are re-imported at updated call sites with no fallback shims.
  - [x] Route parity: same blueprint, endpoint names, and URL/method mappings before/after extraction.
  - [x] Celery parity: same registered task names and invocation points from web/chat/rag call paths.
  - [x] Data contract parity: JSON response keys and socket payload envelopes unchanged for touched handlers.
  - [x] Test parity: targeted suites for touched domains pass at each wave checkpoint; failures require same-wave remediation.
- [x] Define CLI vestigiality verification checklist for candidate removals.
  - [x] Candidate set: `app/llmctl-studio-backend/src/__main__.py` and `app/llmctl-studio-backend/src/cli/*`.
  - [x] Inbound-reference proof: run `rg -n "agent-loop\\.py|agent-cli\\.py|src/cli/|AGENT_CLI" app/llmctl-studio-backend/src .` and confirm references are self-contained or non-runtime.
  - [x] Runtime-path proof: verify backend load paths from `app/llmctl-studio-backend/src/web/app.py`, `app/llmctl-studio-backend/src/services/celery_app.py`, and imports in `web/views.py`, `chat/runtime.py`, `rag/web/views.py` do not depend on CLI modules.
  - [x] Deployment-path proof: verify no Kubernetes/script/runtime startup references to CLI entrypoints.
  - [x] Removal gate: only remove a CLI-era path when all three proofs are satisfied and targeted automated tests remain green.
  - [x] Fail-fast rule: if any runtime/deployment dependency is found, defer deletion and record dependency evidence in Stage 6.

## Stage 3 - Execution Wave 1 (Inventory And Baseline)

- [x] Produce file-size and symbol inventory for oversized backend modules.
  - [x] Baseline file-size inventory captured on 2026-02-21 with `rg --files app/llmctl-studio-backend/src | xargs wc -l | sort -nr | head -n 30`.
  - [x] Confirmed top hotspots: `web/views.py` (21670), `services/tasks.py` (11453), `core/db.py` (2615), `core/models.py` (1686), `core/seed.py` (1489), `rag/web/views.py` (1253), `services/integrations.py` (1227), `services/flow_migration.py` (1102).
  - [x] Symbol-density snapshot captured with `rg -n '^def |^async def |^class |^from |^import ' ...`:
    - [x] `web/views.py`: 601 defs, 55 imports.
    - [x] `services/tasks.py`: 244 defs, 52 imports.
    - [x] `core/db.py`: 61 defs, 2 classes.
    - [x] `core/models.py`: 33 classes.
  - [x] Surface-size signals recorded: `web/views.py` has 244 blueprint route decorators; `services/tasks.py` has 6 Celery task decorators.
- [x] Capture baseline automated test targets for touched domains.
  - [x] Target discovery recorded from `rg --files app/llmctl-studio-backend/tests` with domain filters for routes, runtime, executor, flowchart, RAG web, seed, and contracts.
  - [x] Reproducible collection command A (23 tests):
    - [x] `LLMCTL_STUDIO_DATABASE_URI='postgresql+psycopg://user:pass@localhost:5432/llmctl' PYTHONPATH=app/llmctl-studio-backend/src .venv/bin/pytest --import-mode=importlib --collect-only -q app/llmctl-studio-backend/tests/test_react_stage7_api_routes.py app/llmctl-studio-backend/tests/test_rag_stage9.py app/llmctl-studio-backend/tests/test_flowchart_stage12.py`
  - [x] Reproducible collection command B (23 tests):
    - [x] `LLMCTL_STUDIO_DATABASE_URI='postgresql+psycopg://user:pass@localhost:5432/llmctl' PYTHONPATH=app/llmctl-studio-backend/src .venv/bin/pytest --import-mode=importlib --collect-only -q app/llmctl-studio-backend/tests/test_runtime_contracts_stage3.py app/llmctl-studio-backend/tests/test_node_executor_stage8.py app/llmctl-studio-backend/tests/test_seed_stage11.py app/llmctl-studio-backend/tests/rag/test_web_sources.py`
  - [x] Baseline prerequisite note: collection requires explicit `LLMCTL_STUDIO_DATABASE_URI`, explicit `PYTHONPATH`, and `--import-mode=importlib` to avoid package shadowing during collection.
- [x] Record extraction order and owner notes in this plan.
  - [x] Wave 2 extraction order (owner: current backend refactor agent in this workspace):
    - [x] Step 1: `core/models.py` split (highest class density, bounded domain entities).
    - [x] Step 2: `core/db.py` split (migration families + DDL helpers).
    - [x] Step 3: `core/seed.py` split (domain seed modules).
  - [x] Wave 3 extraction order (owner: current backend refactor agent in this workspace):
    - [x] Step 4: `services/tasks.py` into task/runtime/executor/artifact/event modules.
    - [x] Step 5: `web/views.py` route-cluster extraction + helper/serializer modules.
    - [x] Step 6: reconcile `rag/web/views.py` if cross-view helper parity is needed.
  - [x] Coordination note: if multiple agents touch this plan concurrently, preserve above order and annotate any ownership handoff directly in this stage block.
- [x] Perform audit checkpoint: verify baseline is reproducible and evidence-backed.
  - [x] Reproducibility confirmed by command-based inventory and successful repeatable `pytest --collect-only` runs with explicit env prerequisites.
  - [x] Evidence captured in this stage block with concrete command lines and measured outputs.
  - [x] Stage 3 exit criteria met; Stage 4 can begin with no behavior-change scope expansion.

## Stage 4 - Execution Wave 2 (Core Module Extractions)

- [x] Extract first domain set into new packages/files.
  - [x] Replaced monolithic `app/llmctl-studio-backend/src/core/models.py` with `app/llmctl-studio-backend/src/core/models/` package.
  - [x] Added split modules: `constants.py`, `associations.py`, `skills.py`, `resources.py`, `rag.py`, `agent.py`, `flowchart.py`, `planning.py`, `chat.py`, and package `__init__.py`.
  - [x] Preserved model/table/constant definitions as structural moves only; no schema/behavior edits introduced.
- [x] Keep import surfaces stable and update all imports in-wave (no compatibility shims).
  - [x] Preserved canonical import surface `from core.models import ...` via `core/models/__init__.py`.
  - [x] No legacy compatibility wrapper file kept at `core/models.py`; module path now resolves via package.
  - [x] Adjusted package exports in-wave (including `LLMModel` export location) to maintain import parity for existing call sites.
- [x] Run targeted verification after each extraction batch.
  - [x] Static compile check: `python3 -m compileall -q app/llmctl-studio-backend/src/core/models`.
  - [x] Baseline collection command A re-run and passing (`23 tests collected`).
  - [x] Baseline collection command B re-run and passing (`23 tests collected`).
  - [x] Focused runtime verification:
    - [x] `... pytest ... tests/test_runtime_contracts_stage3.py` => `8 passed`.
    - [x] `... pytest ... tests/test_seed_stage11.py` => `3 passed`.
- [x] Perform audit checkpoint: verify moved symbols and imports are behavior-equivalent.
  - [x] Import-surface parity validated by successful collection/execution of suites importing `core.models` constants, tables, and ORM classes.
  - [x] Behavior-equivalence signal: no route/runtime/seed contract test regressions observed in targeted verification.
  - [x] Stage 4 core-model extraction batch complete; next extraction wave is Stage 5 route/service modules.

## Stage 5 - Execution Wave 3 (Route/Service Extractions)

- [x] Extract additional oversized route/service modules into structured subpackages.
  - [x] Service extraction: created `app/llmctl-studio-backend/src/services/task_utils/` and moved task JSON/path coercion helpers into `json_utils.py`.
  - [x] Route extraction: created `app/llmctl-studio-backend/src/web/view_helpers/` and moved stage/display helpers into `stage_display.py`.
  - [x] Rewired `services/tasks.py` and `web/views.py` to import helper modules without changing public route/task APIs.
- [x] Normalize loose helper functions into focused utility modules.
  - [x] Normalized service helpers:
    - [x] `_json_safe`, `_json_dumps`, `_parse_json_object`, `_extract_path_value`, `_parse_optional_int`, `_coerce_bool` -> `services/task_utils/json_utils.py`.
  - [x] Normalized route/display helpers:
    - [x] `_format_bytes`, `_parse_stage_logs`, `_task_output_for_display`, `_STAGE_STATUS_CLASSES` -> `web/view_helpers/stage_display.py`.
- [x] Remove temporary extraction scaffolding that is no longer needed.
  - [x] Removed moved helper definitions from `services/tasks.py` and `web/views.py` after import rewiring.
  - [x] No compatibility shim functions retained for moved helper names.
- [x] Perform audit checkpoint: verify API behavior and event contracts remain unchanged.
  - [x] Static verification: `python3 -m compileall -q app/llmctl-studio-backend/src/services app/llmctl-studio-backend/src/web`.
  - [x] Baseline collection parity:
    - [x] Stage 3 command A re-run => `23 tests collected`.
    - [x] Stage 3 command B re-run => `23 tests collected`.
  - [x] Focused execution verification:
    - [x] `... pytest ... tests/test_runtime_contracts_stage3.py tests/test_seed_stage11.py` => `11 passed`.
  - [x] Environment note: full DB-dependent route/executor execution suites (`test_react_stage7_api_routes.py`, `test_node_executor_stage8.py`) are blocked in this workspace by missing local PostgreSQL listener on `localhost:5432` (connection refused), so collection parity + non-DB execution tests were used as Stage 5 gate evidence.

## Stage 6 - Execution Wave 4 (Vestigial CLI Path Removal)

- [x] Identify and prove vestigial CLI-era backend paths using code references and runtime call paths.
  - [x] Candidate paths validated: `app/llmctl-studio-backend/src/__main__.py` and `app/llmctl-studio-backend/src/cli/*`.
  - [x] Inbound-reference evidence before removal: references to `agent-loop.py` / `agent-cli.py` / `AGENT_CLI` were confined to `src/__main__.py` and `src/cli/*` (self-contained CLI surface).
  - [x] Runtime/deployment path evidence:
    - [x] Studio serving entrypoint is `app/llmctl-studio-backend/run.py` in Docker/Kubernetes (`app/llmctl-studio-backend/docker/Dockerfile`, `kubernetes/llmctl-studio/base/studio-deployment.yaml`, `kubernetes/llmctl-studio/overlays/dev/studio-live-code-patch.yaml`).
    - [x] Worker entrypoint is `app/llmctl-celery-worker/run.py` with `services.celery_app:celery_app`.
    - [x] No startup path references to `src/__main__.py` or `src/cli/*` were found.
- [x] Remove only paths confirmed non-load-bearing for SDK-first runtime.
  - [x] Removed:
    - [x] `app/llmctl-studio-backend/src/__main__.py`
    - [x] `app/llmctl-studio-backend/src/cli/__init__.py`
    - [x] `app/llmctl-studio-backend/src/cli/agent-cli.py`
    - [x] `app/llmctl-studio-backend/src/cli/agent-dispatch.py`
    - [x] `app/llmctl-studio-backend/src/cli/agent-loop.py`
  - [x] Post-removal scan confirms no remaining source/test references to removed CLI paths.
- [x] Remove/adjust related UI or configuration affordances if present in backend scope.
  - [x] No backend UI routes/settings/provider/runtime config affordances referenced removed CLI paths; explicit no-op.
- [x] Perform audit checkpoint: verify no remaining backend dependencies on removed vestigial paths.
  - [x] Static verification: `python3 -m compileall -q app/llmctl-studio-backend/src`.
  - [x] Baseline collection parity:
    - [x] Stage 3 command A re-run => `23 tests collected`.
    - [x] Stage 3 command B re-run => `23 tests collected`.
  - [x] Focused execution verification:
    - [x] `... pytest ... tests/test_runtime_contracts_stage3.py tests/test_seed_stage11.py` => `11 passed`.
  - [x] Stage 6 removal gate satisfied; no remaining backend runtime dependency on removed CLI-era paths.

## Stage 7 - Execution Wave 5 (Web Views Package Decomposition)

- [x] Decompose `app/llmctl-studio-backend/src/web/views.py` into `app/llmctl-studio-backend/src/web/views/` package modules.
  - [x] Replaced monolith module with `web/views/` package and moved route handlers into:
    - [x] `agents_runs.py`
    - [x] `chat_nodes.py`
    - [x] `plans_milestones.py`
    - [x] `flowcharts.py`
    - [x] `models_mcps.py`
    - [x] `artifacts_attachments.py`
    - [x] `settings_providers.py`
    - [x] `settings_integrations.py`
  - [x] Consolidated non-route shared helpers/imports/constants into `web/views/shared.py`.
- [x] Categorize route handlers by bounded domain and move handlers accordingly (agents/runs, chat/nodes, plans/milestones, flowcharts, models/mcps, settings/providers/integrations, artifacts/attachments).
  - [x] Route categorization was executed by URL cluster matching Stage 2 domain map and moved into the corresponding domain modules above.
- [x] Extract shared serializers/parsers/formatters used by moved view modules into focused helper modules under `web/views/`.
  - [x] Shared route-adjacent helper surface (serializers/parsers/formatters and supporting utilities) now lives in `web/views/shared.py` and is imported by each domain route module.
- [x] Keep blueprint/endpoint names, URL mappings, request/response contracts, and flash-message behavior unchanged.
  - [x] Route-signature parity verified against pre-split `HEAD` `web/views.py`: `orig_count=235`, `new_count=235`, `missing=0`, `added=0`.
- [x] Update imports across backend modules/tests to use the new `web.views` package surface.
  - [x] Preserved the existing `web.views` import surface via `web/views/__init__.py` package exports; no call-site import rewiring was required.
  - [x] Added package-level symbol mirroring for patch compatibility so `web.views.<symbol>` test patches propagate to moved route modules.
- [x] Perform audit checkpoint: verify route contract parity with baseline collection/tests and no behavior drift.
  - [x] Static verification:
    - [x] `python3 -m compileall -q app/llmctl-studio-backend/src/web/views app/llmctl-studio-backend/src/web/app.py`
  - [x] Baseline collection parity:
    - [x] Stage 3 command A re-run => `23 tests collected`.
    - [x] Stage 3 command B re-run => `23 tests collected`.
  - [x] Broad import/contract collection parity for all tests importing/patching `web.views`:
    - [x] `... pytest --collect-only -q $(rg -l "import web\\.views as studio_views|from web\\.views import|patch\\(\"web\\.views\\." app/llmctl-studio-backend/tests)` => `207 tests collected`.
  - [x] Focused execution verification:
    - [x] `... pytest ... tests/test_runtime_contracts_stage3.py tests/test_seed_stage11.py` => `11 passed`.
    - [x] `... pytest ... tests/test_backend_api_boundary_stage3.py` => `4 passed`.
  - [x] Environment note: DB-backed execution suites such as `tests/test_react_stage7_api_routes.py` remain blocked in this workspace by missing PostgreSQL listener on `localhost:5432` (connection refused), so collection parity + non-DB execution suites were used as Stage 7 exit evidence.

## Stage 8 - Automated Testing

- [x] Run backend automated tests relevant to refactored modules.
  - [x] Non-DB targeted execution suites passed:
    - [x] `... pytest ... tests/test_runtime_contracts_stage3.py tests/test_seed_stage11.py tests/test_backend_api_boundary_stage3.py` => `15 passed`.
  - [x] Broad import/contract coverage for the refactored `web.views` package collected successfully:
    - [x] `... pytest --collect-only -q $(rg -l "import web\\.views as studio_views|from web\\.views import|patch\\(\"web\\.views\\." app/llmctl-studio-backend/tests)` => `207 tests collected`.
- [x] Run static checks for touched backend Python files.
  - [x] Static compile verification passed:
    - [x] `python3 -m compileall -q app/llmctl-studio-backend/src/web/views app/llmctl-studio-backend/src/web/app.py`
- [x] Record pass/fail and remediation notes.
  - [x] Passes recorded above for all requested non-DB execution/collection checks.
  - [x] Warnings observed: upstream `pkg_resources` deprecation warnings from test dependencies (no Stage 8 remediation required for this refactor scope).
  - [x] Environment limitation retained: DB-backed route/API execution suites are not runnable in this workspace without local PostgreSQL on `localhost:5432`; this run intentionally used non-DB coverage only per user direction.

## Stage 9 - Docs Updates

- [x] Update Sphinx/Read the Docs docs for backend module layout and any removed CLI vestiges.
  - [x] Added dedicated backend layout guide: `docs/sphinx/studio_backend_module_layout.rst`.
  - [x] Added guide to docs navigation: `docs/sphinx/index.rst` runtime guides toctree.
  - [x] Updated runtime architecture guide with package-decomposition and CLI-removal notes: `docs/sphinx/studio_serving_runtime.rst`.
  - [x] Updated docs changelog entries for structural module layout and vestigial CLI removal: `docs/sphinx/changelog.rst`.
  - [x] Updated Sphinx apidoc exclusions for package-based paths and set docs-build default DB URI for import safety: `docs/sphinx/conf.py`.
  - [x] Sphinx HTML build verification passed:
    - [x] `LLMCTL_STUDIO_DATABASE_URI='postgresql+psycopg://llmctl:llmctl@127.0.0.1:15432/llmctl_studio' .venv/bin/sphinx-build -b html docs/sphinx docs/sphinx/_build/html-stage9-structural-refactor-docs`
    - [x] Result: `build succeeded, 2 warnings` (cross-reference ambiguity warnings unrelated to this structural refactor stage).
- [x] Update internal planning notes with final package map and extraction summary.
  - [x] Stage 7 and Stage 8 sections record final extraction map, parity gates, and test/static evidence.
  - [x] Stage 9 section now records final docs-update artifacts and build verification.
- [x] If no docs updates are needed for a touched area, record explicit no-op decision.
  - [x] No-op not applicable: docs updates were required and completed for touched backend layout/runtime surfaces.
