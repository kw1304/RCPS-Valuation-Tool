import pytest
from datetime import date
from src.application.design_sampling_uc import DesignSamplingUC, DesignParams
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
def project_with_rps(session):
    pid = ProjectRepo(session).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=10_000_000, tolerable=5_000_000)
    accs = []
    # 5 RP
    for i in range(5):
        accs.append(Account(party_id=f"RP{i}", name=f"특관자{i}",
                            gl_account="11200",
                            balance_orig=100_000, ccy="KRW",
                            fx_rate=1.0, balance_krw=100_000,
                            is_related_party=True))
    # 100 일반
    for i in range(100):
        accs.append(Account(party_id=f"P{i:03d}", name=f"갑{i}",
                            gl_account="11200",
                            balance_orig=10_000 * (i + 1),
                            ccy="KRW", fx_rate=1.0,
                            balance_krw=10_000 * (i + 1)))
    AccountRepo(session).bulk_insert(pid, Kind.AR, accs)
    return pid


def test_n_override_25_includes_rps(session, project_with_rps):
    pid = project_with_rps
    params = DesignParams(
        confidence=0.95, expected_ms_pct=0.0,
        key_threshold=999_999_999_999,
        n_strata=4, seed=42, n_override=25,
    )
    result = DesignSamplingUC(session).design(pid, Kind.AR, params)
    # 표본 정확히 25건
    assert result.n_total == 25
    # 5 RP 모두 포함
    assert result.n_forced == 5
    # 대표 = 25 - 5 = 20
    assert result.n_representative == 20

    sample = SampleRepo(session).list_by_project_kind(pid, Kind.AR)
    rp_count = sum(1 for a, _ in sample if a.is_related_party)
    assert rp_count == 5


def test_n_override_below_forced_count(session, project_with_rps):
    """n_override가 forced(5)보다 작으면 forced 보장 (n_total = forced)."""
    pid = project_with_rps
    params = DesignParams(
        confidence=0.95, expected_ms_pct=0.0,
        key_threshold=999_999_999_999,
        n_strata=4, seed=42, n_override=3,
    )
    result = DesignSamplingUC(session).design(pid, Kind.AR, params)
    # forced 5 >= override 3 → forced만 (5건)
    assert result.n_total == 5
    assert result.n_forced == 5


def test_n_override_none_auto_size(session, project_with_rps):
    """n_override=None이면 sample_size_mus 자동산정."""
    pid = project_with_rps
    params = DesignParams(
        confidence=0.95, expected_ms_pct=0.0,
        key_threshold=999_999_999_999,
        n_strata=4, seed=42,  # n_override 미지정
    )
    result = DesignSamplingUC(session).design(pid, Kind.AR, params)
    # 자동산정 — 25과 다를 가능성 매우 높음
    assert result.n_total >= 5  # 최소 RP 5
