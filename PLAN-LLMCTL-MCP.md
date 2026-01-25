# LLMCTL MCP Server Plan

## Goals
- Add a FastMCP-based HTTP server in `app/llmctl-mcp` that works with llmctl-studio.
- Provide CRUD tools for all core (Flask/SQLAlchemy) models.
- Provide control tools for tasks, runs, and pipelines (start/stop/cancel/toggle).
- Dockerize with a build script and docker-compose entry.

## Phases
1. **Scaffold & bootstrap**
   - [x] Create `app/llmctl-mcp` with `requirements.txt`, `run.py`, and server module.
   - [x] Initialize DB engine/session using existing llmctl-studio config/db helpers.
   - [x] Define model registry + serialization helpers.
2. **MCP tool surface**
   - [x] CRUD tools (`list`, `get`, `create`, `update`, `delete`) for all models.
   - [x] Action tools for: cancel task, start/cancel/end run, toggle pipeline loop,
     start pipeline, cancel pipeline run.
   - [x] Return JSON-friendly payloads (datetime ISO strings, ids, status flags).
3. **Containerization**
   - [x] Add `docker/llmctl-mcp.Dockerfile`.
   - [x] Add `docker/build-llmctl-mcp.sh`.
   - [x] Add compose service entry + env var for port.

## Open Questions
- [ ] Confirm preferred HTTP path (default `/mcp`) and port for llmctl-mcp.
- [ ] Decide auth requirements (if any) for the MCP endpoint.
