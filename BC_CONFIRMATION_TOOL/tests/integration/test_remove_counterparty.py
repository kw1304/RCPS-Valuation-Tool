from fastapi.testclient import TestClient
from sqlmodel import Session
from api.app import app
from src.infrastructure.db.repository import get_engine, upsert_counterparty, list_counterparties


def test_remove_sampled_counterparty():
    c = TestClient(app)
    pid = c.post("/api/projects", json={"name": "rm-test", "fiscal_date": "2025-12-31"}).json()["id"]
    with Session(get_engine()) as s:
        cp = upsert_counterparty(s, pid, canonical_name="테스트은행", branch=None)
        cp_id = cp.id
        assert len(list_counterparties(s, pid)) == 1
    # 제거
    r = c.delete(f"/api/projects/{pid}/counterparty/{cp_id}")
    assert r.status_code == 200, r.text
    assert r.json()["remaining"] == 0
    with Session(get_engine()) as s:
        assert len(list_counterparties(s, pid)) == 0
    # 없는 id → 404
    assert c.delete(f"/api/projects/{pid}/counterparty/999999").status_code == 404
