"""대손충당금 판정.

설계서 5.4 — 부실채권 자동 제외 판정 근거.
"""
from __future__ import annotations
from src.domain.entities import Account


def is_fully_provisioned(acc: Account) -> bool:
    """충당금 100% & is_bad_debt 플래그.

    잔액 ≤ 0이면 False. 두 조건 모두 만족해야 표본에서 자동 제외 대상.
    """
    if abs(acc.balance_krw) < 1e-9:
        return False
    if not acc.is_bad_debt:
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
