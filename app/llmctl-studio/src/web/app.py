from __future__ import annotations

import atexit
from pathlib import Path

from flask import Flask
from flask_seeder import FlaskSeeder

from core.config import Config
from core.db import create_session, init_db, init_engine
from core.migrations import apply_runtime_migrations
from core.seed import seed_defaults
from rag.web.scheduler import start_source_scheduler, stop_source_scheduler
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


def create_app() -> Flask:
    template_dir = Path(__file__).resolve().parent / "templates"
    app = Flask(__name__, template_folder=str(template_dir))
    app.config.from_object(Config)

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
    start_source_scheduler()
    atexit.register(stop_source_scheduler)

    return app
