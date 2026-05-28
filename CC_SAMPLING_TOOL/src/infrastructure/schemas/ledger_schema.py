"""거래처별 원장 시트명 + 컬럼 자동 감지

설계 원칙:
- 감지 실패 시 None 반환 → UI 수동 매핑 fallback
- 7620 원본 컬럼 순서(코드|명|계정과목|계정과목명|통화|기초|증감|기말)는
  기존 iloc 기반 코드와 완전 호환 (감지 결과가 같은 인덱스를 반환)
- 코스맥스네오 양식: 시트명 = 계정과목명 다중시트. 채권/채무 시트를 all 목록으로 반환.
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

# ── 계정과목명 = 시트명 방식 (다중 시트 통합용) ─────────────────────────
# 채권 계정과목 시트 후보
_RECEIVABLE_ACCOUNT_SHEETS: set[str] = {
    "외상매출금", "받을어음", "미수금", "선급금",
    "단기대여금", "장기대여금", "임차보증금", "기타보증금",
}
# 채무 계정과목 시트 후보
_PAYABLE_ACCOUNT_SHEETS: set[str] = {
    "외상매입금", "지급어음", "미지급금", "선수금",
    "임대보증금", "단기차입금", "장기차입금",
}


def detect_ledger_sheets(sheetnames: list[str]) -> dict[str, Optional[str]]:
    """시트명 목록에서 채권·채무 시트를 자동 감지.

    단일 시트 방식(7620: "채권"/"채무")과
    다중 시트 방식(코스맥스네오: "외상매출금", "외상매입금" 등)을 모두 지원.

    Returns:
        단일 시트 방식: {"receivable": "채권", "payable": "채무"}
        다중 시트 방식: {"receivable": None, "payable": None}
            → detect_multi_account_sheets()를 별도 호출해야 함.
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

    # 부분매칭 fallback (계정과목명 시트 후보는 제외 — 정확매칭만)
    for name in sheetnames:
        normalized = name.strip().lower().replace(" ", "")
        # 계정과목명으로만 구성된 시트는 단일-채권/채무 시트로 오인 방지
        if name.strip() in _RECEIVABLE_ACCOUNT_SHEETS or name.strip() in _PAYABLE_ACCOUNT_SHEETS:
            continue
        if result["receivable"] is None:
            if any(kw.lower() in normalized for kw in _RECEIVABLE_PARTIAL):
                result["receivable"] = name
        if result["payable"] is None:
            if any(kw.lower() in normalized for kw in _PAYABLE_PARTIAL):
                result["payable"] = name

    return result


def detect_multi_account_sheets(sheetnames: list[str]) -> dict[str, list[str]]:
    """계정과목명 = 시트명 방식에서 채권·채무 시트 목록을 반환.

    코스맥스네오 양식처럼 시트별 계정과목이 분리된 경우 사용.
    원장 내 계정과목명(account_name) 은 시트명으로부터 자동 주입.

    Returns:
        {"receivable": ["외상매출금", "받을어음", ...],
         "payable":    ["외상매입금", "지급어음", ...]}
        해당 계정과목 시트가 없으면 빈 리스트.
    """
    result: dict[str, list[str]] = {"receivable": [], "payable": []}
    for name in sheetnames:
        stripped = name.strip()
        if stripped in _RECEIVABLE_ACCOUNT_SHEETS:
            result["receivable"].append(name)
        elif stripped in _PAYABLE_ACCOUNT_SHEETS:
            result["payable"].append(name)
    return result


def is_multi_sheet_ledger(sheetnames: list[str]) -> bool:
    """시트명 목록이 다중 계정과목 시트 방식인지 판단.

    채권·채무 계정과목 시트가 2개 이상 존재하면 다중 시트로 판단.
    """
    multi = detect_multi_account_sheets(sheetnames)
    return len(multi["receivable"]) + len(multi["payable"]) >= 2


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
        # 코스맥스네오 양식: "전기(월)이월" — 괄호 포함 형태 우선 배치
        "전기(월)이월", "전기이월",
        "기초", "기초잔액", "전기말",
        "beginningbalance", "openingbalance", "opening balance", "opening",
        "beginning balance", "beg balance", "beg bal",
    ],
    # ── 신규: 증가/감소 컬럼 (코스맥스네오 양식) ────────────────────────────
    # ISA 505 완전성 검토: 채무 under-statement risk는 당기 증가(매입활동)로 측정.
    "increase":      [
        "증가", "당기증가", "차변누계", "차변합계",
        "debit", "debit total", "increase",
    ],
    "decrease":      [
        "감소", "당기감소", "대변누계", "대변합계",
        "credit", "credit total", "decrease",
    ],
    # ────────────────────────────────────────────────────────────────────────
    "change":        [
        "증감", "증감액", "당기증감",
        "change", "movement", "net change", "net movement",
    ],
    "ending":        [
        # "잔액" 단독을 우선 배치 (코스맥스네오 양식 헤더)
        "잔액", "기말잔액", "기말",  "당기말",
        "endingbalance", "closingbalance", "closing balance", "closing",
        "ending balance", "end balance", "end bal", "balance",
    ],
    # ── 신규: 사업자번호 ─────────────────────────────────────────────────────
    "business_no":   ["사업자번호", "사업자등록번호", "bizno", "business no", "tax id"],
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

    코스맥스네오 호환:
        컬럼 순서 = [코드, 거래처명, 사업자번호, 전기(월)이월, 증가, 감소, 잔액, ...]
        → increase/decrease/business_no 필드가 추가로 감지됨.
        "증가" 컬럼이 존재하면 increase = 해당 인덱스, 없으면 None.
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

    # ── 충돌 해소: "잔액" 컬럼이 "기초잔액"에 오인되지 않도록 ────────────────
    # "ending" 이 "beginning"과 같은 인덱스로 잡히면(예: "기초잔액" 컬럼) 재탐색
    if result["beginning"] is not None and result["ending"] == result["beginning"]:
        result["ending"] = None
        for kw in _COL_KEYWORDS["ending"]:
            kw_norm = kw.lower().replace(" ", "")
            for idx, col in enumerate(cols):
                if idx == result["beginning"]:
                    continue
                if kw_norm == col or kw_norm in col:
                    result["ending"] = idx
                    break
            if result["ending"] is not None:
                break

    return result
