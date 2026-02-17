# ArgoCD Commit Push Autosync Skill Plan

## Stage 0: Requirements Gathering
- [x] Confirm target scope for this skill (llmctl-only vs reusable for any ArgoCD-managed repo).
  - Use the currently opened workspace repository as the commit/push target.
- [x] Confirm preferred skill name and trigger wording.
  - Skill name: `argocd-commit-push-autosync`.
- [x] Confirm whether to include executable helper scripts (git + argocd automation) or instructions-only workflow.
  - Implement script-backed workflow.
- [x] Confirm default git remote/branch behavior before push.
  - Push current checked-out branch to its configured upstream; fail if no upstream exists.
- [x] Confirm exact ArgoCD sync command policy (app-level sync, project-level behavior, and safety flags).
  - Default behavior: enable autosync only with `prune=true` and `selfHeal=true`.

## Stage 1: Code Planning
- [x] Define execution stages:
- [x] Stage 2: Initialize/create skill folder and metadata.
- [x] Stage 3: Implement workflow instructions and helper script for commit/push + autosync enablement.
- [x] Stage 4: Validate skill and run representative dry-run/safe checks.
- [x] Stage 5: Automated Testing.
- [x] Stage 6: Docs Updates.

## Stage 2: Skill Initialization
- [x] Create skill directory with required `SKILL.md` frontmatter and optional resources.
- [x] Generate/update `agents/openai.yaml` metadata for host skill listing.

## Stage 3: Skill Implementation
- [x] Implement commit/push prerequisite workflow guidance.
- [x] Implement ArgoCD autosync workflow guidance and safeguards.
- [x] Add helper script(s) if required and make them executable.

## Stage 4: Validation and Verification
- [x] Run skill validator and fix any schema or naming issues.
  - `python3 /home/nodadyoushutup/.codex/skills/.system/skill-creator/scripts/quick_validate.py /home/nodadyoushutup/.codex/skills/argocd-commit-push-autosync` -> `Skill is valid!`
- [x] Execute representative command path(s) in a safe way to verify script behavior.
  - `bash -n ~/.codex/skills/argocd-commit-push-autosync/scripts/commit_push_enable_autosync.sh` -> success
  - `~/.codex/skills/argocd-commit-push-autosync/scripts/commit_push_enable_autosync.sh --help` -> usage output verified
  - `~/.codex/skills/argocd-commit-push-autosync/scripts/commit_push_enable_autosync.sh --app llmctl-studio --dry-run` -> dry-run command sequence verified

## Stage 5: Automated Testing
- [x] Run targeted automated checks for new skill scripts/validators.
- [x] Record command outcomes and any remaining risk.
  - `python3 -m sphinx -q -b dummy docs/sphinx docs/_build/dummy` -> failed (`No module named sphinx`) in this environment.
  - Remaining risk: live ArgoCD autosync command path requires `argocd` CLI availability and valid app name at runtime.

## Stage 6: Docs Updates
- [x] Update relevant documentation to reference the new skill workflow.
  - Added `docs/sphinx/codex_host_skills.rst` and linked it from `docs/sphinx/index.rst`.
- [x] Move this completed plan to `docs/planning/archive/`.
