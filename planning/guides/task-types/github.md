# GitHub Code Review Task (kind = "github")

See `planning/guides/task-types/README.md` for shared execution details and payload conventions.

How it works
- Created by `github_pull_request_code_review` in `app/llmctl-studio/src/web/views.py`.
- Uses the Code Reviewer agent with the GitHub MCP server attached.
- Prompt is plain text built by `_build_github_code_review_prompt`.
- GitHub repo/workspace info is prefixed into the text (not JSON fields).

Example final payload
```
Default GitHub repository: org/repo
Workspace path (checked out from default repo): /path/to/workspaces/task-456

You are a Code Reviewer focused on GitHub pull requests.
Pull request to review: org/repo#42
Title: Example PR
URL: https://github.com/org/repo/pull/42

Requirements:
- Use the GitHub MCP tools to read the PR, diff, and relevant files.
- Leave feedback as a comment on the pull request (not just in this response).
- Start the comment with pass or fail.
- Cite explicit files/lines or include short code blocks with file paths.
- Do a full, proper code review every time.
- If you cannot post a comment, explain why in your output.
```
