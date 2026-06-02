from __future__ import annotations
from dataclasses import dataclass
from risk.domain.financial import FinancialYear

_PM_RATIO = 0.75  # 수행중요성 = 중요성 × 75%


@dataclass(frozen=True)
class Materiality:
    materiality: float
    pm: float
    benchmark: str


def performance_materiality(fy: FinancialYear) -> Materiality:
    """benchmark 후보 중 가장 작은(보수적) 중요성 채택. PM = 중요성 × 0.75."""
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
    return Materiality(materiality=materiality, pm=materiality * _PM_RATIO,
                       benchmark=benchmark)
