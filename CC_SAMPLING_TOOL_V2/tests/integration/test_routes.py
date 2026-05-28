import pytest
from api.app import create_app
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base


@pytest.fixture
def app():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session(engine)
    app = create_app(testing=True, session_factory=SessionFactory)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_create_project(client):
    resp = client.post("/api/projects", json={
        "client": "ACME", "period_end": "2025-12-31",
        "base_ccy": "KRW", "materiality": 500_000_000,
        "tolerable": 250_000_000,
    })
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["id"] > 0
    assert body["client"] == "ACME"


def test_list_projects(client):
    client.post("/api/projects", json={
        "client": "A", "period_end": "2025-12-31",
        "base_ccy": "KRW", "materiality": 1, "tolerable": 1,
    })
    client.post("/api/projects", json={
        "client": "B", "period_end": "2025-12-31",
        "base_ccy": "KRW", "materiality": 1, "tolerable": 1,
    })
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body) == 2


def test_get_project(client):
    r = client.post("/api/projects", json={
        "client": "X", "period_end": "2025-12-31",
        "base_ccy": "KRW", "materiality": 1, "tolerable": 1,
    })
    pid = r.get_json()["id"]
    resp = client.get(f"/api/projects/{pid}")
    assert resp.status_code == 200
    assert resp.get_json()["client"] == "X"


def test_get_project_not_found(client):
    resp = client.get("/api/projects/99999")
    assert resp.status_code == 404
