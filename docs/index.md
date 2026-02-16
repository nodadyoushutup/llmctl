# llmctl Documentation

This site is built with Sphinx and the Read the Docs theme.

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
FLOWCHART_CONNECTOR_ROLLOUT_2026-02-16
llmctl-mcp-tool-prompts
task-types/README
task-types/quick
task-types/autorun
task-types/github
RAG_STAGE0_BASELINE_SNAPSHOT_2026-02-16
RAG_STAGE1_AUDIT_2026-02-16
SKILLS_STAGE0_ARCHITECTURE_DECISION_RECORD_2026-02-16
```
