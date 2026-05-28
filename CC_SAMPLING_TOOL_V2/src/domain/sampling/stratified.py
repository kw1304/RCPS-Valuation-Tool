"""Stratification — 다단계 + uniform·소규모 fallback.

설계서 5.3.
"""
from __future__ import annotations
import math
import statistics
from typing import Optional
from src.domain.entities import Account, Strata
from src.domain.sampling.mus import pps_select


MIN_POPULATION_FOR_STRATIFY = 50
UNIFORM_CV_THRESHOLD = 0.3


def should_use_single_stratum(accounts: list[Account]) -> bool:
    """단일 strata로 강등할지 판단.

    조건: 모집단 < 50 OR 잔액 변동계수(CV) < 0.3.
    """
    if len(accounts) < MIN_POPULATION_FOR_STRATIFY:
        return True
    balances = [abs(a.balance_krw) for a in accounts if a.balance_krw != 0]
    if not balances:
        return True
    mean = statistics.fmean(balances)
    if mean == 0:
        return True
    stdev = statistics.pstdev(balances)
    cv = stdev / mean
    return cv < UNIFORM_CV_THRESHOLD


def suggest_strata(
    accounts: list[Account],
    n_strata: int = 4,
) -> list[Strata]:
    """log-binning으로 strata 경계 제안.

    각 strata의 n_required는 0 (호출자가 별도 할당).
    """
    if n_strata < 1:
        raise ValueError("n_strata must be >= 1")
    balances = sorted(abs(a.balance_krw) for a in accounts if a.balance_krw != 0)
    if not balances:
        return [Strata(low=0.0, high=0.0, n_required=0)]

    min_b = balances[0]
    max_b = balances[-1]
    if min_b == max_b or n_strata == 1:
        return [Strata(low=0.0, high=max_b, n_required=0)]

    # log-spaced edges
    log_min = math.log10(min_b if min_b > 0 else 1)
    log_max = math.log10(max_b)
    edges = [10 ** (log_min + (log_max - log_min) * i / n_strata)
             for i in range(n_strata + 1)]
    edges[0] = 0.0  # 최저 strata는 0부터 (작은 잔액 흡수)

    return [Strata(low=edges[i], high=edges[i + 1], n_required=0)
            for i in range(n_strata)]


def stratified_pps(
    accounts: list[Account],
    strata: list[Strata],
    seed: Optional[int] = None,
) -> list[Account]:
    """각 strata 내 MUS PPS 독립 수행 후 union.

    각 account는 최초 매칭되는 strata 1곳에만 할당 (경계 중복 방지).
    """
    assigned: set[int] = set()
    sample: list[Account] = []
    for i, st in enumerate(strata):
        bucket: list[Account] = []
        for a in accounts:
            if id(a) in assigned:
                continue
            if st.contains(abs(a.balance_krw)):
                bucket.append(a)
                assigned.add(id(a))
        sub_seed = None if seed is None else seed + i
        sample.extend(pps_select(bucket, st.n_required, seed=sub_seed))
    return sample
