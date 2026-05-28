"""E2E — Phase 3 마일스톤: 전 라이프사이클 (ingest → projection)."""
import pytest
import io
from pathlib import Path
from unittest.mock import MagicMock
from api.app import create_app
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base


FIXTURES = Path(__file__).parent / "fixtures"


def _dynamic_pdf(name: str, amount: float) -> bytes:
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
    c.drawString(50, 800, "회신서")
    c.drawString(50, 780, f"조회처: {name}")
    c.drawString(50, 760, f"잔액: {int(amount):,}원")
    c.save()
    return buf.getvalue()


@pytest.fixture(scope="module")
def fixtures_ready():
    for n in ("dummy_ledger", "dummy_fs", "dummy_rp", "dummy_allowance"):
        if not (FIXTURES / f"{n}.xlsx").exists():
            pytest.skip(f"fixture {n}.xlsx missing")


@pytest.fixture
def client(fixtures_ready):
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SF = make_session(engine)
    fx_mock = MagicMock()
    fx_mock.lookup.return_value = 1300.0
    app = create_app(testing=True, session_factory=SF)
    app.config["FX_CLIENT"] = fx_mock
    return app.test_client()


def _file(name):
    return (open(FIXTURES / f"{name}.xlsx", "rb"), f"{name}.xlsx")


def test_e2e_drop_to_projection(client):
    # 1) 프로젝트 + ingest
    r = client.post("/api/projects", json={
        "client": "DUMMY_CLIENT", "period_end": "2025-12-31",
        "base_ccy": "KRW", "materiality": 50_000_000, "tolerable": 25_000_000,
    })
    pid = r.get_json()["id"]
    client.post(f"/api/projects/{pid}/ingest", data={
        "ledger": _file("dummy_ledger"),
        "fs": _file("dummy_fs"),
        "rp": _file("dummy_rp"),
        "allowance": _file("dummy_allowance"),
    }, content_type="multipart/form-data")

    # 2) AR/AP 표본설계
    for kind in ("AR", "AP"):
        client.post(f"/api/projects/{pid}/sampling/design", json={
            "kind": kind, "confidence": 0.95, "expected_ms_pct": 0.0,
            "key_threshold": 5_000_000, "n_strata": 4, "seed": 42,
        })

    # 3) 발송명단 다운로드
    r = client.get(f"/api/projects/{pid}/sendlist")
    assert r.status_code == 200
    assert r.content_type.startswith("application/vnd.openxmlformats")

    # 4) AR 표본 일부에 PDF 회신
    state = client.get(f"/api/projects/{pid}/state").get_json()
    ar_items = state["samples"]["AR"]["items"][:3]
    assert len(ar_items) >= 1
    for i, it in enumerate(ar_items):
        amt = it["balance_krw"] if i != 1 else it["balance_krw"] * 0.9
        pdf_bytes = _dynamic_pdf(it["name"], amt)
        r = client.post(f"/api/projects/{pid}/confirmations/upload",
                        data={"kind": "AR",
                              "pdf": (io.BytesIO(pdf_bytes), f"conf{i}.pdf")},
                        content_type="multipart/form-data")
        assert r.status_code == 200

    # 5) 표본 4번째에 대체적 절차
    if len(state["samples"]["AR"]["items"]) > 3:
        no_resp = state["samples"]["AR"]["items"][3]
        r = client.post(f"/api/projects/{pid}/alternative", json={
            "kind": "AR", "party_id": no_resp["party_id"],
            "procedure_type": "후속회수",
            "evidence_sum": no_resp["balance_krw"],
            "note": "수령증 확인",
        })
        assert r.status_code == 200

    # 6) AR projection
    r = client.post(f"/api/projects/{pid}/projection",
                    json={"kind": "AR", "confidence": 0.95})
    assert r.status_code == 200
    proj = r.get_json()
    assert proj["upper_limit"] >= proj["projected_misstatement"]
    assert proj["verdict"] in ("WITHIN_TOLERABLE", "EXCEED")

    # 7) AP projection
    r = client.post(f"/api/projects/{pid}/projection",
                    json={"kind": "AP", "confidence": 0.95})
    assert r.status_code == 200

    # 8) state 전체 확인
    body = client.get(f"/api/projects/{pid}/state").get_json()
    assert body["confirmations"]["AR"]
    assert body["projection"]["AR"] is not None
    assert body["projection"]["AP"] is not None
