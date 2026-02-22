from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

os.environ.setdefault(
    "LLMCTL_STUDIO_DATABASE_URI",
    "postgresql+psycopg://llmctl:llmctl@127.0.0.1:15432/llmctl_studio",
)

from services.mcp_integrations import (
    map_mcp_servers_to_integration_keys,
    normalize_mcp_server_keys,
    resolve_effective_integrations_from_mcp,
)


class McpIntegrationsTests(unittest.TestCase):
    def test_normalize_mcp_server_keys_dedupes_and_lowercases(self) -> None:
        self.assertEqual(
            ["github", "atlassian", "chroma"],
            normalize_mcp_server_keys([" GitHub ", "ATLaSSIAN", "github", "", "Chroma"]),
        )

    def test_map_mcp_servers_to_integration_keys_uses_static_mapping(self) -> None:
        self.assertEqual(
            ["github", "jira", "confluence", "google_workspace"],
            map_mcp_servers_to_integration_keys([
                "github",
                "atlassian",
                "jira",
                "google-workspace",
                "unknown-custom",
            ]),
        )

    def test_resolve_effective_integrations_skips_unconfigured_with_warning(self) -> None:
        with patch("services.mcp_integrations.load_integration_settings", return_value={}):
            resolved = resolve_effective_integrations_from_mcp(["github"])

        self.assertEqual(["github"], resolved.selected_mcp_server_keys)
        self.assertEqual(["github"], resolved.mapped_integration_keys)
        self.assertEqual([], resolved.configured_integration_keys)
        self.assertEqual(["github"], resolved.skipped_integration_keys)
        self.assertTrue(resolved.warnings)
        self.assertIn("Skipping integration 'github'", resolved.warnings[0])

    def test_resolve_effective_integrations_accepts_jira_confluence_defaults(self) -> None:
        def _settings(provider: str) -> dict[str, str]:
            if provider == "jira":
                return {
                    "site": "https://example.atlassian.net",
                    "project_key": "OPS",
                }
            if provider == "confluence":
                return {
                    "site": "https://example.atlassian.net/wiki",
                    "space": "ENG",
                }
            return {}

        with patch("services.mcp_integrations.load_integration_settings", side_effect=_settings):
            resolved = resolve_effective_integrations_from_mcp(["atlassian"])

        self.assertEqual(["jira", "confluence"], resolved.mapped_integration_keys)
        self.assertEqual(["jira", "confluence"], resolved.configured_integration_keys)
        self.assertEqual([], resolved.skipped_integration_keys)
        self.assertEqual([], resolved.warnings)


if __name__ == "__main__":
    unittest.main()
