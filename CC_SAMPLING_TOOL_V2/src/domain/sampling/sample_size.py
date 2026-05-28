"""AAG-SAM 기반 MUS 표본규모 산정.

근거: AICPA Audit Guide — Audit Sampling (AAG-SAM), Table A-2 (신뢰계수),
Table A-3 (Expansion Factor).
"""
from __future__ import annotations
import math


# AAG-SAM Table A-2: Reliability factors at zero misstatement
_RF_TABLE = {
    0.99: 4.61,
    0.95: 3.00,
    0.90: 2.31,
    0.80: 1.61,
}

# AAG-SAM Table A-3: Expansion Factor for Expected Misstatement
# 키: 신뢰수준, 값: (em_ratio → factor) 선형보간용
_EXPANSION_TABLE = {
    0.99: [(0.0, 1.00), (0.1, 1.60), (0.3, 1.90), (0.5, 2.30)],
    0.95: [(0.0, 1.00), (0.1, 1.50), (0.3, 1.75), (0.5, 2.00)],
    0.90: [(0.0, 1.00), (0.1, 1.40), (0.3, 1.60), (0.5, 1.80)],
    0.80: [(0.0, 1.00), (0.1, 1.30), (0.3, 1.50), (0.5, 1.70)],
}


def reliability_factor(confidence: float) -> float:
    """신뢰수준에 대응하는 reliability factor 반환."""
    if confidence not in _RF_TABLE:
        raise ValueError(
            f"unsupported confidence {confidence!r}; "
            f"choose from {sorted(_RF_TABLE)}"
        )
    return _RF_TABLE[confidence]


def expansion_factor(confidence: float, em_ratio: float) -> float:
    """예상오차 비율 (EM/TM)에 따른 Expansion Factor (선형보간)."""
    if confidence not in _EXPANSION_TABLE:
        raise ValueError(f"unsupported confidence {confidence!r}")
    if em_ratio < 0:
        raise ValueError("em_ratio must be >= 0")

    points = _EXPANSION_TABLE[confidence]
    if em_ratio >= points[-1][0]:
        return points[-1][1]
    for i in range(len(points) - 1):
        x0, y0 = points[i]
        x1, y1 = points[i + 1]
        if x0 <= em_ratio <= x1:
            if x1 == x0:
                return y0
            t = (em_ratio - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return points[0][1]


def sample_size_mus(
    book_value: float,
    confidence: float,
    tolerable: float,
    expected_ms: float,
) -> int:
    """MUS 표본규모.

    n = (BV × RF) / (TM − EM × ExpansionFactor)

    Args:
        book_value: 모집단 장부가 (외화 환산 후 base_ccy).
        confidence: 신뢰수준 (0.80/0.90/0.95/0.99).
        tolerable: tolerable misstatement.
        expected_ms: expected misstatement.

    Returns:
        표본수 (올림).

    Raises:
        ValueError: EM × ExpansionFactor ≥ TM 인 경우 (표본 불가능).
    """
    rf = reliability_factor(confidence)
    em_ratio = expected_ms / tolerable if tolerable > 0 else 0
    ef = expansion_factor(confidence, em_ratio)

    denom = tolerable - expected_ms * ef
    if denom <= 0:
        raise ValueError(
            f"EM × ExpansionFactor ({expected_ms * ef:.0f}) "
            f">= tolerable ({tolerable:.0f}) — sample design impossible"
        )
    return math.ceil((book_value * rf) / denom)
