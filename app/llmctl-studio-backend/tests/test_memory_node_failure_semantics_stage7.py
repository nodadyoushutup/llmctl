from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

from services import tasks as studio_tasks


class MemoryNodeFailureSemanticsStage7Tests(unittest.TestCase):
    def test_primary_mode_retries_before_returning_success(self) -> None:
        call_modes: list[str] = []

        def _side_effect(*args, **kwargs):
            del args
            call_modes.append(str(kwargs.get("mode")))
            if len(call_modes) == 1:
                raise RuntimeError("primary failure")
            return (
                {
                    "node_type": "memory",
                    "action": "retrieve",
                    "retrieved_memories": [{"id": 1, "description": "match"}],
                    "action_results": ["retrieved"],
                },
                {},
            )

        with patch.object(studio_tasks, "_execute_memory_node_for_mode", side_effect=_side_effect):
            output_state, routing_state = studio_tasks._execute_flowchart_memory_node(
                node_id=10,
                node_ref_id=None,
                node_config={
                    "action": "retrieve",
                    "mode": "deterministic",
                    "retry_count": 1,
                    "fallback_enabled": False,
                },
                input_context={},
                mcp_server_keys=["llmctl-mcp"],
                execution_id=100,
                enabled_providers={"codex"},
                default_model_id=1,
            )

        self.assertEqual(["deterministic", "deterministic"], call_modes)
        self.assertFalse(bool(output_state.get("fallback_used")))
        self.assertNotIn("execution_status", output_state)
        self.assertEqual({}, routing_state)

    def test_fallback_success_sets_degraded_markers(self) -> None:
        call_modes: list[str] = []

        def _side_effect(*args, **kwargs):
            del args
            mode = str(kwargs.get("mode"))
            call_modes.append(mode)
            if mode == "deterministic":
                raise RuntimeError("deterministic primary failed")
            return (
                {
                    "node_type": "memory",
                    "action": "retrieve",
                    "retrieved_memories": [{"id": 2, "description": "fallback-match"}],
                    "action_results": ["retrieved"],
                },
                {},
            )

        with patch.object(studio_tasks, "_execute_memory_node_for_mode", side_effect=_side_effect):
            output_state, routing_state = studio_tasks._execute_flowchart_memory_node(
                node_id=11,
                node_ref_id=None,
                node_config={
                    "action": "retrieve",
                    "mode": "deterministic",
                    "retry_count": 0,
                    "fallback_enabled": True,
                },
                input_context={},
                mcp_server_keys=["llmctl-mcp"],
                execution_id=101,
                enabled_providers={"codex"},
                default_model_id=1,
            )

        self.assertEqual(["deterministic", "llm_guided"], call_modes)
        self.assertEqual("success_with_warning", output_state.get("execution_status"))
        self.assertTrue(bool(output_state.get("fallback_used")))
        self.assertEqual("deterministic", output_state.get("failed_mode"))
        self.assertEqual("primary_runtime_error", output_state.get("fallback_reason"))
        self.assertTrue(bool(routing_state.get("fallback_used")))
        self.assertEqual("primary_runtime_error", routing_state.get("fallback_reason"))

    def test_fallback_disabled_raises_primary_failure(self) -> None:
        with patch.object(
            studio_tasks,
            "_execute_memory_node_for_mode",
            side_effect=RuntimeError("primary failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "primary failed"):
                studio_tasks._execute_flowchart_memory_node(
                    node_id=12,
                    node_ref_id=None,
                    node_config={
                        "action": "retrieve",
                        "mode": "deterministic",
                        "retry_count": 0,
                        "fallback_enabled": False,
                    },
                    input_context={},
                    mcp_server_keys=["llmctl-mcp"],
                    execution_id=102,
                    enabled_providers={"codex"},
                    default_model_id=1,
                )

    def test_fallback_failure_raises_hard_failure(self) -> None:
        call_modes: list[str] = []

        def _side_effect(*args, **kwargs):
            del args
            call_modes.append(str(kwargs.get("mode")))
            raise RuntimeError("mode failure")

        with patch.object(studio_tasks, "_execute_memory_node_for_mode", side_effect=_side_effect):
            with self.assertRaisesRegex(RuntimeError, "fallback_runtime_error"):
                studio_tasks._execute_flowchart_memory_node(
                    node_id=13,
                    node_ref_id=None,
                    node_config={
                        "action": "retrieve",
                        "mode": "deterministic",
                        "retry_count": 0,
                        "fallback_enabled": True,
                    },
                    input_context={},
                    mcp_server_keys=["llmctl-mcp"],
                    execution_id=103,
                    enabled_providers={"codex"},
                    default_model_id=1,
                )
        self.assertEqual(["deterministic", "llm_guided"], call_modes)

    def test_empty_primary_result_classifies_as_primary_empty_result(self) -> None:
        call_modes: list[str] = []

        def _side_effect(*args, **kwargs):
            del args
            mode = str(kwargs.get("mode"))
            call_modes.append(mode)
            if mode == "llm_guided":
                return (
                    {
                        "node_type": "memory",
                        "action": "retrieve",
                        "retrieved_memories": [],
                        "action_results": ["retrieved"],
                    },
                    {},
                )
            return (
                {
                    "node_type": "memory",
                    "action": "retrieve",
                    "retrieved_memories": [{"id": 3, "description": "fallback"}],
                    "action_results": ["retrieved"],
                },
                {},
            )

        with patch.object(studio_tasks, "_execute_memory_node_for_mode", side_effect=_side_effect):
            output_state, _routing_state = studio_tasks._execute_flowchart_memory_node(
                node_id=14,
                node_ref_id=None,
                node_config={
                    "action": "retrieve",
                    "mode": "llm_guided",
                    "retry_count": 0,
                    "fallback_enabled": True,
                },
                input_context={},
                mcp_server_keys=["llmctl-mcp"],
                execution_id=104,
                enabled_providers={"codex"},
                default_model_id=1,
            )

        self.assertEqual(["llm_guided", "deterministic"], call_modes)
        self.assertEqual("llm_guided", output_state.get("failed_mode"))
        self.assertEqual("primary_empty_result", output_state.get("fallback_reason"))

    def test_llm_guided_validation_error_classifies_correctly(self) -> None:
        call_modes: list[str] = []

        def _side_effect(*args, **kwargs):
            del args
            mode = str(kwargs.get("mode"))
            call_modes.append(mode)
            if mode == "llm_guided":
                raise studio_tasks._MemoryLlmGuidedValidationError("bad llm json")
            return (
                {
                    "node_type": "memory",
                    "action": "retrieve",
                    "retrieved_memories": [{"id": 4, "description": "fallback"}],
                    "action_results": ["retrieved"],
                },
                {},
            )

        with patch.object(studio_tasks, "_execute_memory_node_for_mode", side_effect=_side_effect):
            output_state, _routing_state = studio_tasks._execute_flowchart_memory_node(
                node_id=15,
                node_ref_id=None,
                node_config={
                    "action": "retrieve",
                    "mode": "llm_guided",
                    "retry_count": 0,
                    "fallback_enabled": True,
                },
                input_context={},
                mcp_server_keys=["llmctl-mcp"],
                execution_id=105,
                enabled_providers={"codex"},
                default_model_id=1,
            )

        self.assertEqual(["llm_guided", "deterministic"], call_modes)
        self.assertEqual("llm_validation_error", output_state.get("fallback_reason"))


if __name__ == "__main__":
    unittest.main()
