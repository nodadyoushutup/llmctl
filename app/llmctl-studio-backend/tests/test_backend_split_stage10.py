from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

from flask import Flask, session

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

os.environ.setdefault(
    "LLMCTL_STUDIO_DATABASE_URI",
    "postgresql+psycopg://llmctl:llmctl@127.0.0.1:15432/llmctl_studio",
)

from web.app import (  # noqa: E402
    _configure_react_only_runtime_guard,
    _configure_socketio_api_prefix_alias,
    _is_react_only_allowed_path,
    _register_blueprints,
)


class BackendSplitStage10Tests(unittest.TestCase):
    def test_api_health_is_reachable_from_primary_and_prefixed_alias_paths(self) -> None:
        app = Flask(__name__)
        app.config.update(API_PREFIX="/api")
        _register_blueprints(app)
        client = app.test_client()

        primary = client.get("/api/health")
        prefixed_alias = client.get("/api/api/health")

        self.assertEqual(200, primary.status_code)
        self.assertEqual(200, prefixed_alias.status_code)
        self.assertEqual(primary.get_json(), prefixed_alias.get_json())
        self.assertEqual(
            {"ok": True, "service": "llmctl-studio-backend"},
            primary.get_json(),
        )

    def test_socketio_alias_supports_custom_socketio_path_behind_api_prefix(self) -> None:
        app = Flask(__name__)
        app.config.update(API_PREFIX="/api", SOCKETIO_PATH="rt/socket.io")

        @app.get("/rt/socket.io/ping")
        def socket_ping():
            return {"ok": True}

        _configure_socketio_api_prefix_alias(app)
        client = app.test_client()

        canonical = client.get("/rt/socket.io/ping")
        prefixed = client.get("/api/rt/socket.io/ping")

        self.assertEqual(200, canonical.status_code)
        self.assertEqual(200, prefixed.status_code)
        self.assertEqual({"ok": True}, prefixed.get_json())

    def test_session_cookie_roundtrip_works_for_api_routes(self) -> None:
        app = Flask(__name__)
        app.secret_key = "stage10-test-secret"

        @app.post("/api/session/login")
        def login():
            session["user"] = "stage10"
            return {"ok": True}

        @app.get("/api/session/me")
        def me():
            return {"user": session.get("user")}

        client = app.test_client()
        login_response = client.post("/api/session/login")
        me_response = client.get("/api/session/me")

        self.assertEqual(200, login_response.status_code)
        self.assertEqual(200, me_response.status_code)
        self.assertEqual({"user": "stage10"}, me_response.get_json())

    def test_react_only_runtime_blocks_legacy_gui_routes_and_keeps_api_health(self) -> None:
        app = Flask(__name__)
        app.config.update(
            API_PREFIX="/api",
            SOCKETIO_PATH="socket.io",
            REACT_ONLY_RUNTIME=True,
        )
        _configure_react_only_runtime_guard(app)
        _register_blueprints(app)
        client = app.test_client()

        legacy_response = client.get("/agents")
        api_health = client.get("/api/health")

        self.assertEqual(404, legacy_response.status_code)
        self.assertEqual(
            {
                "error": "Not found.",
                "reason": "react_only_runtime_api_surface",
            },
            legacy_response.get_json(),
        )
        self.assertEqual(200, api_health.status_code)
        self.assertEqual(
            {"ok": True, "service": "llmctl-studio-backend"},
            api_health.get_json(),
        )

    def test_react_only_allowed_path_checks_api_and_socketio_surfaces(self) -> None:
        self.assertTrue(
            _is_react_only_allowed_path(
                "/api/agents",
                api_prefix="/api",
                socketio_path="/socket.io",
            )
        )
        self.assertTrue(
            _is_react_only_allowed_path(
                "/socket.io/",
                api_prefix="/api",
                socketio_path="/socket.io",
            )
        )
        self.assertFalse(
            _is_react_only_allowed_path(
                "/agents",
                api_prefix="/api",
                socketio_path="/socket.io",
            )
        )


if __name__ == "__main__":
    unittest.main()
