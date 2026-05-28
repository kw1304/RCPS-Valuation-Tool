"""test_under_statement_flag.py — suspect_under_statement 플래그 검증

ISA 505 / ISA 530 완전성 검토:
  채무 under-statement 의심 거래처 = 당기 증가 크고(매입 활발) 기말 잔액 소(지급 완료).
  이 거래처는 일부러 채무를 과소계상했을 가능성이 있어 별도 강조 표시.

suspect_flag 조건 (classify_parties 파라미터 기본값 기준):
  activity > PM × 1.5  AND  ending < PM × 0.1

검증 항목:
  1. 두 조건 모두 충족 → True
  2. activity 조건만 충족 → False
  3. ending 조건만 충족 → False
  4. 둘 다 불충족 → False
  5. kind="receivable" 이면 항상 False
  6. performance_materiality=0 이면 항상 False (비교 불가)
  7. 경계값: activity == PM×1.5 → False (strictly greater 조건)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest

from src.domain.population import LedgerRow, aggregate_by_party, classify_parties


PM = 200_000_000  # 2억


def _rows_with_increase(name, increase, ending) -> list[LedgerRow]:
    """increase 컬럼 명시 방식으로 LedgerRow 생성."""
    return [LedgerRow(
        code="X001", name=name, account_code="201", account_name="외상매입금",
        currency="KRW",
        beginning=0, change=ending, ending=ending,
        increase=increase, decrease=0.0,
    )]


def _classify(rows, pm=PM):
    parties = aggregate_by_party(rows, kind="payable")
    return classify_parties(
        parties=parties,
        key_item_threshold=pm * 100,  # 아무도 Key item 아니도록 높게 설정
        related_party_names=set(),
        kind="payable",
        performance_materiality=pm,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. 두 조건 모두 충족
# ─────────────────────────────────────────────────────────────────────────────

def test_suspect_flag_both_conditions_met():
    """activity > PM×1.5(3억) AND ending < PM×0.1(2천만) → suspect_flag = True."""
    # activity = 4억(> 3억), ending = 1천만(< 2천만)
    rows = _rows_with_increase("의심거래처", increase=400_000_000, ending=10_000_000)
    d = _classify(rows)[0]

    assert d.suspect_flag is True, (
        f"activity={d.activity:,.0f}, ending={d.ending_balance:,.0f}, PM={PM:,.0f}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. activity 조건만 충족 (ending은 큼)
# ─────────────────────────────────────────────────────────────────────────────

def test_suspect_flag_only_activity():
    """activity > PM×1.5 이지만 ending ≥ PM×0.1 → False."""
    # activity = 4억(> 3억), ending = 5천만(≥ 2천만)
    rows = _rows_with_increase("보통거래처", increase=400_000_000, ending=50_000_000)
    d = _classify(rows)[0]
    assert d.suspect_flag is False


# ─────────────────────────────────────────────────────────────────────────────
# 3. ending 조건만 충족 (activity는 작음)
# ─────────────────────────────────────────────────────────────────────────────

def test_suspect_flag_only_ending():
    """activity ≤ PM×1.5 이고 ending < PM×0.1 → False."""
    # activity = 2억(≤ 3억), ending = 1천만(< 2천만)
    rows = _rows_with_increase("소형거래처", increase=200_000_000, ending=10_000_000)
    d = _classify(rows)[0]
    assert d.suspect_flag is False


# ─────────────────────────────────────────────────────────────────────────────
# 4. 둘 다 불충족
# ─────────────────────────────────────────────────────────────────────────────

def test_suspect_flag_neither():
    """activity ≤ PM×1.5 AND ending ≥ PM×0.1 → False."""
    rows = _rows_with_increase("일반거래처", increase=100_000_000, ending=50_000_000)
    d = _classify(rows)[0]
    assert d.suspect_flag is False


# ─────────────────────────────────────────────────────────────────────────────
# 5. kind=receivable 이면 항상 False
# ─────────────────────────────────────────────────────────────────────────────

def test_suspect_flag_receivable_always_false():
    """채권은 실재성(over-statement) 검토 — suspect_flag 항상 False."""
    rows = [LedgerRow(
        code="R001", name="채권거래처", account_code="101", account_name="외상매출금",
        currency="KRW", beginning=0, change=400_000_000, ending=400_000_000,
        increase=400_000_000, decrease=0.0,
    )]
    parties = aggregate_by_party(rows, kind="receivable")
    decisions = classify_parties(
        parties=parties,
        key_item_threshold=PM * 100,
        related_party_names=set(),
        kind="receivable",
        performance_materiality=PM,
    )
    assert decisions[0].suspect_flag is False


# ─────────────────────────────────────────────────────────────────────────────
# 6. performance_materiality=0 이면 항상 False
# ─────────────────────────────────────────────────────────────────────────────

def test_suspect_flag_no_pm():
    """performance_materiality=0 → 조건 평가 불가 → False."""
    rows = _rows_with_increase("의심거래처", increase=400_000_000, ending=10_000_000)
    parties = aggregate_by_party(rows, kind="payable")
    decisions = classify_parties(
        parties=parties,
        key_item_threshold=1_000_000_000,
        related_party_names=set(),
        kind="payable",
        performance_materiality=0,  # PM 미제공
    )
    assert decisions[0].suspect_flag is False


# ─────────────────────────────────────────────────────────────────────────────
# 7. 경계값 — activity == PM×1.5 → False (strictly >)
# ─────────────────────────────────────────────────────────────────────────────

def test_suspect_flag_boundary_activity_equal():
    """activity == PM×1.5 (경계값) → False (strictly greater 조건)."""
    # activity = PM×1.5 = 3억 정확히
    rows = _rows_with_increase("경계거래처", increase=300_000_000, ending=10_000_000)
    d = _classify(rows)[0]
    assert d.suspect_flag is False


# ─────────────────────────────────────────────────────────────────────────────
# 8. 다중 계정과목 통합 시 suspect_flag — by_account_activity 합산 검증
# ─────────────────────────────────────────────────────────────────────────────

def test_suspect_flag_multi_account_combined():
    """여러 계정과목 합산 activity가 임계값 초과 시 suspect_flag = True."""
    rows = [
        LedgerRow("X001", "복합거래처", "201", "외상매입금", "KRW",
                  0, 150_000_000, 5_000_000, 200_000_000, 0.0),
        LedgerRow("X001", "복합거래처", "202", "미지급금", "KRW",
                  0, 150_000_000, 5_000_000, 200_000_000, 0.0),
    ]
    parties = aggregate_by_party(rows, kind="payable")
    decisions = classify_parties(
        parties=parties,
        key_item_threshold=PM * 100,
        related_party_names=set(),
        kind="payable",
        performance_materiality=PM,
    )
    d = decisions[0]
    # activity = 200억+200억=400억? — 아니라 increase=0이므로 |기초|+|change| 방식
    # beginning=0, change=150억 → activity_each = 150억
    # 합계 activity = 300억 > PM×1.5=3억 ✓
    # ending_each = 500만 → total = 1000만 < PM×0.1=2000만 ✓
    # → suspect_flag = True
    assert d.suspect_flag is True, (
        f"activity={d.activity:,.0f}, ending={d.ending_balance:,.0f}"
    )
