import pytest
from api.app import create_app


def test_app_factory_creates_flask_instance():
    app = create_app(testing=True)
    assert app is not None
    assert app.config["TESTING"] is True


def test_healthz_returns_ok():
    app = create_app(testing=True)
    client = app.test_client()
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json == {"status": "ok"}
