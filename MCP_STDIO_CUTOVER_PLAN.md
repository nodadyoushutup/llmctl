# MCP stdio cutover plan

**Work checklist instructions**
- Check off each subtask as it is completed.
- Use `- [x]` for done and `- [ ]` for not done.
- Update this file in-place as work progresses.

Goal: move all MCP servers to stdio transport, remove HTTP proxy layers, and update Studio to launch MCP servers via `command`/`args` (Docker now, kubectl later). This plan covers docker-compose changes, DB + seed updates, and operational cutover.

## Stage 0 - Scope and decisions

- [x] Confirm deployment target(s): local docker-compose in this repo; Studio runs in Docker (see `docker/docker-compose.yml`). Staging/prod/k8s cutover is out of scope for this pass.
- [x] Decide the stdio launcher for each MCP server:
  - [x] **Docker now**: `command = "docker"`, `args = ["exec", "-i", <container>, <server>, "stdio", ...]`
  - [x] **Kubernetes later**: keep `kubectl exec -i <pod> -- <server> stdio` template for follow-on work.
- [x] Decide how MCP containers remain alive (so `docker exec` works):
  - [x] Use `command: ["sleep", "infinity"]` for MCP containers (github-mcp, jira-mcp, chromadb-mcp, llmctl-mcp).
  - [x] Keep server binaries installed in the container image (already true for current images).

Deliverables:
- [x] Final stdio command templates per MCP server (Docker exec):
  - GitHub: `docker exec -i github-mcp github-mcp-server stdio`
  - Jira: `docker exec -i jira-mcp mcp-atlassian --transport stdio`
  - Chroma: `docker exec -i chromadb-mcp chromadb-mcp --client-type http --host chromadb --port 8000 --ssl false`
  - LLMCTL MCP: `docker exec -i llmctl-mcp env LLMCTL_MCP_TRANSPORT=stdio python3 app/llmctl-mcp/run.py`
- [x] Decision on container keepalive command: `command: ["sleep", "infinity"]`.

## Stage 1 - DB configuration updates (runtime configs)

Update MCP server configs in the database to use stdio `command`/`args` (not HTTP URLs). This is a DB update, not just seed.

Targets (examples):
- [x] GitHub:
  - `command = "docker"`
  - `args = ["exec", "-i", "github-mcp", "/server/github-mcp-server", "stdio"]`
- [x] Jira:
  - `command = "docker"`
  - `args = ["exec", "-i", "jira-mcp", "mcp-atlassian", "--transport", "stdio"]`
- [x] Chroma:
  - `command = "docker"`
  - `args = ["exec", "-i", "chromadb-mcp", "chromadb-mcp", "--client-type", "http", "--host", "chromadb", "--port", "8000", "--ssl", "false"]`
- [x] LLMCTL MCP:
  - `command = "docker"`
  - `args = ["exec", "-i", "llmctl-mcp", "env", "LLMCTL_MCP_TRANSPORT=stdio", "python3", "app/llmctl-mcp/run.py"]`

Notes:
- The LLMCTL MCP `run.py` may need a `--transport` flag or `LLMCTL_MCP_TRANSPORT=stdio` if not already supported. Verify before cutover.
- Ensure MCP server logs are on stderr to avoid corrupting MCP stdout.

Deliverables:
- [x] DB migration script or admin task to update `MCPServer.config_json`.
- [x] Validation script to print parsed MCP configs.

## Stage 2 - Seed updates

Update `app/llmctl-studio/src/core/seed.py` to match the new stdio configs, so fresh environments align with the DB standard.

Deliverables:
- [x] Updated `MCP_SERVER_SEEDS` entries for GitHub, Jira, Chroma, LLMCTL MCP.
- [x] Verify seed format via `format_mcp_config` to ensure valid TOML.

## Stage 3 - docker-compose and image changes

Remove HTTP proxy layers and switch MCP containers to stdio-only, with keepalive commands.

