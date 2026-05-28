import pytest
from datetime import date
from src.domain.entities import (
    Project, Account, Sample, Confirmation,
    AlternativeProcedure, ProjectionResult, Strata,
    Kind, SelectionReason, Verdict, ResponseStatus,
)


def test_project_defaults():
    p = Project(
        client="ACME", period_end=date(2025, 12, 31),
        base_ccy="KRW", materiality=500_000_000, tolerable=250_000_000,
    )
    assert p.materiality == 500_000_000
    assert p.tolerable == 250_000_000


def test_account_balance_krw_default():
    a = Account(party_id="P1", name="갑", gl_account="11200",
                balance_orig=1000, ccy="USD", fx_rate=1300,
                balance_krw=1_300_000)
    assert a.balance_krw == 1_300_000
    assert a.is_related_party is False
    assert a.is_bad_debt is False
    assert a.allowance_amt == 0


def test_kind_enum_values():
    assert Kind.AR.value == "AR"
    assert Kind.AP.value == "AP"


def test_selection_reason_values_distinct():
    # 5개 사유 모두 distinct (값 충돌 없음)
    order = [
        SelectionReason.EXCLUDED_BAD,
        SelectionReason.EXCLUDED_ZERO,
        SelectionReason.FORCED_RP,
        SelectionReason.FORCED_KEY,
        SelectionReason.REP,
    ]
    assert len({r.value for r in order}) == 5


def test_sample_holds_accounts():
    a1 = Account(party_id="P1", name="갑", gl_account="11200",
                 balance_orig=100, ccy="KRW", fx_rate=1, balance_krw=100)
    s = Sample(kind=Kind.AR, accounts=[(a1, SelectionReason.FORCED_RP)])
    assert len(s.accounts) == 1
    assert s.accounts[0][1] == SelectionReason.FORCED_RP


def test_strata_range():
    st = Strata(low=0, high=1_000_000, n_required=10)
    assert st.contains(500_000) is True
    assert st.contains(1_000_001) is False


def test_response_status_values():
    from src.domain.entities import ResponseStatus
    assert ResponseStatus.PENDING.value == "PENDING"
    assert ResponseStatus.RECEIVED.value == "RECEIVED"
    assert ResponseStatus.NO_RESPONSE.value == "NO_RESPONSE"
    assert ResponseStatus.EXTRACT_FAILED.value == "EXTRACT_FAILED"
    assert len({s.value for s in ResponseStatus}) == 4


def test_project_optional_defaults():
    from datetime import datetime
    p = Project(client="X", period_end=date(2025, 12, 31),
                base_ccy="KRW", materiality=1, tolerable=1)
    assert p.id is None
    assert isinstance(p.created_at, datetime)


def test_account_allowance_ratio_uses_krw():
    # USD 100, rate 1300, KRW 130_000; allowance 65_000 KRW = 50% of KRW value
    a = Account(party_id="p", name="p", gl_account="x",
                balance_orig=100, ccy="USD", fx_rate=1300,
                balance_krw=130_000, allowance_amt=65_000)
    assert a.allowance_ratio == pytest.approx(0.5, abs=1e-9)


def test_account_allowance_ratio_zero_krw():
    a = Account(party_id="p", name="p", gl_account="x",
                balance_orig=100, ccy="USD", fx_rate=0,
                balance_krw=0, allowance_amt=10)
    # 0 잔액(KRW) → ratio 0
    assert a.allowance_ratio == 0.0
