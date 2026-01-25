# Autorun Task (agent autorun loop, kind defaults to "task")

## Example Payloads

### Agent selected + no integrations
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
    },
    "autoprompt": "If given no other prompt direction, fallback to pulling a random Jira ticket and posting a Hello World comment",
    "scripts": {
      "description": "Use Skill scripts to accomplish simple tasks. The rest of the scripts are performed via task python",
      "pre_init": [
        {
          "description": "Used to do XYZ",
          "path": "path/to/a/script.py"
        }
      ],
      "post_init": [
        {
          "description": "Used to do XYZ",
          "path": "path/to/a/script.py"
        }
      ],
      "post_run": [
        {
          "description": "Used to do XYZ",
          "path": "path/to/a/script.py"
        }
      ],
      "skill": [
        {
          "description": "Used to do XYZ",
          "path": "path/to/a/script.py"
        }
      ]
    }
  },
  "output_instructions": "Do not ask follow-up questions. This is a one-off task."
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
    },
    "autoprompt": "If given no other prompt direction, fallback to pulling a random Jira ticket and posting a Hello World comment",
    "scripts": {
      "description": "Use Skill scripts to accomplish simple tasks. The rest of the scripts are performed via task python",
      "pre_init": [
        {
          "description": "Used to do XYZ",
          "path": "path/to/a/script.py"
        }
      ],
      "post_init": [
        {
          "description": "Used to do XYZ",
          "path": "path/to/a/script.py"
        }
      ],
      "post_run": [
        {
          "description": "Used to do XYZ",
          "path": "path/to/a/script.py"
        }
      ],
      "skill": [
        {
          "description": "Used to do XYZ",
          "path": "path/to/a/script.py"
        }
      ]
    }
  },
  "output_instructions": "Do not ask follow-up questions. This is a one-off task.",
  "integrations": {
    "github": {
      "repo": "org/repo",
      "workspace": "/path/to/workspaces/task-123",
      "note": "Workspace is a local git clone of the GitHub repo. All instructions in the prompt relate to the repo above and its local workspace."
    }
  }
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
    },
    "autoprompt": "If given no other prompt direction, fallback to pulling a random Jira ticket and posting a Hello World comment",
    "scripts": {
      "description": "Use Skill scripts to accomplish simple tasks. The rest of the scripts are performed via task python",
      "pre_init": [
        {
          "description": "Used to do XYZ",
          "path": "path/to/a/script.py"
        }
      ],
      "post_init": [
        {
          "description": "Used to do XYZ",
          "path": "path/to/a/script.py"
        }
      ],
      "post_run": [
        {
          "description": "Used to do XYZ",
          "path": "path/to/a/script.py"
        }
      ],
      "skill": [
        {
          "description": "Used to do XYZ",
          "path": "path/to/a/script.py"
        }
      ]
    }
  },
  "output_instructions": "Do not ask follow-up questions. This is a one-off task.",
  "integrations": {
    "jira": {
      "email": "user@example.com",
      "site": "https://example.atlassian.net",
      "board": "ENG",
      "project_key": "ENG",
      "note": "All instructions in the prompt relate to the Jira project/board above. If a DNS lookup fails, retry until it succeeds."
    }
  }
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
    },
    "autoprompt": "If given no other prompt direction, fallback to pulling a random Jira ticket and posting a Hello World comment",
    "scripts": {
      "description": "Use Skill scripts to accomplish simple tasks. The rest of the scripts are performed via task python",
      "pre_init": [
        {
          "description": "Used to do XYZ",
          "path": "path/to/a/script.py"
        }
      ],
      "post_init": [
        {
          "description": "Used to do XYZ",
          "path": "path/to/a/script.py"
        }
      ],
      "post_run": [
        {
          "description": "Used to do XYZ",
          "path": "path/to/a/script.py"
        }
      ],
      "skill": [
        {
          "description": "Used to do XYZ",
          "path": "path/to/a/script.py"
        }
      ]
    }
  },
  "output_instructions": "Do not ask follow-up questions. This is a one-off task.",
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
  }
}
```
