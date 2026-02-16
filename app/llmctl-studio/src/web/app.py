from __future__ import annotations

from pathlib import Path

from flask import Flask
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


def create_app() -> Flask:
    template_dir = Path(__file__).resolve().parent / "templates"
    app = Flask(__name__, template_folder=str(template_dir))
    app.config.from_object(Config)
    _configure_proxy_middleware(app)
    init_socketio(app)

    init_engine(app.config["SQLALCHEMY_DATABASE_URI"])
    init_db()
    seed_defaults()
    apply_runtime_migrations()

    seeder_db = _SeederDB(create_session)
    seeder = FlaskSeeder()
    seeder.init_app(app, seeder_db)

    @app.teardown_appcontext
    def _shutdown_seeder_session(_exception=None):
        seeder_db.close()

    app.register_blueprint(agents_bp)
    app.register_blueprint(rag_bp)

    return app
