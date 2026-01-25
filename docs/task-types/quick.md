# Quick Task (kind = "quick" or "chat")

Quick tasks do not accept task-level scripts. An agent is required (the seeded "Quick" agent is the default selection), and any scripts in the final payload are sourced from the selected agent profile, so `agent.scripts` is omitted from the examples below. The agent autoprompt is also omitted for quick tasks so the user prompt is the only instruction; the prompt text is preserved exactly as entered.

## Example Payloads

### Agent selected
```json
{
  "agent": {
    "description": "An intelligent senior engineer",
    "role": {
      "name": "Jacob",
      "description": "Senior development engineer",
      "details": {
        "personality": "Collaborative, pragmatic, direct",
        "focus": "Ship reliable software",
        "rituals": [
          "Clarify scope",
          "Write tests first when feasible"
        ]
      }
    }
  },
  "output_instructions": "Do not ask follow-up questions. This is a one-off task.",
  "prompt": "Say hello world"
}
```

### Agent selected + GitHub integration on
```json
{
  "agent": {
    "description": "An intelligent senior engineer",
    "role": {
      "name": "Jacob",
      "description": "Senior development engineer",
      "details": {
        "personality": "Collaborative, pragmatic, direct",
        "focus": "Ship reliable software",
        "rituals": [
          "Clarify scope",
          "Write tests first when feasible"
        ]
      }
    }
  },
  "integrations": {
    "github": {
      "repo": "org/repo",
      "workspace": "/path/to/workspaces/task-123",
      "note": "Workspace is a local git clone of the GitHub repo. All instructions in the prompt relate to the repo above and its local workspace."
    }
  },
  "output_instructions": "Do not ask follow-up questions. This is a one-off task.",
  "prompt": "Say hello world"
}
```

### Agent selected + Jira integration on
```json
{
  "agent": {
    "description": "An intelligent senior engineer",
    "role": {
      "name": "Jacob",
      "description": "Senior development engineer",
      "details": {
        "personality": "Collaborative, pragmatic, direct",
        "focus": "Ship reliable software",
        "rituals": [
          "Clarify scope",
          "Write tests first when feasible"
        ]
      }
    }
  },
  "integrations": {
    "jira": {
      "email": "user@example.com",
      "site": "https://example.atlassian.net",
      "board": "ENG",
      "project_key": "ENG",
      "note": "All instructions in the prompt relate to the Jira project/board above. If a DNS lookup fails, retry until it succeeds."
    }
  },
  "output_instructions": "Do not ask follow-up questions. This is a one-off task.",
  "prompt": "Say hello world"
}
```

### Agent selected + GitHub + Jira integration on
```json
{
  "agent": {
    "description": "An intelligent senior engineer",
    "role": {
      "name": "Jacob",
      "description": "Senior development engineer",
      "details": {
        "personality": "Collaborative, pragmatic, direct",
        "focus": "Ship reliable software",
        "rituals": [
          "Clarify scope",
          "Write tests first when feasible"
        ]
      }
    }
  },
  "integrations": {
    "github": {
      "repo": "org/repo",
      "workspace": "/path/to/workspaces/task-123",
      "note": "Workspace is a local git clone of the GitHub repo. All instructions in the prompt relate to the repo above and its local workspace."
    },
    "jira": {
      "email": "user@example.com",
      "site": "https://example.atlassian.net",
      "board": "ENG",
      "project_key": "ENG",
      "note": "All instructions in the prompt relate to the Jira project/board above. If a DNS lookup fails, retry until it succeeds."
    }
  },
  "output_instructions": "Do not ask follow-up questions. This is a one-off task.",
  "prompt": "Say hello world"
}
```
