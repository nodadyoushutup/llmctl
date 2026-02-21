from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

os.environ.setdefault(
    "LLMCTL_STUDIO_DATABASE_URI",
    "postgresql+psycopg://llmctl:llmctl@127.0.0.1:15432/llmctl_studio",
)

from core.prompt_envelope import build_prompt_envelope
from core.quick_node import build_quick_node_agent_info, build_quick_node_agent_profile
from services.execution.agent_info import AgentInfo, coerce_agent_profile_payload
from services.execution.agent_runtime import FrontierAgentRequest
import services.tasks as studio_tasks


class AgentRuntimeAbstractionTests(unittest.TestCase):
    def test_prompt_envelope_accepts_typed_agent_info(self) -> None:
        info = AgentInfo(id=42, name="Typed Agent", description="Typed profile")

        envelope = build_prompt_envelope(
            user_request="execute",
            system_contract={"role": {"name": "operator"}},
            agent_profile=info,
            task_context={"kind": "task"},
            output_contract={"mode": "one_off"},
        )

        self.assertEqual("Typed Agent", envelope["agent_profile"]["name"])
        self.assertEqual(42, envelope["agent_profile"]["id"])
        self.assertEqual("Typed profile", envelope["agent_profile"]["description"])

    def test_quick_node_exposes_typed_agent_info(self) -> None:
        info = build_quick_node_agent_info()
        payload = build_quick_node_agent_profile()

        self.assertIsInstance(info, AgentInfo)
        self.assertEqual(info.name, payload.get("name"))
        self.assertEqual(info.description, payload.get("description"))
        self.assertEqual("quick-node-default", payload.get("id"))

    def test_coerce_agent_profile_payload_supports_agent_info(self) -> None:
        info = AgentInfo(id=7, name="A", description="B")

        payload = coerce_agent_profile_payload(info)

        self.assertEqual({"id": 7, "name": "A", "description": "B"}, payload)

    def test_run_frontier_llm_sdk_builds_typed_request(self) -> None:
        captured: dict[str, object] = {}

        class _FakeFrontierAgent:
            def __init__(self, dependencies) -> None:
                captured["dependencies"] = dependencies

            def run(self, request, *, on_update=None, on_log=None):
                captured["request"] = request
                return subprocess.CompletedProcess(["sdk:codex"], 0, "typed-runtime-ok", "")

        with patch.object(studio_tasks, "FrontierAgent", _FakeFrontierAgent):
            result = studio_tasks._run_frontier_llm_sdk(
                provider="codex",
                prompt="hello",
                mcp_configs={},
                model_config={"model": "gpt-5"},
                env={"OPENAI_API_KEY": "unit-test"},
            )

        self.assertEqual(0, result.returncode)
        self.assertEqual("typed-runtime-ok", result.stdout)
        self.assertIsInstance(captured.get("request"), FrontierAgentRequest)


if __name__ == "__main__":
    unittest.main()
