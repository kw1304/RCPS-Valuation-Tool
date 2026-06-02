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


def test_debt_ratio_na_when_capital_impaired():
    # 완전자본잠식(자본<=0) → 부채/자본 분모 비정상 → na (green 오인 금지)
    prev = _mk(2024)
    curr = _mk(2025, total_liabilities=300, total_equity=-50)
    sigs = evaluate_axes([prev, curr], _pm(10_000_000))
    dr = next(s for s in sigs if s.code == "debt_ratio")
    assert dr.level == "na"
    assert dr.value is None
    # 자본잠식 신호 자체는 적신호로 별도 표시
    ci = next(s for s in sigs if s.code == "capital_impairment")
    assert ci.level == "red"


# ── FIX 1: 판관비율(SG&A ratio) 신호 존재 ──

def test_sga_ratio_signal_present():
    # 판관비율 신호가 축1에 존재하는지 (지표 누락 회귀 방지)
    prev = _mk(2024, revenue=1_000_000_000, cogs=600_000_000, operating_income=300_000_000)
    curr = _mk(2025, revenue=1_000_000_000, cogs=600_000_000, operating_income=300_000_000)
    sigs = evaluate_axes([prev, curr], _pm(10_000_000))
    sga = next((s for s in sigs if s.code == "sga_ratio"), None)
    assert sga is not None
    assert sga.label == "판관비율"


def test_sga_ratio_yellow_on_2pp_jump():
    # 전기 판관비율 10% → 당기 13% (Δ+3%p, 황 임계 ±2 초과), 금액게이트 통과
    # 판관비 = 매출총이익 − 영업이익
    prev = _mk(2024, revenue=1_000_000_000, cogs=600_000_000, operating_income=300_000_000)  # GP4억, SGA1억=10%
    curr = _mk(2025, revenue=1_000_000_000, cogs=600_000_000, operating_income=270_000_000)  # SGA1.3억=13%
    sigs = evaluate_axes([prev, curr], _pm(10_000_000))
    sga = next(s for s in sigs if s.code == "sga_ratio")
    assert sga.level == "yellow"


# ── FIX 2: 영업CF 인접연도 판정 (중간 결측 오탐 방지) ──

def test_operating_cf_gap_year_not_consecutive_red():
    # [-100, None, -50]: 중간 결측이라 연속 판정 불가 → 최신만 음수 yellow (red 아님)
    ys = [
        _mk(2023, operating_cf=-100),
        _mk(2024, operating_cf=None),
        _mk(2025, operating_cf=-50),
    ]
    sigs = evaluate_axes(ys, _pm(10_000_000))
    ocf = next(s for s in sigs if s.code == "operating_cf")
    assert ocf.level == "yellow"


def test_operating_cf_adjacent_negative_red():
    # 인접 2년 연속 음수 → red
    ys = [
        _mk(2023, operating_cf=50),
        _mk(2024, operating_cf=-80),
        _mk(2025, operating_cf=-50),
    ]
    sigs = evaluate_axes(ys, _pm(10_000_000))
    ocf = next(s for s in sigs if s.code == "operating_cf")
    assert ocf.level == "red"


def test_operating_cf_latest_missing_na():
    ys = [
        _mk(2024, operating_cf=-80),
        _mk(2025, operating_cf=None),
    ]
    sigs = evaluate_axes(ys, _pm(10_000_000))
    ocf = next(s for s in sigs if s.code == "operating_cf")
    assert ocf.level == "na"


# ── FIX 3: 회전율 Δ잔액 PM게이트 ──

def test_turnover_fires_when_delta_balance_exceeds_pm():
    # 매출채권 잔액 전기 1억 → 당기 5억 (Δ4억 > PM 1천만), 회전율 급락 → 신호 발화
    prev = _mk(2024, revenue=2_000_000_000, trade_receivables=100_000_000)  # 회전율 20
    curr = _mk(2025, revenue=2_000_000_000, trade_receivables=500_000_000)  # 회전율 4 (-80%)
    sigs = evaluate_axes([prev, curr], _pm(10_000_000))
    ar = next(s for s in sigs if s.code == "ar_turnover")
    assert ar.level == "red"  # -80% 하락 (적 임계 -35 초과)


def test_turnover_observation_when_delta_balance_below_pm():
    # 회전율 급락이지만 Δ잔액이 PM 미만 → green + 관찰
    prev = _mk(2024, revenue=20_000_000, trade_receivables=1_000_000)   # 회전율 20
    curr = _mk(2025, revenue=20_000_000, trade_receivables=5_000_000)   # 회전율 4 (-80%), Δ잔액 4백만 < PM 1천만
    sigs = evaluate_axes([prev, curr], _pm(10_000_000))
    ar = next(s for s in sigs if s.code == "ar_turnover")
    assert ar.level == "green"
    assert "관찰" in ar.note


# ── FIX 4: 유효세율 음수 과탐 좁힘 ──

def test_tax_negative_in_loss_company_not_red():
    # 적자기업(세전손실) 법인세수익(-) → red 아님 (green)
    prev = _mk(2024)
    curr = _mk(2025, pretax_income=-50_000_000, tax_expense=-10_000_000)
    sigs = evaluate_axes([prev, curr], _pm(10_000_000))
    tax = next(s for s in sigs if s.code == "effective_tax")
    assert tax.level == "green"


def test_tax_negative_with_positive_pretax_red():
    # 세전이익(+)인데 법인세(-) → 비정상 red
    prev = _mk(2024)
    curr = _mk(2025, pretax_income=100_000_000, tax_expense=-5_000_000)
    sigs = evaluate_axes([prev, curr], _pm(10_000_000))
    tax = next(s for s in sigs if s.code == "effective_tax")
    assert tax.level == "red"


# ── FIX 5: 자본잠식 경계 (eq==0도 red) ──

def test_capital_impairment_zero_equity_red():
    prev = _mk(2024, total_equity=100_000_000)
    curr = _mk(2025, total_equity=0, total_liabilities=300_000_000)
    sigs = evaluate_axes([prev, curr], _pm(10_000_000))
    cap = next(s for s in sigs if s.code == "capital_impairment")
    assert cap.level == "red"


# ── FIX 6: None 전파 → na 신호보류 ──

def test_revenue_change_na_when_revenue_missing():
    prev = _mk(2024, revenue=None)
    curr = _mk(2025, revenue=None)
    sigs = evaluate_axes([prev, curr], _pm(10_000_000))
    rev = next(s for s in sigs if s.code == "revenue_change")
    assert rev.level == "na"
    assert rev.note == "데이터 없음 — 신호 보류"


def test_na_does_not_affect_grade():
    # na 신호는 등급 카운트에 영향 없음 (모두 결측 → green/na 혼재여도 red/yellow 0)
    from risk.domain.risk_grade import overall_grade
    prev = _mk(2024)
    curr = _mk(2025)  # 전 항목 결측
    sigs = evaluate_axes([prev, curr], _pm(10_000_000))
    grade = overall_grade(sigs)
    assert grade.red == 0
    assert grade.yellow == 0
    assert grade.grade == "낮음"
