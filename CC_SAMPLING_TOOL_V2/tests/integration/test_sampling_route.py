import pytest
import io
import openpyxl
from api.app import create_app
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base


def _ledger_bytes():
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("매출채권")
    ws.append(["거래처코드", "거래처명", "계정", "기말잔액", "통화"])
    for i in range(50):
        ws.append([f"P{i:03d}", f"갑{i}", "11200", (i + 1) * 100_000, "KRW"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def client_with_project():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    SF = make_session(e)
    app = create_app(testing=True, session_factory=SF)
    c = app.test_client()
    r = c.post("/api/projects", json={
        "client": "X", "period_end": "2025-12-31",
        "base_ccy": "KRW", "materiality": 10_000_000, "tolerable": 5_000_000,
    })
    pid = r.get_json()["id"]
    c.post(f"/api/projects/{pid}/ingest",
           data={"ledger": (io.BytesIO(_ledger_bytes()), "x.xlsx")},
           content_type="multipart/form-data")
    return c, pid


def test_design_sampling(client_with_project):
    c, pid = client_with_project
    resp = c.post(f"/api/projects/{pid}/sampling/design", json={
        "kind": "AR",
        "confidence": 0.95,
        "expected_ms_pct": 0.0,
        "key_threshold": 999_999_999,
        "n_strata": 4,
        "seed": 42,
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["kind"] == "AR"
    assert body["n_total"] > 0
    assert body["used_seed"] == 42


def test_state_returns_dashboard_view(client_with_project):
    c, pid = client_with_project
    resp = c.get(f"/api/projects/{pid}/state")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["project"]["id"] == pid
    assert body["populations"]["AR"]["count"] == 50
    assert body["populations"]["AP"]["count"] == 0
    assert body["samples"]["AR"]["count"] == 0
    c.post(f"/api/projects/{pid}/sampling/design", json={
        "kind": "AR", "confidence": 0.95, "expected_ms_pct": 0.0,
        "key_threshold": 999_999_999, "n_strata": 4, "seed": 1,
    })
    resp = c.get(f"/api/projects/{pid}/state")
    body = resp.get_json()
    assert body["samples"]["AR"]["count"] > 0
    assert isinstance(body["samples"]["AR"]["items"], list)
    item = body["samples"]["AR"]["items"][0]
    assert "party_id" in item and "selection_reason" in item
