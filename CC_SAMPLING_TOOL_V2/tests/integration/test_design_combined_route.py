import pytest
import io
import openpyxl
from datetime import date
from api.app import create_app
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import ProjectRepo, AccountRepo
from src.domain.entities import Account, Kind


@pytest.fixture
def client_with_pop():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    SF = make_session(e)
    app = create_app(testing=True, session_factory=SF)
    s = SF()
    pid = ProjectRepo(s).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=10_000_000, tolerable=5_000_000)
    # AR 잔액 800만, AP 잔액 200만 → 4:1 비율
    ar = [Account(party_id=f"AR{i}", name=f"갑{i}", gl_account="x",
                  balance_orig=100_000, ccy="KRW", fx_rate=1.0,
                  balance_krw=100_000)
          for i in range(80)]
    # AP 설계는 당기증가(debit_amt) 기반 PPS이므로 debit_amt도 설정
    ap = [Account(party_id=f"AP{i}", name=f"을{i}", gl_account="x",
                  balance_orig=50_000, ccy="KRW", fx_rate=1.0,
                  balance_krw=50_000, debit_amt=50_000)
          for i in range(40)]
    AccountRepo(s).bulk_insert(pid, Kind.AR, ar)
    AccountRepo(s).bulk_insert(pid, Kind.AP, ap)
    s.close()
    return app.test_client(), pid


def test_combined_25_splits_by_bv(client_with_pop):
    c, pid = client_with_pop
    r = c.post(f"/api/projects/{pid}/sampling/design_combined", json={
        "n_total": 25, "confidence": 0.95, "expected_ms_pct": 0.0,
        "key_threshold": 999_999_999, "n_strata": 1, "seed": 42,
    })
    assert r.status_code == 200
    body = r.get_json()
    # BV 800만 vs 200만 = 4:1 → AR ~20, AP ~5
    assert body["allocation"]["AR"] + body["allocation"]["AP"] == 25
    assert body["allocation"]["AR"] >= body["allocation"]["AP"]
    # 합계 (RP/KEY 없으므로) 25에 가까움
    assert body["n_total_actual"] == 25


def test_combined_requires_n_total(client_with_pop):
    c, pid = client_with_pop
    r = c.post(f"/api/projects/{pid}/sampling/design_combined", json={})
    assert r.status_code == 400


def test_combined_zero_population(client_with_pop):
    """ingest 없는 새 프로젝트 — BV 0."""
    c, pid_existing = client_with_pop
    r = c.post("/api/projects", json={
        "client": "Y", "period_end": "2025-12-31",
        "base_ccy": "KRW", "materiality": 1, "tolerable": 1,
    })
    new_pid = r.get_json()["id"]
    r = c.post(f"/api/projects/{new_pid}/sampling/design_combined", json={
        "n_total": 25,
    })
    assert r.status_code == 400
