from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
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
from services.execution.agent_runtime import (
    FrontierAgent,
    FrontierAgentDependencies,
    FrontierAgentRequest,
)
import services.tasks as studio_tasks


class AgentRuntimeAbstractionTests(unittest.TestCase):
    @staticmethod
    def _build_frontier_dependencies(
        *,
        gemini_settings_from_model_config=None,
        load_gemini_auth_key=None,
    ) -> FrontierAgentDependencies:
        return FrontierAgentDependencies(
            provider_label=lambda provider: provider,
            codex_settings_from_model_config=lambda _config: {},
            gemini_settings_from_model_config=gemini_settings_from_model_config
            or (lambda config: dict(config)),
            load_codex_auth_key=lambda: "",
            load_gemini_auth_key=load_gemini_auth_key or (lambda: ""),
            resolve_claude_auth_key=lambda _env: ("", ""),
            default_codex_model="gpt-5",
            default_gemini_model="gemini-2.5-flash",
            default_claude_model="claude-sonnet-4-0",
            require_claude_api_key=True,
        )

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

    def test_frontier_agent_gemini_uses_vertex_client_when_enabled(self) -> None:
        captured: dict[str, object] = {}

        class _FakeClient:
            def __init__(self, **kwargs) -> None:
                captured["client_kwargs"] = kwargs
                self.models = self

            def generate_content(self, **kwargs):
                captured["generate_content_kwargs"] = kwargs
                return SimpleNamespace(text="vertex-ok")

        runtime = FrontierAgent(
            self._build_frontier_dependencies(
                gemini_settings_from_model_config=lambda _config: {
                    "model": "gemini-2.5-pro",
                    "use_vertex_ai": True,
                    "project": "vertex-proj",
                    "location": "us-central1",
                }
            )
        )
        request = FrontierAgentRequest(
            provider="gemini",
            prompt="hello",
            mcp_configs={},
            model_config={},
            env={},
        )

        with patch.dict(
            sys.modules,
            {"google": SimpleNamespace(genai=SimpleNamespace(Client=_FakeClient))},
        ):
            result = runtime.run(request)

        self.assertEqual(0, result.returncode)
        self.assertEqual("vertex-ok", result.stdout)
        self.assertEqual(
            {"vertexai": True, "project": "vertex-proj", "location": "us-central1"},
            captured.get("client_kwargs"),
        )
        self.assertEqual(
            "gemini-2.5-pro",
            dict(captured.get("generate_content_kwargs") or {}).get("model"),
        )

    def test_frontier_agent_gemini_vertex_requires_project_and_location(self) -> None:
        runtime = FrontierAgent(
            self._build_frontier_dependencies(
                gemini_settings_from_model_config=lambda _config: {
                    "use_vertex_ai": True,
                    "project": "",
                    "location": "",
                }
            )
        )
        request = FrontierAgentRequest(
            provider="gemini",
            prompt="hello",
            mcp_configs={},
            model_config={},
            env={},
        )

        with patch.dict(
            sys.modules,
            {"google": SimpleNamespace(genai=SimpleNamespace(Client=object))},
        ):
            result = runtime.run(request)

        self.assertEqual(1, result.returncode)
        self.assertIn("requires both project and location", result.stderr)

    def test_frontier_agent_gemini_uses_api_key_client_when_vertex_disabled(self) -> None:
        captured: dict[str, object] = {}

        class _FakeClient:
            def __init__(self, **kwargs) -> None:
                captured["client_kwargs"] = kwargs
                self.models = self

            def generate_content(self, **kwargs):
                captured["generate_content_kwargs"] = kwargs
                return SimpleNamespace(text="developer-api-ok")

        runtime = FrontierAgent(self._build_frontier_dependencies())
        request = FrontierAgentRequest(
            provider="gemini",
            prompt="hello",
            mcp_configs={},
            model_config={"model": "gemini-2.5-flash"},
            env={"GEMINI_API_KEY": "env-key"},
        )

        with patch.dict(
            sys.modules,
            {"google": SimpleNamespace(genai=SimpleNamespace(Client=_FakeClient))},
        ):
            result = runtime.run(request)

        self.assertEqual(0, result.returncode)
        self.assertEqual("developer-api-ok", result.stdout)
        self.assertEqual({"api_key": "env-key"}, captured.get("client_kwargs"))
        self.assertEqual(
            "gemini-2.5-flash",
            dict(captured.get("generate_content_kwargs") or {}).get("model"),
        )

    def test_gemini_settings_from_model_config_falls_back_to_provider_settings(self) -> None:
        with patch.object(
            studio_tasks,
            "load_integration_settings",
            return_value={
                "gemini_use_vertex_ai": "true",
                "gemini_project": "provider-project",
                "gemini_location": "us-central1",
            },
        ):
            settings = studio_tasks._gemini_settings_from_model_config(
                {"model": "gemini-2.5-flash", "approval_mode": "auto"}
            )

        self.assertTrue(bool(settings.get("use_vertex_ai")))
        self.assertEqual("provider-project", settings.get("project"))
        self.assertEqual("us-central1", settings.get("location"))


if __name__ == "__main__":
    unittest.main()
