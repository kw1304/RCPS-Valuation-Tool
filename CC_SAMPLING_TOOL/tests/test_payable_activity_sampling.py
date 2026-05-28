"""
test_payable_activity_sampling.py — 채무 activity 기준 sampling 검증

ISA 505 / ISA 330·530:
  채무 조회는 기말 잔액 기준이 아니라 당기 매입활동 기준으로 수행.
  기말 잔액이 작더라도 당기 매입활동(activity)이 크면 under-statement risk 존재.

검증 항목:
  1. aggregate_by_party: activity = |기초| + |증감|
  2. classify_parties(kind="payable"): balance = activity
  3. classify_parties(kind="receivable"): balance = 기말 잔액 (회귀 보호)
  4. run_sampling(kind="payable"): population_amount = sum(activity)
  5. Key item 기준이 activity 기준으로 적용됨
  6. suspect_flag: 활동량 크고 기말 잔액 소 거래처 표시
  7. 채권 sampling 회귀: 기말 잔액 기준 불변
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
import pytest

from src.domain.population import (
    LedgerRow,
    PartyBalance,
    aggregate_by_party,
    classify_parties,
    load_ledger_rows,
)
from src.orchestrator import SamplingParams, run_sampling
from datetime import date


# ─────────────────────────────────────────────────────────────
# 헬퍼 — 테스트용 LedgerRow / DataFrame 생성
# ─────────────────────────────────────────────────────────────

def _payable_rows() -> list[LedgerRow]:
    """채무 원장 픽스처.

    인투바이오: 기초 5억 + 증감 8억 = activity 13억, 기말 2억
    우진트레이딩: 기초 0 + 증감 6억 = activity 6억, 기말 6억
    삼광켐: 기초 2억 + 증감 1억 = activity 3억, 기말 1억
    """
    return [
        LedgerRow("A001", "인투바이오", "201", "외상매입금", "KRW",
                  beginning=-500_000_000, change=300_000_000, ending=-200_000_000),
        LedgerRow("A002", "우진트레이딩", "201", "외상매입금", "KRW",
                  beginning=0, change=-600_000_000, ending=-600_000_000),
        LedgerRow("A003", "삼광켐", "202", "미지급금", "KRW",
                  beginning=-200_000_000, change=100_000_000, ending=-100_000_000),
    ]


def _receivable_rows() -> list[LedgerRow]:
    """채권 원장 픽스처.

    알파코: 기말 10억 (잔액 큼)
    베타코: 기말 2억 (잔액 소)
    """
    return [
        LedgerRow("R001", "알파코", "101", "외상매출금", "KRW",
                  beginning=800_000_000, change=200_000_000, ending=1_000_000_000),
        LedgerRow("R002", "베타코", "101", "외상매출금", "KRW",
                  beginning=100_000_000, change=100_000_000, ending=200_000_000),
    ]


# ─────────────────────────────────────────────────────────────
# Task 1: aggregate_by_party — activity 계산 검증
# ─────────────────────────────────────────────────────────────

def test_aggregate_activity_calculation():
    """activity = |기초| + |증감| — 각 거래처별 정확 계산."""
    rows = _payable_rows()
    parties = aggregate_by_party(rows, kind="payable", sign_normalize=True)

    # 인투바이오: |−5억| + |+3억| = 8억
    assert parties["인투바이오"].activity == pytest.approx(800_000_000)
    # 우진트레이딩: |0| + |−6억| = 6억
    assert parties["우진트레이딩"].activity == pytest.approx(600_000_000)
    # 삼광켐: |−2억| + |+1억| = 3억
    assert parties["삼광켐"].activity == pytest.approx(300_000_000)


def test_aggregate_ending_balance_preserved():
    """기말 잔액(total)도 별도 보존 — 재무제표 대사에 사용."""
    rows = _payable_rows()
    parties = aggregate_by_party(rows, kind="payable", sign_normalize=True)

    assert parties["인투바이오"].total == pytest.approx(200_000_000)
    assert parties["우진트레이딩"].total == pytest.approx(600_000_000)
    assert parties["삼광켐"].total == pytest.approx(100_000_000)


def test_aggregate_by_account_activity():
    """by_account_activity 그룹별 활동량 누적 검증."""
    rows = _payable_rows()
    parties = aggregate_by_party(rows, kind="payable", sign_normalize=True)

    # 인투바이오 외상매입금: 8억
    assert parties["인투바이오"].by_account_activity.get("외상매입금", 0) == pytest.approx(800_000_000)
    # 삼광켐 미지급금: 3억
    assert parties["삼광켐"].by_account_activity.get("미지급금", 0) == pytest.approx(300_000_000)


# ─────────────────────────────────────────────────────────────
# Task 2: classify_parties — 채무 balance = activity
# ─────────────────────────────────────────────────────────────

def test_classify_payable_balance_is_activity():
    """채무 PartyDecision.balance = activity (기말 잔액 아님)."""
    rows = _payable_rows()
    parties = aggregate_by_party(rows, kind="payable")
    decisions = classify_parties(
        parties=parties,
        key_item_threshold=500_000_000,
        related_party_names=set(),
        kind="payable",
    )
    d_map = {d.name: d for d in decisions}

    # 인투바이오: balance = activity = 8억
    assert d_map["인투바이오"].balance == pytest.approx(800_000_000)
    # 우진트레이딩: balance = activity = 6억
    assert d_map["우진트레이딩"].balance == pytest.approx(600_000_000)
    # 삼광켐: balance = activity = 3억
    assert d_map["삼광켐"].balance == pytest.approx(300_000_000)


def test_classify_payable_ending_balance_preserved():
    """채무 PartyDecision.ending_balance = 기말 잔액 (조서 표기용 보존)."""
    rows = _payable_rows()
    parties = aggregate_by_party(rows, kind="payable")
    decisions = classify_parties(
        parties=parties,
        key_item_threshold=500_000_000,
        related_party_names=set(),
        kind="payable",
    )
    d_map = {d.name: d for d in decisions}

    assert d_map["인투바이오"].ending_balance == pytest.approx(200_000_000)
    assert d_map["우진트레이딩"].ending_balance == pytest.approx(600_000_000)


def test_classify_payable_key_item_uses_activity():
    """Key item 기준 = activity. 인투바이오(activity 8억) ≥ threshold 7억 → Key item."""
    rows = _payable_rows()
    parties = aggregate_by_party(rows, kind="payable")
    decisions = classify_parties(
        parties=parties,
        key_item_threshold=700_000_000,  # 7억
        related_party_names=set(),
        kind="payable",
    )
    d_map = {d.name: d for d in decisions}

    assert d_map["인투바이오"].is_key_item is True   # activity 8억 ≥ 7억
    assert d_map["우진트레이딩"].is_key_item is False  # activity 6억 < 7억
    assert d_map["삼광켐"].is_key_item is False       # activity 3억 < 7억


# ─────────────────────────────────────────────────────────────
# Task 3: 채권 classify — 기말 잔액 기준 회귀 보호
# ─────────────────────────────────────────────────────────────

def test_classify_receivable_balance_is_ending():
    """채권: balance = 기말 잔액 (기존 동작 회귀 보호)."""
    rows = _receivable_rows()
    parties = aggregate_by_party(rows, kind="receivable")
    decisions = classify_parties(
        parties=parties,
        key_item_threshold=500_000_000,
        related_party_names=set(),
        kind="receivable",
    )
    d_map = {d.name: d for d in decisions}

    # 알파코: balance = 기말 잔액 10억
    assert d_map["알파코"].balance == pytest.approx(1_000_000_000)
    # 베타코: balance = 기말 잔액 2억
    assert d_map["베타코"].balance == pytest.approx(200_000_000)


def test_classify_receivable_key_item_ending_based():
    """채권 Key item = 기말 잔액 기준. 알파코(10억) ≥ 5억 → Key item."""
    rows = _receivable_rows()
    parties = aggregate_by_party(rows, kind="receivable")
    decisions = classify_parties(
        parties=parties,
        key_item_threshold=500_000_000,
        related_party_names=set(),
        kind="receivable",
    )
    d_map = {d.name: d for d in decisions}

    assert d_map["알파코"].is_key_item is True
    assert d_map["베타코"].is_key_item is False


# ─────────────────────────────────────────────────────────────
# Task 4: run_sampling — population_amount = sum(activity) for payable
# ─────────────────────────────────────────────────────────────

def _make_payable_df() -> pd.DataFrame:
    """채무 원장 DataFrame — 컬럼: 코드|명|계정코드|계정명|통화|기초|증감|기말."""
    return pd.DataFrame([
        ["A001", "인투바이오",   "201", "외상매입금", "KRW", -500_000_000,  300_000_000, -200_000_000],
        ["A002", "우진트레이딩", "201", "외상매입금", "KRW",           0, -600_000_000, -600_000_000],
        ["A003", "삼광켐",       "202", "미지급금",   "KRW", -200_000_000,  100_000_000, -100_000_000],
    ])


def test_run_sampling_payable_population_is_activity():
    """run_sampling(payable): population_amount = 인투바이오(8억) + 우진(6억) + 삼광(3억) = 17억."""
    df = _make_payable_df()
    params = SamplingParams(
        company_name="테스트",
        period_end=date(2024, 12, 31),
        kind="payable",
        performance_materiality=300_000_000,
        risk_level="유의적위험",
        control_reliance="Y",
        random_seed=42,
    )
    out = run_sampling(df, params)
    # activity: 인투바이오 8억 + 우진트레이딩 6억 + 삼광켐 3억 = 17억
    assert out.population_amount == pytest.approx(1_700_000_000)


def _make_receivable_df() -> pd.DataFrame:
    return pd.DataFrame([
        ["R001", "알파코", "101", "외상매출금", "KRW",  800_000_000,  200_000_000, 1_000_000_000],
        ["R002", "베타코", "101", "외상매출금", "KRW",  100_000_000,  100_000_000,   200_000_000],
    ])


def test_run_sampling_receivable_population_is_ending():
    """run_sampling(receivable): population_amount = 기말 잔액 합계 (채권 회귀 보호)."""
    df = _make_receivable_df()
    params = SamplingParams(
        company_name="테스트",
        period_end=date(2024, 12, 31),
        kind="receivable",
        performance_materiality=300_000_000,
        risk_level="유의적위험",
        control_reliance="Y",
        random_seed=42,
    )
    out = run_sampling(df, params)
    # 기말 잔액: 알파코 10억 + 베타코 2억 = 12억
    assert out.population_amount == pytest.approx(1_200_000_000)


# ─────────────────────────────────────────────────────────────
# Task 6: suspect_flag — 활동량 크고 기말 잔액 소 거래처
# ─────────────────────────────────────────────────────────────

def test_suspect_flag_high_activity_low_ending():
    """suspect_flag: activity > PM×1.5 AND ending < PM×0.1 거래처 표시.

    PM = 2억.  인투바이오: activity 8억 > 3억(PM×1.5), ending 2억 > 2000만(PM×0.1).
    삼광켐: activity 3억 > 3억 조건 NOT satisfied (경계값 — 미만).
    """
    rows = _payable_rows()
    parties = aggregate_by_party(rows, kind="payable")
    pm = 200_000_000  # 2억

    decisions = classify_parties(
        parties=parties,
        key_item_threshold=900_000_000,  # 9억 — 아무도 Key item 아님
        related_party_names=set(),
        kind="payable",
        performance_materiality=pm,
    )
    d_map = {d.name: d for d in decisions}

    # 인투바이오: activity=8억 > PM×1.5=3억 ✓ / ending=2억 < PM×0.1=2천만 ✗
    # → suspect_flag = False (ending 조건 미충족)
    assert d_map["인투바이오"].suspect_flag is False

    # suspect_flag = True 시나리오: 기말 잔액 1천만원짜리 픽스처 별도 검증
    rows2 = [
        LedgerRow("X001", "의심거래처", "201", "외상매입금", "KRW",
                  beginning=-500_000_000, change=-100_000_000, ending=-10_000_000),
    ]
    parties2 = aggregate_by_party(rows2, kind="payable")
    d2 = classify_parties(
        parties=parties2,
        key_item_threshold=900_000_000,
        related_party_names=set(),
        kind="payable",
        performance_materiality=pm,
    )
    # activity = 6억 > PM×1.5=3억 ✓  ending = 1천만 < PM×0.1=2천만 ✓
    assert d2[0].suspect_flag is True, f"activity={d2[0].activity}, ending={d2[0].ending_balance}"


# ─────────────────────────────────────────────────────────────
# Task 8: 채무 sampling 거래처 검증
# ─────────────────────────────────────────────────────────────

def test_payable_high_activity_party_sampled():
    """활동량 큰 거래처(인투바이오·우진트레이딩)가 기말 잔액 무관하게 sampling 대상.

    인투바이오: 기말 잔액 2억(소) but activity 8억(대) → Key item or Rep 기대.
    """
    df = _make_payable_df()
    pm = 200_000_000  # 2억 — 인투바이오 activity(8억) ≥ PM×2.5 → Key item 예상

    params = SamplingParams(
        company_name="테스트",
        period_end=date(2024, 12, 31),
        kind="payable",
        performance_materiality=pm,
        risk_level="유의적위험",
        control_reliance="Y",
        random_seed=42,
    )
    out = run_sampling(df, params)

    d_map = {d.name: d for d in out.decisions}
    assert d_map["인투바이오"].final_sampled is True, (
        f"인투바이오 activity={d_map['인투바이오'].activity} 기준 sampling 안됨"
    )
