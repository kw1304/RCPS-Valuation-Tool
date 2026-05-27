"""채권채무조회서 차이 판정 — 장부가 vs 회신 잔액 대사.

ISA 505 / 감사기준서 505에 따라 회신 잔액과 장부가 차이를 수치로 계산하고
허용 차이(tolerance) 내 여부를 판정한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ReconResult:
    status: str                          # "matched" | "mismatch" | "extraction_failed"
    difference: Optional[float]         # 장부가 - 회신 잔액 (None이면 추출 실패)
    difference_pct: Optional[float]     # 차이 / 장부가 (분모 0이면 None)
    tolerance: float                     # 적용된 허용 차이


def reconcile(
    ledger_balance: float,
    extracted_balance: Optional[float],
    tolerance: float = 0.0,
) -> ReconResult:
    """장부가와 추출된 회신 잔액을 대사한다.

    Args:
        ledger_balance: Step 1 샘플링 결과의 장부가
        extracted_balance: PDF에서 추출된 잔액 (None이면 추출 실패)
        tolerance: 차이 허용 금액 (기본 0원 — 1원이라도 다르면 mismatch)

    Returns:
        ReconResult: 상태·차이·차이율 포함
    """
    if extracted_balance is None:
        return ReconResult(
            status="extraction_failed",
            difference=None,
            difference_pct=None,
            tolerance=tolerance,
        )

    difference = ledger_balance - extracted_balance
    difference_pct = (difference / ledger_balance) if ledger_balance != 0 else None

    if abs(difference) <= tolerance:
        status = "matched"
    else:
        status = "mismatch"

    return ReconResult(
        status=status,
        difference=difference,
        difference_pct=difference_pct,
        tolerance=tolerance,
    )
