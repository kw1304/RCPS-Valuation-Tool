import pytest
from datetime import date
from src.application.projection_uc import ProjectionUC, ProjectionView
from src.domain.entities import (
    Account, Kind, SelectionReason, Verdict, ResponseStatus,
)
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo, ConfirmationRepo, ProjectionRepo,
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
def project_with_discrepancy(session):
    pid = ProjectRepo(session).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=1_000_000, tolerable=500_000)
    accs = [
        Account(party_id=f"P{i:03d}", name=f"갑{i}", gl_account="x",
                balance_orig=100_000, ccy="KRW", fx_rate=1.0,
                balance_krw=100_000)
        for i in range(100)
    ]
    AccountRepo(session).bulk_insert(pid, Kind.AR, accs)
    accs_db = AccountRepo(session).list_by_project_kind(pid, Kind.AR)
    SampleRepo(session).persist(pid, Kind.AR, [
        (a, SelectionReason.REP) for a in accs_db[:10]
    ])
    conf = ConfirmationRepo(session)
    for i in range(10):
        if i < 2:
            conf.upsert(pid, Kind.AR, party_id=f"P{i:03d}",
                        expected=100_000, confirmed=80_000,
                        verdict=Verdict.DISCREPANCY, diff_reason=None,
                        pdf_path=None, status=ResponseStatus.RECEIVED)
        else:
            conf.upsert(pid, Kind.AR, party_id=f"P{i:03d}",
                        expected=100_000, confirmed=100_000,
                        verdict=Verdict.MATCH, diff_reason=None,
                        pdf_path=None, status=ResponseStatus.RECEIVED)
    return pid


def test_projection_computes(session, project_with_discrepancy):
    pid = project_with_discrepancy
    uc = ProjectionUC(session)
    view = uc.compute(pid, kind=Kind.AR, confidence=0.95)
    assert view.kind == Kind.AR
    assert view.projected_misstatement > 0
    assert view.upper_limit >= view.projected_misstatement
    assert view.verdict in ("WITHIN_TOLERABLE", "EXCEED")


def test_projection_persists(session, project_with_discrepancy):
    pid = project_with_discrepancy
    uc = ProjectionUC(session)
    uc.compute(pid, Kind.AR, confidence=0.95)
    got = ProjectionRepo(session).get_latest(pid, Kind.AR)
    assert got is not None
    assert got["verdict"] in ("WITHIN_TOLERABLE", "EXCEED")


def test_projection_no_discrepancy_returns_basic_only(session):
    pid = ProjectRepo(session).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=1_000_000, tolerable=500_000)
    accs = [Account(party_id=f"P{i}", name=str(i), gl_account="x",
                    balance_orig=10_000, ccy="KRW", fx_rate=1.0,
                    balance_krw=10_000) for i in range(20)]
    AccountRepo(session).bulk_insert(pid, Kind.AR, accs)
    accs_db = AccountRepo(session).list_by_project_kind(pid, Kind.AR)
    SampleRepo(session).persist(pid, Kind.AR,
                                 [(accs_db[0], SelectionReason.REP)])
    conf = ConfirmationRepo(session)
    conf.upsert(pid, Kind.AR, party_id="P0", expected=10_000, confirmed=10_000,
                verdict=Verdict.MATCH, diff_reason=None,
                pdf_path=None, status=ResponseStatus.RECEIVED)
    uc = ProjectionUC(session)
    view = uc.compute(pid, Kind.AR, confidence=0.95)
    assert view.projected_misstatement == 0
    assert view.upper_limit > 0
