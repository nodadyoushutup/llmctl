from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

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
    FrontierToolCall,
    FrontierToolDispatchError,
    _error_status_code,
)
import services.tasks as studio_tasks


class AgentRuntimeAbstractionTests(unittest.TestCase):
    @staticmethod
    def _build_frontier_dependencies(
        *,
        gemini_settings_from_model_config=None,
        load_gemini_auth_key=None,
        dispatch_tool_call=None,
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
            dispatch_tool_call=dispatch_tool_call,
        )

    @staticmethod
    def _completed_with_payload(
        *,
        command: list[str],
        returncode: int,
        stdout: str,
        stderr: str,
        payload: object | None = None,
    ) -> subprocess.CompletedProcess[str]:
        completed = subprocess.CompletedProcess(command, returncode, stdout, stderr)
        if payload is not None:
            setattr(completed, "_llmctl_raw_response", payload)
        return completed

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

    def test_run_frontier_llm_sdk_dispatches_workspace_tool_via_domain_handler(self) -> None:
        captured: dict[str, object] = {}

        class _FakeFrontierAgent:
            def __init__(self, dependencies) -> None:
                captured["dependencies"] = dependencies

            def run(self, request, *, on_update=None, on_log=None):
                captured["request"] = request
                return subprocess.CompletedProcess(["sdk:codex"], 0, "ok", "")

        fake_outcome = SimpleNamespace(
            output_state={"result": {"value": "README"}},
            routing_state={"tool_domain": "workspace"},
            trace_envelope={"contract_version": "v1"},
            execution_status="success",
            fallback_used=False,
            warnings=[],
        )
        with (
            patch.object(studio_tasks, "FrontierAgent", _FakeFrontierAgent),
            patch.object(studio_tasks, "run_workspace_tool", return_value=fake_outcome) as run_tool,
        ):
            result = studio_tasks._run_frontier_llm_sdk(
                provider="codex",
                prompt="hello",
                mcp_configs={},
                model_config={"model": "gpt-5"},
                workspace_root="/tmp/llmctl-stage4-workspace",
                request_id="req-stage4",
                correlation_id="corr-stage4",
                execution_id=77,
                env={"OPENAI_API_KEY": "unit-test"},
            )
            dispatcher = captured["dependencies"].dispatch_tool_call
            dispatched = dispatcher(
                FrontierToolCall(
                    call_id="call-1",
                    tool_name="deterministic.workspace",
                    arguments={"operation": "read", "path": "README.md"},
                )
            )

        self.assertEqual(0, result.returncode)
        self.assertEqual("call-1", dispatched["call_id"])
        self.assertEqual("deterministic.workspace", dispatched["tool_name"])
        output = dict(dispatched.get("output") or {})
        self.assertEqual("workspace", output.get("tool_domain"))
        self.assertEqual("read", output.get("operation"))
        run_tool.assert_called_once()
        kwargs = dict(run_tool.call_args.kwargs)
        context = kwargs.get("context")
        self.assertEqual(Path("/tmp/llmctl-stage4-workspace").resolve(), context.workspace_root)
        self.assertEqual(77, context.execution_id)
        self.assertEqual("req-stage4", context.request_id)
        self.assertEqual("corr-stage4", context.correlation_id)

    def test_run_frontier_llm_sdk_dispatches_git_tool_via_domain_handler(self) -> None:
        captured: dict[str, object] = {}

        class _FakeFrontierAgent:
            def __init__(self, dependencies) -> None:
                captured["dependencies"] = dependencies

            def run(self, request, *, on_update=None, on_log=None):
                return subprocess.CompletedProcess(["sdk:codex"], 0, "ok", "")

        fake_outcome = SimpleNamespace(
            output_state={"result": {"branch": "feature/stage7"}},
            routing_state={"tool_domain": "git"},
            trace_envelope={"contract_version": "v1"},
            execution_status="success",
            fallback_used=False,
            warnings=[],
        )
        with (
            patch.object(studio_tasks, "FrontierAgent", _FakeFrontierAgent),
            patch.object(studio_tasks, "run_git_tool", return_value=fake_outcome) as run_tool,
        ):
            studio_tasks._run_frontier_llm_sdk(
                provider="codex",
                prompt="hello",
                mcp_configs={},
                model_config={"model": "gpt-5"},
                workspace_root="/tmp/llmctl-stage7-workspace",
                request_id="req-stage7-git",
                correlation_id="corr-stage7-git",
                execution_id=88,
                env={"OPENAI_API_KEY": "unit-test"},
            )
            dispatcher = captured["dependencies"].dispatch_tool_call
            dispatched = dispatcher(
                FrontierToolCall(
                    call_id="call-git-1",
                    tool_name="deterministic.git",
                    arguments={
                        "operation": "branch",
                        "action": "switch",
                        "name": "feature/stage7",
                        "create": True,
                    },
                )
            )

        self.assertEqual("call-git-1", dispatched["call_id"])
        output = dict(dispatched.get("output") or {})
        self.assertEqual("git", output.get("tool_domain"))
        self.assertEqual("branch", output.get("operation"))
        run_tool.assert_called_once()
        kwargs = dict(run_tool.call_args.kwargs)
        context = kwargs.get("context")
        self.assertEqual(Path("/tmp/llmctl-stage7-workspace").resolve(), context.workspace_root)
        self.assertEqual(88, context.execution_id)
        self.assertEqual("req-stage7-git", context.request_id)
        self.assertEqual("corr-stage7-git", context.correlation_id)

    def test_run_frontier_llm_sdk_dispatches_command_tool_via_domain_handler(self) -> None:
        captured: dict[str, object] = {}

        class _FakeFrontierAgent:
            def __init__(self, dependencies) -> None:
                captured["dependencies"] = dependencies

            def run(self, request, *, on_update=None, on_log=None):
                return subprocess.CompletedProcess(["sdk:codex"], 0, "ok", "")

        fake_outcome = SimpleNamespace(
            output_state={"result": {"exit_code": 0, "stdout": "ok"}},
            routing_state={"tool_domain": "command"},
            trace_envelope={"contract_version": "v1"},
            execution_status="success",
            fallback_used=False,
            warnings=[],
        )
        with (
            patch.object(studio_tasks, "FrontierAgent", _FakeFrontierAgent),
            patch.object(studio_tasks, "run_command_tool", return_value=fake_outcome) as run_tool,
        ):
            studio_tasks._run_frontier_llm_sdk(
                provider="codex",
                prompt="hello",
                mcp_configs={},
                model_config={"model": "gpt-5"},
                workspace_root="/tmp/llmctl-stage7-workspace",
                request_id="req-stage7-cmd",
                correlation_id="corr-stage7-cmd",
                execution_id=89,
                env={"OPENAI_API_KEY": "unit-test"},
            )
            dispatcher = captured["dependencies"].dispatch_tool_call
            dispatched = dispatcher(
                FrontierToolCall(
                    call_id="call-cmd-1",
                    tool_name="deterministic.command",
                    arguments={
                        "operation": "run",
                        "command": ["bash", "-lc", "echo ok"],
                        "timeout_seconds": 10,
                    },
                )
            )

        self.assertEqual("call-cmd-1", dispatched["call_id"])
        output = dict(dispatched.get("output") or {})
        self.assertEqual("command", output.get("tool_domain"))
        self.assertEqual("run", output.get("operation"))
        run_tool.assert_called_once()
        kwargs = dict(run_tool.call_args.kwargs)
        context = kwargs.get("context")
        self.assertEqual(Path("/tmp/llmctl-stage7-workspace").resolve(), context.workspace_root)
        self.assertEqual(89, context.execution_id)
        self.assertEqual("req-stage7-cmd", context.request_id)
        self.assertEqual("corr-stage7-cmd", context.correlation_id)

    def test_run_frontier_llm_sdk_dispatch_raises_for_unsupported_tool(self) -> None:
        captured: dict[str, object] = {}

        class _FakeFrontierAgent:
            def __init__(self, dependencies) -> None:
                captured["dependencies"] = dependencies

            def run(self, request, *, on_update=None, on_log=None):
                return subprocess.CompletedProcess(["sdk:codex"], 0, "ok", "")

        with patch.object(studio_tasks, "FrontierAgent", _FakeFrontierAgent):
            studio_tasks._run_frontier_llm_sdk(
                provider="codex",
                prompt="hello",
                mcp_configs={},
                model_config={"model": "gpt-5"},
                workspace_root="/tmp/llmctl-stage4-workspace",
                env={"OPENAI_API_KEY": "unit-test"},
            )
            dispatcher = captured["dependencies"].dispatch_tool_call

        with self.assertRaises(FrontierToolDispatchError):
            dispatcher(
                FrontierToolCall(
                    call_id="call-unsupported",
                    tool_name="deterministic.unknown",
                    arguments={"operation": "read"},
                )
            )

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

    def test_frontier_agent_codex_retries_mcp_tool_list_failed_dependency(self) -> None:
        runtime = FrontierAgent(self._build_frontier_dependencies())
        request = FrontierAgentRequest(
            provider="codex",
            prompt="hello",
            mcp_configs={
                "llmctl-mcp": {
                    "url": "http://llmctl-mcp.llmctl.svc.cluster.local:9020/mcp",
                    "transport": "streamable-http",
                }
            },
            model_config={},
            env={"OPENAI_API_KEY": "env-key"},
        )
        transient_error = (
            "Error code: 424 - {'error': {'message': \"Error retrieving tool list from MCP "
            "server: 'llmctl-mcp'. Http status code: 424 (Failed Dependency)\", 'type': "
            "'external_connector_error', 'param': 'tools', 'code': 'http_error'}}"
        )
        with patch.object(
            runtime,
            "_run_codex",
            side_effect=[
                subprocess.CompletedProcess(["sdk:codex"], 424, "", transient_error),
                subprocess.CompletedProcess(["sdk:codex"], 0, "recovered", ""),
            ],
        ) as run_mock, patch("services.execution.agent_runtime.time.sleep") as sleep_mock:
            logs: list[str] = []
            result = runtime.run(request, on_log=logs.append)

        self.assertEqual(0, result.returncode)
        self.assertEqual("recovered", result.stdout)
        self.assertEqual(2, run_mock.call_count)
        sleep_mock.assert_called_once_with(1.0)
        self.assertTrue(
            any("MCP tools/list returned failed dependency" in line for line in logs)
        )

    def test_frontier_agent_codex_mcp_retry_is_bounded(self) -> None:
        runtime = FrontierAgent(self._build_frontier_dependencies())
        request = FrontierAgentRequest(
            provider="codex",
            prompt="hello",
            mcp_configs={"llmctl-mcp": {"url": "http://example.invalid/mcp"}},
            model_config={},
            env={"OPENAI_API_KEY": "env-key"},
        )
        transient_error = (
            "Error code: 424 - {'error': {'message': \"Error retrieving tool list from MCP "
            "server: 'llmctl-mcp'. Http status code: 424 (Failed Dependency)\"}}"
        )
        with patch.object(
            runtime,
            "_run_codex",
            side_effect=[
                subprocess.CompletedProcess(["sdk:codex"], 424, "", transient_error),
                subprocess.CompletedProcess(["sdk:codex"], 424, "", transient_error),
                subprocess.CompletedProcess(["sdk:codex"], 424, "", transient_error),
            ],
        ) as run_mock, patch("services.execution.agent_runtime.time.sleep") as sleep_mock:
            result = runtime.run(request)

        self.assertEqual(424, result.returncode)
        self.assertEqual(3, run_mock.call_count)
        sleep_mock.assert_has_calls([call(1.0), call(2.0)])

    def test_frontier_agent_tool_loop_dispatches_and_continues(self) -> None:
        captured_calls: list[FrontierToolCall] = []

        def _dispatch_tool_call(tool_call: FrontierToolCall) -> dict[str, object]:
            captured_calls.append(tool_call)
            return {
                "call_id": tool_call.call_id,
                "output": {"tool_domain": "workspace", "operation": "read"},
            }

        runtime = FrontierAgent(
            self._build_frontier_dependencies(dispatch_tool_call=_dispatch_tool_call)
        )
        request = FrontierAgentRequest(
            provider="codex",
            prompt="hello",
            mcp_configs={},
            model_config={},
            env={"OPENAI_API_KEY": "env-key"},
        )
        first_payload = {
            "output": [
                {
                    "type": "function_call",
                    "id": "call_1",
                    "name": "deterministic.workspace",
                    "arguments": "{\"operation\":\"read\",\"path\":\"README.md\"}",
                }
            ]
        }
        with patch.object(
            runtime,
            "_run_codex",
            side_effect=[
                self._completed_with_payload(
                    command=["sdk:codex"],
                    returncode=0,
                    stdout="",
                    stderr="",
                    payload=first_payload,
                ),
                self._completed_with_payload(
                    command=["sdk:codex"],
                    returncode=0,
                    stdout="final-answer",
                    stderr="",
                    payload={"output": []},
                ),
            ],
        ) as run_mock:
            logs: list[str] = []
            result = runtime.run(request, on_log=logs.append)

        self.assertEqual(0, result.returncode)
        self.assertEqual("final-answer", result.stdout)
        self.assertEqual(2, run_mock.call_count)
        self.assertEqual(1, len(captured_calls))
        self.assertEqual("call_1", captured_calls[0].call_id)
        self.assertEqual("deterministic.workspace", captured_calls[0].tool_name)
        self.assertTrue(any("sdk_tool_cycle" in line for line in logs))
        self.assertTrue(any("sdk_tool_dispatch" in line for line in logs))
        tool_trace = getattr(result, "_llmctl_tool_trace", None)
        self.assertIsInstance(tool_trace, list)
        self.assertEqual(1, len(tool_trace))
        self.assertEqual("deterministic.workspace", tool_trace[0].get("tool_name"))
        self.assertEqual("read", tool_trace[0].get("operation"))

    def test_sdk_tooling_evidence_payload_extracts_trace(self) -> None:
        completed = subprocess.CompletedProcess(["sdk:codex"], 0, "ok", "")
        setattr(
            completed,
            "_llmctl_tool_trace",
            [
                {
                    "provider": "codex",
                    "cycle": 1,
                    "call_id": "call-1",
                    "tool_name": "deterministic.workspace",
                    "tool_domain": "workspace",
                    "operation": "read",
                    "trace_envelope": {
                        "request_id": "req-1",
                        "correlation_id": "corr-1",
                    },
                }
            ],
        )

        payload = studio_tasks._sdk_tooling_evidence_payload(
            llm_result=completed,
            provider="codex",
            workspace_root=Path("/tmp/llmctl-stage5-workspace"),
        )

        self.assertEqual("codex", payload.get("provider"))
        self.assertEqual("req-1", payload.get("request_id"))
        self.assertEqual("corr-1", payload.get("correlation_id"))
        self.assertEqual(1, payload.get("tool_call_count"))
        self.assertEqual(
            "/tmp/llmctl-stage5-workspace",
            payload.get("workspace_root"),
        )

    def test_execute_executor_llm_call_node_includes_sdk_tooling(self) -> None:
        completed = subprocess.CompletedProcess(["sdk:codex"], 0, "ok", "")
        setattr(
            completed,
            "_llmctl_tool_trace",
            [
                {
                    "provider": "codex",
                    "cycle": 1,
                    "call_id": "call-1",
                    "tool_name": "deterministic.command",
                    "tool_domain": "command",
                    "operation": "run",
                    "trace_envelope": {},
                }
            ],
        )
        with patch.object(studio_tasks, "_run_llm", return_value=completed):
            output_state, routing_state = studio_tasks._execute_executor_llm_call_node(
                node_config={
                    "provider": "codex",
                    "prompt": "hello",
                    "mcp_configs": {},
                    "model_config": {},
                }
            )

        self.assertEqual({}, routing_state)
        self.assertEqual("llm_call", output_state.get("node_type"))
        tooling = output_state.get("sdk_tooling")
        self.assertIsInstance(tooling, dict)
        self.assertEqual(1, tooling.get("tool_call_count"))

    def test_frontier_agent_tool_loop_fails_when_dispatcher_missing(self) -> None:
        runtime = FrontierAgent(self._build_frontier_dependencies())
        request = FrontierAgentRequest(
            provider="codex",
            prompt="hello",
            mcp_configs={},
            model_config={},
            env={"OPENAI_API_KEY": "env-key"},
            request_id="req-tool-loop",
            correlation_id="corr-tool-loop",
        )
        first_payload = {
            "output": [
                {
                    "type": "function_call",
                    "id": "call_1",
                    "name": "deterministic.workspace",
                    "arguments": "{\"operation\":\"read\"}",
                }
            ]
        }
        with patch.object(
            runtime,
            "_run_codex",
            return_value=self._completed_with_payload(
                command=["sdk:codex"],
                returncode=0,
                stdout="",
                stderr="",
                payload=first_payload,
            ),
        ) as run_mock:
            result = runtime.run(request)

        self.assertEqual(1, result.returncode)
        self.assertEqual(1, run_mock.call_count)
        self.assertIn("dispatcher is not configured", result.stderr)
        self.assertIn("tool_dispatcher_unconfigured", result.stderr)
        self.assertIn("req-tool-loop", result.stderr)
        self.assertIn("corr-tool-loop", result.stderr)

    def test_frontier_agent_tool_loop_respects_cycle_limit(self) -> None:
        def _dispatch_tool_call(tool_call: FrontierToolCall) -> dict[str, object]:
            return {"call_id": tool_call.call_id, "output": {"ok": True}}

        runtime = FrontierAgent(
            self._build_frontier_dependencies(dispatch_tool_call=_dispatch_tool_call)
        )
        request = FrontierAgentRequest(
            provider="codex",
            prompt="hello",
            mcp_configs={},
            model_config={"tool_loop_max_cycles": 1},
            env={"OPENAI_API_KEY": "env-key"},
        )
        first_payload = {
            "output": [
                {
                    "type": "function_call",
                    "id": "call_1",
                    "name": "deterministic.command",
                    "arguments": "{\"operation\":\"run\",\"command\":\"pwd\"}",
                }
            ]
        }
        with patch.object(
            runtime,
            "_run_codex",
            return_value=self._completed_with_payload(
                command=["sdk:codex"],
                returncode=0,
                stdout="",
                stderr="",
                payload=first_payload,
            ),
        ) as run_mock:
            result = runtime.run(request)

        self.assertEqual(1, result.returncode)
        self.assertEqual(1, run_mock.call_count)
        self.assertIn("tool_loop_max_cycles_exceeded", result.stderr)

    def test_frontier_agent_tool_loop_surfaces_normalized_dispatch_error(self) -> None:
        def _dispatch_tool_call(_tool_call: FrontierToolCall) -> dict[str, object]:
            raise FrontierToolDispatchError(
                code="tool_domain_error",
                message="workspace read failed",
                details={"operation": "read", "tool_domain": "workspace"},
                retryable=False,
            )

        runtime = FrontierAgent(
            self._build_frontier_dependencies(dispatch_tool_call=_dispatch_tool_call)
        )
        request = FrontierAgentRequest(
            provider="codex",
            prompt="hello",
            mcp_configs={},
            model_config={},
            env={"OPENAI_API_KEY": "env-key"},
            request_id="req-norm-error",
            correlation_id="corr-norm-error",
        )
        first_payload = {
            "output": [
                {
                    "type": "function_call",
                    "id": "call_1",
                    "name": "deterministic.workspace",
                    "arguments": "{\"operation\":\"read\",\"path\":\"README.md\"}",
                }
            ]
        }
        with patch.object(
            runtime,
            "_run_codex",
            return_value=self._completed_with_payload(
                command=["sdk:codex"],
                returncode=0,
                stdout="",
                stderr="",
                payload=first_payload,
            ),
        ):
            result = runtime.run(request)

        self.assertEqual(1, result.returncode)
        self.assertIn("workspace read failed", result.stderr)
        self.assertIn("tool_domain_error", result.stderr)
        self.assertIn("req-norm-error", result.stderr)
        self.assertIn("corr-norm-error", result.stderr)

    def test_frontier_agent_tool_loop_dispatches_for_gemini(self) -> None:
        captured_calls: list[FrontierToolCall] = []

        def _dispatch_tool_call(tool_call: FrontierToolCall) -> dict[str, object]:
            captured_calls.append(tool_call)
            return {
                "call_id": tool_call.call_id,
                "output": {"tool_domain": "workspace", "operation": "write"},
            }

        runtime = FrontierAgent(
            self._build_frontier_dependencies(dispatch_tool_call=_dispatch_tool_call)
        )
        request = FrontierAgentRequest(
            provider="gemini",
            prompt="hello",
            mcp_configs={},
            model_config={},
            env={"GEMINI_API_KEY": "env-key"},
        )
        first_payload = SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    content=SimpleNamespace(
                        parts=[
                            SimpleNamespace(
                                function_call=SimpleNamespace(
                                    name="deterministic.workspace",
                                    id="gemini-call-1",
                                    args={"operation": "write", "path": "README.md"},
                                )
                            )
                        ]
                    )
                )
            ]
        )
        with patch.object(
            runtime,
            "_run_gemini",
            side_effect=[
                self._completed_with_payload(
                    command=["sdk:gemini"],
                    returncode=0,
                    stdout="",
                    stderr="",
                    payload=first_payload,
                ),
                self._completed_with_payload(
                    command=["sdk:gemini"],
                    returncode=0,
                    stdout="gemini-final",
                    stderr="",
                    payload=SimpleNamespace(candidates=[]),
                ),
            ],
        ):
            result = runtime.run(request)

        self.assertEqual(0, result.returncode)
        self.assertEqual("gemini-final", result.stdout)
        self.assertEqual(1, len(captured_calls))
        self.assertEqual("deterministic.workspace", captured_calls[0].tool_name)
        tool_trace = getattr(result, "_llmctl_tool_trace", None)
        self.assertIsInstance(tool_trace, list)
        self.assertEqual(1, len(tool_trace))
        self.assertEqual("write", tool_trace[0].get("operation"))

    def test_frontier_agent_repo_workflow_e2e_codex_verbose_trace(self) -> None:
        calls: list[FrontierToolCall] = []

        def _dispatch_tool_call(tool_call: FrontierToolCall) -> dict[str, object]:
            calls.append(tool_call)
            operation = str((tool_call.arguments or {}).get("operation") or "").strip()
            tool_name = str(tool_call.tool_name or "").strip().lower()
            domain = tool_name.split(".", 1)[1] if "." in tool_name else tool_name
            return {
                "call_id": tool_call.call_id,
                "tool_name": tool_call.tool_name,
                "output": {
                    "tool_domain": domain,
                    "operation": operation,
                    "trace_envelope": {"request_id": "req-codex-e2e"},
                },
                "is_error": False,
            }

        runtime = FrontierAgent(
            self._build_frontier_dependencies(dispatch_tool_call=_dispatch_tool_call)
        )
        request = FrontierAgentRequest(
            provider="codex",
            prompt="Implement change and open PR",
            mcp_configs={},
            model_config={},
            env={"OPENAI_API_KEY": "env-key"},
        )
        first_payload = {
            "output": [
                {
                    "type": "function_call",
                    "id": "call-1",
                    "name": "deterministic.git",
                    "arguments": "{\"operation\":\"branch\",\"action\":\"switch\",\"name\":\"feature/sdk-stage7\",\"create\":true}",
                },
                {
                    "type": "function_call",
                    "id": "call-2",
                    "name": "deterministic.workspace",
                    "arguments": "{\"operation\":\"write\",\"path\":\"README.md\",\"content\":\"updated\"}",
                },
                {
                    "type": "function_call",
                    "id": "call-3",
                    "name": "deterministic.command",
                    "arguments": "{\"operation\":\"run\",\"command\":[\"bash\",\"-lc\",\".venv/bin/python -m pytest\"],\"timeout_seconds\":120}",
                },
                {
                    "type": "function_call",
                    "id": "call-4",
                    "name": "deterministic.git",
                    "arguments": "{\"operation\":\"commit\",\"message\":\"sdk stage7\"}",
                },
                {
                    "type": "function_call",
                    "id": "call-5",
                    "name": "deterministic.git",
                    "arguments": "{\"operation\":\"push\",\"remote\":\"origin\",\"branch\":\"feature/sdk-stage7\"}",
                },
                {
                    "type": "function_call",
                    "id": "call-6",
                    "name": "deterministic.git",
                    "arguments": "{\"operation\":\"pull_request\",\"base\":\"main\",\"head\":\"feature/sdk-stage7\",\"title\":\"SDK Stage7\"}",
                },
            ]
        }
        with patch.object(
            runtime,
            "_run_codex",
            side_effect=[
                self._completed_with_payload(
                    command=["sdk:codex"],
                    returncode=0,
                    stdout="",
                    stderr="",
                    payload=first_payload,
                ),
                self._completed_with_payload(
                    command=["sdk:codex"],
                    returncode=0,
                    stdout="workflow-complete",
                    stderr="",
                    payload={"output": []},
                ),
            ],
        ):
            logs: list[str] = []
            result = runtime.run(request, on_log=logs.append)

        self.assertEqual(0, result.returncode)
        self.assertEqual("workflow-complete", result.stdout)
        self.assertEqual(6, len(calls))
        operations = [str((item.arguments or {}).get("operation") or "") for item in calls]
        self.assertEqual(
            ["branch", "write", "run", "commit", "push", "pull_request"],
            operations,
        )
        self.assertTrue(any("sdk_tool_cycle provider=codex cycle=1" in line for line in logs))
        self.assertEqual(6, sum("sdk_tool_dispatch provider=codex" in line for line in logs))
        tool_trace = getattr(result, "_llmctl_tool_trace", None)
        self.assertIsInstance(tool_trace, list)
        self.assertEqual(6, len(tool_trace))
        self.assertEqual(
            ["branch", "write", "run", "commit", "push", "pull_request"],
            [str(item.get("operation") or "") for item in tool_trace],
        )

    def test_frontier_agent_repo_workflow_e2e_gemini_verbose_trace(self) -> None:
        calls: list[FrontierToolCall] = []

        def _dispatch_tool_call(tool_call: FrontierToolCall) -> dict[str, object]:
            calls.append(tool_call)
            operation = str((tool_call.arguments or {}).get("operation") or "").strip()
            tool_name = str(tool_call.tool_name or "").strip().lower()
            domain = tool_name.split(".", 1)[1] if "." in tool_name else tool_name
            return {
                "call_id": tool_call.call_id,
                "tool_name": tool_call.tool_name,
                "output": {
                    "tool_domain": domain,
                    "operation": operation,
                    "trace_envelope": {"request_id": "req-gemini-e2e"},
                },
                "is_error": False,
            }

        runtime = FrontierAgent(
            self._build_frontier_dependencies(dispatch_tool_call=_dispatch_tool_call)
        )
        request = FrontierAgentRequest(
            provider="gemini",
            prompt="Implement change and open PR",
            mcp_configs={},
            model_config={},
            env={"GEMINI_API_KEY": "env-key"},
        )
        first_payload = SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    content=SimpleNamespace(
                        parts=[
                            SimpleNamespace(
                                function_call=SimpleNamespace(
                                    name="deterministic.git",
                                    id="call-1",
                                    args={
                                        "operation": "branch",
                                        "action": "switch",
                                        "name": "feature/sdk-stage7",
                                        "create": True,
                                    },
                                )
                            ),
                            SimpleNamespace(
                                function_call=SimpleNamespace(
                                    name="deterministic.workspace",
                                    id="call-2",
                                    args={
                                        "operation": "write",
                                        "path": "README.md",
                                        "content": "updated",
                                    },
                                )
                            ),
                            SimpleNamespace(
                                function_call=SimpleNamespace(
                                    name="deterministic.command",
                                    id="call-3",
                                    args={
                                        "operation": "run",
                                        "command": [
                                            "bash",
                                            "-lc",
                                            ".venv/bin/python -m pytest",
                                        ],
                                        "timeout_seconds": 120,
                                    },
                                )
                            ),
                            SimpleNamespace(
                                function_call=SimpleNamespace(
                                    name="deterministic.git",
                                    id="call-4",
                                    args={"operation": "commit", "message": "sdk stage7"},
                                )
                            ),
                            SimpleNamespace(
                                function_call=SimpleNamespace(
                                    name="deterministic.git",
                                    id="call-5",
                                    args={
                                        "operation": "push",
                                        "remote": "origin",
                                        "branch": "feature/sdk-stage7",
                                    },
                                )
                            ),
                            SimpleNamespace(
                                function_call=SimpleNamespace(
                                    name="deterministic.git",
                                    id="call-6",
                                    args={
                                        "operation": "pull_request",
                                        "base": "main",
                                        "head": "feature/sdk-stage7",
                                        "title": "SDK Stage7",
                                    },
                                )
                            ),
                        ]
                    )
                )
            ]
        )
        with patch.object(
            runtime,
            "_run_gemini",
            side_effect=[
                self._completed_with_payload(
                    command=["sdk:gemini"],
                    returncode=0,
                    stdout="",
                    stderr="",
                    payload=first_payload,
                ),
                self._completed_with_payload(
                    command=["sdk:gemini"],
                    returncode=0,
                    stdout="workflow-complete",
                    stderr="",
                    payload=SimpleNamespace(candidates=[]),
                ),
            ],
        ):
            logs: list[str] = []
            result = runtime.run(request, on_log=logs.append)

        self.assertEqual(0, result.returncode)
        self.assertEqual("workflow-complete", result.stdout)
        self.assertEqual(6, len(calls))
        operations = [str((item.arguments or {}).get("operation") or "") for item in calls]
        self.assertEqual(
            ["branch", "write", "run", "commit", "push", "pull_request"],
            operations,
        )
        self.assertTrue(any("sdk_tool_cycle provider=gemini cycle=1" in line for line in logs))
        self.assertEqual(6, sum("sdk_tool_dispatch provider=gemini" in line for line in logs))
        tool_trace = getattr(result, "_llmctl_tool_trace", None)
        self.assertIsInstance(tool_trace, list)
        self.assertEqual(6, len(tool_trace))
        self.assertEqual(
            ["branch", "write", "run", "commit", "push", "pull_request"],
            [str(item.get("operation") or "") for item in tool_trace],
        )

    def test_frontier_agent_tool_loop_dispatches_for_claude(self) -> None:
        captured_calls: list[FrontierToolCall] = []

        def _dispatch_tool_call(tool_call: FrontierToolCall) -> dict[str, object]:
            captured_calls.append(tool_call)
            return {
                "call_id": tool_call.call_id,
                "output": {"tool_domain": "command", "operation": "run"},
            }

        runtime = FrontierAgent(
            self._build_frontier_dependencies(dispatch_tool_call=_dispatch_tool_call)
        )
        request = FrontierAgentRequest(
            provider="claude",
            prompt="hello",
            mcp_configs={},
            model_config={},
            env={"ANTHROPIC_API_KEY": "env-key"},
        )
        first_payload = SimpleNamespace(
            content=[
                {
                    "type": "tool_use",
                    "id": "claude-call-1",
                    "name": "deterministic.command",
                    "input": {"operation": "run", "command": "pwd"},
                }
            ]
        )
        with patch.object(
            runtime,
            "_run_claude",
            side_effect=[
                self._completed_with_payload(
                    command=["sdk:claude"],
                    returncode=0,
                    stdout="",
                    stderr="",
                    payload=first_payload,
                ),
                self._completed_with_payload(
                    command=["sdk:claude"],
                    returncode=0,
                    stdout="claude-final",
                    stderr="",
                    payload=SimpleNamespace(content=[]),
                ),
            ],
        ):
            result = runtime.run(request)

        self.assertEqual(0, result.returncode)
        self.assertEqual("claude-final", result.stdout)
        self.assertEqual(1, len(captured_calls))
        self.assertEqual("deterministic.command", captured_calls[0].tool_name)
        tool_trace = getattr(result, "_llmctl_tool_trace", None)
        self.assertIsInstance(tool_trace, list)
        self.assertEqual(1, len(tool_trace))
        self.assertEqual("run", tool_trace[0].get("operation"))

    def test_frontier_agent_rejects_mcp_transport_for_non_codex_providers(self) -> None:
        runtime = FrontierAgent(self._build_frontier_dependencies())
        for provider in ("gemini", "claude"):
            with self.subTest(provider=provider):
                request = FrontierAgentRequest(
                    provider=provider,
                    prompt="hello",
                    mcp_configs={"llmctl-mcp": {"url": "http://example.test/mcp"}},
                    model_config={},
                    env={},
                )
                result = runtime.run(request)
                self.assertEqual(1, result.returncode)
                self.assertIn("does not support MCP transport config", result.stderr)

    def test_error_status_code_parses_embedded_error_code(self) -> None:
        exc = Exception(
            "Error code: 424 - {'error': {'message': 'simulated failed dependency'}}"
        )

        status_code = _error_status_code(exc)

        self.assertEqual(424, status_code)

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
