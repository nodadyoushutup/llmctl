Agent Skill Binding
===================

Overview
--------

Studio skill binding is Agent-first. Skills are authored and managed on Agent
records, then resolved at runtime for nodes that reference those Agents.

Contract
--------

- Node-level ``skill_ids`` writes are unsupported and rejected.
- Flowchart graph updates must assign skills on the referenced Agent.
- Task nodes are prompt-driven and must provide ``config.task_prompt``.

Migration Notes
---------------

- Legacy runtime compatibility modes have been removed.
- Existing integrations must migrate to Agent-level skill assignment only.
- Node payloads should not carry direct skill-binding state.

See Also
--------

- :doc:`provider_runtime`
