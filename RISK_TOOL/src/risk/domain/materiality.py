from __future__ import annotations
from dataclasses import dataclass
from risk.domain.financial import FinancialYear

_PM_RATIO = 0.75  # 수행중요성 = 중요성 × 75% (기본)

# 직접지정 benchmark → (표시명, FinancialYear 값 추출, 기본 중요성비율)
_BENCHMARKS = {
    "revenue": ("매출액", lambda fy: fy.revenue, 0.005),
    "total_assets": ("자산총계", lambda fy: fy.total_assets, 0.005),
    "pretax_income": ("세전이익", lambda fy: fy.pretax_income, 0.05),
    "total_equity": ("자본총계", lambda fy: fy.total_equity, 0.01),
}


@dataclass(frozen=True)
class Materiality:
    materiality: float
    pm: float
    benchmark: str
    manual: bool = False


def performance_materiality(
    fy: FinancialYear,
    *,
    benchmark: str | None = None,
    materiality_ratio: float | None = None,
    pm_ratio: float | None = None,
) -> Materiality:
    """수행중요성(PM) 산정.

    benchmark 미지정(자동): 매출0.5%/자산0.5%/세전이익5% 후보 중 가장 작은(보수적) 채택.
    benchmark 지정(직접): 해당 기준값 × materiality_ratio(미지정 시 기본비율). PM = 중요성 × pm_ratio.

    materiality_ratio·pm_ratio는 소수(0.005, 0.75). API에서 %→소수 변환해 전달.
    """
    pmr = pm_ratio if pm_ratio is not None else _PM_RATIO
    if not (0 < pmr <= 1):
        raise ValueError("수행중요성 비율은 0~100% 사이여야 합니다.")

    if benchmark:  # ── 직접 지정 ──
        if benchmark not in _BENCHMARKS:
            raise ValueError(f"알 수 없는 benchmark: {benchmark}")
        label, getter, default_ratio = _BENCHMARKS[benchmark]
        base = getter(fy)
        if base is None or base <= 0:
            raise ValueError(f"선택한 기준({label})의 값이 결측이거나 0 이하입니다.")
        ratio = materiality_ratio if materiality_ratio is not None else default_ratio
        if not (0 < ratio <= 1):
            raise ValueError("중요성 비율은 0~100% 사이여야 합니다.")
        materiality = base * ratio
        return Materiality(materiality=materiality, pm=materiality * pmr,
                           benchmark=benchmark, manual=True)

    # ── 자동 (보수적 최소 benchmark) ──
    cands: list[tuple[str, float]] = []
    if fy.pretax_income is not None and fy.pretax_income > 0:
        cands.append(("pretax_income", fy.pretax_income * 0.05))
    if fy.revenue is not None and fy.revenue > 0:
        cands.append(("revenue", fy.revenue * 0.005))
    if fy.total_assets is not None and fy.total_assets > 0:
        cands.append(("total_assets", fy.total_assets * 0.005))
    if not cands:
        raise ValueError("중요성 산정 benchmark 없음 (매출·자산·세전이익 모두 결측/비양수)")
    benchmark, materiality = min(cands, key=lambda c: c[1])
    return Materiality(materiality=materiality, pm=materiality * pmr,
                       benchmark=benchmark, manual=False)
