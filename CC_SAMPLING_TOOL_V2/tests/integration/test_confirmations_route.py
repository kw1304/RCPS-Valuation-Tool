import pytest
import io
from pathlib import Path
import openpyxl
from datetime import date
from api.app import create_app
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo,
)
from src.domain.entities import Account, Kind, SelectionReason


def _make_pdf_bytes(text):
    try:
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfbase import pdfmetrics
        pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
    except ImportError:
        pytest.skip("reportlab not installed")
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setFont("HYSMyeongJo-Medium", 11)
    for i, line in enumerate(text.split("\n")):
        c.drawString(50, 800 - i * 20, line)
    c.save()
    return buf.getvalue()


@pytest.fixture
def client_with_sample():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    SF = make_session(e)
    app = create_app(testing=True, session_factory=SF)
    s = SF()
    pid = ProjectRepo(s).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=10_000, tolerable=5_000)
    acc = Account(party_id="P1", name="고객사001", gl_account="11200",
                  balance_orig=1_500_000, ccy="KRW", fx_rate=1.0,
                  balance_krw=1_500_000)
    AccountRepo(s).bulk_insert(pid, Kind.AR, [acc])
    accs = AccountRepo(s).list_by_project_kind(pid, Kind.AR)
    SampleRepo(s).persist(pid, Kind.AR, [(accs[0], SelectionReason.FORCED_RP)])
    s.close()
    return app.test_client(), pid


def test_sendlist_download(client_with_sample):
    c, pid = client_with_sample
    r = c.get(f"/api/projects/{pid}/sendlist")
    assert r.status_code == 200
    assert r.content_type.startswith("application/vnd.openxmlformats-officedocument")
    wb = openpyxl.load_workbook(io.BytesIO(r.data))
    assert "발송명단" in wb.sheetnames


def test_upload_confirmation_pdf(client_with_sample):
    c, pid = client_with_sample
    pdf_bytes = _make_pdf_bytes("조회처: 고객사001\n잔액: 1,500,000원")
    r = c.post(f"/api/projects/{pid}/confirmations/upload",
               data={"kind": "AR",
                     "pdf": (io.BytesIO(pdf_bytes), "conf.pdf")},
               content_type="multipart/form-data")
    assert r.status_code == 200
    body = r.get_json()
    assert body["matched_party"] == "P1"
    assert body["verdict"] == "MATCH"


def test_upload_without_pdf_returns_400(client_with_sample):
    c, pid = client_with_sample
    r = c.post(f"/api/projects/{pid}/confirmations/upload",
               data={"kind": "AR"},
               content_type="multipart/form-data")
    assert r.status_code == 400
