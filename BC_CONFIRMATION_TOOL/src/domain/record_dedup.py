"""추출 레코드 중복제거(dedup) — 이중계상 방지.

배경
----
회신본 입력 디렉터리에 *개별 회신본 PDF* 와 *그것들을 한 파일로 합친 합본 스캔*
(예: 'new-document-2025-04-10.pdf') 이 함께 들어오면, 동일한 금융자산 holding 이
두 번 파싱돼 AC 금액합이 ~2배가 된다(코스맥스 FY2024 AC1 510억→1,017억).

해결
----
같은 holding 을 가리키는 두 레코드를 한 건으로 접는다. 합본 스캔은 파일명 메타가
없어 bc_no·bank 가 비므로, 이 둘은 dedup 키에서 **제외**한다.

키 = (ac_section, account_no, product, balance, currency)
  - 계좌번호가 있으면 계좌번호가 사실상 유일 식별자(같은 계좌+같은 잔액 = 같은 행).
  - 계좌번호가 없는 행(당좌개설보증금 등)은 product+balance+currency 로 식별.
  - 잔액 0(또는 None)은 키 충돌이 흔한 noise → dedup 대상에서 제외(항상 보존).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def _norm_amount(v: Any) -> str | None:
    """금액을 정규화된 정수 문자열로. 0·None·비금액 → None(=dedup 비대상)."""
    if v is None:
        return None
    if isinstance(v, (int, float, Decimal)):
        try:
            iv = int(Decimal(str(v)))
        except (InvalidOperation, ValueError):
            return None
        return str(iv) if iv != 0 else None
    s = str(v).strip().replace(",", "")
    if not s:
        return None
    try:
        iv = int(Decimal(s))
    except (InvalidOperation, ValueError):
        return None
    return str(iv) if iv != 0 else None


def _as_dict(rec: Any) -> dict:
    if hasattr(rec, "model_dump"):
        return rec.model_dump()
    if isinstance(rec, dict):
        return rec
    return dict(rec)


def dedup_key(ac_section: str, rec: Any) -> tuple | None:
    """레코드의 dedup 키. 같은 holding 이면 같은 키, 다르면 다른 키.

    잔액이 0/None/비금액이면 None(=dedup 비대상, 항상 보존)."""
    d = _as_dict(rec)
    bal = _norm_amount(d.get("balance"))
    if bal is None:
        return None
    acct = d.get("account_no")
    acct = str(acct).strip() if acct not in (None, "") else None
    prod = d.get("product")
    prod = str(prod).strip() if prod not in (None, "") else None
    ccy = d.get("currency")
    ccy = str(ccy).strip() if ccy not in (None, "") else None
    # 계좌번호가 있으면 product 는 키에서 뺀다(합본/개별 간 product 표기 차이 흡수).
    if acct is not None:
        return (ac_section, acct, None, bal, ccy)
    return (ac_section, None, prod, bal, ccy)
