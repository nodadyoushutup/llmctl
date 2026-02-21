from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

from services import tasks as studio_tasks


class MemoryNodeLlmGuidedRetrieveStage6Tests(unittest.TestCase):
    def test_normalize_llm_guided_retrieve_payload_applies_bounds(self) -> None:
        payload = studio_tasks._normalize_memory_llm_guided_retrieve_payload(
            {
                "query_text": "  deployment readiness  ",
                "memory_id": "17",
                "limit": 999,
                "confidence": "0.25",
            },
            default_limit=7,
        )
        self.assertEqual("deployment readiness", payload.get("query_text"))
        self.assertEqual(17, payload.get("memory_id"))
        self.assertEqual(50, payload.get("limit"))
        self.assertEqual(0.25, payload.get("confidence"))

    def test_normalize_llm_guided_retrieve_payload_defaults_when_values_missing(self) -> None:
        payload = studio_tasks._normalize_memory_llm_guided_retrieve_payload(
            {
                "query_text": "   ",
                "memory_id": "invalid",
            },
            default_limit=12,
        )
        self.assertEqual("", payload.get("query_text"))
        self.assertNotIn("memory_id", payload)
        self.assertEqual(12, payload.get("limit"))

    def test_llm_guided_retrieve_prefers_inferred_memory_id_when_no_ref(self) -> None:
        deterministic_output = {
            "node_type": "memory",
            "action": "retrieve",
            "action_results": ["Retrieved memory 44 via llmctl-mcp."],
        }
        with patch.object(
            studio_tasks,
            "_resolve_memory_llm_guided_runtime",
            return_value=(
                "codex",
                {},
                {},
                {"provider": "codex", "model_id": 7, "model_name": "Memory Model"},
            ),
        ), patch.object(
            studio_tasks,
            "_run_llm",
            return_value=SimpleNamespace(
                returncode=0,
                stdout='{"memory_id":44,"query_text":"ignored","limit":3,"confidence":0.6}',
                stderr="",
            ),
        ), patch.object(
            studio_tasks,
            "_execute_flowchart_memory_node_deterministic",
            return_value=(deterministic_output, {}),
        ) as deterministic_mock:
            output_state, routing_state = studio_tasks._execute_flowchart_memory_node_llm_guided_retrieve(
                node_id=9,
                node_ref_id=None,
                node_config={"action": "retrieve"},
                input_context={"node": {"execution_index": 2}},
                mcp_server_keys=["llmctl-mcp"],
                execution_id=33,
                enabled_providers={"codex"},
                default_model_id=7,
            )

        self.assertEqual({}, routing_state)
        call_kwargs = deterministic_mock.call_args.kwargs
        self.assertEqual(44, call_kwargs.get("node_ref_id"))
        self.assertEqual(3, call_kwargs.get("node_config", {}).get("limit"))
        self.assertEqual("retrieve", call_kwargs.get("node_config", {}).get("action"))
        retrieve_meta = output_state.get("llm_guided_retrieve") or {}
        self.assertEqual("inferred_memory_id", retrieve_meta.get("retrieval_resolution"))
        self.assertEqual(44, retrieve_meta.get("resolved_memory_id"))
        self.assertTrue(
            any(
                "LLM-guided retrieve inferred retrieval parameters" in str(item)
                for item in (output_state.get("action_results") or [])
            )
        )

    def test_llm_guided_retrieve_respects_explicit_ref_id_over_inferred_memory_id(self) -> None:
        with patch.object(
            studio_tasks,
            "_resolve_memory_llm_guided_runtime",
            return_value=(
                "codex",
                {},
                {},
                {"provider": "codex", "model_id": 7, "model_name": "Memory Model"},
            ),
        ), patch.object(
            studio_tasks,
            "_run_llm",
            return_value=SimpleNamespace(
                returncode=0,
                stdout='{"memory_id":99,"query_text":"ignored","limit":2}',
                stderr="",
            ),
        ), patch.object(
            studio_tasks,
            "_execute_flowchart_memory_node_deterministic",
            return_value=(
                {"node_type": "memory", "action": "retrieve", "action_results": []},
                {},
            ),
        ) as deterministic_mock:
            output_state, _ = studio_tasks._execute_flowchart_memory_node_llm_guided_retrieve(
                node_id=9,
                node_ref_id=5,
                node_config={"action": "retrieve"},
                input_context={"node": {"execution_index": 2}},
                mcp_server_keys=["llmctl-mcp"],
                execution_id=33,
                enabled_providers={"codex"},
                default_model_id=7,
            )

        call_kwargs = deterministic_mock.call_args.kwargs
        self.assertEqual(5, call_kwargs.get("node_ref_id"))
        retrieve_meta = output_state.get("llm_guided_retrieve") or {}
        self.assertEqual("node_ref_id", retrieve_meta.get("retrieval_resolution"))
        self.assertEqual(5, retrieve_meta.get("resolved_memory_id"))

    def test_llm_guided_retrieve_empty_query_uses_unfiltered_query_path(self) -> None:
        with patch.object(
            studio_tasks,
            "_resolve_memory_llm_guided_runtime",
            return_value=(
                "codex",
                {},
                {},
                {"provider": "codex", "model_id": 7, "model_name": "Memory Model"},
            ),
        ), patch.object(
            studio_tasks,
            "_run_llm",
            return_value=SimpleNamespace(
                returncode=0,
                stdout='{"query_text":"   ","limit":8}',
                stderr="",
            ),
        ), patch.object(
            studio_tasks,
            "_execute_flowchart_memory_node_deterministic",
            return_value=(
                {"node_type": "memory", "action": "retrieve", "action_results": []},
                {},
            ),
        ) as deterministic_mock:
            studio_tasks._execute_flowchart_memory_node_llm_guided_retrieve(
                node_id=9,
                node_ref_id=None,
                node_config={"action": "retrieve", "additive_prompt": "should not be used"},
                input_context={
                    "node": {"execution_index": 7},
                    "latest_upstream": {"output_state": {"message": "upstream context"}},
                },
                mcp_server_keys=["llmctl-mcp"],
                execution_id=33,
                enabled_providers={"codex"},
                default_model_id=7,
            )

        call_kwargs = deterministic_mock.call_args.kwargs
        self.assertEqual("", call_kwargs.get("node_config", {}).get("query"))
        self.assertEqual("", call_kwargs.get("node_config", {}).get("additive_prompt"))
        self.assertEqual({"node": {"execution_index": 7}}, call_kwargs.get("input_context"))

    def test_llm_guided_retrieve_raises_on_llm_runtime_failure(self) -> None:
        with patch.object(
            studio_tasks,
            "_resolve_memory_llm_guided_runtime",
            return_value=("codex", {}, {}, {"provider": "codex", "model_id": 7, "model_name": "Model"}),
        ), patch.object(
            studio_tasks,
            "_run_llm",
            return_value=SimpleNamespace(returncode=1, stdout="", stderr="retrieve failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "retrieve failure"):
                studio_tasks._execute_flowchart_memory_node_llm_guided_retrieve(
                    node_id=9,
                    node_ref_id=None,
                    node_config={"action": "retrieve"},
                    input_context={},
                    mcp_server_keys=["llmctl-mcp"],
                    execution_id=33,
                    enabled_providers={"codex"},
                    default_model_id=7,
                )


if __name__ == "__main__":
    unittest.main()