Changes:
- [x] **github-mcp**:
  - [x] Remove `mcp-proxy` usage; no need for HTTP port mapping.
  - [x] Keep container alive with `command: ["sleep", "infinity"]` (or similar).
- [x] **jira-mcp**:
  - [x] Remove `--transport streamable-http` from compose.
  - [x] Keep container alive.
- [x] **chromadb-mcp**:
  - [x] Remove `mcp-proxy` wrapper (simplify Dockerfile or use upstream image directly).
  - [x] Keep container alive.
- [x] **llmctl-mcp**:
  - [x] No HTTP server required for stdio; keep container alive if it is only used via `docker exec`.

Deliverables:
- [x] Updated `docker/docker-compose.yml` with no MCP HTTP ports (except any other services that still need them).
- [x] Updated Dockerfiles to remove `mcp-proxy` layers where applicable.

## Stage 4 - Studio container updates

If Studio runs in Docker, mount the Docker socket so `docker exec` works.

Changes:
- [x] Add volume mount to Studio service (compose/k8s):
  - [x] `/var/run/docker.sock:/var/run/docker.sock`
- [x] Ensure `docker` CLI is available in the Studio container image.

Deliverables:
- [x] Updated Studio container definition and/or base image to include Docker CLI.

## Stage 5 - Code updates and validation

- [x] Ensure `app/llmctl-studio/src/services/tasks.py` accepts stdio MCP config for all targets.
- [x] Validate MCP config parsing with `parse_mcp_config` and `_build_mcp_overrides_from_configs`.
- [x] Verify MCP session creation for each agent (Gemini/Claude) works with stdio commands (command/config build validated; runtime CLI not executed).

Validation checks:
- [ ] Launch a test task with each MCP server attached.
- [ ] Confirm MCP tool listing works and responses flow back to the LLM.
- [ ] Confirm no stdout logging from MCP servers (stderr only for logs).

Deliverables:
- [ ] Test results captured in a short checklist.

## Stage 6 - Cutover and rollback plan

Cutover:
- [ ] Deploy docker-compose changes.
- [ ] Apply DB config updates.
- [ ] Restart Studio and MCP containers.
- [ ] Run validation checks.

Rollback:
- [ ] Restore DB configs to HTTP URLs.
- [ ] Re-enable mcp-proxy and HTTP ports in docker-compose.
- [ ] Restart services.

Deliverables:
- [x] A short runbook for cutover and rollback.

Runbook (short)

Pre-cutover snapshot:
- Save current MCP configs for rollback reference:
  - `python3 app/llmctl-studio/scripts/print_mcp_configs.py > /tmp/mcp-configs.before.json`

Cutover steps:
1) Apply docker-compose stdio changes:
   - `docker compose -f docker/docker-compose.yml up -d --build github-mcp jira-mcp chromadb-mcp llmctl-mcp llmctl-studio`
2) Apply DB stdio configs:
   - `python3 app/llmctl-studio/scripts/update_mcp_stdio_configs.py --apply --print`
3) Restart Studio and MCP containers (if not already restarted by compose):
   - `docker compose -f docker/docker-compose.yml restart llmctl-studio github-mcp jira-mcp chromadb-mcp llmctl-mcp`
4) Run validation checks (Stage 5 checklist):
   - Launch a test task per MCP server and verify tool listing + responses.

Rollback steps:
1) Restore DB configs to HTTP:
   - Use the saved `/tmp/mcp-configs.before.json` as the source of truth.
   - Reapply prior `config_json` values (or restore from DB backup).
2) Re-enable mcp-proxy + HTTP ports:
   - Revert docker-compose + Dockerfile changes from Stage 3.
3) Restart services:
   - `docker compose -f docker/docker-compose.yml up -d --build`
   - `docker compose -f docker/docker-compose.yml restart llmctl-studio github-mcp jira-mcp chromadb-mcp llmctl-mcp`

## Open questions

- Will Studio always run in Docker (so docker socket mount is required)?
- Are any MCP servers required outside of Studio (other services expecting HTTP)?
- Do we want to keep streamable-http as a fallback for k8s or remove entirely?
