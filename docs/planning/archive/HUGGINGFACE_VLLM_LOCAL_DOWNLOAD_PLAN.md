# HuggingFace vLLM Local Download Integration Plan

## Stage 0: Requirements Gathering
- [x] Review current vLLM Local settings, Qwen action flow, and download script behavior.
- [x] Confirm when HuggingFace model download controls should be visible in vLLM Local settings.
- [x] Confirm HuggingFace credential shape and storage keys (for example token only vs additional fields).
- [x] Confirm expected behavior for Qwen download with and without HuggingFace credentials.
- [x] Confirm arbitrary HuggingFace model download input format and target directory naming.
- [x] Confirm arbitrary HuggingFace model download error/overwrite behavior.
- [x] Confirm Stage 0 is complete with user and get explicit go-ahead to proceed to Stage 1.

## Stage 1: Code Planning
- [x] Define concrete Stage 2+ implementation tasks and file-level change list after requirements are finalized.
- [x] Confirm implementation decisions:
  - Keep existing `Download Qwen` button; use HF token automatically when configured, anonymous otherwise.
  - Add HF token-only setting in vLLM Local settings.
  - Show generic HF model download controls only when HF token is configured.
  - Generic download input is HuggingFace repo id (`owner/model`) and local dir is auto-generated from model name.
  - If generated target dir already exists, skip download and show already-downloaded info.
- [x] File-level execution plan:
  - `app/llmctl-studio/src/web/views.py`: add HF settings payload, token-aware download helpers, generic HF download route, and vLLM-local settings persistence updates.
  - `app/llmctl-studio/src/web/templates/settings_provider.html`: add HF token field and conditional generic HF download controls in vLLM Local panel.
  - `app/llmctl-studio/tests/test_vllm_local_qwen_action_stage9.py`: extend coverage for HF token persistence/visibility and generic download route behavior.
  - `docs/sphinx/provider_runtime.rst` and `docs/sphinx/changelog.rst`: document HF integration and vLLM Local download behavior.

## Stage 2: HuggingFace Settings + Download Backend
- [x] Add HuggingFace integration settings handling in provider settings backend for vLLM Local usage.
- [x] Implement backend action for downloading arbitrary HuggingFace models into the custom models directory.
- [x] Ensure Qwen download flow uses HuggingFace credentials when configured and continues to work anonymously when absent.

## Stage 3: vLLM Local UI Wiring
- [x] Update vLLM Local settings template to expose HuggingFace controls only when required by finalized requirements.
- [x] Keep existing no-extra-nav constraint and integrate with current action-header/button patterns.
- [x] Add any needed status text and validation messaging for download actions.

## Stage 4: Validation + Regression Coverage
- [x] Extend/add tests for HuggingFace settings persistence, conditional UI visibility, Qwen download behavior, and arbitrary model download action.
- [x] Verify existing vLLM Local/Qwen behavior remains stable.

## Stage 5: Automated Testing
- [x] Run targeted automated tests for updated vLLM Local/provider settings flows.
- [x] Run any additional related tests needed to catch regressions from the implementation.

## Stage 6: Docs Updates
- [x] Update Sphinx/RTD docs for new HuggingFace integration behavior and vLLM Local download workflow.
- [x] Update any relevant in-repo operator/developer docs for required env/settings.
