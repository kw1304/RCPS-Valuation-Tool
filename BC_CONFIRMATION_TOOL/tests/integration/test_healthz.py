from fastapi.testclient import TestClient
from api.app import app

def test_healthz():
    c = TestClient(app)
    r = c.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"   # healthz가 DB 연결까지 확인
