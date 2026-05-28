"""Strata n_required 할당 — BV 비례 + 최소 1개 (잔액 존재 시).

설계서 §3 UX (strata 자동제안), §5.3 보강.
"""
from __future__ import annotations
from src.domain.entities import Account, Strata


def allocate_strata(
    strata: list[Strata],
    accounts: list[Account],
    total_n: int,
) -> list[Strata]:
    """각 strata에 표본수 비례 할당.

    정책:
    - 각 strata의 BV(잔액 합) 비례로 floor 분배
    - 잔여 표본은 BV 큰 strata부터 1개씩 추가
    - 잔액 있는 strata는 최소 1개 보장 (단 total_n이 충분할 때)
    - 잔액 0인 strata는 0
    """
    if total_n <= 0:
        return [Strata(s.low, s.high, n_required=0) for s in strata]

    bvs = []
    for s in strata:
        bv = sum(abs(a.balance_krw) for a in accounts
                 if s.contains(abs(a.balance_krw)))
        bvs.append(bv)

    total_bv = sum(bvs)
    if total_bv <= 0:
        return [Strata(s.low, s.high, n_required=0) for s in strata]

    raw = [bv / total_bv * total_n for bv in bvs]
    n_allocs = [int(r) for r in raw]

    needs_min = [i for i, bv in enumerate(bvs) if bv > 0 and n_allocs[i] == 0]
    while needs_min and sum(n_allocs) < total_n:
        idx = needs_min.pop(0)
        n_allocs[idx] = 1

    remainders = sorted(
        [(raw[i] - n_allocs[i], i) for i in range(len(strata))],
        reverse=True,
    )
    leftover = total_n - sum(n_allocs)
    for _, i in remainders:
        if leftover <= 0:
            break
        if bvs[i] > 0:
            n_allocs[i] += 1
            leftover -= 1

    return [
        Strata(strata[i].low, strata[i].high, n_required=n_allocs[i])
        for i in range(len(strata))
    ]
