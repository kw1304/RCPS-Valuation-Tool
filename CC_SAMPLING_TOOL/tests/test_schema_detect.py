"""시트명·컬럼 자동 감지 테스트

케이스:
  1. 7620 원본 (시트명: "채권", "채무" / 컬럼 순서: 코드|명|계정과목|계정과목명|통화|기초|증감|기말)
  2. 변형 케이스A — 시트명 "매출채권명세서"/"매입채무명세서", 컬럼 순서 동일
  3. 변형 케이스B — 영문 시트명 "AR"/"AP", 컬럼명 영문 혼용
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
import pytest

from src.infrastructure.schemas.ledger_schema import detect_ledger_sheets, detect_ledger_columns


# ── 시트명 감지 ────────────────────────────────────────────
def test_detect_sheets_standard():
    """7620 원본 시트명 감지."""
    sheets = ["특관자리스트", "채권", "채무", "Sheet3"]
    result = detect_ledger_sheets(sheets)
    assert result["receivable"] == "채권"
    assert result["payable"] == "채무"


def test_detect_sheets_variant_a():
    """변형A: 매출채권명세서 / 매입채무명세서."""
    sheets = ["매출채권명세서", "매입채무명세서"]
    result = detect_ledger_sheets(sheets)
    assert result["receivable"] == "매출채권명세서"
    assert result["payable"] == "매입채무명세서"


def test_detect_sheets_variant_b():
    """변형B: 영문 AR / AP."""
    sheets = ["Summary", "AR", "AP", "Notes"]
    result = detect_ledger_sheets(sheets)
    assert result["receivable"] == "AR"
    assert result["payable"] == "AP"


def test_detect_sheets_not_found():
    """감지 실패 시 None 반환."""
    sheets = ["Sheet1", "Sheet2"]
    result = detect_ledger_sheets(sheets)
    assert result["receivable"] is None
    assert result["payable"] is None


# ── 컬럼 감지 ──────────────────────────────────────────────
def _make_df(columns):
    return pd.DataFrame(columns=columns)


def test_detect_columns_7620():
    """7620 원본 컬럼 순서 → 0~7 인덱스."""
    df = _make_df(["고객코드", "고객명", "계정과목", "계정과목명", "통화", "기초", "증감", "기말"])
    m = detect_ledger_columns(df)
    assert m["code_col"] == 0
    assert m["name_col"] == 1
    assert m["account_code"] == 2
    assert m["account_name"] == 3
    assert m["currency"] == 4
    assert m["beginning"] == 5
    assert m["change"] == 6
    assert m["ending"] == 7


def test_detect_columns_variant_a():
    """변형A: 컬럼명 한국어 변형 (공급업체 / 잔액 등)."""
    df = _make_df(["공급업체코드", "공급업체명", "계정코드", "계정명", "Currency", "기초잔액", "당기증감", "기말잔액"])
    m = detect_ledger_columns(df)
    assert m["code_col"] == 0
    assert m["name_col"] == 1
    assert m["ending"] == 7


def test_detect_columns_partial_fail():
    """일부 컬럼 미감지 시 None."""
    df = _make_df(["X", "Y", "Z"])
    m = detect_ledger_columns(df)
    # 전부 None
    assert all(v is None for v in m.values())
