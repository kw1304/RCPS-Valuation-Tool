import pytest
from datetime import date
from src.application.design_sampling_uc import (
    DesignSamplingUC, DesignParams, DesignResult,
)
from src.domain.entities import Account, Kind, SelectionReason
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import ProjectRepo, AccountRepo, SampleRepo


@pytest.fixture
def session():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    S = make_session(e)
    s = S()
    yield s
    s.close()


@pytest.fixture
def project_with_accounts(session):
    pid = ProjectRepo(session).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=10_000_000, tolerable=5_000_000,
    )
    accs = []
    for i in range(200):
        bal = (i + 1) * 10_000
        accs.append(Account(
            party_id=f"P{i:03d}", name=f"갑{i}", gl_account="11200",
            balance_orig=bal, ccy="KRW", fx_rate=1.0, balance_krw=bal,
        ))
    accs.append(Account(
        party_id="RP1", name="자회사", gl_account="11200",
        balance_orig=100, ccy="KRW", fx_rate=1.0, balance_krw=100,
        is_related_party=True,
    ))
    accs.append(Account(
        party_id="BAD1", name="부실거래처", gl_account="11200",
        balance_orig=1000, ccy="KRW", fx_rate=1.0, balance_krw=1000,
        is_bad_debt=True, allowance_amt=1000,
    ))
    AccountRepo(session).bulk_insert(pid, Kind.AR, accs)
    return pid


def test_design_runs_ar(session, project_with_accounts):
    pid = project_with_accounts
    uc = DesignSamplingUC(session)
    params = DesignParams(
        confidence=0.95, expected_ms_pct=0.0,
        key_threshold=1_000_000, n_strata=4, seed=42,
    )
    result = uc.design(project_id=pid, kind=Kind.AR, params=params)

    assert result.kind == Kind.AR
    assert result.used_seed == 42
    assert result.n_total > 0
    assert result.n_forced >= 1
    sample = SampleRepo(session).list_by_project_kind(pid, Kind.AR)
    sample_ids = {a.party_id for a, _ in sample}
    assert "BAD1" not in sample_ids
    assert "RP1" in sample_ids


def test_design_persists_replaceable(session, project_with_accounts):
    pid = project_with_accounts
    uc = DesignSamplingUC(session)
    params = DesignParams(confidence=0.95, expected_ms_pct=0.0,
                          key_threshold=999_999_999, n_strata=4, seed=1)
    r1 = uc.design(pid, Kind.AR, params)
    r2 = uc.design(pid, Kind.AR, params)
    assert r1.n_total == r2.n_total


def test_design_includes_strata_metadata(session, project_with_accounts):
    pid = project_with_accounts
    uc = DesignSamplingUC(session)
    params = DesignParams(confidence=0.95, expected_ms_pct=0.0,
                          key_threshold=999_999_999, n_strata=4, seed=1)
    result = uc.design(pid, Kind.AR, params)
    assert len(result.strata) >= 1
    for s in result.strata:
        assert hasattr(s, "low") and hasattr(s, "high") and hasattr(s, "n_required")
