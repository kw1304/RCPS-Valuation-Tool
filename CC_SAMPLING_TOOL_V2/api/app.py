"""Flask app factory with route registration."""
from __future__ import annotations
from typing import Optional
from flask import Flask, jsonify, g
from src.infrastructure.db.session import make_engine, make_session


def create_app(testing: bool = False, session_factory=None) -> Flask:
    app = Flask(__name__, static_folder="../frontend",
                static_url_path="")
    app.config["TESTING"] = testing

    if session_factory is None:
        # Phase 1 fallback: default sqlite path. Ensure parent dir exists.
        from pathlib import Path
        Path("data").mkdir(parents=True, exist_ok=True)
        engine = make_engine()
        from src.infrastructure.db.models import Base
        Base.metadata.create_all(engine)
        session_factory = make_session(engine)
    app.config["SESSION_FACTORY"] = session_factory

    @app.before_request
    def open_session():
        g.session = session_factory()

    @app.teardown_request
    def close_session(exc):
        s = g.pop("session", None)
        if s is not None:
            s.close()

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    from api.routes.project import bp as project_bp
    app.register_blueprint(project_bp)

    from api.routes.ingest import bp as ingest_bp
    app.register_blueprint(ingest_bp)

    from api.routes.sampling import bp as sampling_bp
    app.register_blueprint(sampling_bp)

    from api.routes.state import bp as state_bp
    app.register_blueprint(state_bp)

    return app
