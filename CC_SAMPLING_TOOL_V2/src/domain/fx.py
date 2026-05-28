"""외화 환산.

설계서 5.5. 기말환율 사용 (잔액 평가용).
"""
from __future__ import annotations
from typing import Optional


class FxRateMissing(Exception):
    """환율 미확보 시 발생."""


def convert_to_base(
    amount: float,
    ccy: str,
    base_ccy: str,
    rate: Optional[float],
) -> float:
    """원통화 금액을 base_ccy로 환산.

    Args:
        amount: 원통화 잔액 (음수 허용 — 환불·선수금 등).
        ccy: 원통화 코드.
        base_ccy: 기준통화 코드.
        rate: ccy 1단위당 base_ccy 환율. ccy == base_ccy면 무시.

    Returns:
        base_ccy 환산 금액.

    Raises:
        FxRateMissing: 다른 통화이면서 rate가 None·0·음수일 때.
    """
    if ccy == base_ccy:
        return amount
    if rate is None or rate <= 0:
        raise FxRateMissing(f"missing or invalid fx rate for {ccy}->{base_ccy}: {rate}")
    return amount * rate
