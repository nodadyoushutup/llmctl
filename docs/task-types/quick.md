# Quick Node (kind = "quick" or "chat")

Quick nodes do not accept task-level scripts. If no override agent is selected, runtime uses a hard-coded Quick profile (not a seeded database agent). Selecting an agent overrides that profile for the node. Quick nodes also support direct node-level model selection and optional MCP server selection. If no model is explicitly selected, runtime uses the configured default model, otherwise the first model in the list.

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
