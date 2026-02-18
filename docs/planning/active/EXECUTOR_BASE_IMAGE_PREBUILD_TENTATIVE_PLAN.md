# Executor Base Image Prebuild Tentative Plan

Goal: create a reusable prebuilt `llmctl-executor-base` image that bakes in CUDA runtime + vLLM so normal executor builds only layer app/runtime-specific content and complete much faster.

## Stage 0 - Requirements Gathering

- [x] Run Stage 0 interview with the user one question per turn and explicit options.
- [x] Confirm base image publication policy (`latest-only`, `latest + sha`, or `sha-only`).
- [x] Confirm base image rebuild trigger policy (`manual`, `dependency-change`, or `scheduled`).
- [x] Confirm vLLM pinning strategy (`exact version`, `minor range`, or `floating latest`).
- [x] Confirm CUDA pinning strategy and acceptable upgrade cadence.
- [x] Confirm whether executor-base should include Node CLI tools (`codex`, `gemini`, `claude`) or keep those in executor app image only.
- [x] Confirm Stage 0 completeness and ask whether to proceed.

## Stage 0 - Interview Notes

- [x] vLLM pinning selected: exact version.
- [x] Base image publication policy selected: `latest + sha` (aligned with current repo image-tagging approach).
- [x] Base image rebuild trigger policy selected: `manual`.
- [x] CUDA pinning selected: exact image tag.
- [x] Executor-base content selected: include Node CLIs (`codex`, `gemini`, optional `claude`) and Chromium in the base image.
- [x] User approved proceeding to Stage 1.

## Stage 1 - Code Planning

- [x] Define Stage 2 through Stage X implementation stages from approved Stage 0 answers.
- [x] Freeze file-level scope for Dockerfiles, build scripts, and Harbor build orchestration.
- [x] Define acceptance criteria and rollback constraints for base-image rollout.
- [x] Ensure final two stages are `Automated Testing` and `Docs Updates`.

## Stage 1 - Output (Frozen Scope And Acceptance)

- [x] Frozen file scope:
  - [x] `app/llmctl-executor/Dockerfile.base` (new executor-base Dockerfile).
  - [x] `app/llmctl-executor/build-executor-base.sh` (new local base-image build script).
  - [x] `app/llmctl-executor/Dockerfile` (switch to consume executor-base).
  - [x] `app/llmctl-executor/build-executor.sh` (wire base image reference and keep executor-specific args).
  - [x] `scripts/build/harbor.sh` (add `--executor-base`, include in `--all`, enforce base-before-executor order).
  - [x] `app/llmctl-executor/README.md` (document base workflow and manual base rebuild policy).
  - [x] `docs/sphinx/changelog.rst` and/or relevant Sphinx runtime docs for base-image workflow notes.
- [x] Frozen acceptance criteria:
  - [x] `llmctl-executor-base` builds from pinned CUDA tag and pinned exact vLLM version.
  - [x] `llmctl-executor-base` includes Chromium and Node CLIs (`codex`, `gemini`, optional `claude`).
  - [x] Harbor flow supports `--executor-base` and includes base image when `--all` is selected.
  - [x] Harbor build order is deterministic: base image is pushed before executor image when both are requested.
  - [x] Tag publication for base image follows `latest + sha`.
  - [x] Base-image refresh remains manual-only (no scheduled/auto trigger introduced in code path).
- [x] Frozen rollback constraints:
  - [x] Executor image can be rolled back to prior tag without requiring immediate base-image rebuild.
  - [x] Harbor script changes must not break existing `--executor` only path.
  - [x] If base image is unavailable, documented operator fallback path is required.

## Stage 2 - Base Image Contract And Layer Boundary

- [x] Define exactly what belongs in `llmctl-executor-base` (pinned CUDA runtime, Python toolchain, exact pinned vLLM, Chromium, Node CLIs, and required OS libs).
- [x] Define what must stay outside base (repo code copy, executor runtime code, fast-changing dependencies/config).
- [x] Define stable build args and environment contract used by downstream executor image.
- [x] Define image naming/tagging convention for Harbor (`llmctl-executor-base:<tag>`).

## Stage 2 - Output (Contract Freeze)

- [x] `llmctl-executor-base` immutable core contents:
  - [x] `FROM nvidia/cuda:12.8.0-cudnn-runtime-ubuntu24.04` (exact pinned tag).
  - [x] Python toolchain (`python3`, `python3-pip`, `python3-venv`) and base OS utilities needed by executor runtime.
  - [x] Exact pinned `vllm` version (pin finalized in Stage 3 implementation files; no floating/latest spec).
  - [x] Chromium runtime (install + command aliases as needed by executor workflows).
  - [x] Node runtime + CLIs: `@openai/codex`, `@google/gemini-cli`, optional `@anthropic-ai/claude-code` controlled by build arg.
- [x] Must stay outside base (executor-app layer):
  - [x] Repository code copy (`app/llmctl-executor` and any fast-changing app sources).
  - [x] Executor command entrypoint and runtime-specific defaults.
  - [x] Fast-changing Python dependency sets not intentionally frozen into base (for now keep non-vLLM app dependencies in executor image).
  - [x] Environment-specific configuration and runtime secrets.
- [x] Build arg and runtime contract between base and executor:
  - [x] Base image exposes `/opt/venv` and downstream image keeps `PATH=/opt/venv/bin:$PATH`.
  - [x] Base build args include exact vLLM version and optional Claude CLI install toggle.
  - [x] Downstream executor image consumes `llmctl-executor-base:latest` directly and does not reinstall vLLM by default when base already contains it.
  - [x] Contract labels/env metadata to be added in Stage 3/4 for traceability (`cuda_tag`, `vllm_version`, build timestamp).
