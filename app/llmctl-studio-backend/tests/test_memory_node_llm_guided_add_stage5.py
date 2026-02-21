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


class MemoryNodeLlmGuidedAddStage5Tests(unittest.TestCase):
    def test_normalize_llm_guided_add_payload_validates_and_normalizes(self) -> None:
        payload = studio_tasks._normalize_memory_llm_guided_add_payload(
            {
                "text": "  keep this context  ",
                "store_mode": "replace",
                "confidence": 1.4,
            }
        )
        self.assertEqual("keep this context", payload.get("text"))
        self.assertEqual("replace", payload.get("store_mode"))
        self.assertEqual(1.0, payload.get("confidence"))

    def test_normalize_llm_guided_add_payload_requires_non_empty_text(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires string field 'text'"):
            studio_tasks._normalize_memory_llm_guided_add_payload({"text": 123})
        with self.assertRaisesRegex(ValueError, "empty 'text'"):
            studio_tasks._normalize_memory_llm_guided_add_payload({"text": "   "})

    def test_llm_guided_add_infers_payload_and_reuses_deterministic_writer(self) -> None:
        deterministic_output = {
            "node_type": "memory",
            "action": "add",
            "action_results": ["Created memory 10 via llmctl-mcp."],
        }
        with patch.object(
            studio_tasks,
            "_resolve_memory_llm_guided_runtime",
            return_value=(
                "codex",
                {},
                {},
                {"provider": "codex", "model_id": 4, "model_name": "Memory Model"},
            ),
        ), patch.object(
            studio_tasks,
            "_run_llm",
            return_value=SimpleNamespace(
                returncode=0,
                stdout='{"text":"persist this insight","store_mode":"replace","confidence":0.72}',
                stderr="",
            ),
        ), patch.object(
            studio_tasks,
            "_execute_flowchart_memory_node_deterministic",
            return_value=(deterministic_output, {}),
        ) as deterministic_mock:
            output_state, routing_state = studio_tasks._execute_flowchart_memory_node_llm_guided_add(
                node_id=9,
                node_ref_id=10,
                node_config={"action": "add", "additive_prompt": "remember release blockers"},
                input_context={"node": {"execution_index": 2}},
                mcp_server_keys=["llmctl-mcp"],
                execution_id=33,
                enabled_providers={"codex"},
                default_model_id=4,
            )

        deterministic_config = deterministic_mock.call_args.kwargs["node_config"]
        self.assertEqual("persist this insight", deterministic_config.get("text"))
        self.assertEqual("replace", deterministic_config.get("store_mode"))
        self.assertEqual({}, routing_state)
        self.assertTrue(
            any(
                "LLM-guided add inferred memory payload" in str(item)
                for item in (output_state.get("action_results") or [])
            )
        )
        llm_guided_payload = output_state.get("llm_guided_add") or {}
        self.assertEqual("codex", llm_guided_payload.get("provider"))
        self.assertEqual(4, llm_guided_payload.get("model_id"))
        inference_payload = llm_guided_payload.get("inference_payload") or {}
        self.assertEqual("persist this insight", inference_payload.get("text"))
        self.assertEqual("replace", inference_payload.get("store_mode"))
        self.assertEqual(0.72, inference_payload.get("confidence"))

    def test_llm_guided_add_raises_on_llm_runtime_failure(self) -> None:
        with patch.object(
            studio_tasks,
            "_resolve_memory_llm_guided_runtime",
            return_value=("codex", {}, {}, {"provider": "codex", "model_id": 4, "model_name": "Model"}),
        ), patch.object(
            studio_tasks,
            "_run_llm",
            return_value=SimpleNamespace(returncode=1, stdout="", stderr="boom"),
        ):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                studio_tasks._execute_flowchart_memory_node_llm_guided_add(
                    node_id=9,
                    node_ref_id=None,
                    node_config={"action": "add"},
                    input_context={},
                    mcp_server_keys=["llmctl-mcp"],
                    execution_id=19,
                    enabled_providers={"codex"},
                    default_model_id=4,
                )


if __name__ == "__main__":
    unittest.main()
