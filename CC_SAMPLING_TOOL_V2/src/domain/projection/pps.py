"""ISA 530 PPS Projection.

설계서 5.8.
"""
from __future__ import annotations
from typing import Optional
from src.domain.entities import Kind, ProjectionResult
from src.domain.sampling.sample_size import reliability_factor


# AAG-SAM Table A-4: Incremental allowance factor by rank.
_RANK_INCREMENTS_TABLE: dict[float, list[float]] = {
    0.80: [0.66, 0.55, 0.46, 0.40, 0.35, 0.30],
    0.90: [0.66, 0.55, 0.46, 0.40, 0.35, 0.30],
    0.95: [0.75, 0.55, 0.46, 0.40, 0.35, 0.30],
    0.99: [0.80, 0.60, 0.55, 0.40, 0.35, 0.30],
}


def _rank_increments(confidence: float) -> list[float]:
    """Rank별 RF 증분 반환. 6위 이후는 마지막 값(0.30) 반복."""
    if confidence not in _RANK_INCREMENTS_TABLE:
        raise ValueError(f"unsupported confidence {confidence!r}")
    base = _RANK_INCREMENTS_TABLE[confidence]
    return base + [base[-1]] * 100


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

    increments = _rank_increments(confidence)
    taintings_sub_one.sort(reverse=True)
    incremental = sum(
        increments[i] * t * sampling_interval
        for i, t in enumerate(taintings_sub_one)
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
