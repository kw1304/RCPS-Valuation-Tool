from fastapi.testclient import TestClient
from api.app import app
from pathlib import Path

def test_export_endpoint_returns_xlsx():
    c = TestClient(app)
    r = c.post("/api/projects", json={"name": "테스트", "fiscal_date": "2025-12-31"})
    assert r.status_code == 200
    pid = r.json()["id"]
    r = c.post(f"/api/projects/{pid}/workpaper/export")
    assert r.status_code == 200
    # Check that it's an xlsx file
    content_type = r.headers.get("content-type") or ""
    assert "spreadsheet" in content_type or "xlsx" in content_type
