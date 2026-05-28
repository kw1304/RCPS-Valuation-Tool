"""KEY / RP / BAD / EXCLUDED 분류.

설계서 5.4. 우선순위:
EXCLUDED_BAD > EXCLUDED_ZERO > FORCED_RP > FORCED_KEY > REP.
"""
from __future__ import annotations
from src.domain.entities import Account, SelectionReason
from src.domain.allowance import is_fully_provisioned


def classify_population(
    accounts: list[Account],
    key_threshold: float,
) -> tuple[
    list[tuple[Account, SelectionReason]],
    list[tuple[Account, SelectionReason]],
    list[Account],
]:
    """모집단을 강제포함·제외·잔여로 분류.

    Args:
        accounts: 분류 대상.
        key_threshold: |잔액| ≥ threshold면 KEY로 강제포함.

    Returns:
        (forced, excluded, remaining).
        forced·excluded는 (account, reason) 페어. remaining은 raw Account.
    """
    forced: list[tuple[Account, SelectionReason]] = []
    excluded: list[tuple[Account, SelectionReason]] = []
    remaining: list[Account] = []

    for acc in accounts:
        if is_fully_provisioned(acc):
            excluded.append((acc, SelectionReason.EXCLUDED_BAD))
            continue
        if abs(acc.balance_krw) < 1e-9:
            excluded.append((acc, SelectionReason.EXCLUDED_ZERO))
            continue
        if acc.is_related_party:
            forced.append((acc, SelectionReason.FORCED_RP))
            continue
        if abs(acc.balance_krw) >= key_threshold:
            forced.append((acc, SelectionReason.FORCED_KEY))
            continue
        remaining.append(acc)

    return forced, excluded, remaining
