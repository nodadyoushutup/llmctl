# LLMCTL MCP Server Plan

## Goals
- Add a FastMCP-based HTTP server in `app/llmctl-mcp` that works with llmctl-studio.
- Provide CRUD tools for all core (Flask/SQLAlchemy) models.
- Provide control tools for tasks, autoruns, and pipelines (start/stop/cancel/toggle).
- Dockerize with a build script and docker-compose entry.
- Close functional gaps vs llmctl-studio UI workflows (tasks, agents, scripts, attachments, delete semantics).

## Phases
1. **Scaffold & bootstrap**
   - [x] Create `app/llmctl-mcp` with `requirements.txt`, `run.py`, and server module.
   - [x] Initialize DB engine/session using existing llmctl-studio config/db helpers.
   - [x] Define model registry + serialization helpers.
2. **MCP tool surface**
   - [x] CRUD tools (`list`, `get`, `create`, `update`, `delete`) for all models.
- [x] Action tools for: cancel task, start/cancel/end autorun, toggle pipeline loop,
     start pipeline, cancel pipeline run.
   - [x] Return JSON-friendly payloads (datetime ISO strings, ids, status flags).
3. **Containerization**
   - [x] Add `docker/llmctl-mcp.Dockerfile`.
   - [x] Add `docker/build-llmctl-mcp.sh`.
   - [x] Add compose service entry + env var for port.
4. **Functional parity + safety**
- [x] Task execution tools to enqueue autoruns/tasks (quick task, standard task, code review).
   - [x] Agent lifecycle tools (start/stop by agent id).
   - [x] Script file sync (write on create/update; cleanup on delete).
   - [x] Attachment file lifecycle (write on create; cleanup on detach/delete).
   - [x] Deletion semantics that mirror UI cleanup/detach behavior (agents, roles, templates, pipelines).
   - [x] Relationship helpers for ordered joins (agent scripts, task scripts, pipeline step ordering).

## Open Questions
- [ ] Confirm preferred HTTP path (default `/mcp`) and port for llmctl-mcp.
- [ ] Decide auth requirements (if any) for the MCP endpoint.
- [ ] Should MCP be allowed to read/write files (scripts/attachments/gitconfig/ssh keys) or remain DB-only?
- [ ] Should MCP reuse UI validations/formatting (e.g., MCP server TOML formatting) or allow raw DB updates?

## Gaps To Address (UI parity)
- [x] Enqueue agent tasks from MCP (quick task, standard task, GitHub code-review task).
- [x] Agent start/stop via MCP (UI creates an autorun and queues it).
- [x] Script updates must rewrite on-disk content, not just DB rows.
- [x] Attachment create/remove should manage files and detach from parents.
- [x] Delete operations must mirror UI cleanup:
  - [x] Agents: detach MCP servers/scripts, null out task.agent_id/run_id, delete autoruns.
  - [x] Roles: null out assigned agents.
  - [x] Task templates: detach/remove pipeline steps; null template references on tasks.
  - [x] Pipelines: delete steps/pipeline runs and associated tasks.
  - [x] Scripts: detach from agents before delete, remove script file.
  - [x] Attachments: unlink from tasks/templates/steps and delete file.

## Implementation Notes
- Prefer explicit MCP tools for complex workflows (e.g., `enqueue_task`, `start_agent`, `delete_agent_safe`)
  instead of generic `delete_record`.
- Where possible, reuse existing llmctl-studio helpers (storage, validation, task builders).
