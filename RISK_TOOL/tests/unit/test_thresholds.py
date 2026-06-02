import pytest
from risk.domain.financial import FinancialYear
from risk.domain.materiality import Materiality
from risk.domain.thresholds import evaluate_axes


def _mk(year, **kw):
    return FinancialYear(year=year, **kw)


def _pm(value):
    return Materiality(materiality=value / 0.75, pm=value, benchmark="revenue")


def test_revenue_change_red_with_pm_gate():
    # 매출 +40% (적 임계 30 초과), 변동금액 4억 > PM 1천만 → red
    prev = _mk(2024, revenue=1_000_000_000)
    curr = _mk(2025, revenue=1_400_000_000)
    sigs = evaluate_axes([prev, curr], _pm(10_000_000))
    rev = next(s for s in sigs if s.code == "revenue_change")
    assert rev.level == "red"


def test_revenue_change_observation_when_below_pm():
    # 매출 +40%지만 변동금액 4백만 < PM 1천만 → 신호 아님(observation, green)
    prev = _mk(2024, revenue=10_000_000)
    curr = _mk(2025, revenue=14_000_000)
    sigs = evaluate_axes([prev, curr], _pm(10_000_000))
    rev = next(s for s in sigs if s.code == "revenue_change")
    assert rev.level == "green"
    assert "관찰" in rev.note


def test_capital_impairment_red():
    # 자본총계 음수 → 완전자본잠식 red
    prev = _mk(2024, total_equity=100_000_000)
    curr = _mk(2025, total_equity=-50_000_000, total_liabilities=300_000_000)
    sigs = evaluate_axes([prev, curr], _pm(10_000_000))
    cap = next(s for s in sigs if s.code == "capital_impairment")
    assert cap.level == "red"


def test_accrual_red_profit_but_negative_ocf():
    prev = _mk(2024)
    curr = _mk(2025, net_income=500_000_000, operating_cf=-100_000_000)
    sigs = evaluate_axes([prev, curr], _pm(10_000_000))
    acc = next(s for s in sigs if s.code == "accrual_quality")
    assert acc.level == "red"


def test_interest_coverage_zombie_red():
    # 3년 연속 이자보상배율<1 → red
    ys = [
        _mk(2023, operating_income=50, finance_costs=100),
        _mk(2024, operating_income=40, finance_costs=100),
        _mk(2025, operating_income=30, finance_costs=100),
    ]
    sigs = evaluate_axes(ys, _pm(10_000_000))
    ic = next(s for s in sigs if s.code == "interest_coverage")
    assert ic.level == "red"


def test_debt_ratio_yellow():
    prev = _mk(2024)
    curr = _mk(2025, total_liabilities=250, total_equity=100)  # 250%
    sigs = evaluate_axes([prev, curr], _pm(10_000_000))
    dr = next(s for s in sigs if s.code == "debt_ratio")
    assert dr.level == "yellow"
