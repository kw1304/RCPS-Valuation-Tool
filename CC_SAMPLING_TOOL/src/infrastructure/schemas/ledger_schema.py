"""거래처별 원장 시트명 + 컬럼 자동 감지

설계 원칙:
- 감지 실패 시 None 반환 → UI 수동 매핑 fallback
- 7620 원본 컬럼 순서(코드|명|계정과목|계정과목명|통화|기초|증감|기말)는
  기존 iloc 기반 코드와 완전 호환 (감지 결과가 같은 인덱스를 반환)
"""
from __future__ import annotations

import re
from typing import Optional

import pandas as pd


# ── 시트명 키워드 (정확매칭 > 부분매칭 우선) ─────────────────────────────
_RECEIVABLE_EXACT = {"채권", "ar", "receivable"}
_RECEIVABLE_PARTIAL = ["채권", "매출", "ar", "receivable", "외상매출", "外상매출"]

_PAYABLE_EXACT = {"채무", "ap", "payable"}
_PAYABLE_PARTIAL = ["채무", "매입", "ap", "payable", "외상매입"]


def detect_ledger_sheets(sheetnames: list[str]) -> dict[str, Optional[str]]:
    """시트명 목록에서 채권·채무 시트를 자동 감지.

    Returns:
        {"receivable": "채권", "payable": "채무"} 형태.
        감지 실패 항목은 None.
    """
    result: dict[str, Optional[str]] = {"receivable": None, "payable": None}

    for name in sheetnames:
        normalized = name.strip().lower().replace(" ", "")

        # 채권 정확매칭
        if result["receivable"] is None and normalized in _RECEIVABLE_EXACT:
            result["receivable"] = name
        # 채무 정확매칭
        if result["payable"] is None and normalized in _PAYABLE_EXACT:
            result["payable"] = name

    # 부분매칭 fallback
    for name in sheetnames:
        normalized = name.strip().lower().replace(" ", "")
        if result["receivable"] is None:
            if any(kw.lower() in normalized for kw in _RECEIVABLE_PARTIAL):
                result["receivable"] = name
        if result["payable"] is None:
            if any(kw.lower() in normalized for kw in _PAYABLE_PARTIAL):
                result["payable"] = name

    return result


# ── 컬럼 키워드 사전 ────────────────────────────────────────────────────────
_COL_KEYWORDS: dict[str, list[str]] = {
    "code_col":      [
        # 한국어 (긴 것 먼저 — 짧은 키워드가 다른 컬럼과 충돌 방지)
        "거래처코드", "고객코드", "공급업체코드",
        # 영문 구체적
        "vendorcode", "customercode", "vendor code", "customer code",
        "party code", "bp code",
        # 짧은 영문 (단독 컬럼명인 경우)
        "code",
        # 한국어 짧은 것 (마지막 fallback)
        "코드",
    ],
    "name_col":      [
        # 한국어 (긴 것 먼저 — "거래처"가 "거래처코드"에 포함되지 않도록 "거래처명" 우선)
        "거래처명", "고객명", "공급업체명",
        # 영문 구체적
        "vendorname", "customername", "vendor name", "customer name",
        "company name", "party name", "bp name",
        # 짧은 영문 (단독 컬럼명인 경우)
        "name",
        # 한국어 단독 약칭 ("명" — 7620 원장 표기)
        "명",
        # 주의: "거래처"는 "거래처코드"에도 포함되므로 등록하지 않음
    ],
    "account_code":  [
        "계정과목코드", "계정코드",
        "accountcode", "gl account code", "account code",
        "gl code", "gl account",
        # "account" 단독은 너무 광범위 — "account name"에도 포함되므로 마지막
        "계정과목", "account",
    ],
    "account_name":  [
        "계정과목명", "계정명",
        "accountname", "gl account name", "account name",
        "account description",
    ],
    "currency":      ["통화", "currency", "ccy", "curr"],
    "beginning":     [
        "기초", "기초잔액", "전기말",
        "beginningbalance", "openingbalance", "opening balance", "opening",
        "beginning balance", "beg balance", "beg bal",
    ],
    "change":        [
        "증감", "증감액", "당기증감",
        "change", "movement", "net change", "net movement",
    ],
    "ending":        [
        "기말", "잔액", "기말잔액", "당기말",
        "endingbalance", "closingbalance", "closing balance", "closing",
        "ending balance", "end balance", "end bal", "balance",
    ],
}


def detect_ledger_columns(df: pd.DataFrame) -> dict[str, Optional[int]]:
    """DataFrame 헤더 행에서 컬럼 인덱스를 키워드 매칭으로 감지.

    Returns:
        {col_key: column_index | None}
        인덱스는 iloc 기준 0-based 정수.

    7620 호환:
        7620 원장 컬럼 순서 = [코드, 명, 계정과목, 계정과목명, 통화, 기초, 증감, 기말]
        → 결과가 {code_col:0, name_col:1, account_code:2, account_name:3,
                  currency:4, beginning:5, change:6, ending:7} 이어야 함.
    """
    result: dict[str, Optional[int]] = {k: None for k in _COL_KEYWORDS}
    cols = [str(c).strip().lower().replace(" ", "") for c in df.columns]

    for field, keywords in _COL_KEYWORDS.items():
        for kw in keywords:
            kw_norm = kw.lower().replace(" ", "")
            for idx, col in enumerate(cols):
                if kw_norm == col or kw_norm in col:
                    if result[field] is None:
                        result[field] = idx
                    break
            if result[field] is not None:
                break

    return result
