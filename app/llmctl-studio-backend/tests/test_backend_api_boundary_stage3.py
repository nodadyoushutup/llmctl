from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

from flask import Flask

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

os.environ.setdefault(
    "LLMCTL_STUDIO_DATABASE_URI",
    "postgresql+psycopg://llmctl:llmctl@127.0.0.1:15432/llmctl_studio",
)

from web.app import _configure_socketio_api_prefix_alias, _normalize_api_prefix  # noqa: E402
from web.views import (  # noqa: E402
    _flowchart_wants_json,
    _request_path_uses_api_prefix,
    _run_wants_json,
)
from rag.web.views import _wants_json_response as _rag_wants_json_response  # noqa: E402


class ApiPrefixBoundaryStage3Tests(unittest.TestCase):
    def test_api_prefix_normalization_handles_expected_inputs(self) -> None:
        self.assertEqual("/api", _normalize_api_prefix(""))
        self.assertEqual("/api", _normalize_api_prefix("api"))
        self.assertEqual("/api", _normalize_api_prefix("/api/"))
        self.assertEqual("/web", _normalize_api_prefix("/web"))
        self.assertEqual("/", _normalize_api_prefix("/"))

    def test_socketio_api_alias_reaches_canonical_socketio_path(self) -> None:
        app = Flask(__name__)
        app.config.update(API_PREFIX="/api", SOCKETIO_PATH="socket.io")

        @app.get("/socket.io/")
        def socket_probe():
            return {"ok": True}

        _configure_socketio_api_prefix_alias(app)
        client = app.test_client()

        root_response = client.get("/socket.io/?EIO=4&transport=polling")
        api_response = client.get("/api/socket.io/?EIO=4&transport=polling")

        self.assertEqual(200, root_response.status_code)
        self.assertEqual(200, api_response.status_code)
        self.assertEqual({"ok": True}, api_response.get_json())

    def test_api_prefixed_path_forces_json_mode_without_breaking_legacy_route_mode(self) -> None:
        app = Flask(__name__)
        app.config.update(API_PREFIX="/api")

        with app.test_request_context("/flowcharts", headers={"Accept": "text/html"}):
            self.assertFalse(_request_path_uses_api_prefix())
            self.assertFalse(_flowchart_wants_json())
            self.assertFalse(_run_wants_json())

        with app.test_request_context("/api/flowcharts", headers={"Accept": "text/html"}):
            self.assertTrue(_request_path_uses_api_prefix())
            self.assertTrue(_flowchart_wants_json())
            self.assertTrue(_run_wants_json())

    def test_api_prefixed_rag_paths_force_json_mode(self) -> None:
        app = Flask(__name__)
        app.config.update(API_PREFIX="/api")

        with app.test_request_context("/rag/chat", headers={"Accept": "text/html"}):
            self.assertFalse(_rag_wants_json_response())

        with app.test_request_context("/api/rag/chat", headers={"Accept": "text/html"}):
            self.assertTrue(_rag_wants_json_response())


if __name__ == "__main__":
    unittest.main()
