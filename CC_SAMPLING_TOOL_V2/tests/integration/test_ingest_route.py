import pytest
import io
import openpyxl
from api.app import create_app
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base


def _build_xlsx_bytes() -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("매출채권")
    ws.append(["거래처코드", "거래처명", "계정과목", "기말잔액", "통화"])
    ws.append(["P1", "갑", "11200", 1000, "KRW"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def client():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SF = make_session(engine)
    app = create_app(testing=True, session_factory=SF)
    return app.test_client()


def test_ingest_endpoint_success(client):
    r = client.post("/api/projects", json={
        "client": "X", "period_end": "2025-12-31",
        "base_ccy": "KRW", "materiality": 1_000_000, "tolerable": 500_000,
    })
    pid = r.get_json()["id"]

    data = {
        "ledger": (io.BytesIO(_build_xlsx_bytes()), "ledger.xlsx"),
    }
    resp = client.post(f"/api/projects/{pid}/ingest",
                       data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ar_count"] == 1
    assert body["ap_count"] == 0


def test_ingest_missing_ledger(client):
    r = client.post("/api/projects", json={
        "client": "X", "period_end": "2025-12-31",
        "base_ccy": "KRW", "materiality": 1, "tolerable": 1,
    })
    pid = r.get_json()["id"]
    resp = client.post(f"/api/projects/{pid}/ingest",
                       data={}, content_type="multipart/form-data")
    assert resp.status_code == 400
