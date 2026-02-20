from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
HARBOR_SCRIPT = REPO_ROOT / "scripts" / "build" / "harbor.sh"
HARBOR_OVERLAY_SCRIPT = REPO_ROOT / "scripts" / "configure-harbor-image-overlays.sh"
EXECUTOR_README = REPO_ROOT / "app" / "llmctl-executor" / "README.md"
FRONTIER_DOCKERFILE = REPO_ROOT / "app" / "llmctl-executor" / "Dockerfile"
VLLM_DOCKERFILE = REPO_ROOT / "app" / "llmctl-executor" / "Dockerfile.base"
EXECUTOR_REQUIREMENTS = REPO_ROOT / "app" / "llmctl-executor" / "requirements.txt"


class ExecutorHarborStage5Tests(unittest.TestCase):
    def test_harbor_script_exposes_split_executor_selection_flags(self) -> None:
        content = HARBOR_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("--executor-frontier", content)
        self.assertIn("--executor-vllm", content)
        self.assertIn("--executor               Deprecated alias for --executor-frontier", content)
        self.assertIn("--executor-base          Deprecated alias for --executor-vllm", content)

    def test_harbor_script_builds_split_executor_images(self) -> None:
        content = HARBOR_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('build_and_push "llmctl-executor-frontier"', content)
        self.assertIn('build_and_push "llmctl-executor-vllm"', content)
        self.assertNotIn('build_and_push "llmctl-executor-base"', content)
        self.assertIn("app/llmctl-executor/build-executor.sh", content)
        self.assertIn("app/llmctl-executor/build-executor-base.sh", content)

    def test_executor_readme_documents_split_build_and_lockfiles(self) -> None:
        content = EXECUTOR_README.read_text(encoding="utf-8")
        self.assertIn("Build Images (Split Executors)", content)
        self.assertIn("IMAGE_NAME=llmctl-executor-frontier:latest", content)
        self.assertIn("IMAGE_NAME=llmctl-executor-vllm:latest", content)
        self.assertIn("requirements.frontier.lock.txt", content)
        self.assertIn("requirements.vllm.lock.txt", content)

    def test_argocd_overlay_script_uses_split_executor_images_only(self) -> None:
        content = HARBOR_OVERLAY_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("--kustomize-image \"llmctl-executor-frontier=", content)
        self.assertIn("--kustomize-image \"llmctl-executor-vllm=", content)
        self.assertNotIn("--kustomize-image \"llmctl-executor=", content)

    def test_frontier_executor_dockerfile_enforces_cpu_only_sdk_only_profile(self) -> None:
        content = FRONTIER_DOCKERFILE.read_text(encoding="utf-8")
        self.assertIn("FROM python:3.12-slim", content)
        self.assertIn('io.llmctl.executor.cpu_only="true"', content)
        self.assertIn("requirements.frontier.lock.txt", content)
        self.assertIn("find_spec('vllm')", content)
        self.assertIn("for blocked in codex gemini claude", content)

    def test_vllm_executor_dockerfile_enforces_split_image_and_cli_denylist(self) -> None:
        content = VLLM_DOCKERFILE.read_text(encoding="utf-8")
        self.assertIn("FROM nvidia/cuda", content)
        self.assertIn('io.llmctl.executor.flavor="vllm"', content)
        self.assertIn("requirements.vllm.lock.txt", content)
        self.assertIn("for blocked in codex gemini claude", content)

    def test_frontier_requirements_include_core_frontier_sdk_inventory(self) -> None:
        content = EXECUTOR_REQUIREMENTS.read_text(encoding="utf-8")
        self.assertIn("openai>=", content)
        self.assertIn("anthropic>=", content)
        self.assertIn("google-genai>=", content)
        self.assertIn("google-cloud-aiplatform>=", content)
        self.assertNotIn("vllm", content)


if __name__ == "__main__":
    unittest.main()
