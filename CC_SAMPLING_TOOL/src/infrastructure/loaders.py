"""Excel 로더 — 회사 제시 거래처별 원장, 재무제표, 특관자리스트

loaders.py 는 파일 I/O 담당. 컬럼 감지 로직은 schemas/ 패키지에 위임.
기존 호출처(시트명 직접 지정)는 완전 호환 유지.
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd
import openpyxl

from .schemas.ledger_schema import detect_ledger_sheets, detect_ledger_columns
from .schemas.fs_schema import detect_fs_sheet
from .schemas.rp_schema import detect_rp_sheet


def load_ledger(
    path: str | Path,
    receivable_sheet: str | None = None,
    payable_sheet: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """회사 제시 거래처별 원장 → (채권 df, 채무 df)

    시트명을 지정하지 않으면 detect_ledger_sheets() 로 자동 감지.
    예상 컬럼: 코드 | 명 | 계정과목 | 계정과목명 | 통화 | 기초 | 증감 | 기말
    """
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheets = wb.sheetnames
    wb.close()

    if receivable_sheet is None or payable_sheet is None:
        detected = detect_ledger_sheets(sheets)
        if receivable_sheet is None:
            receivable_sheet = detected.get("receivable") or "채권"
        if payable_sheet is None:
            payable_sheet = detected.get("payable") or "채무"

    ar = pd.read_excel(path, sheet_name=receivable_sheet, header=0)
    ap = pd.read_excel(path, sheet_name=payable_sheet, header=0)
    return ar, ap


def load_ledger_sheet(
    path: str | Path,
    sheet: str,
) -> tuple[pd.DataFrame, dict]:
    """단일 시트 로드 + 컬럼 자동 감지 결과 반환.

    Returns:
        (df, col_map) — col_map 은 detect_ledger_columns() 결과.
    """
    df = pd.read_excel(path, sheet_name=sheet, header=0)
    col_map = detect_ledger_columns(df)
    return df, col_map


def load_related_parties(path: str | Path, sheet: str | None = None) -> set[str]:
    """특관자리스트 → 이름 집합. sheet=None 이면 detect_rp_sheet() 자동 감지."""
    wb = openpyxl.load_workbook(path, data_only=True)

    # 시트명 자동 감지
    if sheet is None:
        sheet = detect_rp_sheet(wb.sheetnames)
    if sheet is None or sheet not in wb.sheetnames:
        # 마지막 fallback: 첫 번째 시트
        sheet = wb.sheetnames[0] if wb.sheetnames else None
    if sheet is None or sheet not in wb.sheetnames:
        return set()

    ws = wb[sheet]
    names: set[str] = set()
    for r in range(1, ws.max_row + 1):
        v = ws.cell(r, 1).value
        if v and isinstance(v, str) and v.strip():
            names.add(v.strip())
    return names


def load_fs_amounts(
    path: str | Path,
    sheet: str | None = None,
    item_col: int | None = None,
    value_col: int | None = None,
) -> dict[str, float]:
    """재무제표(자산·부채) → {계정명: 잔액}

    시트명·컬럼 위치를 지정하지 않으면 자동 감지:
    - 시트명: detect_fs_sheet() — FS_M / BS / 재무상태표 / 재무제표 등
    - 컬럼: 헤더 행 키워드 감지 — 항목·계정명 컬럼 + 금액·잔액 컬럼 (당기 우선)
    - 자동 감지 실패 시 기본값: item_col=3, value_col=5 (7620 호환)
    """
    from .schemas.fs_schema import detect_fs_sheet, detect_fs_columns

    wb = openpyxl.load_workbook(path, data_only=True)

    # 시트 자동 감지
    if sheet is None:
        sheet = detect_fs_sheet(wb.sheetnames) or "FS_M"
    if sheet not in wb.sheetnames:
        return {}

    ws = wb[sheet]

    # 컬럼 자동 감지 — 첫 번째 데이터 행 키워드 기반
    if item_col is None or value_col is None:
        header_vals = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
        detected = detect_fs_columns(wb.sheetnames, header_vals)
        # 당기 금액 우선 (value_col이 여러 개 감지된 경우 마지막 = 당기)
        if item_col is None:
            item_col = detected.get("item_col") or 3
        if value_col is None:
            value_col = detected.get("value_col") or 5

    result: dict[str, float] = {}
    for r in range(1, ws.max_row + 1):
        item = ws.cell(r, item_col).value
        val = ws.cell(r, value_col).value
        if isinstance(item, str) and item.strip() and isinstance(val, (int, float)):
            result[item.strip()] = float(val)
    return result


def get_total_assets(fs_amounts: dict[str, float]) -> float:
    """총자산 추출 — 명칭 변형 대응"""
    for key in ("자산총계", "자산 총계", "총자산"):
        if key in fs_amounts:
            return fs_amounts[key]
    # fallback: 유동자산 + 비유동자산
    유동 = fs_amounts.get("유동자산", 0.0)
    비유동 = fs_amounts.get("비유동자산", 0.0)
    return 유동 + 비유동
