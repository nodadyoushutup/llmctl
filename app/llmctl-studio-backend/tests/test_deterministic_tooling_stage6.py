from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault(
    "LLMCTL_STUDIO_DATABASE_URI",
    "postgresql+psycopg://llmctl:llmctl@127.0.0.1:15432/llmctl_studio",
)

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

from services.execution.tooling import (  # noqa: E402
    DETERMINISTIC_TOOL_STATUS_SUCCESS,
    DETERMINISTIC_TOOL_STATUS_SUCCESS_WITH_WARNING,
    ToolInvocationConfig,
    ToolInvocationIdempotencyError,
    build_fallback_warning,
    invoke_deterministic_tool,
    resolve_base_tool_scaffold,
)


class DeterministicToolingStage6Tests(unittest.TestCase):
    def test_resolve_base_tool_scaffold_covers_all_special_node_types(self) -> None:
        decision = resolve_base_tool_scaffold(node_type="decision")
        self.assertEqual("deterministic.decision", decision.get("tool_name"))
        self.assertEqual("evaluate", decision.get("operation"))

        memory = resolve_base_tool_scaffold(node_type="memory")
        self.assertEqual("deterministic.memory", memory.get("tool_name"))
        self.assertEqual("add", memory.get("operation"))

        milestone = resolve_base_tool_scaffold(node_type="milestone")
        self.assertEqual("deterministic.milestone", milestone.get("tool_name"))
        self.assertEqual("create_or_update", milestone.get("operation"))

        plan = resolve_base_tool_scaffold(node_type="plan")
        self.assertEqual("deterministic.plan", plan.get("tool_name"))
        self.assertEqual("create_or_update_plan", plan.get("operation"))

    def test_resolve_base_tool_scaffold_falls_back_to_default_operation(self) -> None:
        scaffold = resolve_base_tool_scaffold(
            node_type="memory",
            operation="unsupported-op",
        )
        self.assertEqual("deterministic.memory", scaffold.get("tool_name"))
        self.assertEqual("add", scaffold.get("operation"))
        self.assertEqual("memory_final_state", scaffold.get("artifact_hook_key"))

    def test_invoke_deterministic_tool_success_attaches_trace_and_contract(self) -> None:
        with patch(
            "services.execution.tooling.register_runtime_idempotency_key",
            return_value=True,
        ):
            outcome = invoke_deterministic_tool(
                config=ToolInvocationConfig(
                    node_type="memory",
                    tool_name="deterministic.memory",
                    operation="add",
                    execution_id=77,
                    request_id="req-77",
                    correlation_id="corr-77",
                    idempotency_key="memory-add-77",
                ),
                invoke=lambda: (
                    {
                        "node_type": "memory",
                        "action": "add",
                        "action_results": ["ok"],
                    },
                    {},
                ),
                validate=lambda output_state, routing_state: self.assertEqual(
                    "memory",
                    output_state.get("node_type"),
                ),
            )

        self.assertEqual(DETERMINISTIC_TOOL_STATUS_SUCCESS, outcome.execution_status)
        self.assertFalse(outcome.fallback_used)
        self.assertEqual("deterministic.memory", outcome.trace_envelope.get("tool_name"))
        self.assertEqual("add", outcome.trace_envelope.get("operation"))
        self.assertEqual("req-77", outcome.trace_envelope.get("request_id"))
        self.assertEqual("corr-77", outcome.trace_envelope.get("correlation_id"))
        self.assertEqual(1, outcome.trace_envelope.get("attempt_count"))
        self.assertEqual(
            DETERMINISTIC_TOOL_STATUS_SUCCESS,
            outcome.output_state.get("execution_status"),
        )
        self.assertFalse(bool(outcome.output_state.get("fallback_used")))
        self.assertIsInstance(outcome.output_state.get("deterministic_tooling"), dict)

    def test_invoke_deterministic_tool_retries_then_succeeds(self) -> None:
        attempts = {"count": 0}

        def _invoke() -> tuple[dict[str, object], dict[str, object]]:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("transient failure")
            return (
                {"node_type": "plan", "action": "create_or_update_plan", "action_results": []},
                {},
            )

        outcome = invoke_deterministic_tool(
            config=ToolInvocationConfig(
                node_type="plan",
                tool_name="deterministic.plan",
                operation="create_or_update_plan",
                max_attempts=2,
            ),
            invoke=_invoke,
        )
        self.assertEqual(2, attempts["count"])
        self.assertEqual(DETERMINISTIC_TOOL_STATUS_SUCCESS, outcome.execution_status)
        self.assertEqual(2, outcome.trace_envelope.get("attempt_count"))
        calls = outcome.trace_envelope.get("calls") or []
        self.assertEqual("failed", calls[0].get("status"))
        self.assertEqual("succeeded", calls[1].get("status"))

    def test_invoke_deterministic_tool_uses_success_with_warning_fallback(self) -> None:
        outcome = invoke_deterministic_tool(
            config=ToolInvocationConfig(
                node_type="decision",
                tool_name="deterministic.decision",
                operation="evaluate",
            ),
            invoke=lambda: (_ for _ in ()).throw(RuntimeError("predicate conflict")),
            validate=lambda output_state, _routing_state: self.assertIn(
                "node_type",
                output_state,
            ),
            fallback_builder=lambda exc: (
                {
                    "node_type": "decision",
                    "matched_connector_ids": [],
                    "evaluations": [],
                    "no_match": True,
                },
                {
                    "matched_connector_ids": [],
                    "evaluations": [],
                    "no_match": True,
                },
                build_fallback_warning(message=str(exc)),
            ),
        )
        self.assertTrue(outcome.fallback_used)
        self.assertEqual(
            DETERMINISTIC_TOOL_STATUS_SUCCESS_WITH_WARNING,
            outcome.execution_status,
        )
        self.assertEqual(
            DETERMINISTIC_TOOL_STATUS_SUCCESS_WITH_WARNING,
            outcome.output_state.get("execution_status"),
        )
        self.assertTrue(bool(outcome.output_state.get("fallback_used")))
        self.assertTrue(bool(outcome.trace_envelope.get("fallback_used")))
        self.assertTrue(bool(outcome.trace_envelope.get("warnings")))

    def test_invoke_deterministic_tool_rejects_duplicate_idempotency_key(self) -> None:
        with patch(
            "services.execution.tooling.register_runtime_idempotency_key",
            return_value=False,
        ):
            with self.assertRaises(ToolInvocationIdempotencyError):
                invoke_deterministic_tool(
                    config=ToolInvocationConfig(
                        node_type="memory",
                        tool_name="deterministic.memory",
                        operation="add",
                        idempotency_key="duplicate-key",
                    ),
                    invoke=lambda: (
                        {"node_type": "memory", "action": "add", "action_results": []},
                        {},
                    ),
                )


if __name__ == "__main__":
    unittest.main()
