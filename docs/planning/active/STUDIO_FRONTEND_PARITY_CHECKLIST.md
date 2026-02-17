# Studio Frontend Parity Checklist

Purpose: track React parity against legacy Flask GUI routes during Stage 5 migration.

Status key:
- `Native React`: page/flow implemented directly in React components.
- `Legacy Bridge`: page/flow served through React shell by mirroring backend GUI route at `/api/...`.

## Wave 1 - Core and Chat Read Flows
- [x] Overview shell (`/overview` -> `/`) [Native React].
- [x] API diagnostics (`/api/health` + `/api/chat/activity` -> `/api-diagnostics`) [Native React].
- [x] Chat activity list (`/chat/activity` -> `/chat/activity`) [Native React].
- [x] Chat thread detail read (`/chat` thread context -> `/chat/threads/:threadId`) [Native React].

## Wave 2 - Agent Execution Flows
- [x] Runs read monitor in React (`/execution-monitor` -> `/api/runs/:id`) [Native React].
- [x] Nodes status monitor in React (`/execution-monitor` -> `/api/nodes/:id/status`) [Native React].
- [x] Agents full route coverage (`/agents`, `/agents/new`, `/agents/:id`, `/agents/:id/edit`) [Native React].
- [x] Runs full route coverage (`/runs`, `/runs/new`, `/runs/:id`, `/runs/:id/edit`) [Native React].
- [x] Quick+Nodes full route coverage (`/quick`, `/nodes`, `/nodes/new`, `/nodes/:id`) [Native React].

## Wave 3 - Planning and Knowledge Objects
- [x] Plans list/detail/edit + stage/task mutations [Legacy Bridge].
- [x] Milestones list/detail/edit [Legacy Bridge].
- [x] Task templates CRUD [Legacy Bridge].
- [x] Memories CRUD [Legacy Bridge].

## Wave 4 - Flowchart System
- [x] Flowchart list/new/detail/edit [Legacy Bridge].
- [x] Flowchart history and run detail [Legacy Bridge].
- [x] Flowchart graph/runtime/validation/execution controls [Legacy Bridge].
- [x] Flowchart node utility/model/mcp/script/skill mutations [Legacy Bridge].

## Wave 5 - Studio Assets and Catalogs
- [x] Skills CRUD/import/export [Legacy Bridge].
- [x] Scripts CRUD [Legacy Bridge].
- [x] Attachments list/detail/file/delete [Legacy Bridge].
- [x] Models CRUD/default management [Legacy Bridge].
- [x] MCP server CRUD/detail [Legacy Bridge].

## Wave 6 - Settings and Runtime Controls
- [x] Roles CRUD [Legacy Bridge].
- [x] Core/provider settings [Legacy Bridge].
- [x] Runtime/chat settings [Legacy Bridge].
- [x] Git config + integrated settings sections [Legacy Bridge].

## Wave 7 - Integrations and RAG Surfaces
- [x] GitHub browser and pull-request review views [Legacy Bridge].
- [x] Jira/Confluence explorer routes [Legacy Bridge].
- [x] Chroma collection explorer [Legacy Bridge].
- [x] RAG chat + sources CRUD and quick index/delta index [Legacy Bridge].

## Global Parity Gates
- [x] Mutation parity preserved by bridge coverage for not-yet-native routes.
- [x] Validation and error feedback preserved via native or bridge route behavior.
- [x] Long-running task feedback and realtime update parity preserved via native polling on execution routes.
- [x] Every legacy route now has a working React route surface (native or bridge).
