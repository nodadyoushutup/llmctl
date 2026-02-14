from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from config import load_config


class ConfigPrecedenceTests(unittest.TestCase):
    def test_rag_settings_override_environment(self):
        rag_settings = {
            "embed_provider": "gemini",
            "chat_provider": "gemini",
            "gemini_api_key": "db-key",
            "gemini_embed_model": "models/gemini-embedding-001",
            "gemini_chat_model": "gemini-2.5-flash",
        }
        with patch.dict(
            os.environ,
            {
                "RAG_EMBED_PROVIDER": "openai",
                "RAG_CHAT_PROVIDER": "openai",
                "OPENAI_API_KEY": "env-openai-key",
            },
            clear=True,
        ):
            with patch(
                "config.load_integration_settings",
                side_effect=lambda provider: rag_settings if provider == "rag" else {},
            ):
                config = load_config()
        self.assertEqual(config.embed_provider, "gemini")
        self.assertEqual(config.chat_provider, "gemini")
        self.assertEqual(config.gemini_api_key, "db-key")

    def test_environment_used_when_rag_setting_is_missing(self):
        with patch.dict(
            os.environ,
            {
                "RAG_EMBED_PROVIDER": "gemini",
                "GEMINI_API_KEY": "env-gemini-key",
            },
            clear=True,
        ):
            with patch("config.load_integration_settings", return_value={}):
                config = load_config()
        self.assertEqual(config.embed_provider, "gemini")
        self.assertEqual(config.gemini_api_key, "env-gemini-key")


if __name__ == "__main__":
    unittest.main()
