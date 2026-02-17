Codex Host Skills
=================

Overview
--------

Host skills in ``~/.codex/skills`` add reusable local workflows for Codex.
Use them when a request matches a known operational routine and deterministic
command sequence.

ArgoCD Commit Push Autosync
---------------------------

Skill: ``argocd-commit-push-autosync``

Purpose:

- enforce GitOps order of operations for workspace repositories
- commit and push first
- then enable ArgoCD autosync with prune + self-heal

Default command:

.. code-block:: bash

   ~/.codex/skills/argocd-commit-push-autosync/scripts/commit_push_enable_autosync.sh \
     --app llmctl-studio \
     --message "chore: prepare studio restart"

Behavior:

- uses current workspace as the default repo
- fails on detached HEAD or missing upstream branch
- avoids force-push
- enables autosync only (no immediate one-off sync)

