"""재무제표 시트명 + 항목·값 컬럼 자동 감지"""
from __future__ import annotations

from typing import Optional


_FS_SHEET_CANDIDATES = [
    "FS_M", "재무상태표", "BS", "Balance Sheet", "재무제표",
    "BalanceSheet", "fs_m",
]


def detect_fs_sheet(sheetnames: list[str]) -> Optional[str]:
    """재무제표 시트명 감지. 우선순위: 정확매칭 → 부분매칭."""
    normalized = {s.strip().lower().replace(" ", ""): s for s in sheetnames}

    for candidate in _FS_SHEET_CANDIDATES:
        key = candidate.lower().replace(" ", "")
        if key in normalized:
            return normalized[key]

    # 부분매칭
    for candidate in _FS_SHEET_CANDIDATES:
        key = candidate.lower().replace(" ", "")
        for norm, orig in normalized.items():
            if key in norm:
                return orig
    return None


def detect_fs_columns(sheetnames: list[str], ws_columns: list) -> dict[str, Optional[int]]:
    """재무제표 시트의 항목명 컬럼과 값 컬럼 인덱스 감지.

    ws_columns: openpyxl 시트 첫 행 셀 값 목록 (1-based 컬럼 인덱스로 반환).
    Returns: {"item_col": int|None, "value_col": int|None}  (1-based)

    당기/기말 우선 전략:
    - value_col 후보가 복수이면 "당기"/"기말" 포함 컬럼 우선 선택
    - 없으면 마지막 값 컬럼 (전기→당기 순 배치에서 당기가 더 오른쪽)
    """
    _ITEM_KW = ["항목", "계정", "item", "account", "과목"]
    _VALUE_KW = ["금액", "잔액", "value", "amount", "balance"]
    _CURRENT_KW = ["당기", "기말", "current", "ending"]

    result: dict[str, Optional[int]] = {"item_col": None, "value_col": None}
    value_candidates: list[int] = []

    for idx, cell_val in enumerate(ws_columns, start=1):
        if cell_val is None:
            continue
        norm = str(cell_val).strip().lower().replace(" ", "")
        if result["item_col"] is None and any(kw in norm for kw in _ITEM_KW):
            result["item_col"] = idx
        if any(kw in norm for kw in _VALUE_KW):
            value_candidates.append(idx)

    if value_candidates:
        # 당기/기말 키워드 포함 컬럼 우선
        for idx in value_candidates:
            cell_val = ws_columns[idx - 1]
            norm = str(cell_val).strip().lower().replace(" ", "") if cell_val else ""
            if any(kw in norm for kw in _CURRENT_KW):
                result["value_col"] = idx
                break
        # 없으면 마지막 값 컬럼 (전기/당기 순 배치에서 당기가 마지막)
        if result["value_col"] is None:
            result["value_col"] = value_candidates[-1]

    return result
