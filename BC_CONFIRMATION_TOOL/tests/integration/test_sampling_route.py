from fastapi.testclient import TestClient
from pathlib import Path
from api.app import app

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "mini_gl.xlsx"

def test_sampling_endpoint_runs_and_returns_parties():
    c = TestClient(app)
    r = c.post("/api/projects", json={"name": "테스트사", "fiscal_date": "2025-12-31"})
    assert r.status_code == 200
    pid = r.json()["id"]
    with open(FIX, "rb") as f:
        r = c.post(f"/api/projects/{pid}/upload/gl", files={"file": ("gl.xlsx", f.read())})
    assert r.status_code == 200
    r = c.post(f"/api/projects/{pid}/sampling/run")
    assert r.status_code == 200
    data = r.json()
    keys = {(p["canonical"], p["branch"]) for p in data["parties"]}
    assert ("국민은행", None) in keys
    assert ("신한은행", "도쿄지점") in keys
