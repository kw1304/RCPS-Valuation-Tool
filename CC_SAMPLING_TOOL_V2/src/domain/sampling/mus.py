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

    # weight 큰 순 정렬 — systematic 첫 interval에 잔액 최대 거래처 보장.
    # interval ≤ 최대 weight면 첫 인터벌이 최대 거래처를 항상 cover.
    positives = sorted(positives,
                        key=lambda a: -abs(getattr(a, weight_attr, 0.0)))

    cumsum = []
    running = 0.0
    for a in positives:
        running += abs(getattr(a, weight_attr, 0.0))
        cumsum.append(running)
    total = cumsum[-1]
    interval = total / n

    rng = random.Random(seed)
    # 첫 거래처(가장 큰 weight) 100% 보장 — start ≤ cumsum[0].
    # interval > cumsum[0]면 start 범위 축소 (PPS 통계 representativeness 유지).
    upper = min(interval, cumsum[0])
    start = rng.uniform(0, upper)

    selected: list[Account] = []
    seen: set[int] = set()
    j = 0
    for i in range(n):
        target = start + i * interval
        while j < len(positives) and cumsum[j] < target:
            j += 1
        if j >= len(positives):
            break
        a = positives[j]
        if id(a) not in seen:
            selected.append(a)
            seen.add(id(a))

    # 대형 항목이 복수 interval 흡수 → systematic만으론 n 미달.
    # 미선정 항목을 weight 큰 순(이미 정렬됨)으로 채워 정확히 n 보장.
    # (n < len(positives)는 위에서 보장됨.)
    if len(selected) < n:
        for a in positives:
            if id(a) not in seen:
                selected.append(a)
                seen.add(id(a))
                if len(selected) >= n:
                    break

    return selected
