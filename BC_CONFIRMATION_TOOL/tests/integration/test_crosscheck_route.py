from fastapi.testclient import TestClient
from api.app import app

def test_crosscheck_endpoint_returns_6_sections():
    c = TestClient(app)
    pid = c.post("/api/projects", json={"name":"X","fiscal_date":"2025-12-31"}).json()["id"]
    # cs 없이 실행 → 빈 결과 OK
    r = c.post(f"/api/projects/{pid}/crosscheck/run")
    assert r.status_code == 200
    body = r.json()
    for key in ("bidirectional","prior","union","collateral","guarantee","address"):
        assert key in body
