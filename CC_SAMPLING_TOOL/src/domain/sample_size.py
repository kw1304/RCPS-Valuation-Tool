"""
표본규모 결정 로직 (감사기준서 530 + AICPA Audit Sampling Guide)

핵심 식:
    Key item 기준금액 = PM × 비율(위험·통제 매트릭스)
    Key item   = {거래처 | 잔액 ≥ Key item 기준금액}  (전수)
    잔여모집단  = 모집단 - Σ(Key item 잔액)
    Base size  = 잔여모집단 / PM
    Final size = ceil(Base × Confidence Factor)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

RiskLevel = Literal["낮음", "보통", "높음", "유의적위험"]
ControlReliance = Literal["Y", "N"]


# --- 위험·통제 매트릭스 -----------------------------------------------
# (1) Key item 기준금액 비율 (PM 대비)
#   감사기준서 530 보론 + 실무 예시
#   "통제 의존 O" → 더 큰 비율 허용 (Key item 범위 좁힘 = 표본↑)
#   기본값은 매트릭스 중간값
KEY_ITEM_RATIO_MATRIX: dict[tuple[RiskLevel, ControlReliance], float] = {
    ("낮음",       "Y"): 0.875,  # 75~100% → mid 87.5%
    ("낮음",       "N"): 0.375,  # 25~50%  → mid 37.5%
    ("보통",       "Y"): 0.75,
    ("보통",       "N"): 0.30,
    ("높음",       "Y"): 0.625,  # 50~75%
    ("높음",       "N"): 0.175,  # 10~25%
    ("유의적위험", "Y"): 0.75,   # 7620 조서 케이스
    ("유의적위험", "N"): 0.15,
}

# (2) Confidence Factor (신뢰계수)
#   AICPA SAM Guide Table A-1 (95% 신뢰수준, 예상왜곡표시=0 기준)
#   "통제 의존 O" + 다른 실증절차 보강 → CF 낮춤
CONFIDENCE_FACTOR_MATRIX: dict[tuple[RiskLevel, ControlReliance], float] = {
    ("낮음",       "Y"): 0.7,
    ("낮음",       "N"): 1.6,
    ("보통",       "Y"): 1.2,
    ("보통",       "N"): 2.3,
    ("높음",       "Y"): 1.9,
    ("높음",       "N"): 2.6,
    ("유의적위험", "Y"): 1.4,   # 7620 조서 케이스
    ("유의적위험", "N"): 3.0,
}


@dataclass(frozen=True)
class SampleSizeInput:
    population_amount: float           # 모집단 금액 (발송대상)
    performance_materiality: float     # PM
    risk_level: RiskLevel
    control_reliance: ControlReliance
    key_item_ratio_override: float | None = None      # 사용자 직접 지정 시
    confidence_factor_override: float | None = None
    key_item_amount: float | None = None              # Key item 잔액 합계 (사전 계산)


@dataclass(frozen=True)
class SampleSizeResult:
    key_item_threshold: float          # Key item 기준금액
    key_item_ratio: float              # 적용된 비율
    confidence_factor: float
    base_sample_size: float
    final_sample_size: int             # ceil(base × CF)
    sample_interval: float             # 표본간격 = 잔여 / Final
    remaining_population: float        # 모집단 - Key item


def resolve_key_item_ratio(risk: RiskLevel, ctrl: ControlReliance, override: float | None) -> float:
    if override is not None:
        return override
    return KEY_ITEM_RATIO_MATRIX[(risk, ctrl)]


def resolve_confidence_factor(risk: RiskLevel, ctrl: ControlReliance, override: float | None) -> float:
    if override is not None:
        return override
    return CONFIDENCE_FACTOR_MATRIX[(risk, ctrl)]


def compute_sample_size(inp: SampleSizeInput) -> SampleSizeResult:
    ratio = resolve_key_item_ratio(inp.risk_level, inp.control_reliance, inp.key_item_ratio_override)
    cf = resolve_confidence_factor(inp.risk_level, inp.control_reliance, inp.confidence_factor_override)

    threshold = inp.performance_materiality * ratio
    key_amt = inp.key_item_amount if inp.key_item_amount is not None else 0.0
    remaining = max(inp.population_amount - key_amt, 0.0)

    base = remaining / inp.performance_materiality if inp.performance_materiality > 0 else 0.0
    final = math.ceil(base * cf) if base > 0 else 0
    interval = remaining / final if final > 0 else 0.0

    return SampleSizeResult(
        key_item_threshold=threshold,
        key_item_ratio=ratio,
        confidence_factor=cf,
        base_sample_size=base,
        final_sample_size=final,
        sample_interval=interval,
        remaining_population=remaining,
    )
