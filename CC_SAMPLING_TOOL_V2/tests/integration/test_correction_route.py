import pytest
from datetime import date
from api.app import create_app
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo, ConfirmationRepo,
)
from src.domain.entities import Account, Kind, SelectionReason


@pytest.fixture
def setup():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    SF = make_session(e)
    app = create_app(testing=True, session_factory=SF)
    s = SF()
    pid = ProjectRepo(s).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=10_000, tolerable=5_000)
    acc = Account(party_id="P1", name="갑", gl_account="x",
                  balance_orig=1_000_000, ccy="KRW", fx_rate=1.0,
                  balance_krw=1_000_000)
    AccountRepo(s).bulk_insert(pid, Kind.AR, [acc])
    accs = AccountRepo(s).list_by_project_kind(pid, Kind.AR)
    SampleRepo(s).persist(pid, Kind.AR,
                          [(accs[0], SelectionReason.FORCED_RP)])
    s.close()
    return app.test_client(), pid


def test_correct_match(setup):
    c, pid = setup
    r = c.post(f"/api/projects/{pid}/confirmations/correct", json={
        "kind": "AR", "party_id": "P1", "confirmed": 1_000_000,
    })
    assert r.status_code == 200
    assert r.get_json()["verdict"] == "MATCH"


def test_correct_no_response(setup):
    c, pid = setup
    r = c.post(f"/api/projects/{pid}/confirmations/correct", json={
        "kind": "AR", "party_id": "P1", "confirmed": None,
    })
    assert r.status_code == 200
    assert r.get_json()["verdict"] == "NO_RESPONSE"


def test_correct_unknown_party_404(setup):
    c, pid = setup
    r = c.post(f"/api/projects/{pid}/confirmations/correct", json={
        "kind": "AR", "party_id": "GHOST", "confirmed": 100,
    })
    assert r.status_code == 404
