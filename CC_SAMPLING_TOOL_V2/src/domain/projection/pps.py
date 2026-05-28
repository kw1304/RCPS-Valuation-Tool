"""ISA 530 PPS Projection.

설계서 5.8.
"""
from __future__ import annotations
from typing import Optional
from src.domain.entities import Kind, ProjectionResult
from src.domain.sampling.sample_size import reliability_factor


# Incremental allowance factor (RF increment between ranks for tainting < 1).
# 단순화: 동일 RF 사용 (각 rank별 reliability_factor 차분 테이블은 별도 필요. 여기선 보수적 근사).
_INCREMENTAL_FACTOR = {
    0.99: 1.40,
    0.95: 1.00,
    0.90: 0.85,
    0.80: 0.70,
}


def tainting(
    misstatement: float,
    book: float,
    sampling_interval: float,
) -> Optional[float]:
    """tainting 비율 계산.

    Returns:
        book < interval이면 ms/book (tainting 비율).
        book >= interval이면 None (key item, 자체 추정 모드).
    """
    if abs(book) >= sampling_interval:
        return None
    if abs(book) < 1e-9:
        return 0.0
    return misstatement / book


def project_misstatement(
    kind: Kind,
    confidence: float,
    sampling_interval: float,
    tolerable: float,
    sampled_misstatements: list[tuple[float, float]],
) -> ProjectionResult:
    """ISA 530 PPS projection.

    Args:
        kind: AR / AP.
        confidence: 신뢰수준.
        sampling_interval: BV / n.
        tolerable: tolerable misstatement.
        sampled_misstatements: [(misstatement_amt, book_amt), ...].

    Returns:
        ProjectionResult.
    """
    rf = reliability_factor(confidence)
    basic_precision = rf * sampling_interval

    projected_ms = 0.0
    taintings_sub_one: list[float] = []
    for ms_amt, book in sampled_misstatements:
        t = tainting(ms_amt, book, sampling_interval)
        if t is None:
            # key item: 실제 오차 사용
            projected_ms += ms_amt
        else:
            projected_ms += t * sampling_interval
            if 0 < t < 1.0:
                taintings_sub_one.append(t)

    inc_factor = _INCREMENTAL_FACTOR.get(confidence, 1.0)
    taintings_sub_one.sort(reverse=True)
    incremental = sum(
        inc_factor * t * sampling_interval for t in taintings_sub_one
    )

    upper = projected_ms + basic_precision + incremental
    verdict = "WITHIN_TOLERABLE" if upper <= tolerable else "EXCEED"

    return ProjectionResult(
        kind=kind,
        projected_misstatement=projected_ms,
        basic_precision=basic_precision,
        incremental_allowance=incremental,
        upper_limit=upper,
        tolerable=tolerable,
        verdict=verdict,
    )
