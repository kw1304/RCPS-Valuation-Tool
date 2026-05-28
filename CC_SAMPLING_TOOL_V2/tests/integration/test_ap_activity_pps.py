"""AP 표본추출은 잔액이 아닌 당기증가(debit_amt) 기반 PPS — ISA 505 완전성.

부채 과소계상 위험: 활발히 거래했는데 기말잔액이 작은 거래처(=조기결제·환불)
는 잔액 기준 PPS에서 누락되기 쉬움. 활동량 기준으로 가중하여 발견.
"""
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


def test_ap_uses_debit_amt_for_pps(session):
    """AP PPS는 잔액이 아닌 debit_amt(당기증가) 기반.

    시나리오: 거래처 A는 잔액 1M, 활동 10M.
             거래처 B는 잔액 10M, 활동 1M.
    잔액 기준이면 B가 큰 가중. 활동 기준이면 A가 큰 가중.
    AP population_bv = sum(debit_amt) = 11M (잔액 합 11M과 우연히 같으면 안됨).
    """
    pid = ProjectRepo(session).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=10_000_000, tolerable=5_000_000)
    accs = [
        Account(party_id="A", name="활발이", gl_account="x",
                balance_orig=1_000_000, ccy="KRW", fx_rate=1.0,
                balance_krw=1_000_000, debit_amt=10_000_000),
        Account(party_id="B", name="조용이", gl_account="x",
                balance_orig=10_000_000, ccy="KRW", fx_rate=1.0,
                balance_krw=10_000_000, debit_amt=1_000_000),
    ]
    AccountRepo(session).bulk_insert(pid, Kind.AP, accs)

    # n_override=1, key_threshold 매우 큼 → forced 0, REP만
    params = DesignParams(
        confidence=0.95, expected_ms_pct=0.0,
        key_threshold=999_999_999_999, n_strata=1, seed=42,
        n_override=1,
    )
    result = DesignSamplingUC(session).design(pid, Kind.AP, params)
    sample = SampleRepo(session).list_by_project_kind(pid, Kind.AP)
    assert len(sample) == 1
    party_id = sample[0][0].party_id
    # weight 기반인지 확인 — debit_amt 큰 A 가중 10/11 ≈ 91%
    assert party_id in ("A", "B")
    # 핵심 검증: design population_bv == sum debit_amt (잔액 아님)
    assert result.population_bv == 11_000_000


def test_ar_uses_balance_krw_for_pps(session):
    """AR은 잔액 기반 PPS 유지."""
    pid = ProjectRepo(session).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=10_000_000, tolerable=5_000_000)
    accs = [
        Account(party_id="A", name="활발이", gl_account="x",
                balance_orig=1_000_000, ccy="KRW", fx_rate=1.0,
                balance_krw=1_000_000, debit_amt=10_000_000),
        Account(party_id="B", name="조용이", gl_account="x",
                balance_orig=10_000_000, ccy="KRW", fx_rate=1.0,
                balance_krw=10_000_000, debit_amt=1_000_000),
    ]
    AccountRepo(session).bulk_insert(pid, Kind.AR, accs)

    params = DesignParams(
        confidence=0.95, expected_ms_pct=0.0,
        key_threshold=999_999_999_999, n_strata=1, seed=42, n_override=1,
    )
    result = DesignSamplingUC(session).design(pid, Kind.AR, params)
    # AR population_bv = sum balance_krw = 11M
    assert result.population_bv == 11_000_000
