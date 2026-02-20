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

from services.flow_migration import (  # noqa: E402
    analyze_flowchart_migration_snapshot,
    apply_flowchart_snapshot_migration,
)


class _FakeNode:
    def __init__(self, node_id: int, config_json: str) -> None:
        self.id = node_id
        self.config_json = config_json


class _FakeEdge:
    def __init__(self, edge_id: int, edge_mode: str, condition_key: str | None = None) -> None:
        self.id = edge_id
        self.edge_mode = edge_mode
        self.condition_key = condition_key


class _FakeFlowchart:
    def __init__(self, nodes: list[_FakeNode], edges: list[_FakeEdge]) -> None:
        self.nodes = nodes
        self.edges = edges


class FlowMigrationStage13Tests(unittest.TestCase):
    def test_transform_generates_decision_connector_ids_and_conditions(self) -> None:
        snapshot = {
            "flowchart": {"id": 100, "name": "legacy-decision"},
            "nodes": [
                {"id": 1, "node_type": "start", "config": {}},
                {
                    "id": 2,
                    "node_type": "decision",
                    "config": {
                        "route_field_path": "legacy.path",
                        "fallback_condition_key": "connector_1",
                        "decision_conditions": [
                            {
                                "connector_id": "connector_1",
                                "condition_text": "value > 10",
                            }
                        ],
                    },
                },
                {"id": 3, "node_type": "task", "config": {"task_prompt": "left"}},
                {"id": 4, "node_type": "task", "config": {"task_prompt": "right"}},
            ],
            "edges": [
                {
                    "id": 10,
                    "source_node_id": 1,
                    "target_node_id": 2,
                    "edge_mode": "solid",
                    "condition_key": None,
                },
                {
                    "id": 11,
                    "source_node_id": 2,
                    "target_node_id": 3,
                    "edge_mode": "solid",
                    "condition_key": "connector_1",
                },
                {
                    "id": 12,
                    "source_node_id": 2,
                    "target_node_id": 4,
                    "edge_mode": "solid",
                    "condition_key": "connector_1",
                },
            ],
        }

        report = analyze_flowchart_migration_snapshot(
            snapshot,
            llmctl_mcp_server_id=999,
            strict_policy=True,
        )

        self.assertEqual("ready", report["compatibility_gate"]["status"])
        post_snapshot = report["post_migration_snapshot"]
        decision_node = next(
            node for node in post_snapshot["nodes"] if int(node["id"]) == 2
        )
        connector_ids = [
            str(edge.get("condition_key") or "")
            for edge in post_snapshot["edges"]
            if int(edge.get("source_node_id") or 0) == 2
        ]
        self.assertEqual(2, len(set(connector_ids)))
        self.assertEqual(2, len(decision_node["config"]["decision_conditions"]))
        self.assertNotIn("route_field_path", decision_node["config"])

    def test_compatibility_gate_blocks_policy_violation(self) -> None:
        snapshot = {
            "flowchart": {"id": 200, "name": "policy-violation"},
            "nodes": [
                {"id": 1, "node_type": "start", "config": {}},
                {"id": 2, "node_type": "task", "config": {"task_prompt": "work"}},
                {"id": 3, "node_type": "end", "config": {}},
            ],
            "edges": [
                {
                    "id": 21,
                    "source_node_id": 1,
                    "target_node_id": 2,
                    "edge_mode": "solid",
                    "condition_key": None,
                },
                {
                    "id": 22,
                    "source_node_id": 2,
                    "target_node_id": 3,
                    "edge_mode": "solid",
                    "condition_key": "route_a",
                },
            ],
        }

        report = analyze_flowchart_migration_snapshot(
            snapshot,
            llmctl_mcp_server_id=None,
            strict_policy=True,
        )
        self.assertEqual("blocked", report["compatibility_gate"]["status"])
        self.assertIn(
            "policy.non_decision_condition_key",
            report["compatibility_gate"]["blocking_issue_codes"],
        )
        self.assertIn("compatibility_gate_blocked", report["rollback"]["trigger_codes"])

    def test_dry_run_check_reports_unresolvable_route_key(self) -> None:
        snapshot = {
            "flowchart": {"id": 300, "name": "dry-run-failure"},
            "nodes": [
                {"id": 1, "node_type": "start", "config": {}},
                {
                    "id": 2,
                    "node_type": "memory",
                    "config": {"route_key": "not_found"},
                    "mcp_server_ids": [99],
                },
                {"id": 3, "node_type": "end", "config": {}},
            ],
            "edges": [
                {
                    "id": 31,
                    "source_node_id": 1,
                    "target_node_id": 2,
                    "edge_mode": "solid",
                    "condition_key": None,
                },
                {
                    "id": 32,
                    "source_node_id": 2,
                    "target_node_id": 3,
                    "edge_mode": "solid",
                    "condition_key": None,
                },
            ],
        }

        report = analyze_flowchart_migration_snapshot(
            snapshot,
            llmctl_mcp_server_id=99,
            strict_policy=True,
        )
        self.assertEqual("blocked", report["compatibility_gate"]["status"])
        blocking_codes = set(report["compatibility_gate"]["blocking_issue_codes"])
        self.assertIn("dry_run.route_resolution_failed", blocking_codes)

    def test_apply_flowchart_snapshot_migration_updates_records(self) -> None:
        flowchart = _FakeFlowchart(
            nodes=[_FakeNode(1, "{}")],
            edges=[_FakeEdge(11, "solid", None)],
        )
        transformed_snapshot = {
            "nodes": [{"id": 1, "config": {"task_prompt": "updated"}}],
            "edges": [
                {
                    "id": 11,
                    "edge_mode": "dotted",
                    "condition_key": None,
                }
            ],
        }

        updates = apply_flowchart_snapshot_migration(
            None,
            flowchart,
            transformed_snapshot,
        )

        self.assertEqual(1, updates["updated_nodes"])
        self.assertEqual(1, updates["updated_edges"])
        self.assertIn("task_prompt", flowchart.nodes[0].config_json)
        self.assertEqual("dotted", flowchart.edges[0].edge_mode)


if __name__ == "__main__":
    unittest.main()
