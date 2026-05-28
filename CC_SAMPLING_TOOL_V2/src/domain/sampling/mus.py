"""MUS systematic PPS 선택.

설계서 5.2.
"""
from __future__ import annotations
import random
from typing import Optional
from src.domain.entities import Account


def pps_select(
    accounts: list[Account],
    n: int,
    seed: Optional[int] = None,
    weight_attr: str = "balance_krw",
) -> list[Account]:
    """누적가중치 기반 systematic PPS.

    각 acc는 |getattr(a, weight_attr)| 비례 확률로 선정. n >= population 이면 모두 반환.

    Args:
        accounts: 후보 모집단.
        n: 추출 개수.
        seed: 결정적 추출용. None이면 매 호출 다름 (운영용).
        weight_attr: PPS 가중 기준 속성명. 기본 "balance_krw"(잔액),
                     AP 활동량 기반 PPS는 "debit_amt".

    Returns:
        선정된 Account 리스트 (입력 순서 유지).
    """
    if n <= 0:
        return []

    positives = [a for a in accounts if abs(getattr(a, weight_attr, 0.0)) > 1e-9]
    if not positives:
        return []
    if n >= len(positives):
        return list(positives)

    cumsum = []
    running = 0.0
    for a in positives:
        running += abs(getattr(a, weight_attr, 0.0))
        cumsum.append(running)
    total = cumsum[-1]
    interval = total / n

    rng = random.Random(seed)
    start = rng.uniform(0, interval)

    selected: list[Account] = []
    j = 0
    for i in range(n):
        target = start + i * interval
        while j < len(positives) and cumsum[j] < target:
            j += 1
        if j >= len(positives):
            break
        if not selected or selected[-1] is not positives[j]:
            selected.append(positives[j])

    return selected
