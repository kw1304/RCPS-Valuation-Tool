import pytest
from datetime import date
from src.application.design_sampling_uc import DesignSamplingUC, DesignParams
from src.application.projection_uc import ProjectionUC
from src.domain.entities import Account, Kind, SelectionReason, Verdict, ResponseStatus
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo, SampleDesignRepo,
    ProjectionRepo, ConfirmationRepo,
)


@pytest.fixture
def session():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    S = make_session(e)
    s = S()
    yield s
    s.close()


def test_design_persists_strata_snapshot(session):
    pid = ProjectRepo(session).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=10_000_000, tolerable=5_000_000)
    accs = [
        Account(party_id=f"P{i:03d}", name=f"갑{i}", gl_account="x",
                balance_orig=(i + 1) * 10_000, ccy="KRW", fx_rate=1.0,
                balance_krw=(i + 1) * 10_000)
        for i in range(100)
    ]
    AccountRepo(session).bulk_insert(pid, Kind.AR, accs)
    DesignSamplingUC(session).design(pid, Kind.AR, DesignParams(
        confidence=0.95, expected_ms_pct=0.0,
        key_threshold=1_000_000, n_strata=4, seed=42))

    design = SampleDesignRepo(session).get_latest(pid, Kind.AR)
    assert design is not None
    assert design["seed"] == 42
    assert design["confidence"] == 0.95
    assert len(design["strata_snapshot"]) >= 1


def test_projection_uses_design_strata(session):
    pid = ProjectRepo(session).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=10_000_000, tolerable=5_000_000)
    accs = [
        Account(party_id=f"P{i:03d}", name=f"갑{i}", gl_account="x",
                balance_orig=100_000, ccy="KRW", fx_rate=1.0,
                balance_krw=100_000)
        for i in range(100)
    ]
    AccountRepo(session).bulk_insert(pid, Kind.AR, accs)
    DesignSamplingUC(session).design(pid, Kind.AR, DesignParams(
        confidence=0.95, expected_ms_pct=0.0,
        key_threshold=999_999_999, n_strata=4, seed=1))
    selected = SampleRepo(session).list_by_project_kind(pid, Kind.AR)
    assert len(selected) >= 1
    first_party = selected[0][0].party_id
    ConfirmationRepo(session).upsert(
        pid, Kind.AR, party_id=first_party, expected=100_000, confirmed=80_000,
        verdict=Verdict.DISCREPANCY, diff_reason=None,
        pdf_path=None, status=ResponseStatus.RECEIVED)
    ProjectionUC(session).compute(pid, Kind.AR, confidence=0.95)
    snap = ProjectionRepo(session).get_latest(pid, Kind.AR)["strata_snapshot"]
    assert len(snap) >= 1
