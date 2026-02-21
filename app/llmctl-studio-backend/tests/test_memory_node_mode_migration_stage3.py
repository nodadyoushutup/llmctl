from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

from core.db import (
    _normalize_memory_node_fallback_enabled_for_migration,
    _normalize_memory_node_mode_for_migration,
    _normalize_memory_node_retry_count_for_migration,
    _parse_memory_node_config_for_migration,
)


class MemoryNodeModeMigrationStage3Tests(unittest.TestCase):
    def test_parse_memory_config_accepts_blank_payload(self) -> None:
        self.assertEqual({}, _parse_memory_node_config_for_migration(None, node_id=1))
        self.assertEqual({}, _parse_memory_node_config_for_migration("", node_id=1))

    def test_parse_memory_config_accepts_json_object_payload(self) -> None:
        parsed = _parse_memory_node_config_for_migration(
            '{"action":"add","mode":"deterministic"}',
            node_id=42,
        )
        self.assertEqual("add", parsed.get("action"))
        self.assertEqual("deterministic", parsed.get("mode"))

    def test_parse_memory_config_rejects_non_object_payload(self) -> None:
        with self.assertRaises(RuntimeError):
            _parse_memory_node_config_for_migration('["not-an-object"]', node_id=4)
        with self.assertRaises(RuntimeError):
            _parse_memory_node_config_for_migration("not-json", node_id=5)

    def test_normalize_memory_mode_defaults_to_llm_guided(self) -> None:
        self.assertEqual("deterministic", _normalize_memory_node_mode_for_migration("deterministic"))
        self.assertEqual("llm_guided", _normalize_memory_node_mode_for_migration("llm_guided"))
        self.assertEqual("llm_guided", _normalize_memory_node_mode_for_migration("bad-value"))
        self.assertEqual("llm_guided", _normalize_memory_node_mode_for_migration(None))

    def test_normalize_retry_count_clamps_and_defaults(self) -> None:
        self.assertEqual(1, _normalize_memory_node_retry_count_for_migration(None))
        self.assertEqual(0, _normalize_memory_node_retry_count_for_migration(-7))
        self.assertEqual(3, _normalize_memory_node_retry_count_for_migration("3"))
        self.assertEqual(5, _normalize_memory_node_retry_count_for_migration(99))
        self.assertEqual(1, _normalize_memory_node_retry_count_for_migration("nope"))

    def test_normalize_fallback_enabled_defaults_when_invalid(self) -> None:
        self.assertTrue(_normalize_memory_node_fallback_enabled_for_migration(None))
        self.assertTrue(_normalize_memory_node_fallback_enabled_for_migration("true"))
        self.assertTrue(_normalize_memory_node_fallback_enabled_for_migration("on"))
        self.assertFalse(_normalize_memory_node_fallback_enabled_for_migration("false"))
        self.assertFalse(_normalize_memory_node_fallback_enabled_for_migration(0))
        self.assertTrue(_normalize_memory_node_fallback_enabled_for_migration("unknown"))


if __name__ == "__main__":
    unittest.main()
