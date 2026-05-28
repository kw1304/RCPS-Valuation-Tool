"""Flask app factory. Phase 1은 healthz만. Phase 2부터 라우트 추가."""
from __future__ import annotations
from flask import Flask, jsonify


def create_app(testing: bool = False) -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = testing

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    return app
