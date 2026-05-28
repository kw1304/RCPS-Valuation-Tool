import pytest
from datetime import date
from src.application.alternative_uc import AlternativeUC, AltProcResult
from src.domain.entities import (
    Account, Kind, SelectionReason, Verdict, ResponseStatus,
)
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo, ConfirmationRepo, AltProcRepo,
)


@pytest.fixture
def session():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    S = make_session(e)
    s = S()
    yield s
    s.close()


@pytest.fixture
def project_with_no_response(session):
    pid = ProjectRepo(session).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=10_000, tolerable=5_000)
    accs = [
        Account(party_id="P1", name="갑", gl_account="x",
                balance_orig=1000, ccy="KRW", fx_rate=1.0, balance_krw=1000),
        Account(party_id="P2", name="을", gl_account="x",
                balance_orig=2000, ccy="KRW", fx_rate=1.0, balance_krw=2000),
    ]
    AccountRepo(session).bulk_insert(pid, Kind.AR, accs)
    accs_db = AccountRepo(session).list_by_project_kind(pid, Kind.AR)
    SampleRepo(session).persist(pid, Kind.AR, [
        (accs_db[0], SelectionReason.FORCED_RP),
        (accs_db[1], SelectionReason.FORCED_RP),
    ])
    conf = ConfirmationRepo(session)
    conf.upsert(pid, Kind.AR, party_id="P1", expected=1000, confirmed=None,
                verdict=Verdict.NO_RESPONSE, diff_reason=None,
                pdf_path=None, status=ResponseStatus.NO_RESPONSE)
    conf.upsert(pid, Kind.AR, party_id="P2", expected=2000, confirmed=None,
                verdict=Verdict.NO_RESPONSE, diff_reason=None,
                pdf_path=None, status=ResponseStatus.NO_RESPONSE)
    return pid


def test_register_increments_coverage(session, project_with_no_response):
    pid = project_with_no_response
    uc = AlternativeUC(session)
    r = uc.register(pid, Kind.AR, party_id="P1",
                    procedure_type="후속회수", evidence_sum=1000)
    assert r.coverage_pct == pytest.approx(0.333, abs=0.01)
    assert r.verdict == "INSUFFICIENT"


def test_register_accumulated_acceptable(session, project_with_no_response):
    pid = project_with_no_response
    uc = AlternativeUC(session)
    uc.register(pid, Kind.AR, party_id="P1",
                procedure_type="후속회수", evidence_sum=1000)
    r = uc.register(pid, Kind.AR, party_id="P2",
                    procedure_type="송장대조", evidence_sum=2000)
    assert r.coverage_pct >= 0.75
    assert r.verdict == "ACCEPTABLE"


def test_register_updates_existing(session, project_with_no_response):
    pid = project_with_no_response
    uc = AlternativeUC(session)
    uc.register(pid, Kind.AR, party_id="P1",
                procedure_type="후속회수", evidence_sum=500)
    uc.register(pid, Kind.AR, party_id="P1",
                procedure_type="후속회수", evidence_sum=900)
    rows = AltProcRepo(session).list_by_project_kind(pid, Kind.AR)
    assert len(rows) == 1
    assert rows[0]["evidence_sum"] == 900
