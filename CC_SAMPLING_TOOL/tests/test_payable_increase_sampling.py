"""test_payable_increase_sampling.py — 채무 sampling = 당기 증가 기준 검증

ISA 505 완전성 원칙:
  채무 조회는 기말 잔액이 아니라 당기 매입활동(증가) 기준으로 수행.
  기말 잔액이 작아도 당기 증가(매입·용역수령)가 크면 under-statement risk.

코스맥스네오 양식처럼 "증가" 컬럼이 명시된 경우:
  LedgerRow.increase 값을 activity로 직접 사용.
  (기존 7620 방식 — |기초| + |change| — 과 비교 시 더 정확)

검증 항목:
  1. increase 컬럼 있을 때 activity = increase 값
  2. increase 컬럼 없을 때 activity = |기초| + |change| (7620 호환)
  3. 채무 Key item 기준 = increase 기반 activity
  4. 기말 잔액 작아도 increase 크면 sampling 대상
  5. 채권은 activity 계산에 무관 — 기말 잔액 기준 불변 (회귀 보호)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest

from src.domain.population import LedgerRow, aggregate_by_party, classify_parties


def _row(name, beginning, increase, decrease, ending, acct="외상매입금") -> LedgerRow:
    """코스맥스네오 양식 LedgerRow — increase/decrease 명시."""
    return LedgerRow(
        code="X001", name=name, account_code="201", account_name=acct,
        currency="KRW",
        beginning=beginning, change=ending - beginning, ending=ending,
        increase=increase, decrease=decrease,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. increase 컬럼 있을 때 activity = increase
# ─────────────────────────────────────────────────────────────────────────────

def test_activity_uses_increase_when_present():
    """LedgerRow.increase > 0 이면 activity = increase (기초+change 무시)."""
    rows = [
        _row("A거래처", beginning=500_000_000, increase=10_000_000_000,
             decrease=9_800_000_000, ending=700_000_000),
    ]
    parties = aggregate_by_party(rows, kind="payable")
    # activity = increase = 100억
    assert parties["A거래처"].activity == pytest.approx(10_000_000_000)
    # 기말 잔액은 별도 보존
    assert parties["A거래처"].total == pytest.approx(700_000_000)


def test_activity_multiple_accounts_summed():
    """같은 거래처가 여러 계정과목에 걸쳐 있으면 activity 합산."""
    rows = [
        _row("코스맥스(주)", beginning=491_270_593, increase=10_040_619_675,
             decrease=10_019_893_727, ending=511_996_541, acct="외상매입금"),
        _row("코스맥스(주)", beginning=1_497_716_588, increase=11_782_807_218,
             decrease=12_163_984_357, ending=1_116_539_449, acct="지급어음"),
    ]
    parties = aggregate_by_party(rows, kind="payable")
    # activity = 10,040,619,675 + 11,782,807,218
    expected = 10_040_619_675 + 11_782_807_218
    assert parties["코스맥스(주)"].activity == pytest.approx(expected)


# ─────────────────────────────────────────────────────────────────────────────
# 2. increase 없을 때 activity = |기초| + |change| (7620 호환)
# ─────────────────────────────────────────────────────────────────────────────

def test_activity_fallback_when_increase_zero():
    """increase = 0이면 |기초| + |change| 방식으로 fallback."""
    # 기초 5억 / change = -3억(기말-기초) → |기초|+|change| = 8억
    row = LedgerRow(
        code="A001", name="인투바이오", account_code="201", account_name="외상매입금",
        currency="KRW",
        beginning=-500_000_000, change=300_000_000, ending=-200_000_000,
        increase=0.0, decrease=0.0,
    )
    parties = aggregate_by_party([row], kind="payable")
    # |−5억| + |+3억| = 8억
    assert parties["인투바이오"].activity == pytest.approx(800_000_000)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Key item 기준 = activity (increase 기반)
# ─────────────────────────────────────────────────────────────────────────────

def test_key_item_by_increase_activity():
    """increase 기반 activity가 threshold 초과 → Key item 선정."""
    rows = [
        _row("대형거래처", beginning=0, increase=50_000_000_000,
             decrease=49_900_000_000, ending=100_000_000),
        _row("소형거래처", beginning=0, increase=500_000_000,
             decrease=400_000_000, ending=100_000_000),
    ]
    parties = aggregate_by_party(rows, kind="payable")
    decisions = classify_parties(
        parties=parties,
        key_item_threshold=5_000_000_000,  # 50억 threshold
        related_party_names=set(),
        kind="payable",
    )
    d_map = {d.name: d for d in decisions}

    # 대형거래처: activity=500억 ≥ 50억 → Key item
    assert d_map["대형거래처"].is_key_item is True
    # 소형거래처: activity=5억 < 50억 → 아님
    assert d_map["소형거래처"].is_key_item is False


# ─────────────────────────────────────────────────────────────────────────────
# 4. 기말 잔액 작아도 increase 크면 sampling 대상
# ─────────────────────────────────────────────────────────────────────────────

def test_high_increase_low_ending_sampled():
    """기말 잔액 1억 미만이어도 당기 증가 500억 → Key item 선정 (under-statement risk 포착)."""
    rows = [
        # 전형적 under-statement 패턴: 매입 500억, 거의 다 결제, 기말 잔액 소
        _row("위험거래처", beginning=0, increase=50_000_000_000,
             decrease=49_950_000_000, ending=50_000_000),
    ]
    parties = aggregate_by_party(rows, kind="payable")
    decisions = classify_parties(
        parties=parties,
        key_item_threshold=1_000_000_000,  # 10억 threshold
        related_party_names=set(),
        kind="payable",
    )
    # 기말 잔액(5천만) < 10억이지만 activity(500억) ≥ 10억 → Key item
    assert decisions[0].is_key_item is True
    assert decisions[0].ending_balance == pytest.approx(50_000_000)


# ─────────────────────────────────────────────────────────────────────────────
# 5. 채권은 기말 잔액 기준 불변 (회귀 보호)
# ─────────────────────────────────────────────────────────────────────────────

def test_receivable_activity_does_not_affect_balance():
    """채권: increase 컬럼이 있어도 balance = 기말 잔액 (채권 실재성 기준 불변)."""
    rows = [
        LedgerRow(
            code="R001", name="알파코", account_code="101", account_name="외상매출금",
            currency="KRW",
            beginning=800_000_000, change=200_000_000, ending=1_000_000_000,
            increase=5_000_000_000,  # increase 주입 — 채권에서는 무시되어야 함
            decrease=4_800_000_000,
        ),
    ]
    parties = aggregate_by_party(rows, kind="receivable")
    decisions = classify_parties(
        parties=parties,
        key_item_threshold=500_000_000,
        related_party_names=set(),
        kind="receivable",
    )
    # 채권 balance = 기말 잔액 10억
    assert decisions[0].balance == pytest.approx(1_000_000_000)
    # Key item: 기말 잔액 10억 ≥ 5억 → True
    assert decisions[0].is_key_item is True
