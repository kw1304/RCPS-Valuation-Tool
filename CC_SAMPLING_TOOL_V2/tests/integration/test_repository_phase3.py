import pytest
from datetime import date, datetime
from src.domain.entities import (
    Account, Kind, SelectionReason, ResponseStatus, Verdict,
)
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo,
    ConfirmationRepo, AltProcRepo, ProjectionRepo,
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
def project_with_sample(session):
    pid = ProjectRepo(session).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=1_000_000, tolerable=500_000)
    acc = Account(party_id="P1", name="갑", gl_account="11200",
                  balance_orig=1000, ccy="KRW", fx_rate=1.0, balance_krw=1000)
    AccountRepo(session).bulk_insert(pid, Kind.AR, [acc])
    accs = AccountRepo(session).list_by_project_kind(pid, Kind.AR)
    SampleRepo(session).persist(
        pid, Kind.AR, [(accs[0], SelectionReason.FORCED_RP)])
    return pid


def test_confirmation_upsert(session, project_with_sample):
    pid = project_with_sample
    repo = ConfirmationRepo(session)
    repo.upsert(pid, Kind.AR, party_id="P1",
                expected=1000, confirmed=999,
                verdict=Verdict.MATCH, diff_reason=None,
                pdf_path="/tmp/conf.pdf",
                status=ResponseStatus.RECEIVED)
    rows = repo.list_by_project_kind(pid, Kind.AR)
    assert len(rows) == 1
    assert rows[0].verdict == Verdict.MATCH
    assert rows[0].confirmed == 999


def test_confirmation_upsert_replaces(session, project_with_sample):
    pid = project_with_sample
    repo = ConfirmationRepo(session)
    repo.upsert(pid, Kind.AR, party_id="P1",
                expected=1000, confirmed=None,
                verdict=Verdict.NO_RESPONSE, diff_reason=None,
                pdf_path=None, status=ResponseStatus.PENDING)
    repo.upsert(pid, Kind.AR, party_id="P1",
                expected=1000, confirmed=950,
                verdict=Verdict.DISCREPANCY, diff_reason=None,
                pdf_path="/tmp/x.pdf", status=ResponseStatus.RECEIVED)
    rows = repo.list_by_project_kind(pid, Kind.AR)
    assert len(rows) == 1
    assert rows[0].confirmed == 950


def test_altproc_persist_and_list(session, project_with_sample):
    pid = project_with_sample
    repo = AltProcRepo(session)
    repo.upsert(pid, Kind.AR, party_id="P1",
                procedure_type="후속회수",
                evidence_sum=500, coverage_pct=0.5,
                note="회수증빙 확인")
    rows = repo.list_by_project_kind(pid, Kind.AR)
    assert len(rows) == 1
    assert rows[0]["procedure_type"] == "후속회수"
    assert rows[0]["evidence_sum"] == 500


def test_projection_persist_and_get(session, project_with_sample):
    pid = project_with_sample
    repo = ProjectionRepo(session)
    repo.upsert(pid, Kind.AR, confidence=0.95,
                sampling_interval=10_000, tolerable=500_000,
                projected_misstatement=1000,
                basic_precision=30_000,
                incremental_allowance=500,
                upper_limit=31_500,
                verdict="WITHIN_TOLERABLE",
                strata_snapshot=[{"low": 0, "high": 1000, "n_required": 5}])
    got = repo.get_latest(pid, Kind.AR)
    assert got is not None
    assert got["upper_limit"] == 31_500
    assert got["strata_snapshot"][0]["high"] == 1000


def test_projection_upsert_replaces(session, project_with_sample):
    pid = project_with_sample
    repo = ProjectionRepo(session)
    repo.upsert(pid, Kind.AR, confidence=0.95,
                sampling_interval=10_000, tolerable=500_000,
                projected_misstatement=1000, basic_precision=30_000,
                incremental_allowance=500, upper_limit=31_500,
                verdict="WITHIN_TOLERABLE", strata_snapshot=[])
    repo.upsert(pid, Kind.AR, confidence=0.95,
                sampling_interval=10_000, tolerable=500_000,
                projected_misstatement=5000, basic_precision=30_000,
                incremental_allowance=2000, upper_limit=37_000,
                verdict="WITHIN_TOLERABLE", strata_snapshot=[])
    got = repo.get_latest(pid, Kind.AR)
    assert got["projected_misstatement"] == 5000
