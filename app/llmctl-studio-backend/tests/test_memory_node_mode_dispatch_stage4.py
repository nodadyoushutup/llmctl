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


class MemoryNodeModeDispatchStage4Tests(unittest.TestCase):
    def test_memory_dispatch_uses_deterministic_helper_when_mode_deterministic(self) -> None:
        sentinel = (
            {
                "node_type": "memory",
                "action": "add",
                "stored_memory": {"id": 22, "description": "stored"},
                "action_results": ["ok"],
            },
            {"route_key": "ok"},
        )
        with patch.object(
            studio_tasks,
            "_execute_flowchart_memory_node_deterministic",
            return_value=sentinel,
        ) as deterministic_mock, patch.object(
            studio_tasks,
            "_execute_flowchart_memory_node_llm_guided",
            return_value=({"node_type": "memory"}, {}),
        ) as llm_guided_mock:
            output_state, routing_state = studio_tasks._execute_flowchart_memory_node(
                node_id=11,
                node_ref_id=22,
                node_config={"action": "add", "mode": "deterministic"},
                input_context={"node": {"execution_index": 1}},
                mcp_server_keys=["llmctl-mcp"],
            )

        self.assertEqual(sentinel[0], output_state)
        self.assertEqual(sentinel[1], routing_state)
        deterministic_mock.assert_called_once()
        llm_guided_mock.assert_not_called()

    def test_memory_dispatch_defaults_to_llm_guided_mode(self) -> None:
        sentinel = (
            {
                "node_type": "memory",
                "action": "retrieve",
                "retrieved_memories": [{"id": 1, "description": "match"}],
                "action_results": ["ok"],
            },
            {},
        )
        with patch.object(
            studio_tasks,
            "_execute_flowchart_memory_node_llm_guided",
            return_value=sentinel,
        ) as llm_guided_mock, patch.object(
            studio_tasks,
            "_execute_flowchart_memory_node_deterministic",
            return_value=({"node_type": "memory"}, {}),
        ) as deterministic_mock:
            output_state, routing_state = studio_tasks._execute_flowchart_memory_node(
                node_id=33,
                node_ref_id=None,
                node_config={"action": "retrieve"},
                input_context={},
                mcp_server_keys=["llmctl-mcp"],
            )

        self.assertEqual(sentinel[0], output_state)
        self.assertEqual(sentinel[1], routing_state)
        llm_guided_mock.assert_called_once()
        deterministic_mock.assert_not_called()

    def test_llm_guided_dispatch_routes_add_action(self) -> None:
        sentinel = ({"node_type": "memory", "action": "add"}, {})
        with patch.object(
            studio_tasks,
            "_execute_flowchart_memory_node_llm_guided_add",
            return_value=sentinel,
        ) as add_mock, patch.object(
            studio_tasks,
            "_execute_flowchart_memory_node_llm_guided_retrieve",
            return_value=({"node_type": "memory", "action": "retrieve"}, {}),
        ) as retrieve_mock:
            output_state, routing_state = studio_tasks._execute_flowchart_memory_node_llm_guided(
                node_id=44,
                node_ref_id=None,
                node_config={"action": "add"},
                input_context={},
                mcp_server_keys=["llmctl-mcp"],
            )

        self.assertEqual(sentinel[0], output_state)
        self.assertEqual(sentinel[1], routing_state)
        add_mock.assert_called_once()
        retrieve_mock.assert_not_called()

    def test_llm_guided_dispatch_routes_retrieve_action(self) -> None:
        sentinel = ({"node_type": "memory", "action": "retrieve"}, {})
        with patch.object(
            studio_tasks,
            "_execute_flowchart_memory_node_llm_guided_retrieve",
            return_value=sentinel,
        ) as retrieve_mock, patch.object(
            studio_tasks,
            "_execute_flowchart_memory_node_llm_guided_add",
            return_value=({"node_type": "memory", "action": "add"}, {}),
        ) as add_mock:
            output_state, routing_state = studio_tasks._execute_flowchart_memory_node_llm_guided(
                node_id=55,
                node_ref_id=66,
                node_config={"action": "retrieve"},
                input_context={},
                mcp_server_keys=["llmctl-mcp"],
            )

        self.assertEqual(sentinel[0], output_state)
        self.assertEqual(sentinel[1], routing_state)
        retrieve_mock.assert_called_once()
        add_mock.assert_not_called()

    def test_llm_guided_dispatch_requires_supported_action(self) -> None:
        with self.assertRaisesRegex(ValueError, "Memory node action is required"):
            studio_tasks._execute_flowchart_memory_node_llm_guided(
                node_id=77,
                node_ref_id=None,
                node_config={"action": "unsupported"},
                input_context={},
                mcp_server_keys=["llmctl-mcp"],
            )


if __name__ == "__main__":
    unittest.main()
