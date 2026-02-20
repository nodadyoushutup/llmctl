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

from core.models import (
    FLOWCHART_NODE_TYPE_DECISION,
    NODE_ARTIFACT_TYPE_PLAN,
    NODE_ARTIFACT_TYPE_TASK,
)
from services.runtime_contracts import (
    build_node_artifact_idempotency_key,
    build_node_run_idempotency_key,
    canonical_socket_event_type,
    resolve_node_degraded_markers,
    validate_node_artifact_payload_contract,
    validate_special_node_output_contract,
)


class RuntimeContractsStage3Tests(unittest.TestCase):
    def test_canonical_socket_event_type_normalizes_dot_and_extra_segments(self) -> None:
        self.assertEqual(
            "node:task:stage_updated",
            canonical_socket_event_type("node.task.stage.updated"),
        )
        self.assertEqual(
            "flowchart:run:updated",
            canonical_socket_event_type("flowchart:run:updated"),
        )

    def test_validate_special_node_output_contract_accepts_decision_shape(self) -> None:
        output_state = {
            "node_type": FLOWCHART_NODE_TYPE_DECISION,
            "matched_connector_ids": ["next"],
            "evaluations": [
                {
                    "connector_id": "next",
                    "condition_text": "latest_upstream.output_state.ok",
                    "matched": True,
                    "reason": "Resolved bool true.",
                }
            ],
            "no_match": False,
        }
        routing_state = {
            "matched_connector_ids": ["next"],
            "evaluations": [{"connector_id": "next", "matched": True}],
            "no_match": False,
            "route_key": "next",
        }
        validate_special_node_output_contract(
            FLOWCHART_NODE_TYPE_DECISION,
            output_state,
            routing_state,
        )

    def test_validate_special_node_output_contract_rejects_empty_connector_id(self) -> None:
        output_state = {
            "node_type": FLOWCHART_NODE_TYPE_DECISION,
            "matched_connector_ids": [""],
            "evaluations": [],
            "no_match": False,
        }
        routing_state = {
            "matched_connector_ids": [""],
            "evaluations": [],
            "no_match": False,
        }
        with self.assertRaises(ValueError):
            validate_special_node_output_contract(
                FLOWCHART_NODE_TYPE_DECISION,
                output_state,
                routing_state,
            )

    def test_validate_node_artifact_payload_contract_requires_routing_state(self) -> None:
        with self.assertRaises(ValueError):
            validate_node_artifact_payload_contract(
                NODE_ARTIFACT_TYPE_PLAN,
                {"action": "create_or_update_plan", "action_results": []},
            )

    def test_validate_node_artifact_payload_contract_accepts_task_artifact_shape(self) -> None:
        validate_node_artifact_payload_contract(
            NODE_ARTIFACT_TYPE_TASK,
            {
                "node_type": "task",
                "input_context": {},
                "output_state": {"node_type": "task"},
                "routing_state": {},
            },
        )

    def test_resolve_node_degraded_markers_prefers_fallback_reason(self) -> None:
        degraded, reason = resolve_node_degraded_markers(
            {
                "fallback_attempted": True,
                "fallback_reason": "provider_unavailable",
                "api_failure_category": "timeout",
            }
        )
        self.assertTrue(degraded)
        self.assertEqual("provider_unavailable", reason)

    def test_resolve_node_degraded_markers_handles_deterministic_warning_contract(self) -> None:
        degraded, reason = resolve_node_degraded_markers(
            {
                "deterministic_fallback_used": True,
                "deterministic_execution_status": "success_with_warning",
            }
        )
        self.assertTrue(degraded)
        self.assertEqual("deterministic_fallback_used", reason)

    def test_idempotency_key_builders_are_stable(self) -> None:
        self.assertEqual(
            "flowchart_run:10:flowchart_node:33:execution:2",
            build_node_run_idempotency_key(
                flowchart_run_id=10,
                flowchart_node_id=33,
                execution_index=2,
            ),
        )
        self.assertEqual(
            "flowchart_run:10:node_run:77:artifact:plan",
            build_node_artifact_idempotency_key(
                flowchart_run_id=10,
                flowchart_run_node_id=77,
                artifact_type="plan",
            ),
        )


if __name__ == "__main__":
    unittest.main()
