import pytest
from datetime import date
from api.app import create_app
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base


@pytest.fixture
def client():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    SF = make_session(e)
    app = create_app(testing=True, session_factory=SF)
    return app.test_client()


def test_delete_existing(client):
    r = client.post("/api/projects", json={
        "client": "X", "period_end": "2025-12-31", "base_ccy": "KRW",
        "materiality": 1, "tolerable": 1})
    pid = r.get_json()["id"]
    r = client.delete(f"/api/projects/{pid}")
    assert r.status_code == 200
    r = client.get(f"/api/projects/{pid}")
    assert r.status_code == 404


def test_delete_not_found(client):
    r = client.delete("/api/projects/99999")
    assert r.status_code == 404
