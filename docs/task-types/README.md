# Task Types and Codex Exec Payloads

This folder tracks how each task type is created and what payload is finally sent to `codex exec`.

Task type docs:
- quick.md
- pipeline.md
- github.md
- autorun.md

## Execution Path (all tasks)

- An `AgentTask` is created (quick, pipeline, github, or autorun loop).
- `_execute_agent_task` in `app/llmctl-studio/src/services/tasks.py` formats the prompt, injects GitHub repo context when a repo is configured, injects integration settings, and builds the final payload.
- If scripts are attached to the agent, they are staged into the task workspace and run per stage. Task-level scripts are not supported yet.
- `codex exec` is launched with `--model` and any MCP overrides, and the payload is written to stdin.

## Task Stages

Tasks run through the following stages in order. Script stages run only when scripts are attached to the agent.

1. Integration (GitHub clone/fetch + integration setup)
2. Pre Init scripts
3. Init scripts
4. Post Init scripts
5. LLM query (Codex exec)
6. Post Autorun scripts

Skill scripts are not executed. They are injected into the prompt as a helper map of available script paths and descriptions.

## Common Payload Fields (only when the payload is JSON)

- `prompt` (string): the actual instruction text.
- `output_instructions` (string): output formatting directives (for example, no follow-up questions).
- `role` (object): role profile from the DB (`name`, `description`, `details`).
- `agent` (object): agent profile from the DB (`description`, `autoprompt`, `scripts`).
- `github_repo` (string): injected when using the GitHub MCP and the default repo is set.
- `workspace_path` (string): injected after a repo checkout when a workspace exists.
- `workspace_note` (string): describes the workspace path.
- `scripts` (list, optional): injected only when no `prompt` field exists and skill scripts are attached.

When a `prompt` string exists, skill scripts are injected as a prefixed "Available helper scripts" block.

If the payload is plain text, repo/workspace info is injected as prefixed lines instead of JSON fields.

Integration settings are injected into JSON payloads as an `integrations` object; for plain text prompts, an `Integrations:` block is prefixed.

## Notes on Codex Exec

- The CLI is invoked as `codex exec` with an optional `--model` flag and MCP overrides from the agent configuration.
- The payload shown above is written to stdin exactly as stored in `AgentTask.prompt` at execution time.
