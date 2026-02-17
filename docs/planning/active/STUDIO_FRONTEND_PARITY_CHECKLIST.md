# Studio Frontend Parity Checklist

Purpose: track React parity against legacy Flask GUI routes during Stage 5 migration.

## Wave 1 - Core and Chat Read Flows
- [x] Overview shell (`/overview` -> `/`).
- [x] API diagnostics (`/api/health` + `/api/chat/activity` -> `/api-diagnostics`).
- [x] Chat activity list (`/chat/activity` -> `/chat/activity`).
- [x] Chat thread detail read (`/chat` thread context -> `/chat/threads/:threadId`).

## Wave 2 - Agent Execution Flows
- [ ] Agents list/detail/create/edit (`/agents*`).
- [ ] Runs list/detail/create/edit/lifecycle (`/runs*`).
- [ ] Quick tasks and node detail/status (`/quick`, `/nodes*`).

## Wave 3 - Planning and Knowledge Objects
- [ ] Plans list/detail/edit + stage/task mutations (`/plans*`).
- [ ] Milestones list/detail/edit (`/milestones*`).
- [ ] Task templates CRUD (`/task-templates*`).
- [ ] Memories CRUD (`/memories*`).

## Wave 4 - Flowchart System
- [ ] Flowchart list/new/detail/edit (`/flowcharts*`).
- [ ] Flowchart history and run detail (`/flowcharts/*/history*`).
- [ ] Flowchart graph/runtime/validation/execution controls.
- [ ] Flowchart node utility/model/mcp/script/skill mutations.

## Wave 5 - Studio Assets and Catalogs
- [ ] Skills CRUD/import/export (`/skills*`).
- [ ] Scripts CRUD (`/scripts*`).
- [ ] Attachments list/detail/file/delete (`/attachments*`).
- [ ] Models CRUD/default management (`/models*`).
- [ ] MCP server CRUD/detail (`/mcps*`).

## Wave 6 - Settings and Runtime Controls
- [ ] Roles CRUD (`/roles*`, `/settings/roles*`).
- [ ] Core/provider settings (`/settings/core`, `/settings/provider*`).
- [ ] Runtime/chat settings (`/settings/runtime*`, `/settings/chat`).
- [ ] Git config + integrated settings sections (`/settings/integrations*`).

## Wave 7 - Integrations and RAG Surfaces
- [ ] GitHub browser and pull-request review views (`/github*`).
- [ ] Jira/Confluence explorer routes (`/jira*`, `/confluence`).
- [ ] Chroma collection explorer (`/chroma*`).
- [ ] RAG chat + sources CRUD and quick index/delta index (`/rag*`).

## Global Parity Gates
- [ ] Mutation parity achieved for create/edit/delete workflows across all waves.
- [ ] Validation and error feedback parity achieved.
- [ ] Long-running task feedback and realtime update parity achieved.
- [ ] Legacy Flask GUI can be disabled without user-facing regressions.
