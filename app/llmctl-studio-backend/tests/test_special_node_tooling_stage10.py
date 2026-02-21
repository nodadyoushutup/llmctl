from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault(
    "LLMCTL_STUDIO_DATABASE_URI",
    "postgresql+psycopg://llmctl:llmctl@127.0.0.1:15432/llmctl_studio",
)

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

from core.models import (  # noqa: E402
    FLOWCHART_NODE_TYPE_DECISION,
    FLOWCHART_NODE_TYPE_MEMORY,
    FLOWCHART_NODE_TYPE_MILESTONE,
    FLOWCHART_NODE_TYPE_PLAN,
)
from services import tasks as studio_tasks  # noqa: E402
from services.execution.tooling import (  # noqa: E402
    DETERMINISTIC_TOOL_STATUS_SUCCESS,
    DETERMINISTIC_TOOL_STATUS_SUCCESS_WITH_WARNING,
)


class SpecialNodeToolingStage10Tests(unittest.TestCase):
    def test_decision_wrapper_defaults_to_legacy_route_operation_without_conditions(
        self,
    ) -> None:
        output_state, routing_state = (
            studio_tasks._execute_deterministic_special_node_with_framework(
                node_type=FLOWCHART_NODE_TYPE_DECISION,
                node_config={
                    "route_field_path": "latest_upstream.output_state.structured_output.route_key",
                },
                input_context={},
                execution_id=9010,
                invoke=lambda: (
                    {
                        "node_type": FLOWCHART_NODE_TYPE_DECISION,
                        "matched_connector_ids": ["approve"],
                        "evaluations": [
                            {
                                "connector_id": "approve",
                                "condition_text": "legacy",
                                "matched": True,
                                "reason": "matched",
                            }
                        ],
                        "no_match": False,
                    },
                    {
                        "route_key": "approve",
                        "matched_connector_ids": ["approve"],
                        "evaluations": [
                            {
                                "connector_id": "approve",
                                "condition_text": "legacy",
                                "matched": True,
                                "reason": "matched",
                            }
                        ],
                        "no_match": False,
                    },
                ),
            )
        )

        trace = output_state.get("deterministic_tooling") or {}
        self.assertEqual("legacy_route", trace.get("operation"))
        self.assertEqual(DETERMINISTIC_TOOL_STATUS_SUCCESS, trace.get("execution_status"))
        self.assertFalse(bool(trace.get("fallback_used")))
        self.assertEqual("approve", routing_state.get("route_key"))

    def test_decision_wrapper_uses_evaluate_operation_when_conditions_exist(self) -> None:
        output_state, _routing_state = (
            studio_tasks._execute_deterministic_special_node_with_framework(
                node_type=FLOWCHART_NODE_TYPE_DECISION,
                node_config={
                    "decision_conditions": [
                        {
                            "connector_id": "approve",
                            "condition_text": "latest_upstream.output_state.structured_output.route_key == approve",
                        }
                    ]
                },
                input_context={},
                execution_id=9011,
                invoke=lambda: (
                    {
                        "node_type": FLOWCHART_NODE_TYPE_DECISION,
                        "matched_connector_ids": ["approve"],
                        "evaluations": [
                            {
                                "connector_id": "approve",
                                "condition_text": "ok",
                                "matched": True,
                                "reason": "matched",
                            }
                        ],
                        "no_match": False,
                    },
                    {
                        "route_key": "approve",
                        "matched_connector_ids": ["approve"],
                        "evaluations": [
                            {
                                "connector_id": "approve",
                                "condition_text": "ok",
                                "matched": True,
                                "reason": "matched",
                            }
                        ],
                        "no_match": False,
                    },
                ),
            )
        )

        trace = output_state.get("deterministic_tooling") or {}
        self.assertEqual("evaluate", trace.get("operation"))
        self.assertEqual("deterministic.decision", trace.get("tool_name"))

    def test_decision_wrapper_uses_evaluate_operation_when_cutover_enabled(self) -> None:
        output_state, _routing_state = (
            studio_tasks._execute_deterministic_special_node_with_framework(
                node_type=FLOWCHART_NODE_TYPE_DECISION,
                node_config={
                    studio_tasks.AGENT_RUNTIME_CUTOVER_FLAG_KEY: "true",
                    "route_field_path": "latest_upstream.output_state.structured_output.route_key",
                },
                input_context={},
                execution_id=9014,
                invoke=lambda: (
                    {
                        "node_type": FLOWCHART_NODE_TYPE_DECISION,
                        "matched_connector_ids": ["approve"],
                        "evaluations": [
                            {
                                "connector_id": "approve",
                                "condition_text": "ok",
                                "matched": True,
                                "reason": "matched",
                            }
                        ],
                        "no_match": False,
                    },
                    {
                        "route_key": "approve",
                        "matched_connector_ids": ["approve"],
                        "evaluations": [
                            {
                                "connector_id": "approve",
                                "condition_text": "ok",
                                "matched": True,
                                "reason": "matched",
                            }
                        ],
                        "no_match": False,
                    },
                ),
            )
        )

        trace = output_state.get("deterministic_tooling") or {}
        self.assertEqual("evaluate", trace.get("operation"))

    def test_memory_wrapper_conflict_only_fallback_handles_conflict(self) -> None:
        output_state, routing_state = (
            studio_tasks._execute_deterministic_special_node_with_framework(
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                node_config={
                    "action": "retrieve",
                    "tool_fallback_mode": "conflict_only",
                    "route_key": "memory_recover",
                },
                input_context={"node": {"execution_index": 3}},
                execution_id=9012,
                invoke=lambda: (_ for _ in ()).throw(
                    RuntimeError("memory retrieval conflict for node")
                ),
            )
        )

        self.assertEqual(FLOWCHART_NODE_TYPE_MEMORY, output_state.get("node_type"))
        self.assertEqual("retrieve", output_state.get("action"))
        self.assertEqual(
            DETERMINISTIC_TOOL_STATUS_SUCCESS_WITH_WARNING,
            output_state.get("execution_status"),
        )
        self.assertTrue(bool(output_state.get("fallback_used")))
        warnings = output_state.get("warnings") or []
        self.assertTrue(warnings)
        self.assertIn("conflict", str(warnings[0].get("message") or "").lower())

        trace = output_state.get("deterministic_tooling") or {}
        self.assertEqual("retrieve", trace.get("operation"))
        self.assertEqual("deterministic.memory", trace.get("tool_name"))
        self.assertTrue(bool(trace.get("fallback_used")))
        self.assertEqual("memory_recover", routing_state.get("route_key"))
        self.assertTrue(bool(routing_state.get("fallback_used")))

    def test_memory_wrapper_conflict_only_fallback_keeps_non_conflict_failures_strict(
        self,
    ) -> None:
        with self.assertRaises(RuntimeError):
            studio_tasks._execute_deterministic_special_node_with_framework(
                node_type=FLOWCHART_NODE_TYPE_MEMORY,
                node_config={
                    "action": "retrieve",
                    "tool_fallback_mode": "conflict_only",
                },
                input_context={},
                execution_id=9013,
                invoke=lambda: (_ for _ in ()).throw(RuntimeError("database unavailable")),
            )

    def test_milestone_wrapper_uses_mark_complete_operation(self) -> None:
        output_state, _routing_state = (
            studio_tasks._execute_deterministic_special_node_with_framework(
                node_type=FLOWCHART_NODE_TYPE_MILESTONE,
                node_config={"action": "mark_complete"},
                input_context={},
                execution_id=9015,
                invoke=lambda: (
                    {
                        "node_type": FLOWCHART_NODE_TYPE_MILESTONE,
                        "action": "mark_complete",
                        "action_results": ["completed milestone"],
                    },
                    {},
                ),
            )
        )

        trace = output_state.get("deterministic_tooling") or {}
        self.assertEqual("mark_complete", trace.get("operation"))
        self.assertEqual("deterministic.milestone", trace.get("tool_name"))
        self.assertEqual(DETERMINISTIC_TOOL_STATUS_SUCCESS, trace.get("execution_status"))

    def test_plan_wrapper_uses_complete_plan_item_operation(self) -> None:
        output_state, _routing_state = (
            studio_tasks._execute_deterministic_special_node_with_framework(
                node_type=FLOWCHART_NODE_TYPE_PLAN,
                node_config={"action": "complete_plan_item"},
                input_context={},
                execution_id=9016,
                invoke=lambda: (
                    {
                        "node_type": FLOWCHART_NODE_TYPE_PLAN,
                        "action": "complete_plan_item",
                        "action_results": ["completed plan task"],
                    },
                    {},
                ),
            )
        )

        trace = output_state.get("deterministic_tooling") or {}
        self.assertEqual("complete_plan_item", trace.get("operation"))
        self.assertEqual("deterministic.plan", trace.get("tool_name"))
        self.assertEqual(DETERMINISTIC_TOOL_STATUS_SUCCESS, trace.get("execution_status"))


if __name__ == "__main__":
    unittest.main()
