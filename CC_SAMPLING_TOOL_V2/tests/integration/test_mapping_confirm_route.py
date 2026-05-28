import pytest
from datetime import date
from api.app import create_app
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import ProjectRepo


@pytest.fixture
def client():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    SF = make_session(e)
    app = create_app(testing=True, session_factory=SF)
    s = SF()
    pid = ProjectRepo(s).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=1, tolerable=1)
    s.close()
    return app.test_client(), pid


def test_confirm_mapping_acks(client):
    c, pid = client
    r = c.post(f"/api/projects/{pid}/ingest/confirm-mapping")
    assert r.status_code == 200
    assert r.get_json()["status"] == "confirmed"
