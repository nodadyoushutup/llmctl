from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

from core.db import _parse_legacy_mcp_config_for_jsonb_migration
from core.mcp_config import parse_mcp_config, render_mcp_config


class MCPConfigJsonStage12Tests(unittest.TestCase):
    def test_parse_accepts_plain_json_object(self) -> None:
        parsed = parse_mcp_config(
            '{"command":"python3","args":["app/llmctl-mcp/run.py"]}',
            server_key="llmctl-mcp",
        )
        self.assertEqual("python3", parsed["command"])
        self.assertEqual(["app/llmctl-mcp/run.py"], parsed["args"])

    def test_parse_accepts_wrapped_mcp_servers_json(self) -> None:
        parsed = parse_mcp_config(
            {
                "mcp_servers": {
                    "github": {
                        "command": "mcp-server-github",
                    }
                }
            },
            server_key="github",
        )
        self.assertEqual("mcp-server-github", parsed["command"])

    def test_parse_rejects_toml_input_after_cutover(self) -> None:
        with self.assertRaises(ValueError):
            parse_mcp_config(
                '[mcp_servers.github]\ncommand = "mcp-server-github"\n',
                server_key="github",
            )

    def test_render_returns_copy_of_validated_config(self) -> None:
        source = {"command": "mcp-server-github", "env": {"TOKEN": "secret"}}
        rendered = render_mcp_config(
            "github",
            source,
        )
        self.assertEqual("mcp-server-github", rendered["command"])
        rendered["command"] = "mutated"
        self.assertEqual("mcp-server-github", source["command"])

    def test_legacy_parser_accepts_toml_for_db_migration(self) -> None:
        converted = _parse_legacy_mcp_config_for_jsonb_migration(
            '[mcp_servers.github]\ncommand = "mcp-server-github"\n',
            server_key="github",
        )
        self.assertEqual("mcp-server-github", converted["command"])

    def test_legacy_parser_rejects_invalid_payload(self) -> None:
        with self.assertRaises(ValueError):
            _parse_legacy_mcp_config_for_jsonb_migration(
                "not-json-and-not-toml",
                server_key="github",
            )


if __name__ == "__main__":
    unittest.main()
