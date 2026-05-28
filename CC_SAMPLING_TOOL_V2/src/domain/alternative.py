"""대체적 절차 coverage 계산.

설계서 §5.7. coverage_pct >= 0.75 이면 ACCEPTABLE.
"""
from __future__ import annotations
from typing import Literal


COVERAGE_ACCEPTABLE_THRESHOLD = 0.75


def coverage_verdict(
    covered_amt: float,
    non_response_total: float,
) -> tuple[float, Literal["ACCEPTABLE", "INSUFFICIENT"]]:
    """대체적 절차 증빙 비율 + 충분성 판정.

    Args:
        covered_amt: 대체적 절차로 증빙된 잔액 합계.
        non_response_total: 미회신 잔액 합계.

    Returns:
        (pct, verdict). pct는 [0, 1] 범위로 cap.
    """
    if non_response_total <= 0:
        return 1.0, "ACCEPTABLE"
    pct = min(1.0, covered_amt / non_response_total)
    verdict = "ACCEPTABLE" if pct >= COVERAGE_ACCEPTABLE_THRESHOLD else "INSUFFICIENT"
    return pct, verdict
