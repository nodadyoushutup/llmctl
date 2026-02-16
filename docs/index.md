# llmctl Documentation

This site is built with Sphinx and the Read the Docs theme.
Planning and execution artifacts are tracked in the repository `planning/` directory.

## Local build

```bash
python3 -m pip install -r docs/requirements.txt
make docs
```

```{toctree}
:maxdepth: 2
:caption: Guides

vllm-local-gpu
flowchart-node-config
FLOWCHART_CONNECTOR_USER_GUIDE
FLOWCHART_CONNECTOR_RELEASE_NOTE_2026-02-16
llmctl-mcp-tool-prompts
task-types/README
task-types/quick
task-types/autorun
task-types/github
```
