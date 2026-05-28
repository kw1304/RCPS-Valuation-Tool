"""회신 매칭·차이판정.

설계서 5.6.
"""
from __future__ import annotations
from typing import Optional
from src.domain.entities import Verdict


DEFAULT_FLOOR = 1000.0
DEFAULT_RATIO = 0.001
RECONCILABLE_REASONS = {"시점차이", "미수령", "미발송"}


def judge_response(
    expected: float,
    confirmed: Optional[float],
    diff_reason: Optional[str],
    floor: float = DEFAULT_FLOOR,
    ratio_threshold: float = DEFAULT_RATIO,
) -> Verdict:
    """회신 결과를 판정.

    Args:
        expected: 장부상 기대 잔액.
        confirmed: 회신 받은 잔액. None이면 미회신·추출 실패.
        diff_reason: 사용자 입력 차이사유 (시점차이 등).
        floor: 최소 절대 임계값 (기본 ₩1,000).
        ratio_threshold: |expected| 대비 비율 (기본 0.1%).

    Returns:
        MATCH / RECONCILED / DISCREPANCY / NO_RESPONSE.
    """
    if confirmed is None:
        return Verdict.NO_RESPONSE

    diff = confirmed - expected
    # floor는 소액 잔액 보호용: |expected| < floor 일 때만 floor 적용,
    # 그 외엔 비율 임계값 사용.
    if abs(expected) < floor:
        threshold = floor
    else:
        threshold = abs(expected) * ratio_threshold

    if abs(diff) <= threshold:
        return Verdict.MATCH
    if diff_reason in RECONCILABLE_REASONS:
        return Verdict.RECONCILED
    return Verdict.DISCREPANCY
