"""추출 레코드 중복제거(dedup) — 이중계상 방지.

배경
----
회신본 입력 디렉터리에 *개별 회신본 PDF* 와 *그것들을 한 파일로 합친 합본 스캔*
(예: 'new-document-2025-04-10.pdf') 이 함께 들어오면, 동일한 금융자산 holding 이
두 번 파싱돼 AC 금액합이 ~2배가 된다(코스맥스 FY2024 AC1 510억→1,017억).

해결
----
합본 스캔은 파일명 메타가 없어 bc_no·bank 가 비어있다("untagged"). 개별 회신본은
bc_no 또는 bank 가 채워진다("tagged"). 이중계상은 *합본 스캔이 개별 회신을 복제*해서
생기므로, 제거 대상은 **untagged 레코드** 뿐이다:

  - tagged 레코드는 **항상 보존**한다. ← 핵심.
    서로 다른 은행의 행이 (계좌·상품·잔액·통화) 우연히 같아도(예: 같은 금액의
    일반자금대출) 둘 다 진짜 개별 회신이므로 절대 병합하지 않는다.
  - untagged 레코드는 동일 content key 를 가진 tagged 레코드가 있으면 제거(합본 복제),
    없으면 보존. untagged 끼리만 중복이면 한 건만 남긴다.

content key = (ac_section, account_no, product, balance, currency)  ← bank/bc_no 제외
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
    # product(예금·유가증권) 또는 contract_type(차입금 AC2) — 둘 다 holding 종류 라벨.
    prod = d.get("product") if d.get("product") not in (None, "") else d.get("contract_type")
    prod = str(prod).strip() if prod not in (None, "") else None
    ccy = d.get("currency")
    ccy = str(ccy).strip() if ccy not in (None, "") else None
    # 계좌번호가 있으면 product 는 키에서 뺀다(합본/개별 간 product 표기 차이 흡수).
    if acct is not None:
        return (ac_section, acct, None, bal, ccy)
    return (ac_section, None, prod, bal, ccy)


def _is_tagged(rec: dict) -> bool:
    """개별 회신본(파일명 메타 보유) = tagged. bank·bc_no 둘 다 비면 합본 스캔(untagged)."""
    return bool((rec.get("bank") or "").strip() or (rec.get("bc_no") or "").strip())


def _content_key(rec: dict) -> tuple | None:
    """레코드의 content key. content 필드는 payload 하위 또는 최상위 어디든 본다."""
    ac = rec.get("ac_section") or rec.get("section") or ""
    payload = rec.get("payload")
    src = payload if isinstance(payload, dict) else rec
    return dedup_key(ac, src)


def dedup_records(records: list) -> list:
    """이중계상 제거 — tagged 는 항상 보존, untagged 중복만 제거.

    규칙
    ----
    1) tagged 레코드(개별 회신본: bank 또는 bc_no 보유)는 **모두 보존**한다.
       서로 다른 은행이 (계좌·상품·잔액·통화) 같아도 진짜 개별 회신이므로 병합 금지.
    2) untagged 레코드(합본 스캔: bank·bc_no 모두 빔)는
         - 동일 content key 를 가진 **tagged** 레코드가 이미 있으면 → 제거(합본 복제).
         - 그런 tagged 가 없고 다른 **untagged** 가 같은 key 면 → 첫 건만 보존.
         - 아무와도 안 겹치면 → 보존.
    content key 가 None(잔액 0/None 등)인 레코드는 dedup 대상 아님 → 항상 보존.
    입력 순서는 보존한다."""
    tagged_keys: set = set()
    for rec in records:
        if _is_tagged(rec):
            k = _content_key(rec)
            if k is not None:
                tagged_keys.add(k)

    out: list = []
    seen_untagged: set = set()
    for rec in records:
        if _is_tagged(rec):
            out.append(rec)            # 규칙1: tagged 무조건 보존
            continue
        k = _content_key(rec)
        if k is None:
            out.append(rec)            # 키 없음(잔액0 등) → 보존
            continue
        if k in tagged_keys:
            continue                   # 규칙2-a: tagged 복제 → 제거
        if k in seen_untagged:
            continue                   # 규칙2-b: untagged 중복 → 첫 건만
        seen_untagged.add(k)
        out.append(rec)
    return out
