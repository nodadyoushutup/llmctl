Agent Skill Binding
===================

Overview
--------

Studio skill binding is Agent-first. Skills are authored and managed on Agent
records, then resolved at runtime for nodes that reference those Agents.

Compatibility Mode
------------------

Runtime compatibility mode is controlled by
``node_skill_binding_mode`` in runtime settings:

- ``warn``: ignore legacy node-level ``skill_ids`` writes and surface
  deprecation metadata
- ``reject``: fail legacy node-level ``skill_ids`` writes with explicit
  validation errors

Migration Notes
---------------

- Existing environments can run in ``warn`` mode during transition.
- New integrations should use Agent-level skill assignment only.
- Node payloads should not carry direct skill-binding state once migration is
  complete.

See Also
--------

- :doc:`provider_runtime`
