"""대손충당금 판정.

설계서 5.4 — 부실채권 자동 제외 판정 근거.
"""
from __future__ import annotations
from src.domain.entities import Account


def is_fully_provisioned(acc: Account) -> bool:
    """표본 자동 제외 대상(완전 대손) 판정 — 순장부가 기준.

    제외 = 충당금 100% 이상 (순장부가 ≈ 0).
    - 충당 100% → 순장부가 0, 조회 실익 없음(이미 손상차손 인식) → 제외.
      부실(is_bad_debt) 플래그 유무와 무관.
    - 부실 플래그라도 충당 부족(순장부가 유의적)이면 제외하지 않음:
      순장부가가 남은 부실채권은 외부조회/대체절차가 가장 필요한
      고위험 모집단이므로 표본에서 자동 제외하면 완전성 누락.
    잔액 ≤ 0이면 대상 아님(별도 EXCLUDED_ZERO 처리).
    """
    if abs(acc.balance_krw) < 1e-9:
        return False
    return acc.allowance_ratio >= 1.0 - 1e-9


def classify_allowance_band(acc: Account) -> str:
    """충당금 구간 분류.

    Returns:
        "NORMAL" (충당 0), "PARTIAL" (0~100%), "FULL" (정확히 100%),
        "EXCESS" (>100%, 데이터 이상).
    """
    ratio = acc.allowance_ratio
    if ratio < 1e-9:
        return "NORMAL"
    if ratio < 1.0 - 1e-9:
        return "PARTIAL"
    if ratio < 1.0 + 1e-9:
        return "FULL"
    return "EXCESS"
