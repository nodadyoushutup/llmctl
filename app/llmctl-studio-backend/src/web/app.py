from __future__ import annotations

from typing import Callable

from flask import Flask, jsonify, request
from flask_seeder import FlaskSeeder
from werkzeug.middleware.proxy_fix import ProxyFix

from core.config import Config
from core.db import create_session, init_db, init_engine
from core.migrations import apply_runtime_migrations
from core.seed import seed_defaults
from rag.web.views import bp as rag_bp
from web.realtime import init_socketio
from web.views import bp as agents_bp


class _SeederDB:
    def __init__(self, session_factory):
        self._session_factory = session_factory
        self._session = None

    @property
    def session(self):
        if self._session is None:
            self._session = self._session_factory()
        return self._session

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None


class _SocketIOPathAliasMiddleware:
    """Support API-prefixed Socket.IO path without breaking legacy clients."""

    def __init__(
        self,
        app: Callable,
        *,
        prefixed_path: str,
        canonical_path: str,
    ) -> None:
        self._app = app
        self._prefixed_path = prefixed_path
        self._canonical_path = canonical_path

    def __call__(self, environ, start_response):
        path = str(environ.get("PATH_INFO", "") or "")
        if path.startswith(self._prefixed_path):
            suffix = path[len(self._prefixed_path) :]
            if not suffix or suffix.startswith("/"):
                environ["PATH_INFO"] = f"{self._canonical_path}{suffix}"
        return self._app(environ, start_response)


def _configure_proxy_middleware(app: Flask) -> None:
    if not bool(app.config.get("PROXY_FIX_ENABLED", False)):
        return

    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=int(app.config.get("PROXY_FIX_X_FOR", 1)),
        x_proto=int(app.config.get("PROXY_FIX_X_PROTO", 1)),
        x_host=int(app.config.get("PROXY_FIX_X_HOST", 1)),
        x_port=int(app.config.get("PROXY_FIX_X_PORT", 1)),
        x_prefix=int(app.config.get("PROXY_FIX_X_PREFIX", 1)),
    )


def _normalize_api_prefix(raw: object) -> str:
    value = str(raw or "").strip()
    if not value:
        return "/api"
    if value == "/":
        return "/"
    return f"/{value.strip('/')}"


def _configure_socketio_api_prefix_alias(app: Flask) -> None:
    api_prefix = _normalize_api_prefix(app.config.get("API_PREFIX", "/api"))
    if api_prefix == "/":
        return

    socketio_path = str(app.config.get("SOCKETIO_PATH", "socket.io")).strip().strip("/")
    if not socketio_path:
        socketio_path = "socket.io"

    api_segment = api_prefix.strip("/")
    if socketio_path.startswith(f"{api_segment}/"):
        return

    prefixed_path = f"{api_prefix}/{socketio_path}"
    canonical_path = f"/{socketio_path}"
    app.wsgi_app = _SocketIOPathAliasMiddleware(
        app.wsgi_app,
        prefixed_path=prefixed_path,
        canonical_path=canonical_path,
    )


def _normalize_socketio_path(raw: object) -> str:
    value = str(raw or "").strip().strip("/")
    if not value:
        value = "socket.io"
    return f"/{value}"


def _path_matches_prefix(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}/")


def _is_react_only_allowed_path(
    path: str,
    *,
    api_prefix: str,
    socketio_path: str,
) -> bool:
    normalized_path = str(path or "")
    if _path_matches_prefix(normalized_path, api_prefix):
        return True
    if _path_matches_prefix(normalized_path, socketio_path):
        return True
    return False


def _configure_react_only_runtime_guard(app: Flask) -> None:
    if not bool(app.config.get("REACT_ONLY_RUNTIME", True)):
        return

    api_prefix = _normalize_api_prefix(app.config.get("API_PREFIX", "/api"))
    socketio_path = _normalize_socketio_path(app.config.get("SOCKETIO_PATH", "socket.io"))

    @app.before_request
    def _react_only_runtime_guard():
        if _is_react_only_allowed_path(
            request.path or "",
            api_prefix=api_prefix,
            socketio_path=socketio_path,
        ):
            return None
        return (
            jsonify(
                {
                    "error": "Not found.",
                    "reason": "react_only_runtime_api_surface",
                }
            ),
            404,
        )


def _register_blueprints(app: Flask) -> None:
    api_prefix = _normalize_api_prefix(app.config.get("API_PREFIX", "/api"))
    app.register_blueprint(agents_bp)
    app.register_blueprint(rag_bp)
    if api_prefix != "/":
        app.register_blueprint(
            agents_bp,
            url_prefix=api_prefix,
            name="agents_api",
        )


def create_app() -> Flask:
    app = Flask(__name__, template_folder=None, static_folder=None)
    app.config.from_object(Config)
    _configure_proxy_middleware(app)
    init_socketio(app)
    _configure_socketio_api_prefix_alias(app)
    _configure_react_only_runtime_guard(app)

    init_engine(app.config["SQLALCHEMY_DATABASE_URI"])
    init_db()
    apply_runtime_migrations()
    seed_defaults()

    seeder_db = _SeederDB(create_session)
    seeder = FlaskSeeder()
    seeder.init_app(app, seeder_db)

    @app.teardown_appcontext
    def _shutdown_seeder_session(_exception=None):
        seeder_db.close()

    _register_blueprints(app)

    return app
