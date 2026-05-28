import pytest
from datetime import date
from api.app import create_app
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo, ConfirmationRepo,
)
from src.domain.entities import (
    Account, Kind, SelectionReason, Verdict, ResponseStatus,
)


@pytest.fixture
def client_setup():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    SF = make_session(e)
    app = create_app(testing=True, session_factory=SF)
    s = SF()
    pid = ProjectRepo(s).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=10_000, tolerable=5_000)
    acc = Account(party_id="P1", name="갑", gl_account="x",
                  balance_orig=1000, ccy="KRW", fx_rate=1.0, balance_krw=1000)
    AccountRepo(s).bulk_insert(pid, Kind.AR, [acc])
    accs = AccountRepo(s).list_by_project_kind(pid, Kind.AR)
    SampleRepo(s).persist(pid, Kind.AR,
                          [(accs[0], SelectionReason.FORCED_RP)])
    ConfirmationRepo(s).upsert(
        pid, Kind.AR, party_id="P1", expected=1000, confirmed=None,
        verdict=Verdict.NO_RESPONSE, diff_reason=None,
        pdf_path=None, status=ResponseStatus.NO_RESPONSE)
    s.close()
    return app.test_client(), pid


def test_register_alternative(client_setup):
    c, pid = client_setup
    r = c.post(f"/api/projects/{pid}/alternative", json={
        "kind": "AR", "party_id": "P1",
        "procedure_type": "후속회수", "evidence_sum": 1000,
        "note": "회수증빙 확인",
    })
    assert r.status_code == 200
    body = r.get_json()
    assert body["coverage_pct"] >= 0.75


def test_register_invalid_kind(client_setup):
    c, pid = client_setup
    r = c.post(f"/api/projects/{pid}/alternative", json={
        "kind": "INVALID", "party_id": "P1",
        "procedure_type": "X", "evidence_sum": 100,
    })
    assert r.status_code == 400
