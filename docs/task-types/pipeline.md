# Pipeline Task (kind = "pipeline")

See `docs/task-types/README.md` for shared execution details and payload conventions.

How it works
- Created by `run_pipeline` in `app/llmctl-studio/src/services/tasks.py` from a `TaskTemplate.prompt`.
- The prompt can be plain text or JSON; the payload is passed through as-is.
- If GitHub repo injection applies:
  - For JSON payloads with `prompt`, the `prompt` string is prefixed.
  - For JSON payloads without `prompt`, `github_repo`, `workspace_path`, and `workspace_note` are added (if missing).
  - For plain text, the repo/workspace lines are prefixed.

Example final payload (JSON template + repo injection)
```json
{
  "github_repo": "org/repo",
  "prompt": "Default GitHub repository: org/repo\n\nRun the smoke test suite.",
  "workspace_note": "workspace_path is a git checkout of github_repo.",
  "workspace_path": "/path/to/workspaces/task-123"
}
```
