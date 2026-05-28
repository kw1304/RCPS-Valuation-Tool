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
def client_with_discrepancy():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    SF = make_session(e)
    app = create_app(testing=True, session_factory=SF)
    s = SF()
    pid = ProjectRepo(s).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=1_000_000, tolerable=500_000)
    accs = [
        Account(party_id=f"P{i:03d}", name=f"갑{i}", gl_account="x",
                balance_orig=100_000, ccy="KRW", fx_rate=1.0,
                balance_krw=100_000)
        for i in range(100)
    ]
    AccountRepo(s).bulk_insert(pid, Kind.AR, accs)
    accs_db = AccountRepo(s).list_by_project_kind(pid, Kind.AR)
    SampleRepo(s).persist(pid, Kind.AR,
                          [(a, SelectionReason.REP) for a in accs_db[:10]])
    conf = ConfirmationRepo(s)
    conf.upsert(pid, Kind.AR, party_id="P000", expected=100_000,
                confirmed=80_000, verdict=Verdict.DISCREPANCY,
                diff_reason=None, pdf_path=None,
                status=ResponseStatus.RECEIVED)
    s.close()
    return app.test_client(), pid


def test_projection_compute(client_with_discrepancy):
    c, pid = client_with_discrepancy
    r = c.post(f"/api/projects/{pid}/projection", json={
        "kind": "AR", "confidence": 0.95,
    })
    assert r.status_code == 200
    body = r.get_json()
    assert body["projected_misstatement"] > 0
    assert body["upper_limit"] >= body["projected_misstatement"]
    assert body["verdict"] in ("WITHIN_TOLERABLE", "EXCEED")


def test_state_exposes_confirmations_and_projection(client_with_discrepancy):
    c, pid = client_with_discrepancy
    c.post(f"/api/projects/{pid}/projection",
           json={"kind": "AR", "confidence": 0.95})
    r = c.get(f"/api/projects/{pid}/state")
    body = r.get_json()
    assert "confirmations" in body
    assert "alternatives" in body
    assert "projection" in body
    assert body["projection"]["AR"] is not None
    assert body["projection"]["AR"]["upper_limit"] > 0
    ar_confs = body["confirmations"]["AR"]
    assert any(c["verdict"] == "DISCREPANCY" for c in ar_confs)
