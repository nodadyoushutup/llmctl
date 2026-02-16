# Google Cloud + Workspace Integration Split Plan

## Stage 0 - Requirements Gathering
- [x] Confirm target direction: separate Google Cloud and Google Workspace integrations with independent service-account credentials.
- [x] Confirm Workspace scope target: full-suite intent, single integrated MCP preference, but service-account-only policy for this implementation.
- [x] Confirm auth policy: Workspace integration remains service-account-only for now (no OAuth rollout in this stage).
- [x] Confirm delegated user handling: Workspace delegated user is optional, not required globally.
- [x] Confirm implementation scope for now: ship Workspace scaffold + guard; do not activate Workspace integrated MCP runtime yet.
- [x] Confirm migration policy: auto-migrate legacy `google_drive` settings into split providers.
- [x] Confirm Drive credential source after split: Drive-related features read from `google_workspace`.

## Stage 1 - Code Planning
- [x] Define provider model split:
  - [x] `google_cloud` provider owns Cloud-specific settings and Cloud MCP controls.
  - [x] `google_workspace` provider owns Workspace service-account settings and delegated user settings.
  - [x] Legacy `google_drive` provider is migrated/retired.
- [x] Define migration behavior:
  - [x] Copy legacy `service_account_json` into both `google_cloud` and `google_workspace` when target keys are empty.
  - [x] Move `google_cloud_project_id` and `google_cloud_mcp_enabled` into `google_cloud`.
  - [x] Remove migrated `google_drive` rows.
- [x] Define UI/route changes:
  - [x] Add separate Integrations tabs/routes/forms for Google Cloud and Google Workspace.
  - [x] Keep legacy Google Drive route as compatibility redirect.
- [x] Define MCP behavior:
  - [x] Cloud MCP continues working from `google_cloud`.
  - [x] Workspace MCP settings/toggle are stored but runtime server creation is guarded off for now.
- [x] Define Drive consumer changes:
  - [x] Studio/RAG Drive checks and verification paths read Workspace credentials.
  - [x] RAG web app uses Workspace provider for Drive settings.
- [x] Define test coverage + docs updates to close implementation.

## Stage 2 - Provider Split + Migration
- [x] Implement auto-migration helper from legacy `google_drive` to `google_cloud` + `google_workspace`.
- [x] Wire migration helper into settings reads so legacy installs migrate automatically.
- [x] Add/adjust integration overview payload for both providers.

## Stage 3 - Studio Integrations UI + Routes
- [x] Add Google Cloud tab/route/form backed by `google_cloud`.
- [x] Add Google Workspace tab/route/form backed by `google_workspace`.
- [x] Add Workspace delegated user and Workspace MCP toggle fields (scaffold-only behavior).
- [x] Keep legacy `/settings/integrations/google-drive` route as redirect compatibility path.
- [x] Update settings dashboard integration summary cards for both Cloud and Workspace.

## Stage 4 - Drive Credential Source Cutover
- [x] Update Studio RAG views to read Drive credentials from `google_workspace`.
- [x] Update RAG web app/settings flows to read/write `google_workspace` for Drive service account.
- [x] Preserve existing Google Drive source behavior while switching credential provider.

## Stage 5 - Integrated MCP Guarding
- [x] Update integrated MCP sync to use `google_cloud` provider for Cloud MCP.
- [x] Add Workspace integrated MCP key/scaffold wiring in sync lifecycle.
- [x] Enforce guard so Workspace MCP server is not created yet, even when enabled, with clear comment/log context.
- [x] Ensure stale Workspace managed server entries are removed if present.

## Stage 6 - Automated Testing
- [x] Add/update tests for provider split migration behavior.
- [x] Add/update tests for Cloud MCP sync using `google_cloud` provider.
- [x] Add/update tests proving Workspace MCP server is guarded off.
- [x] Run targeted automated tests for touched Studio/RAG modules.

## Stage 7 - Docs Updates
- [x] Update Sphinx docs/changelog with Google Cloud/Workspace split behavior.
- [x] Document Workspace scaffold guard status (settings exist, runtime MCP intentionally disabled pending supported path).
- [x] Record migration/cutover notes for legacy `google_drive` settings.