- [x] Harbor naming and tagging convention:
  - [x] Local build name: `llmctl-executor-base:latest`.
  - [x] Harbor repo: `${HARBOR_REGISTRY}/${HARBOR_PROJECT}/llmctl-executor-base`.
  - [x] Publication policy: publish `latest` and SHA tag (same as current repo convention).
  - [x] Manual rebuild policy retained: base image published only on explicit operator action.

## Stage 3 - Implement Executor Base Image Build

- [x] Add dedicated Dockerfile for `llmctl-executor-base` with pinned CUDA base and vLLM install.
- [x] Add dedicated build script (for local and Harbor workflows).
- [x] Ensure base image build is deterministic and cache-friendly.
- [x] Ensure resulting image includes required runtime validation checks (import/runtime smoke checks for vLLM dependencies).

## Stage 3 - Output (Implemented)

- [x] Added `app/llmctl-executor/Dockerfile.base` with:
  - [x] pinned CUDA runtime base `nvidia/cuda:12.8.0-cudnn-runtime-ubuntu24.04`
  - [x] exact `vllm==0.8.5` install in `/opt/venv`
  - [x] Chromium install and aliases (`chromium`, `chromium-browser`)
  - [x] Node runtime + CLI installs (`codex`, `gemini`, optional `claude`)
  - [x] runtime validation commands (`import torch,vllm`, `chromium --version`, `node --version`)
- [x] Added `app/llmctl-executor/build-executor-base.sh` for base-image build entrypoint.
- [x] Base build smoke execution performed:
  - [x] command: `IMAGE_NAME=llmctl-executor-base:stage3-check INSTALL_CLAUDE=false VLLM_VERSION=0.8.5 app/llmctl-executor/build-executor-base.sh`
  - [x] validation layer completed successfully (`torch 2.6.0+cu124`, `vllm 0.8.5`, Chrome/Node version checks printed).
  - [x] final Docker export step was manually canceled after prolonged no-output unpack phase; implementation and validation layer behavior confirmed.

## Stage 4 - Update Executor Image To Consume Base

- [x] Update `app/llmctl-executor/Dockerfile` to `FROM llmctl-executor-base` (tag-aware via build arg or scripted injection).
- [x] Keep executor-specific layers minimal (app code copy and non-base runtime pieces only).
- [x] Preserve current executor behavior and startup contract.
- [x] Keep fallback path documented if base image is unavailable.

## Stage 4 - Output (Implemented)

- [x] Updated `app/llmctl-executor/Dockerfile` to default to:
  - [x] `FROM llmctl-executor-base:latest`
- [x] Reduced executor image layering to app-focused steps:
  - [x] Removed heavyweight CUDA/Node/CLI/Chromium/vLLM bootstrap from executor image (moved to base image).
  - [x] Kept only app dependency layering and code copy in executor Dockerfile.
- [x] Preserved startup/runtime contract:
  - [x] `PATH` remains `/opt/venv/bin:$PATH`.
  - [x] `CMD ["python3", "app/llmctl-executor/run.py"]` unchanged.
  - [x] Compatibility guard added: build fails fast if base image does not provide `/opt/venv`.
- [x] Updated `app/llmctl-executor/build-executor.sh`:
  - [x] Simplified executor build to consume local `llmctl-executor-base:latest` without base-image override arg.
  - [x] Set `INSTALL_VLLM=false` default for downstream executor builds.
- [x] Documented fallback path in `app/llmctl-executor/README.md`:
  - [x] Build base first, then executor image.
  - [x] If `latest` base is unavailable, use a prior known-good immutable base SHA tag.

## Stage 5 - Harbor Build Workflow Integration

- [x] Extend `scripts/build/harbor.sh` with `--executor-base`.
- [x] Include `llmctl-executor-base` in `--all`.
- [x] Build/push ordering: push `llmctl-executor-base` before `llmctl-executor` when both are selected.
- [x] Ensure output logs clearly list base and app image tags/digests.

## Stage 5 - Output (Implemented)

- [x] `scripts/build/harbor.sh` now supports `--executor-base`.
- [x] Default and `--all` selection sets now include `llmctl-executor-base`.
- [x] Build/push order now guarantees:
  - [x] `llmctl-executor-base` builds/pushes before `llmctl-executor` when both are selected.
- [x] Existing logging/output formatting from `build_and_push()` is reused for `llmctl-executor-base`, including explicit build/tag/push lines and final summary.

## Stage 6 - Rollout And Compatibility Guardrails

- [ ] Define safe migration path from direct executor build to base-dependent executor build.
- [ ] Define mismatch detection between executor-base and executor (version/label compatibility check).
- [ ] Define fast rollback path to previous executor image tag.
- [ ] Verify Kubernetes image references and deployment behavior for updated build flow.

## Stage 7 - Automated Testing

- [ ] Add/adjust automated checks validating base image build success and executor-from-base build success.
- [ ] Add smoke checks confirming vLLM runtime availability in executor containers.
- [ ] Add script-level tests for `scripts/build/harbor.sh --executor-base` and `--all` path selection/order.
- [ ] Record pass/fail outcomes and follow-up actions.

## Stage 8 - Docs Updates

- [ ] Update build/run docs for executor-base workflow and Harbor usage.
- [ ] Document tag strategy, rebuild triggers, and rollback procedure.
- [ ] Update Sphinx/RTD docs for architecture split and base-image ownership.
- [ ] Document operator runbook for base-image refresh and dependent executor rebuilds.
